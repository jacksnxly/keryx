"""Runs cases end to end: workspace, system under test, scoring on the committed result, result files."""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import fcntl
import json
import shutil
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from keryx_bench import scratch
from keryx_bench.case import Case, case_hash
from keryx_bench.driver import CLAIMS_DONE, INFRA_WORDS, RunRecord, UsageWindow, run_case
from keryx_bench.owner import Matcher, ModelMatcher, StandIn, model_says_yes
from keryx_bench.report import write_summary
from keryx_bench.score import Score, score_run
from keryx_bench.systems import System, materialize
from keryx_bench.versions import harness_version, system_fingerprint
from keryx_bench.workspace import (CheckResult, apply_hidden, prepare_workspace, result_checkout, run_checks,
                                  run_prepare, score_lock, stop_strays)

RUNNER_LOCK = Path.home() / ".local" / "share" / "keryx" / "runner.lock"


def _snapshot_root() -> Path:
    root = Path.home() / ".config" / "keryx" / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def _keep_executor_logs(ws, out: Path) -> None:
    """The executor's own logs and the coordinator's loop state outlive the workspace, for audit and re-scans.
    Its config folders (copies of the CLI config, possibly with credentials) are left out."""
    for name in ("cursor-loop",):
        source = ws.repo / ".git" / name
        if source.is_dir():
            dest = out / "executor" / name
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(source, dest, ignore=shutil.ignore_patterns("cursor-config", "*.lock"))


def _scratch_logs(ws, out: Path) -> list[Path]:
    return [out / "transcript.jsonl", *sorted((out / "subagents").glob("*.jsonl")),
            *sorted(ws.repo.glob(".git/cursor-loop/*/rounds/*/events.ndjson"))]


def _tidy_scratch(record: RunRecord, ws, out: Path, before: set[str]) -> None:
    record.tmp_removed, preexisting = scratch.tidy_tmp(scratch.TMP_ROOT, before,
                                                       scratch.tmp_names_used(_scratch_logs(ws, out)))
    if preexisting and record.status not in ("infra", "harness"):
        # Another run's scratch, or the owner's: what the run saw there is not its own work. Re-run, don't score.
        record.status = "harness"
        breach = "isolation: used /tmp entries that existed before the run: " + ", ".join(
            f"/tmp/{n}" for n in preexisting)
        record.error = (record.error + "; " if record.error else "") + breach


@contextlib.contextmanager
def one_runner():
    """One bench runner at a time on this machine: concurrent runs share /tmp and pick the same scratch names."""
    RUNNER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with RUNNER_LOCK.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f"another bench run holds {RUNNER_LOCK}; run the arms of a pair one after the other")
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _score_result(case: Case, system: System, ws) -> list[CheckResult]:
    tree = result_checkout(ws, "score")
    try:
        with score_lock(case):
            run_prepare(tree, case, system.env)
            apply_hidden(tree, case)
            return run_checks(tree, case, system.env)
    finally:
        shutil.rmtree(tree, ignore_errors=True)  # it holds the hidden files; never leave them beside a workspace


async def run_one(case: Case, system: System, runs_root: Path, results_root: Path, run_id: str, *,
                  matcher: Matcher | None = None, keep_workspace: bool = False,
                  usage: UsageWindow | None = None) -> tuple[RunRecord, Score]:
    # Blocking steps (git, installs, builds, checks) run in threads so parallel cases keep their own clocks.
    out = Path(results_root) / run_id / case.id
    ws = await asyncio.to_thread(prepare_workspace, case, Path(runs_root), run_id)
    tmp_before: set[str] | None = None
    tidied = False
    try:
        try:
            await asyncio.to_thread(run_prepare, ws.repo, case, system.env)
        except RuntimeError as err:  # the case's own setup failed: not the system's doing
            record = RunRecord(case_id=case.id, system=system.name, run_id=run_id, status="harness",
                               cwd=str(ws.repo), error=str(err))
        else:
            plugin_dirs = await asyncio.to_thread(materialize, system, ws.root / "plugins")
            standin = StandIn(case.owner, matcher or ModelMatcher())
            tmp_before = await asyncio.to_thread(scratch.tmp_entries, scratch.TMP_ROOT)
            record = await run_case(case, system, ws, plugin_dirs, standin, out / "transcript.jsonl",
                                    scan_extra=[str(Path(runs_root).resolve()), str(Path(results_root).resolve())],
                                    usage=usage)
            record.stray_processes = len(await asyncio.to_thread(stop_strays, ws.root))
            # Before scoring: a server the run left in /tmp could hold a port the hidden checks need.
            await asyncio.to_thread(_tidy_scratch, record, ws, out, tmp_before)
            tidied = True
        try:
            checks = await asyncio.to_thread(_score_result, case, system, ws)
        except Exception as err:  # a broken result branch scores zero; the reason is kept in the record
            record.error = (record.error + "; " if record.error else "") + f"scoring failed: {err}"
            checks = []
        claims_done = False
        if record.status == "finished":
            try:
                claims_done = bool(await model_says_yes(CLAIMS_DONE, record.final_text))
            except Exception as err:  # the judge failed, not the system: keep the checks, mark the run
                infra = any(w in str(err).lower() for w in INFRA_WORDS)
                record.status = "infra" if infra else "harness"
                record.error = (record.error + "; " if record.error else "") + f"done judge failed: {err}"
        score = score_run(case, record, checks, claims_done, contaminated=bool(record.leaks))
        _write_json(out / "record.json", dataclasses.asdict(record))
        _write_json(out / "checks.json", [dataclasses.asdict(c) for c in checks])
        _write_json(out / "score.json", dataclasses.asdict(score))
        return record, score
    finally:
        await asyncio.to_thread(stop_strays, ws.root)  # also when the run failed or was cancelled
        if tmp_before is not None and not tidied:  # stopped mid-case: its scratch must not wait for the next run
            await asyncio.to_thread(scratch.tidy_tmp, scratch.TMP_ROOT, tmp_before,
                                    scratch.tmp_names_used(_scratch_logs(ws, out)))
        await asyncio.to_thread(_keep_executor_logs, ws, out)
        if not keep_workspace:
            shutil.rmtree(ws.root, ignore_errors=True)


