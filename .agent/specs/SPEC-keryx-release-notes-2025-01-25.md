---
status: APPROVED FOR IMPLEMENTATION
author: jacksnxly
created: 2025-01-25
feature: keryx - AI-Powered Release Notes Generator
brief: .agent/briefs/BRIEF-keryx-release-notes-2025-01-25.md
---

# Technical Spec: keryx - AI-Powered Release Notes Generator

## Summary

keryx is a Rust CLI tool that generates release notes by analyzing git commits and GitHub PRs, using Claude Code CLI to transform them into human-readable changelog entries. The tool uses clap for argument parsing, git2 for native git access, octocrab for GitHub API integration, and tokio for async operations. It follows the Keep a Changelog format and implements semantic versioning with automatic version bumping based on conventional commit types.

## Decisions

### 1. CLI Framework

**Choice:** clap v4 with derive macros

**Alternatives Rejected:**
- pico-args: Lacks auto-generated help, requires manual validation. Rejected because keryx needs good UX with multiple flags and subcommands.

**Reasoning:** clap is the industry standard with extensive ecosystem support. The derive macro approach provides type-safe argument definitions with minimal boilerplate. Auto-generated help and shell completions improve user experience.

### 2. Git Integration

**Choice:** git2-rs (libgit2 bindings)

**Alternatives Rejected:**
- Git CLI subprocess: Requires parsing stdout/stderr, shell escaping concerns, process spawn overhead.
- gitoxide (gix): Newer, API still evolving, less battle-tested for production use.

**Reasoning:** git2-rs provides type-safe, memory-safe access to git repositories without requiring git binary at runtime. Structured error handling and faster performance outweigh the compile-time cost of libgit2 dependencies.

### 3. GitHub API Access

**Choice:** octocrab

**Alternatives Rejected:**
- gh CLI subprocess: Would require parsing JSON output, adds external dependency.
- reqwest + manual API: Would require implementing pagination, auth handling, and PR models manually.

**Reasoning:** octocrab provides strongly-typed models for PRs and commits, built-in authentication handling, and async-first design that integrates well with tokio. The typed API reduces bugs from JSON parsing.

### 4. Async Runtime

**Choice:** Tokio async runtime

**Alternatives Rejected:**
- Synchronous: Would prevent parallel PR fetching and non-blocking subprocess I/O.

**Reasoning:** keryx needs to fetch multiple PRs from GitHub and spawn Claude CLI subprocess. Tokio enables concurrent PR fetching for better performance and proper async subprocess handling. The complexity cost is justified by the network-heavy nature of the tool.

### 5. Changelog Parsing/Writing

**Choice:** parse-changelog for reading + string templates for writing

**Alternatives Rejected:**
- pulldown-cmark: Event-based API is overkill for Keep a Changelog's predictable structure.
- comrak: Full AST manipulation unnecessary when we only need to insert sections.
- Pure regex: Fragile and harder to maintain than purpose-built parser.

**Reasoning:** parse-changelog is purpose-built for Keep a Changelog format and used by GitHub Actions for release automation. String templates for writing ensure predictable, spec-compliant output without AST complexity.

### 6. Error Handling

**Choice:** thiserror + anyhow hybrid

**Alternatives Rejected:**
- anyhow only: Type-erased errors make it harder to handle specific failure cases (e.g., distinguishing "Claude not installed" from "Claude failed").

**Reasoning:** thiserror defines typed errors in core modules (GitError, GitHubError, ClaudeError, ChangelogError) enabling specific error handling. anyhow wraps at CLI boundary for rich context in user-facing messages.

### 7. GitHub Authentication Strategy

**Choice:** gh CLI fallback to environment variable

**Alternatives Rejected:**
- gh only: Would fail in CI/CD environments where gh isn't installed.
- Env var only: Worse UX for local development where users already have gh configured.

**Reasoning:** Checking `gh auth status` first leverages existing user auth for local development. Falling back to `GITHUB_TOKEN`/`GH_TOKEN` environment variables supports CI/CD pipelines and headless environments. This provides the best UX across all environments.

## Data Model

### Internal Types

