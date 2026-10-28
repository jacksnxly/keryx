"""The executors' logs are read from <repo>/.keryx/runs/ (keryx 1.2) as well as from .git/cursor-loop/ (before 1.2)."""
import json

from keryx_bench.leaks import find_executor_leaks
from keryx_bench.usage import collect_executor_usage

EVENT = {"type": "tool_call", "subtype": "started", "tool_call": {"readToolCall": {"args": {"path": "/src/repo/calc.py"}}}}


def test_executor_usage_is_read_from_the_keryx_folder_too(tmp_path):
    (tmp_path / ".git").mkdir()
    rounds = tmp_path / ".keryx" / "runs" / "slug" / "rounds" / "01"
    rounds.mkdir(parents=True)
    (rounds / "events.ndjson").write_text(
        '{"type":"result","duration_ms":2000,"usage":{"inputTokens":4,"outputTokens":3,"cacheReadTokens":2}}\n')
    assert collect_executor_usage(tmp_path) == {
        "cursor": {"runs": 1, "input_tokens": 4, "output_tokens": 3, "cache_read_tokens": 2, "seconds": 2.0}}


def test_executor_leaks_are_read_from_the_keryx_folder_too(tmp_path):
    rounds = tmp_path / ".keryx" / "runs" / "slug" / "rounds" / "01"
    rounds.mkdir(parents=True)
    (rounds / "events.ndjson").write_text(json.dumps(EVENT) + "\n")
    assert find_executor_leaks(tmp_path, ["/src/repo"], allow="R1") == ["/src/repo"]


def test_kept_executor_logs_are_scanned_in_the_new_layout(tmp_path):
    rounds = tmp_path / "executor" / "runs" / "slug" / "rounds" / "01"
    rounds.mkdir(parents=True)
    (rounds / "events.ndjson").write_text(json.dumps(EVENT) + "\n")
    assert find_executor_leaks(tmp_path / "repo", ["/src/repo"], allow="R1", logs=tmp_path / "executor") == ["/src/repo"]
