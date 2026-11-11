"""Field fixes after 1.6.0, the adapter: a round folder only for a brief that exists, a locked block that ends in
a comma, a slice that reads its run's locks, a report written where the change ships, usage limits and the
parallel cap checked before a round starts, a rate limit that `wait` retries, and run-log rows a program can read."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

DEAD_PID = 2 ** 22 + 7  # above every pid_max: never a live process
LIMITED = {"cli": {"kind": "weekly", "until": "2099-01-01T00:00:00Z", "recorded": "2026-11-11T00:00:00Z"}}


def cli(repo, argv, env=None):
    """Run keryx.py inside the repository: (exit code, stdout, stderr). An argparse refusal is its exit code."""
    old = os.getcwd()
    os.chdir(repo)
    out, err = io.StringIO(), io.StringIO()
    try:
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = keryx.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()
    finally:
        os.chdir(old)


def machine(tmp, **config):
    """A config folder of the test's own; returns the environment that points keryx at it."""
    cfg = Path(tmp) / "cfg" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"executors": ["cli", "subagent"], **config}))
    return {"KERYX_CONFIG": str(cfg)}


def brief(tmp):
    path = Path(tmp) / "brief.md"
    path.write_text("Mode: IMPLEMENT\nGoal: x\n")
    return str(path)


class RoundFolders(unittest.TestCase):
    def test_a_missing_brief_leaves_no_round_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "s"
            d.mkdir()
            with self.assertRaises(keryx.LoopError):
                keryx.new_round(d, str(Path(tmp) / "no-such-brief.md"))
            self.assertEqual(keryx.rounds(d), [])

    def test_an_empty_brief_leaves_no_round_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "s"
            d.mkdir()
            empty = Path(tmp) / "empty.md"
            empty.write_text("  \n")
            with self.assertRaises(keryx.LoopError):
                keryx.new_round(d, str(empty))
            self.assertEqual(keryx.rounds(d), [])


class LockedBlockEndingInAComma(unittest.TestCase):
    BLOCK = '    ("a", 1),\n    ("b", 2),'

    def test_the_last_row_of_a_tuple_is_found(self):
        self.assertTrue(keryx.locked_block_present(self.BLOCK, 'ROWS = (\n    ("a", 1),\n    ("b", 2),\n)\n'))
        self.assertTrue(keryx.locked_block_present(self.BLOCK, 'ROWS = (\n    ("a", 1),\n    ("b", 2),\n    ("c", 3),\n)\n'))

    def test_a_changed_row_is_still_a_change(self):
        self.assertFalse(keryx.locked_block_present(self.BLOCK, 'ROWS = (\n    ("a", 1),\n    ("b", 3),\n)\n'))


class SlicesReadTheirRun(unittest.TestCase):
    def test_inherited_takes_the_slices_own_file_then_the_run_that_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / ".keryx" / "runs"
            (runs / "big" / "locked").mkdir(parents=True)
            (runs / "big" / "PLAN.md").write_text("## Slices\n- big-api: owns the API\n")
            (runs / "big-api").mkdir()
            (runs / "big-other").mkdir()
            self.assertEqual(keryx.inherited(runs / "big-api", "PLAN.md"), runs / "big" / "PLAN.md")
            self.assertEqual(keryx.inherited(runs / "big-api", "locked"), runs / "big" / "locked")
            self.assertEqual(keryx.inherited(runs / "big-other", "PLAN.md"), runs / "big-other" / "PLAN.md",
                             "sharing a prefix does not make a slice")
            (runs / "big-api" / "PLAN.md").write_text("own")
            self.assertEqual(keryx.inherited(runs / "big-api", "PLAN.md"), runs / "big-api" / "PLAN.md")
            self.assertEqual(keryx.inherited(runs / "big", "gates.txt"), runs / "big" / "gates.txt")

    def test_locked_on_a_slice_checks_the_runs_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            runs = repo / ".keryx" / "runs"
            (runs / "big" / "locked").mkdir(parents=True)
            (runs / "big" / "PLAN.md").write_text("## Slices\n- big-api: owns the API\n")
            (runs / "big" / "locked" / "01.json").write_text(
                json.dumps({"path": "app.py", "block": "def f():\n    return 2"}))
            (runs / "big-api" / "rounds" / "01").mkdir(parents=True)
            (runs / "big-api" / "agent.json").write_text(json.dumps(
                {"slug": "big-api", "runner": "cli", "workspace": str(repo), "branch": "main", "baseSha": base}))
            code, out, err = cli(repo, ["locked", "--slug", "big-api", "--ref", head])
            self.assertEqual(code, 0, out + err)
            self.assertIn("ok       app.py", out)


