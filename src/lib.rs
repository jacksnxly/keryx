//! keryx - A CLI tool that generates release notes from merged PRs and conventional commits.
//!
//! # Overview
//!
//! keryx analyzes git commits and GitHub PRs, uses Claude or Codex CLI to transform them
//! into human-readable changelog entries, and writes them to CHANGELOG.md in
//! Keep a Changelog format.

pub mod changelog;
pub mod claude;
pub mod codex;
pub mod commit;
pub mod error;
pub mod git;
pub mod github;
pub mod llm;
pub mod verification;
pub mod version;

// Re-export commonly used types
pub use changelog::{ChangelogCategory, ChangelogEntry, ChangelogOutput};
pub use error::{
    ChangelogError, ClaudeError, CodexError, CommitError, GitError, GitHubError, VerificationError,
    VersionError,
};
pub use git::{CommitType, ParsedCommit};
pub use github::PullRequest;
pub use verification::{Confidence, EntryEvidence, VerificationEvidence};
pub use version::BumpType;
