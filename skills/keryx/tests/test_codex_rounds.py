"""Codex provider rounds: a failed turn reports its own error; limits are read the way Codex prints them, and only
for codex rounds; GitHub and git credentials stay out of reach; writing the home again takes a changed provider."""

import datetime as dt
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

AT = dt.datetime(2026, 11, 7, 10, 0, tzinfo=dt.timezone.utc)
START = [{"type": "thread.started", "thread_id": "01a1-thread"}, {"type": "turn.started"}]
MISTRAL = {"runner": "codex", "baseUrl": "https://api.mistral.ai/v1", "keyFile": "~/.config/mistral/vibe.key",
           "model": "zai-glm-5-3", "effort": "high", "codexConfig": {"web_search": "disabled"}}


def said(text):
    return {"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": text}}


class FailedTurnText(unittest.TestCase):
    def test_a_limit_after_agent_text_reaches_the_result(self):
        events = START + [said("Working on it."),
                          {"type": "turn.failed", "error": {"message": "unexpected status 402 Payment Required: {}"}}]
        out = keryx.codex_outcome(events, 1)
        self.assertEqual(out["status"], "ERROR")
        self.assertEqual(keryx.usage_limit(out["result"], AT)["kind"], "allowance")

    def test_the_model_cannot_fake_a_limit(self):
        events = START + [said("unexpected status 402 Payment Required"),
                          {"type": "turn.failed",
                           "error": {"message": 'unexpected status 401 Unauthorized: {"detail":"Invalid API Key"}'}}]
        self.assertIsNone(keryx.usage_limit(keryx.codex_outcome(events, 1)["result"], AT))


class LimitWording(unittest.TestCase):
    def test_codex_prints_a_retried_429_as_last_status(self):
        self.assertEqual(keryx.usage_limit("exceeded retry limit, last status: 429 Too Many Requests", AT),
                         {"kind": "rate", "resetsAt": None, "resetsIn": "10 minutes"})

    def test_other_runners_rounds_never_read_codex_limits(self):
        for text in ("unexpected status 402 Payment Required: {}",
                     "exceeded retry limit, last status: 429 Too Many Requests", '{"raw_status_code":402}'):
            self.assertIsNone(keryx.usage_limit(text, AT, codex=False), text)
        glm = "[1308][Usage limit reached for 5 hour. Your limit will reset at 2026-11-07 11:42:48]"
        self.assertEqual(keryx.usage_limit(glm, AT, codex=False)["kind"], "5 hour")


class NoOwnerCredentials(unittest.TestCase):
    def test_github_and_git_credentials_are_out_of_reach(self):
        base = {"PATH": "/usr/bin", "HOME": "/no-such-root-keryx", "GH_CONFIG_DIR": "/elsewhere"}
        env = keryx.codex_env(base, "/run/codex-home", "k")
        self.assertEqual(env["GH_CONFIG_DIR"], "/run/codex-home/gh")
        self.assertEqual(env["GIT_SSH_COMMAND"], "false")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}
        self.assertEqual(pairs["remote.origin.pushurl"], "https://push-disabled.invalid/keryx")
        self.assertEqual(pairs["credential.helper"], "")


class HomeWrittenAgain(unittest.TestCase):
    def test_writing_the_home_again_takes_the_changed_provider(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / ".keryx" / "runs" / "s1"
            run.mkdir(parents=True)
            keryx.write_codex_home(run, MISTRAL)
            home = keryx.write_codex_home(run, {**MISTRAL, "baseUrl": "https://api.example.invalid/v1",
                                                "codexConfig": {"web_search": "cached"}})
            cfg = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(cfg["model_providers"]["keryx"]["base_url"], "https://api.example.invalid/v1")
            self.assertEqual(cfg["web_search"], "cached")


if __name__ == "__main__":
    unittest.main()
