"""The plan and where the run is in it: steps declared once, ticked as they end, and one block that closes a
message, printed from the run's own record (the owner: "i never know what is planned and where we exactly are")."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402,F401
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

STEPS = ["Intake", "Plan", "Part A: adapter", "Build", "QA", "Review", "Merge"]


def started(tmp, done=("1", "2"), running="Part A"):
    """A run with its steps declared, the first two done and one running."""
    repo, run, base, head = _two_commit_repo(tmp)
    env = machine(tmp)
    assert cli(repo, ["log", "--slug", "pg", "intake", "task", "why", "ev", "ok"], env)[0] == 0
    code, out, err = cli(repo, ["steps", "--slug", "pg", *STEPS], env)
    assert code == 0, out + err
    for n in done:
        assert cli(repo, ["step", "--slug", "pg", n, "done"], env)[0] == 0
    if running:
        code, out, err = cli(repo, ["step", "--slug", "pg", running, "running", "--note", "round 02 on the executor"],
                             env)
        assert code == 0, out + err
    return repo, env


def block(repo, env, *extra):
    code, out, err = cli(repo, ["progress", "--slug", "pg", "--live", "round 02 runs", "--next", "check it", *extra],
                         env)
    assert code == 0, out + err
    return out.splitlines()


class ClosingBlock(unittest.TestCase):
    def test_the_block_shows_the_plan_and_the_place_in_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            self.assertEqual(block(repo, env), [
                "| Step 3 of 7 | `■■■■ ■■■■ ▶▶▶▶ ···· ···· ···· ····` |",
                "|---|---|",
                "| **Plan** | Intake → Plan → **[ Part A ]** → Build → QA → Review → Merge |",
                "| **Live** | round 02 runs |",
                "| **Waiting on you** | Nothing |",
                "| **Next** | check it |",
            ])

    def test_the_waiting_row_is_the_repositorys_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            self.assertEqual(cli(repo, ["ask", "--slug", "pg", "Which bar?", "--option", "A: segments", "--option",
                                        "B: blocks", "--recommend", "A"], env)[0], 0)
            self.assertEqual(block(repo, env)[4],
                             "| **Waiting on you** | **Which bar?** · **A: segments** (recommended) · B: blocks |")
            self.assertEqual(cli(repo, ["ask", "Rotate the secret?"], env)[0], 0)
            row = block(repo, env)[4]
            self.assertIn("**Which bar?**", row)
            self.assertIn("**Rotate the secret?**", row)
            self.assertIn("2 decisions", row)

    def test_a_pipe_in_the_text_cannot_break_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--live", "a | b", "--next", "c"], env)
            self.assertEqual(code, 0, out + err)
            self.assertEqual(out.splitlines()[3], "| **Live** | a \\| b |")

    def test_everything_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp, done=("1", "2", "3", "4", "5", "6", "7"), running=None)
            lines = block(repo, env)
            self.assertEqual(lines[0], "| 7 of 7 done | `■■■■ ■■■■ ■■■■ ■■■■ ■■■■ ■■■■ ■■■■` |")
            self.assertEqual(lines[2], "| **Plan** | Intake → Plan → Part A → Build → QA → Review → Merge |")

    def test_a_failed_step_is_where_the_run_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp, running=None)
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "3", "failed", "--note", "usage limit"], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[0], "| Step 3 of 7 | `■■■■ ■■■■ xxxx ···· ···· ···· ····` |")
            self.assertIn("**[ Part A ]**", lines[2])

    def test_nothing_running_points_at_the_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp, running=None)
            lines = block(repo, env)
            self.assertEqual(lines[0], "| Step 3 of 7 | `■■■■ ■■■■ ···· ···· ···· ···· ····` |")
            self.assertIn("**[ Part A ]**", lines[2])


class FullPlan(unittest.TestCase):
    def test_the_full_plan_is_a_table_of_every_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--full"], env)
            self.assertEqual(code, 0, out + err)
            lines = out.splitlines()
            self.assertEqual(lines[:2], ["| # | Step | Status | Note |", "|---|---|---|---|"])
            self.assertEqual(lines[2], "| 1 | Intake | done |  |")
            self.assertEqual(lines[4], "| 3 | **Part A: adapter** | **running** | round 02 on the executor |")
            self.assertEqual(lines[5], "| 4 | Build | to do |  |")
            self.assertEqual(len(lines), 9)


class Steps(unittest.TestCase):
    def test_declaring_again_keeps_what_is_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            again = STEPS[:4] + ["Fixes"] + STEPS[4:]
            self.assertEqual(cli(repo, ["steps", "--slug", "pg", *again], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[0], "| Step 3 of 8 | `■■■■ ■■■■ ▶▶▶▶ ···· ···· ···· ···· ····` |")
            self.assertIn("Build → Fixes → QA", lines[2])

    def test_a_step_is_named_by_its_number_its_name_or_the_part_before_the_colon(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp, running=None)
            for name in ("3", "Part A: adapter", "Part A", "part a"):
                self.assertEqual(cli(repo, ["step", "--slug", "pg", name, "running"], env)[0], 0, name)
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "9", "done"], env)[0], 1)
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "Deploy", "done"], env)[0], 1)
            self.assertNotEqual(cli(repo, ["step", "--slug", "pg", "3", "finished"], env)[0], 0)

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            code, out, err = cli(repo, ["progress", "--slug", "np", "--live", "x", "--next", "y"], env)
            self.assertEqual(code, 1, out + err)
            self.assertIn("keryx.py steps", err)
            self.assertEqual(cli(repo, ["steps", "--slug", "np", "Only one"], env)[0], 1)
            self.assertEqual(cli(repo, ["steps", "--slug", "np", "A", "A"], env)[0], 1, "two steps of one name")

    def test_more_than_ten_steps_get_a_shorter_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            names = [f"Step {chr(65 + i)}" for i in range(12)]
            self.assertEqual(cli(repo, ["steps", "--slug", "pg", *names], env)[0], 0)
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "1", "done"], env)[0], 0)
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--live", "x", "--next", "y"], env)
            self.assertEqual(out.splitlines()[0], "| Step 2 of 12 | `■■ ·· ·· ·· ·· ·· ·· ·· ·· ·· ·· ··` |")


if __name__ == "__main__":
    unittest.main()
