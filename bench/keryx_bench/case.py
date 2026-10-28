"""A benchmark case: a task with a known good outcome and hidden checks that score a result."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from keryx_bench.owner import OwnerScript, load_owner

MODES = ("bug", "review", "feature")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class CaseError(ValueError):
    pass


@dataclass(frozen=True)
class Check:
    name: str
    run: str
    timeout_s: int = 900


@dataclass(frozen=True)
class KnownDefect:
    id: str
    check: str


@dataclass(frozen=True)
class Budget:
    timeout_min: int = 30
    max_usd: float = 5.0


@dataclass(frozen=True)
class Case:
    id: str
    mode: str
    repo: str
    base: str
    good: str
    prompt: str
    owner: OwnerScript
    hidden_dir: Path
    checks: tuple[Check, ...]
    known_defects: tuple[KnownDefect, ...]
    env: Mapping[str, str]
    prepare: str | None
    budget: Budget
    tags: tuple[str, ...]
    path: Path
    check_env: Mapping[str, str] = field(default_factory=dict)  # for hidden checks and prepare only, never the system
    base_failed: tuple[str, ...] | None = None  # from validation.json: the checks the unfinished base fails


def load_case(case_dir: Path) -> Case:
    case_dir = Path(case_dir)
    raw = yaml.safe_load((case_dir / "case.yaml").read_text()) or {}

    def need(key: str):
        if raw.get(key) in (None, ""):
            raise CaseError(f"{case_dir}: case.yaml needs {key}")
        return raw[key]

    mode = str(need("mode"))
    if mode not in MODES:
        raise CaseError(f"{case_dir}: mode must be one of {', '.join(MODES)}, not {mode!r}")
    shas = {}
    for key in ("base", "good"):
        value = str(need(key))
        if not _SHA.match(value):
            raise CaseError(f"{case_dir}: {key} must be a full 40-character commit SHA, not {value!r}")
        shas[key] = value

    hidden = need("hidden")
    hidden_dir = case_dir / str(hidden.get("files") or "")
    if not hidden.get("files") or not hidden_dir.is_dir():
        raise CaseError(f"{case_dir}: hidden.files must name a directory in the case")
    checks = tuple(
        Check(name=str(c["name"]), run=str(c["run"]), timeout_s=int(c.get("timeout_s", 900)))
        for c in hidden.get("checks") or []
    )
    if not checks:
        raise CaseError(f"{case_dir}: hidden.checks needs at least one check")
    names = {c.name for c in checks}
    if len(names) != len(checks):
        raise CaseError(f"{case_dir}: hidden.checks names must be unique")

    defects = tuple(KnownDefect(id=str(d["id"]), check=str(d["check"])) for d in raw.get("known_defects") or [])
    if mode == "review" and not defects:
        raise CaseError(f"{case_dir}: a review case needs known_defects")
    for d in defects:
        if d.check not in names:
            raise CaseError(f"{case_dir}: known defect {d.id} names check {d.check}, which hidden.checks lacks")

    budget_raw = raw.get("budget") or {}
    budget = Budget(timeout_min=int(budget_raw.get("timeout_min", 30)), max_usd=float(budget_raw.get("max_usd", 5.0)))
    if budget.timeout_min <= 0 or budget.max_usd <= 0:
        raise CaseError(f"{case_dir}: budget values must be positive")

    try:
        owner = load_owner(case_dir / str(need("owner")))
    except ValueError as err:
        raise CaseError(str(err)) from err

    case = Case(
        id=str(need("id")),
        mode=mode,
        repo=str(need("repo")),
        base=shas["base"],
        good=shas["good"],
        prompt=(case_dir / str(need("prompt"))).read_text(),
        owner=owner,
        hidden_dir=hidden_dir,
        checks=checks,
        known_defects=defects,
        env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        prepare=str(raw["prepare"]) if raw.get("prepare") else None,
        budget=budget,
        tags=tuple(str(t) for t in raw.get("tags") or []),
        path=case_dir,
        check_env={str(k): str(Path(str(v)).expanduser()) if str(v).startswith("~") else str(v)
                   for k, v in (raw.get("check_env") or {}).items()},
    )
    return _with_validation(case)


def _with_validation(case: Case) -> Case:
    """Attaches the base result recorded by validate, if it was recorded for exactly this content."""
    import dataclasses
    import json

    record = case.path / "validation.json"
    if not record.exists():
        return case
    data = json.loads(record.read_text())
    if data.get("case_hash") != case_hash(case):
        return case
    return dataclasses.replace(case, base_failed=tuple(data.get("base_failed") or ()))


def case_hash(case: Case) -> str:
    digest = hashlib.sha256()
    raw = yaml.safe_load((case.path / "case.yaml").read_text())
    files = [case.path / "case.yaml", case.path / str(raw["prompt"]), case.path / str(raw["owner"])]
    files += sorted(p for p in case.hidden_dir.rglob("*") if p.is_file())
    for path in files:
        digest.update(str(path.relative_to(case.path)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
