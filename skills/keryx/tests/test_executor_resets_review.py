"""Offline tests from the fresh reviews of 0371401..6906ba8 and 6906ba8..57f7f89: setup never saves a ladder nobody
chose; a broken config is still replaced by a new ladder as in 1.4.0, but kept beside it; the reset dates cannot break
the saved order while the mode is off, and the off switch works even when a date is bad; other keys survive setup; the
reason line is exact. Run: python3 -m unittest discover -s tests"""

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


def _run(path, *argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {"KERYX_CONFIG": str(path)}), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = keryx.main(list(argv))
    return code, out.getvalue().split(), err.getvalue()


class SetupNeverSavesALadderNobodyChose(unittest.TestCase):
    def test_order_or_reset_alone_on_a_new_machine_is_refused_and_the_first_use_note_stays(self):
        """Opus review P2: `setup --order resets` on a new machine saved the subagent alone, and the setup note that
        makes keryx ask the owner for the executors went quiet."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            for argv in (("--order", "resets"), ("--reset", "cli=2026-11-06/month")):
                code, _, err = _run(path, "setup", *argv)
                self.assertEqual(code, 1, argv)
                self.assertIn("--executors", err, argv)
                self.assertFalse(path.exists(), argv)
            self.assertIn("not set up", _run(path, "executors")[2])
            code = _run(path, "setup", "--executors", "glm,cli,subagent", "--order", "resets",
                        "--reset", "cli=2026-11-06/month")[0]
            self.assertEqual(code, 0, "with the ladder in the same call it is saved")
            saved = json.loads(path.read_text())
            self.assertEqual((saved["executors"], saved["order"], saved["resets"]),
                             (["glm", "cli", "subagent"], "resets", {"cli": {"next": "2026-11-06", "every": "month"}}))

    def test_a_new_ladder_still_replaces_a_config_that_is_not_json_and_nothing_else_does(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text("{not json")
            code, _, err = _run(path, "setup", "--order", "resets")
            self.assertEqual(code, 1)
            self.assertIn("not valid JSON", err, "the refusal says what is wrong with the file")
            self.assertEqual(path.read_text(), "{not json")
            code, _, err = _run(path, "setup", "--executors", "cli")
            self.assertEqual(code, 0, "1.4.0 replaced it; so does 1.5")
            self.assertEqual(json.loads(path.read_text())["executors"], ["cli"])
            kept = path.with_name("config.json.broken")
            self.assertEqual(kept.read_text(), "{not json", "the broken file is kept beside the new one")
            self.assertIn(str(kept), err, "and setup says where")


class TheModeOffIgnoresTheDates(unittest.TestCase):
    def test_a_bad_reset_never_breaks_the_saved_order_while_the_mode_is_off(self):
        """Security review P3: with the order `ladder`, a malformed `resets` made `keryx.py executors` exit 1."""
        for extra in ({}, {"order": "ladder"}):
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "config.json"
                path.write_text(json.dumps({"executors": ["glm", "cli"], "resets": {"cli": {"next": "bad"}}, **extra}))
                self.assertEqual(_run(path, "executors"), (0, ["glm", "cli"], ""), extra)
                self.assertEqual(_run(path, "setup", "--executors", "cli,glm")[0], 0, "off, the dates do not block")
                saved = json.loads(path.read_text())
                self.assertEqual((saved["executors"], saved["resets"]), (["cli", "glm"], {"cli": {"next": "bad"}}))
                before = path.read_text()
                code, _, err = _run(path, "setup", "--order", "resets")
                self.assertEqual(code, 1, "turning the mode on with a bad date is refused")
                self.assertIn("reset for cli", err)
                self.assertEqual(path.read_text(), before)

    def test_the_off_switch_works_when_a_bad_date_stops_the_reset_order(self):
        """Opus review of 57f7f89: with the mode on and a hand-broken date every `executors` call failed, and
        `setup --order ladder`, the documented way out, was refused as well."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"executors": ["glm", "cli"], "order": "resets", "resets": {"cli": {"next": "bad"}}}))
            self.assertEqual(_run(path, "executors")[0], 1, "on, a bad date is an error, not a silent order")
            self.assertEqual(_run(path, "setup", "--order", "ladder")[0], 0)
            self.assertEqual(_run(path, "executors"), (0, ["glm", "cli"], ""))


class SetupKeepsWhatItDoesNotKnow(unittest.TestCase):
    def test_unknown_keys_survive_every_kind_of_setup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"executors": ["glm", "cli"], "note": "kept", "nested": {"a": [1, 2]}}))
            for argv in (("--executors", "cli,glm"), ("--order", "resets"), ("--reset", "glm=2026-11-11/week"),
                         ("--order", "ladder")):
                self.assertEqual(_run(path, "setup", *argv)[0], 0, argv)
                saved = json.loads(path.read_text())
                self.assertEqual((saved["note"], saved["nested"]), ("kept", {"a": [1, 2]}), argv)


class TheReasonLine(unittest.TestCase):
    def test_executors_prints_one_exact_reason_line_in_the_reset_order(self):
        now = datetime.now(timezone.utc)
        soon = (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        later = (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"executors": ["glm", "cli", "subagent"], "order": "resets",
                                        "resets": {"cli": {"next": soon}, "glm": {"next": later}}}))
            self.assertEqual(_run(path, "executors")[2],
                             f"order: resets, soonest first: cli resets {soon}, glm resets {later}, subagent no reset\n")


if __name__ == "__main__":
    unittest.main()
