"""A ChatGPT workspace without credit, or at its spend cap, is a limit on that rung: Codex prints no reset time, so
keryx looks again a day later."""

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

AT = dt.datetime(2026, 11, 18, 10, 0, tzinfo=dt.timezone.utc)
WORKSPACE = (  # codex-rs 0.169.0 protocol/src/error.rs, RateLimitReachedType::Workspace*
    "Your workspace is out of credits. Add credits to continue.",
    "Your workspace is out of credits. Ask your workspace owner to refill in order to continue.",
    "You hit your spend cap set in your workspace. Increase your spend cap to continue.",
    "You hit your spend cap set by the owner of your workspace. Ask an owner to increase your spend cap to continue.",
)


class WorkspaceLimit(unittest.TestCase):
    def test_each_workspace_message_is_a_day_long_limit(self):
        for text in WORKSPACE:
            self.assertEqual(keryx.usage_limit("ERROR: " + text, AT),
                             {"kind": "workspace", "resetsAt": None, "resetsIn": "1 day"}, text)

    def test_only_a_codex_rounds_report_counts(self):
        for text in WORKSPACE:
            self.assertIsNone(keryx.usage_limit(text, AT, codex=False), text)

    def test_the_limit_reaches_the_round_result_and_the_record(self):
        events = [{"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"},
                  {"type": "turn.failed", "error": {"message": WORKSPACE[1]}}]
        limit = keryx.usage_limit(keryx.codex_outcome(events, 1)["result"], AT)
        self.assertEqual(keryx._until_from_limit(limit, AT), "2026-11-19T10:00:00Z")


if __name__ == "__main__":
    unittest.main()
