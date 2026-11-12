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
    """A table, as the owner wants it ("it should be a table"), built so the terminal keeps drawing it: the UI
    draws a grid while no cell needs more than about four lines (a 97-character cell held at 50 columns, a
    164-character one came out as stacked "Header: value" records at 60), so every cell stays within 96 shown
    characters, the labels are single words that cannot wrap, and the decisions are listed under the table."""

    def test_the_block_shows_the_plan_and_the_place_in_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            self.assertEqual(block(repo, env), [
                "| Step | 3 of 7 · `■■■■ ■■■■ ▶▶▶▶ ···· ···· ···· ····` |",
                "|---|---|",
                "| **Plan** | Intake → Plan → **[Part A]** → Build → QA → Review → Merge |",
                "| **Live** | round 02 runs |",
                "| **Waiting** | Nothing |",
                "| **Next** | check it |",
            ])

    def test_the_decisions_are_listed_under_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            self.assertEqual(cli(repo, ["ask", "--slug", "pg", "Which bar?", "--option", "A: segments", "--option",
                                        "B: blocks", "--recommend", "A", "--blocks", "the merge"], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[4], "| **Waiting** | 1 decision, listed below |")
            self.assertEqual(lines[5], "| **Next** | check it |")
            self.assertEqual(lines[6:], [
                "",
                "1. **Which bar?** (blocks: the merge)",
                "   - **A: segments** (recommended)",
                "   - B: blocks",
            ])
            self.assertEqual(cli(repo, ["ask", "--slug", "pg", "And the colour?"], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[4], "| **Waiting** | 2 decisions, listed below |")
            self.assertEqual(lines[-1], "2. **And the colour?**")

    def test_another_runs_question_is_not_this_sessions_to_show(self):
        """Seen 2026-11-12: one run asked 10 questions, four parallel sessions of the repository each showed them,
        and the owner answered once and then told three more sessions "already answered"."""
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            self.assertEqual(cli(repo, ["ask", "--slug", "other-run", "Rotate the secret?"], env)[0], 0)
            self.assertEqual(cli(repo, ["ask", "Between runs?"], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[4], "| **Waiting** | Nothing |")
            self.assertEqual(len(lines), 6)
            inbox = cli(repo, ["inbox"], env)[1]
            self.assertIn("Rotate the secret?", inbox)
            self.assertIn("Between runs?", inbox)

    def test_a_slices_question_belongs_to_its_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            (repo / ".keryx" / "runs" / "pg" / "PLAN.md").write_text("## Slices\n- pg-api: owns the API\n")
            self.assertEqual(cli(repo, ["ask", "--slug", "pg-api", "Which limit?"], env)[0], 0)
            self.assertEqual(cli(repo, ["ask", "--slug", "pg-unnamed", "Not a slice?"], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[4], "| **Waiting** | 1 decision, listed below |")
            self.assertEqual(lines[6:], ["", "1. **Which limit?**"])

    def test_questions_keep_their_order_oldest_first_whatever_the_folders_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            (repo / ".keryx" / "runs" / "pg" / "PLAN.md").write_text("## Slices\n- pg-aa\n- pg-zz\n- pg-mm\n")
            head = "ts\tphase\tdecision\twhy\tevidence\tresult\n"
            for slug, stamp, question in (("pg-aa", "2099-02-01T00:00:00Z", "Newer?"),
                                          ("pg-zz", "2099-01-01T00:00:00Z", "Older?"),
                                          ("pg-mm", "2099-01-15T00:00:00Z", "Middle?")):
                folder = repo / ".keryx" / "runs" / slug
                folder.mkdir(parents=True)
                (folder / "decisions.tsv").write_text(f"{head}{stamp}\twaiting\towner: {question}\t-\t-\topen\n")
            lines = block(repo, env)
            self.assertEqual(lines[7:], ["1. **Older?**", "2. **Middle?**", "3. **Newer?**"])
            inbox = cli(repo, ["inbox"], env)[1].splitlines()
            self.assertEqual([line.rsplit("  ", 1)[-1] for line in inbox], ["Older?", "Middle?", "Newer?"])

    def test_a_pipe_or_a_line_break_in_the_text_cannot_break_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--live", "a | b\nc", "--next", "d"], env)
            self.assertEqual(code, 0, out + err)
            self.assertEqual(out.splitlines()[3], "| **Live** | a \\| b c |")

    def test_a_cell_too_long_for_the_terminal_to_keep_the_table_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            fits = "x" * 96
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--live", fits, "--next", "**" + fits + "**"], env)
            self.assertEqual(code, 0, out + err)
            for flag in ("--live", "--next"):
                argv = ["progress", "--slug", "pg", "--live", "ok", "--next", "ok"]
                argv[argv.index(flag) + 1] = "x" * 97
                code, out, err = cli(repo, argv, env)
                self.assertEqual(code, 1, flag)
                self.assertEqual(out, "", flag)
                self.assertIn("96", err, flag)
                self.assertIn(flag, err, flag)

    def test_a_long_plan_folds_what_is_done_so_its_row_stays_short(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            names = [f"Implementation part {chr(65 + i)}" for i in range(12)]
            self.assertEqual(cli(repo, ["steps", "--slug", "pg", *names], env)[0], 0)
            for n in range(1, 9):
                self.assertEqual(cli(repo, ["step", "--slug", "pg", str(n), "done"], env)[0], 0)
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "9", "running"], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[2],
                             "| **Plan** | 8 done → **[Implementation part I]** → Implementation part J → 2 more |")
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "9", "done"], env)[0], 0)
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "10", "done"], env)[0], 0)
            self.assertEqual(block(repo, env)[2], "| **Plan** | 10 done → **[Implementation part K]** → "
                                                  "Implementation part L |")
            for line in lines[2:6]:
                shown = line.split(" | ", 1)[1].rstrip(" |").replace("**", "").replace("`", "")
                self.assertLessEqual(len(shown), 96, line)

    def test_everything_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp, done=("1", "2", "3", "4", "5", "6", "7"), running=None)
            lines = block(repo, env)
            self.assertEqual(lines[0], "| Step | 7 of 7 done · `■■■■ ■■■■ ■■■■ ■■■■ ■■■■ ■■■■ ■■■■` |")
            self.assertEqual(lines[2], "| **Plan** | Intake → Plan → Part A → Build → QA → Review → Merge |")

    def test_a_failed_step_is_where_the_run_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp, running=None)
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "3", "failed", "--note", "usage limit"], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[0], "| Step | 3 of 7, failed · `■■■■ ■■■■ xxxx ···· ···· ···· ····` |")
            self.assertIn("**[Part A]**", lines[2])

    def test_nothing_running_points_at_the_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp, running=None)
            lines = block(repo, env)
            self.assertEqual(lines[0], "| Step | 3 of 7 · `■■■■ ■■■■ ···· ···· ···· ···· ····` |")
            self.assertIn("**[Part A]**", lines[2])


