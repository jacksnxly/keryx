"""Offline test from the coordinator's check of round 01: a reset saved further ahead than one period is the next
reset as given, never a date before it. Run: python3 -m unittest discover -s tests"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

AT = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)


class ASavedNextResetIsNeverMovedEarlier(unittest.TestCase):
    def test_a_weekly_reset_three_weeks_ahead_is_that_date(self):
        """Round 01 counted whole weeks back from `next` and answered 2026-11-11 for a reset saved as 11-25."""
        self.assertEqual(keryx.next_reset({"next": "2026-11-25T00:00:00Z", "every": "week"}, AT), "2026-11-25T00:00:00Z")
        self.assertEqual(keryx.next_reset({"next": "2026-11-12", "every": "week"}, AT), "2026-11-12T00:00:00Z")

    def test_a_monthly_reset_months_ahead_is_that_date(self):
        self.assertEqual(keryx.next_reset({"next": "2027-01-06", "every": "month"}, AT), "2027-01-06T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
