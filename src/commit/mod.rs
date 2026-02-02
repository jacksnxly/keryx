//! AI-generated commit messages using LLM providers.

pub mod diff;
pub mod message;
pub mod prompt;

pub use diff::{ChangedFile, DiffSummary, FileStatus, collect_diff};
pub use message::{CommitMessage, generate_commit_message, stage_and_commit};
pub use prompt::build_commit_prompt;
