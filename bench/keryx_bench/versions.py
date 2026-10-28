"""What produced a run: the harness commit and a fingerprint of the system under test."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from keryx_bench.systems import System

REPO = Path(__file__).resolve().parents[2]


def harness_version() -> str:
    """The keryx commit the bench ran from, with "-dirty" when bench/ had uncommitted changes."""
    try:
        sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short=12", "HEAD"], check=True,
                             capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "bench"],
                               capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return sha + ("-dirty" if dirty else "")


def system_fingerprint(system: System, path: Path | None = None) -> str:
    """Hash of the system file and every file it brings in (plugins, assembled skills, session text)."""
    digest = hashlib.sha256()
    files: list[Path] = [Path(path)] if path else []
    dirs = list(system.plugins)
    if system.assemble:
        dirs += list(system.assemble.skills)
        if system.assemble.session_start_text:
            files.append(system.assemble.session_start_text)
    for d in dirs:
        files += sorted(f for f in Path(d).resolve().rglob("*") if f.is_file() and ".git" not in f.parts)
    for f in files:
        digest.update(str(f).encode())
        digest.update(b"\0")
        digest.update(f.read_bytes())
    return digest.hexdigest()
