"""Rows the inbox reads as the owner's word or as work to start are the coordinator's to write, never an executor's
(the second review's security pass)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402,F401
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402


class RowsOnlyTheCoordinatorWrites(unittest.TestCase):
    def test_inside_an_executor_round_no_answer_next_or_question_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = {**machine(tmp), "KERYX_EXECUTOR": "1"}
            for argv in (["log", "--slug", "x", "next", "do more", "why", "-", "safe"],
                         ["log", "--slug", "x", "answer", "row 1: yes", "why", "-", "closed"],
                         ["log", "--slug", "x", "Answer", "row 1: yes", "why", "-", "closed"],
                         ["ask", "--slug", "x", "Really?"]):
                code, out, err = cli(repo, argv, env)
                self.assertEqual(code, 1, argv)
                self.assertIn("executor", err, argv)
            self.assertFalse((repo / ".keryx" / "runs" / "x").exists())
            self.assertEqual(cli(repo, ["log", "--slug", "x", "note", "seen", "why", "ev", "ok"], env)[0], 0)

    def test_the_coordinator_still_writes_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            self.assertEqual(cli(repo, ["log", "--slug", "x", "next", "do more", "why", "-", "safe"], env)[0], 0)
            self.assertEqual(cli(repo, ["ask", "--slug", "x", "Really?"], env)[0], 0)


if __name__ == "__main__":
    unittest.main()
