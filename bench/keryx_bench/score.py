"""The score of one run: quality from the hidden checks, plus time, cost and interruptions."""
from __future__ import annotations

from dataclasses import dataclass

from keryx_bench.case import Case
from keryx_bench.driver import RunRecord
from keryx_bench.workspace import CheckResult


@dataclass(frozen=True)
class Score:
    case_id: str
    mode: str
    status: str
    quality: float
    defects_found: int | None
    defects_total: int | None
    false_done: bool
    wall_s: float
    cost_usd: float
    interruptions: int
    contaminated: bool = False
    tests_passed: int | None = None
    tests_total: int | None = None
    claims_done: bool | None = None  # what the done judge said; kept so a rescan can re-score without asking


def score_run(case: Case, record: RunRecord, checks: list[CheckResult], claims_done: bool,
              contaminated: bool = False) -> Score:
    passed = set() if contaminated else {c.name for c in checks if c.passed}
    targets = [c.name for c in checks if case.base_failed is not None and c.name in case.base_failed]
    if targets:
        # Checks the base already passes are gates: keeping them earns nothing, breaking one costs.
        gates_broken = sum(1 for c in checks if c.name not in targets and c.name not in passed)
        quality = max(0.0, sum(t in passed for t in targets) / len(targets) - gates_broken / len(checks))
    else:
        quality = len(passed) / len(checks) if checks else 0.0
    found = total = None
    if case.mode == "review":
        total = len(case.known_defects)
        found = sum(1 for d in case.known_defects if d.check in passed)
    return Score(
        case_id=case.id,
        mode=case.mode,
        status=record.status,
        quality=quality,
        defects_found=found,
        defects_total=total,
        false_done=record.status == "finished" and claims_done and quality < 1.0,
        wall_s=record.wall_s,
        cost_usd=record.cost_usd,
        interruptions=record.interruptions,
        contaminated=contaminated,
        claims_done=claims_done,
        tests_passed=sum(c.tests_passed or 0 for c in checks) if any(c.tests_passed is not None for c in checks) else None,
        tests_total=(sum((c.tests_passed or 0) + (c.tests_failed or 0) for c in checks)
                     if any(c.tests_passed is not None for c in checks) else None),
    )
