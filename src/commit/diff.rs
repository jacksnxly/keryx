//! Diff collection from the working tree using git2.

use std::fmt;

use git2::{Delta, Diff, DiffFormat, DiffOptions, ErrorCode, Repository, Tree};
use tracing::warn;

use crate::error::CommitError;

/// Maximum characters for the unified diff text before truncation.
const MAX_DIFF_LENGTH: usize = 30_000;

/// Status of a changed file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FileStatus {
    Added,
    Modified,
    Deleted,
    Renamed,
}

impl fmt::Display for FileStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FileStatus::Added => write!(f, "Added"),
            FileStatus::Modified => write!(f, "Modified"),
            FileStatus::Deleted => write!(f, "Deleted"),
            FileStatus::Renamed => write!(f, "Renamed"),
        }
    }
}

/// A file that was changed in the working tree.
#[derive(Debug, Clone)]
pub struct ChangedFile {
    pub path: String,
    pub status: FileStatus,
    /// Old path for renamed files (None for non-rename changes).
    pub old_path: Option<String>,
}

/// Summary of changes in the working tree.
#[derive(Debug, Clone)]
pub struct DiffSummary {
    pub diff_text: String,
    pub changed_files: Vec<ChangedFile>,
    pub truncated: bool,
    pub additions: usize,
    pub deletions: usize,
}

/// Resolve the HEAD tree, distinguishing empty-repo errors from real failures.
///
/// Returns `Ok(None)` for repos with no commits (unborn branch / not found),
/// `Ok(Some(tree))` for repos with a valid HEAD, or `Err(CommitError::DiffFailed)`
/// for real errors (corrupt HEAD, permission issues, missing objects).
fn resolve_head_tree(repo: &Repository) -> Result<Option<Tree<'_>>, CommitError> {
    let head_ref = match repo.head() {
        Ok(r) => r,
        Err(e)
            if e.code() == ErrorCode::UnbornBranch || e.code() == ErrorCode::NotFound =>
        {
            return Ok(None);
        }
        Err(e) => return Err(CommitError::DiffFailed(e)),
    };

    let tree = head_ref.peel_to_tree().map_err(CommitError::DiffFailed)?;
    Ok(Some(tree))
}

/// Collect the working tree diff scoped to specific file paths.
///
/// Same logic as [`collect_diff`] but uses `DiffOptions::pathspec()` to restrict
/// both staged and unstaged diffs to only the given paths.
pub fn collect_diff_for_paths(
    repo: &Repository,
    paths: &[String],
) -> Result<DiffSummary, CommitError> {
    let head_tree = resolve_head_tree(repo)?;

    // Staged changes with pathspec filter
    let mut staged_opts = DiffOptions::new();
    for p in paths {
        staged_opts.pathspec(p);
    }
    let staged_diff = repo
        .diff_tree_to_index(head_tree.as_ref(), None, Some(&mut staged_opts))
        .map_err(CommitError::DiffFailed)?;

    // Unstaged + untracked changes with pathspec filter
    let mut unstaged_opts = DiffOptions::new();
    unstaged_opts.include_untracked(true).recurse_untracked_dirs(true);
    for p in paths {
        unstaged_opts.pathspec(p);
    }
    let unstaged_diff = repo
        .diff_index_to_workdir(None, Some(&mut unstaged_opts))
        .map_err(CommitError::DiffFailed)?;

    build_summary(&staged_diff, &unstaged_diff)
}

/// Collect the working tree diff (staged + unstaged + untracked).
///
/// Merges `diff_tree_to_index` (staged changes) with `diff_index_to_workdir`
/// (unstaged changes including untracked files) to capture all pending changes.
pub fn collect_diff(repo: &Repository) -> Result<DiffSummary, CommitError> {
    let head_tree = resolve_head_tree(repo)?;

    let staged_diff = repo
        .diff_tree_to_index(head_tree.as_ref(), None, None)
        .map_err(CommitError::DiffFailed)?;

    let mut opts = DiffOptions::new();
    opts.include_untracked(true)
        .recurse_untracked_dirs(true);
    let unstaged_diff = repo
        .diff_index_to_workdir(None, Some(&mut opts))
        .map_err(CommitError::DiffFailed)?;

    build_summary(&staged_diff, &unstaged_diff)
}

