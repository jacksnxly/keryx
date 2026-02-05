//! keryx - CLI entry point.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::thread::JoinHandle;

use anyhow::{Context, Result, bail};
use clap::{CommandFactory, Parser, Subcommand, ValueEnum};
use git2::Repository;
use semver::Version;
use tokio::process::Command;
use tracing::{Level, debug, warn};
use tracing_subscriber::FmtSubscriber;

use keryx::changelog::format::CHANGELOG_HEADER;
use keryx::changelog::{parser::read_changelog, write_changelog, writer::generate_summary};
use keryx::commit::{
    ChangedFile, DiffSummary, SPLIT_ANALYSIS_THRESHOLD, analyze_split, collect_diff,
    collect_diff_for_paths, generate_commit_message, stage_and_commit, stage_paths_and_commit,
};
use keryx::git::{
    commits::fetch_commits,
    range::{find_root_commit, resolve_range},
    tags::{get_all_tags, get_latest_tag},
};
use keryx::github::{
    auth::get_github_token,
    prs::{fetch_merged_prs, parse_github_remote},
};
use keryx::llm::{
    ChangelogInput, LlmCompletion, LlmError, LlmProviderError, LlmRouter, Provider,
    ProviderSelection, build_prompt, build_verification_prompt,
};
use keryx::verification::{check_ripgrep_installed, gather_verification_evidence};
use keryx::version::{VersionBumpInput, calculate_next_version, calculate_next_version_with_llm};

/// Result from the background update check.
struct UpdateResult {
    /// Whether an update is available.
    update_available: bool,
}

/// Handles background update checking without output interleaving.
///
/// Spawns a thread to check for updates and provides a method to
/// display the notification at a controlled time (end of program).
struct UpdateChecker {
    /// Receiver for update check result.
    receiver: Receiver<UpdateResult>,
    /// Thread handle (kept to prevent detachment).
    _handle: JoinHandle<()>,
}

impl UpdateChecker {
    /// Start the background update check.
    ///
    /// Spawns a thread that checks for updates and sends the result
    /// through a channel. The check is non-blocking from the caller's
    /// perspective.
    fn start(verbose: bool) -> Self {
        let (sender, receiver) = mpsc::channel();

        let handle = std::thread::spawn(move || {
            let result = match check_for_update() {
                Ok(update_available) => UpdateResult { update_available },
                Err(e) => {
                    if verbose {
                        // Provide actionable error messages based on error content
                        let error_str = e.to_string().to_lowercase();
                        if error_str.contains("network")
                            || error_str.contains("connection")
                            || error_str.contains("dns")
                        {
                            warn!(
                                "Update check failed (network error): {}. Check your internet connection.",
                                e
                            );
                        } else if error_str.contains("parse") || error_str.contains("version") {
                            warn!(
                                "Update check failed (version parse error): {}. This may indicate a corrupted install.",
                                e
                            );
                        } else if error_str.contains("not found") || error_str.contains("404") {
                            warn!(
                                "Update check failed (release not found): {}. No releases may be available yet.",
                                e
                            );
                        } else {
                            warn!(
                                "Update check failed: {}. Run with --verbose for more details.",
                                e
                            );
                        }
                    }
                    UpdateResult {
                        update_available: false,
                    }
                }
            };

            // Send result to main thread
            if sender.send(result).is_err() {
                // Receiver was dropped - main thread exited early, this is expected
                debug!("Update check completed but main thread already exited");
            }
        });

        UpdateChecker {
            receiver,
            _handle: handle,
        }
    }

    /// Print update notification if an update is available.
    ///
    /// Uses non-blocking try_recv() to check if the update check has
    /// completed. If an update is available, prints the notification.
    /// Logs a warning if the update thread terminated unexpectedly.
    fn maybe_notify(&self) {
        match self.receiver.try_recv() {
            Ok(result) if result.update_available => {
                print_update_notification();
            }
            Ok(_) => {
                // No update available - this is normal
            }
            Err(TryRecvError::Empty) => {
                // Update check not finished yet - this is expected for quick commands
            }
            Err(TryRecvError::Disconnected) => {
                // Thread terminated unexpectedly (panic or other failure)
                warn!("Update checker thread terminated unexpectedly. This may indicate a bug.");
            }
        }
    }
}

/// Generate release notes from commits and PRs using Claude or Codex.
#[derive(Parser, Debug)]
#[command(name = "keryx")]
#[command(about = "Generate release notes from commits and PRs using Claude or Codex")]
#[command(version)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,

    /// Explicit version to use (overrides auto-detection)
    #[arg(long = "set-version", global = true)]
    set_version: Option<Version>,

    /// Start of commit range (tag, commit hash, or branch)
    #[arg(long, global = true)]
    from: Option<String>,

    /// End of commit range (defaults to HEAD)
    #[arg(long, default_value = "HEAD", global = true)]
    to: String,

    /// Path to changelog file
    #[arg(short = 'o', long, default_value = "CHANGELOG.md", global = true)]
    output: PathBuf,

    /// Skip GitHub PR fetching
    #[arg(long, global = true)]
    no_prs: bool,

    /// Maximum number of PRs to fetch (default: 100, env: KERYX_PR_LIMIT)
    #[arg(short = 'l', long, global = true)]
    pr_limit: Option<usize>,

    /// Dry run - print changelog without writing
    #[arg(long, global = true)]
    dry_run: bool,

    /// Strict mode - fail on any errors instead of graceful degradation
    #[arg(long, global = true)]
    strict: bool,

    /// Force overwrite if version already exists in changelog
    #[arg(long, global = true)]
    force: bool,

    /// Enable verbose/debug logging
    #[arg(short, long, global = true)]
    verbose: bool,

    /// Skip verification pass (faster but may include inaccuracies)
    #[arg(long, global = true)]
    no_verify: bool,

    /// Skip LLM-based version bump (use algorithmic bump from commit types)
    #[arg(long, global = true)]
    no_llm_bump: bool,

    /// LLM provider to use (fallback will be attempted on failure)
    #[arg(long, value_enum, global = true)]
    provider: Option<ProviderFlag>,
}

#[derive(Debug, Clone, ValueEnum)]
enum ProviderFlag {
    Claude,
    Codex,
}

impl From<ProviderFlag> for Provider {
    fn from(value: ProviderFlag) -> Self {
        match value {
            ProviderFlag::Claude => Provider::Claude,
            ProviderFlag::Codex => Provider::Codex,
        }
    }
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Update keryx to the latest version
    Update,

    /// Initialize a new changelog file
    Init {
        /// Generate entries from all commits and put in [Unreleased] section
        #[arg(long, conflicts_with = "from_history")]
        unreleased: bool,

        /// Generate entries for each existing git tag (full history)
        #[arg(long, conflicts_with = "unreleased")]
        from_history: bool,
    },

    /// Generate a commit message from staged/unstaged changes using AI
    Commit {
        /// Print the generated message to stdout without committing
        #[arg(long)]
        message_only: bool,

        /// Skip split analysis, always create a single commit
        #[arg(long)]
        no_split: bool,
    },

    /// Generate a commit message and push the commit to the remote
    Push {
        /// Print the generated message to stdout without committing
        #[arg(long)]
        message_only: bool,

        /// Skip split analysis, always create a single commit
        #[arg(long)]
        no_split: bool,
    },

    /// Create a release: bump version, update changelog, tag, and push
    Ship,
}

