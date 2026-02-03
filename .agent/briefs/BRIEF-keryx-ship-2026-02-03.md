---
status: PENDING TECHNICAL REVIEW
author: jacksnxly
created: 2026-02-03
feature: keryx ship
---

# Feature Brief: keryx ship

## Problem

**Persona:** Any contributor with push access to a project using keryx.

**Trigger:** A PR has been merged to the main branch (or any branch) and the contributor decides it's time to cut a release.

**Current State:**
1. Developer merges a feature PR that already includes a manual version bump in Cargo.toml and a hand-written CHANGELOG.md section
2. Developer switches to main and pulls
3. Developer manually runs `git tag vX.Y.Z`
4. Developer runs `git push --tags`
5. cargo-dist CI takes over from the tag

**Pain:**
- Forgot to bump the version in Cargo.toml (tag points to old version)
- Tagged the wrong commit (before the version bump commit was pushed)
- Manual steps are fragile and undocumented — new contributors can't ship releases without tribal knowledge
- Changelog sections are sometimes stale or missing for the tagged version
- The whole process discourages frequent, small releases

## Solution

### User Journey

**Step 1: Run the command**
```
keryx ship
```
Or with overrides:
```
keryx ship --set-version 1.0.0
keryx ship --no-llm-bump
keryx ship --dry-run
```

**Step 2: Preflight checks**
The command runs a series of checks and displays results:
```
Preflight checks:
  [PASS] Working tree is clean
  [PASS] Local branch is up to date with remote
  [PASS] 7 commits since v0.4.0
  [PASS] LLM provider available
```
If any check fails, the command aborts with a clear message explaining what's wrong.

**Step 3: Version calculation**
Using the LLM bump (default) or algorithmic fallback (with `--no-llm-bump`), the next version is determined:
```
Version: 0.4.0 -> 0.5.0 (minor: new features detected)
```
If `--set-version` is provided, that version is used instead.

If a tag for the calculated version already exists, suggest the next available version:
```
v0.5.0 already exists. Did you mean v0.5.1?
```

**Step 4: Version file detection and bump**
Auto-detect which version file(s) the project uses and update them:
- `Cargo.toml` (Rust)
- `package.json` (Node.js)
- `pyproject.toml` (Python)

```
Version files:
  [UPDATE] Cargo.toml: 0.4.0 -> 0.5.0
```

**Step 5: Changelog check/generation**
Check if CHANGELOG.md (or CHANGES.md, HISTORY.md) already has a section for the target version:
- If a section for v0.5.0 already exists: skip changelog generation, show `[SKIP] Changelog section for 0.5.0 already exists`
- If no section exists: auto-generate one using keryx's existing release note engine, show `[CREATE] Changelog section for 0.5.0`

**Step 6: Confirmation prompt**
Show a summary and ask for confirmation (unless `--dry-run`):
```
Summary:
  Version:   0.4.0 -> 0.5.0
  Changelog: Auto-generated (7 entries)
  Commit:    chore(release): v0.5.0
  Tag:       v0.5.0
  Push to:   origin/main

Proceed? [Y/n]
```

In `--dry-run` mode, show the summary and exit without executing.

**Step 7: Execute**
1. Update version file(s)
2. Update changelog (if needed)
3. Create commit: `chore(release): v0.5.0`
4. Create tag: `v0.5.0`
5. Push commit and tag to remote

```
  [DONE] Updated Cargo.toml
  [DONE] Updated CHANGELOG.md
  [DONE] Created commit: chore(release): v0.5.0
  [DONE] Created tag: v0.5.0
  [DONE] Pushed to origin/main

Release v0.5.0 shipped! cargo-dist will build and publish artifacts.
```

**Step 8: Rollback on failure**
If `git push` fails, roll back everything:
- Delete the local tag
- Reset the release commit
- Display error with instructions

## Examples

