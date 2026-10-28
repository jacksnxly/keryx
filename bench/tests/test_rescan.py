import json

from helpers import write_case
from keryx_bench.case import case_hash, load_case
from keryx_bench.cli import main
from keryx_bench.leaks import find_leaks


def _assistant(*commands):
    return "".join(json.dumps({"type": "AssistantMessage", "content": [{"name": "Bash", "input": {"command": c}}]})
                   + "\n" for c in commands)


def test_a_cd_carries_over_to_the_next_bash_call(tmp_path):
    t = tmp_path / "t.jsonl"
    # Seen in the paired run: the shell keeps its folder between calls, so `../../..` went back to the repo.
    t.write_text(_assistant("cd rust/crates/rc-sweep", "cd ../../.. && cat rust/x.rs"))
    assert find_leaks(t, ["/R"], allow="run1", base_dir="/R/run1/case/repo") == []


def test_a_cd_out_of_the_project_does_not_carry_over(tmp_path):
    t = tmp_path / "t.jsonl"
    # The shell goes back to the project folder when a call leaves it.
    t.write_text(_assistant("cd /tmp && ls", "cat ../../../x"))
    assert find_leaks(t, ["/R"], allow="run1", base_dir="/R/run1/case/repo") == ["/R"]


def test_an_unknown_cd_target_stops_resolving_relative_paths(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(_assistant('cd "$STATE"', "ls ../../.."))
    assert find_leaks(t, ["/R"], allow="run1", base_dir="/R/run1/case/repo") == []
    t.write_text(_assistant('cd "$STATE"', "cd /R/run1/case/repo", "ls ../../.."))
    assert find_leaks(t, ["/R"], allow="run1", base_dir="/R/run1/case/repo") == ["/R"]


RUN = "20991231T000000Z-s"


def _result(tmp_path, toy_repo, transcript: str, *, leaks, quality, false_done, harness="abc"):
    repo, base, good = toy_repo
    case_dir = write_case(tmp_path / "case", repo, base, good)
    runs = tmp_path / "runs"
    run_dir = tmp_path / "results" / RUN
    out = run_dir / "toy-add"
    out.mkdir(parents=True)
    cwd = runs / RUN / "toy-add" / "repo"
    cwd.mkdir(parents=True)
    (out / "transcript.jsonl").write_text(transcript)
    (out / "record.json").write_text(json.dumps({
        "case_id": "toy-add", "system": "s", "run_id": RUN, "status": "finished", "wall_s": 10.0,
        "cost_usd": 1.0, "cwd": str(cwd), "final_text": "Done.", "leaks": leaks}))
    (out / "checks.json").write_text(json.dumps([{"name": "hidden-add", "passed": True, "exit_code": 0,
                                                  "seconds": 1.0, "output_tail": ""}]))
    (out / "score.json").write_text(json.dumps({
        "case_id": "toy-add", "mode": "bug", "status": "finished", "quality": quality, "defects_found": None,
        "defects_total": None, "false_done": false_done, "wall_s": 10.0, "cost_usd": 1.0, "interruptions": 0,
        "contaminated": bool(leaks)}))
    (run_dir / "run.json").write_text(json.dumps({
        "system": "s", "case_hashes": {"toy-add": case_hash(load_case(case_dir))}, "case_dirs": {"toy-add": str(case_dir)},
        "harness": harness}))
    return run_dir, out, runs


def _judge(monkeypatch, answer):
    from keryx_bench import rescan

    asked = []

    async def judge(question, text):
        asked.append(text)
        return answer

    monkeypatch.setattr(rescan, "model_says_yes", judge)
    return asked


def test_rescan_clears_a_false_leak_and_rescores_from_the_saved_checks(tmp_path, toy_repo, monkeypatch):
    asked = _judge(monkeypatch, True)
    t = _assistant("cd a/b/c", "cd ../../.. && ls")
    run_dir, out, runs = _result(tmp_path, toy_repo, t, leaks=[str(tmp_path / "runs")], quality=0.0,
                                 false_done=True)
    assert main(["rescan", str(run_dir)]) == 0
    score = json.loads((out / "score.json").read_text())
    assert (score["quality"], score["contaminated"], score["false_done"]) == (1.0, False, False)
    assert json.loads((out / "record.json").read_text())["leaks"] == []
    audit = json.loads((out / "rescan.json").read_text())
    assert audit["before"]["leaks"] == [str(tmp_path / "runs")] and audit["after"]["leaks"] == []
    assert audit["before"]["quality"] == 0.0
    assert json.loads((run_dir / "run.json").read_text())["rescans"][0]["harness"]
    assert asked == []  # the old false done already said the run claimed to be done
    assert score["claims_done"] is True


def test_rescan_leaves_an_unasked_judge_unknown(tmp_path, toy_repo, monkeypatch):
    asked = _judge(monkeypatch, True)
    run_dir, out, _ = _result(tmp_path, toy_repo, _assistant("ls"), leaks=[], quality=1.0, false_done=False)
    main(["rescan", str(run_dir)])
    assert json.loads((out / "score.json").read_text())["claims_done"] is None and asked == []


def test_rescan_keeps_a_real_leak(tmp_path, toy_repo, monkeypatch):
    asked = _judge(monkeypatch, True)
    repo, _, _ = toy_repo
    t = _assistant(f"cat {repo.resolve()}/calc.py")
    run_dir, out, runs = _result(tmp_path, toy_repo, t, leaks=[], quality=1.0, false_done=False)
    assert main(["rescan", str(run_dir)]) == 0
    score = json.loads((out / "score.json").read_text())
    assert (score["quality"], score["contaminated"], score["false_done"]) == (0.0, True, True)
    assert asked == ["Done."]  # a clean full score never needed the judge, so it is asked now
    assert json.loads((out / "record.json").read_text())["leaks"] == [str(repo.resolve())]


def test_a_rescanned_run_compares_only_with_a_run_rescanned_the_same_way(tmp_path, toy_repo, monkeypatch):
    _judge(monkeypatch, True)
    from keryx_bench.compare import load_runset

    run_dir, _, _ = _result(tmp_path, toy_repo, _assistant("ls"), leaks=[], quality=1.0, false_done=False)
    before = load_runset(run_dir).harness
    main(["rescan", str(run_dir)])
    assert load_runset(run_dir).harness != before


def test_rescan_also_reads_the_kept_subagent_transcripts(tmp_path, toy_repo, monkeypatch):
    _judge(monkeypatch, True)
    repo, _, _ = toy_repo
    run_dir, out, _ = _result(tmp_path, toy_repo, _assistant("ls"), leaks=[], quality=1.0, false_done=False)
    (out / "subagents").mkdir()
    (out / "subagents" / "agent-a1.jsonl").write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": f"{repo.resolve()}/calc.py"}}]}}) + "\n")
    main(["rescan", str(run_dir)])
    assert json.loads((out / "record.json").read_text())["leaks"] == [str(repo.resolve())]


def _score(case_id, quality=1.0):
    from keryx_bench.score import Score
    return Score(case_id=case_id, mode="bug", status="finished", quality=quality, defects_found=None,
                 defects_total=None, false_done=False, wall_s=10.0, cost_usd=1.0, interruptions=0)


def test_resuming_one_arm_more_often_with_the_same_version_still_compares(tmp_path):
    from keryx_bench.compare import load_runset

    for name, resumes in (("a", ["v2"]), ("b", ["v2", "v2"])):
        d = tmp_path / name
        (d / "x").mkdir(parents=True)
        (d / "x" / "score.json").write_text(json.dumps(_score("x").__dict__))
        (d / "run.json").write_text(json.dumps({"system": name, "case_hashes": {"x": "h"}, "harness": "v1",
                                                "resumed": [{"harness": v} for v in resumes]}))
    assert load_runset(tmp_path / "a").harness == load_runset(tmp_path / "b").harness


def test_a_cross_version_or_subset_comparison_is_allowed_only_when_asked_and_marked_provisional():
    from keryx_bench.compare import RunSet, compare_runs

    a = RunSet("a", {"x": "h", "y": "h"}, {"x": _score("x"), "y": _score("y")}, harness="v1")
    b = RunSet("b", {"x": "h"}, {"x": _score("x")}, harness="v2")
    assert compare_runs(a, b, None).winner == "invalid"
    verdict = compare_runs(a, b, None, common_only=True, allow_bench_mismatch=True)
    assert verdict.winner != "invalid"
    assert any("provisional" in r and "v1" in r and "v2" in r for r in verdict.reasons)
    assert any("provisional" in r and "y" in r for r in verdict.reasons)


def test_under_the_runs_folder_only_another_run_or_a_glob_into_it_is_a_leak(tmp_path):
    t = tmp_path / "t.jsonl"
    runs = "/S/bench-runs"
    me = "20261024T224456Z-cand"
    forbidden = [runs]
    # Seen: a reviewer walked up the parent folders looking for CLAUDE.md files.
    t.write_text(_assistant(f"for d in {runs}/{me}/case {runs} /S; do ls $d/CLAUDE.md; done"))
    assert find_leaks(t, forbidden, allow=me, base_dir=f"{runs}/{me}/case/repo", runs_root=runs) == []
    # Seen: a run globbed every run's folder for a virtualenv.
    t.write_text(_assistant(f"ls -d {runs}/*/venv*"))
    assert find_leaks(t, forbidden, allow=me, base_dir=f"{runs}/{me}/case/repo", runs_root=runs) == [runs]
    t.write_text(_assistant(f"cat {runs}/20261024T224452Z-base/case/repo/x.rs"))
    assert find_leaks(t, forbidden, allow=me, base_dir=f"{runs}/{me}/case/repo", runs_root=runs) == [runs]
