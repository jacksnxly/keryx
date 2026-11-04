"""Offline tests from the coordinator's mutation probes of round 01: `setup` checks the whole result before it writes,
so a hand-edited bad setting it did not touch still stops the write; and a monthly reset at this very moment has
passed, as a weekly one does. Run: python3 -m unittest discover -s tests"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402


class SetupChecksTheWholeFileFirst(unittest.TestCase):
    def test_a_bad_saved_reset_stops_a_new_ladder_and_the_file_is_left_as_it_was(self):
        """The probe that saved before checking survived the first tests: every value they refused failed earlier."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"executors": ["glm", "cli"], "order": "resets",
                                        "resets": {"cli": {"next": "6 Nov"}}, "note": "kept"}))
            before = path.read_text()
            err = io.StringIO()
            with mock.patch.dict(os.environ, {"KERYX_CONFIG": str(path)}), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = keryx.main(["setup", "--executors", "cli,glm"])
            self.assertEqual(code, 1)
            self.assertIn("reset for cli", err.getvalue())
            self.assertEqual(path.read_text(), before, "nothing is written when the result is refused")


class AResetAtThisMomentHasPassed(unittest.TestCase):
    def test_a_monthly_reset_at_this_very_second_is_counted_as_past(self):
        at = datetime(2026, 11, 6, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(keryx.next_reset({"next": "2026-10-06", "every": "month"}, at), "2026-12-06T00:00:00Z")
        self.assertIsNone(keryx.next_reset({"next": "2026-11-06"}, at), "a one-off at this second has passed")


if __name__ == "__main__":
    unittest.main()
