"""Re-check a finished run for leaks with the current detector, and re-score it from its saved checks.

Nothing is run again: the transcript, the executor's kept logs and the hidden checks' results are re-read. The
old values stay in each case's rescan.json, and run.json lists every rescan, so two runs compare only when both
were rescanned by the same bench version.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

from keryx_bench.case import case_hash, load_case
from keryx_bench.driver import CLAIMS_DONE, RunRecord
from keryx_bench.leaks import find_executor_leaks, find_leaks, find_subagent_leaks, scan_paths
from keryx_bench.owner import model_says_yes
from keryx_bench.report import write_summary
from keryx_bench.runner import _write_json
from keryx_bench.score import Score, score_run
from keryx_bench.versions import harness_version
from keryx_bench.workspace import CheckResult


class RescanError(Exception):
    pass


def _claims_done(old: dict, record: RunRecord) -> bool | None:
    """What the done judge said, as far as the old score can tell; None when it cannot."""
    if old.get("claims_done") is not None:
        return old["claims_done"]
    if old["false_done"]:
        return True
    if record.status == "finished" and old["quality"] < 1.0:
        return False
    return None


def _summary(score: dict, leaks: list) -> dict:
    return {"leaks": leaks, "quality": score["quality"], "false_done": score["false_done"],
            "contaminated": score["contaminated"]}


def rescan_run(run_dir: Path) -> dict[str, tuple[list, list]]:
    """Rescan every case of a run in place. Returns {case id: (old leaks, new leaks)} for the cases rescanned."""
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run.json").read_text())
    version, at = harness_version(), datetime.now(timezone.utc).isoformat()
    cases = {}
    for case_id, case_dir in meta["case_dirs"].items():
        case = load_case(Path(case_dir))
        if case_hash(case) != meta["case_hashes"][case_id]:
            raise RescanError(f"{case_id} changed since the run; its score would not mean the same")
        cases[case_id] = case
    changes, scores = {}, []
    for case_id, case in cases.items():
        out = run_dir / case_id
        record = RunRecord(**json.loads((out / "record.json").read_text()))
        old = json.loads((out / "score.json").read_text())
        if not record.cwd or not (out / "transcript.jsonl").exists():  # never got as far as running
            scores.append(Score(**old))
            continue
        runs_root = Path(record.cwd).parents[2]  # <runs>/<run id>/<case id>/repo
        forbidden = scan_paths(case, extra=[str(runs_root.resolve()), str(run_dir.parent.resolve())])
        scan = {"allow": record.run_id, "runs_root": str(runs_root.resolve())}
        leaks = sorted(set(find_leaks(out / "transcript.jsonl", forbidden, base_dir=record.cwd, **scan))
                       | set(find_subagent_leaks(sorted((out / "subagents").glob("*.jsonl")), forbidden,
                                               base_dir=record.cwd, **scan))
                       | set(find_executor_leaks(Path(record.cwd), forbidden, logs=out / "executor", **scan)))
        old_leaks = list(record.leaks)
        record = dataclasses.replace(record, leaks=leaks)
        checks = [CheckResult(**c) for c in json.loads((out / "checks.json").read_text())] \
            if (out / "checks.json").exists() else []
        claims = _claims_done(old, record)
        score = score_run(case, record, checks, bool(claims), contaminated=bool(leaks))
        if claims is None and record.status == "finished" and score.quality < 1.0:
            claims = bool(asyncio.run(model_says_yes(CLAIMS_DONE, record.final_text)))
            score = score_run(case, record, checks, claims, contaminated=bool(leaks))
        score = dataclasses.replace(score, claims_done=claims)  # None: never asked, and not needed
        _write_json(out / "rescan.json", {"harness": version, "at": at, "before": _summary(old, old_leaks),
                                          "after": _summary(dataclasses.asdict(score), leaks)})
        _write_json(out / "record.json", dataclasses.asdict(record))
        _write_json(out / "score.json", dataclasses.asdict(score))
        changes[case_id] = (old_leaks, leaks)
        scores.append(score)
    meta.setdefault("rescans", []).append({"harness": version, "at": at})
    _write_json(run_dir / "run.json", meta)
    write_summary(run_dir, meta["system"], scores)
    return changes
