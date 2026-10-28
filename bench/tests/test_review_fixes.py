"""Fixes from the final whole-branch review."""
import asyncio
import inspect
import subprocess
import sys
import threading
import time

from helpers import write_case
from keryx_bench import runner
from keryx_bench.case import load_case
from keryx_bench.driver import RunRecord
from keryx_bench.owner import KeywordMatcher
from keryx_bench.systems import System

PLAIN = System(name="plain", model="haiku", plugins=(), assemble=None,
               entry={"bug": "{prompt}", "review": "{prompt}", "feature": "{prompt}"}, env={})


def _case(tmp_path, toy_repo, case_id, check="true"):
    repo, base, good = toy_repo
    d = write_case(tmp_path / case_id, repo, base, good, checks=[("c", check)])
    (d / "case.yaml").write_text((d / "case.yaml").read_text().replace("id: toy-add", f"id: {case_id}"))
    return load_case(d)


async def _no(*args, **kwargs):
    return False


def test_scoring_one_case_does_not_freeze_another(tmp_path, toy_repo, monkeypatch):
    durations = {"a": 1.0, "b": 3.0}

    async def fake_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        start = time.monotonic()
        await asyncio.sleep(durations[case.id])
        return RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status="finished",
                         wall_s=time.monotonic() - start)

    monkeypatch.setattr(runner, "run_case", fake_run_case)
    monkeypatch.setattr(runner, "model_says_yes", _no)
    cases = [_case(tmp_path, toy_repo, "a", check="sleep 3"), _case(tmp_path, toy_repo, "b")]
    results = asyncio.run(runner.run_many(cases, PLAIN, tmp_path / "runs", tmp_path / "results", "r1", 2,
                                          matcher=KeywordMatcher()))
    walls = {record.case_id: record.wall_s for record, _ in results}
    assert walls["b"] < 3.6, walls


def test_a_shared_build_cache_is_used_by_one_scoring_tree_at_a_time(tmp_path):
    from keryx_bench.workspace import cache_lock

    cache = tmp_path / "target"
    held = threading.Event()

    def holder():
        with cache_lock(str(cache)):
            held.set()
            time.sleep(1.0)

    t = threading.Thread(target=holder)
    t.start()
    held.wait()
    start = time.monotonic()
    with cache_lock(str(cache)):
        waited = time.monotonic() - start
    t.join()
    assert waited >= 0.8


def test_stopping_strays_matches_the_run_directory_not_a_prefix(tmp_path):
    from keryx_bench.workspace import stop_strays

    root = tmp_path / "runs" / "r1" / "case"
    sibling = tmp_path / "runs" / "r1" / "case-2"
    root.mkdir(parents=True)
    sibling.mkdir(parents=True)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", str(sibling / "marker")])
    try:
        assert stop_strays(root) == []
        assert other.poll() is None
    finally:
        other.kill()


def test_processes_are_stopped_even_when_the_run_fails(tmp_path, toy_repo, monkeypatch):
    started = {}

    async def failing_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        started["p"] = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", str(ws.root / "x")])
        raise RuntimeError("session broke")

    monkeypatch.setattr(runner, "run_case", failing_run_case)
    case = _case(tmp_path, toy_repo, "a")
    try:
        asyncio.run(runner.run_one(case, PLAIN, tmp_path / "runs", tmp_path / "results", "r1",
                                   matcher=KeywordMatcher()))
    except RuntimeError:
        pass
    time.sleep(0.5)
    assert started["p"].poll() is not None


def test_reruns_and_runs_delete_their_workspaces_by_default():
    assert inspect.signature(runner.run_many).parameters["keep_workspaces"].default is False
    assert inspect.signature(runner.run_one).parameters["keep_workspace"].default is False


def _assistant(command):
    import json
    return json.dumps({"type": "AssistantMessage", "content": [{"name": "Bash", "input": {"command": command}}]}) + "\n"


