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

    #[error("Commit {hash} has invalid timestamp (seconds={seconds})")]
    InvalidTimestamp { hash: String, seconds: i64 },

    #[error(
        "Commit traversal incomplete: {error_count} error(s) occurred. Root commit {partial_root} may not be the actual repository root. This can happen with shallow clones, missing objects, or permission issues."
    )]
    TraversalIncomplete {
        partial_root: String,
        error_count: usize,
    },
}

/// Errors from GitHub API operations.
#[derive(Error, Debug)]
pub enum GitHubError {
    #[error(
        "GitHub authentication failed: no valid auth found. Run 'gh auth login' or set GITHUB_TOKEN environment variable"
    )]
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

    #[error("All retry attempts failed: {0}")]
    RetriesExhausted(#[source] Box<ClaudeError>),

    #[error("Failed to serialize prompt data: {0}")]
    SerializationFailed(String),
}

/// Errors from Codex CLI operations.
#[derive(Error, Debug)]
pub enum CodexError {
    #[error(
        "Codex CLI not found. Install with: npm install -g @openai/codex (then run `codex` or set CODEX_API_KEY)"
    )]
    NotInstalled,

    #[error("Codex CLI failed to execute: {0}")]
    ExecutionFailed(String),

    #[error("Failed to spawn Codex process: {0}")]
    SpawnFailed(#[source] std::io::Error),

    #[error("Codex returned invalid JSON: {0}")]
    InvalidJson(String),

    #[error("Codex process timed out after {0} seconds")]
    Timeout(u64),

    #[error("Codex CLI exited with code {code}: {stderr}")]
    NonZeroExit { code: i32, stderr: String },

    #[error("All retry attempts failed: {0}")]
    RetriesExhausted(#[source] Box<CodexError>),

    #[error("Failed to serialize prompt data: {0}")]
    SerializationFailed(String),
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

    #[error("Version {0} already exists in changelog. Use --force to overwrite.")]
    VersionAlreadyExists(String),
}

/// Errors from version operations.
#[derive(Error, Debug)]
pub enum VersionError {
    #[error("Failed to parse version '{0}': {1}")]
    ParseFailed(String, #[source] semver::Error),

    #[error("No version found to bump from")]
    NoBaseVersion,
}

/// Errors from commit message generation operations.
#[derive(Error, Debug)]
pub enum CommitError {
    #[error("No changes to commit (working tree is clean)")]
    NoChanges,

    #[error("Failed to collect diff: {0}")]
    DiffFailed(#[source] git2::Error),

    #[error("Failed to stage changes: {0}")]
    StagingFailed(#[source] git2::Error),

    #[error("Failed to create commit: {0}")]
    CommitFailed(#[source] git2::Error),

    #[error("Git config error (missing user.name or user.email): {0}")]
    ConfigError(#[source] git2::Error),
}

/// Errors from verification and scanning operations.
#[derive(Error, Debug)]
pub enum VerificationError {
    #[error(
        "ripgrep (rg) is required for verification but was not found.\n\n\
             Install with one of:\n  \
             cargo install ripgrep\n  \
             brew install ripgrep     (macOS)\n  \
             apt install ripgrep      (Debian/Ubuntu)\n\n\
             Or skip verification with: --no-verify"
    )]
    RipgrepNotInstalled,

    #[error("ripgrep (rg) was found but exited with {}: {stderr}\n\n\
             This may indicate a corrupted installation or missing dependencies.\n\
             Try reinstalling ripgrep or skip verification with: --no-verify",
             exit_code.map_or("unknown status".to_string(), |c| format!("code {c}")))]
    RipgrepFailed {
        exit_code: Option<i32>,
        stderr: String,
    },

    #[error(
        "ripgrep (rg) could not be executed: {0}\n\n\
             This may be a permission issue or a problem with the ripgrep binary.\n\
             Check file permissions or reinstall ripgrep.\n\
             Or skip verification with: --no-verify"
    )]
    RipgrepExecutionFailed(String),

    #[error("I/O error during scan: {0}")]
    ScannerIoError(#[source] std::io::Error),
}
