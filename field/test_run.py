import json
from datetime import datetime, timedelta, timezone

import run

BASE = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)


def _ts(minutes: float) -> str:
    return (BASE + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _ms(minutes: float) -> int:
    return int((BASE + timedelta(minutes=minutes)).timestamp() * 1000)


def owner(minutes, text):
    return {"type": "user", "timestamp": _ts(minutes), "origin": {"kind": "human"},
            "message": {"role": "user", "content": text}}


def assistant(minutes, msg_id, *, out=100, model="claude-opus-5-5", tool=None, text=None):
    content = [{"type": "text", "text": text}] if text else []
    if tool:
        content.append({"type": "tool_use", "id": f"tu-{msg_id}", "name": tool[0], "input": tool[1]})
    return {"type": "assistant", "timestamp": _ts(minutes),
            "message": {"id": msg_id, "model": model, "content": content,
                        "usage": {"input_tokens": 10, "cache_creation_input_tokens": 0,
                                  "cache_read_input_tokens": 1000, "output_tokens": out}}}


def answer(minutes, msg_id):
    return {"type": "user", "timestamp": _ts(minutes), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": f"tu-{msg_id}",
         "content": 'Your questions have been answered: "Where?"="Here".'}]}}


def _write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


def _events(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))


def _setup(tmp_path):
    session = _write(tmp_path / "projects" / "p" / "s1.jsonl", [
        owner(0, "earlier, unrelated"), assistant(1, "m0", out=5000),
        owner(10, "build the terminal foundation using keryx"),
        assistant(11, "m1", out=200, tool=("Skill", {"skill": "keryx:keryx"})),
        assistant(12, "m2", out=300, tool=("AskUserQuestion", {"questions": [{"question": "Where?"}]})),
        answer(36, "m2"),                                           # the owner took 24 minutes
        assistant(37, "m3", out=100, tool=("Bash", {"command": "cursor.py create --slug tf-s1"})),
        assistant(40, "m4", out=50, text="Waiting for S1."),
        {"type": "pr-link", "timestamp": _ts(90), "prUrl": "https://github.com/o/r/pull/7"},
    ])
    _write(tmp_path / "projects" / "p" / "s1" / "subagents" / "agent-a.jsonl",
           [assistant(15, "x1", out=900, model="claude-sonnet-5-5"),
            assistant(5, "x0", out=7, model="claude-sonnet-5-5")])  # before the run: not counted
    loops = tmp_path / "repo" / ".git" / "cursor-loop"
    (loops / "tf").mkdir(parents=True)
    (loops / "tf" / "decisions.tsv").write_text(
        "ts\tphase\tdecision\twhy\tevidence\tresult\n"
        "t\tintake\tsize L\tw\te\tsized\n"
        "t\tintake\tmaster = mockup\tw\te\truling\n"
        "t\tcheck\tacceptance on base\tw\te\tFAIL as stated\n")
    _events(loops / "tf-s1" / "rounds" / "01" / "events.ndjson", [
        {"type": "system", "subtype": "init", "timestamp_ms": _ms(37)},
        {"type": "assistant", "timestamp_ms": _ms(60)},
        {"type": "result", "subtype": "success", "duration_ms": 23 * 60_000, "timestamp_ms": _ms(60),
         "usage": {"inputTokens": 500, "outputTokens": 40, "cacheReadTokens": 9000}}])
    _events(loops / "tf-s2" / "rounds" / "01" / "events.ndjson", [
        {"type": "system", "subtype": "init", "timestamp_ms": _ms(61)},
        {"type": "thinking", "subtype": "completed", "timestamp_ms": _ms(70)}])  # never finished
    return session, tmp_path / "repo"


def test_a_field_run_is_one_record_from_the_owners_keryx_prompt_on(tmp_path):
    session, repo = _setup(tmp_path)
    rec = run.record(session, repo, slug="tf", now=BASE + timedelta(minutes=120))
    assert rec["start"] == _ts(10) and rec["coordinator"]["by_model"]["claude-opus-5-5"]["output"] == 650
    assert rec["subagents"]["by_model"]["claude-sonnet-5-5"]["output"] == 900
    q = rec["owner"]["questions"]
    assert len(q) == 1 and q[0]["waited_min"] == 24.0
    assert rec["owner"]["prompts"] == 1  # the keryx prompt itself; the earlier one is outside the run
    assert rec["outcome"]["prs"] == ["https://github.com/o/r/pull/7"]
    assert rec["log"]["rulings"] == 1 and rec["log"]["rows"] == 3


