//! Commit message generation via LLM and git staging/commit operations.

use std::collections::HashMap;
use std::path::Path;

use git2::{ErrorCode, IndexAddOption, Oid, Repository};
use serde::Deserialize;
use tracing::debug;

use crate::changelog::ChangelogCategory;
use crate::commit::diff::{ChangedFile, DiffSummary, FileStatus};
use crate::commit::prompt::build_commit_prompt;
use crate::error::CommitError;
use crate::llm::extract_json;
use crate::llm::router::{LlmError, LlmRawCompletion, LlmRouter};

/// A parsed commit message from the LLM.
#[derive(Debug, Clone, Deserialize)]
pub struct CommitMessage {
    pub subject: String,
    pub body: Option<String>,
    #[serde(default)]
    pub breaking: bool,
    /// Keep a Changelog category, or None for internal-only changes.
    pub changelog_category: Option<ChangelogCategory>,
    /// User-facing description for the changelog, written for end users.
    /// None when changelog_category is None (internal change).
    pub changelog_description: Option<String>,
}

impl CommitMessage {
    /// Format the commit message for git, including Git trailers.
    ///
    /// Produces:
    /// ```text
    /// type(scope): subject
    ///
    /// Body text explaining why.
    ///
    /// Changelog: added
    /// Changelog-Description: User-facing description here
    /// ```
    pub fn format(&self) -> String {
        let mut parts = Vec::new();

        // Subject
        parts.push(self.subject.clone());

        // Body (if present and non-empty)
        if let Some(body) = self.body.as_deref().filter(|b| !b.trim().is_empty()) {
            parts.push(String::new()); // blank line
            parts.push(body.trim().to_string());
        }

        // Trailers
        let mut trailers = Vec::new();
        if let Some(ref cat) = self.changelog_category {
            trailers.push(format!("Changelog: {}", cat.as_str().to_lowercase()));
        }
        if let Some(ref desc) = self.changelog_description {
            trailers.push(format!("Changelog-Description: {desc}"));
        }

        if !trailers.is_empty() {
            parts.push(String::new()); // blank line before trailers
            parts.extend(trailers);
        }

        parts.join("\n")
    }

    /// Whether this change is user-facing (has a changelog category).
    pub fn is_user_facing(&self) -> bool {
        self.changelog_category.is_some()
    }
}

/// Generate a commit message from the diff using the LLM.
pub async fn generate_commit_message(
    diff: &DiffSummary,
    branch_name: &str,
    llm: &mut LlmRouter,
    verbose: bool,
) -> Result<(CommitMessage, LlmRawCompletion), LlmError> {
    let prompt = build_commit_prompt(diff, branch_name);

    if verbose {
        debug!("Commit prompt length: {} chars", prompt.len());
        debug!(
            "Diff: {} files, {} additions, {} deletions, truncated={}",
            diff.changed_files.len(),
            diff.additions,
            diff.deletions,
            diff.truncated
        );
    }

    let completion = llm.generate_raw(&prompt).await?;

    let json_str = extract_json(&completion.output);
    let message: CommitMessage = serde_json::from_str(&json_str)
        .map_err(|e| {
            debug!("Failed to parse LLM response as CommitMessage: {}", e);
            debug!("Raw response: {}", &completion.output);

            LlmError::ResponseParseFailed {
                provider: completion.provider,
                raw_output: completion.output.clone(),
                parse_error: format!("Could not parse commit message JSON: {}", e),
            }
        })?;

    Ok((message, completion))
}

/// Stage all changes and create a commit.
///
/// Uses `index.add_all()` to stage everything (like `git add -A`),
/// then creates a commit on HEAD with the given message.
pub fn stage_and_commit(repo: &Repository, message: &str) -> Result<Oid, CommitError> {
    // Stage all changes
    let mut index = repo.index().map_err(CommitError::StagingFailed)?;
    index
        .add_all(["*"].iter(), IndexAddOption::DEFAULT, None)
        .map_err(CommitError::StagingFailed)?;
    index.write().map_err(CommitError::StagingFailed)?;

    // Write the index as a tree
    let tree_id = index.write_tree().map_err(CommitError::StagingFailed)?;
    let tree = repo.find_tree(tree_id).map_err(CommitError::CommitFailed)?;

    // Get the signature from git config
    let sig = repo
        .signature()
        .map_err(CommitError::ConfigError)?;

    let parent = resolve_parent_commit(repo)?;
    let mut parents = Vec::new();
    if let Some(ref parent) = parent {
        parents.push(parent);
    }

    // Create the commit
    let oid = repo
        .commit(Some("HEAD"), &sig, &sig, message, &tree, &parents)
        .map_err(CommitError::CommitFailed)?;

    Ok(oid)
}