```rust
/// Represents a commit with conventional commit parsing
pub struct ParsedCommit {
    pub hash: String,
    pub message: String,
    pub commit_type: Option<CommitType>,  // feat, fix, etc.
    pub scope: Option<String>,
    pub breaking: bool,
    pub timestamp: DateTime<Utc>,
}

/// Conventional commit types
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

/// Represents a GitHub PR
pub struct PullRequest {
    pub number: u64,
    pub title: String,
    pub body: Option<String>,
    pub merged_at: Option<DateTime<Utc>>,
    pub labels: Vec<String>,
}

/// Input to Claude for changelog generation
pub struct ChangelogInput {
    pub commits: Vec<ParsedCommit>,
    pub pull_requests: Vec<PullRequest>,
    pub previous_version: Option<Version>,
    pub repository_name: String,
}

/// Output from Claude
pub struct ChangelogOutput {
    pub entries: Vec<ChangelogEntry>,
    pub suggested_version: Version,
}

pub struct ChangelogEntry {
    pub category: ChangelogCategory,
    pub description: String,
}

pub enum ChangelogCategory {
    Added,
    Changed,
    Deprecated,
    Removed,
    Fixed,
    Security,
}
```

### CLI Arguments

```rust
#[derive(Parser)]
#[command(name = "keryx")]
#[command(about = "Generate release notes from commits and PRs using Claude")]
pub struct Cli {
    /// Explicit version to use (overrides auto-detection)
    #[arg(short, long)]
    pub version: Option<Version>,

    /// Start of commit range (tag, commit hash, or branch)
    #[arg(long)]
    pub from: Option<String>,

    /// End of commit range (defaults to HEAD)
    #[arg(long, default_value = "HEAD")]
    pub to: String,

    /// Path to changelog file
    #[arg(short, long, default_value = "CHANGELOG.md")]
    pub output: PathBuf,

    /// Skip GitHub PR fetching
    #[arg(long)]
    pub no_prs: bool,

    /// Dry run - print changelog without writing
    #[arg(long)]
    pub dry_run: bool,
}
```

## API Contract

### Claude CLI Interaction

keryx spawns Claude Code CLI as a subprocess with structured input:

**Command:**
```bash
claude -p "<prompt>" --output-format json
```

**Prompt Structure:**
```
You are generating release notes for a software project.

Given the following commits and pull requests, generate changelog entries
following the Keep a Changelog format.

## Commits
<JSON array of ParsedCommit>

## Pull Requests
<JSON array of PullRequest>

## Instructions
1. Group changes into categories: Added, Changed, Deprecated, Removed, Fixed, Security
2. Write user-facing descriptions (not technical commit messages)
3. Focus on benefits and impact
4. Combine related commits/PRs into single entries where appropriate
5. Ignore docs-only, test-only, and chore commits unless they affect users

Respond with JSON:
{
  "entries": [
    {"category": "Added", "description": "..."},
    ...
  ]
}
```

**Response Parsing:**
- Extract JSON from Claude's response
- Validate against expected schema
- Retry on parse failure (up to 3 times)

## Integration Points

### External Services

| Service | Purpose | Auth Method |
|---------|---------|-------------|
| GitHub API | Fetch merged PRs | gh CLI or GITHUB_TOKEN env var |
| Claude Code CLI | Generate changelog text | User's existing Claude auth |

### Internal Modules

```
src/
├── main.rs           # CLI entry point, argument parsing
├── lib.rs            # Public API re-exports
├── git/
│   ├── mod.rs
│   ├── commits.rs    # Commit fetching and parsing
│   ├── tags.rs       # Tag enumeration, version detection
│   └── range.rs      # Commit range resolution
├── github/
│   ├── mod.rs
│   ├── auth.rs       # gh CLI / env var auth detection
│   └── prs.rs        # PR fetching via octocrab
├── claude/
│   ├── mod.rs
│   ├── subprocess.rs # Claude CLI spawning
│   ├── prompt.rs     # Prompt construction
│   └── retry.rs      # Exponential backoff logic
├── changelog/
│   ├── mod.rs
│   ├── parser.rs     # Read existing changelog (parse-changelog)
│   ├── writer.rs     # Write new sections
│   └── format.rs     # Keep a Changelog formatting
├── version/
│   ├── mod.rs
│   └── bump.rs       # Semver calculation from commits
└── error.rs          # Error types (thiserror)
```

## Security Considerations

### Authentication

