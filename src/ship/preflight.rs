//! Preflight checks for the ship pipeline.
//!
//! Validates working tree state, remote sync, commits, and LLM availability
//! before starting the release process.

use std::process::Command;

use git2::Repository;
use semver::Version;

use crate::error::ShipError;
use crate::git::ParsedCommit;
use crate::git::commits::fetch_commits;
use crate::git::range::resolve_range;
use crate::git::tags::{TagInfo, get_all_tags, get_latest_reachable_tag};
use crate::llm::{Provider, ProviderSelection};

/// Result of all preflight checks.
pub struct PreflightResult {
    pub current_branch: String,
    pub remote_name: String,
    pub upstream_branch: String,
    pub latest_tag: Option<TagInfo>,
    pub commits_since_tag: Vec<ParsedCommit>,
    pub llm_available: bool,
    pub base_version: Option<Version>,
}

struct TrackingBranch {
    remote: String,
    branch: String,
}

/// Run all preflight checks.
///
/// Checks (in order):
/// 1. Clean working tree
/// 2. Up to date with remote
/// 3. Commits exist since last tag
/// 4. LLM available (if needed)
pub fn run_checks(
    repo: &Repository,
    _no_llm_bump: bool,
    provider_selection: ProviderSelection,
    verbose: bool,
) -> Result<PreflightResult, ShipError> {
    // 1. Clean working tree
    check_clean_working_tree(verbose)?;

    // Get branch info
    let current_branch = get_current_branch(repo)?;
    let tracking = get_tracking_branch(repo, &current_branch)?;
    let remote_name = tracking.remote;
    let upstream_branch = tracking.branch;

    // 2. Up to date with remote
    check_remote_sync(&remote_name, &upstream_branch, verbose)?;

    // 3. Commits exist since last reachable stable semver tag
    // Uses commit-graph reachability from HEAD so multi-branch workflows
    // (maintenance branches, backports, etc.) are handled correctly.
    let latest_tag =
        get_latest_reachable_tag(repo).map_err(|e| ShipError::GitFailed(e.to_string()))?;
    let base_version = latest_tag.as_ref().and_then(|t| t.version.clone());

    // Use the reachable tag as range start to ensure commit list matches the tag we report.
    // This prevents including already-released commits when another branch has a newer tag.
    let from_ref = latest_tag.as_ref().map(|t| t.name.as_str());
    let range = resolve_range(repo, from_ref, Some("HEAD"), false)
        .map_err(|e| ShipError::GitFailed(e.to_string()))?;

    let mut commits = fetch_commits(repo, range.from, range.to, false)
        .map_err(|e| ShipError::GitFailed(e.to_string()))?;

    // Include the root commit for initial releases (no tags).
    // The revwalk hides `range.from`, so the first commit is otherwise omitted.
    if latest_tag.is_none() {
        let commit = repo
            .find_commit(range.from)
            .map_err(|e| ShipError::GitFailed(e.to_string()))?;
        let root_hash = commit.id().to_string();
        if !commits.iter().any(|c| c.hash == root_hash) {
            let parsed = ParsedCommit::from_git2_commit(&commit, false)
                .map_err(|e| ShipError::GitFailed(e.to_string()))?;
            commits.push(parsed);
        }
    }

    let tag_ref = latest_tag
        .as_ref()
        .map(|t| t.name.as_str())
        .unwrap_or("(initial)");

    if commits.is_empty() {
        return Err(ShipError::NoCommitsSinceTag(tag_ref.to_string()));
    }

    // 4. LLM available (used for changelog generation)
    let llm_available = check_llm_available(provider_selection, verbose);

    Ok(PreflightResult {
        current_branch,
        remote_name,
        upstream_branch,
        latest_tag,
        commits_since_tag: commits,
        llm_available,
        base_version,
    })
}

