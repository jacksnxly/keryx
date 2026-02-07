# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.2] - 2026-02-07

### Fixed

- Fix corrupted AI responses caused by stray stderr output during release note generation
- Fix Claude CLI response parsing when hook stderr is mixed into output
- Fix self-update failing to locate releases by using install receipt


## [0.6.1] - 2026-02-06

### Added

- New `keryx commit` command that generates conventional commit messages from staged changes using AI, with automatic splitting of large changesets into multiple focused commits (`--no-split` to disable)
- New `keryx push` command that runs the commit flow and then pushes to the current branch in one step
- LLM-based semantic version bumping that intelligently determines the next version number based on changes (`--no-llm-bump` to disable)
- New `keryx ship` command for streamlined release workflow

### Fixed

- Duplicate file deduplication and character-safe UTF-8 truncation in diff processing
- Initial commits into empty repositories now work correctly
- File renames are properly staged with old path removed from the index


## [0.6.0] - 2026-02-06

### Added

- Add `keryx ship` command to automate releases with version bumping, changelog updates, tagging, and pushing
- Add `keryx push` command that runs the commit flow then pushes to the current branch
- Add `keryx commit` subcommand that generates conventional commit messages from staged changes using AI, with automatic splitting of large changesets into focused commits
- Add LLM-based semantic version bumping with `--no-llm-bump` flag to skip
- Verify generated changelog entries against repository evidence before writing
- Show a clear error when running `ship` with a detached HEAD

### Changed

- Require an upstream tracking branch for `ship` and push to the correct remote branch instead of guessing
- Use branch-aware tag discovery for accurate version detection in multi-branch workflows
- Skip redundant version-bump commit when version files already match the target version
- Improve error messages when changelog generation fails or the required LLM provider is unavailable

### Fixed

- Fix release preflight picking up tags from unrelated branches
- Fix incorrect version detection when non-semver tags (e.g. deploy dates) are present
- Show clear error when version files contain invalid semver strings instead of silently skipping them
- Fix commit list including already-released commits when another branch has a newer tag
- Include the root commit when releasing a repository with no prior tags
- Avoid partial pushes during releases by pushing tags atomically
- Fix release tags not being pushed to remote by switching to annotated tags
- Fix version suggestion when multiple tags conflict and handle initial repos with a single commit
- Fix duplicate entries in v0.5.0 changelog


## [0.5.0] - 2026-02-04

### Added

- New `keryx push` command that commits and pushes in one step, with actionable error messages for common failures

### Fixed

- Claude Code integration now works in headless and automated environments (CI/CD pipelines)
- Push command now respects user's `push.default` git configuration instead of requiring an upstream branch


## [0.4.0] - 2026-02-02

### Added

- Generate commit messages from staged changes using AI
- Automatically split large changesets into multiple focused commits
- Support file renames and initial commits in AI commit workflow
- LLM-based semantic version bumping that intelligently determines the next version number based on changes

### Changed

- Improve error messages when AI responses or git state are invalid

### Fixed

- Fix duplicate files in commit diffs and prevent pre-staged changes from leaking into split commits
- Fix potential crash when truncating non-ASCII LLM responses


## [0.3.0] - 2026-02-02

### Added

- LLM-based semantic version bumping that intelligently determines the next version number based on your changes
- `--no-llm-bump` CLI flag to skip LLM version inference and use conventional commit-based versioning instead

### Changed

- Improved reliability of LLM provider communication with shared retry logic and robust JSON parsing


## [0.2.0] - 2026-01-29

### Added

- Added two-pass verification that scans the codebase, gathers evidence, and flags low-confidence or unverifiable entries (including numeric claims) to reduce hallucinations.
- Added `--no-verify` to skip verification for faster generation.
- Added LLM provider routing with Codex fallback and a `--provider` flag for manual selection.
- Documented `keryx init` usage with `--unreleased`, `--from-history`, and `--dry-run` examples.
- Documented uninstall steps for macOS/Linux and Windows.

### Changed

- Verification now reports keyword search failures in CLI output and reduces confidence when searches fail.

### Fixed

- When `init --unreleased` verification yields no entries, it now falls back to the basic template to avoid empty sections.
- Reduced verification false positives by de-duplicating stub indicators per file/line.
- Verification skips CLI flags (for example, `--no-verify`) during keyword extraction.
- Numeric-claim verification avoids matching hyphenated tokens like `UTF-8 handling` by anchoring on start/whitespace.
- Verification skips non-countable subjects (handling, panic, byte, etc.) to avoid misleading counts.
- Fixed a UTF-8 edge case in array element counting during verification (uses char indices).
- Fixed UTF-8 truncation in key-file gathering to avoid panics on multi-byte boundaries.


## [0.1.1] - 2026-01-26

### Added

- New `keryx init` command to bootstrap changelogs for existing projects with three modes: create an empty template, generate entries from all commits as unreleased changes (`--unreleased`), or build a complete changelog from git tag history (`--from-history`)


## [0.1.0] - 2026-01-25

### Added

- CLI tool for generating release notes from merged PRs and conventional commits
- Automatic version detection with `--set-version` override option
- Flexible commit range selection via `--from` and `--to` flags
- Customizable output path with `-o, --output` flag (defaults to CHANGELOG.md)
- Commit-only mode with `--no-prs` flag when GitHub PR fetching is not needed
- Preview mode with `--dry-run` to review changes before writing
- Multiple GitHub authentication methods: gh CLI, GITHUB_TOKEN, and GH_TOKEN environment variables
- Automatic backup creation (.changelog.md.bak) before modifying existing changelogs
- Support for [Unreleased] sections following Keep a Changelog specification
- AI-powered changelog generation with context-aware descriptions for initial releases