/// Configuration for the commit command.
struct CommitConfig {
    /// Print the generated message to stdout without committing.
    message_only: bool,
    /// Preview without actually creating commits.
    dry_run: bool,
    /// Enable verbose/debug logging.
    verbose: bool,
}

/// Result of running the commit flow.
enum CommitOutcome {
    /// No commit was created (message-only or dry run).
    NoCommit,
    /// One or more commits were created.
    Committed(Vec<git2::Oid>),
}

/// Configuration for init commands, avoiding too_many_arguments clippy warning.
struct InitConfig {
    /// Path to output changelog file.
    output: PathBuf,
    /// Preview without writing to file.
    dry_run: bool,
    /// Skip GitHub PR fetching.
    no_prs: bool,
    /// Fail on any errors instead of graceful degradation.
    strict: bool,
    /// Maximum number of PRs to fetch.
    pr_limit: Option<usize>,
    /// Skip verification pass.
    no_verify: bool,
    /// Enable verbose/debug logging.
    verbose: bool,
    /// LLM provider selection.
    provider_selection: ProviderSelection,
}

impl InitConfig {
    /// Create an `InitConfig` from the CLI arguments.
    fn from_cli(cli: &Cli) -> Self {
        let provider_selection = cli
            .provider
            .clone()
            .map(Provider::from)
            .map(ProviderSelection::from_primary)
            .unwrap_or_default();

        Self {
            output: cli.output.clone(),
            dry_run: cli.dry_run,
            no_prs: cli.no_prs,
            strict: cli.strict,
            pr_limit: cli.pr_limit,
            no_verify: cli.no_verify,
            verbose: cli.verbose,
            provider_selection,
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    // Initialize tracing subscriber for logging
    let log_level = if cli.verbose {
        Level::DEBUG
    } else {
        Level::WARN
    };
    let subscriber = FmtSubscriber::builder()
        .with_max_level(log_level)
        .with_writer(std::io::stderr)
        .without_time()
        .finish();
    tracing::subscriber::set_global_default(subscriber).expect("Failed to set tracing subscriber");

    // Start background update check (non-blocking)
    let update_checker = UpdateChecker::start(cli.verbose);

    // Run the requested command
    let result = match cli.command {
        Some(Commands::Update) => run_update().await,
        Some(Commands::Init {
            unreleased,
            from_history,
        }) => {
            let config = InitConfig::from_cli(&cli);
            run_init(&config, unreleased, from_history).await
        }
        Some(Commands::Commit {
            message_only,
            no_split,
        }) => {
            let config = CommitConfig {
                message_only,
                dry_run: cli.dry_run,
                verbose: cli.verbose,
            };
            run_commit(&config, no_split, cli.provider)
                .await
                .map(|_| ())
        }
        Some(Commands::Push {
            message_only,
            no_split,
        }) => {
            let config = CommitConfig {
                message_only,
                dry_run: cli.dry_run,
                verbose: cli.verbose,
            };
            run_push(&config, no_split, cli.provider).await
        }
        Some(Commands::Ship) => {
            let provider_selection = cli
                .provider
                .clone()
                .map(Provider::from)
                .map(ProviderSelection::from_primary)
                .unwrap_or_default();

            let ship_config = keryx::ship::ShipConfig {
                set_version: cli.set_version.clone(),
                dry_run: cli.dry_run,
                no_llm_bump: cli.no_llm_bump,
                no_prs: cli.no_prs,
                verbose: cli.verbose,
                no_verify: cli.no_verify,
                output: cli.output.clone(),
                provider_selection,
            };
            keryx::ship::run_ship(ship_config)
                .await
                .map_err(|e| anyhow::anyhow!("{}", e))
        }
        None => run_generate(cli).await,
    };

    // Print update notification at the very end (if available)
    // This prevents output interleaving with main program output
    update_checker.maybe_notify();

    result
}

/// Check if an update is available (without printing).
///
/// Returns true if a newer version is available, false otherwise.
fn check_for_update() -> Result<bool, Box<dyn std::error::Error + Send + Sync>> {
    use axoupdater::{AxoUpdater, Version};

    let current_version: Version = env!("CARGO_PKG_VERSION").parse()?;

    let mut updater = AxoUpdater::new_for("keryx");
    updater.set_current_version(current_version)?;

    Ok(updater.is_update_needed_sync()?)
}

/// Print the update notification banner to stderr.
fn print_update_notification() {
    eprintln!();
    eprintln!("\x1b[33m╭───────────────────────────────────────────────╮\x1b[0m");
    eprintln!("\x1b[33m│\x1b[0m  A new version of keryx is available!        \x1b[33m│\x1b[0m");
    eprintln!(
        "\x1b[33m│\x1b[0m  Run \x1b[36mkeryx update\x1b[0m to upgrade                 \x1b[33m│\x1b[0m"
    );
    eprintln!("\x1b[33m╰───────────────────────────────────────────────╯\x1b[0m");
    eprintln!();
}

/// Run the self-update command.
async fn run_update() -> Result<()> {
    use axoupdater::{AxoUpdater, Version};

    println!("Checking for updates...");

    let current_version: Version = env!("CARGO_PKG_VERSION")
        .parse()
        .context("Failed to parse current version")?;

    let mut updater = AxoUpdater::new_for("keryx");
    updater.set_current_version(current_version)?;

    // Enable output from the installer
    updater.enable_installer_output();

    // Use async version since we're in a tokio runtime
    match updater.run().await {
        Ok(Some(result)) => {
            println!(
                "\n\x1b[32m✓ Successfully updated keryx to v{}\x1b[0m",
                result.new_version
            );
        }
        Ok(None) => {
            println!(
                "keryx is already up to date (v{})",
                env!("CARGO_PKG_VERSION")
            );
        }
        Err(e) => {
            eprintln!("\x1b[31mFailed to update: {}\x1b[0m", e);
            eprintln!("\nYou can manually update by running:");
            eprintln!(
                "  curl --proto '=https' --tlsv1.2 -LsSf https://github.com/jacksnxly/keryx/releases/latest/download/keryx-installer.sh | sh"
            );
            return Err(e.into());
        }
    }

    Ok(())
}

/// Handle PR fetch errors with consistent messaging.
///
/// In strict mode, returns an error. Otherwise, prints a warning and returns an empty Vec.
fn handle_pr_fetch_error(e: anyhow::Error, strict: bool) -> Result<Vec<keryx::PullRequest>> {
    if strict {
        bail!(
            "GitHub API error: {}. \n\
            Hint: Use --no-prs to skip PR fetching, or check your GitHub token.",
            e
        );
    }

    warn!("GitHub API error: {}", e);
    eprintln!();
    eprintln!("\x1b[33m⚠ Warning: Could not fetch pull requests\x1b[0m");
    eprintln!("  Error: {}", e);
    eprintln!("  Impact: Changelog will be generated from commits only (may be incomplete)");
    eprintln!("  Fix: Set GITHUB_TOKEN or run `gh auth login`");
    eprintln!("  Hint: Use --strict to fail instead of continuing with partial data");
    eprintln!();

    Ok(Vec::new())
}

/// Run the init command to create a new changelog.
async fn run_init(config: &InitConfig, unreleased: bool, from_history: bool) -> Result<()> {
    let mut llm = LlmRouter::new(config.provider_selection);

    // Check if changelog already exists
    if config.output.exists() && !config.dry_run {
        bail!(
            "{} already exists. Delete it first or use a different output path with -o.",
            config.output.display()
        );
    }

    // Open git repository
    let repo = Repository::open(".")
        .context("Not a git repository. Run keryx from within a git repository.")?;

    if unreleased {
        run_init_unreleased(&repo, config, &mut llm).await
    } else if from_history {
        run_init_from_history(&repo, config, &mut llm).await
    } else {
        run_init_basic(&config.output, config.dry_run)
    }
}

/// Create a basic empty changelog with headers.
fn run_init_basic(output: &PathBuf, dry_run: bool) -> Result<()> {
    let content = format!("{}## [Unreleased]\n", CHANGELOG_HEADER);

    if dry_run {
        println!("--- Dry Run Output ---\n");
        println!("{}", content);
    } else {
        std::fs::write(output, &content).context("Failed to write changelog")?;
        println!("✓ Created {} with [Unreleased] section", output.display());
    }

    Ok(())
}

/// Create changelog with all commits in [Unreleased] section.
async fn run_init_unreleased(
    repo: &Repository,
    config: &InitConfig,
    llm: &mut LlmRouter,
) -> Result<()> {
    println!("Analyzing all commits for [Unreleased] section...");

    // Get all commits from root to HEAD (bypassing tag-based resolution)
    let root_oid = find_root_commit(repo, config.strict).context("Failed to find root commit")?;
    let head_oid = repo.head()?.peel_to_commit()?.id();

    let commits = fetch_commits(repo, root_oid, head_oid, config.strict)
        .context("Failed to fetch commits")?;

    if commits.is_empty() {
        // Just create basic changelog if no commits
        return run_init_basic(&config.output, config.dry_run);
    }

    println!("Found {} commits", commits.len());

    // Fetch PRs if not disabled
    let pull_requests = if config.no_prs {
        Vec::new()
    } else {
        match fetch_prs_for_repo(repo, config.pr_limit).await {
            Ok(prs) => {
                println!("Found {} merged PRs", prs.len());
                prs
            }
            Err(e) => handle_pr_fetch_error(e, config.strict)?,
        }
    };

    // Build prompt and generate entries
    let repo_name = get_repo_name(repo).unwrap_or_else(|| "repository".to_string());
    let input = ChangelogInput {
        commits,
        pull_requests,
        previous_version: None,
        repository_name: repo_name,
        project_description: read_cargo_description(),
        cli_features: None,
    };

    let prompt = build_prompt(&input).context("Failed to build prompt")?;

    println!(
        "Generating release notes with {} (fallback: {})...",
        llm.primary(),
        llm.fallback()
    );
    let draft_completion = llm
        .generate(&prompt)
        .await
        .map_err(|e| handle_llm_error(e, config.verbose))?;
    report_llm_fallback_if_any(&draft_completion, config.verbose);
    let draft_output = draft_completion.output;

    // Verify entries against codebase (unless --no-verify)
    let changelog_output = if config.no_verify {
        debug!("Skipping verification (--no-verify flag)");
        draft_output
    } else {
        let repo_path = repo
            .workdir()
            .context("Cannot verify in a bare repository. Use --no-verify to skip verification.")?;
        verify_changelog_entries(&draft_output, repo_path, config.verbose, llm).await?
    };

    if changelog_output.entries.is_empty() {
        println!("No verified changelog entries found. Creating basic changelog template.");
        return run_init_basic(&config.output, config.dry_run);
    }

    // Build the changelog content
    let mut content = CHANGELOG_HEADER.to_string();
    content.push_str("## [Unreleased]\n\n");

    if !changelog_output.entries.is_empty() {
        for (category, entries) in changelog_output.entries_by_category() {
            content.push_str(&format!("### {}\n\n", category.as_str()));
            for entry in entries {
                content.push_str(&format!("- {}\n", entry.description));
            }
            content.push('\n');
        }
    }

    if config.dry_run {
        println!("\n--- Dry Run Output ---\n");
        println!("{}", content);
    } else {
        std::fs::write(&config.output, &content).context("Failed to write changelog")?;
        println!(
            "✓ Created {} with {} entries in [Unreleased]",
            config.output.display(),
            changelog_output.entries.len()
        );
    }

    Ok(())
}

/// Create changelog with entries for each existing git tag.
///
/// Note: Verification is not yet implemented for this path as it processes
/// multiple versions. The regular `keryx` command includes verification.
async fn run_init_from_history(
    repo: &Repository,
    config: &InitConfig,
    llm: &mut LlmRouter,
) -> Result<()> {
    if !config.no_verify {
        eprintln!(
            "\x1b[33m⚠ Note: Verification is not yet supported for --from-history.\n  \
             Entries will be unverified. Use --no-verify to suppress this warning.\x1b[0m"
        );
    }

    println!("Analyzing git history to build changelog from tags...");

    // Get all semver tags, sorted by version (oldest first for processing)
    let mut tags: Vec<_> = get_all_tags(repo)?
        .into_iter()
        .filter(|t| t.version.is_some())
        .collect();

    tags.sort_by(|a, b| a.version.cmp(&b.version));

    if tags.is_empty() {
        println!("No semver tags found. Creating basic changelog instead.");
        return run_init_basic(&config.output, config.dry_run);
    }

    println!(
        "Found {} version tags: {}",
        tags.len(),
        tags.iter()
            .map(|t| t.name.clone())
            .collect::<Vec<_>>()
            .join(", ")
    );

    // Fetch PRs once if not disabled
    let all_prs = if config.no_prs {
        Vec::new()
    } else {
        match fetch_prs_for_repo(repo, config.pr_limit).await {
            Ok(prs) => {
                println!("Found {} merged PRs", prs.len());
                prs
            }
            Err(e) => handle_pr_fetch_error(e, config.strict)?,
        }
    };

    let repo_name = get_repo_name(repo).unwrap_or_else(|| "repository".to_string());

    // Build sections for each version (newest first in output)
    let mut version_sections: Vec<(Version, String)> = Vec::new();
    let mut prev_oid: Option<git2::Oid> = None;

    for tag in &tags {
        let version = tag.version.as_ref().unwrap();

        // Get commits between previous tag and this tag
        let commits = if let Some(from_oid) = prev_oid {
            match fetch_commits(repo, from_oid, tag.oid, config.strict) {
                Ok(c) => c,
                Err(e) => {
                    if config.strict {
                        bail!("Failed to fetch commits for tag {}: {}", tag.name, e);
                    }
                    warn!(
                        "Failed to fetch commits for tag {}: {}. Section may be incomplete.",
                        tag.name, e
                    );
                    Vec::new()
                }
            }
        } else {
            // First tag - get all commits from root to this tag
            let root_oid = match find_root_commit(repo, config.strict) {
                Ok(oid) => oid,
                Err(e) => {
                    if config.strict {
                        bail!("Failed to find root commit for tag {}: {}", tag.name, e);
                    }
                    warn!(
                        "Failed to find root commit for tag {}: {}. Using tag commit as fallback.",
                        tag.name, e
                    );
                    tag.oid
                }
            };
            match fetch_commits(repo, root_oid, tag.oid, config.strict) {
                Ok(c) => c,
                Err(e) => {
                    if config.strict {
                        bail!("Failed to fetch commits for tag {}: {}", tag.name, e);
                    }
                    warn!(
                        "Failed to fetch commits for tag {}: {}. Section may be incomplete.",
                        tag.name, e
                    );
                    Vec::new()
                }
            }
        };

        if commits.is_empty() {
            prev_oid = Some(tag.oid);
            continue;
        }

        println!("Processing {} ({} commits)...", tag.name, commits.len());

        // Generate entries for this version
        let input = ChangelogInput {
            commits,
            pull_requests: all_prs.clone(), // TODO: filter by date range
            previous_version: prev_oid.and_then(|_| {
                tags.iter()
                    .find(|t| t.oid == prev_oid.unwrap())
                    .and_then(|t| t.version.clone())
            }),
            repository_name: repo_name.clone(),
            project_description: if prev_oid.is_none() {
                read_cargo_description()
            } else {
                None
            },
            cli_features: None,
        };

        let prompt = build_prompt(&input).context("Failed to build prompt")?;
        let draft_completion = llm
            .generate(&prompt)
            .await
            .map_err(|e| handle_llm_error(e, config.verbose))?;
        report_llm_fallback_if_any(&draft_completion, config.verbose);
        let changelog_output = draft_completion.output;

        // Get tag date from commit
        let tag_date = repo
            .find_commit(tag.oid)
            .map(|c| {
                let time = c.time();
                chrono::DateTime::from_timestamp(time.seconds(), 0)
                    .map(|dt| dt.format("%Y-%m-%d").to_string())
                    .unwrap_or_else(|| "unknown".to_string())
            })
            .unwrap_or_else(|_| "unknown".to_string());

        // Format section
        let mut section = format!("## [{}] - {}\n\n", version, tag_date);

        if changelog_output.entries.is_empty() {
            section.push_str("- Initial release\n\n");
        } else {
            for (category, entries) in changelog_output.entries_by_category() {
                section.push_str(&format!("### {}\n\n", category.as_str()));
                for entry in entries {
                    section.push_str(&format!("- {}\n", entry.description));
                }
                section.push('\n');
            }
        }

        version_sections.push((version.clone(), section));
        prev_oid = Some(tag.oid);
    }

    // Check for unreleased commits (after latest tag)
    let latest_tag = tags.last().unwrap();
    let head = repo.head()?.peel_to_commit()?.id();

    let unreleased_commits = match fetch_commits(repo, latest_tag.oid, head, config.strict) {
        Ok(c) => c,
        Err(e) => {
            if config.strict {
                bail!("Failed to fetch unreleased commits: {}", e);
            }
            warn!(
                "Failed to fetch unreleased commits: {}. Unreleased section may be incomplete.",
                e
            );
            Vec::new()
        }
    };

    let mut unreleased_section = String::new();
    if !unreleased_commits.is_empty() {
        println!(
            "Processing {} unreleased commits...",
            unreleased_commits.len()
        );

        let input = ChangelogInput {
            commits: unreleased_commits,
            pull_requests: all_prs,
            previous_version: latest_tag.version.clone(),
            repository_name: repo_name,
            project_description: None,
            cli_features: None,
        };

        let prompt = build_prompt(&input)?;
        let draft_completion = llm
            .generate(&prompt)
            .await
            .map_err(|e| handle_llm_error(e, config.verbose))?;
        report_llm_fallback_if_any(&draft_completion, config.verbose);
        let changelog_output = draft_completion.output;

        unreleased_section.push_str("## [Unreleased]\n\n");
        if !changelog_output.entries.is_empty() {
            for (category, entries) in changelog_output.entries_by_category() {
                unreleased_section.push_str(&format!("### {}\n\n", category.as_str()));
                for entry in entries {
                    unreleased_section.push_str(&format!("- {}\n", entry.description));
                }
                unreleased_section.push('\n');
            }
        }
    } else {
        unreleased_section.push_str("## [Unreleased]\n\n");
    }

    // Build final content (newest versions first)
    let mut content = CHANGELOG_HEADER.to_string();
    content.push_str(&unreleased_section);

    // Add versions in reverse order (newest first)
    for (_, section) in version_sections.into_iter().rev() {
        content.push_str(&section);
    }

    if config.dry_run {
        println!("\n--- Dry Run Output ---\n");
        println!("{}", content);
    } else {
        std::fs::write(&config.output, &content).context("Failed to write changelog")?;
        println!(
            "✓ Created {} with {} version(s)",
            config.output.display(),
            tags.len()
        );
    }

    Ok(())
}

/// Run the commit message generation command.
///
/// Orchestrates the full commit flow: collects diff, optionally analyzes
/// whether to split into multiple commits, then dispatches to either
/// [`run_single_commit`] or [`run_split_commits`].
async fn run_commit(
    config: &CommitConfig,
    no_split: bool,
    provider_flag: Option<ProviderFlag>,
) -> Result<CommitOutcome> {
    let provider_selection = provider_flag
        .map(Provider::from)
        .map(ProviderSelection::from_primary)
        .unwrap_or_default();
    let mut llm = LlmRouter::new(provider_selection);

    let repo = Repository::open(".")
        .context("Not a git repository. Run keryx from within a git repository.")?;

    let diff = collect_diff(&repo).map_err(|e| match &e {
        keryx::CommitError::NoChanges => anyhow::anyhow!("Nothing to commit (working tree clean)"),
        _ => anyhow::anyhow!("{}", e),
    })?;

    if config.verbose {
        debug!(
            "Found {} changed files ({} additions, {} deletions)",
            diff.changed_files.len(),
            diff.additions,
            diff.deletions
        );
        if diff.truncated {
            debug!("Diff was truncated at 30,000 characters");
        }
    }

    println!(
        "Analyzing {} changed file{}...",
        diff.changed_files.len(),
        if diff.changed_files.len() == 1 {
            ""
        } else {
            "s"
        }
    );

    let branch_name = repo
        .head()
        .ok()
        .and_then(|h| h.shorthand().map(String::from))
        .unwrap_or_else(|| "HEAD".to_string());

    // Attempt split analysis if conditions are met
    let file_count = diff.changed_files.len();
    let analysis = if !no_split && file_count >= SPLIT_ANALYSIS_THRESHOLD {
        if config.verbose {
            debug!(
                "Attempting split analysis ({} files >= threshold {})",
                file_count, SPLIT_ANALYSIS_THRESHOLD
            );
        }

        println!("Checking if changes should be split into multiple commits...");

        match analyze_split(&diff, &branch_name, &mut llm, config.verbose).await {
            Ok(Some(analysis)) => Some(analysis),
            Ok(None) => {
                if config.verbose {
                    debug!("Split analysis returned single group or was invalid");
                }
                None
            }
            Err(e) => {
                warn!("Split analysis failed: {}", e.summary());
                eprintln!("\x1b[33m⚠ Split analysis failed, falling back to single commit\x1b[0m");
                if config.verbose {
                    eprintln!("  Details: {}", e.detailed());
                }
                None
            }
        }
    } else {
        if config.verbose && !no_split {
            debug!(
                "Skipping split analysis ({} files < threshold {})",
                file_count, SPLIT_ANALYSIS_THRESHOLD
            );
        }
        None
    };

    match analysis {
        Some(analysis) => {
            run_split_commits(&repo, &diff, &analysis, &branch_name, &mut llm, config).await
        }
        None => run_single_commit(&repo, &diff, &branch_name, &mut llm, config).await,
    }
}

/// Run the commit flow and push the resulting commit(s) to the remote.
async fn run_push(
    config: &CommitConfig,
    no_split: bool,
    provider_flag: Option<ProviderFlag>,
) -> Result<()> {
    let outcome = run_commit(config, no_split, provider_flag).await?;

    let commit_count = match outcome {
        CommitOutcome::NoCommit => return Ok(()),
        CommitOutcome::Committed(oids) => oids.len(),
    };

    if commit_count == 0 {
        return Ok(());
    }

    println!(
        "Pushing {} commit{} to remote...",
        commit_count,
        if commit_count == 1 { "" } else { "s" }
    );

    push_to_remote(config.verbose).await?;

    println!(
        "\x1b[32m\u{2713} Pushed {} commit{} to remote\x1b[0m",
        commit_count,
        if commit_count == 1 { "" } else { "s" }
    );

    Ok(())
}

/// Push the current branch to its remote.
///
/// Following CLI best practices (clig.dev), this function:
/// - Lets git push run first (respects push.default, push.autoSetupRemote)
/// - Provides actionable error messages with fix commands on failure
/// - Uses verbose mode for detailed debugging output
async fn push_to_remote(verbose: bool) -> Result<()> {
    // Get current branch name for actionable error messages
    let branch_output = Command::new("git")
        .args(["rev-parse", "--abbrev-ref", "HEAD"])
        .output()
        .await
        .context("Failed to determine current branch")?;

    if !branch_output.status.success() {
        let stderr = String::from_utf8_lossy(&branch_output.stderr);
        bail!(
            "Failed to determine current branch: {}",
            stderr.trim().lines().next().unwrap_or("unknown error")
        );
    }

    let branch_name = String::from_utf8_lossy(&branch_output.stdout)
        .trim()
        .to_string();

    if verbose {
        debug!("Current branch: {}", branch_name);
        debug!("Running git push (respecting user's push.default config)");
    }

    // Let git push run - it respects push.default (simple, current, matching, etc.)
    // and push.autoSetupRemote settings. Only provide guidance on failure.
    let output = Command::new("git")
        .arg("push")
        .stdout(Stdio::inherit())
        .stderr(Stdio::piped())
        .output()
        .await
        .context("Failed to run `git push`")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);

        // Provide actionable hints based on common failure patterns
        let hint = if stderr.contains("no upstream branch")
            || stderr.contains("has no upstream")
            || stderr.contains("--set-upstream")
        {
            // No upstream configured and push.default requires it
            format!(
                "\n\nHint: No upstream branch configured for '{}'.\n  \
                 To push and set upstream: git push -u origin {}\n  \
                 Or enable auto-setup: git config --global push.autoSetupRemote true",
                branch_name, branch_name
            )
        } else if stderr.contains("rejected") && stderr.contains("non-fast-forward") {
            "\n\nHint: Remote has changes you don't have locally.\n  \
             Pull first: git pull --rebase\n  \
             Or force push: git push --force-with-lease"
                .to_string()
        } else if stderr.contains("Permission denied") || stderr.contains("403") {
            "\n\nHint: Check your Git credentials or repository permissions.".to_string()
        } else if stderr.contains("Could not resolve host") {
            "\n\nHint: Check your network connection.".to_string()
        } else {
            String::new()
        };

        bail!(
            "git push failed (exit {}){}\n\n{}",
            output.status.code().unwrap_or(-1),
            hint,
            stderr.trim()
        );
    }

