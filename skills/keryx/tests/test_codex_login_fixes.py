"""Review fixes for the ChatGPT-login provider: a bare reset time is read against the moment the round wrote it,
an owner's Codex home is never written, only a ChatGPT login counts, and the executor's shells do not see the
login home."""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

CODEX_A = {"runner": "codex", "codexHome": "~/.config/keryx/codex/a", "model": "gpt-6.2-sol", "effort": "high"}
PRO = ("You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit "
       "https://chatgpt.com/settings/usage to purchase more credits")


class _Berlin(unittest.TestCase):
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


class BareTimeIsTheSameDay(_Berlin):
    def test_a_bare_time_read_after_it_passed_stays_on_that_day(self):
        late = dt.datetime(2026, 11, 18, 14, 45, 10, tzinfo=dt.timezone.utc)  # 15:45:10 in Berlin
        self.assertEqual(keryx.usage_limit(PRO + " or try again at 3:45 PM.", late)["resetsAt"],
                         "2026-11-18T14:45:00Z")

    def test_a_round_is_read_at_the_time_it_wrote_its_report(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "loops" / "s1"
            r = run / "rounds" / "01"
            r.mkdir(parents=True)
            (run / "agent.json").write_text(json.dumps({"runner": "codex-a", "runnerKind": "codex"}))
            (r / "result.md").write_text(PRO + " or try again at 11:50 PM.\n")
            written = dt.datetime(2026, 11, 10, 22, 40, tzinfo=dt.timezone.utc).timestamp()  # 23:40 in Berlin
            os.utime(r / "result.md", (written, written))
            self.assertEqual(keryx.round_usage_limit(r)["resetsAt"], "2026-11-10T22:50:00Z")


class OwnersHomeIsNeverWritten(unittest.TestCase):
    def test_a_home_with_files_but_no_config_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "acct"
            home.mkdir()
            (home / "auth.json").write_text("{}")
            with self.assertRaisesRegex(keryx.LoopError, str(home)):
                keryx.write_login_home({**CODEX_A, "codexHome": str(home)}, {"HOME": d})
            self.assertFalse((home / "config.toml").exists())

    def test_the_default_codex_home_is_refused_even_when_empty(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".codex").mkdir()
            with self.assertRaisesRegex(keryx.LoopError, ".codex"):
                keryx.write_login_home({**CODEX_A, "codexHome": "~/.codex"}, {"HOME": d})
            self.assertFalse((Path(d) / ".codex" / "config.toml").exists())

    def test_an_empty_folder_is_taken(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "acct"
            home.mkdir()
            keryx.write_login_home({**CODEX_A, "codexHome": str(home)}, {"HOME": d})
            self.assertTrue((home / "config.toml").read_text().startswith(keryx.LOGIN_HOME_MARK))

    def test_an_unreadable_config_or_a_file_in_the_way_is_a_loop_error(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "acct"
            home.mkdir()
            (home / "config.toml").write_bytes(b"\xff\xfe not text")
            with self.assertRaisesRegex(keryx.LoopError, str(home)):
                keryx.write_login_home({**CODEX_A, "codexHome": str(home)}, {"HOME": d})
            (Path(d) / "afile").write_text("x")
            with self.assertRaisesRegex(keryx.LoopError, "afile"):
                keryx.write_login_home({**CODEX_A, "codexHome": str(Path(d) / "afile")}, {"HOME": d})


class OnlyAChatGPTLoginCounts(unittest.TestCase):
    def _status(self, text, code=0):
        return mock.patch.object(keryx.subprocess, "run",
                                 return_value=subprocess.CompletedProcess(["codex"], code, text, ""))

    def test_an_api_key_login_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self._status("Logged in using an API key - sk-***\n"):
                with self.assertRaisesRegex(keryx.LoopError, "no ChatGPT login"):
                    keryx.codex_login_check("codex-a", CODEX_A, {"HOME": d})
            with self._status("Logged in using ChatGPT\n"):
                self.assertEqual(keryx.codex_login_check("codex-a", CODEX_A, {"HOME": d}),
                                 Path(d) / ".config" / "keryx" / "codex" / "a")


class ShellsDoNotSeeTheLoginHome(unittest.TestCase):
    def test_codex_home_is_kept_out_of_the_executors_shells(self):
        with tempfile.TemporaryDirectory() as d:
            home = keryx.write_login_home(CODEX_A, {"HOME": d})
            cfg = tomllib.loads((home / "config.toml").read_text())
            self.assertIn("CODEX_HOME", cfg["shell_environment_policy"]["exclude"])


if __name__ == "__main__":
    unittest.main()
