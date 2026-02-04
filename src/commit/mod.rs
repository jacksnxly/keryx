//! AI-generated commit messages using LLM providers.

pub mod analysis;
pub mod diff;
pub mod message;
pub mod prompt;

pub use analysis::{CommitGroup, SPLIT_ANALYSIS_THRESHOLD, SplitAnalysis, analyze_split};
pub use diff::{ChangedFile, DiffSummary, FileStatus, collect_diff, collect_diff_for_paths};
pub use message::{
    CommitMessage, generate_commit_message, stage_and_commit, stage_paths_and_commit,
};
pub use prompt::build_commit_prompt;
