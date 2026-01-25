# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