def test_home_shorthands_in_commands_are_expanded_before_matching(tmp_path):
    from pathlib import Path

    from keryx_bench.leaks import find_leaks

    projects = str(Path.home() / ".claude" / "projects")
    t = tmp_path / "t.jsonl"
    for command in ("ls ~/.claude/projects/", "cat $HOME/.claude/projects/x/y.jsonl", "cat ${HOME}/.claude/projects/z"):
        t.write_text(_assistant(command))
        assert find_leaks(t, [projects]) == [projects], command


def test_relative_paths_are_resolved_against_the_workspace(tmp_path):
    from keryx_bench.leaks import find_leaks

    t = tmp_path / "t.jsonl"
    t.write_text(_assistant("cat ../../../src/repo/calc.py"))
    assert find_leaks(t, ["/a/src/repo"], base_dir="/a/b/c/repo") == ["/a/src/repo"]


def test_another_runs_results_are_a_leak_and_this_runs_files_are_not(tmp_path):
    from keryx_bench.leaks import find_leaks

    t = tmp_path / "t.jsonl"
    t.write_text(_assistant("cat /data/bench-results/R0/case/transcript.jsonl"))
    assert find_leaks(t, ["/data"], allow="R1") == ["/data"]
    t.write_text(_assistant("cat /data/bench-runs/R1/case/repo/calc.py"))
    assert find_leaks(t, ["/data"], allow="R1") == []


def test_the_executors_own_tool_calls_are_scanned(tmp_path):
    import json

    from keryx_bench.leaks import find_executor_leaks

    rounds = tmp_path / ".git" / "cursor-loop" / "slug" / "rounds" / "01"
    rounds.mkdir(parents=True)
    event = {"type": "tool_call", "subtype": "started",
             "tool_call": {"readToolCall": {"args": {"path": "/src/repo/calc.py"}}}}
    (rounds / "events.ndjson").write_text(json.dumps(event) + "\n")
    assert find_executor_leaks(tmp_path, ["/src/repo"], allow="R1") == ["/src/repo"]


def test_the_sealed_workspace_does_not_name_its_source(toy_case, tmp_path):
    from keryx_bench.workspace import prepare_workspace

    ws = prepare_workspace(load_case(toy_case), tmp_path / "runs", "r1")
    assert not (ws.repo / ".git" / "FETCH_HEAD").exists()


def test_the_runs_own_session_files_stay_readable_while_scanned(toy_case, tmp_path, monkeypatch):
    import os
    from pathlib import Path

    from keryx_bench.leaks import deny_paths, scan_paths

    # Its own HOME with the folder in place: a fresh CI runner has no ~/.claude/projects.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (Path.home() / ".claude" / "projects").mkdir(parents=True)
    case = load_case(toy_case)
    projects = os.path.realpath(Path.home() / ".claude" / "projects")
    assert projects not in deny_paths(case)
    assert projects in scan_paths(case, extra=[str(tmp_path)])
    assert str(tmp_path) in scan_paths(case, extra=[str(tmp_path)])


def test_a_judge_failure_after_a_good_run_is_infra_and_keeps_the_checks(tmp_path, toy_repo, monkeypatch):
    from helpers import git

    async def fixing_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        (ws.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
        git(ws.repo, "commit", "-q", "-am", "fix")
        return RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status="finished")

    async def judge_down(*args, **kwargs):
        raise RuntimeError("usage limit reached for this week")

    monkeypatch.setattr(runner, "run_case", fixing_run_case)
    monkeypatch.setattr(runner, "model_says_yes", judge_down)
    repo, base, good = toy_repo
    case = load_case(write_case(tmp_path / "c", repo, base, good))
    record, score = asyncio.run(runner.run_one(case, PLAIN, tmp_path / "runs", tmp_path / "results", "r1",
                                               matcher=KeywordMatcher()))
    assert record.status == "infra"
    assert score.quality == 1.0
    assert (tmp_path / "results" / "r1" / "toy-add" / "checks.json").exists()


