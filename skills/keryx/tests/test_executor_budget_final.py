"""Fixes from the full-branch review of the executor budget: executors that do not fit wait in reset order, a failed
spend is not a spend, no spend from inside an executor round or twice across sessions, the meter cache follows a spend,
`executors --mode` works outside a repository, and expired credits are not counted."""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

AT = dt.datetime(2026, 11, 18, 10, 0, tzinfo=dt.timezone.utc)
LOGIN = {"runner": "codex", "model": "m"}
CONFIG = {"budget": True, "executors": ["codex-a"],
          "providers": {"codex-a": {**LOGIN, "codexHome": "~/.config/keryx/codex/a"}}}


def meter(used5, used7, reset5, credits=(), reset7="2026-11-25T00:00:00Z"):
    return {"plan": "plus", "reached": None, "credits": list(credits),
            "windows": [{"minutes": 300, "usedPercent": used5, "resetsAt": reset5},
                        {"minutes": 10080, "usedPercent": used7, "resetsAt": reset7}]}


def soon_credit():
    expires = keryx._stamp(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    return {"id": "c-soon", "status": "available", "expiresAt": expires}


class WaitingOrder(unittest.TestCase):
    def test_executors_that_do_not_fit_are_ordered_by_when_they_fit(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"KERYX_CONFIG": str(Path(d) / "config.json"), "HOME": d}
            cfg = {"executors": ["codex-a", "codex-b"], "order": "ladder", "budget": True, "resets": {},
                   "providers": {n: {**LOGIN, "codexHome": f"~/x/{n}"} for n in ("codex-a", "codex-b")},
                   "maxParallel": {}, "roots": [], "research": None}
            hist = [{"runner": n, "mode": "IMPLEMENT", "size": "M", "windows": {"300": 50, "10080": 8}}
                    for n in ("codex-a", "codex-b") for _ in range(3)]
            meters = {"codex-a": meter(90, 10, "2026-11-18T16:00:00Z"), "codex-b": meter(90, 10, "2026-11-18T13:00:00Z")}
            ranked = keryx.choose_executors(cfg, env, AT, "IMPLEMENT", "M", meters, hist)
            self.assertEqual([(r["name"], r["fits"]) for r in ranked], [("codex-b", False), ("codex-a", False)])


class _Spend(unittest.TestCase):
    def _executors(self, tmp, outcome, grant="allow", extra_env=None, reread=None):
        repo = _two_commit_repo(tmp)[0]
        env = machine(tmp, **CONFIG)
        cli(repo, ["grant", "reset-credits", grant, "--source", "owner, a test"], env)
        spent = meter(100, 100, "2099-01-01T05:00:00Z", [soon_credit()], reset7="2099-01-02T00:00:00Z")
        after = reread if reread is not None else spent
        env = {**env, **(extra_env or {})}
        with mock.patch.object(keryx, "codex_meters", return_value={"codex-a": spent}), \
                mock.patch.object(keryx, "read_codex_meter", return_value=after), \
                mock.patch.object(keryx, "consume_reset_credit", return_value=outcome) as consume:
            code, out, err = cli(repo, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
        ledger = Path(env["KERYX_CONFIG"]).parent / "credits.jsonl"
        return code, err, consume, ledger, env


class FailedSpend(_Spend):
    def test_a_failed_spend_is_not_reported_or_logged_as_spent(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err, consume, ledger, _ = self._executors(tmp, None)
            self.assertEqual(code, 0)
            self.assertEqual(consume.call_count, 1)
            self.assertNotIn("spent a reset credit", err)
            self.assertRegex(err, r"codex-a: .*reset credit.*(failed|not spent)")
            self.assertFalse(ledger.exists() and ledger.read_text().strip())

    def test_budget_spend_credit_that_fails_exits_non_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, **CONFIG)
            with mock.patch.object(keryx, "read_codex_meter",
                                   return_value=meter(50, 50, "2099-01-01T05:00:00Z", [soon_credit()])), \
                    mock.patch.object(keryx, "consume_reset_credit", return_value=None):
                code, out, err = cli(repo, ["budget", "--spend-credit", "codex-a"], env)
            self.assertNotEqual(code, 0)
            self.assertNotIn("spent a reset credit", out)


class NoSpendFromAnExecutorRound(_Spend):
    def test_an_executor_round_never_spends(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err, consume, _, _ = self._executors(tmp, "consumed", extra_env={"KERYX_EXECUTOR": "1"})
            self.assertEqual(code, 0)
            consume.assert_not_called()


class SpendRechecksUnderALock(_Spend):
    def test_a_credit_already_spent_by_another_session_is_not_spent_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            refilled = meter(0, 0, "2099-01-01T05:00:00Z", [], reset7="2099-01-08T00:00:00Z")
            code, err, consume, _, _ = self._executors(tmp, "consumed", reread=refilled)
            self.assertEqual(code, 0)
            consume.assert_not_called()


class CacheFollowsASpend(_Spend):
    def test_the_meter_read_after_a_spend_is_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            after = meter(0, 0, "2099-01-01T05:00:00Z", [], reset7="2099-01-08T00:00:00Z")
            spent = meter(100, 100, "2099-01-01T05:00:00Z", [soon_credit()], reset7="2099-01-02T00:00:00Z")
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, **CONFIG)
            cli(repo, ["grant", "reset-credits", "allow", "--source", "owner, a test"], env)
            reads = iter([spent, spent, after, after, after])
            with mock.patch.object(keryx, "read_codex_meter", side_effect=lambda *a, **k: next(reads)), \
                    mock.patch.object(keryx, "consume_reset_credit", return_value="consumed"):
                code, _, err = cli(repo, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
            self.assertEqual(code, 0)
            self.assertIn("spent a reset credit on codex-a", err)
            cache = json.loads((Path(env["KERYX_CONFIG"]).parent / "meters.json").read_text())
            self.assertEqual(cache["codex-a"]["meter"]["windows"][1]["usedPercent"], 0)


class OutsideARepository(unittest.TestCase):
    def test_executors_mode_works_outside_a_git_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = machine(tmp, **CONFIG)
            spent = meter(100, 100, "2099-01-01T05:00:00Z", [soon_credit()], reset7="2099-01-02T00:00:00Z")
            outside = Path(tmp) / "plain"
            outside.mkdir()
            with mock.patch.object(keryx, "codex_meters", return_value={"codex-a": spent}), \
                    mock.patch.object(keryx, "consume_reset_credit") as consume:
                code, out, err = cli(outside, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
            self.assertEqual(code, 0, err)
            consume.assert_not_called()  # no grant was given: the default is ask


class ExpiredCreditsDoNotCount(unittest.TestCase):
    def test_budget_counts_only_credits_that_have_not_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, **CONFIG)
            past = {"id": "c-old", "status": "available", "expiresAt": "2020-01-01T00:00:00Z"}
            with mock.patch.object(keryx, "codex_meters",
                                   return_value={"codex-a": meter(10, 10, "2099-01-01T05:00:00Z",
                                                                  [past, soon_credit()])}):
                code, out, _ = cli(repo, ["budget", "--json"], env)
            entry = json.loads(out)[0]
            self.assertEqual(entry["credits"], 1)
            self.assertNotEqual(entry["creditExpires"], "2020-01-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
