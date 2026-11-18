"""Part 1 of the executor budget: each executor's meter (Codex logins read exactly through `codex app-server`), what
is left per executor, the opt-in Executors row in the status block, and `keryx.py budget`."""

import datetime as dt
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

AT = dt.datetime(2026, 11, 18, 0, 30, tzinfo=dt.timezone.utc)  # 01:30 in Berlin
R5 = 1794974173   # 2026-11-18T03:56:13Z
R7 = 1795563042   # 2026-11-24T23:30:42Z
EXPIRES = 1796066025  # 2026-11-30T19:13:45Z
RESULT = {  # account/rateLimits/read, as codex-cli 0.169.0 answered it (ids replaced)
    "ordinaryUsageAllowed": True,
    "rateLimits": {
        "limitId": "codex", "limitName": None, "normalModelSlug": None,
        "primary": {"usedPercent": 100, "windowDurationMins": 300, "resetsAt": R5},
        "secondary": {"usedPercent": 32, "windowDurationMins": 10080, "resetsAt": R7},
        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        "individualLimit": None, "spendControlReached": False, "planType": "team",
        "rateLimitReachedType": "workspace_member_credits_depleted",
    },
    "rateLimitResetCredits": {"availableCount": 1, "credits": [
        {"id": "credit-1", "resetType": "codexRateLimits", "status": "available", "grantedAt": 1793474025,
         "expiresAt": EXPIRES, "title": "Full reset (Weekly + 5 hr)", "description": "x"}]},
    "accountId": "account-1",
}
CODEX_A = {"runner": "codex", "codexHome": "~/.config/keryx/codex/a", "model": "gpt-6.2-sol", "effort": "high"}


def meter(used5, used7, plan="plus"):
    return {"plan": plan, "reached": None, "credits": [],
            "windows": [{"minutes": 300, "usedPercent": used5, "resetsAt": "2026-11-18T03:56:13Z"},
                        {"minutes": 10080, "usedPercent": used7, "resetsAt": "2026-11-24T23:30:42Z"}]}


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


class CodexMeter(unittest.TestCase):
    def test_the_answer_reads_as_plan_windows_credits(self):
        self.assertEqual(keryx.parse_codex_meter(RESULT), {
            "plan": "team", "reached": "workspace_member_credits_depleted",
            "windows": [{"minutes": 300, "usedPercent": 100, "resetsAt": "2026-11-18T03:56:13Z"},
                        {"minutes": 10080, "usedPercent": 32, "resetsAt": "2026-11-24T23:30:42Z"}],
            "credits": [{"id": "credit-1", "status": "available", "expiresAt": "2026-11-30T19:13:45Z"}]})

    def test_missing_parts_read_as_nothing(self):
        self.assertEqual(keryx.parse_codex_meter({"rateLimits": {"primary": None, "secondary": None}}),
                         {"plan": None, "reached": None, "windows": [], "credits": []})
        self.assertIsNone(keryx.parse_codex_meter({}))
        self.assertIsNone(keryx.parse_codex_meter("nope"))

    def _fake_codex(self, d, answer=True):
        bin_dir = Path(d) / "bin"
        bin_dir.mkdir()
        log = Path(d) / "calls.txt"
        script = bin_dir / "codex"
        script.write_text(f"""#!{sys.executable}
import json, os, sys, time
open({str(log)!r}, "a").write(" ".join(sys.argv[1:]) + "|" + os.environ.get("CODEX_HOME", "") + "|" +
                              str("OPENAI_API_KEY" in os.environ) + "\\n")
for line in sys.stdin:
    m = json.loads(line)
    if {not answer!r}:
        time.sleep(30)
    if m.get("method") == "initialize":
        print(json.dumps({{"id": m["id"], "result": {{"userAgent": "x"}}}}), flush=True)
    elif m.get("method") == "account/rateLimits/read":
        print(json.dumps({{"id": m["id"], "result": json.loads({json.dumps(RESULT)!r})}}), flush=True)
""")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", "HOME": d, "OPENAI_API_KEY": "o"}, log

    def test_the_meter_is_read_through_the_logins_own_home(self):
        with tempfile.TemporaryDirectory() as d:
            env, log = self._fake_codex(d)
            home = Path(d) / "acct"
            home.mkdir()
            got = keryx.read_codex_meter(home, env, timeout=10)
            self.assertEqual(got["plan"], "team")
            self.assertEqual(got["windows"][0]["usedPercent"], 100)
            self.assertEqual(log.read_text().strip(), f"app-server|{home}|False")

    def test_a_meter_that_does_not_answer_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            env, _ = self._fake_codex(d, answer=False)
            started = time.monotonic()
            self.assertIsNone(keryx.read_codex_meter(Path(d), env, timeout=2))
            self.assertLess(time.monotonic() - started, 10)
        self.assertIsNone(keryx.read_codex_meter(Path("/no-such-root-keryx"), {"PATH": "/no-such-root-keryx"},
                                                 timeout=2))

    def test_an_exhausted_window_is_the_limit_with_its_reset(self):
        self.assertEqual(keryx.limit_from_meter(keryx.parse_codex_meter(RESULT)),
                         {"kind": "5 hour", "resetsAt": "2026-11-18T03:56:13Z", "resetsIn": None})
        both = meter(100, 100)
        self.assertEqual(keryx.limit_from_meter(both),
                         {"kind": "weekly", "resetsAt": "2026-11-24T23:30:42Z", "resetsIn": None})
        self.assertIsNone(keryx.limit_from_meter(meter(99, 50)))
        self.assertIsNone(keryx.limit_from_meter(None))