class ReportGoesWhereItShips(unittest.TestCase):
    def _shipping_worktree(self, tmp):
        repo, run, base, head = _two_commit_repo(tmp)
        wt = Path(tmp) / "ship"
        run("worktree", "add", "-q", "-b", "ship", str(wt), head)
        (wt / "app.py").write_text("def f():\n    return 3\n")
        subprocess.run(["git", "-C", str(wt), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am",
                        "fix: three"], check=True)
        shipped = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], check=True, capture_output=True,
                                 text=True).stdout.strip()
        self.assertEqual(cli(repo, ["log", "--slug", "rp", "intake", "task", "why", "ev", "ok"])[0], 0)
        return repo, wt, head, shipped

    def test_the_report_lands_in_the_worktree_that_holds_the_shipped_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt, head, shipped = self._shipping_worktree(tmp)
            code, out, err = cli(repo, ["report", "--slug", "rp", "--head", shipped])
            self.assertEqual(code, 0, out + err)
            self.assertEqual(len(list((wt / "docs" / "keryx").glob("*-rp.md"))), 1)
            self.assertFalse((repo / "docs" / "keryx").exists())

    def test_into_names_the_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, wt, head, shipped = self._shipping_worktree(tmp)
            code, out, err = cli(repo, ["report", "--slug", "rp", "--head", head, "--into", str(wt)])
            self.assertEqual(code, 0, out + err)
            self.assertEqual(len(list((wt / "docs" / "keryx").glob("*-rp.md"))), 1)
            self.assertFalse((repo / "docs" / "keryx").exists())


class LimitsBeforeARound(unittest.TestCase):
    def test_create_refuses_a_runner_at_its_usage_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            (Path(tmp) / "cfg" / "limits.json").write_text(json.dumps(LIMITED))
            argv = ["create", "--slug", "lim", "--runner", "cli", "--prompt-file", brief(tmp), "--ref", head,
                    "--dry-run"]
            code, out, err = cli(repo, argv, env)
            self.assertEqual(code, 1, out + err)
            self.assertIn("usage limit until 2099-01-01T00:00:00Z", err)
            self.assertIn("subagent", err, "the refusal names the next rung")
            code, out, err = cli(repo, argv + ["--ignore-limit"], env)
            self.assertEqual(code, 0, out + err)

    def test_followup_refuses_before_it_opens_a_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            env = machine(tmp)
            (Path(tmp) / "cfg" / "limits.json").write_text(json.dumps(LIMITED))
            d = repo / ".keryx" / "runs" / "fu"
            (d / "rounds" / "01").mkdir(parents=True)
            (d / "agent.json").write_text(json.dumps(
                {"slug": "fu", "runner": "cli", "workspace": str(repo), "branch": "main", "baseSha": base,
                 "model": "m", "sessionId": "s-1"}))
            (d / "rounds" / "01" / "run.json").write_text(json.dumps({"pid": DEAD_PID, "status": "FINISHED"}))
            (d / "rounds" / "01" / "exit.code").write_text("0\n")
            with mock.patch.object(keryx, "cli_launch") as launch:
                code, out, err = cli(repo, ["followup", "--slug", "fu", "--prompt-file", brief(tmp)], env)
            self.assertEqual(code, 1, out + err)
            launch.assert_not_called()
            self.assertIn("usage limit until 2099-01-01T00:00:00Z", err)
            self.assertFalse((d / "rounds" / "02").exists())

    def test_create_refuses_past_the_parallel_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            busy = repo / ".keryx" / "runs" / "busy"
            (busy / "rounds" / "01").mkdir(parents=True)
            (busy / "agent.json").write_text(json.dumps(
                {"slug": "busy", "runner": "cli", "workspace": str(repo), "branch": "main", "baseSha": base}))
            (busy / "rounds" / "01" / "run.json").write_text(
                json.dumps({"runner": "cli", "pid": os.getpid(), "status": "RUNNING"}))
            argv = ["create", "--slug", "cap", "--runner", "cli", "--prompt-file", brief(tmp), "--ref", head,
                    "--dry-run"]
            code, out, err = cli(repo, argv, machine(tmp, maxParallel={"cli": 1}))
            self.assertEqual(code, 1, out + err)
            self.assertIn("maxParallel", err)
            self.assertIn("1 round", err)
            code, out, err = cli(repo, argv, machine(tmp, maxParallel={"cli": 2}))
            self.assertEqual(code, 0, out + err)
            code, out, err = cli(repo, argv + ["--ignore-limit"], machine(tmp, maxParallel={"cli": 1}))
            self.assertEqual(code, 0, out + err)

    def test_a_cap_must_be_a_positive_whole_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            code, out, err = cli(repo, ["executors"], machine(tmp, maxParallel={"cli": 0}))
            self.assertEqual(code, 1, out + err)
            self.assertIn("maxParallel", err)


