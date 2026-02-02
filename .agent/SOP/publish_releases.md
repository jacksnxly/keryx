# How to: Publish a Release

## Overview

This procedure covers releasing a new version of keryx, from merging a PR through to published GitHub Release with cross-platform binaries.

keryx uses **cargo-dist** (v0.30.3) for automated cross-platform builds and **GitHub Actions** for CI/CD. Pushing a version tag triggers the full release pipeline.

## Prerequisites

- Push access to `main` branch on GitHub
- `gh` CLI authenticated (`gh auth status`)
- `cargo` installed locally
- CHANGELOG.md updated for the new version (follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format)

## Release Pipeline Overview

```
Push vX.Y.Z tag
  └─→ release.yml triggers
        ├─→ plan (determines build matrix)
        ├─→ build-local-artifacts (per-platform binaries)
        │     ├── aarch64-apple-darwin
        │     ├── aarch64-unknown-linux-gnu
        │     ├── x86_64-apple-darwin
        │     ├── x86_64-unknown-linux-gnu
        │     └── x86_64-pc-windows-msvc
        ├─→ build-global-artifacts (checksums, installers)
        ├─→ host (upload to GitHub Release)
        └─→ announce
```

Installers generated: `shell` (Unix) and `powershell` (Windows).

## Steps

### 1. Merge the PR

Merge the feature branch into `main` via GitHub (squash merge or merge commit).

```bash
# Or from CLI:
gh pr merge --merge
```

Pull the merged main locally:

```bash
git checkout main && git pull origin main
```

### 2. Verify CHANGELOG.md

Ensure the CHANGELOG has a section for the new version with the correct date:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- ...

### Changed
- ...

### Fixed
- ...
```

If not already present, add it now following the existing format. Commit:

```bash
git add CHANGELOG.md
git commit -m "docs: update CHANGELOG for vX.Y.Z"
```

### 3. Bump version in Cargo.toml

Update the `version` field in `Cargo.toml`:

```toml
[package]
version = "X.Y.Z"
```

Verify it compiles:

```bash
cargo check
```

Commit the version bump:

```bash
git add Cargo.toml Cargo.lock
git commit -m "chore: bump version to X.Y.Z"
```

### 4. Push to main

```bash
git push origin main
```

### 5. Create and push the version tag

The tag **must** follow the `vX.Y.Z` format to trigger the release workflow.

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

### 6. Monitor the release workflow

The tag push triggers `.github/workflows/release.yml` automatically.

```bash
# Watch the workflow run:
gh run watch

# Or list recent runs:
gh run list --workflow=release.yml --limit=3
```

The workflow runs these jobs in sequence:
1. **plan** — Determines the build matrix from cargo-dist
2. **build-local-artifacts** — Compiles binaries for all 5 target platforms
3. **build-global-artifacts** — Generates checksums and installers
4. **host** — Uploads artifacts to the GitHub Release
5. **announce** — Final announcement step

### 7. Verify the release

```bash
# Check the GitHub Release was created:
gh release view vX.Y.Z

# List all releases:
gh release list
```

Also verify on GitHub: `https://github.com/jacksnxly/keryx/releases/tag/vX.Y.Z`

Confirm the release includes:
- Release notes from CHANGELOG
- Binary archives for all 5 platforms
- Shell installer script
- PowerShell installer script

## Version Numbering

This project follows [Semantic Versioning](https://semver.org/):

| Change type | Bump | Example |
|-------------|------|---------|
| Bug fix, patch | PATCH | 0.3.0 → 0.3.1 |
| New feature, backwards compatible | MINOR | 0.3.0 → 0.4.0 |
| Breaking API change | MAJOR | 0.4.0 → 1.0.0 |

## Quick Reference (Copy-Paste)

For a release of version `0.4.0` after merging a PR:

```bash
git checkout main && git pull origin main
# Edit Cargo.toml version to "0.4.0" if not done
# Edit CHANGELOG.md if not done
cargo check
git add Cargo.toml Cargo.lock CHANGELOG.md
git commit -m "chore: bump version to 0.4.0"
git push origin main
git tag v0.4.0
git push origin v0.4.0
gh run watch
gh release view v0.4.0
```

## Troubleshooting

### Release workflow didn't trigger

- Verify the tag matches the pattern `**[0-9]+.[0-9]+.[0-9]+*`
- Check that the tag was pushed: `git ls-remote --tags origin | grep vX.Y.Z`
- View workflow runs: `gh run list --workflow=release.yml`

### Build failed for a platform

```bash
# View the failed run logs:
gh run view <run-id> --log-failed
```

Fix the issue, then delete the tag and re-release:

```bash
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
# Fix, commit, push, then re-tag
git tag vX.Y.Z
git push origin vX.Y.Z
```

### Tag exists but no GitHub Release

This can happen if the workflow failed mid-way (tag `v0.3.0` shows this pattern). Delete the tag and re-push, or manually create the release:

```bash
gh release create vX.Y.Z --title "X.Y.Z - YYYY-MM-DD" --notes-file CHANGELOG.md
```

### Cargo.toml version doesn't match tag

cargo-dist will error if the tag version doesn't match `Cargo.toml`. Always ensure they agree before tagging.

## Past Releases

| Version | Date | Notes |
|---------|------|-------|
| v0.1.0 | 2026-01-25 | Initial release |
| v0.1.1 | 2026-01-26 | `keryx init` command |
| v0.2.0 | 2026-01-29 | Verification, LLM routing |
| v0.3.0 | 2026-02-02 | LLM version bumping (tag exists, GitHub Release missing) |

## Related Documentation

- [cargo-dist docs](https://opensource.axo.dev/cargo-dist/)
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
- [Semantic Versioning](https://semver.org/)
- Release workflow: `.github/workflows/release.yml`
- dist config: `dist-workspace.toml`
