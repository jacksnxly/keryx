"""Offline tests: with `"order": "resets"` in config.json, keryx tries first the executor whose plan resets soonest,
so a quota that lapses at its reset is used up before one that keeps (owner, 2026-11-04: Cursor resets on 11-06,
GLM on 11-11, and every round that day still went to GLM). Off by default. Run: python3 -m unittest discover -s tests"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

UTC = timezone.utc
STAMP = "%Y-%m-%dT%H:%M:%SZ"
OWNER_RESETS = {"cli": {"next": "2026-11-06", "every": "month"},
                "glm": {"next": "2026-11-11T03:24:16Z", "every": "week"}}


def _config(d, **data):
    path = Path(d) / "config.json"
    path.write_text(json.dumps({"executors": ["glm", "cli", "subagent"], **data}))
    return {"KERYX_CONFIG": str(path)}


def _run(env, *argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = keryx.main(list(argv))
    return code, out.getvalue().split(), err.getvalue()


class TheNextReset(unittest.TestCase):
    def test_a_date_alone_is_midnight_utc_and_a_future_reset_is_kept(self):
        at = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
        self.assertEqual(keryx.next_reset({"next": "2026-11-06", "every": "month"}, at), "2026-11-06T00:00:00Z")
        self.assertEqual(keryx.next_reset({"next": "2026-11-06"}, at), "2026-11-06T00:00:00Z")

    def test_a_monthly_reset_rolls_on_from_its_first_date_and_clamps_to_the_months_end(self):
        spec = {"next": "2026-01-31T09:30:00Z", "every": "month"}
        self.assertEqual(keryx.next_reset(spec, datetime(2026, 2, 1, tzinfo=UTC)), "2026-02-28T09:30:00Z")
        self.assertEqual(keryx.next_reset(spec, datetime(2026, 3, 1, tzinfo=UTC)), "2026-03-31T09:30:00Z",
                         "each month is counted from the first date, not from the clamped one before it")
        self.assertEqual(keryx.next_reset(spec, datetime(2028, 2, 1, tzinfo=UTC)), "2028-02-29T09:30:00Z")
        self.assertEqual(keryx.next_reset({"next": "2026-11-06", "every": "month"},
                                          datetime(2026, 11, 6, 0, 0, 1, tzinfo=UTC)), "2026-12-06T00:00:00Z")

    def test_a_weekly_reset_rolls_on_by_seven_days_and_a_reset_at_this_moment_is_past(self):
        spec = {"next": "2026-11-11T03:24:16Z", "every": "week"}
        self.assertEqual(keryx.next_reset(spec, datetime(2026, 11, 11, 3, 24, 15, tzinfo=UTC)), "2026-11-11T03:24:16Z")
        self.assertEqual(keryx.next_reset(spec, datetime(2026, 11, 11, 3, 24, 16, tzinfo=UTC)), "2026-11-18T03:24:16Z")
        self.assertEqual(keryx.next_reset(spec, datetime(2026, 12, 1, tzinfo=UTC)), "2026-12-02T03:24:16Z")
        self.assertEqual(keryx.next_reset({"next": "2026-11-04T03:24:16Z", "every": "week"},
                                          datetime(2026, 11, 3, tzinfo=UTC)), "2026-11-04T03:24:16Z")

    def test_a_one_off_reset_that_has_passed_is_no_reset(self):
        self.assertIsNone(keryx.next_reset({"next": "2026-11-06"}, datetime(2026, 11, 7, tzinfo=UTC)))


class TheOrder(unittest.TestCase):
    def _order(self, at, **data):
        with tempfile.TemporaryDirectory() as d:
            return keryx.ordered_ladder(keryx.load_config(_config(d, **data)), at)

    def test_off_by_default_the_saved_order_stands_even_with_resets_saved(self):
        at = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
        self.assertEqual(self._order(at, resets=OWNER_RESETS), ["glm", "cli", "subagent"])
        self.assertEqual(self._order(at, order="ladder", resets=OWNER_RESETS), ["glm", "cli", "subagent"])

    def test_the_plan_that_resets_soonest_goes_first_and_the_order_follows_the_calendar(self):
        def order(*when):
            return self._order(datetime(*when, tzinfo=UTC), order="resets", resets=OWNER_RESETS)
        self.assertEqual(order(2026, 11, 4, 18, 0), ["cli", "glm", "subagent"], "Cursor lapses on 11-06, GLM on 11-11")
        self.assertEqual(order(2026, 11, 6, 0, 0, 1), ["glm", "cli", "subagent"], "after its reset Cursor keeps to 12-06")
        self.assertEqual(order(2026, 12, 1, 0, 0), ["glm", "cli", "subagent"], "GLM resets 12-02, Cursor 12-06")
        self.assertEqual(order(2026, 12, 2, 4, 0), ["cli", "glm", "subagent"], "GLM next resets 12-09, Cursor 12-06")

    def test_executors_without_a_reset_follow_in_the_saved_order_and_a_tie_keeps_it(self):
        at = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)
        got = self._order(at, executors=["subagent", "glm", "cloud", "cli"], order="resets",
                          resets={"cli": {"next": "2026-11-06"}, "glm": {"next": "2026-11-01"}})
        self.assertEqual(got, ["cli", "subagent", "glm", "cloud"], "glm's one-off reset has passed: no reset")
        tie = {"cli": {"next": "2026-11-06"}, "glm": {"next": "2026-11-06T00:00:00Z"}}
        self.assertEqual(self._order(at, order="resets", resets=tie), ["glm", "cli", "subagent"])

    def test_a_bad_setting_is_an_error_that_names_the_file(self):
        bad = [{"order": "fastest"},
               {"order": "resets", "resets": {"codex": {"next": "2026-11-06"}}},
               {"order": "resets", "resets": {"cli": {"next": "2026-11-06", "every": "fortnight"}}},
               {"order": "resets", "resets": {"cli": {"next": "6 Nov"}}},
               {"order": "resets", "resets": {"cli": "2026-11-06"}},
               {"order": "resets", "resets": ["cli"]}]
        for data in bad:
            with tempfile.TemporaryDirectory() as d:
                env = _config(d, **data)
                with self.assertRaises(keryx.LoopError, msg=str(data)) as caught:
                    keryx.load_config(env)
                self.assertIn(env["KERYX_CONFIG"], str(caught.exception))


class TheExecutorsCommand(unittest.TestCase):
    def test_executors_lists_the_soonest_reset_first_says_why_and_skips_a_limited_runner(self):
        now = datetime.now(UTC)
        soon, later = (now + timedelta(days=2)).strftime(STAMP), (now + timedelta(days=7)).strftime(STAMP)
        with tempfile.TemporaryDirectory() as d:
            env = _config(d, order="resets", resets={"cli": {"next": soon}, "glm": {"next": later}})
            code, ladder, err = _run(env, "executors")
            self.assertEqual((code, ladder), (0, ["cli", "glm", "subagent"]))
            self.assertIn("resets", err)
            self.assertIn(soon, err)
            self.assertIn(later, err)
            self.assertEqual(_run(env, "executors", "--after", "cli")[1], ["glm"])
            self.assertEqual(_run(env, "executors", "--after", "glm")[1], ["subagent"])
            keryx.record_limit(env, "cli", {"kind": "monthly", "resetsAt": later, "resetsIn": None}, now)
            self.assertEqual(_run(env, "executors")[1], ["glm", "subagent"], "a runner at its limit is still left out")
            self.assertEqual(_run(env, "executors", "--after", "glm")[1], ["subagent"])

    def test_with_the_mode_off_the_command_is_as_before(self):
        now = datetime.now(UTC)
        with tempfile.TemporaryDirectory() as d:
            env = _config(d, resets={"cli": {"next": (now + timedelta(days=2)).strftime(STAMP)}})
            self.assertEqual(_run(env, "executors"), (0, ["glm", "cli", "subagent"], ""))


class SetupSavesTheMode(unittest.TestCase):
    def test_setup_turns_the_mode_on_and_off_and_never_drops_the_other_settings(self):
        with tempfile.TemporaryDirectory() as d:
            env = _config(d)
            path = Path(env["KERYX_CONFIG"])
            code = _run(env, "setup", "--order", "resets", "--reset", "cli=2026-11-06/month",
                        "--reset", "glm=2026-11-11T03:24:16Z/week")[0]
            self.assertEqual(code, 0)
            saved = json.loads(path.read_text())
            self.assertEqual((saved["order"], saved["resets"], saved["executors"]),
                             ("resets", OWNER_RESETS, ["glm", "cli", "subagent"]))
            _run(env, "setup", "--executors", "cli,glm,subagent")
            saved = json.loads(path.read_text())
            self.assertEqual((saved["order"], saved["resets"], saved["executors"]),
                             ("resets", OWNER_RESETS, ["cli", "glm", "subagent"]), "a new ladder keeps the mode")
            _run(env, "setup", "--order", "ladder")
            saved = json.loads(path.read_text())
            self.assertEqual((saved["order"], saved["resets"]), ("ladder", OWNER_RESETS), "off keeps the dates")
            _run(env, "setup", "--reset", "glm=2026-11-20", "--reset", "cli=none")
            self.assertEqual(json.loads(path.read_text())["resets"], {"glm": {"next": "2026-11-20"}})
            code, words, _ = _run(env, "setup")
            self.assertEqual(code, 0)
            self.assertIn("order:", words)
            self.assertIn("ladder", words)

    def test_setup_refuses_a_bad_reset_and_leaves_the_file_as_it_was(self):
        with tempfile.TemporaryDirectory() as d:
            env = _config(d)
            before = Path(env["KERYX_CONFIG"]).read_text()
            for value in ("codex=2026-11-06", "cli=6 Nov", "cli=2026-11-06/fortnight", "cli"):
                code, _, err = _run(env, "setup", "--order", "resets", "--reset", value)
                self.assertEqual(code, 1, value)
                self.assertIn("keryx:", err, value)
            self.assertEqual(Path(env["KERYX_CONFIG"]).read_text(), before, "nothing is saved from a refused setup")
            with self.assertRaises(SystemExit) as refused:
                _run(env, "setup", "--order", "fastest")
            self.assertEqual(refused.exception.code, 2, "argparse refuses an unknown order")
            self.assertEqual(Path(env["KERYX_CONFIG"]).read_text(), before)


if __name__ == "__main__":
    unittest.main()