    Ok(())
}

/// Run a single commit for all changes (original behavior).
async fn run_single_commit(
    repo: &Repository,
    diff: &keryx::commit::DiffSummary,
    branch_name: &str,
    llm: &mut LlmRouter,
    config: &CommitConfig,
) -> Result<CommitOutcome> {
    println!(
        "Generating commit message with {} (fallback: {})...",
        llm.primary(),
        llm.fallback()
    );

    let (message, completion) = generate_commit_message(diff, branch_name, llm, config.verbose)
        .await
        .map_err(|e| handle_llm_error(e, config.verbose))?;

    report_llm_fallback_if_any(&completion, config.verbose);

    display_commit_message(&message, config.verbose);

    if config.message_only || config.dry_run {
        if config.message_only {
            print!("{}", message.format());
        }
        return Ok(CommitOutcome::NoCommit);
    }

    let formatted = message.format();
    let oid = stage_and_commit(repo, &formatted).map_err(|e| anyhow::anyhow!("{}", e))?;

    println!(
        "\x1b[32m\u{2713} Created commit {}\x1b[0m",
        &oid.to_string()[..7]
    );

    Ok(CommitOutcome::Committed(vec![oid]))
}

/// Run split commits: one per commit group from the analysis.
async fn run_split_commits(
    repo: &Repository,
    diff: &keryx::commit::DiffSummary,
    analysis: &keryx::commit::SplitAnalysis,
    branch_name: &str,
    llm: &mut LlmRouter,
    config: &CommitConfig,
) -> Result<CommitOutcome> {
    println!();
    println!(
        "\x1b[1mProposed split into {} commits:\x1b[0m",
        analysis.groups.len()
    );
    for (i, group) in analysis.groups.iter().enumerate() {
        println!(
            "  {}. {} ({} file{})",
            i + 1,
            group.label,
            group.files.len(),
            if group.files.len() == 1 { "" } else { "s" }
        );
        if config.verbose {
            for file in &group.files {
                println!("     - {}", file);
            }
        }
    }
    println!();

    let file_changes: HashMap<String, ChangedFile> = diff
        .changed_files
        .iter()
        .map(|f| (f.path.clone(), f.clone()))
        .collect();

    // Collect all group diffs upfront before any commits advance HEAD.
    // This ensures each group's LLM prompt sees the diff against the original HEAD.
    let group_diffs: Vec<DiffSummary> = analysis
        .groups
        .iter()
        .map(|group| {
            collect_diff_for_paths(repo, &group.files).map_err(|e| {
                anyhow::anyhow!("Failed to collect diff for group '{}': {}", group.label, e)
            })
        })
        .collect::<Result<Vec<_>>>()?;

    let mut commit_oids: Vec<(String, git2::Oid)> = Vec::new();
    let mut all_messages: Vec<String> = Vec::new();

    for (i, (group, group_diff)) in analysis.groups.iter().zip(group_diffs.iter()).enumerate() {
        println!(
            "\x1b[1m[{}/{}] {}\x1b[0m",
            i + 1,
            analysis.groups.len(),
            group.label
        );

        println!(
            "  Generating message with {} (fallback: {})...",
            llm.primary(),
            llm.fallback()
        );

        let (message, completion) =
            generate_commit_message(group_diff, branch_name, llm, config.verbose)
                .await
                .map_err(|e| handle_llm_error(e, config.verbose))?;

        report_llm_fallback_if_any(&completion, config.verbose);

        display_commit_message(&message, config.verbose);

        let formatted = message.format();
        all_messages.push(formatted.clone());

        if !config.message_only && !config.dry_run {
            let oid = stage_paths_and_commit(repo, &group.files, &file_changes, &formatted)
                .map_err(|e| anyhow::anyhow!("{}", e))?;

            println!(
                "\x1b[32m  \u{2713} Created commit {}\x1b[0m",
                &oid.to_string()[..7]
            );
            commit_oids.push((group.label.clone(), oid));
        }
    }

    if config.message_only {
        print!("{}", all_messages.join("\n---\n"));
        return Ok(CommitOutcome::NoCommit);
    } else if !config.dry_run && !commit_oids.is_empty() {
        println!();
        println!(
            "\x1b[32m\u{2713} Created {} commits:\x1b[0m",
            commit_oids.len()
        );
        for (label, oid) in &commit_oids {
            println!("  {} -- {}", &oid.to_string()[..7], label);
        }
    }

    if config.dry_run || commit_oids.is_empty() {
        Ok(CommitOutcome::NoCommit)
    } else {
        Ok(CommitOutcome::Committed(
            commit_oids.into_iter().map(|(_, oid)| oid).collect(),
        ))
    }
}

