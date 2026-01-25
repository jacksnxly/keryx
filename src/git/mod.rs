//! Git operations using git2-rs.

pub mod commits;
pub mod range;
pub mod tags;

pub use commits::{fetch_commits, parse_commit_message, CommitType, ParsedCommit};
pub use range::resolve_range;
pub use tags::{get_latest_tag, get_version_from_tag};
