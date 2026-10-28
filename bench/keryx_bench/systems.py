"""A system under test: the coordinator model, the plugins it loads, and how each mode is started."""
from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from keryx_bench.case import MODES

RESERVED_PREFIXES = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
ALLOWED_SETTING_SOURCES = ("project",)  # the repo's own committed settings; never the owner's user or local ones


class SystemConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Assemble:
    name: str
    skills: tuple[Path, ...]
    session_start_text: Path | None


@dataclass(frozen=True)
class System:
    name: str
    model: str
    plugins: tuple[Path, ...]
    assemble: Assemble | None
    entry: Mapping[str, str]
    env: Mapping[str, str]
    setting_sources: tuple[str, ...] = ()


def _path(value) -> Path:
    return Path(str(value)).expanduser()


def load_system(path: Path) -> System:
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    for key in ("name", "model", "entry"):
        if not raw.get(key):
            raise SystemConfigError(f"{path}: system needs {key}")
    entry = {str(k): str(v) for k, v in raw["entry"].items()}
    for mode in MODES:
        if mode not in entry:
            raise SystemConfigError(f"{path}: entry needs a prompt for mode {mode}")
        if "{prompt}" not in entry[mode]:
            raise SystemConfigError(f"{path}: entry for {mode} must contain {{prompt}}")
    assemble = None
    if raw.get("assemble"):
        a = raw["assemble"]
        name = str(a.get("name") or "")
        if not name or name.lower().startswith(RESERVED_PREFIXES):
            raise SystemConfigError(f"{path}: assemble.name must be set and not start with a reserved prefix")
        skills = tuple(_path(s) for s in a.get("skills") or [])
        missing = [str(s) for s in skills if not (s / "SKILL.md").exists()]
        if missing:
            raise SystemConfigError(f"{path}: no SKILL.md in {', '.join(missing)}")
        text = _path(a["session_start_text"]) if a.get("session_start_text") else None
        if text and not text.is_file():
            raise SystemConfigError(f"{path}: session_start_text {text} does not exist")
        assemble = Assemble(name=name, skills=skills, session_start_text=text)
    sources = tuple(str(x) for x in raw.get("setting_sources") or ())
    banned = [x for x in sources if x not in ALLOWED_SETTING_SOURCES]
    if banned:
        raise SystemConfigError(f"{path}: setting_sources may only name {ALLOWED_SETTING_SOURCES}, not {banned}")
    return System(
        name=str(raw["name"]),
        model=str(raw["model"]),
        plugins=tuple(_path(p) for p in raw.get("plugins") or []),
        assemble=assemble,
        entry=entry,
        env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        setting_sources=sources,
    )


def materialize(system: System, dest: Path) -> list[Path]:
    dirs = list(system.plugins)
    if system.assemble is None:
        return dirs
    a = system.assemble
    root = Path(dest) / a.name
    if root.exists():
        shutil.rmtree(root)
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(
        {"name": a.name, "version": "0.0.0", "description": f"Assembled for the benchmark system {system.name}"},
        indent=2) + "\n")
    for skill in a.skills:
        shutil.copytree(skill.resolve(), root / "skills" / skill.name, symlinks=False)
    if a.session_start_text:
        shutil.copyfile(a.session_start_text, root / "session-start.md")
        (root / "hooks").mkdir()
        hook = {"type": "command", "command": 'cat "${CLAUDE_PLUGIN_ROOT}/session-start.md"'}
        (root / "hooks" / "hooks.json").write_text(json.dumps(
            {"hooks": {"SessionStart": [{"hooks": [hook]}]}}, indent=2) + "\n")
    dirs.append(root)
    return dirs