/// Display a commit message to the user.
fn display_commit_message(message: &keryx::commit::CommitMessage, verbose: bool) {
    println!();
    println!("\x1b[1m{}\x1b[0m", message.subject);

    if let Some(body) = message.body.as_deref().filter(|b| !b.trim().is_empty()) {
        println!();
        println!("{}", body.trim());
    }

    if message.breaking {
        println!();
        println!("\x1b[33m⚠ BREAKING CHANGE\x1b[0m");
    }

    match message
        .changelog_category
        .as_ref()
        .zip(message.changelog_description.as_ref())
    {
        Some((cat, desc)) => {
            println!();
            println!(
                "\x1b[36mChangelog ({}):\x1b[0m {}",
                cat.as_str().to_lowercase(),
                desc
            );
        }
        None if verbose => {
            println!();
            println!("\x1b[2mInternal change — excluded from changelog\x1b[0m");
        }
        None => {}
    }

    println!();
}

/// Run the changelog generation command.
async fn run_generate(cli: Cli) -> Result<()> {
    let provider_selection = cli
        .provider
        .clone()
        .map(Provider::from)
        .map(ProviderSelection::from_primary)
        .unwrap_or_default();
    let mut llm = LlmRouter::new(provider_selection);

    // Step 1: Open git repository
    let repo = Repository::open(".")
        .context("Not a git repository. Run keryx from within a git repository.")?;

    // Step 3: Resolve commit range
    let range = resolve_range(&repo, cli.from.as_deref(), Some(&cli.to), cli.strict)
        .context("Failed to resolve commit range")?;

    println!(
        "Analyzing commits from {} to {}...",
        range.from_ref, range.to_ref
    );

    // Step 4: Fetch commits
    let commits = fetch_commits(&repo, range.from, range.to, cli.strict)
        .context("Failed to fetch commits")?;

    if commits.is_empty() {
        println!("No changes found since {}. Nothing to add.", range.from_ref);
        return Ok(());
    }

    println!("Found {} commits", commits.len());

    // Step 5: Fetch PRs (if not disabled)
    let pull_requests = if cli.no_prs {
        Vec::new()
    } else {
        match fetch_prs_for_repo(&repo, cli.pr_limit).await {
            Ok(prs) => {
                println!("Found {} merged PRs", prs.len());
                prs
            }
            Err(e) => handle_pr_fetch_error(e, cli.strict)?,
        }
    };

    // Step 6: Determine version
    let base_version = get_latest_tag(&repo)?.and_then(|t| t.version);
    let repo_name_for_bump = get_repo_name(&repo).unwrap_or_else(|| "repository".to_string());

    let (next_version, bump_reasoning) = if let Some(explicit) = cli.set_version.clone() {
        (explicit, None)
    } else if cli.no_llm_bump {
        (
            calculate_next_version(base_version.as_ref(), &commits),
            None,
        )
    } else {
        let bump_input = VersionBumpInput {
            commits: &commits,
            pull_requests: &pull_requests,
            previous_version: base_version.as_ref(),
            repository_name: &repo_name_for_bump,
        };
        calculate_next_version_with_llm(&bump_input, &mut llm, cli.verbose).await
    };

    println!(
        "Version: {} -> {}",
        base_version
            .as_ref()
            .map(|v| v.to_string())
            .unwrap_or_else(|| "none".to_string()),
        next_version
    );

    if cli.verbose
        && let Some(ref reasoning) = bump_reasoning
    {
        println!("  LLM bump reasoning: {}", reasoning);
    }

    // Step 6b: Check if version already exists in changelog
    if let Some(parsed) =
        read_changelog(&cli.output).context("Failed to read existing changelog")?
        && parsed.has_version(&next_version)
    {
        if cli.force {
            eprintln!(
                "\x1b[33m⚠ Warning: Version {} already exists in changelog, overwriting due to --force\x1b[0m",
                next_version
            );
        } else {
            bail!(
                "Version {} already exists in {}. Use --force to overwrite, or use --set-version to specify a different version.",
                next_version,
                cli.output.display()
            );
        }
    }

    // Step 7: Build prompt and call LLM provider
    let repo_name = get_repo_name(&repo).unwrap_or_else(|| "repository".to_string());
    let is_initial_release = base_version.is_none();

    // For initial releases, gather extra context
    let (project_description, cli_features) = if is_initial_release {
        (read_cargo_description(), Some(get_cli_features()))
    } else {
        (None, None)
    };

    let input = ChangelogInput {
        commits,
        pull_requests,
        previous_version: base_version,
        repository_name: repo_name,
        project_description,
        cli_features,
    };

    let prompt = build_prompt(&input).context("Failed to build prompt for LLM")?;

    println!(
        "Generating release notes with {} (fallback: {})...",
        llm.primary(),
        llm.fallback()
    );

    let draft_completion = llm
        .generate(&prompt)
        .await
        .map_err(|e| handle_llm_error(e, cli.verbose))?;
    report_llm_fallback_if_any(&draft_completion, cli.verbose);
    let draft_output = draft_completion.output;

    if draft_output.entries.is_empty() {
        println!("No changelog entries generated. Nothing to add.");
        return Ok(());
    }

    // Step 8: Verify entries against codebase (unless --no-verify)
    let changelog_output = if cli.no_verify {
        debug!("Skipping verification (--no-verify flag)");
        draft_output
    } else {
        let repo_path = repo
            .workdir()
            .context("Cannot verify in a bare repository. Use --no-verify to skip verification.")?;
        verify_changelog_entries(&draft_output, repo_path, cli.verbose, &mut llm).await?
    };

    if changelog_output.entries.is_empty() {
        println!("No verified changelog entries found. Nothing to add.");
        return Ok(());
    }

    // Step 9: Write or display changelog
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

/// Verify changelog entries against the codebase using a second LLM pass.
///
/// This function:
/// 1. Scans the codebase for evidence supporting/refuting each entry
/// 2. Sends the evidence to Claude for verification
/// 3. Returns corrected entries with hallucinations removed
async fn verify_changelog_entries(
    draft: &keryx::ChangelogOutput,
    repo_path: &std::path::Path,
    verbose: bool,
    llm: &mut LlmRouter,
) -> Result<keryx::ChangelogOutput> {
    // Check prerequisites
    check_ripgrep_installed().context("Verification requires ripgrep")?;

    println!("Verifying entries against codebase...");

    // Gather evidence from the codebase
    let evidence = gather_verification_evidence(&draft.entries, repo_path);

    // Report verification findings
    let low_confidence: Vec<_> = evidence.low_confidence_entries();
    if !low_confidence.is_empty() {
        eprintln!();
        eprintln!(
            "\x1b[33m⚠ Found {} entries with low confidence:\x1b[0m",
            low_confidence.len()
        );
        for entry in &low_confidence {
            eprintln!(
                "  • {}",
                truncate_description(&entry.original_description, 60)
            );
            if !entry.stub_indicators.is_empty() {
                eprintln!(
                    "    └─ Found {} stub/TODO indicators",
                    entry.stub_indicators.len()
                );
            }
            if entry.scan_summary.has_failures() {
                eprintln!(
                    "    └─ {} of {} keyword searches failed",
                    entry.scan_summary.failed_searches,
                    entry.scan_summary.successful_searches + entry.scan_summary.failed_searches
                );
            }
            for check in &entry.count_checks {
                match check.matches() {
                    Some(false) => {
                        eprintln!(
                            "    └─ Count mismatch: claimed {}, found {}",
                            check.claimed_text,
                            check
                                .actual_count
                                .map(|c| c.to_string())
                                .unwrap_or_else(|| "unknown".to_string())
                        );
                    }
                    None => {
                        eprintln!("    └─ Could not verify: {}", check.claimed_text,);
                    }
                    Some(true) => {} // Verified match - no warning needed
                }
            }
        }
        eprintln!();
    }

    // Summary of search failures across all entries
    let total_failures: usize = evidence
        .entries
        .iter()
        .map(|e| e.scan_summary.failed_searches)
        .sum();
    if total_failures > 0 {
        eprintln!(
            "\x1b[33m⚠ Note: {} keyword search(es) failed during verification. Confidence scores may be affected.\x1b[0m",
            total_failures
        );
        eprintln!();
    }

    if verbose {
        // Show all evidence in verbose mode
        for entry_ev in &evidence.entries {
            debug!(
                "Entry: {} | Confidence: {} | Keywords: {} | Stubs: {}",
                truncate_description(&entry_ev.original_description, 40),
                entry_ev.confidence(),
                entry_ev.keyword_matches.len(),
                entry_ev.stub_indicators.len()
            );
        }
    }

    // Serialize draft entries for verification prompt
    let draft_json =
        serde_json::to_string_pretty(&draft).context("Failed to serialize draft entries")?;

    // Build verification prompt
    let verification_prompt = build_verification_prompt(&draft_json, &evidence)
        .context("Failed to build verification prompt")?;

    println!(
        "Running verification agent with {} (fallback: {})...",
        llm.primary(),
        llm.fallback()
    );

    // Run verification pass
    let verified_completion = llm
        .generate(&verification_prompt)
        .await
        .map_err(|e| handle_llm_error(e, verbose))?;
    report_llm_fallback_if_any(&verified_completion, verbose);
    let verified_output = verified_completion.output;

    // Report what changed
    let original_count = draft.entries.len();
    let verified_count = verified_output.entries.len();

    if verified_count < original_count {
        println!(
            "\x1b[33m⚠ Verification removed {} potentially inaccurate entries\x1b[0m",
            original_count - verified_count
        );
    } else if verified_count == original_count {
        println!("\x1b[32m✓ All {} entries verified\x1b[0m", verified_count);
    }

    Ok(verified_output)
}

fn report_llm_fallback_if_any<T>(completion: &LlmCompletion<T>, verbose: bool) {
    if let Some(primary_error) = &completion.primary_error {
        eprintln!();
        eprintln!(
            "\x1b[33m⚠ {} failed, using {} instead\x1b[0m",
            primary_error.provider(),
            completion.provider
        );
        if verbose {
            eprintln!("  Details: {}", primary_error.detail());
        } else {
            eprintln!("  Reason: {}", primary_error.summary());
        }
        eprintln!();
    }
}

fn handle_llm_error(err: LlmError, verbose: bool) -> anyhow::Error {
    let message = if verbose {
        err.detailed()
    } else {
        err.summary()
    };
    let hint = llm_error_hint(&err);

    let full_message = if let Some(hint) = hint {
        format!("{}\nHint: {}", message, hint)
    } else {
        message
    };

    anyhow::anyhow!(full_message)
}

fn llm_error_hint(err: &LlmError) -> Option<String> {
    let mut hints: Vec<&'static str> = Vec::new();

    let primary = err.primary_error();
    let fallback = err.fallback_error();

    for provider_error in [primary, fallback].into_iter().flatten() {
        if let Some(hint) = provider_install_hint(provider_error)
            && !hints.contains(&hint)
        {
            hints.push(hint);
        }
    }

    if hints.is_empty() {
        None
    } else {
        Some(hints.join(" | "))
    }
}

fn provider_install_hint(err: &LlmProviderError) -> Option<&'static str> {
    match err {
        LlmProviderError::Claude(keryx::ClaudeError::NotInstalled) => Some(
            "Install Claude Code CLI: npm install -g @anthropic-ai/claude-code (then run `claude login`)",
        ),
        LlmProviderError::Codex(keryx::CodexError::NotInstalled) => Some(
            "Install Codex CLI: npm install -g @openai/codex (then run `codex` or set CODEX_API_KEY)",
        ),
        _ => None,
    }
}

