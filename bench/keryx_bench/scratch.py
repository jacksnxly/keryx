"""Scratch a run leaves in the shared /tmp: found by name in its own tool calls, stopped and removed after it.

/tmp is shared by every run and by the owner's other sessions. A run's coordinator, its subagents and its executor
write scratch there by literal path (`/tmp/rc-review-target`), so two runs of the same task pick the same names.
Only names a run itself used and that did not exist before it started are removed. A name it used that already
existed is an isolation breach: it may hold another run's work.
"""
from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from keryx_bench.workspace import stop_strays

TMP_ROOT = Path("/private/tmp")
_NAME = re.compile(r"/(?:private/)?tmp/([A-Za-z0-9._-]+)")
# Never a run's own: Claude Code's per-session folders (their paths carry the run id), sockets, system entries.
SHARED_PREFIXES = ("claude-", "cc-socks", ".s.PGSQL", "com.apple.", "tmux-", "launchd")


def tmp_entries(root: Path | None = None) -> set[str]:
    root = Path(root or TMP_ROOT)
    return {p.name for p in root.iterdir()} if root.is_dir() else set()


def tmp_names_used(files: Iterable[Path]) -> set[str]:
    """The top-level /tmp names a run's transcripts and logs mention."""
    names = set()
    for path in files:
        if Path(path).is_file():
            names |= set(_NAME.findall(Path(path).read_text(errors="replace")))
    return {n for n in names if n not in (".", "..") and not n.startswith(SHARED_PREFIXES)}


def tidy_tmp(root: Path | None, before: set[str], used: set[str]) -> tuple[list[str], list[str]]:
    """(removed, preexisting): stops processes tied to the run's new /tmp entries, removes those entries,
    and lists the names the run used that existed before it started."""
    root = Path(root or TMP_ROOT)
    present = tmp_entries(root)
    new = sorted(n for n in used & present if n not in before)
    spellings = [str(root / n) for n in new]
    if root.resolve() == Path("/private/tmp"):
        spellings += [f"/tmp/{n}" for n in new]
    stop_strays(root / ".no-such-run", also=spellings)
    for name in new:
        path = root / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    return new, sorted(used & before)
