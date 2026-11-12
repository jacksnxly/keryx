"""keryx.py research: an optional research agent the owner sets (Codex today); none is set by default."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

ANSWER = "pytest 9.2.0 is the latest release. Source: https://pypi.org/project/pytest/"

FAKE_CODEX = """#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CODEX_ARGS"], "w") as f:
    json.dump({{"args": args, "cwd": os.getcwd(), "stdin_tty": sys.stdin.isatty(), "stdin": sys.stdin.read()}}, f)
if os.environ.get("FAKE_CODEX_FAIL"):
    print(json.dumps({{"type": "thread.started", "thread_id": "t1"}}))
    print(json.dumps({{"type": "turn.failed", "error": {{"message": "unexpected status 500: backend down"}}}}))
    sys.exit(1)
out = args[args.index("-o") + 1]
print(json.dumps({{"type": "thread.started", "thread_id": "t1"}}))
print(json.dumps({{"type": "item.completed", "item": {{"id": "i1", "type": "agent_message", "text": {answer!r}}}}}))
print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 1, "output_tokens": 1}}}}))
with open(out, "w") as f:
    f.write({answer!r})
"""


def _config(tmp: Path, research=None) -> Path:
    data = {"executors": ["subagent"]}
    if research is not None:
        data["research"] = research
    path = tmp / "config.json"
    path.write_text(json.dumps(data))
    return path


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = keryx.main(argv)
    return code, out.getvalue(), err.getvalue()


class ResearchConfig(unittest.TestCase):
    def test_no_research_agent_by_default(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(keryx.load_config({"KERYX_CONFIG": str(Path(t) / "missing.json")})["research"])
            self.assertIsNone(keryx.load_config({"KERYX_CONFIG": str(_config(Path(t)))})["research"])

    def test_a_research_agent_is_read_with_its_optional_model_and_effort(self):
        with tempfile.TemporaryDirectory() as t:
            path = _config(Path(t), {"agent": "codex"})
            self.assertEqual(keryx.load_config({"KERYX_CONFIG": str(path)})["research"], {"agent": "codex"})
            path = _config(Path(t), {"agent": "codex", "model": "gpt-x", "effort": "high"})
            self.assertEqual(keryx.load_config({"KERYX_CONFIG": str(path)})["research"],
                             {"agent": "codex", "model": "gpt-x", "effort": "high"})

    def test_an_unknown_research_agent_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            for bad in ({"agent": "gemini"}, "codex", {"agent": "codex", "model": 3}):
                path = _config(Path(t), bad)
                with self.assertRaises(keryx.LoopError) as caught:
                    keryx.load_config({"KERYX_CONFIG": str(path)})
                self.assertIn("research", str(caught.exception))

    def test_setup_sets_and_clears_the_research_agent(self):
        with tempfile.TemporaryDirectory() as t:
            path = _config(Path(t))
            with mock.patch.dict(os.environ, {"KERYX_CONFIG": str(path)}):
                self.assertEqual(_run(["setup", "--research", "codex"])[0], 0)
                self.assertEqual(json.loads(path.read_text())["research"], {"agent": "codex"})
                self.assertEqual(json.loads(path.read_text())["executors"], ["subagent"])
                code, out, _ = _run(["setup"])
                self.assertEqual(code, 0)
                self.assertIn("research: codex", out)
                self.assertEqual(_run(["setup", "--research", "none"])[0], 0)
                self.assertNotIn("research", json.loads(path.read_text()))
                code, out, _ = _run(["setup"])
                self.assertIn("research: none", out)


class ResearchCommand(unittest.TestCase):
    def test_the_codex_command_is_read_only_isolated_and_searches_the_live_web(self):
        self.assertEqual(
            keryx.research_command("/tmp/a.md", "PROMPT", None, None),
            ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
             "--disable", "plugins", "--disable", "remote_plugin", "--disable", "apps", "--disable", "memories",
             "-s", "read-only", "-c", 'approval_policy="never"', "-c", 'web_search="live"',
             "-o", "/tmp/a.md", "--", "PROMPT"])
        self.assertEqual(
            keryx.research_command("/tmp/a.md", "PROMPT", "gpt-x", "high"),
            ["codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
             "--disable", "plugins", "--disable", "remote_plugin", "--disable", "apps", "--disable", "memories",
             "-s", "read-only", "-c", 'approval_policy="never"', "-c", 'web_search="live"',
             "-m", "gpt-x", "-c", 'model_reasoning_effort="high"',
             "-o", "/tmp/a.md", "--", "PROMPT"])

    def test_with_no_research_agent_the_session_researches_itself(self):
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.dict(os.environ, {"KERYX_CONFIG": str(_config(Path(t)))}):
                code, out, _ = _run(["research", "What is the latest pytest?"])
        self.assertEqual(code, 3)
        self.assertIn("no research agent", out)
        self.assertIn("setup --research codex", out)

    def _fake(self, tmp: Path) -> dict:
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "codex"
        fake.write_text(FAKE_CODEX.format(python=sys.executable, answer=ANSWER))
        fake.chmod(0o755)
        repo = tmp / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        return {"KERYX_CONFIG": str(_config(tmp, {"agent": "codex"})),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "FAKE_CODEX_ARGS": str(tmp / "args.json"), "repo": str(repo)}

    def test_a_run_saves_the_answer_in_the_run_and_logs_it(self):
        with tempfile.TemporaryDirectory() as t:
            env = self._fake(Path(t))
            repo = Path(env.pop("repo"))
            cwd = os.getcwd()
            os.chdir(repo)
            try:
                with mock.patch.dict(os.environ, env):
                    code, out, _ = _run(["research", "--slug", "r1", "What is the latest pytest?"])
            finally:
                os.chdir(cwd)
            self.assertEqual(code, 0)
            self.assertIn(ANSWER, out)
            saved = repo / ".keryx" / "runs" / "r1" / "research" / "01.md"
            self.assertTrue(saved.is_file())
            text = saved.read_text()
            self.assertIn("What is the latest pytest?", text)
            self.assertIn(ANSWER, text)
            self.assertIn(str(saved.relative_to(repo)), out)
            self.assertEqual((repo / ".keryx" / ".gitignore").read_text(), "*\n")
            log = (repo / ".keryx" / "runs" / "r1" / "decisions.tsv").read_text()
            self.assertIn("research", log)
            self.assertIn("What is the latest pytest?", log)
            seen = json.loads(Path(env["FAKE_CODEX_ARGS"]).read_text())
            self.assertEqual(Path(seen["cwd"]).resolve(), repo.resolve())
            self.assertFalse(seen["stdin_tty"])
            self.assertEqual(seen["stdin"], "")
            prompt = seen["args"][-1]
            self.assertIn("What is the latest pytest?", prompt)
            self.assertIn("read-only", prompt)
            self.assertIn("source", prompt)

    def test_a_second_run_takes_the_next_number_and_no_slug_saves_beside_the_runs(self):
        with tempfile.TemporaryDirectory() as t:
            env = self._fake(Path(t))
            repo = Path(env.pop("repo"))
            cwd = os.getcwd()
            os.chdir(repo)
            try:
                with mock.patch.dict(os.environ, env):
                    self.assertEqual(_run(["research", "--slug", "r1", "one?"])[0], 0)
                    self.assertEqual(_run(["research", "--slug", "r1", "two?"])[0], 0)
                    self.assertEqual(_run(["research", "three?"])[0], 0)
            finally:
                os.chdir(cwd)
            self.assertIn("two?", (repo / ".keryx" / "runs" / "r1" / "research" / "02.md").read_text())
            self.assertIn("three?", (repo / ".keryx" / "research" / "01.md").read_text())

    def test_a_failed_run_says_so_and_tells_the_session_to_research_itself(self):
        with tempfile.TemporaryDirectory() as t:
            env = self._fake(Path(t))
            repo = Path(env.pop("repo"))
            env["FAKE_CODEX_FAIL"] = "1"
            cwd = os.getcwd()
            os.chdir(repo)
            try:
                with mock.patch.dict(os.environ, env):
                    code, out, err = _run(["research", "--slug", "r1", "What is the latest pytest?"])
            finally:
                os.chdir(cwd)
            self.assertEqual(code, 1)
            self.assertIn("backend down", out + err)
            self.assertIn("research it yourself", out + err)
            log = (repo / ".keryx" / "runs" / "r1" / "decisions.tsv").read_text()
            self.assertIn("failed", log)


if __name__ == "__main__":
    unittest.main()