/// Truncate a description for display.
fn truncate_description(desc: &str, max_len: usize) -> String {
    if desc.len() <= max_len {
        desc.to_string()
    } else {
        let mut end = max_len.saturating_sub(3);
        while end > 0 && !desc.is_char_boundary(end) {
            end -= 1;
        }
        format!("{}...", &desc[..end])
    }
}

/// Fetch PRs for the current repository.
async fn fetch_prs_for_repo(
    repo: &Repository,
    limit: Option<usize>,
) -> Result<Vec<keryx::PullRequest>> {
    // Get GitHub token
    let token = get_github_token()
        .await
        .context("GitHub authentication required for PR fetching")?;

    // Get remote URL
    let remote = repo
        .find_remote("origin")
        .context("No 'origin' remote found")?;

    let url = remote.url().context("Remote has no URL")?;

    let (owner, repo_name) =
        parse_github_remote(url).context("Could not parse GitHub remote URL")?;

    // Fetch PRs (no date filter for now, we'll filter by commits later)
    let prs = fetch_merged_prs(&token, &owner, &repo_name, None, None, limit).await?;

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
        if line.starts_with("description")
            && let Some(start) = line.find('"')
            && let Some(end) = line.rfind('"')
            && end > start
        {
            return Some(line[start + 1..end].to_string());
        }
    }
    None
}

