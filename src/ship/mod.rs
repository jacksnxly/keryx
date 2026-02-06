//! Ship pipeline: automate the full release flow.
//!
//! Orchestrates preflight checks, version calculation, version file updates,
//! changelog generation, and git commit/tag/push.

pub mod executor;
pub mod preflight;
pub mod version_files;

use std::path::{Path, PathBuf};

use dialoguer::Confirm;
use git2::Repository;
use semver::Version;
use tracing::debug;

use crate::changelog::parser::read_changelog;
use crate::changelog::write_changelog;
use crate::error::ShipError;
use crate::llm::{
    ChangelogInput, LlmRouter, ProviderSelection, build_prompt, build_verification_prompt,
};
use crate::verification::{check_ripgrep_installed, gather_verification_evidence};
use crate::version::{VersionBumpInput, calculate_next_version, calculate_next_version_with_llm};

use self::preflight::{check_tag_exists, run_checks};
use self::version_files::{detect_version_files, update_version_file};

/// Configuration for the ship command, derived from CLI flags.
pub struct ShipConfig {
    pub set_version: Option<Version>,
    pub dry_run: bool,
    pub no_llm_bump: bool,
    pub no_prs: bool,
    pub verbose: bool,
    pub no_verify: bool,
    pub output: PathBuf,
    pub provider_selection: ProviderSelection,
}

/// Run the full ship pipeline.
pub async fn run_ship(config: ShipConfig) -> Result<(), ShipError> {
    let repo = Repository::open(".")
        .map_err(|e| ShipError::GitFailed(format!("Not a git repository: {}", e)))?;

    // ── Stage 1: Preflight checks ──
    println!("Preflight checks:");

    let preflight = run_checks(
        &repo,
        config.no_llm_bump,
        config.provider_selection,
        config.verbose,
    )?;

    let tag_display = preflight
        .latest_tag
        .as_ref()
        .map(|t| t.name.as_str())
        .unwrap_or("(none)");

    println!("  [PASS] Working tree is clean");
    println!("  [PASS] Local branch is up to date with remote");
    println!(
        "  [PASS] {} commits since {}",
        preflight.commits_since_tag.len(),
        tag_display
    );

    if !config.no_llm_bump {
        if preflight.llm_available {
            println!("  [PASS] LLM provider available");
        } else {
            println!("  [WARN] LLM provider not available, using algorithmic versioning");
        }
    }

    println!();

    // ── Stage 2: Version calculation ──
    let mut llm = LlmRouter::new(config.provider_selection);

    let (next_version, bump_reasoning) = if let Some(ref explicit) = config.set_version {
        (explicit.clone(), None)
    } else if config.no_llm_bump || !preflight.llm_available {
        (
            calculate_next_version(
                preflight.base_version.as_ref(),
                &preflight.commits_since_tag,
            ),
            None,
        )
    } else {
        let bump_input = VersionBumpInput {
            commits: &preflight.commits_since_tag,
            pull_requests: &[], // PRs are optional for version bump
            previous_version: preflight.base_version.as_ref(),
            repository_name: &get_repo_name(&repo),
        };
        calculate_next_version_with_llm(&bump_input, &mut llm, config.verbose).await
    };

    println!(
        "Version: {} -> {}{}",
        preflight
            .base_version
            .as_ref()
            .map(|v| v.to_string())
            .unwrap_or_else(|| "none".to_string()),
        next_version,
        bump_reasoning
            .as_ref()
            .map(|r| format!(" ({})", r))
            .unwrap_or_default()
    );

    // ── Stage 3: Tag collision check ──
    let tag_name = format!("v{}", next_version);
    if check_tag_exists(&repo, &tag_name)? {
        let suggested = find_next_available_version(&repo, &next_version)?;
        let suggested_tag = format!("v{}", suggested);

        println!();
        let use_suggested = Confirm::new()
            .with_prompt(format!(
                "{} already exists. Did you mean {}?",
                tag_name, suggested
            ))
            .default(true)
            .interact()
            .map_err(|_| ShipError::Cancelled)?;

        if !use_suggested {
            return Err(ShipError::TagAlreadyExists(tag_name));
        }

        // Use the suggested version instead
        return run_ship_with_version(
            config,
            &repo,
            &mut llm,
            &preflight,
            suggested,
            suggested_tag,
        )
        .await;
    }

    run_ship_with_version(config, &repo, &mut llm, &preflight, next_version, tag_name).await
}

