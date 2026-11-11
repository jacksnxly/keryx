"""Where the report lands when more than one checkout holds the shipped head (found by drafting this change's own
report: it landed in a scratch copy made for the mutation probes)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402,F401
from test_field_adapter import cli  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

ID = ["-c", "user.email=t@t", "-c", "user.name=t"]

def commit_in(wt, name):
    (wt / name).write_text("x = 1\n")
    subprocess.run(["git", "-C", str(wt), "add", name], check=True)
    subprocess.run(["git", "-C", str(wt), *ID, "commit", "-q", "-m", f"feat: {name}"], check=True)
    return subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()

class ReportWithTwoCheckoutsAtTheHead(unittest.TestCase):
    def test_the_branch_that_ships_wins_over_a_detached_scratch_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            scratch, ship = Path(tmp) / "scratch", Path(tmp) / "ship"
            run("worktree", "add", "-q", "--detach", str(scratch), head)  # listed before the shipping worktree
            run("worktree", "add", "-q", "-b", "ship", str(ship), head)
            shipped = commit_in(ship, "new.py")
            subprocess.run(["git", "-C", str(scratch), "checkout", "-q", "--detach", shipped], check=True)
            self.assertEqual(cli(repo, ["log", "--slug", "rp", "intake", "task", "why", "ev", "ok"])[0], 0)
            code, out, err = cli(repo, ["report", "--slug", "rp", "--head", shipped])
            self.assertEqual(code, 0, out + err)
            self.assertEqual(len(list((ship / "docs" / "keryx").glob("*-rp.md"))), 1)
            self.assertFalse((scratch / "docs").exists())

    def test_two_detached_copies_and_no_branch_need_into(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            one, two = Path(tmp) / "one", Path(tmp) / "two"
            run("worktree", "add", "-q", "--detach", str(one), head)
            shipped = commit_in(one, "new.py")
            run("worktree", "add", "-q", "--detach", str(two), shipped)
            self.assertEqual(cli(repo, ["log", "--slug", "rp", "intake", "task", "why", "ev", "ok"])[0], 0)
            code, out, err = cli(repo, ["report", "--slug", "rp", "--head", shipped])
            self.assertEqual(code, 1, out + err)
            self.assertIn("--into", err)
            self.assertFalse((one / "docs").exists())
            self.assertFalse((two / "docs").exists())
            code, out, err = cli(repo, ["report", "--slug", "rp", "--head", shipped, "--into", str(two)])
            self.assertEqual(code, 0, out + err)
            self.assertEqual(len(list((two / "docs" / "keryx").glob("*-rp.md"))), 1)

if __name__ == "__main__":
    unittest.main()
