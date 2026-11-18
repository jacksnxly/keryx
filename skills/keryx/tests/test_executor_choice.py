"""Part 3 of the executor budget: the chooser. An executor whose cautious cost (p80) fits what is left goes first;
among those, the one whose weekly window will lapse soonest (pressure) wins, then the tightest fit. Running rounds
reserve their cost, a meter overrules a limit record it disproves, and with the budget off nothing changes."""

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

AT = dt.datetime(2026, 11, 18, 1, 0, tzinfo=dt.timezone.utc)
LOGIN = {"runner": "codex", "model": "gpt-6.2-sol", "effort": "high"}


def config(*names):
    providers = {n: {**LOGIN, "codexHome": f"~/.config/keryx/codex/{n}"} for n in names if n.startswith("codex")}
    return {"executors": list(names), "order": "ladder", "budget": True, "resets": {}, "providers": providers,
            "maxParallel": {}, "roots": [], "research": None}


def meter(used5, used7, reset5="2026-11-18T05:00:00Z", reset7="2026-11-25T00:00:00Z"):
    return {"plan": "plus", "reached": None, "credits": [],
            "windows": [{"minutes": 300, "usedPercent": used5, "resetsAt": reset5},
                        {"minutes": 10080, "usedPercent": used7, "resetsAt": reset7}]}


