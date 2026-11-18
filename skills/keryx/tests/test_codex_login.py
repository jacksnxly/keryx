"""A Codex provider on a ChatGPT login: the provider names a Codex home where the owner ran `codex login`, keryx
owns that home's config.toml, no API key reaches Codex, and the ChatGPT plan's usage-limit message is read."""

import datetime as dt
import json
import os
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

CODEX_A = {"runner": "codex", "codexHome": "~/.config/keryx/codex/a", "model": "gpt-6.2-sol", "effort": "high"}
MISTRAL = {"runner": "codex", "baseUrl": "https://api.mistral.ai/v1", "keyFile": "~/.config/mistral/vibe.key",
           "model": "zai-glm-5-3", "effort": "high"}
AT = dt.datetime(2026, 11, 18, 10, 0, tzinfo=dt.timezone.utc)  # 11:00 in Berlin


def _config(d, data):
    p = Path(d) / "config.json"
    p.write_text(json.dumps(data))
    return {"KERYX_CONFIG": str(p), "HOME": d}


class LoginProviderConfig(unittest.TestCase):
    def test_a_login_provider_is_an_executor_without_a_key(self):
        with tempfile.TemporaryDirectory() as d:
            env = _config(d, {"executors": ["codex-a", "codex-b", "subagent"],
                              "providers": {"codex-a": CODEX_A,
                                            "codex-b": {**CODEX_A, "codexHome": "~/.config/keryx/codex/b"}}})
            cfg = keryx.load_config(env)
            self.assertEqual(cfg["executors"], ["codex-a", "codex-b", "subagent"])
            self.assertEqual(cfg["providers"]["codex-a"],
                             {"runner": "codex", "codexHome": "~/.config/keryx/codex/a", "model": "gpt-6.2-sol",
                              "effort": "high"})

    def test_a_provider_has_a_key_or_a_login_never_both_or_neither(self):
        bad = [
            {**CODEX_A, "baseUrl": "https://api.openai.com/v1"},
            {**CODEX_A, "keyFile": "~/.config/openai.key"},
            {k: v for k, v in CODEX_A.items() if k != "codexHome"},
            {**CODEX_A, "codexHome": ""},
            {**CODEX_A, "codexHome": 3},
        ]
        for spec in bad:
            with tempfile.TemporaryDirectory() as d:
                env = _config(d, {"executors": ["subagent"], "providers": {"codex-a": spec}})
                with self.assertRaises(keryx.LoopError, msg=json.dumps(spec)):
                    keryx.load_config(env)

    def test_a_key_provider_reads_as_before(self):
        with tempfile.TemporaryDirectory() as d:
            env = _config(d, {"executors": ["mistral-vibe"], "providers": {"mistral-vibe": MISTRAL}})
            self.assertEqual(keryx.load_config(env)["providers"]["mistral-vibe"], MISTRAL)


class LoginHome(unittest.TestCase):
    def test_the_home_is_read_against_the_runs_home(self):
        self.assertEqual(keryx.codex_login_home(CODEX_A, {"HOME": "/h"}), Path("/h/.config/keryx/codex/a"))
        self.assertEqual(keryx.codex_login_home({**CODEX_A, "codexHome": "/abs/b"}, {"HOME": "/h"}), Path("/abs/b"))

    def test_keryx_writes_the_homes_config(self):
        with tempfile.TemporaryDirectory() as d:
            provider = {**CODEX_A, "codexConfig": {"web_search": "disabled"}}
            home = keryx.write_login_home(provider, {"HOME": d})
            self.assertEqual(home, Path(d) / ".config" / "keryx" / "codex" / "a")
            self.assertEqual(home.stat().st_mode & 0o077, 0)
            text = (home / "config.toml").read_text()
            self.assertTrue(text.startswith(keryx.LOGIN_HOME_MARK + "\n"))
            cfg = tomllib.loads(text)
            self.assertEqual(cfg["model"], "gpt-6.2-sol")
            self.assertEqual(cfg["model_reasoning_effort"], "high")
            self.assertEqual(cfg["approval_policy"], "never")
            self.assertEqual(cfg["cli_auth_credentials_store"], "file")
            self.assertEqual(cfg["web_search"], "disabled")
            self.assertNotIn("model_provider", cfg)
            self.assertNotIn("model_providers", cfg)
            for feature in ("plugins", "remote_plugin", "apps", "memories"):
                self.assertIs(cfg["features"][feature], False, feature)

    def test_writing_again_takes_the_changed_provider_and_keeps_the_login(self):
        with tempfile.TemporaryDirectory() as d:
            home = keryx.write_login_home(CODEX_A, {"HOME": d})
            (home / "auth.json").write_text('{"auth_mode": "chatgpt"}')
            keryx.write_login_home({**CODEX_A, "model": "gpt-6.1-sol", "effort": "medium"}, {"HOME": d})
            cfg = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual((cfg["model"], cfg["model_reasoning_effort"]), ("gpt-6.1-sol", "medium"))
            self.assertEqual((home / "auth.json").read_text(), '{"auth_mode": "chatgpt"}')

    def test_a_config_keryx_did_not_write_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / ".codex"
            home.mkdir()
            (home / "config.toml").write_text('model = "gpt-6-astra"\n')
            with self.assertRaisesRegex(keryx.LoopError, str(home)):
                keryx.write_login_home({**CODEX_A, "codexHome": "~/.codex"}, {"HOME": d})
            self.assertEqual((home / "config.toml").read_text(), 'model = "gpt-6-astra"\n')