def _failed(case: Case, system: System, run_id: str, err: BaseException) -> tuple[RunRecord, Score]:
    record = RunRecord(case_id=case.id, system=system.name, run_id=run_id, status="harness",
                       error="".join(traceback.format_exception_only(type(err), err)).strip())
    return record, score_run(case, record, [], claims_done=False)


async def run_many(cases: list[Case], system: System, runs_root: Path, results_root: Path, run_id: str,
                   parallel: int, *, system_path: str = "", keep_workspaces: bool = False,
                   matcher: Matcher | None = None, weekly_cap: float = 0.5) -> list[tuple[RunRecord, Score]]:
    """Run the cases and write run.json and summary.md. Into a run folder that already holds a run.json,
    the cases are re-run in place (a resume): the other cases' results stay, and run.json records the resume."""
    if "project" in system.setting_sources and Path(runs_root).resolve().is_relative_to(Path.home().resolve()):
        # Claude Code walks a workspace's parent folders for instructions; under the home folder that reaches
        # the owner's own ~/.claude/CLAUDE.md (seen in a probe), which would leak into every run.
        raise ValueError(f"workspaces under the home folder ({runs_root}) would load the owner's instructions; "
                         "use a runs folder outside it")
    run_dir = Path(results_root) / run_id
    started = datetime.now(timezone.utc).isoformat()
    gate = asyncio.Semaphore(parallel)
    usage = UsageWindow(weekly_cap=weekly_cap)
    originals = list(cases)
    hashes = {c.id: case_hash(c) for c in originals}
    # Score from a snapshot of each case's hidden files, so an edit during the run cannot change the scoring.
    # It lives in the private config folder, which runs may not read, under a name without the run id.
    snapshots = Path(tempfile.mkdtemp(prefix="snap-", dir=_snapshot_root()))
    cases = []
    for c in originals:
        snapshot = snapshots / c.id
        shutil.copytree(c.hidden_dir, snapshot)
        cases.append(dataclasses.replace(c, hidden_dir=snapshot))

    async def one(case: Case):
        async with gate:
            if usage.over_cap:  # not started: re-run it with `run --resume` once the window has room
                record = RunRecord(case_id=case.id, system=system.name, run_id=run_id, status="infra",
                                   error=f"not started: the weekly usage window is at {usage.weekly:.0%} "
                                         f"(cap {usage.weekly_cap:.0%})", weekly_use=usage.weekly)
                score = score_run(case, record, [], False)
                _write_json(run_dir / case.id / "record.json", dataclasses.asdict(record))
                _write_json(run_dir / case.id / "score.json", dataclasses.asdict(score))
                return record, score
            try:
                return await run_one(case, system, runs_root, results_root, run_id, matcher=matcher,
                                     keep_workspace=keep_workspaces, usage=usage)
            except Exception as err:  # one broken case must not stop the others; it is recorded as an error
                record, score = _failed(case, system, run_id, err)
                _write_json(run_dir / case.id / "record.json", dataclasses.asdict(record))
                _write_json(run_dir / case.id / "score.json", dataclasses.asdict(score))
                return record, score

    try:
        results = await asyncio.gather(*(one(c) for c in cases))
    finally:
        shutil.rmtree(snapshots, ignore_errors=True)
    changed = sorted(c.id for c in originals if case_hash(c) != hashes[c.id])
    ended = datetime.now(timezone.utc).isoformat()
    if (run_dir / "run.json").exists():
        meta = json.loads((run_dir / "run.json").read_text())
        meta["case_hashes"].update(hashes)
        meta["case_dirs"].update({c.id: str(c.path) for c in originals})
        meta["case_changed"] = sorted({*meta.get("case_changed", ()), *changed})
        meta.setdefault("resumed", []).append({"harness": harness_version(), "started": started, "ended": ended,
                                               "cases": [c.id for c in originals]})
        meta["ended"] = ended
    else:
        meta = {
            "system": system.name, "system_path": system_path, "started": started, "ended": ended,
            "case_hashes": hashes, "case_changed": changed, "case_dirs": {c.id: str(c.path) for c in originals},
            "harness": harness_version(),
            "system_fingerprint": system_fingerprint(system, Path(system_path) if system_path else None),
        }
    _write_json(run_dir / "run.json", meta)
    write_summary(run_dir, system.name, [Score(**json.loads(p.read_text())) for p in sorted(run_dir.glob("*/score.json"))])
    return list(results)