def test_executor_runs_report_time_tokens_and_a_stall(tmp_path):
    session, repo = _setup(tmp_path)
    rec = run.record(session, repo, slug="tf", now=BASE + timedelta(minutes=120))
    runs = {r["loop"]: r for r in rec["executor"]["runs"]}
    assert runs["tf-s1"]["status"] == "success" and runs["tf-s1"]["minutes"] == 23.0
    assert runs["tf-s1"]["output_tokens"] == 40
    # No result event and silent for 50 minutes: the run's work may be done, but nothing will say so.
    assert runs["tf-s2"]["status"] == "stalled" and runs["tf-s2"]["silent_min"] == 50.0
    assert rec["executor"]["stalled"] == ["tf-s2"]


def test_defects_found_after_done_are_kept_with_the_record(tmp_path):
    session, repo = _setup(tmp_path)
    out = tmp_path / "field-runs"
    run.save(run.record(session, repo, slug="tf", now=BASE), out)
    run.add_defect(out, "tf", "board loses its layout on reload")
    run.save(run.record(session, repo, slug="tf", now=BASE), out)  # a later snapshot keeps them
    saved = json.loads((out / "tf.json").read_text())
    assert [d["what"] for d in saved["escaped_defects"]] == ["board loses its layout on reload"]


def test_a_pr_counts_only_when_it_first_appears_during_the_run(tmp_path):
    session, repo = _setup(tmp_path)
    lines = session.read_text().splitlines()
    # The transcript repeats the session's current PR on every turn: one from before the run is not its outcome.
    early = {"type": "pr-link", "timestamp": _ts(2), "prUrl": "https://github.com/o/r/pull/1"}
    again = {"type": "pr-link", "timestamp": _ts(50), "prUrl": "https://github.com/o/r/pull/1"}
    session.write_text("\n".join([lines[0], json.dumps(early), *lines[1:], json.dumps(again)]) + "\n")
    rec = run.record(session, repo, slug="tf", now=BASE + timedelta(minutes=120))
    assert rec["outcome"]["prs"] == ["https://github.com/o/r/pull/7"]


def test_a_glm_round_counts_its_tokens_and_time_and_a_silent_one_stalls(tmp_path):
    # Claude Code's events carry no timestamps and its usage is snake_case.
    import os
    import time
    session, repo = _setup(tmp_path)
    loops = repo / ".git" / "cursor-loop"
    _events(loops / "tf-g1" / "rounds" / "01" / "events.ndjson", [
        {"type": "system", "subtype": "init", "session_id": "s"},
        {"type": "result", "subtype": "success", "duration_ms": 2 * 60_000,
         "usage": {"input_tokens": 10, "output_tokens": 321}}])
    silent = loops / "tf-g2" / "rounds" / "01" / "events.ndjson"
    _events(silent, [{"type": "system", "subtype": "init", "session_id": "s"}])
    old = time.time() - 30 * 60
    os.utime(silent, (old, old))
    rec = run.record(session, repo, slug="tf", now=datetime.now(timezone.utc))
    runs = {r["loop"]: r for r in rec["executor"]["runs"]}
    assert runs["tf-g1"]["status"] == "success" and runs["tf-g1"]["minutes"] == 2.0
    assert runs["tf-g1"]["output_tokens"] == 321
    assert runs["tf-g2"]["status"] == "stalled" and 29 <= runs["tf-g2"]["silent_min"] <= 31


def test_an_explicit_start_and_end_bound_a_run_inside_a_longer_session(tmp_path):
    # Seen: a session reviewed a design with keryx, then built it after a compaction without calling keryx again,
    # and did unrelated work in between: the run needs its own start and end.
    session, repo = _setup(tmp_path)
    rec = run.record(session, repo, slug="tf", now=BASE + timedelta(minutes=120),
                     start=_ts(36), until=_ts(41))
    assert rec["start"] == _ts(36) and rec["wall_min"] == 4.0
    assert rec["coordinator"]["by_model"]["claude-opus-5-5"]["output"] == 150  # m3 + m4 only
    assert rec["outcome"]["prs"] == []  # the PR at minute 90 is after the run
    assert rec["subagents"]["by_model"] == {}  # the subagent ran at minute 15


def test_rulings_logged_in_the_phase_column_count(tmp_path):
    session, repo = _setup(tmp_path)
    log = repo / ".git" / "cursor-loop" / "tf" / "decisions.tsv"
    log.write_text(log.read_text() + "t\truling\tGLM executors\tw\te\tlogged\n")
    assert run.record(session, repo, slug="tf", now=BASE)["log"]["rulings"] == 2


