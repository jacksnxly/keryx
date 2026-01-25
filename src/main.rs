//! keryx - CLI entry point.

use std::path::PathBuf;

use anyhow::{Context, Result};
use clap::Parser;
use git2::Repository;
use semver::Version;

use keryx::changelog::{write_changelog, writer::generate_summary};
use keryx::claude::{build_prompt, check_claude_installed, generate_with_retry, prompt::ChangelogInput};
use keryx::git::{commits::fetch_commits, range::resolve_range, tags::get_latest_tag};
use keryx::github::{auth::get_github_token, prs::{fetch_merged_prs, parse_github_remote}};
use keryx::version::calculate_next_version;

/// Generate release notes from commits and PRs using Claude.
#[derive(Parser, Debug)]
#[command(name = "keryx")]
#[command(about = "Generate release notes from commits and PRs using Claude")]
#[command(version)]
struct Cli {
    /// Explicit version to use (overrides auto-detection)
    #[arg(long = "set-version")]
    version: Option<Version>,

    /// Start of commit range (tag, commit hash, or branch)
    #[arg(long)]
    from: Option<String>,

    /// End of commit range (defaults to HEAD)
    #[arg(long, default_value = "HEAD")]
    to: String,

    /// Path to changelog file
    #[arg(short = 'o', long, default_value = "CHANGELOG.md")]
    output: PathBuf,

    /// Skip GitHub PR fetching
    #[arg(long)]
    no_prs: bool,

    /// Dry run - print changelog without writing
    #[arg(long)]
    dry_run: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    // Step 1: Check prerequisites
    check_claude_installed()
        .await
        .context("Claude Code CLI is required")?;

    // Step 2: Open git repository
    let repo = Repository::open(".")
        .context("Not a git repository. Run keryx from within a git repository.")?;

    // Step 3: Resolve commit range
    let range = resolve_range(&repo, cli.from.as_deref(), Some(&cli.to))
        .context("Failed to resolve commit range")?;

    println!(
        "Analyzing commits from {} to {}...",
        range.from_ref, range.to_ref
    );

    // Step 4: Fetch commits
    let commits = fetch_commits(&repo, range.from, range.to)
        .context("Failed to fetch commits")?;

    if commits.is_empty() {
        println!(
            "No changes found since {}. Nothing to add.",
            range.from_ref
        );
        return Ok(());
    }

    println!("Found {} commits", commits.len());

    // Step 5: Fetch PRs (if not disabled)
    let pull_requests = if cli.no_prs {
        Vec::new()
    } else {
        match fetch_prs_for_repo(&repo).await {
            Ok(prs) => {
                println!("Found {} merged PRs", prs.len());
                prs
            }
            Err(e) => {
                eprintln!("Warning: Could not fetch PRs: {}. Continuing with commits only.", e);
                Vec::new()
            }
        }
    };

    // Step 6: Determine version
    let base_version = get_latest_tag(&repo)?.and_then(|t| t.version);
    let next_version = cli.version.unwrap_or_else(|| {
        calculate_next_version(base_version.as_ref(), &commits)
    });

    println!("Version: {} -> {}",
        base_version.as_ref().map(|v| v.to_string()).unwrap_or_else(|| "none".to_string()),
        next_version
    );

    // Step 7: Build prompt and call Claude
    let repo_name = get_repo_name(&repo).unwrap_or_else(|| "repository".to_string());
    let is_initial_release = base_version.is_none();

    // For initial releases, gather extra context
    let (project_description, cli_features) = if is_initial_release {
        (
            read_cargo_description(),
            Some(get_cli_features()),
        )
    } else {
        (None, None)
    };

    let input = ChangelogInput {
        commits,
        pull_requests,
        previous_version: base_version.map(|v| v.to_string()),
        repository_name: repo_name,
        project_description,
        cli_features,
    };

    let prompt = build_prompt(&input);

    println!("Generating release notes with Claude...");

    let changelog_output = generate_with_retry(&prompt)
        .await
        .context("Failed to generate changelog entries")?;

    if changelog_output.entries.is_empty() {
        println!("No changelog entries generated. Nothing to add.");
        return Ok(());
    }

    // Step 8: Write or display changelog
    if cli.dry_run {
        println!("\n--- Dry Run Output ---\n");
        print_changelog_preview(&changelog_output, &next_version);
    } else {
        write_changelog(&cli.output, &changelog_output, &next_version)
            .context("Failed to write changelog")?;

        let summary = generate_summary(&changelog_output);
        println!("✓ {}", summary);
    }

    Ok(())
}

/// Fetch PRs for the current repository.
async fn fetch_prs_for_repo(repo: &Repository) -> Result<Vec<keryx::PullRequest>> {
    // Get GitHub token
    let token = get_github_token()
        .context("GitHub authentication required for PR fetching")?;

    // Get remote URL
    let remote = repo.find_remote("origin")
        .context("No 'origin' remote found")?;

    let url = remote.url()
        .context("Remote has no URL")?;

    let (owner, repo_name) = parse_github_remote(url)
        .context("Could not parse GitHub remote URL")?;

    // Fetch PRs (no date filter for now, we'll filter by commits later)
    let prs = fetch_merged_prs(&token, &owner, &repo_name, None, None).await?;

    Ok(prs)
}

/// Get the repository name from the remote URL.
fn get_repo_name(repo: &Repository) -> Option<String> {
    let remote = repo.find_remote("origin").ok()?;
    let url = remote.url()?;
    let (_, name) = parse_github_remote(url).ok()?;
    Some(name)
}

/// Print a preview of the changelog output.
fn print_changelog_preview(output: &keryx::ChangelogOutput, version: &Version) {
    use chrono::Utc;

    let today = Utc::now().format("%Y-%m-%d");
    println!("## [{}] - {}\n", version, today);

    for (category, entries) in output.entries_by_category() {
        println!("### {}\n", category.as_str());
        for entry in entries {
            println!("- {}", entry.description);
        }
        println!();
    }
}

/// Read project description from Cargo.toml.
fn read_cargo_description() -> Option<String> {
    let content = std::fs::read_to_string("Cargo.toml").ok()?;

    // Simple parsing - look for description = "..."
    for line in content.lines() {
        let line = line.trim();
        if line.starts_with("description") {
            if let Some(start) = line.find('"') {
                if let Some(end) = line.rfind('"') {
                    if end > start {
                        return Some(line[start + 1..end].to_string());
                    }
                }
            }
        }
    }
    None
}

/// Get CLI features for context.
fn get_cli_features() -> Vec<String> {
    vec![
        "--set-version <VERSION>: Override auto-detected version".to_string(),
        "--from <REF>: Start of commit range (tag, hash, or branch)".to_string(),
        "--to <REF>: End of commit range (default: HEAD)".to_string(),
        "-o, --output <PATH>: Changelog output path (default: CHANGELOG.md)".to_string(),
        "--no-prs: Skip GitHub PR fetching, use commits only".to_string(),
        "--dry-run: Preview without writing to file".to_string(),
        "GitHub auth: Supports gh CLI, GITHUB_TOKEN, and GH_TOKEN".to_string(),
        "Automatic backup: Creates .changelog.md.bak before modifying".to_string(),
        "Handles [Unreleased] sections per Keep a Changelog spec".to_string(),
    ]
}