class FullPlan(unittest.TestCase):
    """The whole plan stays a numbered list: four columns of free text are what a narrow terminal stacks."""

    def test_the_full_plan_is_a_numbered_list_of_every_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--full"], env)
            self.assertEqual(code, 0, out + err)
            self.assertFalse([line for line in out.splitlines() if line.startswith("|")])
            self.assertEqual(out.splitlines(), [
                "**The plan** · step 3 of 7",
                "",
                "1. Intake — done",
                "2. Plan — done",
                "3. **Part A: adapter — running** · round 02 on the executor",
                "4. Build — to do",
                "5. QA — to do",
                "6. Review — to do",
                "7. Merge — to do",
            ])

    def test_the_full_plan_of_a_finished_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp, done=("1", "2", "3", "4", "5", "6", "7"), running=None)
            lines = cli(repo, ["progress", "--slug", "pg", "--full"], env)[1].splitlines()
            self.assertEqual(lines[0], "**The plan** · 7 of 7 done")
            self.assertEqual(lines[-1], "7. Merge — done")


class Steps(unittest.TestCase):
    def test_declaring_again_keeps_what_is_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            again = STEPS[:4] + ["Fixes"] + STEPS[4:]
            self.assertEqual(cli(repo, ["steps", "--slug", "pg", *again], env)[0], 0)
            lines = block(repo, env)
            self.assertEqual(lines[0], "| Step | 3 of 8 · `■■■■ ■■■■ ▶▶▶▶ ···· ···· ···· ···· ····` |")
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
            self.assertEqual(out.splitlines()[0], "| Step | 2 of 12 · `■■ ·· ·· ·· ·· ·· ·· ·· ·· ·· ·· ··` |")


def second_run(repo, env, slug="tf"):
    assert cli(repo, ["log", "--slug", slug, "intake", "task", "why", "ev", "ok"], env)[0] == 0
    assert cli(repo, ["steps", "--slug", slug, "Check", "Fix", "Ship"], env)[0] == 0
    assert cli(repo, ["step", "--slug", slug, "1", "done"], env)[0] == 0
    assert cli(repo, ["step", "--slug", slug, "Fix", "running"], env)[0] == 0


