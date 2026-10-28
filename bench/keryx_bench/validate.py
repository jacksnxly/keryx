"""A case is valid only if its hidden checks tell the unfinished base from the known good result."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from keryx_bench.case import Case
from keryx_bench.workspace import apply_hidden, run_checks, run_prepare, score_lock, tree_at


@dataclass(frozen=True)
class Validation:
    ok: bool
    base_failed: tuple[str, ...]
    good_failed: tuple[str, ...]
    reasons: tuple[str, ...]


def _failing(case: Case, scratch: Path, ref: str, name: str, runs: int = 1) -> list[tuple[str, ...]]:
    tree = tree_at(case, scratch / name, ref)
    with score_lock(case):
        run_prepare(tree, case)
        apply_hidden(tree, case)
        return [tuple(r.name for r in run_checks(tree, case) if not r.passed) for _ in range(runs)]


def validate_case(case: Case, runs_root: Path, good_runs: int = 1) -> Validation:
    """Rejects a case unless its checks fail on base and pass on good in every one of `good_runs` runs."""
    Path(runs_root).mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f"validate-{case.id}-", dir=runs_root))
    try:
        [base_failed] = _failing(case, scratch, case.base, "base")
        good_rounds = _failing(case, scratch, case.good, "good", runs=good_runs)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    reasons = []
    if case.mode == "review":
        reasons += [f"known defect {d.id} passes on base" for d in case.known_defects if d.check not in base_failed]
    elif not base_failed:
        reasons.append("every check passes on base")
    good_failed = []
    for check in case.checks:
        failures = sum(check.name in failed for failed in good_rounds)
        if failures == len(good_rounds):
            good_failed.append(check.name)
            reasons.append(f"check {check.name} fails on good")
        elif failures:
            good_failed.append(check.name)
            reasons.append(f"check {check.name} is flaky on good ({failures} of {len(good_rounds)} runs failed)")
    return Validation(ok=not reasons, base_failed=base_failed, good_failed=tuple(good_failed), reasons=tuple(reasons))
