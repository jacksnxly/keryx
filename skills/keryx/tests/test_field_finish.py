"""Field fixes after 1.6.0, finishing: `finish` knows a size S run, a QA-only run, an umbrella over finished
slices and a report kept in the run folder; an M or L run needs its QA file; the fourth review round needs a
reason; merged executor branches and worktrees are removed under the owner's grant."""

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

CLEAN = "Head: {head}\nReach: one caller\nSpec: matches\nFindings: none\n"


def state(repo, slug):
    return repo / ".keryx" / "runs" / slug


def log(repo, slug, phase, decision, result="ok", env=None):
    code, out, err = cli(repo, ["log", "--slug", slug, phase, decision, "why", "ev", result], env)
    assert code == 0, out + err


def reviewed(repo, slug, base, head):
    """A well-formed clean review of base..head in the run's folder."""
    code, out, err = cli(repo, ["review-brief", "--slug", slug, "--base", base, "--head", head])
    assert code == 0, out + err
    (state(repo, slug) / "review" / f"{base[:12]}..{head[:12]}.findings.md").write_text(CLEAN.format(head=head))


def shipped_m_run(repo, slug, base, head, size="M"):
    """An M run with everything `finish` asked for before this change: review, filled-in report, finish row."""
    assert cli(repo, ["repo", "--report", "local"])[0] == 0
    if size:
        log(repo, slug, "size", size)
    reviewed(repo, slug, base, head)
    (state(repo, slug) / "REPORT.md").write_text("# report\n\nProof: the check passes.\n")
    log(repo, slug, "finish", "merged PR #1", "merged")


