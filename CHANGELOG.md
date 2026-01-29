# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

