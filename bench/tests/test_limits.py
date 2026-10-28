import asyncio
import json

from claude_agent_sdk.types import RateLimitInfo

from helpers import write_case
from keryx_bench import runner
from keryx_bench.case import load_case
from keryx_bench.cli import main
from keryx_bench.driver import RunRecord, UsageWindow, limit_pause
from keryx_bench.owner import KeywordMatcher
from keryx_bench.score import Score
from keryx_bench.systems import System

NOW = 1_800_000_000.0


def _info(status, resets_in=600, weekly=0.3, kind="five_hour"):
    return RateLimitInfo(status=status, resets_at=int(NOW + resets_in) if resets_in is not None else None,
                         rate_limit_type=kind,
                         raw={"unifiedWindows": {"seven_day": {"utilization": weekly}}})


def test_a_rejected_window_pauses_until_it_resets():
    assert limit_pause(_info("rejected", 600), NOW) == 660  # a minute past the reset


def test_no_pause_without_a_rejection_a_reset_time_or_within_reach():
    assert limit_pause(_info("allowed_warning"), NOW) is None
    assert limit_pause(_info("rejected", None), NOW) is None
    assert limit_pause(_info("rejected", 7 * 3600), NOW) is None  # more than a five-hour window away
    assert limit_pause(None, NOW) is None


def test_the_weekly_window_stops_new_work_at_its_cap():
    usage = UsageWindow(weekly_cap=0.5)
    usage.note(_info("allowed", weekly=0.49))
    assert not usage.over_cap
    usage.note(_info("allowed", weekly=0.5))
    assert usage.over_cap and usage.weekly == 0.5
    usage.note(_info("allowed", weekly=None))  # an event without the window keeps what was seen
    assert usage.weekly == 0.5


PLAIN = System(name="plain", model="haiku", plugins=(), assemble=None, env={}, entry={"bug": "{prompt}", "feature": "{prompt}",
                                                                     "review": "{prompt}"})


def _case(tmp_path, toy_repo, case_id):
    repo, base, good = toy_repo
    d = write_case(tmp_path / case_id, repo, base, good, checks=[("c", "true")])
    (d / "case.yaml").write_text((d / "case.yaml").read_text().replace("id: toy-add", f"id: {case_id}"))
    return load_case(d)


async def _yes(*args, **kwargs):
    return True


def test_no_case_starts_once_the_weekly_cap_is_reached(tmp_path, toy_repo, monkeypatch):
    started = []

    async def fake_run_case(case, system, ws, plugin_dirs, standin, transcript, *, usage=None, **kw):
        started.append(case.id)
        usage.note(_info("allowed", weekly=0.8))
        return RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status="finished")

    monkeypatch.setattr(runner, "run_case", fake_run_case)
    monkeypatch.setattr(runner, "model_says_yes", _yes)
    cases = [_case(tmp_path, toy_repo, i) for i in ("a", "b")]
    results = asyncio.run(runner.run_many(cases, PLAIN, tmp_path / "runs", tmp_path / "results", "r1", 1,
                                          matcher=KeywordMatcher(), weekly_cap=0.5))
    assert started == ["a"]
    assert [r.status for r, _ in results] == ["finished", "infra"]
    assert "weekly" in results[1][0].error


def test_resume_reruns_only_the_unscored_cases_into_the_same_run(tmp_path, toy_repo, monkeypatch):
    status = {"a": "finished", "b": "infra"}

    async def fake_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        return RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status=status[case.id])

    monkeypatch.setattr(runner, "run_case", fake_run_case)
    monkeypatch.setattr(runner, "model_says_yes", _yes)
    system_file = tmp_path / "plain.yaml"
    system_file.write_text("name: plain\nmodel: opus\nentry: {bug: '{prompt}', feature: '{prompt}', review: '{prompt}'}\n")
    cases_dir = tmp_path / "cases"
    for i in ("a", "b"):
        _case(cases_dir, toy_repo, i)
    runs, results = tmp_path / "runs", tmp_path / "results"
    assert main(["run", "--system", str(system_file), "--cases", str(cases_dir), "--runs", str(runs),
                 "--results", str(results)]) == 0
    [run_dir] = results.iterdir()
    first = json.loads((run_dir / "a" / "score.json").read_text())
    status["b"] = "finished"
    started = []
    original = fake_run_case

    async def counting(case, *a, **kw):
        started.append(case.id)
        return await original(case, *a, **kw)

    monkeypatch.setattr(runner, "run_case", counting)
    assert main(["run", "--resume", str(run_dir), "--runs", str(runs)]) == 0
    assert started == ["b"]
    assert json.loads((run_dir / "a" / "score.json").read_text()) == first
    assert Score(**json.loads((run_dir / "b" / "score.json").read_text())).status == "finished"
    meta = json.loads((run_dir / "run.json").read_text())
    assert set(meta["case_hashes"]) == {"a", "b"} and meta["resumed"][0]["cases"] == ["b"]
    assert "| b |" in (run_dir / "summary.md").read_text() and "| a |" in (run_dir / "summary.md").read_text()
