"""Rework: did "done" stick? For each owner turn that made commits, the fix or revert commits that touched the
same files within 72 hours after it ended. A quality signal from git, not from the wording of the chat.

Reads only git history (all branches) of the repositories the sessions ran in; no model calls, no text kept.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

WINDOW_S = 72 * 3600
_REWORK = re.compile(r"^(revert\b|fix(\(|:|!)|hotfix\b|bugfix\b)", re.I)


@dataclass(frozen=True)
class Commit:
    sha: str
    when: float
    subject: str
    files: frozenset[str]


@dataclass(frozen=True)
class TurnWindow:
    start: str
    end: str


def _t(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def is_rework_subject(subject: str) -> bool:
    return bool(_REWORK.search(subject.strip()))


def repo_commits(repo: Path, since: str = "60 days ago") -> list[Commit]:
    out = subprocess.run(["git", "-C", str(repo), "log", "--all", f"--since={since}", "--no-merges",
                          "--format=%x1e%H%x1f%ct%x1f%s", "--name-only"],
                         capture_output=True, text=True).stdout
    commits = []
    for record in out.split("\x1e")[1:]:
        head, _, names = record.partition("\n")
        sha, when, subject = head.split("\x1f", 2)
        commits.append(Commit(sha, float(when), subject, frozenset(n for n in names.splitlines() if n.strip())))
    return commits


def rework_for(turn: TurnWindow, commits: list[Commit],
               own: set[str] | None = None) -> tuple[list[Commit], list[Commit]]:
    """(the turn's own commits, the rework commits that followed them). With `own` (short SHAs the turn's
    commit calls printed), only those count as the turn's; otherwise every commit made while it ran."""
    start, end = _t(turn.start), _t(turn.end)
    made = sorted((c for c in commits if (any(c.sha.startswith(s) for s in own) if own is not None
                                          else start <= c.when <= end)), key=lambda c: c.when)
    files = frozenset().union(*(c.files for c in made)) if made else frozenset()
    redo = sorted((c for c in commits if end < c.when <= end + WINDOW_S and c.files & files
                   and is_rework_subject(c.subject)), key=lambda c: c.when)
    return made, redo
