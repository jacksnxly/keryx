"""Review fixes for Part 2: minutes from the round's own times, one ledger line per round, only finished rounds teach
the estimate, and a slice takes its size only from the run that names it."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402


def _budget_env(d):
    cfg = Path(d) / "cfg" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"executors": ["cli", "subagent"], "budget": True}))
    return {"KERYX_CONFIG": str(cfg)}


def _round(d, slug="part-cost"):
    run = Path(d) / "runs" / slug
    r = run / "rounds" / "01"
    r.mkdir(parents=True)
    (r / "prompt.md").write_text("Mode: IMPLEMENT\n")
    return run, r


HEADER = "ts\tphase\tdecision\twhy\tevidence\tresult\n"
RUN = {"status": "FINISHED", "durationMs": None, "startedAt": "2026-11-18T01:30:44Z", "endedAt": "2026-11-18T01:44:14Z"}


class Minutes(unittest.TestCase):
    def test_minutes_come_from_the_rounds_own_times(self):
        self.assertEqual(keryx.round_minutes(RUN), 13.5)
        self.assertEqual(keryx.round_minutes({**RUN, "durationMs": 120000}), 2.0)
        self.assertEqual(keryx.round_minutes({"durationMs": None}), 0.0)


class OneLinePerRound(unittest.TestCase):
    def test_a_second_wait_records_nothing_more(self):
        with tempfile.TemporaryDirectory() as d:
            env = _budget_env(d)
            run, r = _round(d)
            keryx._record_round_cost(run, {"runner": "cli"}, r, RUN, [], env)
            keryx._record_round_cost(run, {"runner": "cli"}, r, RUN, [], env)
            samples = keryx.cost_samples(env)
            self.assertEqual(len(samples), 1)
            self.assertEqual((samples[0]["status"], samples[0]["minutes"], samples[0]["mode"]),
                             ("FINISHED", 13.5, "IMPLEMENT"))
            self.assertTrue((r / "cost.json").exists())


class OnlyFinishedRoundsTeach(unittest.TestCase):
    def test_a_round_that_did_not_finish_is_no_sample(self):
        rows = [{"runner": "codex-a", "mode": "IMPLEMENT", "size": "M", "windows": {"300": 60}},
                {"runner": "codex-a", "mode": "IMPLEMENT", "size": "M", "windows": {"300": 60}, "status": "FINISHED"},
                {"runner": "codex-a", "mode": "IMPLEMENT", "size": "M", "windows": {"300": 0}, "status": "ERROR"},
                {"runner": "codex-a", "mode": "IMPLEMENT", "size": "M", "windows": {"300": 1}, "status": "STALLED"}]
        got = keryx.cost_estimate(rows, "codex-a", "IMPLEMENT", "M")
        self.assertEqual(got["n"], 2)
        self.assertAlmostEqual(got["median"], 60.0, places=1)


class SliceSize(unittest.TestCase):
    def test_a_slice_takes_the_size_of_the_run_that_names_it(self):
        with tempfile.TemporaryDirectory() as d:
            env = _budget_env(d)
            parent = Path(d) / "runs" / "part"
            parent.mkdir(parents=True)
            (parent / "decisions.tsv").write_text(HEADER + "t\tsize\tL\tparts\t-\t-\n"
                                                  "t\tplan\tdispatched part-cost\tx\t-\t-\n")
            run, r = _round(d, "part-cost")
            keryx._record_round_cost(run, {"runner": "cli"}, r, RUN, [], env)
            self.assertEqual(keryx.cost_samples(env)[0]["size"], "L")

    def test_a_run_that_does_not_name_the_slug_lends_no_size(self):
        with tempfile.TemporaryDirectory() as d:
            env = _budget_env(d)
            parent = Path(d) / "runs" / "part"
            parent.mkdir(parents=True)
            (parent / "decisions.tsv").write_text(HEADER + "t\tsize\tL\tparts\t-\t-\n")
            run, r = _round(d, "part-cost")
            keryx._record_round_cost(run, {"runner": "cli"}, r, RUN, [], env)
            self.assertIsNone(keryx.cost_samples(env)[0]["size"])


if __name__ == "__main__":
    unittest.main()