def test_a_failed_prepare_is_the_harnesss_failure(tmp_path, toy_repo):
    repo, base, good = toy_repo
    case = load_case(write_case(tmp_path / "c", repo, base, good, extra="prepare: \"exit 3\"\n"))
    record, _ = asyncio.run(runner.run_one(case, PLAIN, tmp_path / "runs", tmp_path / "results", "r1",
                                           matcher=KeywordMatcher()))
    assert record.status == "harness"


def test_harness_failures_are_left_out_like_infra():
    from keryx_bench.compare import RunSet, compare_runs
    from keryx_bench.score import Score

    def sc(case_id, wall, status="finished"):
        return Score(case_id=case_id, mode="bug", status=status, quality=0.0 if status != "finished" else 1.0,
                     defects_found=None, defects_total=None, false_done=False, wall_s=wall, cost_usd=1.0,
                     interruptions=0)

    a = RunSet("a", {"x": "hx", "y": "hy"}, {"x": sc("x", 100), "y": sc("y", 100)})
    b = RunSet("b", {"x": "hx", "y": "hy"}, {"x": sc("x", 50), "y": sc("y", 5, status="harness")})
    v = compare_runs(a, b, None)
    assert v.winner == "B"
    assert v.rerun == ("y",)


def test_a_case_edited_during_the_run_is_flagged_and_scored_from_its_snapshot(tmp_path, toy_repo, monkeypatch):
    import json

    repo, base, good = toy_repo
    d = write_case(tmp_path / "a", repo, base, good, checks=[("marker", "test -f marker.txt")])
    (d / "hidden" / "marker.txt").write_text("x\n")
    (d / "case.yaml").write_text((d / "case.yaml").read_text().replace("id: toy-add", "id: a"))
    case = load_case(d)

    async def editing_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        (d / "hidden" / "marker.txt").unlink()
        return RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status="finished")

    monkeypatch.setattr(runner, "run_case", editing_run_case)
    monkeypatch.setattr(runner, "model_says_yes", _no)
    [(_, score)] = asyncio.run(runner.run_many([case], PLAIN, tmp_path / "runs", tmp_path / "results", "r1", 1,
                                               matcher=KeywordMatcher()))
    meta = json.loads((tmp_path / "results" / "r1" / "run.json").read_text())
    assert score.quality == 1.0
    assert meta["case_changed"] == ["a"]
    assert meta["harness"]


def test_runs_from_different_harness_versions_or_with_edited_cases_cannot_be_compared():
    from keryx_bench.compare import RunSet, compare_runs
    from keryx_bench.score import Score

    s = Score(case_id="x", mode="bug", status="finished", quality=1.0, defects_found=None, defects_total=None,
              false_done=False, wall_s=10.0, cost_usd=1.0, interruptions=0)
    a = RunSet("a", {"x": "h"}, {"x": s}, harness="abc")
    assert compare_runs(a, RunSet("b", {"x": "h"}, {"x": s}, harness="def"), None).winner == "invalid"
    assert compare_runs(a, RunSet("b", {"x": "h"}, {"x": s}, harness="abc", changed=("x",)), None).winner == "invalid"


def test_the_hidden_snapshot_is_where_the_run_cannot_read_it(tmp_path, toy_repo, monkeypatch):
    from pathlib import Path

    seen = {}

    async def looking_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        seen["hidden"] = str(case.hidden_dir)
        return RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status="finished")

    monkeypatch.setattr(runner, "run_case", looking_run_case)
    monkeypatch.setattr(runner, "model_says_yes", _no)
    case = _case(tmp_path, toy_repo, "a")
    # A run id that a random temporary folder name cannot contain by chance ("r1" once matched "snap-nlr1dd74").
    run_id = "20991231T000000Z-plain"
    asyncio.run(runner.run_many([case], PLAIN, tmp_path / "runs", tmp_path / "results", run_id, 1,
                                matcher=KeywordMatcher()))
    assert run_id not in seen["hidden"]
    assert seen["hidden"].startswith(str(Path.home() / ".config" / "keryx"))
    assert not Path(seen["hidden"]).exists()


