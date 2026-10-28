from keryx_bench.usage import collect_executor_usage


def test_cursor_loop_usage_is_summed(tmp_path):
    rounds = tmp_path / ".git" / "cursor-loop" / "slug" / "rounds"
    (rounds / "01").mkdir(parents=True)
    (rounds / "02").mkdir()
    (rounds / "01" / "events.ndjson").write_text(
        '{"type":"system","subtype":"init","model":"Grok"}\n'
        '{"type":"result","duration_ms":1000,"usage":{"inputTokens":10,"outputTokens":5,"cacheReadTokens":100}}\n')
    (rounds / "02" / "events.ndjson").write_text(
        '{"type":"result","duration_ms":500,"usage":{"inputTokens":1,"outputTokens":2,"cacheReadTokens":3}}\n')
    assert collect_executor_usage(tmp_path) == {
        "cursor": {"runs": 2, "input_tokens": 11, "output_tokens": 7, "cache_read_tokens": 103, "seconds": 1.5}}


def test_no_executor_runs_means_no_usage(tmp_path):
    (tmp_path / ".git").mkdir()
    assert collect_executor_usage(tmp_path) == {}