def test_a_running_glm_round_counts_its_minutes_from_its_start(tmp_path):
    import os
    import time
    session, repo = _setup(tmp_path)
    r = repo / ".git" / "cursor-loop" / "tf-g3" / "rounds" / "01"
    _events(r / "events.ndjson", [{"type": "system", "subtype": "init", "session_id": "s"}])
    started = datetime.now(timezone.utc) - timedelta(minutes=25)
    (r / "run.json").write_text(json.dumps({"startedAt": started.strftime("%Y-%m-%dT%H:%M:%SZ")}))
    os.utime(r / "events.ndjson", (time.time(), time.time()))
    runs = {x["loop"]: x for x in run.record(session, repo, slug="tf", now=datetime.now(timezone.utc))["executor"]["runs"]}
    assert runs["tf-g3"]["status"] == "running" and 24 <= runs["tf-g3"]["minutes"] <= 26


def test_a_record_can_be_saved_under_its_own_name(tmp_path):
    session, repo = _setup(tmp_path)
    out = tmp_path / "field-runs"
    path = run.save(run.record(session, repo, slug="tf", now=BASE, name="tf-build"), out)
    assert path.name == "tf-build.json" and json.loads(path.read_text())["slug"] == "tf"


def test_executor_loops_can_be_named_apart_from_the_slug(tmp_path):
    # Seen: a run on slug playground-parity dispatched its slices as playground-u1g, playground-b1, rhg-a-ddl...
    session, repo = _setup(tmp_path)
    loops = repo / ".git" / "cursor-loop"
    _events(loops / "pg-u1" / "rounds" / "01" / "events.ndjson", [
        {"type": "result", "subtype": "success", "duration_ms": 60_000, "usage": {"output_tokens": 5}}])
    _events(loops / "other-x" / "rounds" / "01" / "events.ndjson", [{"type": "result", "subtype": "success"}])
    rec = run.record(session, repo, slug="tf", now=BASE, loops=["tf", "pg-"])
    assert sorted(r["loop"] for r in rec["executor"]["runs"]) == ["pg-u1", "tf-s1", "tf-s2"]


def test_a_subagent_message_counts_its_final_usage_not_its_first_chunk(tmp_path):
    # Seen 2026-10-27: background subagent transcripts write one entry per streamed chunk with growing usage;
    # a review's first chunk carried 992 output tokens, its last 41,770.
    session, repo = _setup(tmp_path)
    _write(tmp_path / "projects" / "p" / "s1" / "subagents" / "agent-b.jsonl",
           [assistant(16, "y1", out=3, model="claude-sonnet-5-5"),
            assistant(16.5, "y1", out=400, model="claude-sonnet-5-5"),
            assistant(17, "y2", out=50, model="claude-sonnet-5-5")])
    subs = run.record(session, repo, slug="tf", now=BASE)["subagents"]["by_model"]["claude-sonnet-5-5"]
    assert subs["output"] == 900 + 400 + 50


def test_a_round_whose_run_json_says_error_is_an_error(tmp_path):
    # Seen: GLM rounds cut by a usage limit wrote a result event (shown "success"); Cursor rounds that died at
    # dispatch wrote none (shown "stalled" or "running"). run.json said ERROR in both.
    session, repo = _setup(tmp_path)
    loops = repo / ".git" / "cursor-loop"
    r1 = loops / "tf-g1" / "rounds" / "01"
    _events(r1 / "events.ndjson", [{"type": "result", "subtype": "success", "duration_ms": 60_000,
                                    "usage": {"output_tokens": 7}}])
    (r1 / "run.json").write_text(json.dumps({"status": "ERROR"}))
    r2 = loops / "tf-c1" / "rounds" / "01"
    _events(r2 / "events.ndjson", [{"type": "system", "subtype": "init", "timestamp_ms": _ms(37)}])
    (r2 / "run.json").write_text(json.dumps({"status": "ERROR"}))
    rec = run.record(session, repo, slug="tf", now=BASE + timedelta(hours=3))
    runs = {x["loop"]: x for x in rec["executor"]["runs"]}
    assert runs["tf-g1"]["status"] == "error" and runs["tf-g1"]["output_tokens"] == 7
    assert runs["tf-c1"]["status"] == "error"
    assert "tf-c1" not in rec["executor"]["stalled"] and "tf-s2" in rec["executor"]["stalled"]


