"""Review fixes for Part 1 of the executor budget: a failed meter read is cached too, a login Codex says is blocked
shows nothing left, a cached meter belongs to the login home it was read from, and setup prints the budget."""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

AT = dt.datetime(2026, 11, 18, 0, 30, tzinfo=dt.timezone.utc)
CODEX_A = {"runner": "codex", "codexHome": "~/.config/keryx/codex/a", "model": "gpt-6.2-sol", "effort": "high"}
METER = {"plan": "plus", "reached": None, "credits": [],
         "windows": [{"minutes": 300, "usedPercent": 40, "resetsAt": "2026-11-18T03:56:13Z"},
                     {"minutes": 10080, "usedPercent": 10, "resetsAt": "2026-11-24T23:30:42Z"}]}


def _env(d):
    return {"KERYX_CONFIG": str(Path(d) / "cfg" / "config.json"), "HOME": d}


def _config():
    return {"executors": ["codex-a", "subagent"], "order": "ladder", "budget": True, "resets": {},
            "providers": {"codex-a": CODEX_A}, "maxParallel": {}, "roots": [], "research": None}


class FailedReadIsCached(unittest.TestCase):
    def test_a_failed_read_is_not_retried_within_max_age(self):
        with tempfile.TemporaryDirectory() as d:
            env = _env(d)
            Path(env["KERYX_CONFIG"]).parent.mkdir()
            with mock.patch.object(keryx, "read_codex_meter", return_value=None) as read:
                self.assertEqual(keryx.codex_meters(_config(), env, AT), {"codex-a": None})
                self.assertEqual(keryx.codex_meters(_config(), env, AT + dt.timedelta(minutes=5)), {"codex-a": None})
                self.assertEqual(read.call_count, 1)
                keryx.codex_meters(_config(), env, AT + dt.timedelta(minutes=11))
                self.assertEqual(read.call_count, 2)

    def test_budget_reads_fresh_even_after_a_failed_read(self):
        with tempfile.TemporaryDirectory() as d:
            env = _env(d)
            Path(env["KERYX_CONFIG"]).parent.mkdir()
            with mock.patch.object(keryx, "read_codex_meter", return_value=None) as read:
                keryx.codex_meters(_config(), env, AT)
                keryx.codex_meters(_config(), env, AT, max_age=0)
                self.assertEqual(read.call_count, 2)


class CacheBelongsToItsHome(unittest.TestCase):
    def test_a_changed_login_home_is_read_again(self):
        with tempfile.TemporaryDirectory() as d:
            env = _env(d)
            Path(env["KERYX_CONFIG"]).parent.mkdir()
            with mock.patch.object(keryx, "read_codex_meter", return_value=METER) as read:
                keryx.codex_meters(_config(), env, AT)
                moved = _config()
                moved["providers"] = {"codex-a": {**CODEX_A, "codexHome": "~/.config/keryx/codex/other"}}
                keryx.codex_meters(moved, env, AT + dt.timedelta(minutes=1))
                self.assertEqual(read.call_count, 2)
                keryx.codex_meters(moved, env, AT + dt.timedelta(minutes=2))
                self.assertEqual(read.call_count, 2)


class BlockedLoginShowsNothingLeft(unittest.TestCase):
    def test_a_reached_limit_with_room_in_every_window_is_zero_left(self):
        blocked = {**METER, "reached": "workspace_owner_usage_limit_reached"}
        self.assertEqual(keryx.executor_left("codex-a", _config(), {}, AT, {"codex-a": blocked}),
                         {"name": "codex-a", "plan": "plus", "left": 0, "until": None, "source": "meter"})

    def test_no_reached_limit_keeps_the_tightest_window(self):
        self.assertEqual(keryx.executor_left("codex-a", _config(), {}, AT, {"codex-a": METER})["left"], 60)


class SetupPrintsTheBudget(unittest.TestCase):
    def test_setup_without_arguments_says_whether_the_budget_is_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            on = machine(tmp, budget=True)
            code, out, _ = cli(repo, ["setup"], on)
            self.assertEqual(code, 0)
            self.assertRegex(out, r"(?m)^budget: on$")
            off = machine(tmp)
            code, out, _ = cli(repo, ["setup"], off)
            self.assertRegex(out, r"(?m)^budget: off$")


if __name__ == "__main__":
    unittest.main()