/// Get CLI features for context by introspecting the Cli struct.
/// This uses clap's CommandFactory to dynamically generate the list,
/// preventing documentation rot when new flags are added.
fn get_cli_features() -> Vec<String> {
    let cmd = Cli::command();
    let mut features: Vec<String> = cmd
        .get_arguments()
        .filter(|arg| {
            // Skip internal clap arguments like "help" and "version"
            let id = arg.get_id().as_str();
            !["help", "version"].contains(&id)
        })
        .filter_map(|arg| {
            let id = arg.get_id().as_str();
            let help = arg.get_help().map(|h| h.to_string())?;
            let short = arg
                .get_short()
                .map(|s| format!("-{}, ", s))
                .unwrap_or_default();
            let long = format!("--{}", id.replace('_', "-"));
            Some(format!("{}{}: {}", short, long, help))
        })
        .collect();

    // Add non-flag features that aren't captured by argument introspection
    features.push("GitHub auth: Supports gh CLI, GITHUB_TOKEN, and GH_TOKEN".to_string());
    features.push("Automatic backup: Creates .changelog.md.bak before modifying".to_string());
    features.push("Handles [Unreleased] sections per Keep a Changelog spec".to_string());

    features
}

#[cfg(test)]
mod tests {
    use super::*;
    use serial_test::serial;
    use std::env;
    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn test_get_cli_features_includes_all_flags() {
        let features = get_cli_features();
        let features_str = features.join("\n");

        // These flags were previously missing from the hardcoded list
        assert!(features_str.contains("--strict"), "Missing --strict flag");
        assert!(features_str.contains("--force"), "Missing --force flag");
        assert!(features_str.contains("--verbose"), "Missing --verbose flag");
        assert!(
            features_str.contains("--no-verify"),
            "Missing --no-verify flag"
        );

        // Original flags should still be present
        assert!(
            features_str.contains("--set-version"),
            "Missing --set-version flag"
        );
        assert!(features_str.contains("--dry-run"), "Missing --dry-run flag");
        assert!(features_str.contains("--no-prs"), "Missing --no-prs flag");
        assert!(features_str.contains("--from"), "Missing --from flag");
        assert!(features_str.contains("--to"), "Missing --to flag");
        assert!(features_str.contains("--output"), "Missing --output flag");
        assert!(
            features_str.contains("--pr-limit"),
            "Missing --pr-limit flag"
        );

        // Non-flag features should be present
        assert!(
            features_str.contains("GitHub auth"),
            "Missing GitHub auth feature"
        );
        assert!(
            features_str.contains("Automatic backup"),
            "Missing backup feature"
        );
        assert!(
            features_str.contains("[Unreleased]"),
            "Missing Unreleased feature"
        );
    }