/// Continue the ship pipeline with a resolved version.
async fn run_ship_with_version(
    config: ShipConfig,
    repo: &Repository,
    llm: &mut LlmRouter,
    preflight: &preflight::PreflightResult,
    next_version: Version,
    tag_name: String,
) -> Result<(), ShipError> {
    let workdir = repo
        .workdir()
        .ok_or_else(|| ShipError::GitFailed("Bare repository not supported".into()))?;

    // ── Stage 4: Version file detection and update ──
    let version_files = detect_version_files(workdir)?;

    println!();
    println!("Version files:");
    for vf in &version_files {
        println!(
            "  [UPDATE] {}: {} -> {}",
            vf.kind, vf.current_version, next_version
        );
    }

    // ── Stage 5: Changelog check/generation ──
    let output_path = resolve_changelog_path(workdir, &config.output);
    let changelog_path = if is_default_changelog_output(&config.output) {
        detect_changelog_path(workdir).unwrap_or_else(|| output_path.clone())
    } else {
        output_path.clone()
    };

    let parsed_changelog = read_changelog(&changelog_path)?;
    let changelog_exists_for_version = parsed_changelog
        .as_ref()
        .map(|parsed| parsed.has_version(&next_version))
        .unwrap_or(false);

    let changelog_generated = if changelog_exists_for_version {
        println!();
        println!(
            "  [SKIP] Changelog section for {} already exists",
            next_version
        );
        false
    } else {
        println!();
        println!("  [CREATE] Changelog section for {}", next_version);
        true
    };

    if changelog_generated && !preflight.llm_available && !config.dry_run {
        let provider = config.provider_selection.primary;
        return Err(ShipError::LlmUnavailable(format!(
            "{} CLI not available. Install/configure the provider or add the changelog section manually.",
            provider
        )));
    }

    // ── Stage 6: Confirmation prompt ──
    let effective_changelog_path = changelog_path.clone();

    println!();
    println!("Summary:");
    println!(
        "  Version:   {} -> {}",
        preflight
            .base_version
            .as_ref()
            .map(|v| v.to_string())
            .unwrap_or_else(|| "none".to_string()),
        next_version
    );
    println!(
        "  Changelog: {}",
        if changelog_generated {
            format!(
                "Auto-generated ({} commits)",
                preflight.commits_since_tag.len()
            )
        } else {
            "Existing section (skip)".to_string()
        }
    );
    println!("  Commit:    chore(release): v{}", next_version);
    println!("  Tag:       {}", tag_name);
    println!(
        "  Push to:   {}/{}",
        preflight.remote_name, preflight.upstream_branch
    );

    if config.dry_run {
        println!();
        println!("Dry run complete. No changes made.");
        return Ok(());
    }

    println!();
    let confirmed = Confirm::new()
        .with_prompt("Proceed?")
        .default(true)
        .interact()
        .map_err(|_| ShipError::Cancelled)?;

    if !confirmed {
        return Err(ShipError::Cancelled);
    }

    // ── Stage 7: Execute ──
    // 7a. Update version files
    for vf in &version_files {
        update_version_file(vf, &next_version)?;
        println!("  [DONE] Updated {}", vf.kind);
    }

    // 7b. Generate and write changelog (if needed)
    if changelog_generated {
        generate_and_write_changelog(
            repo,
            llm,
            &preflight.commits_since_tag,
            &next_version,
            preflight.base_version.as_ref(),
            &effective_changelog_path,
            config.no_prs,
            config.no_verify,
            config.verbose,
        )
        .await?;
        println!("  [DONE] Updated CHANGELOG.md");
    }

    // 7c. Collect files to stage
    let mut files_to_stage: Vec<PathBuf> = version_files.iter().map(|vf| vf.path.clone()).collect();
    if changelog_generated {
        files_to_stage.push(effective_changelog_path);
    }

    // 7d. Commit, tag, push
    let commit_message = format!("chore(release): v{}", next_version);
    let commit_result = executor::commit_and_tag(&commit_message, &tag_name, &files_to_stage)?;

    if commit_result.commit_created {
        println!("  [DONE] Created commit: {}", commit_message);
    } else {
        println!("  [SKIP] No changes to commit; using current HEAD");
    }
    println!("  [DONE] Created tag: {}", tag_name);

    match executor::push_with_tags(&preflight.remote_name, &preflight.upstream_branch) {
        Ok(()) => {
            println!(
                "  [DONE] Pushed to {}/{}",
                preflight.remote_name, preflight.upstream_branch
            );
            println!();
            println!("Release {} shipped!", tag_name);
        }
        Err(e) => {
            // ── Stage 8: Rollback on push failure ──
            eprintln!("  [FAIL] {}", e);
            eprintln!();
            eprintln!("Rolling back...");

            match executor::rollback(&tag_name, commit_result.commit_created) {
                Ok(()) => {
                    eprintln!("  [DONE] Deleted tag {}", tag_name);
                    if commit_result.commit_created {
                        eprintln!("  [DONE] Reset commit {}", commit_message);
                    }
                    eprintln!();
                    eprintln!("Release aborted. Fix the push issue and try again.");
                }
                Err(rollback_err) => {
                    eprintln!("  [FAIL] Rollback failed: {}", rollback_err);
                    eprintln!();
                    if commit_result.commit_created {
                        eprintln!(
                            "Manual cleanup may be needed: git tag -d {} && git reset --soft HEAD~1",
                            tag_name
                        );
                    } else {
                        eprintln!("Manual cleanup may be needed: git tag -d {}", tag_name);
                    }
                }
            }

            return Err(e);
        }
    }

    Ok(())
}

