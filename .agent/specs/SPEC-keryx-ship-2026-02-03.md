---
status: APPROVED FOR IMPLEMENTATION
author: jacksnxly
created: 2026-02-03
feature: keryx ship
brief: .agent/briefs/BRIEF-keryx-ship-2026-02-03.md
---

# Technical Spec: keryx ship

## Summary

`keryx ship` is a new subcommand that automates the full release pipeline: preflight validation, version calculation (LLM or algorithmic), version file updates across ecosystems (Cargo.toml, package.json, pyproject.toml), changelog check/generation, git commit, tag, and push. It lives in a new `src/ship/` module, reuses existing keryx infrastructure for version bumping and changelog generation, and shells out to the system `git` binary for write operations (commit, tag, push, rollback).

## Research Sources

| Topic | Source | Date Accessed |
|-------|--------|---------------|
| Rust release automation patterns | [Orhun's Blog: Fully Automated Rust Releases](https://blog.orhun.dev/automated-rust-releases/) | 2026-02-03 |
| release-plz architecture | [release-plz.dev](https://release-plz.dev/) | 2026-02-03 |
| cargo-release (shells out to git) | [GitHub: crate-ci/cargo-release](https://github.com/crate-ci/cargo-release) | 2026-02-03 |
| git2 push auth problems | [rust-lang/git2-rs#329](https://github.com/rust-lang/git2-rs/issues/329) | 2026-02-03 |
| dialoguer confirm prompt | [docs.rs/dialoguer](https://docs.rs/dialoguer/latest/dialoguer/struct.Confirm.html) | 2026-02-03 |
| pyproject.toml PEP 621 vs Poetry | [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) | 2026-02-03 |
| pyproject.toml Poetry format | [Poetry docs: pyproject.toml](https://python-poetry.org/docs/pyproject/) | 2026-02-03 |
| Rust CLI prompt comparison | [fadeevab.com: CLI Prompts Comparison](https://fadeevab.com/comparison-of-rust-cli-prompts/) | 2026-02-03 |
| toml_edit for format-preserving edits | [crates.io/toml_edit](https://crates.io/crates/toml_edit) | 2026-02-03 |

## Decisions

### 1. Git Write Operations (commit, tag, push)
**Choice:** Shell out to system `git` binary via `std::process::Command`
**Best Practice:** `cargo-release` uses the same pattern — shells out to `git` for all write operations
**Deviation:** None — matches industry standard
**Source:** [cargo-release reference](https://github.com/sunng87/cargo-release/blob/master/docs/reference.md)

Rationale: `git2` has well-documented authentication problems for push operations (SSH, tokens, credential helpers). Shelling out inherits the user's existing git config, SSH agent, and credential store with zero configuration.

### 2. Interactive Confirmation
**Choice:** Add `dialoguer` crate
**Best Practice:** `dialoguer` is the most widely used Rust CLI prompt library, used by cargo-release and other major tools
**Deviation:** None
**Source:** [dialoguer docs](https://docs.rs/dialoguer/latest/dialoguer/struct.Confirm.html)

### 3. Module Architecture
**Choice:** New `src/ship/` module with submodules
**Best Practice:** Separation of concerns — ship orchestration is distinct from changelog generation
**Deviation:** None

### 4. Version File Editing
**Choice:** Proper parsers (`toml_edit` for TOML, `serde_json` for JSON)
**Best Practice:** Format-preserving edits prevent destroying comments and formatting
**Deviation:** None
**Source:** [toml_edit crate](https://crates.io/crates/toml_edit)

### 5. pyproject.toml Version Location
**Choice:** Check `[project].version` first (PEP 621), fall back to `[tool.poetry].version`
**Best Practice:** PEP 621 is the standard since 2021, Poetry 2.0+ supports it
**Deviation:** None — supports both for backward compatibility
**Source:** [Python Packaging Guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)

### 6. Error Handling
**Choice:** New `ShipError` enum using `thiserror`
**Best Practice:** Matches existing codebase pattern (GitError, ChangelogError, CommitError, etc.)
**Deviation:** None

### 7. LLM Availability Check
**Choice:** Separate preflight check before version calculation
**Best Practice:** Fail fast — don't start a release pipeline if a required resource is unavailable
**Deviation:** Overrides the existing `calculate_next_version_with_llm()` silent fallback behavior. Ship explicitly checks LLM reachability first.

### 8. Rollback Mechanism
**Choice:** Shell out to `git reset --soft HEAD~1` and `git tag -d`
**Best Practice:** Consistent with Decision 1 (all git writes via CLI)
**Deviation:** None

### 9. Changelog Generation Reuse
**Choice:** Extract core logic from `run_generate()` into a reusable library function
**Best Practice:** DRY — both `generate` and `ship` need changelog generation
**Deviation:** None — requires refactoring existing code

## Module Structure

```
src/ship/
├── mod.rs              # Public API: run_ship() entry point
├── preflight.rs        # All preflight checks
├── version_files.rs    # Auto-detect and update version files
└── executor.rs         # Git operations: commit, tag, push, rollback
```

### src/ship/mod.rs — Orchestrator

```rust
pub async fn run_ship(config: ShipConfig) -> Result<(), ShipError>
```

Pipeline stages (in order):
1. `preflight::run_checks()` — validate working tree, remote sync, commits exist, LLM available
2. `version::calculate_next_version*()` — determine next version (reuse existing)
3. Tag collision check — if tag exists, suggest next version
4. `version_files::detect_and_update()` — find and bump version files
5. Changelog check/generate — check if section exists, generate if missing (reuse extracted lib function)
6. Confirmation prompt — show summary, ask Y/n (skip in dry-run)
7. `executor::commit_tag_push()` — create commit, tag, push
8. On failure: `executor::rollback()` — undo commit and tag

### src/ship/preflight.rs — Preflight Checks

```rust
pub struct PreflightResult {
    pub current_branch: String,
    pub remote_name: String,
    pub latest_tag: Option<TagInfo>,
    pub commits_since_tag: Vec<ParsedCommit>,
    pub llm_available: bool,
}

pub async fn run_checks(config: &ShipConfig) -> Result<PreflightResult, ShipError>
```

Checks (in order):
1. **Clean working tree:** `git status --porcelain` — if output is non-empty, abort
2. **Up to date with remote:** `git fetch` then compare `git rev-parse HEAD` with `git rev-parse @{u}` — if local is behind, abort
3. **Commits exist:** Use existing `get_latest_tag()` + `fetch_commits()` — if zero commits since last tag, abort
4. **LLM available (if not --no-llm-bump):** Check env var presence (`ANTHROPIC_API_KEY` or equivalent for configured provider)

### src/ship/version_files.rs — Version File Detection & Update

```rust
pub enum VersionFileKind {
    CargoToml,
    PackageJson,
    PyprojectToml,
}

pub struct VersionFile {
    pub path: PathBuf,
    pub kind: VersionFileKind,
    pub current_version: Version,
}

pub fn detect_version_files(root: &Path) -> Result<Vec<VersionFile>, ShipError>
pub fn update_version_file(file: &VersionFile, new_version: &Version) -> Result<(), ShipError>
```

Detection order:
1. `Cargo.toml` — look for `[package].version`
2. `package.json` — look for top-level `"version"` field
3. `pyproject.toml` — look for `[project].version`, fall back to `[tool.poetry].version`

All files found in the project root are updated. If none found, abort with error.

Update strategy:
- **Cargo.toml / pyproject.toml:** Use `toml_edit` to parse, modify, and serialize (preserves formatting, comments, ordering)
- **package.json:** Use `serde_json` to parse, modify `version` field, serialize with 2-space indent (standard npm formatting)

### src/ship/executor.rs — Git Operations

```rust
pub fn commit_tag_push(
    message: &str,
    tag_name: &str,
    files: &[PathBuf],
    remote: &str,
    branch: &str,
) -> Result<(), ShipError>

pub fn rollback(tag_name: &str) -> Result<(), ShipError>
```

All operations use `std::process::Command`:

**commit_tag_push:**
1. `git add <file1> <file2> ...` — stage only the modified version/changelog files
2. `git commit -m "chore(release): vX.Y.Z"` — create release commit
3. `git tag vX.Y.Z` — create lightweight tag
4. `git push <remote> <branch> --follow-tags` — push commit + tag together

**rollback (on push failure):**
1. `git tag -d vX.Y.Z` — delete local tag
2. `git reset --soft HEAD~1` — undo the release commit (keeps changes staged)

## CLI Integration

Add `Ship` variant to the `Commands` enum in `src/main.rs`:

```rust
#[derive(Subcommand, Debug)]
enum Commands {
    Update,
    Init { ... },
    Commit { ... },

    /// Create a release: bump version, update changelog, tag, and push
    Ship,
}
```

`Ship` inherits these existing global flags:
- `--set-version` — override calculated version
- `--dry-run` — show summary without executing
- `--no-llm-bump` — use algorithmic versioning
- `--no-prs` — skip PR fetching for changelog generation
- `--provider` — select LLM provider
- `--verbose` — show detailed output

No new flags needed — the existing global flags cover all ship options.

## Error Type

```rust
#[derive(Error, Debug)]
pub enum ShipError {
    #[error("Working tree has uncommitted changes")]
    DirtyWorkingTree,

    #[error("Local branch is behind remote. Run 'git pull' first.")]
    BehindRemote,

    #[error("No commits since {0}. Nothing to ship.")]
    NoCommitsSinceTag(String),

    #[error("No version files found (Cargo.toml, package.json, or pyproject.toml)")]
    NoVersionFiles,

    #[error("Tag {0} already exists")]
    TagAlreadyExists(String),

    #[error("LLM provider unavailable: {0}")]
    LlmUnavailable(String),

    #[error("Failed to update version file {path}: {reason}")]
    VersionFileUpdateFailed { path: PathBuf, reason: String },

    #[error("Git operation failed: {0}")]
    GitFailed(String),

    #[error("Push failed: {0}")]
    PushFailed(String),

    #[error("Rollback failed: {0}")]
    RollbackFailed(String),

    #[error("Changelog error: {0}")]
    Changelog(#[from] ChangelogError),

    #[error("User cancelled")]
    Cancelled,
}
```

## New Dependencies

| Crate | Version | Purpose |
|-------|---------|---------|
| `dialoguer` | latest | Interactive Y/n confirmation prompt |
| `toml_edit` | latest | Format-preserving TOML editing for Cargo.toml and pyproject.toml |

Note: `serde_json` is already a dependency in the project.

## Refactoring Required

### Extract changelog generation from `run_generate()`

The core logic in `src/main.rs:1035-1202` (`run_generate()`) needs to be split:

**Before:**
```
run_generate(cli: Cli) → writes changelog directly
```

**After:**
```
generate_changelog_entries(input: GenerateInput) → ChangelogOutput  (new lib function)
run_generate(cli: Cli) → calls generate_changelog_entries(), then writes  (existing, refactored)
run_ship(config: ShipConfig) → calls generate_changelog_entries() when needed  (new)
```

The `GenerateInput` struct encapsulates what both callers need:
- commits
- pull requests (optional)
- version
- LLM router
- verification settings

This is the only existing code that needs modification. All other existing modules are called via their existing public APIs.

## Implementation Constraints

1. **git must be installed** — ship requires the system `git` binary. If not found, abort with a clear error message.
2. **Single version file type can appear at most once** — we don't handle multiple Cargo.toml files (that's monorepo, out of scope).
3. **Changelog format is Keep a Changelog only** — detection of CHANGES.md/HISTORY.md checks for common filenames, but the format must be Keep a Changelog for parsing/generation to work.
4. **Lightweight tags only** — no annotated/signed tags in v1. Consistent with how cargo-dist triggers.
5. **`--soft` reset on rollback** — the release commit is undone but changes stay staged, so the user doesn't lose the version bump work.

## Documentation References

Before implementing, consult these official docs:
- [dialoguer Confirm API](https://docs.rs/dialoguer/latest/dialoguer/struct.Confirm.html) — for confirmation prompt usage
- [toml_edit DocumentMut API](https://docs.rs/toml_edit/latest/toml_edit/) — for format-preserving TOML edits
- [std::process::Command](https://doc.rust-lang.org/stable/std/process/struct.Command.html) — for git CLI invocations
- [PEP 621: pyproject.toml metadata](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) — for pyproject.toml field locations
- [Poetry pyproject.toml](https://python-poetry.org/docs/pyproject/) — for legacy tool.poetry.version location

## Testing Requirements

### Unit Tests
- **version_files.rs:** Detection logic with mock directories containing each file type, version parsing, version updating with format preservation
- **preflight.rs:** Each check in isolation (dirty tree, behind remote, no commits, LLM unavailable)
- **executor.rs:** Command construction (verify correct git arguments are assembled), rollback logic

### Integration Tests
- **Happy path:** Full ship flow with a temp git repo (init, commit, ship, verify tag exists)
- **Dry-run:** Ship with `--dry-run`, verify no files modified and no tag created
- **Rollback:** Simulate push failure, verify commit and tag are cleaned up
- **Existing changelog:** Pre-populate changelog section, verify ship skips generation
- **Tag collision:** Create a tag first, verify ship suggests next version
- **Multi-ecosystem:** Test with Cargo.toml, package.json, and pyproject.toml separately

## Rollout

1. Implement behind the `Ship` subcommand (no feature flag needed — it's opt-in via subcommand)
2. Dogfood on keryx's own next release (v0.5.0)
3. Document in README after successful dogfood release