    #[test]
    fn test_truncate_description_short_string() {
        // Short strings should not be truncated
        assert_eq!(truncate_description("hello", 10), "hello");
        assert_eq!(truncate_description("", 10), "");
    }

    #[test]
    fn test_truncate_description_exact_length() {
        // String exactly at max_len should not be truncated
        assert_eq!(truncate_description("hello", 5), "hello");
    }

    #[test]
    fn test_truncate_description_ascii() {
        // ASCII strings should be truncated normally
        assert_eq!(truncate_description("hello world", 8), "hello...");
    }

    #[test]
    fn test_truncate_description_multibyte_characters() {
        // Multi-byte UTF-8 characters should not cause a panic
        // and truncation should respect character boundaries

        // Emoji (4 bytes each)
        let emoji_str = "🚀🔥💡✨";
        let result = truncate_description(emoji_str, 10);
        assert!(result.ends_with("..."));
        // Should not panic and should be valid UTF-8

        // CJK characters (3 bytes each)
        let cjk_str = "日本語テスト";
        let result = truncate_description(cjk_str, 10);
        assert!(result.ends_with("..."));

        // Mixed ASCII and multi-byte
        let mixed = "hello 世界 🌍";
        let result = truncate_description(mixed, 12);
        assert!(result.ends_with("..."));
    }