def test_a_run_that_claims_done_is_not_held_open_by_a_leftover_background_task():
    from keryx_bench.driver import next_step

    assert next_step(active_tasks=1, reply=None, resumes=0, max_resumes=3, claims_done=True) == "finish"
    assert next_step(active_tasks=1, reply=None, resumes=0, max_resumes=3, claims_done=False) == "wait"


def test_only_meaningful_messages_end_a_wait():
    from claude_agent_sdk.types import RateLimitEvent, TaskNotificationMessage

    from keryx_bench.driver import resets_wait

    assert resets_wait(TaskNotificationMessage(subtype="task_notification", data={}, task_id="t", status="completed",
                                               output_file="", summary="", uuid="u", session_id="s"))
    assert not resets_wait(RateLimitEvent.__new__(RateLimitEvent))


def test_secret_looking_variables_are_removed_but_model_auth_is_kept():
    from keryx_bench.safety import removed_keys, safe_env

    base = {"PATH": "/usr/bin", "SOPS_AGE_KEY_FILE": "/k", "GEMINI_API_KEY": "g", "SOME_SERVICE_TOKEN": "t",
            "CLAUDE_CODE_MESSAGING_TOKEN": "m", "ANTHROPIC_API_KEY": "a", "DB_PASSWORD": "p"}
    env = safe_env(base, {})
    kept = [k for k in ("SOPS_AGE_KEY_FILE", "GEMINI_API_KEY", "SOME_SERVICE_TOKEN", "CLAUDE_CODE_MESSAGING_TOKEN",
                        "DB_PASSWORD") if k in env]
    assert kept == []
    assert env["ANTHROPIC_API_KEY"] == "a"
    assert "IdentityFile=/dev/null" in env["GIT_SSH_COMMAND"]
    assert set(removed_keys(base)) == {"SOPS_AGE_KEY_FILE", "GEMINI_API_KEY", "SOME_SERVICE_TOKEN",
                                       "CLAUDE_CODE_MESSAGING_TOKEN", "DB_PASSWORD"}


def test_the_systems_code_runs_in_the_checks_without_the_owners_credentials(toy_case, monkeypatch):
    from keryx_bench.workspace import check_env

    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("KUBECONFIG", "/real/kubeconfig")
    env = check_env(load_case(toy_case))
    has_token = "GH_TOKEN" in env  # booleans only: a failing assert must never print the environment
    kube_blanked = env.get("KUBECONFIG") == "/dev/null"
    assert not has_token
    assert kube_blanked


def test_edits_outside_the_runs_directory_are_refused(tmp_path):
    from pathlib import Path

    from keryx_bench.driver import edit_allowed

    root = Path.home() / ".local" / "share" / "keryx-edit-test" / "runs" / "r1" / "case"  # outside the temp dirs
    assert edit_allowed("Write", {"file_path": str(root / "repo" / "calc.py")}, root)
    assert edit_allowed("Edit", {"file_path": "/tmp/scratch.txt"}, root)
    assert not edit_allowed("Write", {"file_path": str(Path.home() / ".zshrc")}, root)
    assert not edit_allowed("Edit", {"file_path": str(root) + "-other/x.py"}, root)
    assert edit_allowed("Read", {"file_path": str(Path.home() / ".zshrc")}, root)


def _validated_case(tmp_path, toy_repo, base_failed):
    import json

    from keryx_bench.case import case_hash

    repo, base, good = toy_repo
    d = write_case(tmp_path / "v", repo, base, good, checks=[("t", "true"), ("g", "true")])
    (d / "validation.json").write_text(json.dumps({"case_hash": case_hash(load_case(d)), "base_failed": base_failed}))
    return load_case(d)


def test_an_untouched_branch_scores_nothing_even_when_its_gates_pass(tmp_path, toy_repo):
    from keryx_bench.score import score_run
    from keryx_bench.workspace import CheckResult

    case = _validated_case(tmp_path, toy_repo, ["t"])
    record = RunRecord(case_id=case.id, system="s", run_id="r", status="finished")

    def checks(t, g):
        return [CheckResult("t", t, 0 if t else 1, 1.0, ""), CheckResult("g", g, 0 if g else 1, 1.0, "")]

    assert case.base_failed == ("t",)
    assert score_run(case, record, checks(False, True), claims_done=False).quality == 0.0
    assert score_run(case, record, checks(True, False), claims_done=False).quality == 0.5
    assert score_run(case, record, checks(True, True), claims_done=False).quality == 1.0