class SizeS(unittest.TestCase):
    def test_a_size_s_run_finishes_on_its_finish_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "s1", "size", "S")
            code, out, err = cli(repo, ["finish", "--slug", "s1", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("missing  a finish row", out)
            self.assertNotIn("fresh review", out)
            self.assertNotIn("run report", out)
            log(repo, "s1", "finish", "merged abc1234", "live")
            code, out, err = cli(repo, ["finish", "--slug", "s1", "--head", head])
            self.assertEqual(code, 0, out + err)
            self.assertIn("FINISHED  s1", out)
            self.assertIn("size S", out)
            self.assertEqual(json.loads((state(repo, "s1") / "finished.json").read_text())["size"], "S")

    def test_size_s_with_executor_rounds_is_not_s(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "s2", "size", "S")
            log(repo, "s2", "finish", "merged abc1234", "live")
            (state(repo, "s2") / "rounds" / "01").mkdir(parents=True)
            (state(repo, "s2") / "rounds" / "01" / "prompt.md").write_text("Mode: IMPLEMENT\n")
            code, out, err = cli(repo, ["finish", "--slug", "s2", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("size S", out)
            self.assertIn("executor round", out)


class QaGate(unittest.TestCase):
    def test_an_m_run_needs_its_qa_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            shipped_m_run(repo, "qa1", base, head)
            code, out, err = cli(repo, ["finish", "--slug", "qa1", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("missing  the QA file", out)
            self.assertNotIn("fresh review", out)
            self.assertNotIn("run report", out)
            (state(repo, "qa1") / "qa").mkdir()
            (state(repo, "qa1") / "qa" / "QA.md").write_text("1. GET /v1/x on staging: 200, body in qa/x.json\n")
            code, out, err = cli(repo, ["finish", "--slug", "qa1", "--head", head])
            self.assertEqual(code, 0, out + err)
            self.assertIn("FINISHED  qa1", out)

    def test_an_empty_qa_file_is_no_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            shipped_m_run(repo, "qa2", base, head, size="L")
            (state(repo, "qa2") / "qa").mkdir()
            (state(repo, "qa2") / "qa" / "QA.md").write_text("\n")
            code, out, err = cli(repo, ["finish", "--slug", "qa2", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("missing  the QA file", out)

    def test_a_ruling_waives_the_qa_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            shipped_m_run(repo, "qa3", base, head)
            log(repo, "qa3", "ruling", "Ruling: no QA file — a comment-only change, nothing to open")
            code, out, err = cli(repo, ["finish", "--slug", "qa3", "--head", head])
            self.assertEqual(code, 0, out + err)

    def test_a_run_without_a_size_row_keeps_the_old_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            shipped_m_run(repo, "qa4", base, head, size=None)
            code, out, err = cli(repo, ["finish", "--slug", "qa4", "--head", head])
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^size\s+not logged")

    def test_a_slice_takes_its_runs_qa_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "big", "intake", "the run")
            (state(repo, "big") / "PLAN.md").write_text("## Slices\n- big-api: owns the API\n")
            (state(repo, "big") / "qa").mkdir()
            (state(repo, "big") / "qa" / "QA.md").write_text("1. the page on staging, screenshot qa/1.png\n")
            shipped_m_run(repo, "big-api", base, head)
            code, out, err = cli(repo, ["finish", "--slug", "big-api", "--head", head])
            self.assertEqual(code, 0, out + err)


class LocalReport(unittest.TestCase):
    def test_the_report_stays_in_the_run_folder_when_the_repository_says_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self.assertEqual(cli(repo, ["repo", "--report", "local"])[0], 0)
            log(repo, "lr", "intake", "task")
            code, out, err = cli(repo, ["report", "--slug", "lr", "--head", head])
            self.assertEqual(code, 0, out + err)
            self.assertTrue((state(repo, "lr") / "REPORT.md").exists())
            self.assertFalse((repo / "docs" / "keryx").exists())
            self.assertEqual(cli(repo, ["report", "--slug", "lr", "--head", head])[0], 1, "never overwritten")

    def test_finish_refuses_a_local_report_with_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            shipped_m_run(repo, "lp", base, head, size=None)
            (state(repo, "lp") / "REPORT.md").write_text("# report\n\n<!-- what changed -->\n")
            code, out, err = cli(repo, ["finish", "--slug", "lp", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("placeholders", out)
            (state(repo, "lp") / "REPORT.md").unlink()
            code, out, err = cli(repo, ["finish", "--slug", "lp", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("missing  the run report", out)
            self.assertIn("REPORT.md", out)


class QaOnly(unittest.TestCase):
    def test_a_qa_only_run_finishes_on_its_qa_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "qo", "intake", "deeper QA of the key store")
            log(repo, "qo", "finish", "QA done: 181 cases, 10 defects handed to qo-fixes", "done")
            code, out, err = cli(repo, ["finish", "--slug", "qo", "--head", head, "--qa-only"])
            self.assertEqual(code, 1, out + err)
            self.assertIn("missing  the QA file", out)
            self.assertNotIn("fresh review", out)
            (state(repo, "qo") / "qa").mkdir()
            (state(repo, "qo") / "qa" / "QA.md").write_text("181 cases, evidence in qa/api, qa/web\n")
            code, out, err = cli(repo, ["finish", "--slug", "qo", "--head", head, "--qa-only"])
            self.assertEqual(code, 0, out + err)
            self.assertEqual(json.loads((state(repo, "qo") / "finished.json").read_text())["kind"], "qa-only")


class Umbrella(unittest.TestCase):
    def test_an_umbrella_finishes_when_every_slice_has(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "um", "intake", "two slices that ship on their own")
            (state(repo, "um") / "PLAN.md").write_text("## Slices\n- um-a: owns a\n- um-b: owns b\n")
            log(repo, "um-a", "intake", "slice a")
            log(repo, "um-b", "intake", "slice b")
            log(repo, "um", "finish", "both slices shipped", "live")
            code, out, err = cli(repo, ["finish", "--slug", "um", "--head", head, "--umbrella"])
            self.assertEqual(code, 1, out + err)
            self.assertIn("um-a", out)
            self.assertIn("um-b", out)
            (state(repo, "um-a") / "finished.json").write_text(json.dumps({"slug": "um-a"}))
            code, out, err = cli(repo, ["finish", "--slug", "um", "--head", head, "--umbrella"])
            self.assertEqual(code, 1, out + err)
            self.assertNotIn("um-a", out)
            self.assertIn("um-b", out)
            (state(repo, "um-b") / "finished.json").write_text(json.dumps({"slug": "um-b"}))
            code, out, err = cli(repo, ["finish", "--slug", "um", "--head", head, "--umbrella"])
            self.assertEqual(code, 0, out + err)
            finished = json.loads((state(repo, "um") / "finished.json").read_text())
            self.assertEqual((finished["kind"], finished["slices"]), ("umbrella", ["um-a", "um-b"]))

    def test_an_umbrella_without_slices_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "solo", "intake", "one run")
            log(repo, "solo", "finish", "shipped", "live")
            code, out, err = cli(repo, ["finish", "--slug", "solo", "--head", head, "--umbrella"])
            self.assertEqual(code, 1, out + err)
            self.assertIn("no slices", out)


class NextAtFinish(unittest.TestCase):
    def test_finish_lists_open_follow_ups_with_the_grants_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            log(repo, "nx", "size", "S", env=env)
            log(repo, "nx", "finish", "merged abc1234", "live", env=env)
            log(repo, "nx", "next", "delete the dead GraphQL fields", "safe", env=env)
            log(repo, "nx", "next", "price the document link", "price", env=env)
            self.assertEqual(cli(repo, ["grant", "followups", "safe", "--source", "owner"], env)[0], 0)
            code, out, err = cli(repo, ["finish", "--slug", "nx", "--head", head], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^next\s+start\s.*delete the dead GraphQL fields")
            self.assertRegex(out, r"(?m)^next\s+ask\s.*price the document link")


class ReviewRounds(unittest.TestCase):
    """Rounds 4 to 9 of three field runs found no P0 or P1 in 13 rounds."""

    RANGES = ("aaaaaaaaaaaa..bbbbbbbbbbbb", "bbbbbbbbbbbb..cccccccccccc", "cccccccccccc..dddddddddddd")

    def _past(self, repo, slug, ranges):
        rv = state(repo, slug) / "review"
        rv.mkdir(parents=True, exist_ok=True)
        for name in ranges:
            (rv / f"{name}.findings.md").write_text("Head: " + name[-12:] + "\nReach: x\nSpec: y\nFindings: none\n")
        (rv / f"{ranges[0]}.security.findings.md").write_text("Head: x\nReach: x\nSpec: y\nFindings: none\n")

    def test_a_fourth_review_round_needs_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "rr", "intake", "task")
            self._past(repo, "rr", self.RANGES)
            argv = ["review-brief", "--slug", "rr", "--base", base, "--head", head]
            code, out, err = cli(repo, argv)
            self.assertEqual(code, 1, out + err)
            self.assertIn("three review rounds", err)
            self.assertFalse((state(repo, "rr") / "review" / f"{base[:12]}..{head[:12]}.brief.md").exists())
            code, out, err = cli(repo, argv + ["--extra", "the fix touched auth"])
            self.assertEqual(code, 0, out + err)
            self.assertTrue((state(repo, "rr") / "review" / f"{base[:12]}..{head[:12]}.brief.md").exists())
            ruling = [c for _, c in keryx.read_log_rows(state(repo, "rr")) if c[2].startswith("Ruling: review round 4")]
            self.assertEqual(len(ruling), 1)
            self.assertIn("the fix touched auth", "\t".join(ruling[0]))

    def test_the_third_round_and_a_repeat_of_its_range_are_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "r3", "intake", "task")
            self._past(repo, "r3", self.RANGES[:2])
            argv = ["review-brief", "--slug", "r3", "--base", base, "--head", head]
            self.assertEqual(cli(repo, argv)[0], 0)
            (state(repo, "r3") / "review" / f"{base[:12]}..{head[:12]}.findings.md").write_text(CLEAN.format(head=head))
            self.assertEqual(cli(repo, argv)[0], 0, "the same range again is the same round")


class Cleanup(unittest.TestCase):
    """The owner typed "post merge cleanup" 14 times in five days."""

    def _run_with_branch(self, tmp, granted=True):
        repo, run, base, head = _two_commit_repo(tmp)
        env = machine(tmp)
        wt = repo / ".worktrees" / "cursor-cl"
        run("worktree", "add", "-q", "-b", "cursor/cl", str(wt), head)
        (wt / "new.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(wt), "add", "new.py"], check=True)
        subprocess.run(["git", "-C", str(wt), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m",
                        "feat: x"], check=True)
        log(repo, "cl", "intake", "task", env=env)
        (state(repo, "cl") / "agent.json").write_text(json.dumps(
            {"slug": "cl", "runner": "cli", "workspace": str(wt), "branch": "cursor/cl", "baseSha": head}))
        if granted:
            assert cli(repo, ["grant", "branch-delete", "allow", "--source", "owner 2026-11-11: 'apply all'"], env)[0] == 0
        return repo, run, wt, env

    @staticmethod
    def _squash_merge(repo, run):
        (repo / "new.py").write_text("x = 1\n")
        run("add", "new.py")
        run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "feat: x (#1)")

    def test_an_unmerged_branch_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = self._run_with_branch(tmp)
            code, out, err = cli(repo, ["cleanup", "--slug", "cl"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^kept\s+cursor/cl: not merged into main")
            self.assertTrue(wt.exists())

    def test_a_squash_merged_branch_and_its_worktree_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = self._run_with_branch(tmp)
            self._squash_merge(repo, run)
            code, out, err = cli(repo, ["cleanup", "--slug", "cl"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^removed\s+cursor/cl")
            self.assertFalse(wt.exists())
            self.assertEqual(run("branch", "--list", "cursor/cl"), "")
            self.assertEqual(keryx.read_log_rows(state(repo, "cl"))[-1][1][1], "cleanup")
            self.assertTrue((state(repo, "cl") / "decisions.tsv").exists(), "the run's record stays")

    def test_without_the_grant_nothing_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = self._run_with_branch(tmp, granted=False)
            self._squash_merge(repo, run)
            code, out, err = cli(repo, ["cleanup", "--slug", "cl"], env)
            self.assertEqual(code, 1, out + err)
            self.assertRegex(out, r"(?m)^would remove\s+cursor/cl")
            self.assertIn("branch-delete", out + err)
            self.assertTrue(wt.exists())
            self.assertNotEqual(run("branch", "--list", "cursor/cl"), "")

    def test_a_dry_run_removes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = self._run_with_branch(tmp)
            self._squash_merge(repo, run)
            code, out, err = cli(repo, ["cleanup", "--slug", "cl", "--dry-run"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^would remove\s+cursor/cl")
            self.assertTrue(wt.exists())

    def test_uncommitted_work_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = self._run_with_branch(tmp)
            self._squash_merge(repo, run)
            (wt / "scratch.txt").write_text("wip\n")
            code, out, err = cli(repo, ["cleanup", "--slug", "cl"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^kept\s+cursor/cl: uncommitted")
            self.assertTrue(wt.exists())


if __name__ == "__main__":
    unittest.main()
