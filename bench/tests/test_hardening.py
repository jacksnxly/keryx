"""Fixes from the prior-art review: leaks, flaky checks, infrastructure failures, unanswered questions."""
import asyncio
import json

from helpers import PYTEST, write_case
from keryx_bench.case import load_case
from keryx_bench.compare import RunSet, compare_runs
from keryx_bench.driver import RunRecord, classify_result
from keryx_bench.leaks import find_leaks, path_deny_rules
from keryx_bench.owner import Answer, KeywordMatcher, OwnerScript, StandIn
from keryx_bench.score import Score, score_run
from keryx_bench.validate import validate_case
from keryx_bench.workspace import CheckResult


def test_a_run_that_reads_the_source_repo_is_flagged(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(
        json.dumps({"type": "SystemMessage", "data": {"note": "/src/repo"}}) + "\n"
        + json.dumps({"type": "AssistantMessage",
                      "content": [{"name": "Bash", "input": {"command": "git -C /src/repo log --all"}}]}) + "\n")
    assert find_leaks(t, ["/src/repo", "/home/x/.claude/projects"]) == ["/src/repo"]


def test_a_run_that_stays_in_its_workspace_has_no_leaks(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "AssistantMessage",
                             "content": [{"name": "Read", "input": {"file_path": "/runs/r1/repo/calc.py"}}]}) + "\n")
    assert find_leaks(t, ["/src/repo"]) == []


def test_reading_forbidden_paths_is_denied():
    assert path_deny_rules(["/src/repo"]) == ["Read(//src/repo/**)", "Edit(//src/repo/**)"]


def test_a_contaminated_run_scores_zero(toy_case):
    record = RunRecord(case_id="toy-add", system="s", run_id="r", status="finished")
    check = CheckResult(name="hidden-add", passed=True, exit_code=0, seconds=1.0, output_tail="")
    s = score_run(load_case(toy_case), record, [check], claims_done=True, contaminated=True)
    assert s.quality == 0.0
    assert s.contaminated is True


def test_a_flaky_check_on_good_is_rejected(tmp_path, toy_repo):
    repo, base, good = toy_repo
    counter = tmp_path / "count"
    flaky = (f"n=$(cat {counter} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {counter}; "
             f"if [ $((n % 2)) -eq 1 ]; then {PYTEST}; else exit 1; fi")
    case = load_case(write_case(tmp_path / "c", repo, base, good, checks=[("hidden-add", flaky)]))
    v = validate_case(case, tmp_path / "runs", good_runs=2)
    assert not v.ok
    assert "check hidden-add is flaky on good (1 of 2 runs failed)" in v.reasons


def test_rate_and_usage_limits_are_infrastructure_failures():
    assert classify_result("success", False, None, None) == "ok"
    assert classify_result("success", True, 429, None) == "infra"
    assert classify_result("error_during_execution", True, None, ["usage limit reached"]) == "infra"
    assert classify_result("error_max_budget_usd", True, None, None) == "budget"
    assert classify_result("error_during_execution", True, None, ["boom"]) == "error"


def test_infrastructure_failures_are_left_out_and_rerun():
    def sc(case_id, wall, status="finished", quality=1.0):
        return Score(case_id=case_id, mode="bug", status=status, quality=quality, defects_found=None,
                     defects_total=None, false_done=False, wall_s=wall, cost_usd=1.0, interruptions=0)

    a = RunSet("a", {"x": "hx", "y": "hy"}, {"x": sc("x", 100), "y": sc("y", 100)})
    b = RunSet("b", {"x": "hx", "y": "hy"}, {"x": sc("x", 50), "y": sc("y", 5, status="infra", quality=0.0)})
    v = compare_runs(a, b, None)
    assert v.winner == "B"
    assert v.rerun == ("y",)


def test_questions_the_script_cannot_answer_are_logged():
    script = OwnerScript(autonomy="No push.", answers=(Answer(about="function name", answer="Keep add."),),
                         default="Your call.")
    s = StandIn(script, KeywordMatcher())
    question = {"header": "Q", "multiSelect": False, "options": []}
    asyncio.run(s.answer([{**question, "question": "Which function name?"}, {**question, "question": "Which database?"}]))
    assert s.unanswered == ["Which database?"]


def test_check_env_reaches_the_checks_but_not_the_system(tmp_path, toy_repo):
    from keryx_bench.driver import build_options
    from keryx_bench.workspace import prepare_workspace, run_checks, tree_at

    repo, base, good = toy_repo
    case = load_case(write_case(tmp_path / "c", repo, base, good, checks=[("env", "test $CHECK_ONLY = 1")],
                                extra="check_env: {CHECK_ONLY: '1'}\n"))
    assert case.check_env == {"CHECK_ONLY": "1"}
    assert [r.passed for r in run_checks(tree_at(case, tmp_path / "t", good), case)] == [True]

    async def allow(tool_name, input_data, context):
        return None

    ws = prepare_workspace(case, tmp_path / "runs", "r1")
    opts = build_options(case, model="haiku", plugin_dirs=[], ws=ws, can_use_tool=allow, extra_env={})
    assert "CHECK_ONLY" not in opts.env


