import json

import field

T0 = "2026-10-20T10:00:00.000Z"


def _ts(minutes: float) -> str:
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def owner(minutes, text, **extra):
    return {"type": "user", "timestamp": _ts(minutes), "origin": {"kind": "human"}, "promptSource": "typed",
            "message": {"role": "user", "content": text}, **extra}


def assistant(minutes, msg_id, *, text=None, out=100, fresh=1000, cached=5000, skill=None, tool=None):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "tool_use", "name": tool[0], "input": tool[1]})
    entry = {"type": "assistant", "timestamp": _ts(minutes),
             "message": {"id": msg_id, "role": "assistant", "content": content,
                         "usage": {"input_tokens": fresh, "cache_creation_input_tokens": 0,
                                   "cache_read_input_tokens": cached, "output_tokens": out}}}
    if skill:
        entry["attributionSkill"] = skill
    return entry


def automated(minutes, text):
    return {"type": "user", "timestamp": _ts(minutes), "origin": {"kind": "task-notification"},
            "promptSource": "system", "message": {"role": "user", "content": text}}


def _write(path, entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


def test_turns_are_cut_at_the_owners_own_prompts_only(tmp_path):
    session = _write(tmp_path / "s.jsonl", [
        owner(0, "fix the funding sign"),
        assistant(1, "m1", out=200, skill="cursor-loop", tool=("Bash", {"command": "ls"})),
        automated(30, "<task-notification>done</task-notification>"),  # wakes the run; not the owner
        assistant(31, "m2", text="Fixed and all tests pass.", out=50),
        owner(40, "that is still wrong on the page"),
        assistant(41, "m3", text="Looking.", out=10),
    ])
    turns = field.read_session(session)
    assert len(turns) == 2
    first = turns[0]
    assert first.workflow == "cursor-loop"
    assert first.output_tokens == 250 and first.claimed_done and first.pushback_next
    assert first.false_done_proxy
    # Busy time skips the 29-minute silence while the run waited on its own job.
    assert first.busy_s == 2 * 60
    assert not turns[1].claimed_done and not turns[1].pushback_next


def test_a_message_split_over_entries_counts_its_usage_once(tmp_path):
    session = _write(tmp_path / "s.jsonl", [
        owner(0, "go"),
        assistant(1, "m1", text="part one", out=300),
        assistant(1, "m1", tool=("Bash", {"command": "ls"}), out=300),  # same API message, second block
    ])
    [turn] = field.read_session(session)
    assert turn.output_tokens == 300 and turn.fresh_tokens == 1000


def test_subagent_usage_lands_in_the_turn_it_ran_in(tmp_path):
    session = _write(tmp_path / "s.jsonl", [owner(0, "review it"), assistant(1, "m1", out=10),
                                            owner(60, "thanks"), assistant(61, "m2", out=10)])
    agents = tmp_path / "s" / "subagents"
    agents.mkdir(parents=True)
    _write(agents / "agent-a1.jsonl", [assistant(5, "x1", out=1000), assistant(62, "x2", out=7)])
    first, second = field.read_session(session)
    assert first.output_tokens == 1010 and first.subagents == 1
    assert second.output_tokens == 17


def test_an_interruption_counts_against_the_turn_it_cut(tmp_path):
    session = _write(tmp_path / "s.jsonl", [
        owner(0, "do x"), assistant(1, "m1", out=10),
        {"type": "user", "timestamp": _ts(2), "message": {"role": "user", "content": [
            {"type": "text", "text": "[Request interrupted by user]"}]}},
        owner(3, "no, do y instead"), assistant(4, "m2", out=10),
    ])
    first, _ = field.read_session(session)
    assert first.interrupted and first.pushback_next


def test_pushback_words_in_english_and_german():
    for text in ("it doesn't work", "still broken", "you said it was done", "funktioniert nicht",
                 "immer noch falsch", "nope, wrong file"):
        assert field.is_pushback(text), text
    for text in ("thanks, looks good", "now do the next one", "ok merge it"):
        assert not field.is_pushback(text), text


def test_the_workflow_is_the_most_specific_skill_of_the_turn():
    assert field.workflow_of({"triple-check", "cursor-loop"}) == "cursor-loop"
    assert field.workflow_of({"triple-check", "pack:brainstorming"}) == "pack:brainstorming"
    assert field.workflow_of({"keryx-pr-review", "triple-check"}) == "keryx"
    assert field.workflow_of({"triple-check"}) == "triple-check only"
    assert field.workflow_of(set()) == "none"


def test_summary_groups_turns_by_workflow(tmp_path):
    session = _write(tmp_path / "s.jsonl", [
        owner(0, "a"), assistant(1, "m1", out=100, skill="cursor-loop", text="Done."),
        owner(10, "still broken"), assistant(11, "m2", out=300, skill="cursor-loop", text="Fixed."),
        owner(200, "great, next: the newsletter"), assistant(201, "m3", out=50),  # > 2 h on: a new task
    ])
    rows = field.summarize(field.read_session(session))
    loop = rows["cursor-loop"]
    assert loop["turns"] == 2 and loop["median_output_tokens"] == 200
    assert loop["false_done_proxy_rate"] == 0.5
    assert rows["none"]["turns"] == 1


def test_a_workflow_keeps_the_follow_up_turns_it_runs_through(tmp_path):
    session = _write(tmp_path / "s.jsonl", [
        owner(0, "/cursor-loop fix it"), assistant(1, "m1", out=10, skill="cursor-loop"),
        owner(30, "go on with QA"), assistant(31, "m2", out=10),           # no skill tag of its own
        owner(300, "new topic: write the newsletter"), assistant(301, "m3", out=10),  # > 2 h later
    ])
    first, second, third = field.read_session(session)
    assert (first.workflow, second.workflow, third.workflow) == ("cursor-loop", "cursor-loop", "none")


def test_a_turn_knows_where_it_ran_and_when_it_ended(tmp_path):
    session = _write(tmp_path / "s.jsonl", [
        {**owner(0, "go"), "cwd": "/repo/x"}, assistant(1, "m1", out=10), assistant(7, "m2", out=10)])
    [turn] = field.read_session(session)
    assert turn.cwd == "/repo/x" and turn.end == _ts(7)


def test_rework_joins_a_turns_commits_with_the_fixes_that_followed(tmp_path, monkeypatch):
    import rework

    turn = field.Turn(session="s", project="p", start=_ts(0), end=_ts(30), cwd=str(tmp_path), claimed_done=True,
                      shas={"a"})
    made = rework.Commit("a", 1.0, "feat: a", frozenset({"a.py"}))
    monkeypatch.setattr(field, "_commits_for", lambda cwd: [made])
    monkeypatch.setattr(rework, "rework_for", lambda window, commits, own=None: ([made], [made]))
    field.attach_rework([turn])
    assert turn.commits == 1 and turn.reworked
    rows = field.summarize([turn])
    assert rows["none"]["turns_with_commits"] == 1 and rows["none"]["rework_rate"] == 1.0


def test_a_turn_owns_only_the_commits_its_own_git_commit_calls_printed(tmp_path):
    result = {"type": "user", "timestamp": _ts(2), "message": {"role": "user", "content": [
        {"type": "tool_result", "content": "[fix/sign 3f18dcf] fix(api): sign of funding\n 1 file changed"}]}}
    session = _write(tmp_path / "s.jsonl", [owner(0, "go"), assistant(1, "m1", tool=("Bash", {"command": "git commit"})),
                                            result, assistant(3, "m2", text="Done.")])
    [turn] = field.read_session(session)
    assert turn.shas == {"3f18dcf"}
