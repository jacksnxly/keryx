"""A run in flight keeps its worktree: a branch with no commit of its own is an ancestor of its target, so a round
that has not committed yet would count as merged."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402,F401
from test_field_adapter import cli, machine  # noqa: E402
from test_field_finish import log, state  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

GRANT = ["grant", "branch-delete", "allow", "--source", "owner 2026-11-11: 'apply all'"]


def fresh_branch(tmp, run_json):
    """A run whose executor branch has no commit of its own yet, so it is an ancestor of main."""
    repo, run, base, head = _two_commit_repo(tmp)
    env = machine(tmp)
    wt = repo / ".worktrees" / "cursor-live"
    run("worktree", "add", "-q", "-b", "cursor/live", str(wt), head)
    log(repo, "live", "intake", "task", env=env)
    (state(repo, "live") / "agent.json").write_text(json.dumps(
        {"slug": "live", "runner": "cli", "workspace": str(wt), "branch": "cursor/live", "baseSha": head}))
    (state(repo, "live") / "rounds" / "01").mkdir(parents=True)
    (state(repo, "live") / "rounds" / "01" / "run.json").write_text(json.dumps(run_json))
    assert cli(repo, GRANT, env)[0] == 0
    return repo, run, wt, env


class ARunInFlight(unittest.TestCase):
    def test_a_branch_whose_round_is_running_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = fresh_branch(tmp, {"runner": "cli", "pid": os.getpid(), "status": "RUNNING"})
            code, out, err = cli(repo, ["cleanup", "--slug", "live"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^kept\s+cursor/live: a round is still running")
            self.assertTrue(wt.exists())
            self.assertNotEqual(run("branch", "--list", "cursor/live"), "")

    def test_a_dispatched_subagent_round_counts_as_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = fresh_branch(tmp, {"status": "DISPATCHED", "startedAt": "2026-11-11T00:00:00Z"})
            code, out, err = cli(repo, ["cleanup", "--slug", "live"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^kept\s+cursor/live: a round is still running")
            self.assertTrue(wt.exists())

    def test_once_the_round_has_ended_the_empty_branch_goes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, wt, env = fresh_branch(tmp, {"runner": "cli", "pid": 2 ** 22 + 7, "status": "FINISHED"})
            code, out, err = cli(repo, ["cleanup", "--slug", "live"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^removed\s+cursor/live")
            self.assertFalse(wt.exists())


if __name__ == "__main__":
    unittest.main()