    #[test]
    fn test_truncate_description_very_short_max_len() {
        // Edge case: max_len smaller than "..."
        let result = truncate_description("hello", 2);
        assert_eq!(result, "...");

        let result = truncate_description("hello", 3);
        assert_eq!(result, "...");
    }

    struct EnvVarGuard {
        key: &'static str,
        original: Option<String>,
    }

    impl EnvVarGuard {
        fn set(key: &'static str, value: String) -> Self {
            let original = env::var(key).ok();
            // SAFETY: `std::env::set_var` is unsafe since Rust 1.80 because modifying
            // environment variables is not thread-safe. We use `#[serial]` from
            // serial_test to ensure these tests run sequentially, preventing data races.
            // This is the standard pattern for env var manipulation in Rust tests.
            unsafe {
                env::set_var(key, value);
            }
            Self { key, original }
        }
    }

    impl Drop for EnvVarGuard {
        fn drop(&mut self) {
            match &self.original {
                Some(value) => unsafe {
                    env::set_var(self.key, value);
                },
                None => unsafe {
                    env::remove_var(self.key);
                },
            }
        }
    }

    #[tokio::test]
    #[cfg(unix)]
    #[serial]
    async fn test_push_to_remote_success() {
        let temp_dir = tempfile::tempdir().unwrap();
        let git_path = temp_dir.path().join("git");
        // Mock git that handles: rev-parse --abbrev-ref HEAD, push
        // No upstream check - we let git push handle it based on push.default
        let script = r#"#!/bin/sh
case "$1 $2" in
  "rev-parse --abbrev-ref")
    if [ "$3" = "HEAD" ]; then
      echo "main"
      exit 0
    fi
    ;;
  "push ")
    exit 0
    ;;
esac
echo "unexpected args: $@" >&2
exit 2
"#;
        std::fs::write(&git_path, script).unwrap();
        let mut perms = std::fs::metadata(&git_path).unwrap().permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&git_path, perms).unwrap();

        let original_path = env::var("PATH").unwrap_or_default();
        let new_path = format!("{}:{}", temp_dir.path().display(), original_path);
        let _guard = EnvVarGuard::set("PATH", new_path);

        let result = push_to_remote(false).await;
        assert!(result.is_ok(), "Expected git push to succeed: {:?}", result);
    }

    #[tokio::test]
    #[cfg(unix)]
    #[serial]
    async fn test_push_to_remote_no_upstream() {
        let temp_dir = tempfile::tempdir().unwrap();
        let git_path = temp_dir.path().join("git");
        // Mock git where push fails due to no upstream (git reports the error)
        let script = r#"#!/bin/sh
case "$1 $2" in
  "rev-parse --abbrev-ref")
    if [ "$3" = "HEAD" ]; then
      echo "feature-branch"
      exit 0
    fi
    ;;
  "push ")
    echo "fatal: The current branch feature-branch has no upstream branch." >&2
    echo "To push the current branch and set the remote as upstream, use" >&2
    echo "    git push --set-upstream origin feature-branch" >&2
    exit 128
    ;;
esac
echo "unexpected args: $@" >&2
exit 2
"#;
        std::fs::write(&git_path, script).unwrap();
        let mut perms = std::fs::metadata(&git_path).unwrap().permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&git_path, perms).unwrap();

        let original_path = env::var("PATH").unwrap_or_default();
        let new_path = format!("{}:{}", temp_dir.path().display(), original_path);
        let _guard = EnvVarGuard::set("PATH", new_path);

        let result = push_to_remote(false).await;
        let err = result.expect_err("Expected push to fail without upstream");
        let err_msg = err.to_string();
        assert!(
            err_msg.contains("No upstream branch configured")
                || err_msg.contains("has no upstream"),
            "Expected actionable error about upstream, got: {err_msg}"
        );
        assert!(
            err_msg.contains("git push -u origin") || err_msg.contains("autoSetupRemote"),
            "Expected fix command in error, got: {err_msg}"
        );
    }

    #[tokio::test]
    #[cfg(unix)]
    #[serial]
    async fn test_push_to_remote_rejected() {
        let temp_dir = tempfile::tempdir().unwrap();
        let git_path = temp_dir.path().join("git");
        // Mock git where push is rejected (non-fast-forward)
        let script = r#"#!/bin/sh
case "$1 $2" in
  "rev-parse --abbrev-ref")
    if [ "$3" = "HEAD" ]; then
      echo "main"
      exit 0
    fi
    ;;
  "push ")
    echo "error: failed to push some refs" >&2
    echo "hint: Updates were rejected because the remote contains work" >&2
    echo "hint: that you do not have locally. non-fast-forward" >&2
    exit 1
    ;;
esac
echo "unexpected args: $@" >&2
exit 2
"#;
        std::fs::write(&git_path, script).unwrap();
        let mut perms = std::fs::metadata(&git_path).unwrap().permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&git_path, perms).unwrap();

        let original_path = env::var("PATH").unwrap_or_default();
        let new_path = format!("{}:{}", temp_dir.path().display(), original_path);
        let _guard = EnvVarGuard::set("PATH", new_path);

        let result = push_to_remote(false).await;
        let err = result.expect_err("Expected git push to fail");
        let err_msg = err.to_string();
        assert!(
            err_msg.contains("git push failed"),
            "Expected error message to mention git push failure, got: {err_msg}"
        );
        assert!(
            err_msg.contains("pull --rebase") || err_msg.contains("force-with-lease"),
            "Expected actionable hint for rejected push, got: {err_msg}"
        );
    }
}