class WhatIsLeft(unittest.TestCase):
    CONFIG = {"executors": ["codex-a", "cli", "subagent"], "providers": {"codex-a": CODEX_A}}

    def test_a_metered_login_shows_the_tightest_window(self):
        self.assertEqual(keryx.executor_left("codex-a", self.CONFIG, {}, AT, {"codex-a": meter(100, 32)}),
                         {"name": "codex-a", "plan": "plus", "left": 0, "until": "2026-11-18T03:56:13Z",
                          "source": "meter"})
        self.assertEqual(keryx.executor_left("codex-a", self.CONFIG, {}, AT, {"codex-a": meter(40, 90)}),
                         {"name": "codex-a", "plan": "plus", "left": 10, "until": None, "source": "meter"})

    def test_without_a_meter_a_recorded_limit_says_it_ran_out(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json")}
            keryx.record_limit(env, "codex-a", {"kind": "plan", "resetsAt": "2026-11-18T03:56:13Z"}, AT)
            keryx.record_limit(env, "cli", {"kind": "weekly", "resetsAt": "2026-11-20T20:13:53Z"}, AT)
            self.assertEqual(keryx.executor_left("codex-a", self.CONFIG, env, AT, {"codex-a": None}),
                             {"name": "codex-a", "plan": None, "left": 0, "until": "2026-11-18T03:56:13Z",
                              "source": "limit"})
            self.assertEqual(keryx.executor_left("cli", self.CONFIG, env, AT, {}),
                             {"name": "cli", "plan": None, "left": 0, "until": "2026-11-20T20:13:53Z",
                              "source": "limit"})
            self.assertEqual(keryx.executor_left("subagent", self.CONFIG, env, AT, {}),
                             {"name": "subagent", "plan": None, "left": None, "until": None, "source": "none"})


class ExecutorsCell(_Berlin):
    def test_one_entry_per_executor_in_ladder_order(self):
        entries = [
            {"name": "codex-a", "plan": "plus", "left": 100, "until": None, "source": "meter"},
            {"name": "codex-b", "plan": "team", "left": 0, "until": "2026-11-18T03:56:13Z", "source": "meter"},
            {"name": "cli", "plan": None, "left": 0, "until": "2026-11-20T20:13:53Z", "source": "limit"},
            {"name": "mistral-vibe", "plan": None, "left": None, "until": None, "source": "none"},
        ]
        self.assertEqual(keryx.executors_cell(entries, AT),
                         "codex-a 100% · codex-b 0% → 04:56 · cli 0% → 11-20 · mistral-vibe")

    def test_a_long_row_folds_into_a_count(self):
        entries = [{"name": f"provider-{i:02d}", "plan": None, "left": 50, "until": None, "source": "meter"}
                   for i in range(12)]
        cell = keryx.executors_cell(entries, AT)
        self.assertLessEqual(keryx._shown_width(cell), keryx.ROW_WIDTH)
        self.assertRegex(cell, r"· \+\d+ more$")


class BudgetIsOptIn(unittest.TestCase):
    def test_setup_turns_the_budget_on_and_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = machine(tmp)
            repo = _two_commit_repo(tmp)[0]
            self.assertEqual(cli(repo, ["setup", "--budget", "on"], env)[0], 0)
            self.assertIs(json.loads(Path(env["KERYX_CONFIG"]).read_text())["budget"], True)
            self.assertEqual(cli(repo, ["setup", "--budget", "off"], env)[0], 0)
            self.assertIs(json.loads(Path(env["KERYX_CONFIG"]).read_text())["budget"], False)

    def test_the_status_block_shows_the_executors_only_when_the_budget_is_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            off = machine(tmp)
            code, out, _ = cli(repo, ["progress", "--live", "x", "--next", "y"], off)
            self.assertEqual(code, 0)
            self.assertNotIn("Executors", out)
            on = machine(tmp, budget=True)
            now = dt.datetime.now(dt.timezone.utc)
            keryx.record_limit(on, "cli", {"kind": "weekly", "resetsAt": keryx._stamp(now + dt.timedelta(days=3))},
                               now - dt.timedelta(minutes=1))
            code, out, _ = cli(repo, ["progress", "--live", "x", "--next", "y"], on)
            self.assertEqual(code, 0)
            self.assertRegex(out, r"\| \*\*Executors\*\* \| cli 0% → \d\d-\d\d · subagent \|")

    def test_budget_prints_one_line_per_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, budget=True)
            code, out, _ = cli(repo, ["budget", "--json"], env)
            self.assertEqual(code, 0)
            self.assertEqual([e["name"] for e in json.loads(out)], ["cli", "subagent"])
            code, out, _ = cli(repo, ["budget"], env)
            self.assertEqual(code, 0)
            self.assertEqual([line.split()[0] for line in out.strip().splitlines()[1:]], ["cli", "subagent"])


if __name__ == "__main__":
    unittest.main()
