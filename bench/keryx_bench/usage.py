"""Token use of the executors a coordinator dispatched during a run, read from their own logs."""
from __future__ import annotations

import json
from pathlib import Path


def collect_executor_usage(repo: Path) -> dict[str, dict[str, float]]:
    git_dir = Path(repo) / ".git"
    if not git_dir.is_dir():
        return {}
    totals = {"runs": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "seconds": 0.0}
    logs = [*git_dir.glob("cursor-loop/*/rounds/*/events.ndjson"),
            *(Path(repo) / ".keryx").glob("runs/*/rounds/*/events.ndjson")]
    for events in sorted(logs):
        for line in events.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "result":
                continue
            usage = event.get("usage") or {}
            totals["runs"] += 1
            totals["input_tokens"] += int(usage.get("inputTokens", 0))
            totals["output_tokens"] += int(usage.get("outputTokens", 0))
            totals["cache_read_tokens"] += int(usage.get("cacheReadTokens", 0))
            totals["seconds"] += float(event.get("duration_ms", 0)) / 1000
    return {"cursor": totals} if totals["runs"] else {}