def test_a_system_may_load_the_repos_project_settings_but_never_personal_ones(tmp_path, toy_case):
    import pytest

    from keryx_bench.driver import build_options
    from keryx_bench.systems import SystemConfigError, load_system
    from keryx_bench.workspace import prepare_workspace

    entry = "entry:\n  bug: '{prompt}'\n  review: '{prompt}'\n  feature: '{prompt}'\n"
    (tmp_path / "ok.yaml").write_text("name: s\nmodel: haiku\nsetting_sources: [project]\n" + entry)
    (tmp_path / "bad.yaml").write_text("name: s\nmodel: haiku\nsetting_sources: [project, user]\n" + entry)
    system = load_system(tmp_path / "ok.yaml")
    assert system.setting_sources == ("project",)
    with pytest.raises(SystemConfigError, match="user"):
        load_system(tmp_path / "bad.yaml")

    async def allow(tool_name, input_data, context):
        return None

    ws = prepare_workspace(load_case(toy_case), tmp_path / "runs", "r1")
    opts = build_options(load_case(toy_case), model="haiku", plugin_dirs=[], ws=ws, can_use_tool=allow,
                         extra_env={}, setting_sources=system.setting_sources)
    assert opts.setting_sources == ["project"]


def test_a_runs_own_executor_files_are_not_a_leak(tmp_path):
    t = tmp_path / "t.jsonl"
    own = "/h/.cursor/projects/Users-x-bench-runs-20261025T0100Z-case-repo/terminals/1.txt"
    other = "/h/.cursor/projects/Users-x-Projects-shop-mono/terminals/7.txt"
    t.write_text(json.dumps({"type": "AssistantMessage", "content": [
        {"name": "Bash", "input": {"command": f"cat {own}"}}]}) + "\n")
    assert find_leaks(t, ["/h/.cursor/projects"], allow="20261025T0100Z") == []
    t.write_text(json.dumps({"type": "AssistantMessage", "content": [
        {"name": "Bash", "input": {"command": f"cat '{other}'"}}]}) + "\n")
    assert find_leaks(t, ["/h/.cursor/projects"], allow="20261025T0100Z") == ["/h/.cursor/projects"]


def test_a_run_gets_the_real_claude_code_system_prompt(tmp_path, toy_case):
    from keryx_bench.driver import build_options
    from keryx_bench.workspace import prepare_workspace

    async def allow(tool_name, input_data, context):
        return None

    case = load_case(toy_case)
    ws = prepare_workspace(case, tmp_path / "runs", "r1")
    opts = build_options(case, model="haiku", plugin_dirs=[], ws=ws, can_use_tool=allow, extra_env={})
    assert opts.system_prompt == {"type": "preset", "preset": "claude_code"}


def test_a_stop_with_running_background_work_waits_unless_it_asks_something():
    from keryx_bench.driver import next_step

    assert next_step(active_tasks=1, reply=None, resumes=0, max_resumes=3) == "wait"
    assert next_step(active_tasks=0, reply=None, resumes=0, max_resumes=3) == "finish"
    assert next_step(active_tasks=1, reply="answer", resumes=0, max_resumes=3) == "resume"
    assert next_step(active_tasks=0, reply="answer", resumes=3, max_resumes=3) == "stalled"


def test_processes_left_behind_in_a_runs_directory_are_stopped(tmp_path):
    import subprocess
    import sys
    import time

    from keryx_bench.workspace import stop_strays

    root = tmp_path / "runs" / "r1"
    root.mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    mine = subprocess.Popen([*sleeper, str(root / "marker")])
    theirs = subprocess.Popen([*sleeper, str(other / "marker")])
    try:
        assert stop_strays(root) == [mine.pid]
        time.sleep(0.5)
        assert mine.poll() is not None
        assert theirs.poll() is None
    finally:
        theirs.kill()
        mine.kill()


def test_test_counts_are_read_from_the_common_runners():
    from keryx_bench.workspace import count_tests

    assert count_tests("FAILED x::y\n1 failed, 75 passed, 2 warnings in 0.08s\n") == (75, 1)
    assert count_tests("....\n76 passed in 0.08s\n") == (76, 0)
    cargo = ("test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured\n"
             "test result: FAILED. 3 passed; 1 failed; 0 ignored; 0 measured\n")
    assert count_tests(cargo) == (13, 1)
    assert count_tests("Tests:       2 failed, 1704 passed, 1706 total\n") == (1704, 2)
    assert count_tests("      Tests  1 failed | 7 passed (8)\n") == (7, 1)
    assert count_tests("error[E0432]: unresolved import\ncould not compile\n") is None
