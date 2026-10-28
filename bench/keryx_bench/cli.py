"""keryx-bench: validate cases, run a system on them, compare two runs, re-run a case."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

from keryx_bench.case import CaseError, case_hash, load_case
from keryx_bench.compare import NOT_SCORED, compare_runs, load_runset
from keryx_bench.rescan import RescanError, rescan_run
from keryx_bench.runner import one_runner, run_many
from keryx_bench.systems import load_system
from keryx_bench.validate import validate_case
from keryx_bench.versions import system_fingerprint

KERYX_HOME = Path.home() / ".config" / "keryx"
DATA_HOME = Path.home() / ".local" / "share" / "keryx"
# Outside the home folder, so a workspace's parent folders never hold the owner's own instructions.
RUNS_HOME = Path(os.environ.get("KERYX_RUNS_HOME", "/Users/Shared/keryx/bench-runs"))


def _run_id(system_name: str) -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{system_name}"


def _system_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.suffix in (".yaml", ".yml") else KERYX_HOME / "systems" / f"{value}.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keryx-bench")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="check that each case fails on base and passes on good")
    validate.add_argument("cases", nargs="+")
    validate.add_argument("--runs", default=str(DATA_HOME / "bench-runs"))
    validate.add_argument("--good-runs", type=int, default=3, help="runs of the good result, to catch flaky checks")

    run = sub.add_parser("run", help="run a system on a set of cases")
    run.add_argument("--system")
    run.add_argument("--cases")
    run.add_argument("--resume", metavar="RUN_DIR", help="re-run the infra and harness cases of this run in place")
    run.add_argument("--force", action="store_true", help="resume although the system file or its skills changed")
    run.add_argument("--weekly-cap", type=float, default=0.5,
                     help="start no new case once the subscription's seven-day window is this full")
    run.add_argument("--only", nargs="*", default=[])
    run.add_argument("--parallel", type=int, choices=[1, 2, 3], default=1)
    run.add_argument("--results", default=str(DATA_HOME / "bench-results"))
    run.add_argument("--runs", default=str(RUNS_HOME))
    run.add_argument("--keep-workspaces", action="store_true")

    compare = sub.add_parser("compare", help="compare the current setup (A) with a candidate (B)")
    compare.add_argument("run_a")
    compare.add_argument("run_b")
    compare.add_argument("--cost-cap", type=float, default=None)
    compare.add_argument("--common", action="store_true", help="compare on the cases both runs share (provisional)")
    compare.add_argument("--allow-bench-mismatch", action="store_true",
                         help="compare runs from different bench versions (provisional)")

    rerun = sub.add_parser("rerun", help="run one case of an earlier run again")
    rerun.add_argument("run_dir")
    rerun.add_argument("--case", required=True)
    rerun.add_argument("--times", type=int, default=3)
    rerun.add_argument("--runs", default=str(RUNS_HOME))
    rerun.add_argument("--force", action="store_true", help="re-run although the system file or its skills changed")

    rescan = sub.add_parser("rescan", help="re-check finished runs for leaks with this bench version and re-score them")
    rescan.add_argument("run_dirs", nargs="+")
    return parser


def _cmd_validate(args) -> int:
    bad = 0
    for case_dir in args.cases:
        try:
            case = load_case(Path(case_dir))
        except CaseError as err:
            print(f"INVALID {case_dir}: {err}")
            bad += 1
            continue
        v = validate_case(case, Path(args.runs), good_runs=args.good_runs)
        if v.ok:
            (case.path / "validation.json").write_text(json.dumps({
                "case_hash": case_hash(case), "base_failed": list(v.base_failed), "good_runs": args.good_runs,
                "validated_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n")
            print(f"ok {case.id}: fails on base ({', '.join(v.base_failed)}), passes on good")
        else:
            print(f"INVALID {case.id}: {'; '.join(v.reasons)}")
            bad += 1
    return 1 if bad else 0


def _load_cases(root: Path, only: list[str]):
    cases = [load_case(d) for d in sorted(root.iterdir()) if (d / "case.yaml").exists()]
    if only:
        cases = [c for c in cases if c.id in only]
        missing = set(only) - {c.id for c in cases}
        if missing:
            raise SystemExit(f"no such case: {', '.join(sorted(missing))}")
    return cases


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)  # the shared folder is world-readable; workspaces hold private code
    return path


def _resume_cases(run_dir: Path, force: bool):
    """The system and the cases of an earlier run that still need a scored result, or a reason they can't."""
    meta = json.loads((run_dir / "run.json").read_text())
    path = Path(meta["system_path"])
    system = load_system(path)
    if meta.get("system_fingerprint") != system_fingerprint(system, path) and not force:
        raise SystemExit("the system file or its skills changed since this run; pass --force to resume anyway")
    cases = []
    for case_id, case_dir in meta["case_dirs"].items():
        score = run_dir / case_id / "score.json"
        if score.exists() and json.loads(score.read_text())["status"] not in NOT_SCORED:
            continue
        case = load_case(Path(case_dir))
        if case_hash(case) != meta["case_hashes"][case_id]:
            raise SystemExit(f"case {case_id} changed since this run; a resumed result would not be comparable")
        cases.append(case)
    return system, path, cases


