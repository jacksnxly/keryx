//! Git operations for the ship pipeline: commit, tag, push, and rollback.
//!
//! All operations use `std::process::Command` to shell out to the system `git`
//! binary, inheriting the user's existing git config, SSH agent, and credential store.

use std::path::PathBuf;
use std::process::Command;

use crate::error::ShipError;

/// Stage files, create a release commit (if needed), and tag it.
///
/// Steps:
/// 1. `git add <files>` - stage only modified version/changelog files
/// 2. `git commit -m "chore(release): vX.Y.Z"` - create release commit (skipped if no staged changes)
/// 3. `git tag -a vX.Y.Z -m "Release vX.Y.Z"` - create annotated tag
pub struct CommitResult {
    pub commit_created: bool,
}

pub fn commit_and_tag(
    message: &str,
    tag_name: &str,
    files: &[PathBuf],
) -> Result<CommitResult, ShipError> {
    // 1. Stage files
    let file_args: Vec<&str> = files.iter().filter_map(|p| p.to_str()).collect();
    if file_args.is_empty() {
        return Err(ShipError::GitFailed("No files to stage".into()));
    }

    let mut add_args = vec!["add"];
    add_args.extend(file_args);

    run_git(&add_args, "stage files")?;

    // 2. Create commit (if there are staged changes)
    let commit_created = if has_staged_changes()? {
        run_git(&["commit", "-m", message], "create commit")?;
        true
    } else {
        false
    };

    // 3. Create annotated tag so --follow-tags will push it
    let tag_message = format!("Release {}", tag_name);
    run_git(&["tag", "-a", tag_name, "-m", &tag_message], "create tag")?;

    Ok(CommitResult { commit_created })
}

/// Push commits and tags atomically.
pub fn push_with_tags(remote: &str, branch: &str) -> Result<(), ShipError> {
    // Push with tags (atomic to avoid partial updates)
    match run_git(
        &["push", remote, branch, "--follow-tags", "--atomic"],
        "push",
    ) {
        Ok(()) => Ok(()),
        Err(e) => Err(ShipError::PushFailed(e.to_string())),
    }
}

/// Roll back a failed release: delete the local tag and undo the release commit.
///
/// Uses `--soft` reset so the version bump changes stay staged.
pub fn rollback(tag_name: &str, commit_created: bool) -> Result<(), ShipError> {
    // 1. Delete local tag
    if let Err(e) = run_git(&["tag", "-d", tag_name], "delete tag") {
        return Err(ShipError::RollbackFailed(format!(
            "Failed to delete tag {}: {}",
            tag_name, e
        )));
    }

    // 2. Undo the release commit (keep changes staged) if we created one
    if commit_created {
        if let Err(e) = run_git(&["reset", "--soft", "HEAD~1"], "reset commit") {
            return Err(ShipError::RollbackFailed(format!(
                "Failed to reset commit: {}",
                e
            )));
        }
    }

    Ok(())
}

/// Return true if there are staged changes (git diff --cached --quiet).
fn has_staged_changes() -> Result<bool, ShipError> {
    let output = Command::new("git")
        .args(["diff", "--cached", "--quiet"])
        .output()
        .map_err(|e| {
            ShipError::GitFailed(format!(
                "Failed to run git check for staged changes: {}",
                e
            ))
        })?;

    if output.status.success() {
        return Ok(false);
    }

    if output.status.code() == Some(1) {
        return Ok(true);
    }

    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(ShipError::GitFailed(format!(
        "git check for staged changes failed: {}",
        stderr.trim()
    )))
}

/// Run a git command and return success or a descriptive error.
fn run_git(args: &[&str], operation: &str) -> Result<(), ShipError> {
    let output = Command::new("git")
        .args(args)
        .output()
        .map_err(|e| ShipError::GitFailed(format!("Failed to run git {}: {}", operation, e)))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ShipError::GitFailed(format!(
            "git {} failed: {}",
            operation,
            stderr.trim()
        )));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_run_git_version_succeeds() {
        // git --version should always succeed
        let result = run_git(&["--version"], "version check");
        assert!(result.is_ok());
    }

    #[test]
    fn test_run_git_invalid_command_fails() {
        let result = run_git(&["not-a-real-command"], "invalid");
        assert!(result.is_err());
    }
}