/// Check that the working tree is clean (no uncommitted changes).
fn check_clean_working_tree(verbose: bool) -> Result<(), ShipError> {
    let output = Command::new("git")
        .args(["status", "--porcelain"])
        .output()
        .map_err(|e| ShipError::GitFailed(format!("Failed to run git status: {}", e)))?;

    if !output.status.success() {
        return Err(ShipError::GitFailed(
            String::from_utf8_lossy(&output.stderr).to_string(),
        ));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    if !stdout.trim().is_empty() {
        if verbose {
            eprintln!("Uncommitted changes:\n{}", stdout);
        }
        return Err(ShipError::DirtyWorkingTree);
    }

    Ok(())
}

/// Get the current branch name.
fn get_current_branch(repo: &Repository) -> Result<String, ShipError> {
    let head = repo
        .head()
        .map_err(|e| ShipError::GitFailed(format!("Could not determine HEAD: {}", e)))?;

    if !head.is_branch() {
        return Err(ShipError::DetachedHead);
    }

    head.shorthand()
        .map(String::from)
        .ok_or_else(|| ShipError::GitFailed("Could not determine current branch".into()))
}

/// Resolve tracked upstream for the current branch from git config.
fn get_tracking_branch(
    repo: &Repository,
    current_branch: &str,
) -> Result<TrackingBranch, ShipError> {
    let config = repo
        .config()
        .map_err(|e| ShipError::GitFailed(format!("Could not read git config: {}", e)))?;

    let remote_key = format!("branch.{}.remote", current_branch);
    let merge_key = format!("branch.{}.merge", current_branch);

    let remote =
        config
            .get_string(&remote_key)
            .map_err(|_| ShipError::MissingUpstreamTracking {
                branch: current_branch.to_string(),
            })?;
    let merge_ref =
        config
            .get_string(&merge_key)
            .map_err(|_| ShipError::MissingUpstreamTracking {
                branch: current_branch.to_string(),
            })?;

    let branch = merge_ref
        .strip_prefix("refs/heads/")
        .unwrap_or(&merge_ref)
        .to_string();

    if remote.trim().is_empty() || branch.trim().is_empty() {
        return Err(ShipError::MissingUpstreamTracking {
            branch: current_branch.to_string(),
        });
    }

    Ok(TrackingBranch { remote, branch })
}

/// Check that local branch is not behind the remote.
fn check_remote_sync(remote: &str, upstream_branch: &str, verbose: bool) -> Result<(), ShipError> {
    // Fetch from remote first
    let fetch_output = Command::new("git")
        .args(["fetch", remote])
        .output()
        .map_err(|e| ShipError::GitFailed(format!("Failed to run git fetch: {}", e)))?;

    if !fetch_output.status.success() {
        let stderr = String::from_utf8_lossy(&fetch_output.stderr);
        return Err(ShipError::GitFailed(format!(
            "git fetch {} failed: {}",
            remote,
            stderr.trim()
        )));
    }

    if verbose {
        let stderr = String::from_utf8_lossy(&fetch_output.stderr);
        if !stderr.trim().is_empty() {
            eprintln!("git fetch output: {}", stderr.trim());
        }
    }

    // Compare local HEAD with upstream
    let local = Command::new("git")
        .args(["rev-parse", "HEAD"])
        .output()
        .map_err(|e| ShipError::GitFailed(format!("Failed to run git rev-parse HEAD: {}", e)))?;
    if !local.status.success() {
        let stderr = String::from_utf8_lossy(&local.stderr);
        return Err(ShipError::GitFailed(format!(
            "git rev-parse HEAD failed: {}",
            stderr.trim()
        )));
    }

    let upstream_ref = format!("refs/remotes/{}/{}", remote, upstream_branch);
    let upstream = Command::new("git")
        .args(["rev-parse", &upstream_ref])
        .output()
        .map_err(|e| ShipError::GitFailed(format!("Failed to run git rev-parse: {}", e)))?;
    if !upstream.status.success() {
        let stderr = String::from_utf8_lossy(&upstream.stderr);
        return Err(ShipError::GitFailed(format!(
            "Could not resolve upstream ref {}: {}",
            upstream_ref,
            stderr.trim()
        )));
    }

    let local_sha = String::from_utf8_lossy(&local.stdout).trim().to_string();
    let upstream_sha = String::from_utf8_lossy(&upstream.stdout).trim().to_string();

    // Ensure local is a descendant of upstream (fast-forward or equal).
    let ancestor_check = Command::new("git")
        .args(["merge-base", "--is-ancestor", &upstream_sha, &local_sha])
        .output()
        .map_err(|e| ShipError::GitFailed(format!("Failed to run git merge-base: {}", e)))?;

    match ancestor_check.status.code() {
        Some(0) => Ok(()),
        Some(1) => Err(ShipError::BehindRemote),
        _ => {
            let stderr = String::from_utf8_lossy(&ancestor_check.stderr);
            Err(ShipError::GitFailed(format!(
                "git merge-base --is-ancestor failed: {}",
                stderr.trim()
            )))
        }
    }
}

/// Check if the LLM CLI tool is available.
fn check_llm_available(selection: ProviderSelection, verbose: bool) -> bool {
    let primary_ok = check_provider_available(selection.primary, verbose);
    let fallback_ok = check_provider_available(selection.fallback, verbose);
    primary_ok || fallback_ok
}

fn check_provider_available(provider: Provider, verbose: bool) -> bool {
    let tool_name = match provider {
        Provider::Claude => "claude",
        Provider::Codex => "codex",
    };

    match which::which(tool_name) {
        Ok(_) => {
            if verbose {
                eprintln!("  LLM provider {} CLI found", provider);
            }
            true
        }
        Err(_) => {
            if verbose {
                eprintln!("  LLM provider {} CLI not found", provider);
            }
            false
        }
    }
}

/// Check if a tag already exists.
pub fn check_tag_exists(repo: &Repository, tag_name: &str) -> Result<bool, ShipError> {
    let tags = get_all_tags(repo).map_err(|e| ShipError::GitFailed(e.to_string()))?;
    Ok(tags.iter().any(|t| t.name == tag_name))
}