def test_the_run_log_continues_in_the_executor_slugs_after_a_runner_switch(tmp_path):
    # Seen: a run copied its log into <slug>-glm/decisions.tsv and kept logging there (50 rows; 16 were read).
    session, repo = _setup(tmp_path)
    loops = repo / ".git" / "cursor-loop"
    original = (loops / "tf" / "decisions.tsv").read_text()
    (loops / "tf-glm").mkdir()
    (loops / "tf-glm" / "decisions.tsv").write_text(
        original + "t\tfix\tround 2\tw\te\tdone\nt\tfinish\tdraft PR\tw\te\tdone\n")
    log = run.record(session, repo, slug="tf", now=BASE)["log"]
    assert log["rows"] == 5 and log["phases"]["finish"] == 1 and log["phases"]["intake"] == 2
def test_a_round_with_only_run_json_counts_as_a_run(tmp_path):
    # A Claude-subagent round writes run.json (prepared, then marked by the coordinator) and no events.
    session, repo = _setup(tmp_path)
    loops = repo / ".git" / "cursor-loop"
    r1 = loops / "tf-x" / "rounds" / "01"
    _events(r1 / "events.ndjson", [{"type": "system", "subtype": "init", "timestamp_ms": _ms(37)}])
    (r1 / "run.json").write_text(json.dumps({"status": "ERROR"}))
    r2 = loops / "tf-x" / "rounds" / "02"
    r2.mkdir(parents=True)
    (r2 / "run.json").write_text(json.dumps({"status": "FINISHED", "startedAt": _ts(40), "finishedAt": _ts(52)}))
    r3 = loops / "tf-sub" / "rounds" / "01"
    r3.mkdir(parents=True)
    (r3 / "run.json").write_text(json.dumps({"status": "DISPATCHED", "startedAt": _ts(50)}))
    runs = {x["loop"]: x for x in run.record(session, repo, slug="tf", now=BASE + timedelta(minutes=55))["executor"]["runs"]}
    assert runs["tf-x"]["rounds"] == 2 and runs["tf-x"]["status"] == "success"
    assert 11.9 <= runs["tf-x"]["minutes"] <= 12.1
    assert runs["tf-sub"]["status"] == "running" and 4.9 <= runs["tf-sub"]["minutes"] <= 5.1


def test_a_run_in_the_keryx_folder_is_read_from_there(tmp_path):
    session, repo = _setup(tmp_path)
    legacy, new = repo / ".git" / "cursor-loop", repo / ".keryx" / "runs"
    new.mkdir(parents=True)
    for name in ("tf", "tf-s1", "tf-s2"):
        (legacy / name).rename(new / name)
    rec = run.record(session, repo, slug="tf", now=BASE)
    assert rec["log"]["rows"] == 3
    assert sorted(x["loop"] for x in rec["executor"]["runs"]) == ["tf-s1", "tf-s2"]


def test_a_run_split_across_both_layouts_is_read_from_both(tmp_path):
    # A run started before 1.2 keeps its folder; a slice it starts after the upgrade lands in .keryx/runs.
    session, repo = _setup(tmp_path)
    new = repo / ".keryx" / "runs"
    new.mkdir(parents=True)
    (repo / ".git" / "cursor-loop" / "tf-s2").rename(new / "tf-s2")
    rec = run.record(session, repo, slug="tf", now=BASE)
    assert rec["log"]["rows"] == 3
    assert sorted(x["loop"] for x in rec["executor"]["runs"]) == ["tf-s1", "tf-s2"]


def test_runs_in_a_separate_git_dir_and_a_submodule_are_recorded(tmp_path):
    # The recorder finds the main checkout by the adapter's rule (keryx.py main_worktree).
    import subprocess
    session, _ = _setup(tmp_path)

    def g(*a, cwd=tmp_path):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "protocol.file.allow=always", *a],
                       cwd=cwd, check=True, capture_output=True)

    g("init", "-q", "-b", "main", "sep", f"--separate-git-dir={tmp_path / 'sep.gitdir'}")
    g("init", "-q", "-b", "main", "sub")
    g("commit", "-q", "--allow-empty", "-m", "b", cwd=tmp_path / "sub")
    g("init", "-q", "-b", "main", "sup")
    g("submodule", "-q", "add", str(tmp_path / "sub"), "mod", cwd=tmp_path / "sup")
    for checkout in (tmp_path / "sep", tmp_path / "sup" / "mod"):
        log = checkout / ".keryx" / "runs" / "tf" / "decisions.tsv"
        log.parent.mkdir(parents=True)
        log.write_text("ts\tphase\tdecision\twhy\tevidence\tresult\nt\tintake\tsize M\tw\te\tM\n")
        assert run.record(session, checkout, slug="tf", now=BASE)["log"]["rows"] == 1, checkout
