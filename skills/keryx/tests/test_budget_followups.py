"""Follow-ups of the executor budget: the chooser reads a brief's first mode word and puts an unknown estimate on a
nearly spent login last; a round that overlapped another round on the same login teaches no estimate; a subagent
round records its cost when `mark` closes it."""

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

AT = dt.datetime(2026, 11, 18, 2, 0, tzinfo=dt.timezone.utc)
LOGIN = {"runner": "codex", "model": "m", "codexHome": "~/x/a"}


def meter(used5, used7=10):
    return {"plan": "plus", "reached": None, "credits": [],
            "windows": [{"minutes": 300, "usedPercent": used5, "resetsAt": "2026-11-18T05:00:00Z"},
                        {"minutes": 10080, "usedPercent": used7, "resetsAt": "2026-11-25T00:00:00Z"}]}


class ModeWord(unittest.TestCase):
    def test_executors_mode_uses_the_first_mode_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, budget=True)
            with mock.patch.object(keryx, "choose_executors", return_value=[]) as choose:
                cli(repo, ["executors", "--mode", "TESTS-ONLY then IMPLEMENT", "--size", "M"], env)
            self.assertEqual(choose.call_args.args[3], "TESTS-ONLY")


class NearlySpentUnknownGoesLast(unittest.TestCase):
    def test_an_unknown_estimate_on_a_login_with_little_left_ranks_after_other_unknowns(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json"), "HOME": d}
            cfg = {"executors": ["codex-a", "subagent"], "order": "ladder", "budget": True, "resets": {},
                   "providers": {"codex-a": LOGIN}, "maxParallel": {}, "roots": [], "research": None}
            ranked = keryx.choose_executors(cfg, env, AT, "UNKNOWN", "M", {"codex-a": meter(85)}, [])
            self.assertEqual([r["name"] for r in ranked], ["subagent", "codex-a"])
            ranked = keryx.choose_executors(cfg, env, AT, "UNKNOWN", "M", {"codex-a": meter(30)}, [])
            self.assertEqual([r["name"] for r in ranked], ["codex-a", "subagent"])


class OverlapTeachesNothing(unittest.TestCase):
    def test_an_overlapping_sample_is_left_out(self):
        rows = [{"runner": "codex-a", "mode": "IMPLEMENT", "size": "M", "windows": {"300": 60}},
                {"runner": "codex-a", "mode": "IMPLEMENT", "size": "M", "windows": {"300": 95}, "overlap": True}]
        self.assertEqual(keryx.cost_estimate(rows, "codex-a", "IMPLEMENT", "M")["n"], 1)

    def test_another_live_reservation_on_the_login_marks_the_round(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json")}
            keryx.reserve(env, "codex-a", "mine", {"300": 50.0}, AT)
            self.assertFalse(keryx.overlapped(env, "codex-a", "mine", AT))
            keryx.reserve(env, "codex-a", "theirs", {"300": 50.0}, AT)
            self.assertTrue(keryx.overlapped(env, "codex-a", "mine", AT))
            self.assertFalse(keryx.overlapped(env, "codex-b", "mine", AT))

    def test_a_round_that_overlapped_is_recorded_with_the_flag(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "cfg" / "config.json"
            cfg.parent.mkdir()
            cfg.write_text(json.dumps({"executors": ["codex-a"], "budget": True,
                                       "providers": {"codex-a": LOGIN}}))
            env = {"KERYX_CONFIG": str(cfg), "HOME": d}
            run = Path(d) / "runs" / "s1"
            r = run / "rounds" / "01"
            r.mkdir(parents=True)
            (r / "prompt.md").write_text("Mode: IMPLEMENT\n")
            keryx.reserve(env, "codex-a", "other-run", {"300": 50.0}, dt.datetime.now(dt.timezone.utc))
            agent = {"runner": "codex-a", "runnerKind": "codex", "slug": "s1"}
            status = {"status": "FINISHED", "startedAt": "2026-11-18T01:00:00Z", "endedAt": "2026-11-18T01:10:00Z"}
            with mock.patch.object(keryx, "read_codex_meter", return_value=None):
                keryx._record_round_cost(run, agent, r, status, [], env)
            self.assertIs(keryx.cost_samples(env)[0]["overlap"], True)


class SubagentRoundsRecordTheirCost(unittest.TestCase):
    def test_mark_records_a_subagent_round_when_the_budget_is_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, budget=True)
            brief = Path(tmp) / "brief.md"
            brief.write_text("Mode: FIX\nGoal: x\n")
            self.assertEqual(cli(repo, ["log", "--slug", "sb", "size", "S", "small", "-", "-"], env)[0], 0)
            code, _, err = cli(repo, ["create", "--slug", "sb", "--runner", "subagent", "--prompt-file", str(brief)],
                               env)
            self.assertEqual(code, 0, err)
            self.assertEqual(cli(repo, ["mark", "--slug", "sb", "--status", "FINISHED"], env)[0], 0)
            samples = keryx.cost_samples(env)
            self.assertEqual([(s["runner"], s["mode"], s["size"], s["status"]) for s in samples],
                             [("subagent", "FIX", "S", "FINISHED")])

    def test_mark_records_nothing_with_the_budget_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp)
            brief = Path(tmp) / "brief.md"
            brief.write_text("Mode: FIX\n")
            cli(repo, ["create", "--slug", "sb", "--runner", "subagent", "--prompt-file", str(brief)], env)
            cli(repo, ["mark", "--slug", "sb", "--status", "FINISHED"], env)
            self.assertEqual(keryx.cost_samples(env), [])


if __name__ == "__main__":
    unittest.main()