class _Isolated(unittest.TestCase):
    """Every test gets a config folder of its own: keryx must never read or clear the real ~/.config/keryx."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"KERYX_CONFIG": str(Path(self._tmp.name) / "config.json"), "HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()


def samples(runner, five, seven, n=3, mode="IMPLEMENT", size="M"):
    return [{"runner": runner, "mode": mode, "size": size, "windows": {"300": five, "10080": seven}}] * n


class Fit(_Isolated):
    def test_an_executor_whose_p80_does_not_fit_goes_after_one_that_fits(self):
        cfg = config("codex-a", "codex-b")
        meters = {"codex-a": meter(70, 10), "codex-b": meter(0, 30)}
        hist = samples("codex-a", 50, 8) + samples("codex-b", 50, 8)
        ranked = keryx.choose_executors(cfg, self.env, AT, "IMPLEMENT", "M", meters, hist)
        self.assertEqual([r["name"] for r in ranked], ["codex-b", "codex-a"])
        self.assertIs(ranked[0]["fits"], True)
        self.assertIs(ranked[1]["fits"], False)
        self.assertIn("05:00", ranked[1]["reason"] + ranked[1].get("until", ""))

    def test_the_weekly_window_must_fit_too(self):
        cfg = config("codex-a")
        ranked = keryx.choose_executors(cfg, self.env, AT, "IMPLEMENT", "M", {"codex-a": meter(0, 95)},
                                        samples("codex-a", 50, 8))
        self.assertIs(ranked[0]["fits"], False)

    def test_no_estimate_or_no_meter_is_unknown_and_keeps_ladder_order(self):
        cfg = config("codex-a", "cli", "subagent")
        ranked = keryx.choose_executors(cfg, self.env, AT, "IMPLEMENT", "M", {"codex-a": meter(10, 10)}, [])
        self.assertEqual([(r["name"], r["fits"]) for r in ranked],
                         [("codex-a", None), ("cli", None), ("subagent", None)])

    def test_a_blocked_or_limited_executor_is_left_out(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json")}
            keryx.record_limit(env, "cli", {"kind": "weekly", "resetsAt": "2026-11-20T20:13:53Z"}, AT)
            blocked = {**meter(10, 10), "reached": "workspace_member_credits_depleted"}
            ranked = keryx.choose_executors(config("codex-a", "cli", "subagent"), env, AT, "IMPLEMENT", "M",
                                            {"codex-a": blocked}, [])
            self.assertEqual([r["name"] for r in ranked], ["subagent"])


class Pressure(_Isolated):
    def test_among_fitting_executors_the_one_closer_to_lapsing_goes_first(self):
        # codex-a: 80 % of the week left, 24 h to its reset; codex-b: 80 % left, 6 days to its reset.
        cfg = config("codex-b", "codex-a")
        meters = {"codex-a": meter(0, 20, reset7="2026-11-19T01:00:00Z"), "codex-b": meter(0, 20)}
        hist = samples("codex-a", 50, 8) + samples("codex-b", 50, 8)
        ranked = keryx.choose_executors(cfg, self.env, AT, "IMPLEMENT", "M", meters, hist)
        self.assertEqual([r["name"] for r in ranked], ["codex-a", "codex-b"])
        self.assertGreater(ranked[0]["pressure"], ranked[1]["pressure"])

    def test_pressure_is_the_rate_needed_over_the_rate_possible(self):
        # weekly per 5 h-window ratio 8/50 → a full 5 h window burns 16 % of the week → 3.2 %/h possible.
        # 80 % left over 24 h needs 3.33 %/h → pressure 80/24/3.2.
        ranked = keryx.choose_executors(config("codex-a"), self.env, AT, "IMPLEMENT", "M",
                                        {"codex-a": meter(0, 20, reset7="2026-11-19T01:00:00Z")},
                                        samples("codex-a", 50, 8))
        self.assertAlmostEqual(ranked[0]["pressure"], (80 / 24) / 3.2, places=2)

    def test_equal_pressure_prefers_the_tightest_fit(self):
        cfg = config("codex-a", "codex-b")
        meters = {"codex-a": meter(0, 20), "codex-b": meter(30, 20)}
        hist = samples("codex-a", 50, 8) + samples("codex-b", 50, 8)
        ranked = keryx.choose_executors(cfg, self.env, AT, "IMPLEMENT", "M", meters, hist)
        self.assertEqual([r["name"] for r in ranked], ["codex-b", "codex-a"])


class Reservations(unittest.TestCase):
    def test_a_running_round_holds_its_p80_until_it_ends(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json")}
            keryx.reserve(env, "codex-a", "slug-1", {"300": 60.0, "10080": 9.0}, AT)
            self.assertEqual(keryx.reserved(env, AT), {"codex-a": {"300": 60.0, "10080": 9.0}})
            ranked = keryx.choose_executors(config("codex-a"), env, AT, "IMPLEMENT", "M",
                                            {"codex-a": meter(0, 10)}, samples("codex-a", 50, 8))
            self.assertIs(ranked[0]["fits"], False)
            keryx.release(env, "codex-a", "slug-1")
            self.assertEqual(keryx.reserved(env, AT), {})

    def test_a_reservation_older_than_three_hours_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json")}
            keryx.reserve(env, "codex-a", "slug-1", {"300": 60.0}, AT)
            self.assertEqual(keryx.reserved(env, AT + dt.timedelta(hours=3, minutes=1)), {})


class MeterOverrulesARecord(unittest.TestCase):
    def test_a_limit_record_the_meter_disproves_is_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json")}
            keryx.record_limit(env, "codex-a", {"kind": "workspace", "resetsIn": "1 day"}, AT)
            ranked = keryx.choose_executors(config("codex-a"), env, AT, "IMPLEMENT", "M",
                                            {"codex-a": meter(10, 10)}, [])
            self.assertEqual([r["name"] for r in ranked], ["codex-a"])
            self.assertNotIn("codex-a", keryx.limited_runners(env, AT))


class ExecutorsCommand(unittest.TestCase):
    def test_with_the_budget_on_mode_and_size_rank_the_ladder_with_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, budget=True)
            keryx.record_cost(env, {"runner": "cli", "mode": "IMPLEMENT", "size": "M", "at": "x",
                                    "windows": {}, "tokens": {}, "minutes": 9.0})
            code, out, err = cli(repo, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
            self.assertEqual(code, 0)
            self.assertEqual(out.split(), ["cli", "subagent"])
            self.assertRegex(err, r"(?m)^cli: ")

    def test_with_the_budget_off_mode_and_size_change_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp)
            with mock.patch.object(keryx, "choose_executors") as choose:
                code, out, _ = cli(repo, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
            self.assertEqual((code, out.split()), (0, ["cli", "subagent"]))
            choose.assert_not_called()


if __name__ == "__main__":
    unittest.main()
