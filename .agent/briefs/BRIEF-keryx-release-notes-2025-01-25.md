---
status: PENDING TECHNICAL REVIEW
author: Developer Interview
created: 2025-01-25
feature: keryx - AI-Powered Release Notes Generator
---

# Feature Brief: keryx - AI-Powered Release Notes Generator

## Problem

**Persona:** Developers using Claude Code with an active subscription who maintain projects requiring changelogs.

**Trigger:** After merging PRs and before cutting a release, the developer needs to generate release notes summarizing what changed.

**Current State:** No changelogs are being written. Changes ship without documentation.

**Pain:**
- Users don't know what changed in releases
- Friction for OSS contributions (contributors and adopters expect changelogs)
- Personal tracking issues (losing track of what shipped when)
- Communication overhead (manually explaining changes each time)

## Solution

### User Journey

1. **Developer runs `keryx`** in a git repository after merging PRs
2. **keryx checks prerequisites:**
   - Verifies Claude Code CLI is installed and authenticated
   - If not: exits with helpful message explaining requirements
3. **keryx determines change range** using one of:
   - Since last git tag (default)
   - User-specified commit range via flags
   - Since last release notes entry in CHANGELOG.md
   - If no tags exist: uses root commit automatically
4. **keryx gathers change data:**
   - Fetches git commits in range
   - Fetches merged PRs from GitHub API
5. **keryx spawns Claude Code CLI** with the commit/PR data and prompts Claude to:
   - Summarize/rewrite cryptic commit messages into human-readable descriptions
   - Categorize changes as Added/Changed/Deprecated/Removed/Fixed/Security
   - Generate benefit-focused, user-facing copy (Linear-style)
6. **keryx determines version number:**
   - Auto-infers from last tag + commit types (semantic versioning)
   - `feat:` commits = minor bump (1.1.0 → 1.2.0)
   - `fix:` commits = patch bump (1.1.0 → 1.1.1)
   - Breaking changes = major bump
   - User can override with explicit version flag
7. **keryx writes to CHANGELOG.md:**
   - If file doesn't exist: creates it with Keep a Changelog header
   - If `[Unreleased]` section exists: converts to versioned section per Keep a Changelog standard
   - Inserts new version section with date
8. **keryx displays summary:**
   - "Added 5 entries (3 features, 2 fixes) to CHANGELOG.md"

### Error Handling

- **No changes in range:** Exit with message "No changes found since {ref}. Nothing to add." No file modification.
- **Claude Code missing:** Check at startup, exit with helpful installation/auth instructions.
- **LLM failure:** Retry with exponential backoff, then fail with clear error message.

## Examples

### Happy Path

**Input:**
```bash
keryx
```

**State:** Repository has tag `v1.2.0`, three commits since then:
- `feat(auth): add OAuth2 support`
- `fix: resolve memory leak in parser`
- `docs: update README`

**Output:**
```
✓ Added 2 entries (1 feature, 1 fix) to CHANGELOG.md
```

**CHANGELOG.md receives:**
```markdown
## [1.3.0] - 2025-01-25

### Added
- OAuth2 authentication support for secure third-party integrations

### Fixed
- Resolved memory leak in parser that could cause slowdowns over time
```

### Edge Case: No Tags Exist

**Input:**
```bash
keryx
```

**State:** New repository, no tags, 5 commits total.

**Behavior:** Uses root commit as starting point, processes all 5 commits, creates CHANGELOG.md with `[0.1.0]` section.

### Error Case: Claude Code Not Installed

**Input:**
```bash
keryx
```

**Output:**
```
Error: Claude Code CLI not found.

keryx requires Claude Code to generate release notes.

To install:
  npm install -g @anthropic-ai/claude-code

After installing, authenticate:
  claude login
```

Exit code: 1

## Scope

### In Scope
- Standalone Rust CLI (`keryx` command)
- Input from git commits (conventional commits) + GitHub PRs
- Spawning Claude Code CLI subprocess for LLM generation
- Writing to CHANGELOG.md in Keep a Changelog format
- Automatic semantic version bumping with override option
- Change range detection (since tag, commit range, since last entry)
- Creating CHANGELOG.md if it doesn't exist
- Handling `[Unreleased]` section per Keep a Changelog standard
- Retry with exponential backoff for LLM failures
- Clear error messages for missing prerequisites

### Out of Scope
- GitHub Release creation (not pushing to GitHub Releases API)
- Multiple output formats (no JSON, HTML, only Markdown)
- Visual assets handling (no GIFs, screenshots)
- Email/notification distribution
- GitLab/Bitbucket support (GitHub only for PR fetching)
- Custom templates or themes
- CI/CD integration (GitHub Actions, pre-commit hooks)
- Web UI or dashboard
- Interactive preview/editing before write
- Non-Claude-Code LLM backends

## Open Questions

1. **GitHub Authentication:** How should keryx authenticate to fetch PRs? Use `gh` CLI auth? Environment variable? Prompt user?
2. **Retry limits:** How many retries before giving up on Claude? 3? 5?
3. **Rate limiting:** If fetching many PRs, should keryx handle GitHub rate limits gracefully?

## Priority

**Urgency:** High - serves multiple needs simultaneously:
- Personal projects need changelogs now
- OSS portfolio piece to publish and share
- Learning opportunity to explore Claude Code CLI integration patterns
- Production tool for team release workflows

**What's blocked without this:** Projects continue shipping without documented changes, increasing communication overhead and reducing discoverability of features/fixes.
