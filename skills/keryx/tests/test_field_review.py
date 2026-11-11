"""Findings of the fresh review of the field fixes (two finders), each pinned by a test that failed first."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402
from test_field_finish import log, shipped_m_run, state  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

GRANT = ["grant", "branch-delete", "allow", "--source", "owner 2026-11-11: 'apply all'"]
ID = ["-c", "user.email=t@t", "-c", "user.name=t"]


def merged_branch(tmp, slug, workspace=None):
    """A run whose executor branch holds one commit that main got as a squash merge; the grant is given."""
    repo, run, base, head = _two_commit_repo(tmp)
    env = machine(tmp)
    wt = workspace or repo / ".worktrees" / f"cursor-{slug}"
    run("worktree", "add", "-q", "-b", f"cursor/{slug}", str(wt), head)
    (wt / f"{slug}.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(wt), "add", f"{slug}.py"], check=True)
    subprocess.run(["git", "-C", str(wt), *ID, "commit", "-q", "-m", "feat: x"], check=True)
    (repo / f"{slug}.py").write_text("x = 1\n")
    run("add", f"{slug}.py")
    run(*ID, "commit", "-q", "-m", "feat: x (#1)")
    log(repo, slug, "intake", "task", env=env)
    (state(repo, slug) / "agent.json").write_text(json.dumps(
        {"slug": slug, "runner": "cli", "workspace": str(wt), "branch": f"cursor/{slug}", "baseSha": head}))
    assert cli(repo, GRANT, env)[0] == 0
    return repo, run, wt, env


class CleanupNeverLosesCommits(unittest.TestCase):
    def test_a_worktree_parked_on_an_unmerged_commit_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = merged_branch(tmp, "dt")
            subprocess.run(["git", "-C", str(wt), "checkout", "-q", "--detach"], check=True)
            (wt / "wip.py").write_text("y = 2\n")
            subprocess.run(["git", "-C", str(wt), "add", "wip.py"], check=True)
            subprocess.run(["git", "-C", str(wt), *ID, "commit", "-q", "-m", "wip"], check=True)
            code, out, err = cli(repo, ["cleanup", "--slug", "dt"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^kept\s+cursor/dt: its checkout is at a commit that is not merged")
            self.assertTrue((wt / "wip.py").exists())
            self.assertNotEqual(run("branch", "--list", "cursor/dt"), "")

    def test_a_branch_checked_out_in_another_worktree_is_kept_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, other, env = merged_branch(tmp, "el", workspace=Path(tmp) / "repo" / ".worktrees" / "other")
            recorded = repo / ".worktrees" / "cursor-el"
            run("worktree", "add", "-q", "--detach", str(recorded), "cursor/el")
            (state(repo, "el") / "agent.json").write_text(json.dumps(
                {"slug": "el", "runner": "cli", "workspace": str(recorded), "branch": "cursor/el", "baseSha": "x"}))
            code, out, err = cli(repo, ["cleanup", "--slug", "el"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^kept\s+cursor/el: checked out in ")
            self.assertTrue(recorded.exists(), "nothing of a kept branch is removed")
            self.assertTrue(other.exists())

    def test_a_worktree_outside_keryxs_folder_is_never_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = merged_branch(tmp, "ow", workspace=Path(tmp) / "elsewhere")
            code, out, err = cli(repo, ["cleanup", "--slug", "ow"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^kept\s+cursor/ow: .*not one of keryx's worktrees")
            self.assertTrue(wt.exists())

    def test_merged_into_local_main_counts_when_origin_is_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            bare = Path(tmp) / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
            run("remote", "add", "origin", str(bare))
            run("push", "-q", "origin", "main")
            run("remote", "set-head", "origin", "main")
            env = machine(tmp)
            wt = repo / ".worktrees" / "cursor-lm"
            run("worktree", "add", "-q", "-b", "cursor/lm", str(wt), head)
            (wt / "lm.py").write_text("x = 1\n")
            subprocess.run(["git", "-C", str(wt), "add", "lm.py"], check=True)
            subprocess.run(["git", "-C", str(wt), *ID, "commit", "-q", "-m", "feat: x"], check=True)
            run(*ID, "merge", "-q", "--no-ff", "-m", "Merge the work", "cursor/lm")
            log(repo, "lm", "intake", "task", env=env)
            (state(repo, "lm") / "agent.json").write_text(json.dumps(
                {"slug": "lm", "runner": "cli", "workspace": str(wt), "branch": "cursor/lm", "baseSha": head}))
            self.assertEqual(cli(repo, GRANT, env)[0], 0)
            code, out, err = cli(repo, ["cleanup", "--slug", "lm"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^removed\s+cursor/lm")


class FinishShapesAndExecutorRounds(unittest.TestCase):
    def _round(self, repo, slug, mode):
        folder = state(repo, slug) / "rounds" / f"{len(list((state(repo, slug) / 'rounds').glob('*'))) + 1:02d}" \
            if (state(repo, slug) / "rounds").exists() else state(repo, slug) / "rounds" / "01"
        folder.mkdir(parents=True)
        (folder / "prompt.md").write_text(f"Mode: {mode}\nGoal: x\n")

    def _qa_run(self, repo, slug):
        log(repo, slug, "intake", "deeper QA")
        log(repo, slug, "finish", "QA done", "done")
        (state(repo, slug) / "qa").mkdir()
        (state(repo, slug) / "qa" / "QA.md").write_text("181 cases, evidence in qa/api\n")

    def test_qa_only_with_a_round_that_wrote_code_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self._qa_run(repo, "qc")
            self._round(repo, "qc", "QA")
            self._round(repo, "qc", "FIX")
            code, out, err = cli(repo, ["finish", "--slug", "qc", "--head", head, "--qa-only"])
            self.assertEqual(code, 1, out + err)
            self.assertIn("executor round", out)

    def test_qa_only_with_qa_rounds_alone_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self._qa_run(repo, "qq")
            self._round(repo, "qq", "QA")
            self._round(repo, "qq", "QA")
            code, out, err = cli(repo, ["finish", "--slug", "qq", "--head", head, "--qa-only"])
            self.assertEqual(code, 0, out + err)

    def test_an_umbrella_with_rounds_of_its_own_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "ur", "intake", "two slices")
            (state(repo, "ur") / "PLAN.md").write_text("## Slices\n- ur-a: owns a\n")
            log(repo, "ur-a", "intake", "slice a")
            (state(repo, "ur-a") / "finished.json").write_text(json.dumps({"slug": "ur-a"}))
            log(repo, "ur", "finish", "shipped", "live")
            self._round(repo, "ur", "IMPLEMENT")
            code, out, err = cli(repo, ["finish", "--slug", "ur", "--head", head, "--umbrella"])
            self.assertEqual(code, 1, out + err)
            self.assertIn("executor round", out)

    def test_another_runs_qa_file_is_not_this_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "foo", "intake", "an earlier, separate run")
            (state(repo, "foo") / "qa").mkdir()
            (state(repo, "foo") / "qa" / "QA.md").write_text("QA of foo\n")
            shipped_m_run(repo, "foo-bar", base, head)
            code, out, err = cli(repo, ["finish", "--slug", "foo-bar", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("missing  the QA file", out)


class WhatRunningSessionsStillType(unittest.TestCase):
    def test_a_size_row_may_say_why_after_the_letter(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            d = state(repo, "sz")
            for text, letter in (("L — node join, three services", "L"), ("M (release phase included)", "M"),
                                 ("S: one obvious place", "S"), ("m", "M")):
                self.assertEqual(cli(repo, ["log", "--slug", "sz", "size", text, "why", "-", "-"])[0], 0, text)
                self.assertEqual(keryx.run_size(keryx.read_log_rows(d)), letter, text)
            for text in ("Small", "XL", "large", ""):
                self.assertEqual(cli(repo, ["log", "--slug", "sz", "size", text, "why", "-", "-"])[0], 1, text)

    def test_minor_deferred_as_the_phase_becomes_a_deferred_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            code, out, err = cli(repo, ["log", "--slug", "md", "minor (deferred)", "overlay runner", "why", "ev",
                                        "later"])
            self.assertEqual(code, 0, out + err)
            rows = keryx.read_log_rows(state(repo, "md"))
            self.assertEqual((rows[-1][1][1], rows[-1][1][2]), ("note", "minor (deferred): overlay runner"))
            self.assertEqual(len(keryx.deferred_rows(rows)), 1)


class OwnerCommandsStayTheOwners(unittest.TestCase):
    """An executor runs with the user's rights; a grant it wrote would read as the owner's word."""

    INSIDE = {"KERYX_EXECUTOR": "1"}

    def test_every_executor_environment_carries_the_marker(self):
        self.assertEqual(keryx.cli_env({"PATH": "/usr/bin"})["KERYX_EXECUTOR"], "1")
        self.assertEqual(keryx.codex_env({"PATH": "/usr/bin", "HOME": "/no-such-root-keryx"}, "/run/home", "k")
                         ["KERYX_EXECUTOR"], "1")
        self.assertEqual(keryx.EXECUTOR_ENV, {"KERYX_EXECUTOR": "1"})
        self.assertIn("Edit(~/.config/keryx/**)", keryx.GLM_DENY)

    def test_inside_an_executor_round_the_owners_commands_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = {**machine(tmp), **self.INSIDE}
            for argv in (["grant", "merge", "allow", "--source", "owner"], ["repo", "--ci", "make ci"],
                         ["repo", "--report", "local"], ["answer", "--slug", "x", "1", "yes"],
                         ["cleanup", "--slug", "x"]):
                code, out, err = cli(repo, argv, env)
                self.assertEqual(code, 1, argv)
                self.assertIn("executor", err, argv)
            self.assertFalse((Path(tmp) / "cfg" / "grants.json").exists())
            self.assertFalse((repo / ".keryx" / "config.json").exists())
            for argv in (["grants"], ["recall"], ["inbox"], ["repo"],
                         ["log", "--slug", "x", "note", "seen", "why", "ev", "ok"]):
                self.assertEqual(cli(repo, argv, env)[0], 0, argv)

    def test_a_ci_command_that_looks_like_a_credential_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            code, out, err = cli(repo, ["repo", "--ci", "TOKEN=" + "a1b2c3d4" * 5 + " make ci"], machine(tmp))
            self.assertEqual(code, 1, out + err)
            self.assertFalse((repo / ".keryx" / "config.json").exists())


if __name__ == "__main__":
    unittest.main()
