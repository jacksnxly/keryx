"""Where Claude Code keeps a session's transcript for a working directory, so a run can remove it."""
from __future__ import annotations

import re
import shutil
from pathlib import Path


def session_dir_for(cwd: str) -> Path:
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", cwd)


def keep_subagent_transcripts(cwd: str, dest: Path) -> list[Path]:
    """Copies the subagents' own transcripts of the sessions run in `cwd`, before the session folder goes."""
    kept = []
    for source in sorted(session_dir_for(cwd).glob("*/subagents/*.jsonl")):
        Path(dest).mkdir(parents=True, exist_ok=True)
        target = Path(dest) / source.name
        shutil.copyfile(source, target)
        kept.append(target)
    return kept


def remove_session_dir(cwd: str, must_contain: str) -> bool:
    path = session_dir_for(cwd)
    if must_contain and must_contain in path.name and path.is_dir():
        shutil.rmtree(path)
        return True
    return False