/// Stage specific file paths and create a commit.
///
/// Unlike [`stage_and_commit`] which stages everything, this function uses
/// `index.add_path()` for each file individually, and `index.remove_path()`
/// for deleted files (detected via the `file_statuses` map).
///
/// HEAD advances after each call, so subsequent calls for remaining groups
/// see the correct parent automatically.
pub fn stage_paths_and_commit(
    repo: &Repository,
    paths: &[String],
    file_changes: &HashMap<String, ChangedFile>,
    message: &str,
) -> Result<Oid, CommitError> {
    let mut index = repo.index().map_err(CommitError::StagingFailed)?;

    for path in paths {
        let change = file_changes.get(path.as_str());
        let status = change.map(|c| &c.status);
        if matches!(status, Some(FileStatus::Deleted)) {
            index
                .remove_path(Path::new(path))
                .map_err(CommitError::StagingFailed)?;
            continue;
        }

        if matches!(status, Some(FileStatus::Renamed)) {
            if let Some(old_path) = change.and_then(|c| c.old_path.as_deref()) {
                if old_path != path {
                    index
                        .remove_path(Path::new(old_path))
                        .map_err(CommitError::StagingFailed)?;
                }
            }
        }

        index
            .add_path(Path::new(path))
            .map_err(CommitError::StagingFailed)?;
    }

    index.write().map_err(CommitError::StagingFailed)?;

    let tree_id = index.write_tree().map_err(CommitError::StagingFailed)?;
    let tree = repo.find_tree(tree_id).map_err(CommitError::CommitFailed)?;

    let sig = repo.signature().map_err(CommitError::ConfigError)?;

    let parent = resolve_parent_commit(repo)?;
    let mut parents = Vec::new();
    if let Some(ref parent) = parent {
        parents.push(parent);
    }

    let oid = repo
        .commit(Some("HEAD"), &sig, &sig, message, &tree, &parents)
        .map_err(CommitError::CommitFailed)?;

    Ok(oid)
}