/// Generate changelog entries and write them to the changelog file.
#[allow(clippy::too_many_arguments)]
async fn generate_and_write_changelog(
    repo: &Repository,
    llm: &mut LlmRouter,
    commits: &[crate::git::ParsedCommit],
    version: &Version,
    base_version: Option<&Version>,
    output_path: &std::path::Path,
    no_prs: bool,
    no_verify: bool,
    verbose: bool,
) -> Result<(), ShipError> {
    // Fetch PRs if not disabled
    let pull_requests = if no_prs {
        Vec::new()
    } else {
        match fetch_prs(repo).await {
            Ok(prs) => {
                if verbose {
                    debug!("Found {} merged PRs for changelog", prs.len());
                }
                prs
            }
            Err(e) => {
                if verbose {
                    debug!("Failed to fetch PRs for changelog: {}", e);
                }
                Vec::new()
            }
        }
    };

    let repo_name = get_repo_name(repo);
    let input = ChangelogInput {
        commits: commits.to_vec(),
        pull_requests,
        previous_version: base_version.cloned(),
        repository_name: repo_name,
        project_description: None,
        cli_features: None,
    };

    let prompt = build_prompt(&input).map_err(|e| {
        ShipError::Changelog(crate::error::ChangelogError::ParseFailed(format!(
            "Failed to build LLM prompt: {}",
            e
        )))
    })?;

    println!("  Generating changelog...");

    let completion = llm.generate(&prompt).await.map_err(|e| {
        ShipError::Changelog(crate::error::ChangelogError::ParseFailed(format!(
            "LLM generation failed: {}",
            e.summary()
        )))
    })?;

    let mut changelog_output = completion.output;

    if changelog_output.entries.is_empty() {
        debug!("No changelog entries generated");
        return Err(ShipError::Changelog(
            crate::error::ChangelogError::EmptyOutput,
        ));
    }

    if !no_verify {
        let repo_path = repo.workdir().ok_or_else(|| {
            ShipError::GitFailed(
                "Cannot verify in a bare repository. Use --no-verify to skip verification.".into(),
            )
        })?;

        check_ripgrep_installed()?;

        println!("  Verifying changelog entries...");

        let evidence = gather_verification_evidence(&changelog_output.entries, repo_path);
        let draft_json = serde_json::to_string_pretty(&changelog_output).map_err(|e| {
            ShipError::VerificationFailed(format!("Failed to serialize draft entries: {}", e))
        })?;
        let verification_prompt =
            build_verification_prompt(&draft_json, &evidence).map_err(|e| {
                ShipError::VerificationFailed(format!("Failed to build verification prompt: {}", e))
            })?;

        let verified_completion = llm.generate(&verification_prompt).await.map_err(|e| {
            ShipError::VerificationFailed(format!("LLM verification failed: {}", e.summary()))
        })?;

        changelog_output = verified_completion.output;

        if changelog_output.entries.is_empty() {
            debug!("No changelog entries remained after verification");
            return Err(ShipError::Changelog(
                crate::error::ChangelogError::EmptyOutput,
            ));
        }
    }

    write_changelog(output_path, &changelog_output, version)?;

    Ok(())
}

