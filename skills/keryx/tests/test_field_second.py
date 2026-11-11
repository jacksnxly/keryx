"""Findings of the second fresh review, each pinned by a test that failed first."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402,F401
from test_field_finish import log, state  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402


class SizeRows(unittest.TestCase):
    def test_a_resize_arrow_or_a_plus_is_no_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            for text in ("S+", "S → M", "S -> M", "S/M", "S+: nearly M", "S or M"):
                self.assertEqual(cli(repo, ["log", "--slug", "sz", "size", text, "why", "-", "-"])[0], 1, text)
            self.assertFalse((state(repo, "sz") / "decisions.tsv").exists())
            for text, letter in (("Size M", "M"), ("size L — it grew", "L"), ("S - one obvious place", "S"),
                                 ("M, several files", "M")):
                self.assertEqual(cli(repo, ["log", "--slug", "sz", "size", text, "why", "-", "-"])[0], 0, text)
                self.assertEqual(keryx.run_size(keryx.read_log_rows(state(repo, "sz"))), letter, text)

    def test_an_old_row_that_does_not_parse_is_no_size_and_never_the_s_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "rs", "size", "S")
            keryx.append_log(state(repo, "rs"), "size", "S → M", "it grew", "-", "-")  # as a log from before holds it
            self.assertIsNone(keryx.run_size(keryx.read_log_rows(state(repo, "rs"))))
            log(repo, "rs", "finish", "merged abc1234", "live")
            code, out, err = cli(repo, ["finish", "--slug", "rs", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("fresh review", out)


class SliceRounds(unittest.TestCase):
    def test_size_s_with_a_slice_that_has_executor_rounds_is_not_s(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "sp", "intake", "task")
            (state(repo, "sp") / "PLAN.md").write_text("## Slices\n- sp-a: owns a\n")
            log(repo, "sp", "size", "S")
            log(repo, "sp", "finish", "merged abc1234", "live")
            log(repo, "sp-a", "intake", "the slice")
            (state(repo, "sp-a") / "rounds" / "01").mkdir(parents=True)
            (state(repo, "sp-a") / "rounds" / "01" / "prompt.md").write_text("Mode: IMPLEMENT\n")
            code, out, err = cli(repo, ["finish", "--slug", "sp", "--head", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("executor round", out)

    def test_qa_only_with_a_slice_that_wrote_code_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "qs", "intake", "deeper QA")
            (state(repo, "qs") / "PLAN.md").write_text("## Slices\n- qs-api: the API cases\n")
            log(repo, "qs", "finish", "QA done", "done")
            (state(repo, "qs") / "qa").mkdir()
            (state(repo, "qs") / "qa" / "QA.md").write_text("cases\n")
            log(repo, "qs-api", "intake", "the slice")
            (state(repo, "qs-api") / "rounds" / "01").mkdir(parents=True)
            (state(repo, "qs-api") / "rounds" / "01" / "prompt.md").write_text("Mode: FIX\n")
            code, out, err = cli(repo, ["finish", "--slug", "qs", "--head", head, "--qa-only"])
            self.assertEqual(code, 1, out + err)
            self.assertIn("executor round", out)


class ReportInto(unittest.TestCase):
    def test_into_a_path_that_does_not_exist_is_refused_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log(repo, "ri", "intake", "task")
            code, out, err = cli(repo, ["report", "--slug", "ri", "--head", head, "--into", str(Path(tmp) / "nope")])
            self.assertEqual(code, 1, out + err)
            self.assertIn("nope", err)


class UnrelatedRunsShareNothing(unittest.TestCase):
    def test_locked_on_a_run_that_merely_shares_a_prefix_finds_no_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            runs = repo / ".keryx" / "runs"
            log(repo, "big", "intake", "an earlier run that names no slice")
            (runs / "big" / "locked").mkdir()
            (runs / "big" / "locked" / "01.json").write_text(
                json.dumps({"path": "app.py", "block": "def f():\n    return 2"}))
            (runs / "big-other" / "rounds" / "01").mkdir(parents=True)
            (runs / "big-other" / "agent.json").write_text(json.dumps(
                {"slug": "big-other", "runner": "cli", "workspace": str(repo), "branch": "main", "baseSha": base}))
            code, out, err = cli(repo, ["locked", "--slug", "big-other", "--ref", head])
            self.assertEqual(code, 1, out + err)
            self.assertIn("no locked test blocks registered", out)


if __name__ == "__main__":
    unittest.main()
