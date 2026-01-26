# keryx

> Greek for "herald" - announces your releases

AI-powered release notes generator that creates changelogs from merged PRs and conventional commits using Claude.

## Installation

### Quick Install (Recommended)

**macOS / Linux:**
```bash
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/jacksnxly/keryx/releases/latest/download/keryx-installer.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://github.com/jacksnxly/keryx/releases/latest/download/keryx-installer.ps1 | iex"
```

### From Source

```bash
cargo install --git https://github.com/jacksnxly/keryx
```

### Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) must be installed and authenticated
- For PR fetching: GitHub CLI (`gh`) authenticated, or `GITHUB_TOKEN`/`GH_TOKEN` environment variable

## Usage

```bash
# Generate release notes (writes to CHANGELOG.md)
keryx

# Preview without writing
keryx --dry-run

# Skip GitHub PR fetching (commits only)
keryx --no-prs

# Specify version manually
keryx --set-version 1.0.0

# Custom commit range
keryx --from v0.1.0 --to HEAD

# Custom output file
keryx -o RELEASES.md
```

### Initialize a New Changelog

For existing projects without a changelog:

```bash
# Create empty changelog template
keryx init

# Generate changelog with all commits as [Unreleased]
keryx init --unreleased

# Build complete changelog from git tag history
keryx init --from-history

# Preview without writing
keryx init --from-history --dry-run
```

## How It Works

1. **Analyzes commits** - Parses conventional commits (feat, fix, etc.) since the last tag
2. **Fetches PRs** - Retrieves merged pull requests from GitHub for additional context
3. **Generates notes** - Uses Claude to transform technical changes into user-friendly descriptions
4. **Writes changelog** - Outputs in [Keep a Changelog](https://keepachangelog.com/) format

## Features

- **Conventional Commits** - Automatically parses `feat:`, `fix:`, `chore:`, etc.
- **Semantic Versioning** - Auto-calculates next version based on commit types
- **Keep a Changelog** - Outputs spec-compliant markdown with proper categories
- **GitHub Integration** - Enriches notes with PR titles and descriptions
- **Smart Initial Releases** - Describes project capabilities for first releases
- **Backup Safety** - Creates `.bak` file before modifying existing changelogs

## Configuration

keryx uses sensible defaults with no configuration required. All options are available via CLI flags.

| Flag | Description | Default |
|------|-------------|---------|
| `--set-version` | Override auto-detected version | Auto from commits |
| `--from` | Start of commit range | Latest tag |
| `--to` | End of commit range | `HEAD` |
| `-o, --output` | Changelog file path | `CHANGELOG.md` |
| `--no-prs` | Skip GitHub PR fetching | `false` |
| `--dry-run` | Preview without writing | `false` |

### Init Command Flags

| Flag | Description |
|------|-------------|
| `--unreleased` | Generate entries from all commits into [Unreleased] section |
| `--from-history` | Generate entries for each existing git tag |
| `--force` | Overwrite if version already exists in changelog |

## License

MIT