class SeveralRuns(unittest.TestCase):
    """Seen 2026-11-12: a session that drove two runs ran `progress` for each, then typed one three-row table by
    hand for its message, without a bar: the block was per run, and the owner asked where the bar had gone."""

    def test_one_block_for_two_runs_keeps_both_bars(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            second_run(repo, env)
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--slug", "tf", "--live", "both building",
                                        "--next", "check them"], env)
            self.assertEqual(code, 0, out + err)
            self.assertEqual(out.splitlines(), [
                "| Step | 2 runs |",
                "|---|---|",
                "| **pg** | 3 of 7 · `■■■■ ■■■■ ▶▶▶▶ ···· ···· ···· ····` · Part A |",
                "| **tf** | 2 of 3 · `■■■■ ▶▶▶▶ ····` · Fix |",
                "| **Live** | both building |",
                "| **Waiting** | Nothing |",
                "| **Next** | check them |",
            ])

    def test_the_questions_of_every_run_named_are_listed_with_their_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            second_run(repo, env)
            self.assertEqual(cli(repo, ["ask", "--slug", "pg", "Which bar?", "--blocks", "the merge"], env)[0], 0)
            self.assertEqual(cli(repo, ["ask", "--slug", "tf", "Ship today?", "--option", "A: yes", "--option",
                                        "B: no", "--recommend", "A"], env)[0], 0)
            self.assertEqual(cli(repo, ["ask", "--slug", "other", "Not mine?"], env)[0], 0)
            lines = cli(repo, ["progress", "--slug", "pg", "--slug", "tf", "--live", "x", "--next", "y"], env)[1] \
                .splitlines()
            self.assertEqual(lines[5], "| **Waiting** | 2 decisions, listed below |")
            self.assertEqual(lines[7:], [
                "",
                "1. **Which bar?** (pg; blocks: the merge)",
                "2. **Ship today?** (tf)",
                "   - **A: yes** (recommended)",
                "   - B: no",
            ])

    def test_a_finished_run_and_a_failed_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            second_run(repo, env)
            self.assertEqual(cli(repo, ["step", "--slug", "tf", "2", "done"], env)[0], 0)
            self.assertEqual(cli(repo, ["step", "--slug", "tf", "3", "done"], env)[0], 0)
            self.assertEqual(cli(repo, ["step", "--slug", "pg", "3", "failed"], env)[0], 0)
            lines = cli(repo, ["progress", "--slug", "tf", "--slug", "pg", "--live", "x", "--next", "y"], env)[1] \
                .splitlines()
            self.assertEqual(lines[2], "| **tf** | 3 of 3 done · `■■■■ ■■■■ ■■■■` |")
            self.assertEqual(lines[3], "| **pg** | 3 of 7, failed · `■■■■ ■■■■ xxxx ···· ···· ···· ····` · Part A |")

    def test_a_run_row_stays_short_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            names = ["Check", "A step whose name is far too long to sit beside a bar of ten segments in one row", "Ship"]
            self.assertEqual(cli(repo, ["steps", "--slug", "tf", *names], env)[0], 0)
            self.assertEqual(cli(repo, ["step", "--slug", "tf", "1", "done"], env)[0], 0)
            lines = cli(repo, ["progress", "--slug", "pg", "--slug", "tf", "--live", "x", "--next", "y"], env)[1] \
                .splitlines()
            self.assertEqual(lines[3], "| **tf** | 2 of 3 · `■■■■ ···· ····` |")

    def test_the_whole_plan_is_of_one_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            second_run(repo, env)
            self.assertEqual(cli(repo, ["progress", "--slug", "pg", "--slug", "tf", "--full"], env)[0], 1)


class NoRun(unittest.TestCase):
    def test_a_session_without_a_run_gets_its_three_rows_from_the_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            code, out, err = cli(repo, ["progress", "--live", "the page on staging", "--next", "nothing scheduled"], env)
            self.assertEqual(code, 0, out + err)
            self.assertEqual(out.splitlines(), [
                "| Step | no run |",
                "|---|---|",
                "| **Live** | the page on staging |",
                "| **Waiting** | Nothing |",
                "| **Next** | nothing scheduled |",
            ])
            out = cli(repo, ["progress", "--live", "x", "--waiting", "your pick: A or B", "--next", "y"], env)[1]
            self.assertEqual(out.splitlines()[3], "| **Waiting** | your pick: A or B |")
            self.assertEqual(cli(repo, ["progress", "--live", "x", "--waiting", "w" * 97, "--next", "y"], env)[0], 1)
            self.assertEqual(cli(repo, ["progress", "--full"], env)[0], 1)


class NeverRetyped(unittest.TestCase):
    def test_the_command_says_to_paste_the_block_as_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--live", "x", "--next", "y"], env)
            self.assertIn("as printed", err)
            self.assertNotIn("as printed", out)


if __name__ == "__main__":
    unittest.main()