def _cmd_run(args) -> int:
    _private_dir(Path(args.runs))
    if args.resume:
        run_dir = Path(args.resume)
        system, path, cases = _resume_cases(run_dir, args.force)
        if args.only:
            cases = [c for c in cases if c.id in args.only]
        results_root, run_id = run_dir.parent, run_dir.name
        if not cases:
            print(f"nothing to resume in {run_dir}")
            return 0
    else:
        if not (args.system and args.cases):
            raise SystemExit("run needs --system and --cases, or --resume RUN_DIR")
        path = _system_path(args.system)
        system = load_system(path)
        cases = _load_cases(Path(args.cases).expanduser(), args.only)
        results_root, run_id = Path(args.results), _run_id(system.name)
    with one_runner():
        results = asyncio.run(run_many(cases, system, Path(args.runs), results_root, run_id, args.parallel,
                                       system_path=str(path), keep_workspaces=args.keep_workspaces,
                                       weekly_cap=args.weekly_cap))
    print((results_root / run_id / "summary.md").read_text())
    print(f"results: {results_root / run_id}")
    return 0 if all(r.status != "error" for r, _ in results) else 1


def _cmd_compare(args) -> int:
    verdict = compare_runs(load_runset(Path(args.run_a)), load_runset(Path(args.run_b)), args.cost_cap,
                           common_only=args.common, allow_bench_mismatch=args.allow_bench_mismatch)
    print(f"winner: {verdict.winner}")
    for reason in verdict.reasons:
        print(f"- {reason}")
    if verdict.rerun:
        print(f"re-run before deciding: {', '.join(verdict.rerun)}")
    return 0


def _cmd_rerun(args) -> int:
    _private_dir(Path(args.runs))
    run_dir = Path(args.run_dir)
    meta = json.loads((run_dir / "run.json").read_text())
    system = load_system(Path(meta["system_path"]))
    if meta.get("system_fingerprint") != system_fingerprint(system, Path(meta["system_path"])) and not args.force:
        print("the system file or its skills changed since this run; pass --force to re-run anyway")
        return 1
    case = load_case(Path(meta["case_dirs"][args.case]))
    if case_hash(case) != meta["case_hashes"][args.case]:
        print(f"case {args.case} changed since this run; a re-run would not be comparable")
        return 1
    for k in range(1, args.times + 1):
        run_id = f"{run_dir.name}-rerun-{args.case}-{k}"
        with one_runner():
            [(record, score)] = asyncio.run(run_many([case], system, Path(args.runs), run_dir.parent, run_id, 1,
                                                     system_path=meta["system_path"]))
        print(f"{run_id}: status {record.status}, quality {score.quality:.2f}, false done {score.false_done}")
    return 0


def _cmd_rescan(args) -> int:
    for run_dir in args.run_dirs:
        try:
            changes = rescan_run(Path(run_dir))
        except RescanError as err:
            print(f"not rescanned {run_dir}: {err}")
            return 1
        for case_id, (before, after) in changes.items():
            if before != after:
                print(f"{Path(run_dir).name} {case_id}: leaks {before or 'none'} -> {after or 'none'}")
        print(f"rescanned {run_dir} ({len(changes)} cases)")
    return 0


def _interrupt_on_term(signum, frame):
    # SIGTERM as KeyboardInterrupt, so asyncio cancels the runs and their sessions exit with them.
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _interrupt_on_term)
    args = build_parser().parse_args(argv)
    return {"validate": _cmd_validate, "run": _cmd_run, "compare": _cmd_compare, "rerun": _cmd_rerun,
            "rescan": _cmd_rescan}[args.command](args)