### Happy Path
**Input:** Developer runs `keryx ship` on main after merging a PR that added a new `export` subcommand.
**State:** Clean working tree, 3 commits since v0.4.0 (`feat: add export command`, `test: add export tests`, `docs: update README`).
**Output:**
- LLM determines: minor bump (new feature)
- Cargo.toml: 0.4.0 -> 0.5.0
- Changelog: auto-generated section with 3 entries under `## [0.5.0] - 2026-02-03`
- Commit `chore(release): v0.5.0` created
- Tag `v0.5.0` pushed
- cargo-dist CI triggered

### Edge Case: Changelog Already Exists
**Input:** Developer already wrote a changelog section for 0.5.0 manually in the feature PR.
**State:** CHANGELOG.md contains `## [0.5.0]` section.
**Output:**
- Version calculation: 0.5.0
- Changelog: `[SKIP] Changelog section for 0.5.0 already exists`
- Only Cargo.toml is updated, changelog left as-is
- Release proceeds normally

### Edge Case: Tag Already Exists
**Input:** Developer runs `keryx ship`, calculated version is 0.5.0, but tag v0.5.0 already exists.
**Output:**
```
v0.5.0 already exists. Did you mean v0.5.1? [Y/n]
```
If confirmed, proceeds with 0.5.1.

### Error Case: Dirty Working Tree
**Input:** Developer has uncommitted changes.
**Output:**
```
Preflight checks:
  [FAIL] Working tree has uncommitted changes

Aborting. Commit or stash your changes before shipping.
```
Exit code 1, nothing modified.

### Error Case: LLM Unavailable
**Input:** No API key configured, network error, or provider timeout.
**Output:**
```
Preflight checks:
  [FAIL] LLM provider unavailable: ANTHROPIC_API_KEY not set

Aborting. Set an API key or use --no-llm-bump for algorithmic versioning.
```

### Error Case: Push Failure
**Input:** Remote rejects the push (e.g., branch protection, auth failure).
**Output:**
```
  [DONE] Created commit: chore(release): v0.5.0
  [DONE] Created tag: v0.5.0
  [FAIL] Push failed: remote rejected (branch protection)

Rolling back...
  [DONE] Deleted tag v0.5.0
  [DONE] Reset commit chore(release): v0.5.0

Release aborted. Fix the push issue and try again.
```

## Scope

### In Scope
- Preflight checks (clean tree, up to date with remote, commits exist, LLM available)
- Version calculation (LLM bump by default, algorithmic with `--no-llm-bump`, manual with `--set-version`)
- Auto-detection and updating of version files (Cargo.toml, package.json, pyproject.toml)
- Auto-detection of changelog files (CHANGELOG.md, CHANGES.md, HISTORY.md)
- Changelog section check (skip if exists) or generation (using existing keryx engine)
- Release commit creation (`chore(release): vX.Y.Z`)
- Git tag creation
- Push commit + tag to remote
- Dry-run mode (`--dry-run`)
- Interactive confirmation prompt
- Full rollback on push failure
- Tag collision detection with next-version suggestion

### Out of Scope
- Pre-release channels (rc, beta, alpha tags)
- GitHub Release body editing (cargo-dist handles this)
- SBOM generation or artifact attestations (cargo-dist configuration)
- Slack/Discord/webhook notifications
- Release branch creation
- Monorepo / workspace-aware multi-package releases
- `cargo publish` or `npm publish` or any registry publishing
- Post-release smoke testing

## Open Questions

None — all requirements clarified during interview.

## Priority

**Why now:**
- Dogfooding: keryx needs this for its own releases. The last two releases (v0.3.0, v0.4.0) both involved manual steps that led to mistakes (forgotten version bumps, tags on wrong commits).
- User demand: contributors have asked for release automation.
- Past mistakes: time has been lost on botched releases that could have been prevented by automated checks.

**What's blocked:** New contributors cannot confidently ship releases without detailed tribal knowledge of the manual process.
