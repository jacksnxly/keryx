"""Field fixes after 1.6.0, the owner's side: standing grants a program can read, one inbox for every open
question across repositories, follow-ups that start or ask by the grant, and per-repository settings."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

WORDS = "owner 2026-11-08: 'merge and release from this Mac'"


class Grants(unittest.TestCase):
    def test_nothing_granted_means_ask(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            code, out, err = cli(repo, ["grants", "--action", "merge"], env)
            self.assertEqual((code, out.strip()), (0, "ask"), err)
            code, out, err = cli(repo, ["grants", "--action", "followups"], env)
            self.assertEqual((code, out.strip()), (0, "none"), err)

    def test_a_grant_needs_the_owners_words_a_known_action_and_a_known_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            self.assertNotEqual(cli(repo, ["grant", "merge", "allow"], env)[0], 0)
            self.assertEqual(cli(repo, ["grant", "teleport", "allow", "--source", WORDS], env)[0], 1)
            self.assertEqual(cli(repo, ["grant", "merge", "maybe", "--source", WORDS], env)[0], 1)
            self.assertEqual(cli(repo, ["grant", "followups", "allow", "--source", WORDS], env)[0], 1)
            self.assertEqual(cli(repo, ["grant", "merge", "safe", "--source", WORDS], env)[0], 1)
            self.assertFalse((Path(tmp) / "cfg" / "grants.json").exists())

    def test_a_repository_grant_outranks_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            self.assertEqual(cli(repo, ["grant", "merge", "allow", "--source", WORDS], env)[0], 0)
            self.assertEqual(cli(repo, ["grant", "push", "allow", "--source", WORDS], env)[0], 0)
            self.assertEqual(cli(repo, ["grant", "push", "ask", "--repo", "--source",
                                        "AGENTS.md: never push without the owner's go"], env)[0], 0)
            self.assertEqual(cli(repo, ["grant", "followups", "safe", "--source", WORDS], env)[0], 0)
            self.assertEqual(cli(repo, ["grants", "--action", "merge"], env)[1].strip(), "allow")
            self.assertEqual(cli(repo, ["grants", "--action", "push"], env)[1].strip(), "ask")
            self.assertEqual(cli(repo, ["grants", "--action", "followups"], env)[1].strip(), "safe")
            saved = json.loads((Path(tmp) / "cfg" / "grants.json").read_text())
            self.assertEqual(saved["default"]["merge"], "allow")
            self.assertEqual(saved["repos"]["repo"]["push"], "ask")
            self.assertIn("merge and release from this Mac", json.dumps(saved["sources"]))
            code, out, err = cli(repo, ["grants"], env)
            self.assertEqual(code, 0, err)
            self.assertRegex(out, r"(?m)^push\s+ask\s+\(this repository\)")
            self.assertRegex(out, r"(?m)^merge\s+allow\s+\(default\)")
            self.assertRegex(out, r"(?m)^production-data\s+ask\s+\(not granted\)")
            self.assertRegex(out, r"(?m)^followups\s+safe\s+\(default\)")

    def test_recall_shows_the_grants(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            self.assertEqual(cli(repo, ["grant", "branch-delete", "allow", "--source", WORDS], env)[0], 0)
            code, out, err = cli(repo, ["recall"], env)
            self.assertEqual(code, 0, err)
            self.assertIn("# keryx grants", out)
            self.assertRegex(out, r"(?m)^branch-delete\s+allow")


class OwnerInbox(unittest.TestCase):
    QUESTION = "Limits for API-key callers at /mcp?"

    def test_ask_answer_and_the_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            d = repo / ".keryx" / "runs" / "mcp"
            self.assertEqual(cli(repo, ["log", "--slug", "mcp", "intake", "task", "why", "ev", "ok"], env)[0], 0)
            code, out, err = cli(repo, ["ask", "--slug", "mcp", self.QUESTION, "--option", "A: same as OAuth",
                                        "--option", "B: half", "--recommend", "A",
                                        "--blocks", "the locked tests need the numbers"], env)
            self.assertEqual(code, 0, out + err)
            n, c = keryx.read_log_rows(d)[-1]
            self.assertEqual((c[1], c[2], c[5]), ("waiting", f"owner: {self.QUESTION}", "open"))
            self.assertEqual(c[3], "the locked tests need the numbers")
            self.assertIn("A: same as OAuth (recommended)", c[4])
            self.assertIn("B: half", c[4])
            self.assertLess(c[4].index("A: same as OAuth"), c[4].index("B: half"), "the recommendation comes first")
            code, out, err = cli(repo, ["inbox"], env)
            self.assertEqual(code, 0, err)
            for part in ("repo/mcp", f"row {n}", self.QUESTION, "A: same as OAuth (recommended)", "B: half",
                         "blocks: the locked tests need the numbers"):
                self.assertIn(part, out)
            self.assertEqual(cli(repo, ["answer", "--slug", "mcp", str(n), "A, and no expiry"], env)[0], 0)
            _, c = keryx.read_log_rows(d)[-1]
            self.assertEqual((c[1], c[2], c[5]), ("answer", f"row {n}: A, and no expiry", "closed"))
            code, out, err = cli(repo, ["inbox"], env)
            self.assertIn("inbox empty", out)
            self.assertNotIn(self.QUESTION, out)
            self.assertEqual(cli(repo, ["answer", "--slug", "mcp", str(n), "again"], env)[0], 1, "answered once")
            self.assertEqual(cli(repo, ["answer", "--slug", "mcp", "1", "x"], env)[0], 1, "row 1 is no question")

    def test_a_question_between_runs_goes_to_the_repositorys_own_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            code, out, err = cli(repo, ["ask", "Rotate REVALIDATE_SECRET?", "--option", "yes", "--option", "no"], env)
            self.assertEqual(code, 0, out + err)
            _, c = keryx.read_log_rows(repo / ".keryx" / "runs" / "owner-inbox")[-1]
            self.assertEqual((c[2], c[5]), ("owner: Rotate REVALIDATE_SECRET?", "open"))
            self.assertIn("Rotate REVALIDATE_SECRET?", cli(repo, ["inbox"], env)[1])

    def test_inbox_all_reads_every_repository_under_the_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            other = Path(tmp) / "other"
            other.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
            env = machine(tmp, roots=[tmp])
            self.assertEqual(cli(repo, ["ask", "--slug", "a", "First?"], env)[0], 0)
            self.assertEqual(cli(other, ["ask", "--slug", "b", "Second?"], env)[0], 0)
            own = cli(repo, ["inbox"], env)[1]
            self.assertIn("First?", own)
            self.assertNotIn("Second?", own)
            code, out, err = cli(repo, ["inbox", "--all"], env)
            self.assertEqual(code, 0, err)
            for part in ("repo/a", "First?", "other/b", "Second?"):
                self.assertIn(part, out)

    def test_a_waiting_row_written_by_hand_is_no_inbox_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            self.assertEqual(cli(repo, ["log", "--slug", "old", "waiting", "owner: approve DESIGN.md", "why", "ev",
                                        "by tomorrow"], env)[0], 0)
            self.assertIn("inbox empty", cli(repo, ["inbox"], env)[1])


class FollowUps(unittest.TestCase):
    SAFE, RISK, PRICE = "delete the dead GraphQL fields", "move register-identity to Rust", "price the document link"

    def test_a_next_row_says_safe_risk_or_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self.assertEqual(cli(repo, ["log", "--slug", "fu", "next", self.SAFE, "why", "-", "maybe"])[0], 1)
            self.assertEqual(cli(repo, ["log", "--slug", "fu", "next", self.SAFE, "why", "-", "safe"])[0], 0)

    def test_the_inbox_says_start_or_ask_by_the_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            for task, kind in ((self.SAFE, "safe"), (self.RISK, "risk"), (self.PRICE, "price")):
                self.assertEqual(cli(repo, ["log", "--slug", "fu", "next", task, "why", "-", kind], env)[0], 0)
            out = cli(repo, ["inbox"], env)[1]
            for task in (self.SAFE, self.RISK, self.PRICE):
                self.assertRegex(out, rf"(?m)^ask\s.*{task}")
            self.assertEqual(cli(repo, ["grant", "followups", "safe", "--source", "owner"], env)[0], 0)
            out = cli(repo, ["inbox"], env)[1]
            self.assertRegex(out, rf"(?m)^start\s.*{self.SAFE}")
            self.assertRegex(out, rf"(?m)^ask\s.*{self.RISK}")
            self.assertRegex(out, rf"(?m)^ask\s.*{self.PRICE}")
            self.assertEqual(cli(repo, ["grant", "followups", "all", "--source", "owner"], env)[0], 0)
            out = cli(repo, ["inbox"], env)[1]
            self.assertRegex(out, rf"(?m)^start\s.*{self.RISK}")
            self.assertRegex(out, rf"(?m)^ask\s.*{self.PRICE}", "a price is always the owner's")
            rows = keryx.read_log_rows(repo / ".keryx" / "runs" / "fu")
            n = next(i for i, c in rows if c[2] == self.SAFE)
            self.assertEqual(cli(repo, ["answer", "--slug", "fu", str(n), "started as dead-graphql"], env)[0], 0)
            out = cli(repo, ["inbox"], env)[1]
            self.assertNotIn(self.SAFE, out)
            self.assertIn(self.RISK, out)


class RepositorySettings(unittest.TestCase):
    def test_the_ci_command_and_the_report_place_are_saved_per_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            code, out, err = cli(repo, ["repo"], env)
            self.assertEqual(code, 0, err)
            self.assertRegex(out, r"(?m)^ci\s+not set")
            self.assertRegex(out, r"(?m)^report\s+committed")
            self.assertEqual(cli(repo, ["repo", "--ci", "make ci-local"], env)[0], 0)
            self.assertEqual(cli(repo, ["repo", "--report", "local"], env)[0], 0)
            self.assertEqual(json.loads((repo / ".keryx" / "config.json").read_text()),
                             {"ci": "make ci-local", "report": "local"})
            out = cli(repo, ["repo"], env)[1]
            self.assertRegex(out, r"(?m)^ci\s+make ci-local$")
            self.assertRegex(out, r"(?m)^report\s+local")
            self.assertIn("make ci-local", cli(repo, ["recall"], env)[1])
            self.assertNotEqual(cli(repo, ["repo", "--report", "elsewhere"], env)[0], 0)
            self.assertEqual(run("status", "--porcelain"), "", ".keryx/ ignores itself")


if __name__ == "__main__":
    unittest.main()
