//! Error types for keryx modules using thiserror.

use thiserror::Error;

/// Errors from git operations.
#[derive(Error, Debug)]
pub enum GitError {
    #[error("Failed to open repository: {0}")]
    OpenRepository(#[source] git2::Error),

    #[error("Failed to find reference '{0}': {1}")]
    ReferenceNotFound(String, #[source] git2::Error),

    #[error("Failed to parse commit: {0}")]
    ParseCommit(#[source] git2::Error),

    #[error("Failed to walk commit history: {0}")]
    RevwalkError(#[source] git2::Error),
}

/// Errors from GitHub API operations.
#[derive(Error, Debug)]
pub enum GitHubError {
    #[error("GitHub authentication failed: no valid auth found. Run 'gh auth login' or set GITHUB_TOKEN environment variable")]
    AuthenticationFailed,

    #[error("Failed to fetch PRs: {0}")]
    FetchPRs(#[source] Box<octocrab::Error>),

    #[error("Rate limited by GitHub API. Resets at: {reset_time}")]
    RateLimited { reset_time: String },

    #[error("Repository not found: {owner}/{repo}")]
    RepositoryNotFound { owner: String, repo: String },

    #[error("Failed to parse repository URL")]
    InvalidRepositoryUrl,
}

/// Errors from Claude CLI operations.
#[derive(Error, Debug)]
pub enum ClaudeError {
    #[error("Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code")]
    NotInstalled,

    #[error("Claude Code CLI failed to execute: {0}")]
    ExecutionFailed(String),

    #[error("Failed to spawn Claude process: {0}")]
    SpawnFailed(#[source] std::io::Error),

    #[error("Claude returned invalid JSON: {0}")]
    InvalidJson(String),

    #[error("Claude process timed out after {0} seconds")]
    Timeout(u64),

    #[error("Claude CLI exited with code {code}: {stderr}")]
    NonZeroExit { code: i32, stderr: String },

    #[error("All retry attempts failed")]
    RetriesExhausted,
}

/// Errors from changelog operations.
#[derive(Error, Debug)]
pub enum ChangelogError {
    #[error("Failed to read changelog: {0}")]
    ReadFailed(#[source] std::io::Error),

    #[error("Failed to write changelog: {0}")]
    WriteFailed(#[source] std::io::Error),

    #[error("Failed to parse changelog: {0}")]
    ParseFailed(String),

    #[error("Failed to create backup: {0}")]
    BackupFailed(#[source] std::io::Error),
}

/// Errors from version operations.
#[derive(Error, Debug)]
pub enum VersionError {
    #[error("Failed to parse version '{0}': {1}")]
    ParseFailed(String, #[source] semver::Error),

    #[error("No version found to bump from")]
    NoBaseVersion,
}