/// Fetch PRs for changelog generation (best-effort).
async fn fetch_prs(repo: &Repository) -> Result<Vec<crate::github::PullRequest>, anyhow::Error> {
    use crate::github::auth::get_github_token;
    use crate::github::prs::{fetch_merged_prs, parse_github_remote};

    let token = get_github_token().await?;
    let remote = repo.find_remote("origin")?;
    let url = remote
        .url()
        .ok_or_else(|| anyhow::anyhow!("No remote URL"))?;
    let (owner, repo_name) = parse_github_remote(url)?;
    let prs = fetch_merged_prs(&token, &owner, &repo_name, None, None, None).await?;
    Ok(prs)
}

/// Detect the changelog file path from common names.
fn detect_changelog_path(root: &std::path::Path) -> Option<PathBuf> {
    let candidates = ["CHANGELOG.md", "CHANGES.md", "HISTORY.md"];
    for name in &candidates {
        let path = root.join(name);
        if path.exists() {
            return Some(path);
        }
    }
    None
}

fn resolve_changelog_path(root: &Path, output: &Path) -> PathBuf {
    if output.is_absolute() {
        output.to_path_buf()
    } else {
        root.join(output)
    }
}

fn is_default_changelog_output(output: &Path) -> bool {
    output == Path::new("CHANGELOG.md")
}

/// Get the repository name from the remote URL.
fn get_repo_name(repo: &Repository) -> String {
    use crate::github::prs::parse_github_remote;

    repo.find_remote("origin")
        .ok()
        .and_then(|r| r.url().map(String::from))
        .and_then(|url| parse_github_remote(&url).ok())
        .map(|(_, name)| name)
        .unwrap_or_else(|| "repository".to_string())
}

/// Suggest the next patch version when a tag collision is detected.
fn suggest_next_version(version: &Version) -> Version {
    Version::new(version.major, version.minor, version.patch + 1)
}

/// Find the next available patch version by skipping existing tags.
fn find_next_available_version(repo: &Repository, version: &Version) -> Result<Version, ShipError> {
    let mut candidate = suggest_next_version(version);
    for _ in 0..1000 {
        let tag_name = format!("v{}", candidate);
        if !check_tag_exists(repo, &tag_name)? {
            return Ok(candidate);
        }
        candidate = suggest_next_version(&candidate);
    }

    Err(ShipError::GitFailed(
        "Failed to find an available tag after 1000 attempts".into(),
    ))
}
