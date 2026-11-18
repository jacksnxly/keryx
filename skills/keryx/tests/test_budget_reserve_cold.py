"""A round on a metered login reserves even before any estimate exists, so two first rounds see each other."""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402


class ColdStartReservation(unittest.TestCase):
    def test_two_rounds_without_an_estimate_see_each_other(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "cfg" / "config.json"
            cfg.parent.mkdir()
            cfg.write_text(json.dumps({"executors": ["codex-a"], "budget": True,
                                       "providers": {"codex-a": {"runner": "codex", "model": "m",
                                                                 "codexHome": "~/x/a"}}}))
            env = {"KERYX_CONFIG": str(cfg), "HOME": d}
            first, second = Path(d) / "runs" / "one", Path(d) / "runs" / "two"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            keryx._reserve_round(first, "codex-a", "Mode: IMPLEMENT\n", env)
            keryx._reserve_round(second, "codex-a", "Mode: IMPLEMENT\n", env)
            now = dt.datetime.now(dt.timezone.utc)
            self.assertTrue(keryx.overlapped(env, "codex-a", "one", now))
            self.assertTrue(keryx.overlapped(env, "codex-a", "two", now))
            self.assertEqual(keryx.reserved(env, now), {})


if __name__ == "__main__":
    unittest.main()
