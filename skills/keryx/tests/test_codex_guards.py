"""A codex round that was cancelled keeps its last report; gh sees a placeholder token; --env cannot undo the guards."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

START = [{"type": "thread.started", "thread_id": "01a1-thread"}, {"type": "turn.started"}]
SAID = {"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": "Status: BLOCKED\nhalfway"}}
RETRY = {"type": "error", "message": "Reconnecting... 1/5 (stream disconnected)"}


class CancelledRoundKeepsItsReport(unittest.TestCase):
    def test_a_cancelled_or_stopped_round_reports_its_last_message(self):
        for code in (130, 137, 143, -15):
            out = keryx.codex_outcome(START + [SAID, RETRY], code)
            self.assertEqual(out["status"], "CANCELLED", code)
            self.assertEqual(out["result"], "Status: BLOCKED\nhalfway", code)

    def test_a_failed_turn_still_reports_its_error(self):
        failed = {"type": "turn.failed", "error": {"message": "unexpected status 402 Payment Required: {}"}}
        self.assertIn("402", keryx.codex_outcome(START + [SAID, failed], 1)["result"])


class GuardsHold(unittest.TestCase):
    def test_gh_gets_a_placeholder_token(self):
        env = keryx.codex_env({"PATH": "/usr/bin", "HOME": "/no-such-root-keryx", "GH_TOKEN": "real"}, "/run/codex-home", "k")
        self.assertEqual(env["GH_TOKEN"], "keryx-provider-round-has-no-github-access")
        self.assertNotIn("GITHUB_TOKEN", env)

    def test_env_cannot_undo_the_guards(self):
        for pair in ("GH_CONFIG_DIR=/x", "GH_TOKEN=y", "GITHUB_TOKEN=y", "GIT_SSH_COMMAND=ssh", "GIT_TERMINAL_PROMPT=1",
                     "GIT_ASKPASS=/x", "SSH_ASKPASS=/x"):
            with self.assertRaises(keryx.LoopError, msg=pair):
                keryx.parse_env([pair])


if __name__ == "__main__":
    unittest.main()
