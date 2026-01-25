//! Commit fetching and conventional commit parsing.

use chrono::{DateTime, TimeZone, Utc};
use git2::{Commit, Repository};
use serde::{Deserialize, Serialize};

use crate::error::GitError;

/// Conventional commit types.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CommitType {
    Feat,
    Fix,
    Docs,
    Style,
    Refactor,
    Perf,
    Test,
    Build,
    Ci,
    Chore,
}

impl std::str::FromStr for CommitType {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "feat" => Ok(Self::Feat),
            "fix" => Ok(Self::Fix),
            "docs" => Ok(Self::Docs),
            "style" => Ok(Self::Style),
            "refactor" => Ok(Self::Refactor),
            "perf" => Ok(Self::Perf),
            "test" => Ok(Self::Test),
            "build" => Ok(Self::Build),
            "ci" => Ok(Self::Ci),
            "chore" => Ok(Self::Chore),
            _ => Err(format!("Unknown commit type: {}", s)),
        }
    }
}

/// Represents a commit with conventional commit parsing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedCommit {
    pub hash: String,
    pub message: String,
    pub commit_type: Option<CommitType>,
    pub scope: Option<String>,
    pub breaking: bool,
    pub timestamp: DateTime<Utc>,
}

impl ParsedCommit {
    /// Create a ParsedCommit from a git2 Commit.
    pub fn from_git2_commit(commit: &Commit) -> Result<Self, GitError> {
        let hash = commit.id().to_string();
        let message = commit.message().unwrap_or("").to_string();
        let time = commit.time();
        let timestamp = Utc
            .timestamp_opt(time.seconds(), 0)
            .single()
            .unwrap_or_else(Utc::now);

        let (commit_type, scope, breaking) = parse_commit_message(&message);

        Ok(Self {
            hash,
            message,
            commit_type,
            scope,
            breaking,
            timestamp,
        })
    }
}

/// Parse a conventional commit message.
/// Returns (commit_type, scope, breaking).
pub fn parse_commit_message(message: &str) -> (Option<CommitType>, Option<String>, bool) {
    let first_line = message.lines().next().unwrap_or("");

    // Check for BREAKING CHANGE in footer
    let breaking_in_footer = message.contains("BREAKING CHANGE:") || message.contains("BREAKING-CHANGE:");

    // Pattern: type(scope)!: description or type!: description or type(scope): description or type: description
    let re_pattern = r"^(\w+)(?:\(([^)]+)\))?(!)?\s*:\s*";

    let re = regex_lite::Regex::new(re_pattern).unwrap();

    if let Some(caps) = re.captures(first_line) {
        let type_str = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        let scope = caps.get(2).map(|m| m.as_str().to_string());
        let breaking_mark = caps.get(3).is_some();

        let commit_type = type_str.parse::<CommitType>().ok();
        let breaking = breaking_mark || breaking_in_footer;

        return (commit_type, scope, breaking);
    }

    (None, None, breaking_in_footer)
}

/// Fetch commits from a repository in a given range.
pub fn fetch_commits(
    repo: &Repository,
    from_oid: git2::Oid,
    to_oid: git2::Oid,
) -> Result<Vec<ParsedCommit>, GitError> {
    let mut revwalk = repo.revwalk().map_err(GitError::RevwalkError)?;

    revwalk.push(to_oid).map_err(GitError::RevwalkError)?;
    revwalk.hide(from_oid).map_err(GitError::RevwalkError)?;

    let mut commits = Vec::new();

    for oid_result in revwalk {
        let oid = oid_result.map_err(GitError::RevwalkError)?;
        let commit = repo.find_commit(oid).map_err(GitError::ParseCommit)?;
        let parsed = ParsedCommit::from_git2_commit(&commit)?;
        commits.push(parsed);
    }

    Ok(commits)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_feat_commit() {
        let (ty, scope, breaking) = parse_commit_message("feat: add new feature");
        assert_eq!(ty, Some(CommitType::Feat));
        assert_eq!(scope, None);
        assert!(!breaking);
    }

    #[test]
    fn test_parse_fix_with_scope() {
        let (ty, scope, breaking) = parse_commit_message("fix(auth): resolve login bug");
        assert_eq!(ty, Some(CommitType::Fix));
        assert_eq!(scope, Some("auth".to_string()));
        assert!(!breaking);
    }

    #[test]
    fn test_parse_breaking_with_exclamation() {
        let (ty, scope, breaking) = parse_commit_message("feat!: breaking change");
        assert_eq!(ty, Some(CommitType::Feat));
        assert_eq!(scope, None);
        assert!(breaking);
    }

    #[test]
    fn test_parse_breaking_with_scope_and_exclamation() {
        let (ty, scope, breaking) = parse_commit_message("feat(api)!: breaking api change");
        assert_eq!(ty, Some(CommitType::Feat));
        assert_eq!(scope, Some("api".to_string()));
        assert!(breaking);
    }

    #[test]
    fn test_parse_breaking_in_footer() {
        let msg = "feat: add feature\n\nBREAKING CHANGE: this breaks things";
        let (ty, _, breaking) = parse_commit_message(msg);
        assert_eq!(ty, Some(CommitType::Feat));
        assert!(breaking);
    }

    #[test]
    fn test_parse_non_conventional() {
        let (ty, scope, breaking) = parse_commit_message("just a normal commit message");
        assert_eq!(ty, None);
        assert_eq!(scope, None);
        assert!(!breaking);
    }
}
