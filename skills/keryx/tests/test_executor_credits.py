"""Part 4 of the executor budget: Codex reset credits. One is spent only when the login's weekly window is used up,
work is waiting that nothing can take, and the credit would expire within three days — and only under the owner's
`reset-credits allow` grant; otherwise keryx says which command would spend it."""

import datetime as dt
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

AT = dt.datetime(2026, 11, 28, 12, 0, tzinfo=dt.timezone.utc)


def meter(used7, credits, used5=40):
    return {"plan": "plus", "reached": None, "credits": credits,
            "windows": [{"minutes": 300, "usedPercent": used5, "resetsAt": "2026-11-28T15:00:00Z"},
                        {"minutes": 10080, "usedPercent": used7, "resetsAt": "2026-12-02T00:00:00Z"}]}


def credit(cid, expires, status="available"):
    return {"id": cid, "status": status, "expiresAt": expires}


SOON = credit("c-soon", "2026-11-30T19:13:45Z")      # 2 d 7 h away
LATER = credit("c-later", "2026-12-01T19:13:45Z")    # 3 d 7 h away
OLD = credit("c-old", "2026-11-29T00:00:00Z", status="consumed")


class WhichCredit(unittest.TestCase):
    def test_the_soonest_expiring_available_credit_within_three_days(self):
        self.assertEqual(keryx.credit_to_spend(meter(100, [LATER, OLD, SOON]), AT, True), SOON)

    def test_nothing_unless_the_week_is_spent_work_waits_and_a_credit_expires_soon(self):
        self.assertIsNone(keryx.credit_to_spend(meter(99, [SOON]), AT, True))
        self.assertIsNone(keryx.credit_to_spend(meter(100, [SOON]), AT, False))
        self.assertIsNone(keryx.credit_to_spend(meter(100, [LATER]), AT, True))
        self.assertIsNone(keryx.credit_to_spend(meter(100, [OLD]), AT, True))
        self.assertIsNone(keryx.credit_to_spend(None, AT, True))


class Consume(unittest.TestCase):
    def test_the_credit_is_consumed_through_the_logins_own_app_server(self):
        with tempfile.TemporaryDirectory() as d:
            bin_dir = Path(d) / "bin"
            bin_dir.mkdir()
            log = Path(d) / "requests.jsonl"
            script = bin_dir / "codex"
            script.write_text(f"""#!{sys.executable}
import json, os, sys
for line in sys.stdin:
    m = json.loads(line)
    open({str(log)!r}, "a").write(json.dumps({{"m": m, "home": os.environ.get("CODEX_HOME")}}) + "\\n")
    if m.get("method") == "initialize":
        print(json.dumps({{"id": m["id"], "result": {{}}}}), flush=True)
    elif m.get("method") == "account/rateLimitResetCredit/consume":
        print(json.dumps({{"id": m["id"], "result": {{"outcome": "consumed"}}}}), flush=True)
""")
            script.chmod(script.stat().st_mode | stat.S_IEXEC)
            env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", "HOME": d}
            home = Path(d) / "acct"
            home.mkdir()
            self.assertEqual(keryx.consume_reset_credit(home, env, "c-soon", "key-1", timeout=10), "consumed")
            sent = [json.loads(line) for line in log.read_text().splitlines()]
            call = [s for s in sent if s["m"].get("method") == "account/rateLimitResetCredit/consume"][0]
            self.assertEqual(call["m"]["params"], {"creditId": "c-soon", "idempotencyKey": "key-1"})
            self.assertEqual(call["home"], str(home))

    def test_no_codex_is_none(self):
        self.assertIsNone(keryx.consume_reset_credit(Path("/no-such-root-keryx"), {"PATH": "/no-such-root-keryx"},
                                                     "c", "k", timeout=2))


class Grant(unittest.TestCase):
    def test_reset_credits_is_a_grant_that_defaults_to_ask(self):
        self.assertIn("reset-credits", keryx.GRANT_ACTIONS)
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp)
            code, out, _ = cli(repo, ["grants"], env)
            self.assertRegex(out, r"(?m)^reset-credits  ask  \(not granted\)$")
            self.assertEqual(cli(repo, ["grant", "reset-credits", "allow", "--source", "owner, a test"], env)[0], 0)
            code, out, _ = cli(repo, ["grants"], env)
            self.assertRegex(out, r"(?m)^reset-credits  allow  \(default\)$")


class SpendWhenNothingFits(unittest.TestCase):
    CONFIG = {"budget": True, "executors": ["codex-a"],
              "providers": {"codex-a": {"runner": "codex", "codexHome": "~/.config/keryx/codex/a",
                                        "model": "gpt-6.2-sol"}}}

    def _run(self, tmp, grant):
        repo = _two_commit_repo(tmp)[0]
        env = machine(tmp, **self.CONFIG)
        if grant:
            cli(repo, ["grant", "reset-credits", grant, "--source", "owner, a test"], env)
        soon = credit("c-soon", keryx._stamp(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)))
        spent = meter(100, [soon])
        with mock.patch.object(keryx, "codex_meters", return_value={"codex-a": spent}), \
                mock.patch.object(keryx, "consume_reset_credit", return_value="consumed") as consume:
            code, out, err = cli(repo, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
        return code, out, err, consume

    def test_with_the_grant_the_expiring_credit_is_spent(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err, consume = self._run(tmp, "allow")
            self.assertEqual(code, 0)
            self.assertEqual(consume.call_count, 1)
            self.assertEqual(consume.call_args.args[2], "c-soon")
            self.assertRegex(err, r"spent a reset credit on codex-a")

    def test_without_the_grant_keryx_names_the_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err, consume = self._run(tmp, None)
            self.assertEqual(code, 0)
            consume.assert_not_called()
            self.assertIn("keryx.py budget --spend-credit codex-a", err)


class SpendByHand(unittest.TestCase):
    def test_budget_spend_credit_spends_the_soonest_available_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, **SpendWhenNothingFits.CONFIG)
            with mock.patch.object(keryx, "read_codex_meter", return_value=meter(50, [LATER, SOON])), \
                    mock.patch.object(keryx, "consume_reset_credit", return_value="consumed") as consume:
                code, out, _ = cli(repo, ["budget", "--spend-credit", "codex-a"], env)
            self.assertEqual(code, 0)
            self.assertEqual(consume.call_args.args[2], "c-soon")
            self.assertIn("consumed", out)

    def test_an_executor_without_a_login_meter_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, budget=True)
            code, _, err = cli(repo, ["budget", "--spend-credit", "cli"], env)
            self.assertNotEqual(code, 0)
            self.assertIn("cli", err)


if __name__ == "__main__":
    unittest.main()