/// Merge staged and unstaged diffs into a single [`DiffSummary`].
///
/// Collects changed files from both diffs, deduplicates by path (staged takes
/// precedence), and assembles the unified diff text with addition/deletion counts.
fn build_summary(staged: &Diff<'_>, unstaged: &Diff<'_>) -> Result<DiffSummary, CommitError> {
    let mut changed_files = Vec::new();
    collect_files_from_diff(staged, &mut changed_files);
    collect_files_from_diff(unstaged, &mut changed_files);

    changed_files.sort_by(|a, b| a.path.cmp(&b.path));
    changed_files.dedup_by(|a, b| a.path == b.path);

    if changed_files.is_empty() {
        return Err(CommitError::NoChanges);
    }

    let mut diff_text = String::new();
    let mut additions = 0usize;
    let mut deletions = 0usize;
    let mut truncated = false;

    append_diff_text(staged, &mut diff_text, &mut additions, &mut deletions, &mut truncated);
    if !truncated {
        append_diff_text(unstaged, &mut diff_text, &mut additions, &mut deletions, &mut truncated);
    }

    Ok(DiffSummary {
        diff_text,
        changed_files,
        truncated,
        additions,
        deletions,
    })
}

/// Collect changed file entries from a diff.
fn collect_files_from_diff(diff: &Diff<'_>, files: &mut Vec<ChangedFile>) {
    for delta_idx in 0..diff.deltas().len() {
        let delta = diff.get_delta(delta_idx).unwrap();
        let status = match delta.status() {
            Delta::Added | Delta::Untracked => FileStatus::Added,
            Delta::Modified => FileStatus::Modified,
            Delta::Deleted => FileStatus::Deleted,
            Delta::Renamed => FileStatus::Renamed,
            _ => FileStatus::Modified,
        };

        let new_path = delta
            .new_file()
            .path()
            .map(|p| p.to_string_lossy().to_string());
        let old_path = delta
            .old_file()
            .path()
            .map(|p| p.to_string_lossy().to_string());

        let (path, old_path) = match status {
            FileStatus::Renamed => {
                let path = new_path
                    .clone()
                    .or_else(|| old_path.clone())
                    .unwrap_or_default();
                (path, old_path)
            }
            _ => {
                let path = new_path.or(old_path).unwrap_or_default();
                (path, None)
            }
        };

        if !path.is_empty() {
            files.push(ChangedFile { path, status, old_path });
        }
    }
}

