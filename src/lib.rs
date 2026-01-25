//! keryx - A CLI tool that generates release notes from merged PRs and conventional commits.
//!
//! # Overview
//!
//! keryx analyzes git commits and GitHub PRs, uses Claude Code CLI to transform them
//! into human-readable changelog entries, and writes them to CHANGELOG.md in
//! Keep a Changelog format.

pub mod changelog;
pub mod claude;
pub mod error;
pub mod git;
pub mod github;
pub mod version;

// Re-export commonly used types
pub use changelog::{ChangelogCategory, ChangelogEntry, ChangelogOutput};
pub use error::{ChangelogError, ClaudeError, GitError, GitHubError, VersionError};
pub use git::{CommitType, ParsedCommit};
pub use github::PullRequest;
pub use version::BumpType;
