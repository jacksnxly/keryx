"""keryx.py research, the cases the locked tests leave open: stdin is closed even when the caller's is open,
and a run that finishes without an answer is a failure."""

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

# Reads stdin only when there is something to read, so an inherited open stdin shows instead of hanging.
FAKE_CODEX = """#!{python}
import json, os, select, sys
args = sys.argv[1:]
ready = select.select([sys.stdin], [], [], 0.5)[0]
with open(os.environ["FAKE_CODEX_ARGS"], "w") as f:
    json.dump({{"stdin": sys.stdin.read(64) if ready else ""}}, f)
print(json.dumps({{"type": "thread.started", "thread_id": "t1"}}))
if not os.environ.get("FAKE_CODEX_EMPTY"):
    print(json.dumps({{"type": "item.completed", "item": {{"id": "i1", "type": "agent_message", "text": "an answer"}}}}))
    with open(args[args.index("-o") + 1], "w") as f:
        f.write("an answer")
print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 1, "output_tokens": 1}}}}))
"""


class ResearchEdges(unittest.TestCase):
    def _run_in_repo(self, extra_env: dict) -> tuple[int, str, Path, Path]:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "bin").mkdir()
        fake = tmp / "bin" / "codex"
        fake.write_text(FAKE_CODEX.format(python=sys.executable))
        fake.chmod(0o755)
        config = tmp / "config.json"
        config.write_text(json.dumps({"executors": ["subagent"], "research": {"agent": "codex"}}))
        repo = tmp / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        env = {"KERYX_CONFIG": str(config), "PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
               "FAKE_CODEX_ARGS": str(tmp / "seen.json"), **extra_env}
        out = io.StringIO()
        cwd = os.getcwd()
        os.chdir(repo)
        try:
            with mock.patch.dict(os.environ, env), redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = keryx.main(["research", "--slug", "r1", "What?"])
        finally:
            os.chdir(cwd)
        return code, out.getvalue(), repo, tmp / "seen.json"

    def test_the_agent_never_reads_the_callers_stdin(self):
        read_end, write_end = os.pipe()
        os.write(write_end, b"the caller's stdin")
        os.close(write_end)
        saved = os.dup(0)
        os.dup2(read_end, 0)
        try:
            code, _, _, seen = self._run_in_repo({})
        finally:
            os.dup2(saved, 0)
            os.close(saved)
            os.close(read_end)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(seen.read_text())["stdin"], "")

    def test_a_finished_run_without_an_answer_is_a_failure(self):
        code, out, repo, _ = self._run_in_repo({"FAKE_CODEX_EMPTY": "1"})
        self.assertEqual(code, 1)
        self.assertIn("empty answer", out)
        self.assertIn("research it yourself", out)
        self.assertIn("Failed: empty answer", (repo / ".keryx" / "runs" / "r1" / "research" / "01.md").read_text())


if __name__ == "__main__":
    unittest.main()
