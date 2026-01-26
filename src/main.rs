//! keryx - CLI entry point.

use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, TryRecvError};
use std::thread::JoinHandle;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use git2::Repository;
use semver::Version;
use tracing::{debug, warn, Level};
use tracing_subscriber::FmtSubscriber;

use keryx::changelog::{parser::read_changelog, write_changelog, writer::generate_summary};
use keryx::claude::{build_prompt, check_claude_installed, generate_with_retry, prompt::ChangelogInput};
use keryx::git::{commits::fetch_commits, range::resolve_range, tags::get_latest_tag};
use keryx::github::{auth::get_github_token, prs::{fetch_merged_prs, parse_github_remote}};
use keryx::version::calculate_next_version;

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
                        if error_str.contains("network") || error_str.contains("connection") || error_str.contains("dns") {
                            warn!("Update check failed (network error): {}. Check your internet connection.", e);
                        } else if error_str.contains("parse") || error_str.contains("version") {
                            warn!("Update check failed (version parse error): {}. This may indicate a corrupted install.", e);
                        } else if error_str.contains("not found") || error_str.contains("404") {
                            warn!("Update check failed (release not found): {}. No releases may be available yet.", e);
                        } else {
                            warn!("Update check failed: {}. Run with --verbose for more details.", e);
                        }
                    }
                    UpdateResult { update_available: false }
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

/// Generate release notes from commits and PRs using Claude.
#[derive(Parser, Debug)]
#[command(name = "keryx")]
#[command(about = "Generate release notes from commits and PRs using Claude")]
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
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Update keryx to the latest version
    Update,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    // Initialize tracing subscriber for logging
    let log_level = if cli.verbose { Level::DEBUG } else { Level::WARN };
    let subscriber = FmtSubscriber::builder()
        .with_max_level(log_level)
        .with_writer(std::io::stderr)
        .without_time()
        .finish();
    tracing::subscriber::set_global_default(subscriber)
        .expect("Failed to set tracing subscriber");

    // Start background update check (non-blocking)
    let update_checker = UpdateChecker::start(cli.verbose);

    // Run the requested command
    let result = match cli.command {
        Some(Commands::Update) => run_update().await,
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
    eprintln!("\x1b[33m│\x1b[0m  Run \x1b[36mkeryx update\x1b[0m to upgrade                 \x1b[33m│\x1b[0m");
    eprintln!("\x1b[33m╰───────────────────────────────────────────────╯\x1b[0m");
    eprintln!();
}

/// Run the self-update command.
async fn run_update() -> Result<()> {
    use axoupdater::{AxoUpdater, Version};

    println!("Checking for updates...");

    let current_version: Version = env!("CARGO_PKG_VERSION").parse()
        .context("Failed to parse current version")?;

    let mut updater = AxoUpdater::new_for("keryx");
    updater.set_current_version(current_version)?;

    // Enable output from the installer
    updater.enable_installer_output();

    // Use async version since we're in a tokio runtime
    match updater.run().await {
        Ok(Some(result)) => {
            println!("\n\x1b[32m✓ Successfully updated keryx to v{}\x1b[0m", result.new_version);
        }
        Ok(None) => {
            println!("keryx is already up to date (v{})", env!("CARGO_PKG_VERSION"));
        }
        Err(e) => {
            eprintln!("\x1b[31mFailed to update: {}\x1b[0m", e);
            eprintln!("\nYou can manually update by running:");
            eprintln!("  curl --proto '=https' --tlsv1.2 -LsSf https://github.com/jacksnxly/keryx/releases/latest/download/keryx-installer.sh | sh");
            return Err(e.into());
        }
    }

    Ok(())
}

/// Run the changelog generation command.
async fn run_generate(cli: Cli) -> Result<()> {
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
                // Issue #4 fix: Don't silently mask GitHub API failures
                // In strict mode, fail fast. Otherwise, warn clearly about impact.
                if cli.strict {
                    bail!(
                        "GitHub API error: {}. \n\
                        Hint: Use --no-prs to skip PR fetching, or check your GitHub token.",
                        e
                    );
                }

                // Warn clearly about the impact (changelog may be incomplete)
                warn!("GitHub API error: {}", e);
                eprintln!();
                eprintln!("\x1b[33m⚠ Warning: Could not fetch pull requests\x1b[0m");
                eprintln!("  Error: {}", e);
                eprintln!("  Impact: Changelog will be generated from commits only (may be incomplete)");
                eprintln!("  Fix: Set GITHUB_TOKEN or run `gh auth login`");
                eprintln!("  Hint: Use --strict to fail instead of continuing with partial data");
                eprintln!();

                Vec::new()
            }
        }
    };

    // Step 6: Determine version
    let base_version = get_latest_tag(&repo)?.and_then(|t| t.version);
    let next_version = cli.set_version.unwrap_or_else(|| {
        calculate_next_version(base_version.as_ref(), &commits)
    });

    println!("Version: {} -> {}",
        base_version.as_ref().map(|v| v.to_string()).unwrap_or_else(|| "none".to_string()),
        next_version
    );

    // Step 6b: Check if version already exists in changelog
    if let Some(parsed) = read_changelog(&cli.output)
        .context("Failed to read existing changelog")?
    {
        if parsed.has_version(&next_version) {
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
    }

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
        previous_version: base_version,
        repository_name: repo_name,
        project_description,
        cli_features,
    };

    let prompt = build_prompt(&input).context("Failed to build prompt for Claude")?;

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
