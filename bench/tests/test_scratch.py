import asyncio
import json
import subprocess
import sys
import time

import pytest

from helpers import write_case
from keryx_bench import runner, scratch
from keryx_bench.case import load_case
from keryx_bench.driver import RunRecord
from keryx_bench.leaks import find_subagent_leaks
from keryx_bench.owner import KeywordMatcher
from keryx_bench.sessions import keep_subagent_transcripts, session_dir_for
from keryx_bench.systems import System


def _native(command):
    """One tool call as Claude Code writes it in a subagent's own transcript."""
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": command}}]}}) + "\n"


def test_a_subagents_tool_calls_are_scanned_for_leaks(tmp_path):
    f = tmp_path / "agent-a1.jsonl"
    # Seen in the paired run: a background reviewer's scratch never appeared in the main transcript.
    f.write_text(_native("cd sub && ls ../../../../other-run/repo"))
    assert find_subagent_leaks([f], ["/R"], allow="run1", base_dir="/R/run1/case/repo") == ["/R"]
    f.write_text(_native("cat /R/run1/case/repo/x.py"))
    assert find_subagent_leaks([f], ["/R"], allow="run1", base_dir="/R/run1/case/repo") == []


def test_a_runs_subagent_transcripts_are_kept_before_its_session_folder_goes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cwd = "/R/run1/case/repo"
    agents = session_dir_for(cwd) / "sess-1" / "subagents"
    agents.mkdir(parents=True)
    (agents / "agent-a1.jsonl").write_text(_native("ls"))
    kept = keep_subagent_transcripts(cwd, tmp_path / "out" / "subagents")
    assert [p.name for p in kept] == ["agent-a1.jsonl"]
    assert (tmp_path / "out" / "subagents" / "agent-a1.jsonl").read_text() == _native("ls")


def test_tmp_names_come_from_both_spellings_and_skip_shared_entries(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("cargo build --target-dir /tmp/rc-review-target; cat /private/tmp/notes.md; "
                 "cat /private/tmp/claude-501/x/tasks/a.output; ls /tmp/.s.PGSQL.55432; ls /tmp/")
    assert scratch.tmp_names_used([f, tmp_path / "missing.jsonl"]) == {"rc-review-target", "notes.md"}


def test_tidy_removes_only_new_entries_the_run_named_and_lists_old_ones_it_used(tmp_path):
    root = tmp_path / "tmp"
    for name in ("new", "old", "someone-elses"):
        (root / name).mkdir(parents=True)
    removed, preexisting = scratch.tidy_tmp(root, before={"old"}, used={"new", "old", "gone"})
    assert (removed, preexisting) == (["new"], ["old"])
    assert not (root / "new").exists() and (root / "old").exists() and (root / "someone-elses").exists()


def test_tidy_stops_a_daemon_left_running_in_the_runs_scratch(tmp_path):
    root = tmp_path / "tmp"
    (root / "rcpg").mkdir(parents=True)
    # A detached server keeps running after the session (seen: postgres -D /tmp/rc-review-pg).
    daemon = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", str(root / "rcpg" / "data")],
                              start_new_session=True)
    try:
        scratch.tidy_tmp(root, before=set(), used={"rcpg"})
        deadline = time.monotonic() + 5
        while daemon.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert daemon.poll() is not None
    finally:
        if daemon.poll() is None:
            daemon.kill()


PLAIN = System(name="plain", model="haiku", plugins=(), assemble=None, env={},
               entry={"bug": "{prompt}", "review": "{prompt}", "feature": "{prompt}"})


def _case(tmp_path, toy_repo):
    repo, base, good = toy_repo
    return load_case(write_case(tmp_path / "case", repo, base, good, checks=[("c", "true")]))


async def _yes(*args, **kwargs):
    return True


def _run_with_scratch(tmp_path, toy_repo, monkeypatch, *, preexisting):
    root = tmp_path / "tmp"
    root.mkdir()
    if preexisting:
        (root / "shared-target").mkdir()
    monkeypatch.setattr(scratch, "TMP_ROOT", root)

    async def scratching_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        (root / "shared-target").mkdir(exist_ok=True)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"type": "AssistantMessage", "content": [
            {"name": "Bash", "input": {"command": "cargo test --target-dir /tmp/shared-target"}}]}) + "\n")
        return RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status="finished")

    monkeypatch.setattr(runner, "run_case", scratching_run_case)
    monkeypatch.setattr(runner, "model_says_yes", _yes)
    record, score = asyncio.run(runner.run_one(_case(tmp_path, toy_repo), PLAIN, tmp_path / "runs",
                                               tmp_path / "results", "20991231T000000Z-plain",
                                               matcher=KeywordMatcher()))
    return root, record, score


def test_a_run_leaves_no_scratch_behind_in_tmp(tmp_path, toy_repo, monkeypatch):
    root, record, score = _run_with_scratch(tmp_path, toy_repo, monkeypatch, preexisting=False)
    assert not (root / "shared-target").exists()
    assert record.tmp_removed == ["shared-target"] and score.status == "finished"


def test_a_run_that_used_scratch_that_was_already_there_is_not_scored(tmp_path, toy_repo, monkeypatch):
    root, record, score = _run_with_scratch(tmp_path, toy_repo, monkeypatch, preexisting=True)
    # Two arms on the same task picked the same /tmp name in the paired run; whoever came second used the
    # other's build output. That is the bench's isolation failing: re-run, never compare.
    assert score.status == "harness" and "/tmp/shared-target" in record.error
    assert (root / "shared-target").exists()


def test_only_one_bench_runner_at_a_time(tmp_path, toy_repo, monkeypatch):
    monkeypatch.setattr(runner, "RUNNER_LOCK", tmp_path / "runner.lock")
    with runner.one_runner():
        with pytest.raises(SystemExit, match="another bench run"):
            with runner.one_runner():
                pass


def test_an_interrupted_run_still_removes_its_scratch(tmp_path, toy_repo, monkeypatch):
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(scratch, "TMP_ROOT", root)

    async def interrupted_run_case(case, system, ws, plugin_dirs, standin, transcript, **kw):
        (root / "half-done").mkdir()
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps({"type": "AssistantMessage", "content": [
            {"name": "Bash", "input": {"command": "initdb /tmp/half-done"}}]}) + "\n")
        raise KeyboardInterrupt  # the runner was stopped with SIGTERM mid-case

    monkeypatch.setattr(runner, "run_case", interrupted_run_case)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(runner.run_one(_case(tmp_path, toy_repo), PLAIN, tmp_path / "runs", tmp_path / "results",
                                   "20991231T000000Z-plain", matcher=KeywordMatcher()))
    assert not (root / "half-done").exists()
