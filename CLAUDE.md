# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**keryx** (Greek for "herald") - A CLI tool that generates release notes from merged PRs and conventional commits.

## SESSION INITIALIZATION

**IMPORTANT:** At the start of every session:

1. **Get the current developer's Git username:**

   ```bash
   git config user.name
   ```

2. **Load the developer-specific session context:**

   Read `.agent/sessions/{git_username}/last_session.md`

   If the developer's session folder doesn't exist yet, that's okay - it will be created when they run `/save_session`.

3. **Also read** `.agent/README.md` for overall project context.

## DEVELOPER SESSION STRUCTURE

Each developer has their own session context folder:

```
.agent/sessions/
├── {developer1}/
│   └── last_session.md
├── {developer2}/
│   └── last_session.md
└── ...
```

This allows multiple contributors to maintain their own session context without conflicts.

## VIBE CODING WORKFLOW

This project uses the **vibe-coding-toolkit** for structured development:

```
Phase 1: /feature-brief    → Discovery interview → .agent/briefs/{feature}.md
Phase 2: /technical-spec   → Research & design  → .agent/specs/{feature}.md
Phase 3: /implement-feature → Build from spec    → Code changes
Phase 4: /review-code      → Audit & verify     → Approval or fixes
```

**Rules:**
- Phase 2 requires an approved brief from Phase 1
- Phase 3 requires an approved spec from Phase 2
- Never skip phases - each gate ensures quality

## DOCUMENTATION STRUCTURE

```
.agent/
├── sessions/{username}/   # Developer session context
│   └── last_session.md
├── briefs/                # Feature briefs (Phase 1 output)
├── specs/                 # Technical specs (Phase 2 output)
├── Tasks/                 # PRD & implementation plans
├── System/                # Architecture & tech stack docs
├── SOP/                   # Standard operating procedures
└── README.md              # Index of all documentation
```

Always update `.agent` docs after implementing features to keep them current.

## COMMIT GUIDELINES

Use Conventional Commits:
- `feat:` new features
- `fix:` bug fixes
- `docs:` documentation
- `refactor:` code restructuring
- `test:` adding tests

**IMPORTANT:** Always ask for approval before committing or pushing.