class RateLimitRetry(unittest.TestCase):
    """A provider's 429 is a rate limit, not a spent quota: `wait` waits, opens the next round with the same
    brief and keeps watching (9 of 10 provider errors in the field were this, and 4 immediate retries failed)."""

    FAILED = [{"type": "thread.started", "thread_id": "t-1"}, {"type": "turn.started"},
              {"type": "turn.failed", "error": {"message": "exceeded retry limit, last status: 429 Too Many Requests"}}]
    DONE = [{"type": "thread.started", "thread_id": "t-1"}, {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": "Status: DONE"}},
            {"type": "turn.completed"}]

    @staticmethod
    def _round(folder, events, code):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "events.ndjson").write_text("".join(json.dumps(e) + "\n" for e in events))
        (folder / "exit.code").write_text(f"{code}\n")
        (folder / "run.json").write_text(json.dumps(
            {"runner": "mv", "pid": DEAD_PID, "status": "RUNNING", "startedAt": "2026-11-11T00:00:00Z",
             "mode": "agent"}))

    def _run(self, tmp):
        repo, run, base, head = _two_commit_repo(tmp)
        d = repo / ".keryx" / "runs" / "rl"
        self._round(d / "rounds" / "01", self.FAILED, 1)
        (d / "rounds" / "01" / "prompt.md").write_text("Mode: IMPLEMENT\nGoal: x\n")
        (d / "agent.json").write_text(json.dumps(
            {"slug": "rl", "runner": "mv", "runnerKind": "codex", "workspace": str(repo), "branch": "main",
             "baseSha": base, "model": "m", "sessionId": None}))
        return repo, d

    def test_wait_retries_a_rate_limited_round_after_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, d = self._run(tmp)
            launched = []

            def fake_launch(folder, r, agent, prompt, mode):
                launched.append((r.name, prompt))
                self._round(r, self.DONE, 0)
                return DEAD_PID

            with mock.patch.object(keryx, "cli_launch", fake_launch):
                code, out, err = cli(repo, ["wait", "--slug", "rl", "--rate-wait", "0"], machine(tmp))
            self.assertEqual(code, 0, out + err)
            self.assertEqual(launched, [("02", "Mode: IMPLEMENT\nGoal: x\n")])
            self.assertEqual(json.loads((d / "rounds" / "01" / "run.json").read_text())["status"], "ERROR")
            self.assertEqual(json.loads((d / "rounds" / "02" / "run.json").read_text())["status"], "FINISHED")
            self.assertIn("RATE_LIMIT", out)
            self.assertFalse((Path(tmp) / "cfg" / "limits.json").exists(),
                             "a rate limit a retry got past is not recorded for the machine")

    def test_a_rate_limit_that_outlasts_the_retries_ends_error_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, d = self._run(tmp)
            launched = []

            def fake_launch(folder, r, agent, prompt, mode):
                launched.append(r.name)
                self._round(r, self.FAILED, 1)
                return DEAD_PID

            with mock.patch.object(keryx, "cli_launch", fake_launch):
                code, out, err = cli(repo, ["wait", "--slug", "rl", "--rate-wait", "0", "--rate-retries", "2"],
                                     machine(tmp))
            self.assertEqual(code, 2, out + err)
            self.assertEqual(launched, ["02", "03"])
            self.assertIn("USAGE_LIMIT", out)
            self.assertIn("mv", json.loads((Path(tmp) / "cfg" / "limits.json").read_text()))


class LogRowsAProgramCanRead(unittest.TestCase):
    def test_a_decision_typed_into_the_phase_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            code, out, err = cli(repo, ["log", "--slug", "lg", "Ruling: no executor", "x", "why", "ev", "res"])
            self.assertEqual(code, 1, out + err)
            self.assertIn("phase", err)
            self.assertFalse((repo / ".keryx" / "runs" / "lg" / "decisions.tsv").exists())

    def test_ground_truth_has_one_spelling(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            for spelled in ("ground truth", "ground", "Ground-Truth"):
                self.assertEqual(cli(repo, ["log", "--slug", "lg", spelled, "fact", "why", "ev", "res"])[0], 0)
            rows = keryx.read_log_rows(repo / ".keryx" / "runs" / "lg")
            self.assertEqual([c[1] for _, c in rows], ["ground-truth"] * 3)

    def test_an_unknown_phase_is_kept_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            code, out, err = cli(repo, ["log", "--slug", "lg", "wibble", "did it", "why", "ev", "ok"])
            self.assertEqual(code, 0, out + err)
            self.assertIn("not a standard phase", err)
            self.assertEqual(keryx.read_log_rows(repo / ".keryx" / "runs" / "lg")[-1][1][1], "wibble")
            for known in ("deploy", "release", "finish-pr2", "check"):
                code, out, err = cli(repo, ["log", "--slug", "lg", known, "did it", "why", "ev", "ok"])
                self.assertEqual((code, err), (0, ""), known)

    def test_size_takes_s_m_or_l(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            d = repo / ".keryx" / "runs" / "lg"
            self.assertEqual(cli(repo, ["log", "--slug", "lg", "size", "XL", "why", "-", "-"])[0], 1)
            self.assertIsNone(keryx.run_size(keryx.read_log_rows(d)))
            self.assertEqual(cli(repo, ["log", "--slug", "lg", "size", "M", "several files", "-", "-"])[0], 0)
            self.assertEqual(keryx.run_size(keryx.read_log_rows(d)), "M")
            self.assertEqual(cli(repo, ["log", "--slug", "lg", "size", "L", "it grew", "-", "-"])[0], 0)
            self.assertEqual(keryx.run_size(keryx.read_log_rows(d)), "L")


if __name__ == "__main__":
    unittest.main()
