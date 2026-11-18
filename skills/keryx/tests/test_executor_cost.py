"""Part 2 of the executor budget: what a round cost (meter before and after, tokens, minutes), a machine-wide cost
ledger, and the learned estimate per executor, mode and size (log-normal: median and 80th percentile)."""

import datetime as dt
import json
import math
import statistics
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402


def meter(used5, used7, reset5="2026-11-18T03:56:13Z", reset7="2026-11-24T23:30:42Z"):
    return {"plan": "plus", "reached": None, "credits": [],
            "windows": [{"minutes": 300, "usedPercent": used5, "resetsAt": reset5},
                        {"minutes": 10080, "usedPercent": used7, "resetsAt": reset7}]}


CODEX_EVENTS = [{"type": "thread.started", "thread_id": "t"},
                {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 80,
                                                     "output_tokens": 7}},
                {"type": "turn.completed", "usage": {"input_tokens": 50, "cached_input_tokens": 40,
                                                     "output_tokens": 3}}]
CLAUDE_EVENTS = [{"type": "result", "usage": {"input_tokens": 10, "cache_read_input_tokens": 900,
                                              "output_tokens": 20}}]


class RoundCost(unittest.TestCase):
    def test_the_meter_difference_per_window_and_the_tokens(self):
        self.assertEqual(keryx.round_cost(meter(0, 1), meter(65, 10), CODEX_EVENTS, 13.5),
                         {"windows": {"300": 65, "10080": 9},
                          "tokens": {"input": 150, "cached": 120, "output": 10}, "minutes": 13.5})

    def test_a_window_that_reset_in_between_is_left_out(self):
        after = meter(5, 12, reset5="2026-11-18T08:56:13Z")
        self.assertEqual(keryx.round_cost(meter(90, 10), after, [], 2.0)["windows"], {"10080": 2})

    def test_without_both_meters_only_tokens_and_minutes(self):
        self.assertEqual(keryx.round_cost(None, meter(5, 5), CLAUDE_EVENTS, 1.0),
                         {"windows": {}, "tokens": {"input": 10, "cached": 900, "output": 20}, "minutes": 1.0})

    def test_a_meter_that_went_down_is_no_sample(self):
        self.assertEqual(keryx.round_cost(meter(50, 10), meter(40, 10), [], 1.0)["windows"], {"10080": 0})


class BriefMode(unittest.TestCase):
    def test_the_first_word_after_mode(self):
        self.assertEqual(keryx.brief_mode("Mode: IMPLEMENT\nGoal: x"), "IMPLEMENT")
        self.assertEqual(keryx.brief_mode("Mode: TESTS-ONLY then IMPLEMENT (two commits)\n"), "TESTS-ONLY")
        self.assertEqual(keryx.brief_mode("# Mode FIX — something\n"), "FIX")
        self.assertEqual(keryx.brief_mode("Write a file."), "UNKNOWN")


class RunSize(unittest.TestCase):
    def test_the_latest_size_row(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            (run / "decisions.tsv").write_text(
                "ts\tphase\tdecision\twhy\tevidence\tresult\n"
                "t1\tsize\tS\tsmall\t-\t-\n"
                "t2\tsize\tM — several files\tgrew\t-\t-\n")
            self.assertEqual(keryx.run_size(run), "M")
            self.assertIsNone(keryx.run_size(Path(d) / "none"))


class Ledger(unittest.TestCase):
    def test_entries_are_appended_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json")}
            a = {"runner": "codex-a", "mode": "IMPLEMENT", "size": "M", "at": "2026-11-18T01:06:21Z",
                 "windows": {"300": 63}, "tokens": {"input": 1, "cached": 0, "output": 1}, "minutes": 13.0}
            keryx.record_cost(env, a)
            keryx.record_cost(env, {**a, "mode": "FIX", "windows": {"300": 2}})
            (Path(d) / "costs.jsonl").open("a").write("not json\n")
            self.assertEqual([s["mode"] for s in keryx.cost_samples(env)], ["IMPLEMENT", "FIX"])
            self.assertEqual(keryx.cost_samples({"KERYX_CONFIG": str(Path(d) / "none" / "config.json")}), [])


class Estimate(unittest.TestCase):
    @staticmethod
    def sample(value, mode="IMPLEMENT", size="M", runner="codex-a", window="300"):
        return {"runner": runner, "mode": mode, "size": size, "windows": {window: value}}

    def test_one_sample_uses_a_wide_spread(self):
        got = keryx.cost_estimate([self.sample(63)], "codex-a", "IMPLEMENT", "M")
        self.assertEqual(got["n"], 1)
        self.assertEqual(got["size"], "M")
        self.assertAlmostEqual(got["median"], 63.0, places=1)
        self.assertAlmostEqual(got["p80"], 63 * math.exp(0.8416 * 0.6), places=1)

    def test_several_samples_use_their_own_spread_with_a_floor(self):
        values = [40, 60, 90]
        logs = [math.log(v) for v in values]
        mu, sigma = statistics.fmean(logs), max(statistics.stdev(logs), 0.25)
        got = keryx.cost_estimate([self.sample(v) for v in values], "codex-a", "IMPLEMENT", "M")
        self.assertAlmostEqual(got["median"], math.exp(mu), places=1)
        self.assertAlmostEqual(got["p80"], math.exp(mu + 0.8416 * sigma), places=1)
        same = keryx.cost_estimate([self.sample(50), self.sample(50)], "codex-a", "IMPLEMENT", "M")
        self.assertAlmostEqual(same["p80"], 50 * math.exp(0.8416 * 0.25), places=1)

    def test_a_zero_cost_counts_as_half_a_percent(self):
        got = keryx.cost_estimate([self.sample(0, mode="FIX")], "codex-a", "FIX", "M")
        self.assertAlmostEqual(got["median"], 0.5, places=2)

    def test_another_size_is_the_fallback_then_nothing(self):
        samples = [self.sample(20, size="S"), self.sample(70, runner="codex-b"), self.sample(5, mode="FIX")]
        got = keryx.cost_estimate(samples, "codex-a", "IMPLEMENT", "M")
        self.assertEqual((got["n"], got["size"]), (1, None))
        self.assertAlmostEqual(got["median"], 20.0, places=1)
        self.assertIsNone(keryx.cost_estimate(samples, "codex-a", "TESTS-ONLY", "M"))
        self.assertIsNone(keryx.cost_estimate(samples, "codex-a", "IMPLEMENT", "M", window="10080"))


class BudgetShowsTheEstimate(unittest.TestCase):
    def test_budget_json_carries_the_implement_m_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, budget=True)
            keryx.record_cost(env, {"runner": "cli", "mode": "IMPLEMENT", "size": "M", "at": "x",
                                    "windows": {"300": 40}, "tokens": {}, "minutes": 9.0})
            code, out, _ = cli(repo, ["budget", "--json"], env)
            self.assertEqual(code, 0)
            entries = {e["name"]: e for e in json.loads(out)}
            self.assertAlmostEqual(entries["cli"]["cost"]["median"], 40.0, places=1)
            self.assertIsNone(entries["subagent"]["cost"])


if __name__ == "__main__":
    unittest.main()
