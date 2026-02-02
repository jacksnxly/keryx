//! Commit message generation via LLM and git staging/commit operations.

use git2::{IndexAddOption, Oid, Repository};
use serde::Deserialize;
use tracing::debug;

use crate::commit::diff::DiffSummary;
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
    /// Keep a Changelog category: "added", "changed", "fixed", "removed",
    /// "deprecated", "security", or None for internal-only changes.
    pub changelog_category: Option<String>,
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

        // Body (if present)
        let has_body = self.body.as_ref().is_some_and(|b| !b.trim().is_empty());
        if has_body {
            parts.push(String::new()); // blank line
            parts.push(self.body.as_ref().unwrap().trim().to_string());
        }

        // Trailers
        let mut trailers = Vec::new();
        if let Some(ref cat) = self.changelog_category {
            trailers.push(format!("Changelog: {cat}"));
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
            // Wrap in LlmError via a provider error on the active provider
            debug!("Failed to parse LLM response as CommitMessage: {}", e);
            debug!("Raw response: {}", &completion.output);
            // We return an LlmError by constructing it manually
            LlmError::AllProvidersFailed {
                primary: completion.provider,
                primary_error: crate::llm::router::LlmProviderError::Claude(
                    crate::error::ClaudeError::InvalidJson(format!(
                        "Could not parse commit message JSON: {}. Response: {}",
                        e,
                        &completion.output[..completion.output.len().min(200)]
                    )),
                ),
                fallback: completion.provider,
                fallback_error: crate::llm::router::LlmProviderError::Claude(
                    crate::error::ClaudeError::InvalidJson("Parse failure (see primary)".to_string()),
                ),
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

    // Get the parent commit (HEAD)
    let parent = repo
        .head()
        .and_then(|h| h.peel_to_commit())
        .map_err(CommitError::CommitFailed)?;

    // Create the commit
    let oid = repo
        .commit(Some("HEAD"), &sig, &sig, message, &tree, &[&parent])
        .map_err(CommitError::CommitFailed)?;

    Ok(oid)
}

#[cfg(test)]
mod tests {
    use super::*;
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
            changelog_category: Some("fixed".to_string()),
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
            changelog_category: Some("fixed".to_string()),
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
            changelog_category: Some("added".to_string()),
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
        assert_eq!(msg.changelog_category.unwrap(), "added");
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
