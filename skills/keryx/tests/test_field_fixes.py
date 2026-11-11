"""Findings on the field fixes, each pinned by a test that failed first."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
import test_field_adapter as adapter  # noqa: E402
from test_field_adapter import DEAD_PID, brief, cli, machine  # noqa: E402
from test_field_finish import log, reviewed, state  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402


class CapWithoutRuns(unittest.TestCase):
    def test_the_cap_check_survives_a_repository_without_runs_and_a_root_that_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self.assertFalse((repo / ".keryx").exists())
            env = machine(tmp, maxParallel={"cli": 1}, roots=[str(Path(tmp) / "nowhere"), tmp])
            code, out, err = cli(repo, ["create", "--slug", "first", "--runner", "cli", "--prompt-file", brief(tmp),
                                        "--ref", head, "--dry-run"], env)
            self.assertEqual(code, 0, out + err)


class NextRungByTheResetOrder(unittest.TestCase):
    def test_the_refusal_names_the_rung_executors_after_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp, executors=["glm", "cli", "subagent"], order="resets",
                          resets={"cli": {"next": "2098-01-06T00:00:00Z", "every": "month"},
                                  "glm": {"next": "2099-01-06T00:00:00Z", "every": "month"}})
            (Path(tmp) / "cfg" / "limits.json").write_text(json.dumps(
                {"glm": {"kind": "weekly", "until": "2097-01-01T00:00:00Z", "recorded": "2026-11-11T00:00:00Z"}}))
            code, after, err = cli(repo, ["executors", "--after", "glm"], env)
            self.assertEqual((code, after.strip()), (0, "subagent"), err)
            code, out, err = cli(repo, ["create", "--slug", "nr", "--runner", "glm", "--prompt-file", brief(tmp),
                                        "--ref", head, "--dry-run"], env)
            self.assertEqual(code, 1, out + err)
            self.assertIn("next rung: subagent", err)


class WaitOnARoundThatHadEnded(unittest.TestCase):
    def test_wait_never_restarts_a_round_whose_end_was_already_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            d = repo / ".keryx" / "runs" / "rl"
            adapter.RateLimitRetry._round(d / "rounds" / "01", adapter.RateLimitRetry.FAILED, 1)
            (d / "rounds" / "01" / "prompt.md").write_text("Mode: IMPLEMENT\nGoal: x\n")
            (d / "rounds" / "01" / "run.json").write_text(json.dumps(
                {"runner": "mv", "pid": DEAD_PID, "status": "ERROR", "exit": 1, "mode": "agent",
                 "endedAt": "2026-11-11T00:05:00Z",
                 "usageLimit": {"kind": "rate", "resetsAt": None, "resetsIn": "10 minutes"}}))
            (d / "agent.json").write_text(json.dumps(
                {"slug": "rl", "runner": "mv", "runnerKind": "codex", "workspace": str(repo), "branch": "main",
                 "baseSha": base, "model": "m", "sessionId": None}))
            with mock.patch.object(keryx, "cli_launch") as launch:
                code, out, err = cli(repo, ["wait", "--slug", "rl", "--rate-wait", "0"], machine(tmp))
            launch.assert_not_called()
            self.assertEqual(code, 2, out + err)
            self.assertFalse((d / "rounds" / "02").exists())


class InheritedWithoutAFolder(unittest.TestCase):
    def test_a_run_folder_that_does_not_exist_yet_is_its_own_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "nope" / "runs" / "x"
            self.assertEqual(keryx.inherited(d, "PLAN.md"), d / "PLAN.md")


class TheRefusalSaysHowToWriteIt(unittest.TestCase):
    def test_a_ruling_in_the_phases_place_gets_its_command_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            code, out, err = cli(repo, ["log", "--slug", "lg", "Ruling: no executor", "x", "why", "ev", "res"])
            self.assertEqual(code, 1, out + err)
            self.assertIn('log --slug lg ruling "Ruling: no executor"', err)
            code, out, err = cli(repo, ["log", "--slug", "lg", "minor (deferred): overlay runner", "x", "why", "ev",
                                        "res"])
            self.assertEqual(code, 1, out + err)
            self.assertIn('log --slug lg note "minor (deferred): overlay runner"', err)


class InboxAndRecallAnywhere(unittest.TestCase):
    def test_the_inbox_of_a_repository_without_runs_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            code, out, err = cli(repo, ["inbox"], machine(tmp))
            self.assertEqual(code, 0, out + err)
            self.assertIn("inbox empty", out)
            code, out, err = cli(repo, ["inbox", "--all"], machine(tmp, roots=[str(Path(tmp) / "nowhere"), tmp]))
            self.assertEqual(code, 0, out + err)
            self.assertIn("inbox empty", out)

    def test_recall_outside_a_repository_still_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = machine(tmp)
            (Path(tmp) / "cfg" / "memory.md").write_text("- 2026-11-11 the owner wants QA evidence\n")
            code, out, err = cli(tmp, ["recall"], env)
            self.assertEqual(code, 0, out + err)
            self.assertIn("the owner wants QA evidence", out)


class GrantsFailClosed(unittest.TestCase):
    def test_a_value_keryx_does_not_know_is_no_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            (Path(tmp) / "cfg" / "grants.json").write_text(json.dumps(
                {"default": {"merge": "yes", "followups": "allow"}, "repos": {"repo": {"push": True}}}))
            for action, expected in (("merge", "ask"), ("push", "ask"), ("followups", "none")):
                code, out, err = cli(repo, ["grants", "--action", action], env)
                self.assertEqual((code, out.strip()), (0, expected), action + err)
            self.assertRegex(cli(repo, ["grants"], env)[1], r"(?m)^merge\s+ask\s+\(not granted\)")


class CleanupReach(unittest.TestCase):
    GRANT = ["grant", "branch-delete", "allow", "--source", "owner 2026-11-11: 'apply all'"]

    @staticmethod
    def _branch(repo, run, head, slug):
        wt = repo / ".worktrees" / f"cursor-{slug}"
        run("worktree", "add", "-q", "-b", f"cursor/{slug}", str(wt), head)
        (wt / f"{slug}.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(wt), "add", f"{slug}.py"], check=True)
        subprocess.run(["git", "-C", str(wt), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m",
                        "feat: x"], check=True)
        (state(repo, slug) / "agent.json").write_text(json.dumps(
            {"slug": slug, "runner": "cli", "workspace": str(wt), "branch": f"cursor/{slug}", "baseSha": head}))
        return wt

    @staticmethod
    def _squash_merge(repo, run, slug):
        (repo / f"{slug}.py").write_text("x = 1\n")
        run("add", f"{slug}.py")
        run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "feat: x (#1)")

    def test_cleanup_of_a_run_without_a_loop_reaches_its_slices(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            log(repo, "big", "intake", "the run", env=env)
            (state(repo, "big") / "PLAN.md").write_text("## Slices\n- big-api: owns the API\n")
            log(repo, "big-api", "intake", "the slice", env=env)
            wt = self._branch(repo, run, head, "big-api")
            self._squash_merge(repo, run, "big-api")
            self.assertEqual(cli(repo, self.GRANT, env)[0], 0)
            code, out, err = cli(repo, ["cleanup", "--slug", "big"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^removed\s+cursor/big-api")
            self.assertFalse(wt.exists())

    def test_a_merged_branch_whose_worktree_is_already_gone_is_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            log(repo, "gone", "intake", "task", env=env)
            wt = self._branch(repo, run, head, "gone")
            self._squash_merge(repo, run, "gone")
            run("worktree", "remove", "--force", str(wt))
            self.assertEqual(cli(repo, self.GRANT, env)[0], 0)
            code, out, err = cli(repo, ["cleanup", "--slug", "gone"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^removed\s+cursor/gone")
            self.assertEqual(run("branch", "--list", "cursor/gone"), "")

    def test_the_target_branch_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            log(repo, "tb", "intake", "task", env=env)
            (state(repo, "tb") / "agent.json").write_text(json.dumps(
                {"slug": "tb", "runner": "cli", "workspace": str(Path(tmp) / "no-such-worktree"), "branch": "main",
                 "baseSha": head}))
            self.assertEqual(cli(repo, self.GRANT, env)[0], 0)
            code, out, err = cli(repo, ["cleanup", "--slug", "tb"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^kept\s+main")
            self.assertNotEqual(run("branch", "--list", "main"), "")


class FinishShapesKeepTheOldGates(unittest.TestCase):
    def test_a_hotfix_sized_s_still_needs_its_review_and_follow_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "hf", "intake", "size S · lane hotfix: prod answers 500 since 14:00")
            log(repo, "hf", "size", "S")
            log(repo, "hf", "finish", "reverted abc1234", "live")
            code, out, err = cli(repo, ["finish", "--slug", "hf", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("fresh review", out)
            self.assertIn("follow-up", out)

    def test_a_findings_only_review_needs_no_qa_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "fo", "size", "M")
            reviewed(repo, "fo", base, head)
            log(repo, "fo", "finish", "findings reported", "reported")
            code, out, err = cli(repo, ["finish", "--slug", "fo", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out + err)

    def test_extra_below_the_cap_logs_no_ruling(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "ex", "intake", "task")
            code, out, err = cli(repo, ["review-brief", "--slug", "ex", "--base", base, "--head", head, "--extra",
                                        "not needed yet"])
            self.assertEqual(code, 0, out + err)
            self.assertFalse([c for _, c in keryx.read_log_rows(state(repo, "ex")) if c[2].startswith("Ruling:")])


if __name__ == "__main__":
    unittest.main()