def test_a_stale_validation_record_is_ignored(tmp_path, toy_repo):
    case = _validated_case(tmp_path, toy_repo, ["t"])
    (case.path / "prompt.md").write_text("changed\n")
    assert load_case(case.path).base_failed is None


def test_validating_an_ok_case_records_its_base_result(tmp_path, toy_repo):
    import json

    from keryx_bench.cli import main

    repo, base, good = toy_repo
    d = write_case(tmp_path / "ok", repo, base, good)
    assert main(["validate", str(d), "--runs", str(tmp_path / "runs"), "--good-runs", "1"]) == 0
    assert json.loads((d / "validation.json").read_text())["base_failed"] == ["hidden-add"]


def test_project_settings_are_refused_for_workspaces_under_the_home_folder(tmp_path, toy_repo):
    import dataclasses
    from pathlib import Path

    import pytest

    project = dataclasses.replace(PLAIN, setting_sources=("project",))
    case = _case(tmp_path, toy_repo, "a")
    with pytest.raises(ValueError, match="home"):
        asyncio.run(runner.run_many([case], project, Path.home() / ".cache" / "keryx-test-runs", tmp_path / "results",
                                    "r1", 1, matcher=KeywordMatcher()))


def test_the_default_runs_folder_is_outside_the_home_folder():
    from pathlib import Path

    from keryx_bench.cli import RUNS_HOME

    assert not RUNS_HOME.resolve().is_relative_to(Path.home().resolve())


def test_two_systems_started_in_the_same_second_get_different_run_ids():
    from keryx_bench.cli import _run_id

    assert _run_id("baseline") != _run_id("candidate")
    assert _run_id("baseline").endswith("-baseline")


def test_relative_paths_follow_the_commands_own_cd(tmp_path):
    from keryx_bench.leaks import find_leaks

    t = tmp_path / "t.jsonl"
    # Seen in the paired run: cd into the loop's state folder, then a path relative to it.
    t.write_text(_assistant("cd /R/run1/case/repo/.git/cursor-loop/slug && python3 qa/qa.py ../../../backend/src"))
    assert find_leaks(t, ["/R"], allow="run1", base_dir="/R/run1/case/repo") == []
    t.write_text(_assistant("python3 qa/qa.py ../../../backend/src"))
    assert find_leaks(t, ["/R"], allow="run1", base_dir="/R/run1/case/repo") == ["/R"]


def test_the_executors_logs_outlive_the_workspace_but_its_config_does_not(tmp_path, toy_repo, monkeypatch):
    async def logging_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        rounds = ws.repo / ".git" / "cursor-loop" / "slug" / "rounds" / "01"
        rounds.mkdir(parents=True)
        (rounds / "events.ndjson").write_text("{}\n")
        (ws.repo / ".git" / "cursor-loop" / "slug" / "cursor-config").mkdir()
        (ws.repo / ".git" / "cursor-loop" / "slug" / "cursor-config" / "cli-config.json").write_text("{}")
        return RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status="finished")

    monkeypatch.setattr(runner, "run_case", logging_run_case)
    monkeypatch.setattr(runner, "model_says_yes", _no)
    case = _case(tmp_path, toy_repo, "a")
    asyncio.run(runner.run_one(case, PLAIN, tmp_path / "runs", tmp_path / "results", "r1", matcher=KeywordMatcher()))
    kept = tmp_path / "results" / "r1" / "a" / "executor" / "cursor-loop" / "slug"
    assert (kept / "rounds" / "01" / "events.ndjson").exists()
    assert not (kept / "cursor-config").exists()
    assert not (tmp_path / "runs" / "r1" / "a").exists()
