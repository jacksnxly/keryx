"""Defects that QA on real run folders found in the field fixes, each pinned by a test that failed first."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402,F401
from test_field_adapter import cli, machine  # noqa: E402
from test_field_finish import log, state  # noqa: E402
from test_field_progress import started  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402


class CleanupOfABranchThatIsGone(unittest.TestCase):
    """In the field most executor branches of finished runs were already deleted, and each was printed as
    "kept … not merged"."""

    def test_a_branch_already_removed_is_gone_not_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            log(repo, "gx", "intake", "task", env=env)
            (state(repo, "gx") / "agent.json").write_text(json.dumps(
                {"slug": "gx", "runner": "cli", "workspace": str(repo / ".worktrees" / "cursor-gx"),
                 "branch": "cursor/gx", "baseSha": head}))
            code, out, err = cli(repo, ["cleanup", "--slug", "gx"], env)
            self.assertEqual(code, 0, out + err)
            self.assertRegex(out, r"(?m)^gone\s+cursor/gx")
            self.assertNotIn("not merged", out)
            self.assertNotIn("would remove", out)


class QuestionsWithOddText(unittest.TestCase):
    def test_an_option_with_a_bar_stays_one_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            self.assertEqual(cli(repo, ["ask", "--slug", "q", "Pick?", "--option", "A: yes | sure", "--option",
                                        "B: no", "--recommend", "A"], env)[0], 0)
            out = cli(repo, ["inbox"], env)[1]
            self.assertEqual([line for line in out.splitlines() if line.startswith("    ")],
                             ["    A: yes / sure (recommended)", "    B: no"])

    def test_a_question_without_options_or_blocks_prints_only_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            self.assertEqual(cli(repo, ["ask", "Rotate the secret?"], env)[0], 0)
            lines = cli(repo, ["inbox"], env)[1].splitlines()
            self.assertEqual(len(lines), 1, lines)
            self.assertTrue(lines[0].endswith("Rotate the secret?"), lines)

    def test_an_empty_question_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self.assertEqual(cli(repo, ["ask", "  "], machine(tmp))[0], 1)
            self.assertFalse((repo / ".keryx" / "runs" / "owner-inbox").exists())

    def test_what_a_question_blocks_stands_outside_the_bold(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, env = started(tmp)
            self.assertEqual(cli(repo, ["ask", "--slug", "pg", "Which bar?", "--blocks", "the merge"], env)[0], 0)
            code, out, err = cli(repo, ["progress", "--slug", "pg", "--live", "x", "--next", "y"], env)
            self.assertIn("  1. **Which bar?** (blocks: the merge)", out.splitlines())


if __name__ == "__main__":
    unittest.main()
