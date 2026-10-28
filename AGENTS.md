# Repository Agent Instructions

These rules apply equally to `AGENTS.md` and `CLAUDE.md`. Keep both files identical.

## What lives here

- `bench/` — the replay benchmark (Python package `keryx_bench`).
- `docs/design/` — designs; `docs/plans/` — implementation plans; `docs/bench/` — published benchmark summaries (aggregate numbers only).

## Rules

- No committed file names an external skill pack.
- Private data never enters the repo: cases, system files, results and provenance live in `~/.config/keryx/` and `~/.local/share/keryx/`.
- Commits follow Conventional Commits, never name an AI assistant or tool, and carry no co-author trailers. Stage files by name.
- Never push, tag or open a PR without the owner's explicit go.
- Dependencies: latest versions via `uv pip install`, pinned in `bench/requirements.txt` to the installed version.
- Never print or store credentials.

## Tests

```bash
cd bench && .venv/bin/pytest -q
```

Unit tests make no model calls. Live tests run only with `KERYX_LIVE=1`.