fn resolve_parent_commit(repo: &Repository) -> Result<Option<git2::Commit<'_>>, CommitError> {
    match repo.head() {
        Ok(head) => Ok(Some(head.peel_to_commit().map_err(CommitError::CommitFailed)?)),
        Err(e) if e.code() == ErrorCode::UnbornBranch || e.code() == ErrorCode::NotFound => {
            Ok(None)
        }
        Err(e) => Err(CommitError::CommitFailed(e)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::changelog::ChangelogCategory;
    use git2::Signature;

    #[test]
    fn test_commit_message_format_subject_only() {
        let msg = CommitMessage {
            subject: "feat(auth): add login endpoint".to_string(),
            body: None,
            breaking: false,
            changelog_category: None,
            changelog_description: None,
        };
        assert_eq!(msg.format(), "feat(auth): add login endpoint");
    }

    #[test]
    fn test_commit_message_format_with_body() {
        let msg = CommitMessage {
            subject: "fix(parser): resolve memory leak".to_string(),
            body: Some("The parser was holding references to\nalready-freed buffers.".to_string()),
            breaking: false,
            changelog_category: Some(ChangelogCategory::Fixed),
            changelog_description: Some("Fix memory leak in parser".to_string()),
        };
        let formatted = msg.format();
        assert!(formatted.starts_with("fix(parser): resolve memory leak"));
        assert!(formatted.contains("\n\n"));
        assert!(formatted.contains("already-freed buffers"));
        assert!(formatted.contains("Changelog: fixed"));
        assert!(formatted.contains("Changelog-Description: Fix memory leak in parser"));
    }

    #[test]
    fn test_commit_message_format_empty_body() {
        let msg = CommitMessage {
            subject: "chore: bump deps".to_string(),
            body: Some("  ".to_string()),
            breaking: false,
            changelog_category: None,
            changelog_description: None,
        };
        // Empty/whitespace body and no trailers → subject only
        assert_eq!(msg.format(), "chore: bump deps");
    }

    #[test]
    fn test_commit_message_format_with_trailers_no_body() {
        let msg = CommitMessage {
            subject: "fix(api): handle timeout".to_string(),
            body: None,
            breaking: false,
            changelog_category: Some(ChangelogCategory::Fixed),
            changelog_description: Some("Fix API timeout on large repos".to_string()),
        };
        let formatted = msg.format();
        assert_eq!(
            formatted,
            "fix(api): handle timeout\n\nChangelog: fixed\nChangelog-Description: Fix API timeout on large repos"
        );
    }

    #[test]
    fn test_commit_message_format_internal_no_trailers() {
        let msg = CommitMessage {
            subject: "refactor(auth): extract middleware".to_string(),
            body: Some("No behavior change.".to_string()),
            breaking: false,
            changelog_category: None,
            changelog_description: None,
        };
        let formatted = msg.format();
        assert_eq!(
            formatted,
            "refactor(auth): extract middleware\n\nNo behavior change."
        );
        assert!(!formatted.contains("Changelog"));
    }

    #[test]
    fn test_commit_message_is_user_facing() {
        let user_facing = CommitMessage {
            subject: "feat: new thing".to_string(),
            body: None,
            breaking: false,
            changelog_category: Some(ChangelogCategory::Added),
            changelog_description: Some("Add new thing".to_string()),
        };
        assert!(user_facing.is_user_facing());

        let internal = CommitMessage {
            subject: "refactor: cleanup".to_string(),
            body: None,
            breaking: false,
            changelog_category: None,
            changelog_description: None,
        };
        assert!(!internal.is_user_facing());
    }

    #[test]
    fn test_commit_message_deserialize() {
        let json = r#"{"subject": "feat: add feature", "body": "Details here", "breaking": false, "changelog_category": "added", "changelog_description": "Add feature"}"#;
        let msg: CommitMessage = serde_json::from_str(json).unwrap();
        assert_eq!(msg.subject, "feat: add feature");
        assert_eq!(msg.body.unwrap(), "Details here");
        assert!(!msg.breaking);
        assert_eq!(msg.changelog_category.unwrap(), ChangelogCategory::Added);
        assert_eq!(msg.changelog_description.unwrap(), "Add feature");
    }

    #[test]
    fn test_commit_message_deserialize_null_changelog() {
        let json = r#"{"subject": "refactor: cleanup", "breaking": false, "changelog_category": null, "changelog_description": null}"#;
        let msg: CommitMessage = serde_json::from_str(json).unwrap();
        assert!(msg.changelog_category.is_none());
        assert!(msg.changelog_description.is_none());
    }

    #[test]
    fn test_commit_message_deserialize_no_body() {
        let json = r#"{"subject": "fix: typo", "breaking": false}"#;
        let msg: CommitMessage = serde_json::from_str(json).unwrap();
        assert_eq!(msg.subject, "fix: typo");
        assert!(msg.body.is_none());
    }

    #[test]
    fn test_commit_message_deserialize_breaking_default() {
        let json = r#"{"subject": "feat: new api"}"#;
        let msg: CommitMessage = serde_json::from_str(json).unwrap();
        assert!(!msg.breaking);
    }

    #[test]
    fn test_commit_message_deserialize_invalid_category_fails() {
        let json = r#"{"subject": "feat: thing", "changelog_category": "enhanced", "changelog_description": "Something"}"#;
        let result = serde_json::from_str::<CommitMessage>(json);
        assert!(result.is_err(), "Invalid changelog category should fail deserialization");
    }

    #[test]
    fn test_stage_paths_and_commit_selective_staging() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        let mut config = repo.config().unwrap();
        config.set_str("user.name", "Test User").unwrap();
        config.set_str("user.email", "test@test.com").unwrap();

        // Create initial commit
        let sig = Signature::now("Test User", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[])
            .unwrap();

        // Create 3 new files
        std::fs::write(dir.path().join("a.txt"), "file a\n").unwrap();
        std::fs::write(dir.path().join("b.txt"), "file b\n").unwrap();
        std::fs::write(dir.path().join("c.txt"), "file c\n").unwrap();

        // Stage only a.txt and b.txt
        let mut statuses = std::collections::HashMap::new();
        statuses.insert(
            "a.txt".to_string(),
            ChangedFile {
                path: "a.txt".to_string(),
                status: FileStatus::Added,
                old_path: None,
            },
        );
        statuses.insert(
            "b.txt".to_string(),
            ChangedFile {
                path: "b.txt".to_string(),
                status: FileStatus::Added,
                old_path: None,
            },
        );

        let paths = vec!["a.txt".to_string(), "b.txt".to_string()];
        let oid = stage_paths_and_commit(&repo, &paths, &statuses, "feat: add a and b").unwrap();
        let commit = repo.find_commit(oid).unwrap();
        assert_eq!(commit.message().unwrap(), "feat: add a and b");

        // Verify a.txt and b.txt are in the committed tree
        let tree = commit.tree().unwrap();
        assert!(tree.get_name("a.txt").is_some());
        assert!(tree.get_name("b.txt").is_some());
        // c.txt should NOT be in the committed tree
        assert!(tree.get_name("c.txt").is_none());
    }

    #[test]
    fn test_stage_paths_and_commit_sequential_multi_commit() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        let mut config = repo.config().unwrap();
        config.set_str("user.name", "Test User").unwrap();
        config.set_str("user.email", "test@test.com").unwrap();

        // Create initial commit
        let sig = Signature::now("Test User", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[])
            .unwrap();

        // Create files
        std::fs::write(dir.path().join("a.txt"), "file a\n").unwrap();
        std::fs::write(dir.path().join("b.txt"), "file b\n").unwrap();

        let mut statuses = std::collections::HashMap::new();
        statuses.insert(
            "a.txt".to_string(),
            ChangedFile {
                path: "a.txt".to_string(),
                status: FileStatus::Added,
                old_path: None,
            },
        );
        statuses.insert(
            "b.txt".to_string(),
            ChangedFile {
                path: "b.txt".to_string(),
                status: FileStatus::Added,
                old_path: None,
            },
        );

        // First commit: a.txt
        let oid1 = stage_paths_and_commit(
            &repo,
            &["a.txt".to_string()],
            &statuses,
            "feat: add a",
        )
        .unwrap();

        // Second commit: b.txt — HEAD should have advanced
        let oid2 = stage_paths_and_commit(
            &repo,
            &["b.txt".to_string()],
            &statuses,
            "feat: add b",
        )
        .unwrap();

        assert_ne!(oid1, oid2);

        // Verify second commit's parent is the first commit
        let commit2 = repo.find_commit(oid2).unwrap();
        assert_eq!(commit2.parent_id(0).unwrap(), oid1);
    }

    #[test]
    fn test_stage_paths_and_commit_deleted_file() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        let mut config = repo.config().unwrap();
        config.set_str("user.name", "Test User").unwrap();
        config.set_str("user.email", "test@test.com").unwrap();

        // Create a file and commit it
        let file_path = dir.path().join("to_delete.txt");
        std::fs::write(&file_path, "will be deleted\n").unwrap();
        let mut index = repo.index().unwrap();
        index
            .add_path(std::path::Path::new("to_delete.txt"))
            .unwrap();
        index.write().unwrap();
        let tree_id = index.write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        let sig = Signature::now("Test User", "test@test.com").unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init with file", &tree, &[])
            .unwrap();

        // Delete the file from disk
        std::fs::remove_file(&file_path).unwrap();

        let mut statuses = std::collections::HashMap::new();
        statuses.insert(
            "to_delete.txt".to_string(),
            ChangedFile {
                path: "to_delete.txt".to_string(),
                status: FileStatus::Deleted,
                old_path: None,
            },
        );

        let oid = stage_paths_and_commit(
            &repo,
            &["to_delete.txt".to_string()],
            &statuses,
            "fix: remove deprecated file",
        )
        .unwrap();

        let commit = repo.find_commit(oid).unwrap();
        let tree = commit.tree().unwrap();
        assert!(tree.get_name("to_delete.txt").is_none());
    }

    #[test]
    fn test_stage_paths_and_commit_rename_removes_old_path() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        let mut config = repo.config().unwrap();
        config.set_str("user.name", "Test User").unwrap();
        config.set_str("user.email", "test@test.com").unwrap();

        // Create a file and commit it
        let old_path = dir.path().join("old.txt");
        std::fs::write(&old_path, "original\n").unwrap();
        let mut index = repo.index().unwrap();
        index.add_path(std::path::Path::new("old.txt")).unwrap();
        index.write().unwrap();
        let tree_id = index.write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        let sig = Signature::now("Test User", "test@test.com").unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init with file", &tree, &[])
            .unwrap();

        // Rename on disk
        let new_path = dir.path().join("new.txt");
        std::fs::rename(&old_path, &new_path).unwrap();

        let mut statuses = std::collections::HashMap::new();
        statuses.insert(
            "new.txt".to_string(),
            ChangedFile {
                path: "new.txt".to_string(),
                status: FileStatus::Renamed,
                old_path: Some("old.txt".to_string()),
            },
        );

        let oid = stage_paths_and_commit(
            &repo,
            &["new.txt".to_string()],
            &statuses,
            "refactor: rename old to new",
        )
        .unwrap();

        let commit = repo.find_commit(oid).unwrap();
        let tree = commit.tree().unwrap();
        assert!(tree.get_name("new.txt").is_some());
        assert!(tree.get_name("old.txt").is_none());
    }

    #[test]
    fn test_stage_and_commit_initial_commit() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Set up git config for the test repo
        let mut config = repo.config().unwrap();
        config.set_str("user.name", "Test User").unwrap();
        config.set_str("user.email", "test@test.com").unwrap();

        // Create a new file in an empty repo
        std::fs::write(dir.path().join("test.txt"), "hello\n").unwrap();

        let oid = stage_and_commit(&repo, "feat: initial commit").unwrap();
        let commit = repo.find_commit(oid).unwrap();
        assert_eq!(commit.parent_count(), 0);
    }

    #[test]
    fn test_stage_paths_and_commit_initial_commit() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        let mut config = repo.config().unwrap();
        config.set_str("user.name", "Test User").unwrap();
        config.set_str("user.email", "test@test.com").unwrap();

        std::fs::write(dir.path().join("test.txt"), "hello\n").unwrap();

        let mut statuses = std::collections::HashMap::new();
        statuses.insert(
            "test.txt".to_string(),
            ChangedFile {
                path: "test.txt".to_string(),
                status: FileStatus::Added,
                old_path: None,
            },
        );

        let oid = stage_paths_and_commit(
            &repo,
            &["test.txt".to_string()],
            &statuses,
            "feat: initial commit",
        )
        .unwrap();

        let commit = repo.find_commit(oid).unwrap();
        assert_eq!(commit.parent_count(), 0);
    }

    #[test]
    fn test_stage_and_commit_on_repo_with_changes() {
        let dir = tempfile::tempdir().unwrap();
        let repo = Repository::init(dir.path()).unwrap();

        // Set up git config for the test repo
        let mut config = repo.config().unwrap();
        config.set_str("user.name", "Test User").unwrap();
        config.set_str("user.email", "test@test.com").unwrap();

        // Create initial commit
        let sig = Signature::now("Test User", "test@test.com").unwrap();
        let tree_id = repo.index().unwrap().write_tree().unwrap();
        let tree = repo.find_tree(tree_id).unwrap();
        repo.commit(Some("HEAD"), &sig, &sig, "init", &tree, &[])
            .unwrap();

        // Create a new file
        std::fs::write(dir.path().join("test.txt"), "hello\n").unwrap();

        let oid = stage_and_commit(&repo, "feat: add test file").unwrap();
        let commit = repo.find_commit(oid).unwrap();
        assert_eq!(commit.message().unwrap(), "feat: add test file");
    }
}