class LoginEnv(unittest.TestCase):
    def test_no_key_reaches_codex_and_gh_stays_in_the_run(self):
        base = {"PATH": "/usr/bin", "HOME": "/h", "OPENAI_API_KEY": "o", "CODEX_API_KEY": "c",
                "CODEX_HOME": "/elsewhere", "GH_TOKEN": "g"}
        env = keryx.codex_env(base, "/h/.config/keryx/codex/a", None, gh_dir="/repo/.keryx/codex/s1/gh")
        self.assertEqual(env["CODEX_HOME"], "/h/.config/keryx/codex/a")
        self.assertEqual(env["GH_CONFIG_DIR"], "/repo/.keryx/codex/s1/gh")
        for gone in ("OPENAI_API_KEY", "CODEX_API_KEY", keryx.CODEX_KEY_ENV):
            self.assertNotIn(gone, env)
        self.assertNotEqual(env["GH_TOKEN"], "g")
        self.assertEqual(env["GIT_SSH_COMMAND"], "false")

    def test_a_key_provider_env_is_unchanged(self):
        env = keryx.codex_env({"PATH": "/usr/bin", "HOME": "/h"}, "/run/codex-home", "k")
        self.assertEqual(env["GH_CONFIG_DIR"], "/run/codex-home/gh")
        self.assertEqual(env[keryx.CODEX_KEY_ENV], "k")


class ChatGPTUsageLimit(unittest.TestCase):
    def setUp(self):
        self._tz = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()

    def tearDown(self):
        if self._tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._tz
        time.tzset()

    PRO = ("You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
           "https://chatgpt.com/settings/usage to purchase more credits")

    def test_a_reset_on_another_day_is_read_in_local_time(self):
        self.assertEqual(keryx.usage_limit(self.PRO + " or try again at Nov 20th, 2026 3:45 PM.", AT),
                         {"kind": "plan", "resetsAt": "2026-11-20T14:45:00Z", "resetsIn": None})
        self.assertEqual(keryx.usage_limit(self.PRO + " or try again at Dec 1st, 2026 9:05 AM.", AT)["resetsAt"],
                         "2026-12-01T08:05:00Z")

    def test_a_reset_later_today_has_only_a_time(self):
        self.assertEqual(keryx.usage_limit(self.PRO + " or try again at 3:45 PM.", AT)["resetsAt"],
                         "2026-11-18T14:45:00Z")
        text = "You’ve hit your usage limit for GPT-6.2 Sol. Switch to another model now, or try again at 9:05 PM."
        self.assertEqual(keryx.usage_limit(text, AT)["resetsAt"], "2026-11-18T20:05:00Z")
        self.assertEqual(keryx.usage_limit("You've hit your usage limit. Try again at 11:30 PM.", AT)["resetsAt"],
                         "2026-11-18T22:30:00Z")

    def test_no_time_given_waits_five_hours(self):
        self.assertEqual(keryx.usage_limit(self.PRO + " or try again later.", AT),
                         {"kind": "plan", "resetsAt": None, "resetsIn": "5 hours"})

    def test_only_a_codex_rounds_report_counts(self):
        self.assertIsNone(keryx.usage_limit(self.PRO + " or try again at 3:45 PM.", AT, codex=False))

    def test_the_limit_reaches_the_round_result(self):
        events = [{"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"},
                  {"type": "error", "message": self.PRO + " or try again at Nov 20th, 2026 3:45 PM."},
                  {"type": "turn.failed", "error": {"message": self.PRO + " or try again at Nov 20th, 2026 3:45 PM."}}]
        out = keryx.codex_outcome(events, 1)
        self.assertEqual(out["status"], "ERROR")
        self.assertEqual(keryx.usage_limit(out["result"], AT)["resetsAt"], "2026-11-20T14:45:00Z")


if __name__ == "__main__":
    unittest.main()