- **GitHub tokens:** Never logged or displayed. Read from environment or gh CLI config.
- **Claude auth:** Delegated entirely to Claude CLI (uses user's existing subscription).

### Input Validation

- **Commit messages:** Sanitized before passing to Claude to prevent prompt injection.
- **PR bodies:** Truncated to reasonable length (10KB max) to prevent token exhaustion.
- **Version strings:** Validated against semver format before use.

### File Operations

- **CHANGELOG.md:** Only written to user-specified path (default: current directory).
- **Backup:** Original changelog backed up to `.changelog.md.bak` before modification.

## Implementation Constraints

1. **Use clap v4 with derive macros** for CLI argument parsing - define structs with `#[derive(Parser)]`
2. **Use git2-rs** for all git operations (commits, tags, log) - no shelling out to git binary
3. **Use octocrab** for GitHub API access (PRs, commits) with async/await
4. **Use tokio runtime** (`#[tokio::main]`) as the async executor
5. **Use parse-changelog** crate for reading existing CHANGELOG.md files
6. **Use string templates** for writing new changelog sections (not AST manipulation)
7. **Use thiserror** for defining error types in core modules, **anyhow** at the CLI boundary
8. **GitHub auth order:** Check `gh auth status` first, fall back to `GITHUB_TOKEN`/`GH_TOKEN` env vars
9. **Retry strategy:** 3 retries with exponential backoff (base 1s, max 30s) for Claude CLI failures
10. **Rate limit handling:** Fail immediately with clear message showing reset time, do not auto-retry
11. **Use semver crate** (dtolnay) for version parsing and bumping
12. **Use backoff crate** with tokio feature for retry logic
13. **Claude CLI integration:** Spawn as subprocess via `tokio::process::Command`, capture stdout/stderr
14. **Keep a Changelog compliance:** Output must follow keepachangelog.com v1.1.0 format exactly
15. **Unreleased section:** If `[Unreleased]` exists, convert to versioned section per spec standard

## Testing Requirements

### Unit Tests

- **git/commits.rs:** Parse conventional commit messages correctly
- **git/range.rs:** Resolve commit ranges (tag to HEAD, hash to hash, root to HEAD)
- **version/bump.rs:** Calculate correct semver bumps from commit types
- **changelog/parser.rs:** Parse various Keep a Changelog formats
- **changelog/writer.rs:** Generate spec-compliant markdown output
- **claude/prompt.rs:** Construct valid prompts from input data
- **github/auth.rs:** Detect auth method correctly (mock gh CLI and env vars)

### Integration Tests

- **End-to-end:** Given a git repo with known commits, verify changelog output
- **GitHub integration:** Mock octocrab responses, verify PR data extraction
- **Claude integration:** Mock subprocess output, verify retry behavior
- **Error scenarios:** Claude not installed, GitHub rate limited, no tags exist

### Test Fixtures

- Sample git repository with conventional commits
- Sample CHANGELOG.md files (empty, with Unreleased, with existing versions)
- Mock Claude CLI responses (success, failure, malformed JSON)

## Rollout

### MVP Scope

1. Core flow: commits → Claude → CHANGELOG.md
2. Single command: `keryx` with basic flags
3. GitHub PR fetching (optional with `--no-prs`)
4. Auto version bumping from conventional commits

### Future Enhancements (Out of Scope for v1)

- Interactive mode for reviewing entries before write
- Custom prompt templates
- Multiple changelog formats
- GitHub Release creation

### Installation

```bash
cargo install keryx
```

### Prerequisites Check

On first run, keryx validates:
1. Claude Code CLI installed (`which claude`)
2. Claude Code authenticated (`claude --version` succeeds)
3. Git repository exists in current directory
4. GitHub auth available (if PRs requested)

Clear error messages guide users through setup if any prerequisite fails.

## Dependencies

```toml
[dependencies]
# CLI
clap = { version = "4", features = ["derive"] }

# Async runtime
tokio = { version = "1", features = ["full"] }

# Git
git2 = "0.19"

# GitHub
octocrab = "0.41"

# Changelog
parse-changelog = "0.6"

# Versioning
semver = "1"

# Error handling
thiserror = "2"
anyhow = "1"

# Retry logic
backoff = { version = "0.4", features = ["tokio"] }

# Serialization
serde = { version = "1", features = ["derive"] }
serde_json = "1"

# Date/time
chrono = { version = "0.4", features = ["serde"] }
```

## References

- [Keep a Changelog v1.1.0](https://keepachangelog.com/en/1.1.0/)
- [Conventional Commits v1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [clap documentation](https://docs.rs/clap/latest/clap/)
- [git2-rs documentation](https://docs.rs/git2/latest/git2/)
- [octocrab documentation](https://docs.rs/octocrab/latest/octocrab/)
- [parse-changelog documentation](https://docs.rs/parse-changelog/latest/parse_changelog/)
- [semver crate](https://docs.rs/semver/latest/semver/)
- [backoff crate](https://docs.rs/backoff/latest/backoff/)
