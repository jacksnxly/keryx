"""Decides between the current setup (A) and a candidate (B): quality may not drop, then speed wins."""
from __future__ import annotations

import dataclasses

import json
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from keryx_bench.score import Score

SPEED_MARGIN = 0.05
NOT_SCORED = ("infra", "harness")  # provider limits or the bench's own failure: re-run, never compared


@dataclass(frozen=True)
class RunSet:
    system: str
    case_hashes: Mapping[str, str]
    scores: Mapping[str, Score]
    harness: str = ""
    changed: tuple[str, ...] = ()


@dataclass(frozen=True)
class Verdict:
    winner: str
    reasons: tuple[str, ...]
    rerun: tuple[str, ...]


def load_runset(run_dir: Path) -> RunSet:
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run.json").read_text())
    scores = {}
    for path in sorted(run_dir.glob("*/score.json")):
        score = Score(**json.loads(path.read_text()))
        scores[score.case_id] = score
    resumed = sorted({r["harness"] for r in meta.get("resumed", ())})  # how often an arm resumed does not matter
    harness = meta.get("harness", "") + "".join(f"+resume {v}" for v in resumed)
    if meta.get("rescans"):  # re-scored by a later bench version: compare only with a run rescanned by the same
        harness += f"+rescan {meta['rescans'][-1]['harness']}"
    return RunSet(system=meta["system"], case_hashes=meta["case_hashes"], scores=scores,
                  harness=harness, changed=tuple(meta.get("case_changed", ())))


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def compare_runs(a: RunSet, b: RunSet, cost_cap_usd: float | None, *, common_only: bool = False,
                 allow_bench_mismatch: bool = False) -> Verdict:
    """A (the current setup) against B (the candidate). `common_only` compares on the cases both ran with the
    same hash; `allow_bench_mismatch` compares runs from different bench versions. Both mark the verdict
    provisional: a candidate checked that way is re-run on the same terms before it replaces anything."""
    notes = []
    if common_only:
        common = sorted(i for i in set(a.scores) & set(b.scores) if a.case_hashes.get(i) == b.case_hashes.get(i))
        left_out = sorted((set(a.scores) | set(b.scores)) - set(common))
        if not common:
            return Verdict("invalid", ("the two runs share no case",), ())
        a = RunSet(a.system, {i: a.case_hashes[i] for i in common}, {i: a.scores[i] for i in common}, a.harness,
                   a.changed)
        b = RunSet(b.system, {i: b.case_hashes[i] for i in common}, {i: b.scores[i] for i in common}, b.harness,
                   b.changed)
        if left_out:
            notes.append(f"provisional — compared on {len(common)} common cases; left out: {', '.join(left_out)}")
    if dict(a.case_hashes) != dict(b.case_hashes) or set(a.scores) != set(b.scores):
        return Verdict("invalid", ("the two runs did not use the same cases",), ())
    if a.changed or b.changed:
        return Verdict("invalid", (f"cases changed during a run: {', '.join(sorted({*a.changed, *b.changed}))}",), ())
    if a.harness and b.harness and a.harness != b.harness:
        if not allow_bench_mismatch:
            return Verdict("invalid", (f"different bench versions: {a.harness} vs {b.harness}",), ())
        notes.append(f"provisional — different bench versions: {a.harness} vs {b.harness}")
        a, b = dataclasses.replace(a, harness=""), dataclasses.replace(b, harness="")
    if notes:
        verdict = compare_runs(a, b, cost_cap_usd)
        return Verdict(verdict.winner, (*verdict.reasons, *notes), verdict.rerun)

    infra = sorted(i for i in a.scores if {a.scores[i].status, b.scores[i].status} & set(NOT_SCORED))
    if infra:
        keep = set(a.scores) - set(infra)
        if not keep:
            return Verdict("invalid", ("every case hit an infrastructure or harness failure",), tuple(infra))
        a = RunSet(a.system, a.case_hashes, {i: a.scores[i] for i in keep}, a.harness)
        b = RunSet(b.system, b.case_hashes, {i: b.scores[i] for i in keep}, b.harness)
        verdict = compare_runs(a, b, cost_cap_usd)
        note = f"provisional — left out after an infrastructure or harness failure: {', '.join(infra)}"
        return Verdict(verdict.winner, (*verdict.reasons, note), (*infra, *verdict.rerun))

    reasons, rerun = [], []
    for mode in sorted({s.mode for s in a.scores.values()}):
        ids = sorted(i for i, s in a.scores.items() if s.mode == mode)
        qa, qb = _mean(a.scores[i].quality for i in ids), _mean(b.scores[i].quality for i in ids)
        if qb < qa:
            reasons.append(f"quality dropped for {mode}: {qa:.2f} -> {qb:.2f}")
            rerun += [i for i in ids if b.scores[i].quality < a.scores[i].quality]
    if reasons:
        return Verdict("A", tuple(reasons), tuple(rerun))

    false_a = sum(s.false_done for s in a.scores.values())
    false_b = sum(s.false_done for s in b.scores.values())
    if false_b > false_a:
        return Verdict("A", (f"more false dones: {false_a} -> {false_b}",), ())

    found_a = sum(s.defects_found or 0 for s in a.scores.values())
    found_b = sum(s.defects_found or 0 for s in b.scores.values())
    if found_b < found_a:
        return Verdict("A", (f"fewer known defects found: {found_a} -> {found_b}",), ())

    cost_b = sum(s.cost_usd for s in b.scores.values())
    if cost_cap_usd is not None and cost_b > cost_cap_usd:
        return Verdict("A", (f"over the cost cap: ${cost_b:.2f} > ${cost_cap_usd:.2f}",), ())

    wall_a = statistics.median(s.wall_s for s in a.scores.values())
    wall_b = statistics.median(s.wall_s for s in b.scores.values())
    speed = f"median time {wall_a:.0f}s -> {wall_b:.0f}s"
    if wall_b < wall_a * (1 - SPEED_MARGIN):
        return Verdict("B", (f"quality held and faster: {speed}",), ())
    if wall_b <= wall_a * (1 + SPEED_MARGIN):
        return Verdict("tie", (f"quality held, speed within {SPEED_MARGIN:.0%}: {speed}",), ())
    return Verdict("A", (f"quality held but slower: {speed}",), ())