/// Append unified diff text from a diff object, respecting the max length.
fn append_diff_text(
    diff: &Diff<'_>,
    text: &mut String,
    additions: &mut usize,
    deletions: &mut usize,
    truncated: &mut bool,
) {
    if *truncated {
        return;
    }

    if let Err(e) = diff.print(DiffFormat::Patch, |_delta, _hunk, line| {
        if *truncated {
            return true;
        }

        match line.origin() {
            '+' => *additions += 1,
            '-' => *deletions += 1,
            _ => {}
        }

        let content = std::str::from_utf8(line.content()).unwrap_or("");

        // Check if adding this line would exceed the limit
        if text.len() + content.len() + 2 > MAX_DIFF_LENGTH {
            *truncated = true;
            return true;
        }

        // Include the origin character for context
        let origin = line.origin();
        if origin == '+' || origin == '-' || origin == ' ' {
            text.push(origin);
        }
        text.push_str(content);

        true
    }) {
        warn!("Failed to collect diff text: {e}");
        *truncated = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_file_status_display() {
        assert_eq!(FileStatus::Added.to_string(), "Added");
        assert_eq!(FileStatus::Modified.to_string(), "Modified");
        assert_eq!(FileStatus::Deleted.to_string(), "Deleted");
        assert_eq!(FileStatus::Renamed.to_string(), "Renamed");
    }

    #[test]
    fn test_collect_diff_on_clean_repo_returns_no_changes() {
        // Use a temp dir with a fresh git repo
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create an initial commit so HEAD exists
        let sig = git2::Signature::now("Test", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[]).unwrap();

        let result = collect_diff(&repo);
        assert!(matches!(result, Err(CommitError::NoChanges)));
    }

    #[test]
    fn test_collect_diff_detects_new_file() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create initial commit
        let sig = git2::Signature::now("Test", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[]).unwrap();

        // Create a new file (untracked)
        std::fs::write(dir.path().join("new.txt"), "hello world\n").unwrap();

        let summary = collect_diff(&repo).unwrap();
        assert!(!summary.changed_files.is_empty());
        assert!(summary.changed_files.iter().any(|f| f.path == "new.txt" && f.status == FileStatus::Added));
    }

    #[test]
    fn test_collect_diff_for_paths_filters_correctly() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create initial commit
        let sig = git2::Signature::now("Test", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[]).unwrap();

        // Create 3 files
        std::fs::write(dir.path().join("a.txt"), "file a\n").unwrap();
        std::fs::write(dir.path().join("b.txt"), "file b\n").unwrap();
        std::fs::write(dir.path().join("c.txt"), "file c\n").unwrap();

        // Request diff for only 2 of them
        let paths = vec!["a.txt".to_string(), "c.txt".to_string()];
        let summary = collect_diff_for_paths(&repo, &paths).unwrap();

        assert_eq!(summary.changed_files.len(), 2);
        let file_names: Vec<&str> = summary.changed_files.iter().map(|f| f.path.as_str()).collect();
        assert!(file_names.contains(&"a.txt"));
        assert!(file_names.contains(&"c.txt"));
        assert!(!file_names.contains(&"b.txt"));
    }

    #[test]
    fn test_collect_diff_for_paths_empty_returns_no_changes() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create initial commit
        let sig = git2::Signature::now("Test", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[]).unwrap();

        // Create a file but request diff for a non-existent path
        std::fs::write(dir.path().join("a.txt"), "file a\n").unwrap();
        let paths = vec!["nonexistent.txt".to_string()];
        let result = collect_diff_for_paths(&repo, &paths);
        assert!(matches!(result, Err(CommitError::NoChanges)));
    }

    #[test]
    fn test_collect_diff_empty_repo_returns_none_head_tree() {
        // An empty repo (no commits) should not error — head_tree should be None
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create a file so there's something to diff
        std::fs::write(dir.path().join("new.txt"), "hello\n").unwrap();

        let summary = collect_diff(&repo).unwrap();
        assert!(summary.changed_files.iter().any(|f| f.path == "new.txt"));
    }

    #[test]
    fn test_collect_diff_includes_binary_files() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create a binary file (includes NUL byte)
        let binary_path = dir.path().join("image.bin");
        std::fs::write(&binary_path, [0u8, 159, 146, 150]).unwrap();

        let summary = collect_diff(&repo).unwrap();
        assert!(summary.changed_files.iter().any(|f| f.path == "image.bin"));
    }

    #[test]
    fn test_collect_diff_corrupt_head_propagates_error() {
        // A corrupt HEAD should propagate as CommitError::DiffFailed, not silently produce None
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create an initial commit so HEAD exists
        let sig = git2::Signature::now("Test", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[]).unwrap();

        // Corrupt HEAD by pointing it to a non-existent ref
        std::fs::write(dir.path().join(".git/HEAD"), "ref: refs/heads/\0invalid").unwrap();

        // Re-open the repo to pick up the corrupt HEAD
        let repo = Repository::open(dir.path()).unwrap();
        let result = collect_diff(&repo);
        assert!(
            matches!(result, Err(CommitError::DiffFailed(_))),
            "Expected DiffFailed for corrupt HEAD, got: {:?}",
            result
        );
    }

    #[test]
    fn test_collect_diff_for_paths_corrupt_head_propagates_error() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create an initial commit so HEAD exists
        let sig = git2::Signature::now("Test", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[]).unwrap();

        // Corrupt HEAD
        std::fs::write(dir.path().join(".git/HEAD"), "ref: refs/heads/\0invalid").unwrap();

        let repo = Repository::open(dir.path()).unwrap();
        let paths = vec!["file.txt".to_string()];
        let result = collect_diff_for_paths(&repo, &paths);
        assert!(
            matches!(result, Err(CommitError::DiffFailed(_))),
            "Expected DiffFailed for corrupt HEAD, got: {:?}",
            result
        );
    }

    #[test]
    fn test_collect_diff_detects_staged_modification() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Create a file and commit it
        let file_path = dir.path().join("file.txt");
        std::fs::write(&file_path, "original\n").unwrap();
        let mut index = repo.index().unwrap();
        index.add_path(std::path::Path::new("file.txt")).unwrap();
        index.write().unwrap();
        let tree_id = index.write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        let sig = git2::Signature::now("Test", "test@test.com").unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[]).unwrap();

        // Modify and stage the file
        std::fs::write(&file_path, "modified\n").unwrap();
        let mut index = repo.index().unwrap();
        index.add_path(std::path::Path::new("file.txt")).unwrap();
        index.write().unwrap();

        let summary = collect_diff(&repo).unwrap();
        assert!(summary.changed_files.iter().any(|f| f.path == "file.txt" && f.status == FileStatus::Modified));
        assert!(summary.diff_text.contains("modified"));
    }
}
