"""Offline tests for the pure helpers in scripts/keryx.py. Run: python3 -m unittest discover -s tests"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx as cloud  # noqa: E402


class ParseSse(unittest.TestCase):
    def test_events_with_ids_json_and_comments(self):
        lines = [
            ": keep-alive\n",
            "id: 1\n", "event: status\n", 'data: {"status": "RUNNING"}\n', "\n",
            "id: 2\n", "event: assistant\n", 'data: {"text": "a"}\n', "\n",
            "event: heartbeat\n", "data: {}\n", "\n",
            "id: 3\n", "event: result\n", 'data: {"status": "FINISHED",\n', 'data: "durationMs": 5}\n', "\n",
        ]
        got = list(cloud.parse_sse(lines))
        self.assertEqual(got[0], ("1", "status", {"status": "RUNNING"}))
        self.assertEqual(got[1], ("2", "assistant", {"text": "a"}))
        self.assertEqual(got[2][1], "heartbeat")
        self.assertEqual(got[2][0], "2", "the last event id persists across events without an id")
        self.assertEqual(got[3], ("3", "result", {"status": "FINISHED", "durationMs": 5}))

    def test_non_json_data_and_unterminated_tail(self):
        got = list(cloud.parse_sse(["event: done\n", "data: [DONE]\n"]))
        self.assertEqual(got, [(None, "done", "[DONE]")])


class RepoUrl(unittest.TestCase):
    def test_forms(self):
        for remote in ("git@github.com:example-org/example.git", "ssh://git@github.com/example-org/example",
                       "https://github.com/example-org/example.git", "https://token@github.com/example-org/example/"):
            self.assertEqual(cloud.normalize_repo_url(remote), "https://github.com/example-org/example", remote)

    def test_rejects_garbage(self):
        with self.assertRaises(cloud.LoopError):
            cloud.normalize_repo_url("not a url")


class LockedBlocks(unittest.TestCase):
    BLOCK = "#[test]\nfn sign() {\n    assert_eq!(f(1.0), -1.0);\n}"

    def test_whitespace_only_changes_pass(self):
        file_text = "mod tests {\n  #[test]\n  fn sign() {\n        assert_eq!(f(1.0),  -1.0);\n  }\n}\n"
        self.assertTrue(cloud.locked_block_present(self.BLOCK, file_text))

    def test_formatter_line_wraps_pass(self):
        block = "let next = predicted.next_funding_time.map(|time| time.timestamp_millis());"
        wrapped = "let next = predicted\n    .next_funding_time\n    .map(|time| time.timestamp_millis());"
        self.assertTrue(cloud.locked_block_present(block, wrapped))

    def test_formatter_trailing_commas_pass(self):
        self.assertTrue(cloud.locked_block_present("foo(a, b);", "foo(\n    a,\n    b,\n);"))
        self.assertTrue(cloud.locked_block_present("let v = [1, 2];", "let v = [\n    1,\n    2,\n];"))
        self.assertFalse(cloud.locked_block_present("foo(a, b);", "foo(a, c,);"))

    def test_merged_words_fail(self):
        self.assertFalse(cloud.locked_block_present("let next = 1;", "letnext = 1;"))

    def test_changed_expectation_fails(self):
        file_text = "#[test]\nfn sign() {\n    assert_eq!(f(1.0), 1.0);\n}"
        self.assertFalse(cloud.locked_block_present(self.BLOCK, file_text))

    def test_ignored_test_fails(self):
        file_text = "#[test]\n#[ignore]\nfn sign() {\n    assert_eq!(f(1.0), -1.0);\n}"
        self.assertFalse(cloud.locked_block_present(self.BLOCK, file_text))


class PushTriggers(unittest.TestCase):
    B = "cursor/fix-funding-sign"

    def test_main_only(self):
        self.assertFalse(cloud.push_triggers_for({True: {"push": {"branches": ["main"]}}}, self.B))

    def test_bare_push_and_list(self):
        self.assertTrue(cloud.push_triggers_for({"on": "push"}, self.B))
        self.assertTrue(cloud.push_triggers_for({"on": ["push", "pull_request"]}, self.B))
        self.assertTrue(cloud.push_triggers_for({True: {"push": None}}, self.B))

    def test_globs_and_negation(self):
        self.assertTrue(cloud.push_triggers_for({True: {"push": {"branches": ["cursor/**"]}}}, self.B))
        self.assertFalse(cloud.push_triggers_for({True: {"push": {"branches": ["**", "!cursor/**"]}}}, self.B))
        self.assertFalse(cloud.push_triggers_for({True: {"push": {"branches-ignore": ["cursor/*"]}}}, self.B))

    def test_tags_only(self):
        self.assertFalse(cloud.push_triggers_for({True: {"push": {"tags": ["v*"]}}}, self.B))

    def test_pull_request_only(self):
        self.assertFalse(cloud.push_triggers_for({True: {"pull_request": {}}}, self.B))


class DecisionLog(unittest.TestCase):
    def test_cells_are_single_line_and_formula_safe(self):
        self.assertEqual(cloud.tsv_cell("a\tb\nc"), "a b c")
        for bad in ("=SUM(A1)", "+1", "-rm", "@x"):
            self.assertEqual(cloud.tsv_cell(bad), "'" + bad)
        self.assertEqual(cloud.tsv_cell("plain"), "plain")

    def test_append_writes_header_once(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "slug"
            cloud.append_log(d, "dispatch", "round 01", "why", "ev", "ok")
            cloud.append_log(d, "review", "=evil", "why", "ev", "ok")
            lines = (d / "decisions.tsv").read_text().splitlines()
        self.assertEqual(lines[0], "ts\tphase\tdecision\twhy\tevidence\tresult")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[2].split("\t")[2], "'=evil")


class ModelParams(unittest.TestCase):
    def test_pairs(self):
        self.assertEqual(cloud.parse_params(["reasoning_effort=xhigh", "fast = false"]),
                         [{"id": "reasoning_effort", "value": "xhigh"}, {"id": "fast", "value": "false"}])

    def test_rejects_bare_word(self):
        with self.assertRaises(cloud.LoopError):
            cloud.parse_params(["xhigh"])


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cli-stream.ndjson"


class CliRunner(unittest.TestCase):
    """Parsing the Cursor CLI's stream-json, recorded from a real run on 2026-10-23 (CLI 2026.10.22)."""

    def events(self):
        return [json.loads(line) for line in FIXTURE.read_text().splitlines()]

    def test_command_is_headless_forced_trusted_and_resumable(self):
        cmd = cloud.cli_command("grok-4.7-xhigh", "/w", "do it", None, "agent")
        self.assertEqual(cmd[:2], ["agent", "-p"])
        for flag in ("--force", "--trust"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")
        self.assertEqual(cmd[-1], "do it")
        self.assertNotIn("--resume", cmd)
        resumed = cloud.cli_command("grok-4.7-xhigh", "/w", "fix", "abc", "plan")
        self.assertEqual(resumed[resumed.index("--resume") + 1], "abc")
        self.assertEqual(resumed[resumed.index("--mode") + 1], "plan")

    def test_env_drops_cluster_and_agent_credentials_and_blocks_pushes(self):
        env = cloud.cli_env({"PATH": "/usr/bin", "SSH_AUTH_SOCK": "/tmp/s", "KUBECONFIG": "/k", "GH_TOKEN": "t", "HOME": "/h"})
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertNotIn("GH_TOKEN", env)
        self.assertEqual(env["KUBECONFIG"], "/dev/null")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "remote.origin.pushurl")
        self.assertTrue(env["GIT_CONFIG_VALUE_0"].startswith("https://push-disabled.invalid"))
        self.assertEqual(env["HOME"], "/h")

    def test_summaries_name_the_shell_command_and_the_result(self):
        lines = [s for s in (cloud.cli_summary(e) for e in self.events()) if s]
        self.assertTrue(lines[0].startswith("init  model=Grok 4.7 256K Low"))
        self.assertIn("tool  shellToolCall ls", lines)
        self.assertTrue(lines[-1].startswith("result success error=False"))

    def test_outcome_of_a_clean_run(self):
        out = cloud.cli_outcome(self.events(), 0)
        self.assertEqual(out["status"], "FINISHED")
        self.assertEqual(out["session_id"], "ebdbc8c4-bfef-43ed-a12d-24c8f33747cc")
        self.assertTrue(out["result"].endswith("done"))
        self.assertEqual(out["durationMs"], 8362)

    def test_extra_env_parses_and_guard_rails_stay(self):
        self.assertEqual(cloud.parse_env(["CARGO_BUILD_JOBS=6", "RUST_LOG=info"]), {"CARGO_BUILD_JOBS": "6", "RUST_LOG": "info"})
        for bad in ("KUBECONFIG=/k", "SSH_AUTH_SOCK=/s", "GIT_CONFIG_COUNT=0", "PATH=/x", "no-equals", "1BAD=x"):
            with self.assertRaises(cloud.LoopError, msg=bad):
                cloud.parse_env([bad])

    def test_outcome_without_a_result_event(self):
        events = [e for e in self.events() if e.get("type") != "result"]
        self.assertEqual(cloud.cli_outcome(events, 1)["status"], "ERROR")
        self.assertEqual(cloud.cli_outcome(events, None)["status"], "RUNNING")
        self.assertEqual(cloud.cli_outcome(events, 143)["status"], "CANCELLED")


class Attribution(unittest.TestCase):
    def test_strips_cursor_trailers_only(self):
        msg = "fix(x): y\n\nbody line\n\nCo-authored-by: Cursor <cursoragent@cursor.com>\n"
        self.assertEqual(cloud.strip_attribution(msg), "fix(x): y\n\nbody line\n")
        human = "feat: z\n\nCo-authored-by: Ada <ada@example.com>\n"
        self.assertEqual(cloud.strip_attribution(human), human)
        self.assertEqual(cloud.strip_attribution("chore: a\n\nMade with Cursor\n"), "chore: a\n")


if __name__ == "__main__":
    unittest.main()


class LogCommand(unittest.TestCase):
    def test_the_coordinators_row_lands_in_the_slugs_log(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            orig = cloud.state_root
            cloud.state_root = lambda: root
            try:
                import contextlib
                import io
                printed = io.StringIO()
                with contextlib.redirect_stdout(printed):
                    self.assertEqual(cloud.main(["log", "--slug", "s", "plan", "=sum(1)", "why", "ev", "OK"]), 0)
                # Seen: a coordinator spent five calls finding where its rows went. The row's number is what a
                # later ruling names when it replaces this one.
                self.assertEqual(printed.getvalue().strip(), f"{root / 's' / 'decisions.tsv'}  row 1")
            finally:
                cloud.state_root = orig
            rows = (root / "s" / "decisions.tsv").read_text().splitlines()
            self.assertEqual(rows[0].split("\t")[1:], ["phase", "decision", "why", "evidence", "result"])
            self.assertEqual(rows[1].split("\t")[1:], ["plan", "'=sum(1)", "why", "ev", "OK"])


class PreflightCli(unittest.TestCase):
    def test_a_local_run_needs_no_github_remote(self):
        # Seen in the benchmark: a sealed checkout's remote is no-push://disabled, and preflight stopped there.
        from unittest import mock

        class Done:
            def __init__(self, out="", code=0):
                self.stdout, self.returncode = out, code

        def fake_run(cmd, *a, **kw):
            text = " ".join(cmd) if isinstance(cmd, list) else cmd
            if "command -v agent" in text:
                return Done("/usr/local/bin/agent")
            if text.endswith("--version"):
                return Done("2026.10")
            if text.endswith("status"):
                return Done("✓ Logged in as owner@example.invalid")
            if text.endswith("models"):
                return Done(f"{cloud.DEFAULT_CLI_MODEL} - default")
            return Done()

        def fake_git(*args, **kwargs):
            if args[:2] == ("remote", "get-url"):
                return "no-push://disabled"
            return "/tmp/repo"

        with mock.patch.object(cloud.subprocess, "run", fake_run), mock.patch.object(cloud, "git", fake_git):
            self.assertEqual(cloud.cmd_preflight(type("A", (), {"runner": "cli"})()), 0)


class Stall(unittest.TestCase):
    """Seen in a real run: two executors finished their work, left dev servers running and never sent a final
    result, so `wait` blocked for hours."""

    START = {"type": "tool_call", "subtype": "started", "call_id": "a"}
    DONE = {"type": "tool_call", "subtype": "completed", "call_id": "a"}
    THOUGHT = {"type": "thinking", "subtype": "completed"}

    def test_a_silent_run_with_nothing_in_flight_has_stalled(self):
        self.assertTrue(cloud.stalled([self.START, self.DONE, self.THOUGHT], silent_s=1300, after_s=1200))

    def test_a_long_command_still_running_is_not_a_stall(self):
        self.assertFalse(cloud.stalled([self.START], silent_s=5000, after_s=1200))

    def test_a_finished_run_or_a_short_silence_is_not_a_stall(self):
        self.assertFalse(cloud.stalled([self.THOUGHT, {"type": "result", "subtype": "success"}], 5000, 1200))
        self.assertFalse(cloud.stalled([self.THOUGHT], silent_s=600, after_s=1200))


class KillTree(unittest.TestCase):
    def test_stopping_a_run_also_stops_what_it_started(self):
        import subprocess
        import time
        parent = subprocess.Popen([sys.executable, "-c", "import subprocess, time; "
                                   "subprocess.Popen(['sleep', '60']); time.sleep(60)"], start_new_session=True)
        time.sleep(0.5)
        kids = subprocess.run(["pgrep", "-P", str(parent.pid)], capture_output=True, text=True).stdout.split()
        self.assertTrue(kids)
        cloud.kill_tree(parent.pid, grace_s=2)
        parent.wait(timeout=5)
        time.sleep(0.3)
        for kid in kids:
            self.assertFalse(cloud.pid_alive(int(kid)), f"child {kid} survived")


class WaitStopsAStalledRun(unittest.TestCase):
    def test_wait_returns_stalled_and_stops_the_run_with_what_it_started(self):
        import os
        import subprocess
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@x.invalid", "-c", "user.name=t",
                            "commit", "-q", "--allow-empty", "-m", "work"], check=True)
            # The executor: done thinking, a dev server still running under it, and no final result coming.
            run = subprocess.Popen([sys.executable, "-c", "import subprocess, time; "
                                    "subprocess.Popen(['sleep', '60']); time.sleep(60)"], start_new_session=True)
            time.sleep(0.5)
            server = int(subprocess.run(["pgrep", "-P", str(run.pid)], capture_output=True, text=True).stdout.split()[0])
            d = root / "loops" / "st"
            (d / "rounds" / "01").mkdir(parents=True)
            (d / "agent.json").write_text(json.dumps({"runner": "cli", "workspace": str(repo), "branch": "cursor/st"}))
            (d / "rounds" / "01" / "run.json").write_text(json.dumps({"pid": run.pid}))
            (d / "rounds" / "01" / "events.ndjson").write_text(
                json.dumps({"type": "tool_call", "subtype": "started", "call_id": "a"}) + "\n"
                + json.dumps({"type": "tool_call", "subtype": "completed", "call_id": "a"}) + "\n"
                + json.dumps({"type": "thinking", "subtype": "completed"}) + "\n")
            # The run went quiet long before this wait began: the silence counts from its last event.
            old = time.time() - 3600
            os.utime(d / "rounds" / "01" / "events.ndjson", (old, old))
            orig = cloud.state_root
            cloud.state_root = lambda: root / "loops"
            try:
                started = time.monotonic()
                code = cloud.main(["wait", "--slug", "st", "--stall", "600", "--timeout", "60"])
            finally:
                cloud.state_root = orig
            run.wait(timeout=10)
            time.sleep(0.3)
            self.assertEqual(code, 4)
            self.assertLess(time.monotonic() - started, 30)
            self.assertFalse(cloud.pid_alive(server))
            self.assertEqual(json.loads((d / "rounds" / "01" / "run.json").read_text())["status"], "STALLED")


class ExecutorsGetNoMcpServers(unittest.TestCase):
    """Seen in a real run: each executor started the owner's Postgres MCP server, a live database tool."""

    def test_every_configured_server_is_disabled_for_the_executors_workspace_only(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            home, ws = Path(tmp) / "home", Path(tmp) / "repo" / ".worktrees" / "cursor-s1"
            (home / ".cursor").mkdir(parents=True)
            (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"supabase": {}, "linear": {}}}))
            (ws / ".cursor").mkdir(parents=True)
            (ws / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": {"local-db": {}}}))
            old = os.environ.get("HOME")
            os.environ["HOME"] = str(home)
            try:
                names = cloud.disable_mcp(str(ws))
            finally:
                os.environ["HOME"] = old
            self.assertEqual(names, ["linear", "local-db", "supabase"])
            project = cloud.re.sub(r"[^A-Za-z0-9]+", "-", os.path.realpath(ws)).strip("-")
            written = json.loads((home / ".cursor" / "projects" / project / "mcp-disabled.json").read_text())
            self.assertEqual(written, ["linear", "local-db", "supabase"])
            self.assertEqual([p.name for p in (home / ".cursor" / "projects").iterdir()], [project])


def _fake_run(test, root, events, *, linger=True, runner="cli"):
    """A loop state with one CLI round whose process (and a child of it) keeps running."""
    import subprocess
    import time
    repo = root / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@x.invalid", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "work"], check=True)
    run = subprocess.Popen([sys.executable, "-c", "import subprocess, time; "
                            "subprocess.Popen(['sleep', '60']); time.sleep(60)"], start_new_session=True)
    time.sleep(0.5)
    d = root / "loops" / "st"
    (d / "rounds" / "01").mkdir(parents=True)
    (d / "agent.json").write_text(json.dumps({"runner": runner, "workspace": str(repo), "branch": f"{runner}/st"}))
    (d / "rounds" / "01" / "run.json").write_text(json.dumps({"pid": run.pid}))
    (d / "rounds" / "01" / "events.ndjson").write_text("".join(json.dumps(e) + "\n" for e in events))
    return run, d


class WaitBoundsEveryHang(unittest.TestCase):
    def _wait(self, root, *extra):
        orig = cloud.state_root
        cloud.state_root = lambda: root / "loops"
        try:
            return cloud.main(["wait", "--slug", "st", "--timeout", "60", *extra])
        finally:
            cloud.state_root = orig

    def test_a_reported_result_finishes_the_run_even_if_the_process_lingers(self):
        # Cursor's known issue: `agent -p` can return its result and never exit.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            run, d = _fake_run(self, Path(tmp), [
                {"type": "assistant", "message": {"content": [{"text": "Status: DONE"}]}},
                {"type": "result", "subtype": "success", "is_error": False, "result": "Status: DONE"}])
            self.assertEqual(self._wait(Path(tmp), "--result-grace", "1"), 0)
            run.wait(timeout=10)
            saved = json.loads((d / "rounds" / "01" / "run.json").read_text())
            self.assertEqual(saved["status"], "FINISHED")
            self.assertIn("Status: DONE", (d / "rounds" / "01" / "result.md").read_text())

    def test_one_tool_call_running_past_its_limit_stops_the_run_and_names_it(self):
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as tmp:
            started = int((time.time() - 120) * 1000)
            run, d = _fake_run(self, Path(tmp), [
                {"type": "tool_call", "subtype": "started", "call_id": "a", "timestamp_ms": started,
                 "tool_call": {"shellToolCall": {"args": {"command": "npm run dev"}}}}])
            self.assertEqual(self._wait(Path(tmp), "--tool-timeout", "60"), 4)
            run.wait(timeout=10)
            log = (d / "decisions.tsv").read_text()
            self.assertIn("npm run dev", log)
            self.assertTrue((d / "rounds" / "01" / "processes.txt").exists())


class Redact(unittest.TestCase):
    def test_credentials_in_process_lines_are_masked(self):
        line = "node server postgresql://user:hunter2@db.example:5432/x --token abc123 API_KEY=zzz9"
        masked = cloud.redact(line)
        for secret in ("hunter2", "abc123", "zzz9"):
            self.assertNotIn(secret, masked)
        self.assertIn("postgresql://", masked)


# ---------------------------------------------------------------- GLM runner (Claude Code on the GLM Coding Plan)


def _tool_use(call_id, command):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}]}}


def _tool_result(call_id):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "content": "ok"}]}}


class GlmRunner(unittest.TestCase):
    """The executor when Cursor's usage is spent: headless Claude Code against Z.ai's GLM Coding Plan endpoint."""

    def test_the_command_is_headless_claude_code_with_our_settings_and_no_mcp_servers(self):
        cmd = cloud.glm_command("opus", "do the slice", None, "agent", "/state/s1/claude-config/settings.json")
        self.assertEqual(cmd[:3], ["claude", "-p", "--output-format"])
        for flag in ("stream-json", "--verbose", "--strict-mcp-config"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--settings") + 1], "/state/s1/claude-config/settings.json")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "bypassPermissions")
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")
        self.assertEqual(cmd[-2:], ["--", "do the slice"])  # a prompt that starts with "-" is not a flag
        self.assertNotIn("--resume", cmd)

    def test_plan_mode_and_a_follow_up_resume_the_session(self):
        cmd = cloud.glm_command("opus", "p", "sess-1", "plan", "/s.json")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "plan")
        self.assertEqual(cmd[cmd.index("--resume") + 1], "sess-1")

    def test_the_environment_drops_secrets_and_the_coordinators_own_settings(self):
        # The model behind this runner is a third party's: it gets the repository, not the owner's credentials.
        base = {"HOME": "/nonexistent-home", "PATH": "/usr/bin", "CARGO_BUILD_JOBS": "6",
                "ANTHROPIC_API_KEY": "sk-ant-x", "ANTHROPIC_MODEL": "claude-opus-5-5", "CLAUDECODE": "1",
                "CLAUDE_CODE_OAUTH_TOKEN": "oauth", "GEMINI_API_KEY": "gem", "SOPS_AGE_KEY_FILE": "/k/age.txt",
                "GH_TOKEN": "gh", "DATABASE_PASSWORD": "pw", "AWS_SECRET_ACCESS_KEY": "aws", "GLM_API_KEY": "glm-k"}
        env = cloud.glm_env(base, "/state/s1/claude-config")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "glm-k")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/state/s1/claude-config")
        self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "glm-5.3[1m]")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1")
        for gone in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "CLAUDECODE", "CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_API_KEY",
                     "SOPS_AGE_KEY_FILE", "GH_TOKEN", "DATABASE_PASSWORD", "AWS_SECRET_ACCESS_KEY", "GLM_API_KEY"):
            self.assertNotIn(gone, env)
        self.assertEqual((env["HOME"], env["CARGO_BUILD_JOBS"], env["KUBECONFIG"]), ("/nonexistent-home", "6", "/dev/null"))
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], cloud.NO_PUSH_ENV["GIT_CONFIG_VALUE_0"])

    def test_git_still_works_and_pushes_still_go_nowhere(self):
        # Seen in the first live run: the secret filter took GIT_CONFIG_KEY_0 ("KEY"), git refused the half-set
        # config, and the executor unset the whole push guard to commit.
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            env = cloud.glm_env({"HOME": "/nonexistent-home", "PATH": "/usr/bin:/bin", "GLM_API_KEY": "k"}, "/cfg")
            got = subprocess.run(["git", "config", "--get", "remote.origin.pushurl"], cwd=tmp, env=env,
                                 capture_output=True, text=True)
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertEqual(got.stdout.strip(), cloud.NO_PUSH_ENV["GIT_CONFIG_VALUE_0"])

    def test_only_the_coding_plan_endpoints_are_accepted(self):
        # The general API endpoint bills the pay-as-you-go balance instead of the plan.
        home = {"HOME": "/nonexistent-home"}
        self.assertEqual(cloud.glm_base_url(home), "https://api.z.ai/api/anthropic")
        self.assertEqual(cloud.glm_base_url({**home, "GLM_BASE_URL": "https://open.bigmodel.cn/api/anthropic"}),
                         "https://open.bigmodel.cn/api/anthropic")
        with self.assertRaises(cloud.LoopError):
            cloud.glm_base_url({**home, "GLM_BASE_URL": "https://api.z.ai/api/paas/v4"})

    def test_a_missing_key_is_an_error_that_names_where_to_put_it(self):
        with self.assertRaises(cloud.LoopError) as caught:
            cloud.glm_key({"HOME": "/nonexistent-home"})
        self.assertIn("coding-plan.key", str(caught.exception))

    def test_the_config_hides_attribution_and_denies_secrets_and_pushes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cloud.write_glm_config(Path(tmp))
            settings = json.loads((cfg / "settings.json").read_text())
        self.assertEqual(settings["attribution"], {"commit": "", "pr": "", "sessionUrl": False})
        self.assertIs(settings["autoMemoryEnabled"], False)
        deny = settings["permissions"]["deny"]
        for rule in ("Bash(git push *)", "Bash(kubectl *)", "Bash(sops *)", "Bash(gh *)", "Read(**/.env)",
                     "Read(**/.env.*)", "Read(~/.config/glm/**)", "Read(~/.ssh/**)"):
            self.assertIn(rule, deny)

    def test_the_guard_rail_variables_cannot_be_set_with_env(self):
        for name in ("ANTHROPIC_BASE_URL", "CLAUDE_CONFIG_DIR", "GLM_API_KEY"):
            with self.assertRaises(cloud.LoopError):
                cloud.parse_env([f"{name}=x"])
        self.assertEqual(cloud.parse_env(["CARGO_BUILD_JOBS=6"]), {"CARGO_BUILD_JOBS": "6"})

    def test_a_glm_slice_has_its_own_worktree_and_branch(self):
        import contextlib
        import io
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "brief.md"
            prompt.write_text("Mode: TESTS-ONLY\n")
            args = type("A", (), {"slug": "s1", "runner": "glm", "ref": "a" * 40, "model": None, "mode": "agent",
                                  "param": [], "image": [], "env": [], "dry_run": True, "prompt_file": str(prompt)})()
            printed = io.StringIO()
            with mock.patch.object(cloud, "git", lambda *a, **k: tmp), contextlib.redirect_stdout(printed):
                self.assertEqual(cloud.cmd_create(args), 0)
        shown = json.loads(printed.getvalue())
        self.assertEqual((shown["runner"], shown["branch"]), ("glm", "glm/s1"))
        self.assertEqual(Path(shown["worktree"]).name, "glm-s1")
        self.assertEqual(shown["command"][0], "claude")
        self.assertEqual(shown["model"], "opus")


class ClaudeCodeEvents(unittest.TestCase):
    """Claude Code's stream-json carries tool calls inside assistant and user messages, not as tool_call events."""

    def test_a_tool_call_without_its_result_is_in_flight(self):
        self.assertFalse(cloud.stalled([_tool_use("t1", "cargo test")], silent_s=5000, after_s=600))
        self.assertTrue(cloud.stalled([_tool_use("t1", "cargo test"), _tool_result("t1")], silent_s=5000, after_s=600))

    def test_tool_calls_of_both_formats(self):
        self.assertEqual(cloud.tool_calls(_tool_use("t1", "npm test")), [("start", "t1", "npm test")])
        self.assertEqual(cloud.tool_calls(_tool_result("t1")), [("end", "t1", "")])
        cursor_start = {"type": "tool_call", "subtype": "started", "call_id": "a",
                        "tool_call": {"shellToolCall": {"args": {"command": "npm run dev"}}}}
        self.assertEqual(cloud.tool_calls(cursor_start), [("start", "a", "npm run dev")])
        self.assertEqual(cloud.tool_calls({"type": "tool_call", "subtype": "completed", "call_id": "a"}), [("end", "a", "")])
        self.assertEqual(cloud.tool_calls({"type": "system", "subtype": "thinking_tokens"}), [])

    def test_the_progress_line_names_the_tool_and_its_command(self):
        self.assertEqual(cloud.cli_summary(_tool_use("t1", "npm test")), "tool  Bash npm test")

    def test_the_status_report_survives_a_later_turn_that_ends_on_an_aside(self):
        # Seen in GLM runs: a background task ending wakes the run after its report, and it ends on a short aside.
        events = [{"type": "system", "subtype": "init", "session_id": "s-1"},
                  {"type": "result", "subtype": "success", "is_error": False, "result": "Status: DONE\nall green"},
                  {"type": "result", "subtype": "success", "is_error": False,
                   "result": "The build finished; my report (Status: DONE) stands."}]
        out = cloud.cli_outcome(events, 0)
        self.assertTrue(out["result"].startswith("Status: DONE\nall green"))
        self.assertIn("my report (Status: DONE) stands", out["result"])
        self.assertEqual(out["session_id"], "s-1")

    def test_claude_code_attribution_is_stripped_and_a_human_co_author_kept(self):
        message = ("feat: add the board store\n\nGenerated with [Claude Code](https://claude.com/claude-code)\n\n"
                   "Co-authored-by: Alice <alice@example.invalid>\nCo-Authored-By: Claude <noreply@anthropic.com>\n")
        clean = cloud.strip_attribution(message)
        self.assertNotIn("Claude", clean)
        self.assertIn("Co-authored-by: Alice <alice@example.invalid>", clean)


class PreflightGlm(unittest.TestCase):
    def _preflight(self, models):
        import contextlib
        import io
        import os
        import tempfile
        from unittest import mock

        class Done:
            def __init__(self, out="", code=0):
                self.stdout, self.stderr, self.returncode = out, "", code

        def fake_run(cmd, *a, **kw):
            text = " ".join(cmd)
            if "command -v claude" in text:
                return Done("/usr/local/bin/claude")
            if text.endswith("--version"):
                return Done("2.1.300 (Claude Code)")
            if text.startswith("claude -p"):
                self.probe_env = kw.get("env") or {}
                return Done(json.dumps({"result": "OK", "is_error": False, "modelUsage": {m: {} for m in models}}))
            return Done()

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"HOME": tmp, "GLM_API_KEY": "glm-k"}), \
                mock.patch.object(cloud.subprocess, "run", fake_run), \
                mock.patch.object(cloud, "git", lambda *a, **k: tmp), \
                mock.patch.object(cloud, "state_root", lambda: Path(tmp) / "loops"), \
                contextlib.redirect_stdout(io.StringIO()) as printed:
            code = cloud.cmd_preflight(type("A", (), {"runner": "glm"})())
        return code, printed.getvalue()

    def test_a_probe_answered_by_a_glm_model_passes(self):
        code, out = self._preflight(["glm-5.3[1m]"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.probe_env["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")
        self.assertNotIn("glm-k", out)

    def test_a_probe_answered_by_another_model_fails(self):
        # The run would draw on the owner's Claude usage instead of the plan.
        code, out = self._preflight(["claude-opus-5-5"])
        self.assertEqual(code, 1)
        self.assertIn("not a GLM model", out)


class WaitOnAGlmRun(unittest.TestCase):
    def _wait(self, root, *extra):
        orig = cloud.state_root
        cloud.state_root = lambda: root / "loops"
        try:
            return cloud.main(["wait", "--slug", "st", "--timeout", "60", *extra])
        finally:
            cloud.state_root = orig

    def test_a_reported_result_finishes_the_run_and_keeps_its_session(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            run, d = _fake_run(self, Path(tmp), [
                {"type": "system", "subtype": "init", "session_id": "s-1"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Status: DONE"}]}},
                {"type": "result", "subtype": "success", "is_error": False, "result": "Status: DONE",
                 "session_id": "s-1"}], runner="glm")
            self.assertEqual(self._wait(Path(tmp), "--result-grace", "1"), 0)
            run.wait(timeout=10)
            self.assertEqual(json.loads((d / "rounds" / "01" / "run.json").read_text())["status"], "FINISHED")
            self.assertEqual(json.loads((d / "agent.json").read_text())["sessionId"], "s-1")

    def test_one_tool_call_running_past_its_limit_stops_the_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            run, d = _fake_run(self, Path(tmp), [_tool_use("t1", "npm run dev")], runner="glm")
            self.assertEqual(self._wait(Path(tmp), "--tool-timeout", "1"), 4)
            run.wait(timeout=10)
            self.assertIn("npm run dev", (d / "decisions.tsv").read_text())


import tempfile  # noqa: E402  (keryx universal-a)


class ExecutorConfig(unittest.TestCase):
    def test_default_is_the_claude_subagent_alone(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = cloud.load_config({"KERYX_CONFIG": str(Path(d) / "missing.json")})
        self.assertEqual(cfg["executors"], ["subagent"])

    def test_reads_the_saved_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.json"
            p.write_text(json.dumps({"executors": ["glm", "subagent"]}))
            self.assertEqual(cloud.load_config({"KERYX_CONFIG": str(p)})["executors"], ["glm", "subagent"])

    def test_parse_executors_validates_and_dedupes(self):
        self.assertEqual(cloud.parse_executors("cli, glm,cli,subagent"), ["cli", "glm", "subagent"])
        with self.assertRaises(cloud.LoopError):
            cloud.parse_executors("cli,codex")
        with self.assertRaises(cloud.LoopError):
            cloud.parse_executors(" ")

    def test_config_path(self):
        self.assertEqual(cloud.config_path({"HOME": "/h"}), Path("/h/.config/keryx/config.json"))
        self.assertEqual(cloud.config_path({"HOME": "/h", "XDG_CONFIG_HOME": "/x"}), Path("/x/keryx/config.json"))
        self.assertEqual(cloud.config_path({"HOME": "/h", "KERYX_CONFIG": "/c.json"}), Path("/c.json"))


class Ladder(unittest.TestCase):
    def test_next_after_each_rung(self):
        ladder = ["cli", "glm", "subagent"]
        self.assertEqual(cloud.next_executor(ladder, "cli"), "glm")
        self.assertEqual(cloud.next_executor(ladder, "glm"), "subagent")
        self.assertEqual(cloud.next_executor(ladder, "subagent"), "inline")
        self.assertEqual(cloud.next_executor(ladder, "cloud"), "cli", "a runner outside the ladder starts it")

    def test_switch_only_after_an_error(self):
        for status in ("ERROR", "STALLED", "EXPIRED", "CANCELLED"):
            self.assertTrue(cloud.can_switch(status), status)
        for status in ("RUNNING", "FINISHED", "CREATING", None):
            self.assertFalse(cloud.can_switch(status), status)


class Gates(unittest.TestCase):
    def test_default_globs_catch_architecture_gates(self):
        paths = [".importlinter", "backend/.importlinter", "tests/test_architecture_guard.py",
                 ".github/workflows/ci.yml", "app/.dependency-cruiser.cjs", "src/feature/widget.ts",
                 "tests/test_widget.py"]
        self.assertEqual(cloud.gate_hits(paths, cloud.DEFAULT_GATE_GLOBS),
                         [".importlinter", "backend/.importlinter", "tests/test_architecture_guard.py",
                          ".github/workflows/ci.yml", "app/.dependency-cruiser.cjs"])

    def test_extra_globs_match_at_the_root_too(self):
        self.assertEqual(cloud.gate_hits(["contracts/deps.toml", "x/contracts/deps.toml", "README.md"],
                                         ["**/contracts/*.toml"]),
                         ["contracts/deps.toml", "x/contracts/deps.toml"])


class SubagentLoop(unittest.TestCase):
    def test_a_subagent_slice_gets_a_worktree_and_loop_state_but_no_process(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()

            def run(*a):
                return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

            run("init", "-q", "-b", "main")
            run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base")
            base = run("rev-parse", "HEAD")
            (Path(tmp) / "brief.md").write_text("Mode: IMPLEMENT\n")
            old = os.getcwd()
            os.chdir(repo)
            try:
                self.assertEqual(cloud.main(["create", "--slug", "s1", "--runner", "subagent",
                                             "--prompt-file", str(Path(tmp) / "brief.md"), "--ref", "main"]), 0)
                state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "s1"
                agent = json.loads((state / "agent.json").read_text())
                self.assertEqual((agent["runner"], agent["branch"], agent["baseSha"]), ("subagent", "sub/s1", base))
                self.assertEqual(run("-C", agent["workspace"], "rev-parse", "HEAD"), base)
                round_file = state / "rounds" / "01" / "run.json"
                self.assertEqual(json.loads(round_file.read_text())["status"], "DISPATCHED")
                self.assertEqual(cloud.main(["gates", "--slug", "s1", "--ref", "sub/s1"]), 0)
                self.assertEqual(cloud.main(["fetch", "--slug", "s1"]), 0)
                self.assertEqual(cloud.main(["mark", "--slug", "s1", "--status", "ERROR"]), 0)
                self.assertTrue(cloud.can_switch(json.loads(round_file.read_text())["status"]))
                self.assertEqual(cloud.main(["wait", "--slug", "s1"]), 1, "a subagent reports to the coordinator")
            finally:
                os.chdir(old)


class RefusedSwitch(unittest.TestCase):
    def test_a_refused_switch_leaves_the_loop_as_it_was(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()

            def run(*a):
                return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=repo,
                                      check=True, capture_output=True, text=True).stdout.strip()

            run("init", "-q", "-b", "main")
            run("commit", "-q", "--allow-empty", "-m", "base")
            brief = Path(tmp) / "brief.md"
            brief.write_text("Mode: IMPLEMENT\n")
            old = os.getcwd()
            os.chdir(repo)
            try:
                self.assertEqual(cloud.main(["create", "--slug", "s5", "--runner", "subagent",
                                             "--prompt-file", str(brief), "--ref", "main"]), 0)
                state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "s5"
                work = json.loads((state / "agent.json").read_text())["workspace"]
                run("-C", work, "commit", "-q", "--allow-empty", "-m", "feat: the executor's work")
                self.assertEqual(cloud.main(["mark", "--slug", "s5", "--status", "ERROR"]), 0)
                run("commit", "-q", "--allow-empty", "-m", "unrelated")
                run("branch", "cursor/s5", "HEAD")
                log_before = (state / "decisions.tsv").read_text()
                self.assertEqual(cloud.main(["create", "--slug", "s5", "--runner", "cli",
                                             "--prompt-file", str(brief), "--ref", "main"]), 1)
                self.assertEqual(json.loads((state / "agent.json").read_text())["runner"], "subagent")
                self.assertEqual(sorted(p.name for p in state.glob("agent*.json")), ["agent.json"])
                self.assertNotIn("switch executor", (state / "decisions.tsv").read_text()[len(log_before):])
                self.assertEqual(len(list((state / "rounds").iterdir())), 1)
            finally:
                os.chdir(old)


class ReviewFindings(unittest.TestCase):
    """The fresh review of the executor ladder (2026-10-27): one test per confirmed finding."""

    def setUp(self):
        import os
        import subprocess
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.repo = tmp / "repo"
        self.repo.mkdir()
        self.brief = tmp / "brief.md"
        self.brief.write_text("Mode: IMPLEMENT\n")
        self.run = lambda *a, cwd=None: subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd or self.repo,
            check=True, capture_output=True, text=True).stdout.strip()
        self.run("init", "-q", "-b", "trunk")
        (self.repo / ".importlinter").write_text("[importlinter]\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_architecture_guard.py").write_text("x = 1\n")
        self.run("add", "-A")
        self.run("commit", "-q", "-m", "base")
        self._old = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        import os
        os.chdir(self._old)
        self._tmp.cleanup()

    def _subagent(self, slug):
        self.assertEqual(cloud.main(["create", "--slug", slug, "--runner", "subagent",
                                     "--prompt-file", str(self.brief), "--ref", "trunk"]), 0)
        state = Path(self.run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / slug
        return state, json.loads((state / "agent.json").read_text())["workspace"]

    def test_a_gate_file_renamed_away_is_a_gate_change(self):
        state, work = self._subagent("r1")
        self.run("mv", ".importlinter", "config.importlinter.bak", cwd=work)
        self.run("mv", "tests/test_architecture_guard.py", "tests/test_imports.py", cwd=work)
        self.run("commit", "-q", "-m", "move", cwd=work)
        self.assertEqual(cloud.main(["gates", "--slug", "r1", "--ref", "sub/r1"]), 1)

    def test_gate_globs_ignore_case_and_folder_names(self):
        self.assertEqual(cloud.gate_hits(["src/test/java/x/ArchitectureTest.java"], cloud.DEFAULT_GATE_GLOBS),
                         ["src/test/java/x/ArchitectureTest.java"])
        self.assertEqual(cloud.gate_hits(["src/routes/guarded/latest.ts", "tests/test_auth_guard.py",
                                          "src/auth/jwt.guard.test.ts", "app/lib/error_boundary.py"],
                                         cloud.DEFAULT_GATE_GLOBS), [])

    def test_the_cloud_rung_refuses_a_start_that_exists_only_here(self):
        state, work = self._subagent("r2")
        self.run("commit", "-q", "--allow-empty", "-m", "local work", cwd=work)
        self.assertEqual(cloud.main(["mark", "--slug", "r2", "--status", "ERROR"]), 0)
        self.run("remote", "add", "origin", "https://github.com/example-org/example.git")
        self.assertEqual(cloud.main(["create", "--slug", "r2", "--runner", "cloud", "--prompt-file", str(self.brief), "--ref", "trunk",
                                     "--dry-run"]), 1)
        self.assertEqual(json.loads((state / "agent.json").read_text())["runner"], "subagent")

    def test_a_subagent_fix_round_and_an_escalation_have_a_path(self):
        state, work = self._subagent("r3")
        self.assertEqual(cloud.main(["mark", "--slug", "r3", "--status", "FINISHED"]), 0)
        self.assertEqual(cloud.main(["followup", "--slug", "r3", "--prompt-file", str(self.brief)]), 0)
        self.assertEqual(json.loads((state / "rounds" / "02" / "run.json").read_text())["status"], "DISPATCHED")
        self.assertEqual(cloud.main(["mark", "--slug", "r3", "--status", "FINISHED"]), 0)
        self.assertEqual(cloud.main(["create", "--slug", "r3", "--runner", "subagent",
                                     "--prompt-file", str(self.brief)]), 1, "a finished round needs --escalate")
        self.assertEqual(cloud.main(["create", "--slug", "r3", "--runner", "subagent", "--escalate",
                                     "--prompt-file", str(self.brief)]), 0)
        self.assertTrue((state / "agent.02.json").exists())
        self.assertIn("escalat", (state / "decisions.tsv").read_text())

    def test_marking_a_round_records_when_it_ended(self):
        state, _ = self._subagent("r4")
        self.assertEqual(cloud.main(["mark", "--slug", "r4", "--status", "CANCELLED"]), 0)
        run = json.loads((state / "rounds" / "01" / "run.json").read_text())
        self.assertEqual(run["status"], "CANCELLED")
        self.assertTrue(run.get("finishedAt") and run.get("startedAt"))

    def test_a_switch_starts_from_the_executors_branch_when_its_worktree_is_gone(self):
        state, work = self._subagent("r5")
        self.run("commit", "-q", "--allow-empty", "-m", "the executor's work", cwd=work)
        head = self.run("rev-parse", "HEAD", cwd=work)
        self.run("worktree", "remove", "--force", work)
        self.assertEqual(cloud.main(["mark", "--slug", "r5", "--status", "ERROR"]), 0)
        self.assertEqual(cloud.main(["create", "--slug", "r5", "--runner", "subagent", "--ref", "no-such-ref",
                                     "--prompt-file", str(self.brief)]), 0)
        self.assertEqual(self.run("rev-parse", "HEAD", cwd=work), head)

    def test_a_subagent_worktree_cannot_push(self):
        state, work = self._subagent("r6")
        self.run("remote", "add", "origin", "https://example.invalid/repo.git")
        self.assertIn("push-disabled", subprocess_call(["git", "config", "--get", "remote.origin.pushurl"], work))
        self.assertEqual(subprocess_call(["git", "config", "--get", "remote.origin.pushurl"], self.repo), "")


def subprocess_call(cmd, cwd):
    # Without the GIT_CONFIG_* overrides an executor's own shell carries (its pushurl would answer instead).
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True).stdout.strip()




class UsageLimit(unittest.TestCase):
    def test_glm_five_hour_limit_resets_in_utc(self):
        # Z.ai prints its reset time in UTC+8 (seen twice: 19:58 -> 11:58Z, 04:53 -> 20:53Z).
        text = ("API Error: Request rejected (429) · [1308][Usage limit reached for 5 hour. "
                "Your limit will reset at 2026-10-27 19:58:02][202610271934270313e65098184fc9]")
        got = cloud.usage_limit(text)
        self.assertEqual((got["kind"], got["resetsAt"], got["resetsIn"]), ("5 hour", "2026-10-27T11:58:02Z", None))

    def test_glm_weekly_limit_resets_in_utc(self):
        # Seen 2026-10-28: code 1310 words it differently from the 5-hour 1308.
        text = ("API Error: Request rejected (429) · [1310][Weekly/Monthly Limit Exhausted. "
                "Your limit will reset at 2026-11-02 23:52:29][20261028094557c82516b14b6d488b]")
        got = cloud.usage_limit(text)
        self.assertEqual((got["kind"], got["resetsAt"], got["resetsIn"]),
                         ("weekly/monthly", "2026-11-02T15:52:29Z", None))

    def test_cursor_weekly_limit(self):
        got = cloud.usage_limit("ActionRequiredError: Weekly usage limit reached. It resets in 4 days. "
                                "Buy credits to keep going now.")
        self.assertEqual((got["kind"], got["resetsAt"], got["resetsIn"]), ("weekly", None, "4 days"))

    def test_other_errors_are_not_limits(self):
        self.assertIsNone(cloud.usage_limit("API Error: Request rejected (500) · internal error"))
        self.assertIsNone(cloud.usage_limit(""))


class SetupNote(unittest.TestCase):
    def test_a_note_only_when_nothing_is_set_up(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("setup", cloud.setup_note({"KERYX_CONFIG": str(Path(d) / "none.json")}))
            p = Path(d) / "c.json"
            p.write_text(json.dumps({"executors": ["glm", "subagent"]}))
            self.assertIsNone(cloud.setup_note({"KERYX_CONFIG": str(p)}))


class Memory(unittest.TestCase):
    def test_a_credential_is_never_remembered(self):
        # Token-shaped values are built at run time, so secret scanners never see one in this file.
        fake_key, fake_pat = "sk-" + "live-" + "0123456789abcdef", "gh" + "p_" + "0123456789abcdef" * 2 + "abcd"
        for text in ("GLM_API_KEY=" + fake_key, "token " + fake_pat,
                     "password: hunter2hunter2", "the staging header is 9f8e7d6c5b4a39281706f5e4d3c2b1a0ffeeddcc"):
            self.assertTrue(cloud.looks_secret(text), text)
        self.assertFalse(cloud.looks_secret("the owner wants GLM first, then Cursor"))

    def test_remember_once_and_recall_both_scopes(self):
        import contextlib
        import io
        import os
        import subprocess
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            cfg = Path(tmp) / "cfg" / "config.json"
            old = os.getcwd()
            os.chdir(repo)
            try:
                with mock.patch.dict(os.environ, {"KERYX_CONFIG": str(cfg)}):
                    self.assertEqual(cloud.main(["remember", "the owner wants GLM first"]), 0)
                    self.assertEqual(cloud.main(["remember", "the owner wants GLM first"]), 0)
                    self.assertEqual(cloud.main(["remember", "--repo", "CI runs four /v1 files with --noconftest"]), 0)
                    self.assertEqual(cloud.main(["remember", "GLM_API_KEY=" + "sk-" + "live-" + "0123456789abcdef"]), 1)
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        self.assertEqual(cloud.main(["recall"]), 0)
                text = out.getvalue()
                self.assertEqual(text.count("the owner wants GLM first"), 1)
                self.assertIn("--noconftest", text)
                self.assertNotIn("sk-live", text)
                self.assertTrue((cfg.parent / "memory.md").exists())
                self.assertNotIn("noconftest", (cfg.parent / "memory.md").read_text())
            finally:
                os.chdir(old)


class RoundUsageLimit(unittest.TestCase):
    def test_only_the_rounds_own_report_counts(self):
        # The event log can quote a limit message from a file the executor read; only result.md and stderr.log
        # are the run's own words.
        msg = "[1308][Usage limit reached for 5 hour. Your limit will reset at 2026-10-27 19:58:02]"
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / "result.md").write_text("API Error: Request rejected (500) · internal error\n")
            (r / "events.ndjson").write_text(json.dumps({"type": "user", "text": msg}) + "\n")
            self.assertIsNone(cloud.round_usage_limit(r))
            (r / "stderr.log").write_text("API Error: Request rejected (429) · " + msg + "\n")
            self.assertEqual(cloud.round_usage_limit(r)["resetsAt"], "2026-10-27T11:58:02Z")


def _two_commit_repo(tmp):
    """A repository with a CLAUDE.md and app.py at the base, and one commit on top that changes app.py."""
    import subprocess
    repo = Path(tmp) / "repo"
    repo.mkdir()

    def run(*a):
        return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    run("init", "-q", "-b", "main")
    (repo / "CLAUDE.md").write_text("Domain code imports no framework.\n")
    (repo / "app.py").write_text("def f():\n    return 1\n")
    run("add", ".")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base")
    base = run("rev-parse", "HEAD")
    (repo / "app.py").write_text("def f():\n    return 2\n")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am", "fix: two")
    return repo, run, base, run("rev-parse", "HEAD")


def _cli(repo, argv):
    """Run keryx.py inside the repository; returns (exit code, stdout)."""
    import contextlib
    import io
    import os
    old = os.getcwd()
    os.chdir(repo)
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cloud.main(argv)
        return code, out.getvalue()
    finally:
        os.chdir(old)


class ReviewBrief(unittest.TestCase):
    """The fresh reviewer's prompt ships with keryx: the coordinator hands out a file instead of retyping the bar
    (field run 10 wrote its own prompt and lost the reach question and the P0-P3 grades)."""

    def test_the_brief_carries_the_bar_the_paths_and_where_to_write_the_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "rb"
            state.mkdir(parents=True)
            (state / "PLAN.md").write_text("# rb: f returns 2\n")
            code, out = _cli(repo, ["review-brief", "--slug", "rb", "--base", base, "--head", head])
            self.assertEqual(code, 0)
            name = f"{base[:12]}..{head[:12]}"
            brief = state / "review" / f"{name}.brief.md"
            text = brief.read_text()
            for must in ("Reach:", "Spec:", "P0", "P3", "confidence", "Findings:", head, str(state / "PLAN.md"),
                         str(state / "review" / f"{name}.diff"), str(state / "review" / f"{name}.findings.md"),
                         str(Path(run("rev-parse", "--show-toplevel")) / "CLAUDE.md")):
                self.assertIn(must, text)
            self.assertNotIn("{{", text)
            self.assertNotIn("Security pass", text)
            self.assertIn("+    return 2", (state / "review" / f"{name}.diff").read_text())
            self.assertEqual(out.count("dispatch"), 1)
            self.assertIn(f"dispatch  model=sonnet  prompt=\"Read {brief} and follow it exactly.\"", out)
            self.assertIn("review brief", (state / "decisions.tsv").read_text())

    def test_a_risk_list_diff_gets_two_finders_the_second_with_a_security_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "rb"
            code, out = _cli(repo, ["review-brief", "--slug", "rb", "--base", base, "--head", head, "--risk"])
            self.assertEqual(code, 0)
            name = f"{base[:12]}..{head[:12]}"
            first, second = state / "review" / f"{name}.brief.md", state / "review" / f"{name}.security.brief.md"
            self.assertNotIn("Security pass", first.read_text())
            self.assertIn("no plan file", first.read_text())
            self.assertIn("Security pass", second.read_text())
            self.assertIn("blame", second.read_text())
            self.assertIn(str(state / "review" / f"{name}.security.findings.md"), second.read_text())
            self.assertEqual(out.count("dispatch"), 2)
            self.assertIn(f"dispatch  model=opus  prompt=\"Read {first} and follow it exactly.\"", out)
            self.assertIn(f"dispatch  model=sonnet  prompt=\"Read {second} and follow it exactly.\"", out)

    def test_a_loop_supplies_base_and_head_and_without_one_the_base_is_needed(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "nb", "--head", head])[0], 1,
                             "no executor loop and no --base")
            (Path(tmp) / "brief.md").write_text("Mode: IMPLEMENT\n")
            self.assertEqual(_cli(repo, ["create", "--slug", "lp", "--runner", "subagent",
                                         "--prompt-file", str(Path(tmp) / "brief.md"), "--ref", "main"])[0], 0)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "lp"
            wt = json.loads((state / "agent.json").read_text())["workspace"]
            (Path(wt) / "app.py").write_text("def f():\n    return 3\n")
            subprocess.run(["git", "-C", wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am",
                            "fix: three"], check=True, capture_output=True)
            sub_head = run("rev-parse", "sub/lp")
            self.assertEqual(_cli(repo, ["fetch", "--slug", "lp"])[0], 0)
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "lp"])[0], 0)
            self.assertTrue((state / "review" / f"{head[:12]}..{sub_head[:12]}.brief.md").exists())


class FinishGate(unittest.TestCase):
    """A run is finished only when its log has a finish row and a well-formed fresh review covers the shipped head
    (field runs 8, 9 and 10 never logged one)."""

    GOOD = ("Head: {head}\nReach: POST /v1/x mounts the router; nothing breaks on the way\nSpec: matches\n"
            "Findings:\n- app.py:2 — returns 2 for every input — f() with no flag set gives 2, not 1 — P1 — 0.8\n"
            "- app.py:1 — the name f says nothing — any call — P3 — 0.4\n"
            "Tests: none would catch f() returning 3\n")

    def test_well_formed_findings_are_counted_and_malformed_ones_named(self):
        got = cloud.review_findings(self.GOOD.format(head="a" * 40))
        self.assertEqual((got["head"], got["problems"]), ("a" * 40, []))
        self.assertEqual(got["counts"], {"P0": 0, "P1": 1, "P2": 0, "P3": 1})
        clean = cloud.review_findings("Head: " + "b" * 40 + "\nReach: one caller\nSpec: matches\nFindings: none\n")
        self.assertEqual((clean["problems"], sum(clean["counts"].values())), ([], 0))
        no_reach = cloud.review_findings(self.GOOD.format(head="a" * 40).replace("Reach: POST", "Rich: POST"))
        self.assertTrue(any("Reach" in p for p in no_reach["problems"]))
        ungraded = cloud.review_findings(self.GOOD.format(head="a" * 40).replace(" — P1 — 0.8", ""))
        self.assertTrue(any("app.py:2" in p for p in ungraded["problems"]))
        self.assertTrue(cloud.review_findings("Reach: x\nSpec: y\nFindings: none\n")["problems"], "no Head line")
        self.assertTrue(cloud.review_findings("Head: " + "b" * 40 + "\nReach: x\nSpec: y\nFindings:\nTests: z\n")
                        ["problems"], "an empty list that does not say none")

    def test_finish_refuses_without_a_finish_row_or_a_well_formed_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "fg"
            self.assertEqual(_cli(repo, ["log", "--slug", "fg", "plan", "planned", "why", "ev", "ok"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "fg", "--head", head, "--findings-only"])
            self.assertEqual(code, 1)
            self.assertIn("NOT FINISHED", out)
            self.assertIn("missing  a finish row", out)
            self.assertIn("missing  a fresh review", out)
            self.assertFalse((state / "finished.json").exists())
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "fg", "--base", base, "--head", head])[0], 0)
            findings = state / "review" / f"{base[:12]}..{head[:12]}.findings.md"
            findings.write_text(self.GOOD.format(head=head).replace(" — P1 — 0.8", ""))
            self.assertEqual(_cli(repo, ["log", "--slug", "fg", "finish", "PR #6", "why", "ev", "merged"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "fg", "--head", head, "--findings-only"])
            self.assertEqual(code, 1, "an ungraded finding is not a review")
            self.assertIn(str(findings), out)
            self.assertIn("missing  a fresh review", out)
            self.assertNotIn("missing  a finish row", out)
            self.assertFalse((state / "finished.json").exists())

    def test_finish_passes_with_a_finish_row_and_a_review_and_reports_the_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "fg"
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "fg", "--base", base, "--head", head])[0], 0)
            findings = state / "review" / f"{base[:12]}..{head[:12]}.findings.md"
            findings.write_text(self.GOOD.format(head=head))
            for row in (["ruling", "Ruling: keep the old flag name", "renaming breaks callers", "app.py:1", "ruled"],
                        ["review", "minor (deferred): the name f", "P3", "app.py:1", "deferred"],
                        ["finish", "PR #7 merged into main", "the acceptance check passes", "ci run 42", "merged"]):
                self.assertEqual(_cli(repo, ["log", "--slug", "fg", *row])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "fg", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)
            self.assertIn("FINISHED", out)
            self.assertNotIn("NOT FINISHED", out)
            for must in ("PR #7 merged into main", "Ruling: keep the old flag name", "minor (deferred): the name f",
                         "P1 1", str(findings), "the final head"):
                self.assertIn(must, out)
            self.assertEqual(json.loads((state / "finished.json").read_text())["head"], head)
            last = (state / "decisions.tsv").read_text().splitlines()[-1].split("\t")
            self.assertEqual(last[1], "done")

    def test_a_review_counts_for_later_commits_on_top_but_not_for_another_line_of_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "fg"
            run("checkout", "-q", "-b", "side", base)
            (repo / "other.py").write_text("x = 1\n")
            run("add", "other.py")
            run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "side")
            side = run("rev-parse", "HEAD")
            run("checkout", "-q", "main")
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "fg", "--base", base, "--head", side])[0], 0)
            (state / "review" / f"{base[:12]}..{side[:12]}.findings.md").write_text(self.GOOD.format(head=side))
            self.assertEqual(_cli(repo, ["log", "--slug", "fg", "finish", "PR #8", "why", "ev", "merged"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "fg", "--head", head, "--findings-only"])
            self.assertEqual(code, 1, "the side branch's review does not cover main")
            self.assertIn("missing  a fresh review", out)
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "fg", "--base", base, "--head", head])[0], 0)
            (state / "review" / f"{base[:12]}..{head[:12]}.findings.md").write_text(self.GOOD.format(head=head))
            (repo / "app.py").write_text("def f():\n    return 4\n")
            run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am", "fix: four")
            later = run("rev-parse", "HEAD")
            code, out = _cli(repo, ["finish", "--slug", "fg", "--head", later, "--findings-only"])
            self.assertEqual(code, 0, out)
            self.assertIn("1 commit before the final head", out)

    def test_a_risk_review_needs_both_finders(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "fg"
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "fg", "--base", base, "--head", head,
                                         "--risk"])[0], 0)
            name = f"{base[:12]}..{head[:12]}"
            (state / "review" / f"{name}.findings.md").write_text(self.GOOD.format(head=head))
            self.assertEqual(_cli(repo, ["log", "--slug", "fg", "finish", "PR #9", "why", "ev", "merged"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "fg", "--head", head, "--findings-only"])
            self.assertEqual(code, 1, "the second finder has not reported")
            self.assertIn(f"{name}.security.findings.md", out)
            (state / "review" / f"{name}.security.findings.md").write_text(self.GOOD.format(head=head))
            self.assertEqual(_cli(repo, ["finish", "--slug", "fg", "--head", head, "--findings-only"])[0], 0)


class FinishRowsAreTheCoordinators(unittest.TestCase):
    """scrub and archive log their own rows under the finish phase; those never stand in for the run's finish row."""

    def test_a_scrubbed_branch_is_not_a_finished_run(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            (Path(tmp) / "brief.md").write_text("Mode: IMPLEMENT\n")
            self.assertEqual(_cli(repo, ["create", "--slug", "sc", "--runner", "subagent",
                                         "--prompt-file", str(Path(tmp) / "brief.md"), "--ref", "main"])[0], 0)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "sc"
            wt = json.loads((state / "agent.json").read_text())["workspace"]
            (Path(wt) / "app.py").write_text("def f():\n    return 3\n")
            subprocess.run(["git", "-C", wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am",
                            "fix: three\n\nCo-authored-by: Cursor <cursoragent@cursor.com>"], check=True,
                           capture_output=True)
            self.assertEqual(_cli(repo, ["scrub", "--slug", "sc"])[0], 0)
            self.assertIn("scrubbed", (state / "decisions.tsv").read_text())
            self.assertEqual(_cli(repo, ["fetch", "--slug", "sc"])[0], 0)
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "sc"])[0], 0)
            sub_head = (state / "head.txt").read_text().strip()
            (state / "review" / f"{head[:12]}..{sub_head[:12]}.findings.md").write_text(
                FinishGate.GOOD.format(head=sub_head))
            code, out = _cli(repo, ["finish", "--slug", "sc", "--findings-only"])
            self.assertEqual(code, 1, out)
            self.assertIn("missing  a finish row", out)
            self.assertEqual(_cli(repo, ["log", "--slug", "sc", "finish", "branch sub/sc committed", "why", "ev",
                                         "committed"])[0], 0)
            self.assertEqual(_cli(repo, ["finish", "--slug", "sc", "--findings-only"])[0], 0)


class ReviewBriefNamesTheCheckout(unittest.TestCase):
    """The reviewer reads the code at the reviewed head, not whatever the repository's own checkout holds (seen when
    keryx reviewed its own release: the main checkout was still at the base)."""

    def test_the_brief_names_where_the_head_is_checked_out_or_how_to_read_it(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            (Path(tmp) / "brief.md").write_text("Mode: IMPLEMENT\n")
            self.assertEqual(_cli(repo, ["create", "--slug", "wt", "--runner", "subagent",
                                         "--prompt-file", str(Path(tmp) / "brief.md"), "--ref", "main"])[0], 0)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "wt"
            wt = json.loads((state / "agent.json").read_text())["workspace"]
            (Path(wt) / "app.py").write_text("def f():\n    return 3\n")
            subprocess.run(["git", "-C", wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am",
                            "fix: three"], check=True, capture_output=True)
            sub_head = run("rev-parse", "sub/wt")
            self.assertEqual(_cli(repo, ["fetch", "--slug", "wt"])[0], 0)
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "wt"])[0], 0)
            text = (state / "review" / f"{head[:12]}..{sub_head[:12]}.brief.md").read_text()
            self.assertIn(f"- The head is checked out in {Path(wt).resolve()}: read the surrounding code there.", text)
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "wt", "--base", base, "--head", head])[0], 0)
            text = (state / "review" / f"{base[:12]}..{head[:12]}.brief.md").read_text()
            top = Path(run("rev-parse", "--show-toplevel"))
            self.assertIn(f"- The head is checked out in {top}: read the surrounding code there.", text)
            run("checkout", "-q", "-b", "side")
            (repo / "other.py").write_text("x = 1\n")
            run("add", "other.py")
            run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "side")
            side = run("rev-parse", "HEAD")
            run("checkout", "-q", "main")
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "wt", "--base", base, "--head", side])[0], 0)
            text = (state / "review" / f"{base[:12]}..{side[:12]}.brief.md").read_text()
            self.assertIn(f"- No checkout holds the head: read files with git show {side[:12]}:<path>, "
                          "never from a working tree.", text)
            self.assertNotIn("checked out in", text)


class FinishWithoutALoop(unittest.TestCase):
    """A PR or branch review has no executor loop and no fetched head: the refusal must say to pass --head, not to
    run fetch (which needs a loop)."""

    def test_the_message_names_head_when_there_is_no_loop(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self.assertEqual(_cli(repo, ["log", "--slug", "nh", "finish", "PR #1 reviewed", "why", "ev", "reported"])[0], 0)
            for argv in (["finish", "--slug", "nh", "--findings-only"], ["review-brief", "--slug", "nh", "--base", base]):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(_cli(repo, argv)[0], 1, argv)
                self.assertIn("--head", err.getvalue(), argv)


class FindingsAsReviewersWriteThem(unittest.TestCase):
    """Real findings files: CRLF line ends, a short head, a blank line after Findings:, a finding wrapped over two
    lines, and a reach answer that continues on the next line."""

    def test_a_real_reviewers_file_parses(self):
        text = ("Head: 1a2b3c4d5\r\nReach: the CLI entry point\r\n  calls f directly\r\nSpec: matches\r\n"
                "Findings:\r\n\r\n- app.py:2 — returns 2 — f() gives 2 where\r\n  the plan says 1 — P1 — 0.7\r\n"
                "- app.py:9 – a dead branch – any input – P3 – .5\r\nTests: none\r\n")
        got = cloud.review_findings(text)
        self.assertEqual(got["problems"], [])
        self.assertEqual(got["head"], "1a2b3c4d5")
        self.assertEqual(got["counts"], {"P0": 0, "P1": 1, "P2": 0, "P3": 1})


class KeryxFolder(unittest.TestCase):
    """A run's files live in <main checkout>/.keryx/runs/<slug>/, a folder that ignores itself: out of .git (a
    protected path where agent writes prompt or are denied) and out of git status."""

    def test_a_run_lives_in_dot_keryx_which_ignores_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            self.assertEqual(_cli(repo, ["log", "--slug", "lay", "intake", "size M", "why", "ev", "M"])[0], 0)
            self.assertTrue((top / ".keryx" / "runs" / "lay" / "decisions.tsv").is_file())
            self.assertEqual((top / ".keryx" / ".gitignore").read_text(), "*\n")
            self.assertEqual(run("status", "--porcelain"), "")
            self.assertFalse((Path(run("rev-parse", "--absolute-git-dir")) / "cursor-loop").exists())

    def test_reading_never_creates_the_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            self.assertEqual(_cli(repo, ["recall"])[0], 0)
            self.assertEqual(_cli(repo, ["finish", "--slug", "none", "--head", head])[0], 1)
            self.assertFalse((Path(run("rev-parse", "--show-toplevel")) / ".keryx").exists())

    def test_every_worktree_shares_the_main_checkouts_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            (Path(tmp) / "brief.md").write_text("Mode: IMPLEMENT\n")
            self.assertEqual(_cli(repo, ["create", "--slug", "wl", "--runner", "subagent",
                                         "--prompt-file", str(Path(tmp) / "brief.md"), "--ref", "main"])[0], 0)
            state = top / ".keryx" / "runs" / "wl"
            wt = Path(json.loads((state / "agent.json").read_text())["workspace"])
            self.assertEqual(wt.parent.name, ".worktrees")
            self.assertEqual(_cli(wt, ["log", "--slug", "wl", "check", "from the worktree", "why", "ev", "ok"])[0], 0)
            self.assertIn("from the worktree", (state / "decisions.tsv").read_text())
            self.assertFalse((wt / ".keryx").exists())
            self.assertEqual(_cli(repo, ["fetch", "--slug", "wl"])[0], 0)
            self.assertEqual(run("rev-parse", "refs/keryx/wl"), run("rev-parse", "sub/wl"))

    def test_a_run_started_before_the_move_stays_where_it_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            legacy = Path(run("rev-parse", "--absolute-git-dir")) / "cursor-loop" / "old"
            legacy.mkdir(parents=True)
            (legacy / "decisions.tsv").write_text("ts\tphase\tdecision\twhy\tevidence\tresult\n"
                                                  "2026-10-28T10:00:00Z\tintake\tsize M\tw\te\tM\n")
            self.assertEqual(_cli(repo, ["log", "--slug", "old", "plan", "planned", "why", "ev", "ok"])[0], 0)
            self.assertIn("planned", (legacy / "decisions.tsv").read_text())
            self.assertFalse((Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "old").exists())

    def test_the_repositorys_memory_moves_into_dot_keryx(self):
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            legacy = Path(run("rev-parse", "--absolute-git-dir")) / "cursor-loop" / "memory.md"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("- 2026-10-20 CI runs four files with --noconftest\n")
            with mock.patch.dict(os.environ, {"KERYX_CONFIG": str(Path(tmp) / "cfg" / "config.json")}):
                self.assertIn("--noconftest", _cli(repo, ["recall"])[1], "an old note is still recalled")
                self.assertEqual(_cli(repo, ["remember", "--repo", "the e2e suite needs the dev stack"])[0], 0)
                out = _cli(repo, ["recall"])[1]
            mem = top / ".keryx" / "memory.md"
            self.assertIn("--noconftest", mem.read_text())
            self.assertIn("the e2e suite needs the dev stack", mem.read_text())
            self.assertFalse(legacy.exists())
            self.assertEqual(out.count("--noconftest"), 1)


class WorktreesFolderIgnoresItself(unittest.TestCase):
    """Executors' worktrees live in <main checkout>/.worktrees/, which ignores itself as .keryx/ does: a round
    leaves git status as it found it, in the repository and in a superproject around a submodule."""

    def _round(self, where, tmp, slug):
        (Path(tmp) / "brief.md").write_text("Mode: IMPLEMENT\n")
        return _cli(where, ["create", "--slug", slug, "--runner", "subagent",
                            "--prompt-file", str(Path(tmp) / "brief.md"), "--ref", "main"])

    def test_a_round_leaves_git_status_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            code, out = self._round(repo, tmp, "ws")
            self.assertEqual(code, 0, out)
            self.assertEqual(run("status", "--porcelain"), "")
            self.assertEqual((top / ".worktrees" / ".gitignore").read_text(), "*\n")
            self.assertEqual(run("-C", str(top / ".worktrees" / "sub-ws"), "status", "--porcelain"), "")

    def test_a_folder_an_older_round_left_is_ignored_from_the_next_round_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            run("worktree", "add", "-q", "-b", "sub/old", str(top / ".worktrees" / "sub-old"))
            self.assertEqual(run("status", "--porcelain"), "?? .worktrees/", "the state 1.2.1 left")
            code, out = self._round(repo, tmp, "nx")
            self.assertEqual(code, 0, out)
            self.assertEqual(run("status", "--porcelain"), "")

    def test_a_round_in_a_submodule_leaves_the_superproject_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()
            g = WorktreesOfABareRepositoryOrASubmodule._g(t)
            g("init", "-q", "-b", "main", "sub")
            g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "sub")
            g("init", "-q", "-b", "main", "sup")
            g("submodule", "-q", "add", str(t / "sub"), "mod", cwd=t / "sup")
            g("commit", "-q", "-m", "mod", cwd=t / "sup")
            code, out = self._round(t / "sup" / "mod", tmp, "sm")
            self.assertEqual(code, 0, out)
            self.assertEqual(g("status", "--porcelain", cwd=t / "sup").stdout, "")
            self.assertEqual(g("status", "--porcelain", cwd=t / "sup" / "mod").stdout, "")


class RunReport(unittest.TestCase):
    """Each finished run leaves a short report in the repository, docs/keryx/<date>-<slug>.md; screenshots and
    executor logs stay in the ignored folder."""

    def _reviewed(self, tmp):
        repo, run, base, head = _two_commit_repo(tmp)
        top = Path(run("rev-parse", "--show-toplevel"))
        state = top / ".keryx" / "runs" / "rp"
        self.assertEqual(_cli(repo, ["review-brief", "--slug", "rp", "--base", base, "--head", head])[0], 0)
        (state / "review" / f"{base[:12]}..{head[:12]}.findings.md").write_text(FinishGate.GOOD.format(head=head))
        (state / "PLAN.md").write_text("# rp: f returns 2\n\n## Acceptance check\n"
                                       "`python3 -c 'import app; assert app.f() == 2'` — on the base: AssertionError.\n")
        for row in (["ruling", "Ruling: keep the name f", "callers use it", "app.py:1", "a rename later"],
                    ["review", "minor (deferred): f has no docstring", "P3", "app.py:1", "deferred"],
                    ["finish", "branch main committed", "the acceptance check passes", "ev", "committed"]):
            self.assertEqual(_cli(repo, ["log", "--slug", "rp", *row])[0], 0)
        return repo, run, head, top, state

    def test_the_report_is_drafted_from_the_run_and_finish_needs_it_filled_and_committed(self):
        import datetime
        import re
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, head, top, state = self._reviewed(tmp)
            code, out = _cli(repo, ["report", "--slug", "rp"])
            self.assertEqual(code, 0, out)
            name = f"docs/keryx/{datetime.date.today().isoformat()}-rp.md"
            report = top / name
            self.assertIn(name, out)
            text = report.read_text()
            for must in ("# rp: f returns 2", "## What changed", "## Proof",
                         "python3 -c 'import app; assert app.f() == 2'", "P1 1", "Ruling: keep the name f",
                         "minor (deferred): f has no docstring", ".keryx/runs/rp/", "<!--"):
                self.assertIn(must, text)
            self.assertNotIn(str(top), text, "a committed report names no local absolute path")
            code, out = _cli(repo, ["finish", "--slug", "rp", "--head", head])
            self.assertEqual(code, 1)
            self.assertIn("missing  the run report", out)
            run("add", name)
            run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "docs(keryx): draft report")
            draft = run("rev-parse", "HEAD")
            code, out = _cli(repo, ["finish", "--slug", "rp", "--head", draft])
            self.assertEqual(code, 1, "a draft with its placeholders left is not a report")
            self.assertIn("missing  the run report", out)
            report.write_text(re.sub(r"<!--.*?-->", "filled in", text, flags=re.S))
            run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am", "docs(keryx): report for rp")
            done = run("rev-parse", "HEAD")
            code, out = _cli(repo, ["finish", "--slug", "rp", "--head", done])
            self.assertEqual(code, 0, out)
            self.assertIn(name, out)

    def test_a_findings_only_review_finishes_without_a_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, head, top, state = self._reviewed(tmp)
            self.assertEqual(_cli(repo, ["finish", "--slug", "rp", "--head", head])[0], 1)
            code, out = _cli(repo, ["finish", "--slug", "rp", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)
            self.assertFalse((top / "docs" / "keryx").exists())


class KeryxNames(unittest.TestCase):
    """The adapter is keryx's, not the old cursor-loop skill's; the old script name keeps working for one release."""

    def test_the_adapter_calls_itself_keryx(self):
        import contextlib
        import io
        self.assertTrue(cloud.USER_AGENT.startswith("keryx/"))
        self.assertEqual(cloud.NO_PUSH_ENV["GIT_CONFIG_VALUE_0"], "https://push-disabled.invalid/keryx")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cloud.main(["--help"])
        self.assertNotIn("cursor-loop", out.getvalue())
        self.assertNotIn("Cursor adapter", out.getvalue())

    def test_the_old_script_name_still_runs_the_adapter(self):
        import subprocess
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            r = subprocess.run([sys.executable, str(scripts / "cursor.py"), "log", "--slug", "sh", "intake",
                                "via the old name", "why", "ev", "ok"], cwd=repo, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("via the old name",
                          (Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "sh" / "decisions.tsv")
                          .read_text())
            r = subprocess.run([sys.executable, str(scripts / "keryx.py"), "finish", "--slug", "nope", "--head",
                                head], cwd=repo, capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertTrue(r.stderr.startswith("keryx: "), r.stderr)


class ExecutorsAndTheKeryxFolder(unittest.TestCase):
    """GLM, a third party's model, reads no run and not the repository's memory: its own Claude Code config, which
    it reads large tool outputs back from, now lives beside the runs (.keryx/glm/<slug>/), so every run can be
    denied. The Cursor CLI, another third party, is denied the runs' QA evidence and reproductions, which can show
    real people. (1.2.0 denied GLM only those two and the Cursor CLI nothing.)"""

    def test_glm_is_denied_every_run_and_the_memory(self):
        for rule in ("Read(**/.keryx/runs/**)", "Read(//**/.keryx/runs/**)",
                     "Read(**/.keryx/memory.md)", "Read(//**/.keryx/memory.md)"):
            self.assertIn(rule, cloud.GLM_DENY)

    def test_glms_own_config_lies_beside_the_runs(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            (Path(tmp) / "brief.md").write_text("Mode: IMPLEMENT\n")
            code, out = _cli(repo, ["create", "--slug", "gc", "--runner", "glm", "--dry-run",
                                    "--prompt-file", str(Path(tmp) / "brief.md"), "--ref", "main"])
            self.assertEqual(code, 0, out)
            cmd = json.loads(out)["command"]
            self.assertEqual(cmd[cmd.index("--settings") + 1], str(top / ".keryx" / "glm" / "gc" / "settings.json"))
            old = os.getcwd()
            os.chdir(repo)
            try:
                cfg = cloud.write_glm_config(cloud.state_root() / "gc")
            finally:
                os.chdir(old)
            self.assertEqual(cfg, top / ".keryx" / "glm" / "gc")
            self.assertIn("Read(//**/.keryx/runs/**)",
                          json.loads((cfg / "settings.json").read_text())["permissions"]["deny"])
            self.assertEqual((top / ".keryx" / ".gitignore").read_text(), "*\n")
            self.assertEqual(run("status", "--porcelain"), "")

    def test_the_cursor_cli_is_denied_the_evidence(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            wt = top / ".worktrees" / "cursor-cd"
            run("worktree", "add", "-q", "-b", "cursor/cd", str(wt))
            old = os.getcwd()
            os.chdir(repo)
            try:
                cloud.write_cli_permissions(wt)
            finally:
                os.chdir(old)
            deny = json.loads((wt / ".cursor" / "cli.json").read_text())["permissions"]["deny"]
            for rule in (f"Read({top}/.keryx/runs/*/qa/**)", f"Read({top}/.keryx/runs/*/repro/**)",
                         f"Read({top}/.keryx/memory.md)"):
                self.assertIn(rule, deny)


class OtherRepositoryShapes(unittest.TestCase):
    """A separate git dir, a submodule (and its linked worktree) and a bare repository's worktrees all keep their
    runs; 1.2's first cut asked git for the top level inside the git dir, which these layouts refuse."""

    def test_each_layout_keeps_its_runs_in_one_shared_folder(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()

            def g(*a, cwd=t):
                return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                       "-c", "protocol.file.allow=always", *a],
                                      cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

            g("init", "-q", "-b", "main", "sep", f"--separate-git-dir={t / 'sep.gitdir'}")
            g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "sep")
            g("init", "-q", "-b", "main", "sub")
            g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "sub")
            g("init", "-q", "-b", "main", "sup")
            g("submodule", "-q", "add", str(t / "sub"), "mod", cwd=t / "sup")
            g("worktree", "add", "-q", "-b", "side", str(t / "mod-wt"), cwd=t / "sup" / "mod")
            g("clone", "-q", "--bare", str(t / "sub"), "bare.git")
            g("worktree", "add", "-q", str(t / "wt-a"), "main", cwd=t / "bare.git")
            g("worktree", "add", "-q", "-b", "b2", str(t / "wt-b"), cwd=t / "bare.git")
            for where, home in ((t / "sep", t / "sep"), (t / "sup" / "mod", t / "sup" / "mod"),
                                (t / "mod-wt", t / "sup" / "mod"), (t / "wt-a", t / "bare.git"),
                                (t / "wt-b", t / "bare.git")):
                code, out = _cli(where, ["log", "--slug", "sh", "intake", f"from {where.name}", "why", "ev", "ok"])
                self.assertEqual(code, 0, where)
                self.assertIn(f"from {where.name}", (home / ".keryx" / "runs" / "sh" / "decisions.tsv").read_text())
            self.assertEqual(g("status", "--porcelain", cwd=t / "sup" / "mod"), "")


class ReportKeepsLocalPathsOut(unittest.TestCase):
    """Text the report copies from the plan and the log names no local path: the report is committed, often to a
    public repository."""

    def test_copied_text_names_no_local_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            state = top / ".keryx" / "runs" / "lp"
            self.assertEqual(_cli(repo, ["log", "--slug", "lp", "ruling",
                                         f"Ruling: read {top}/app.py, not {Path.home()}/notes.txt", "why", "ev",
                                         "ok"])[0], 0)
            (state / "PLAN.md").write_text(f"# lp: fix {top}/app.py\n\n## Acceptance check\n"
                                           f"`python3 {top}/app.py` — on the base: 1\n")
            self.assertEqual(_cli(repo, ["report", "--slug", "lp"])[0], 0)
            text = next((top / "docs" / "keryx").glob("*-lp.md")).read_text()
            self.assertNotIn(str(top), text)
            self.assertNotIn(str(Path.home()), text)
            self.assertIn("`python3 app.py`", text)
            self.assertIn("~/notes.txt", text)


class NoSurroundingRepository(unittest.TestCase):
    """The suite runs from an export without .git (seen in a Linux check): a state root pointed elsewhere needs no
    repository around the current directory."""

    def test_a_log_row_needs_no_repository_when_the_state_root_points_elsewhere(self):
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.object(cloud, "state_root", lambda: Path(tmp) / "loops"):
                    self.assertEqual(cloud.main(["log", "--slug", "s", "intake", "x", "w", "e", "ok"]), 0)
            finally:
                os.chdir(old)
            self.assertTrue((Path(tmp) / "loops" / "s" / "decisions.tsv").is_file())


class FinishFromASubdirectory(unittest.TestCase):
    """A monorepo coordinator often works from a package folder: report and finish find the top level anyway."""

    def test_report_and_finish_work_from_a_subdirectory(self):
        import re
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            pkg = repo / "pkg"
            pkg.mkdir()
            state = top / ".keryx" / "runs" / "sd"
            self.assertEqual(_cli(pkg, ["review-brief", "--slug", "sd", "--base", base, "--head", head])[0], 0)
            (state / "review" / f"{base[:12]}..{head[:12]}.findings.md").write_text(FinishGate.GOOD.format(head=head))
            self.assertEqual(_cli(pkg, ["log", "--slug", "sd", "finish", "branch main committed", "why", "ev",
                                        "committed"])[0], 0)
            code, out = _cli(pkg, ["report", "--slug", "sd"])
            self.assertEqual(code, 0, out)
            report = next((top / "docs" / "keryx").glob("*-sd.md"))
            report.write_text(re.sub(r"<!--.*?-->", "filled in", report.read_text(), flags=re.S))
            run("add", str(report))
            run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "docs(keryx): report for sd")
            code, out = _cli(pkg, ["finish", "--slug", "sd", "--head", run("rev-parse", "HEAD")])
            self.assertEqual(code, 0, out)


class FinishSaysWhichHeadItChecked(unittest.TestCase):
    """Without --head, finish checks the executor's fetched head; when the report ships on another branch, the
    refusal says which head it checked and to pass --head."""

    def test_the_refusal_names_the_head_and_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "nh2"
            self.assertEqual(_cli(repo, ["log", "--slug", "nh2", "finish", "PR #3", "why", "ev", "merged"])[0], 0)
            (state / "head.txt").write_text(base + "\n")
            code, out = _cli(repo, ["finish", "--slug", "nh2"])
            self.assertEqual(code, 1)
            line = next(x for x in out.splitlines() if x.startswith("missing  the run report"))
            self.assertIn(base[:12], line)
            self.assertIn("--head", line)


class ReportForAnOldRunInASubmodule(unittest.TestCase):
    """A run started before 1.2 in a submodule lives under the superproject's git dir, outside the checkout: its
    report still gets written, with relative paths."""

    def test_an_old_run_outside_the_checkout_still_gets_its_report(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()

            def g(*a, cwd=t):
                return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                       "-c", "protocol.file.allow=always", *a],
                                      cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

            g("init", "-q", "-b", "main", "sub")
            g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "sub")
            g("init", "-q", "-b", "main", "sup")
            g("submodule", "-q", "add", str(t / "sub"), "mod", cwd=t / "sup")
            mod = t / "sup" / "mod"
            legacy = Path(g("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=mod)) / "cursor-loop" / "lg"
            (legacy / "review").mkdir(parents=True)
            (legacy / "decisions.tsv").write_text("ts\tphase\tdecision\twhy\tevidence\tresult\n"
                                                  "2026-10-28T10:00:00Z\tintake\tsize M\tw\te\tM\n")
            head = g("rev-parse", "HEAD", cwd=mod)
            (legacy / "review" / f"{head[:12]}..{head[:12]}.findings.md").write_text(FinishGate.GOOD.format(head=head))
            code, out = _cli(mod, ["report", "--slug", "lg"])
            self.assertEqual(code, 0, out)
            text = next((mod / "docs" / "keryx").glob("*-lg.md")).read_text()
            self.assertIn("P1 1", text)
            self.assertNotIn(str(t), text)


class TwoBareRepositoriesSideBySide(unittest.TestCase):
    """Bare repositories in one folder keep their runs and memory apart: each keeps .keryx/ in its own folder."""

    def test_they_keep_separate_runs_and_memory(self):
        import os
        import subprocess
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()

            def g(*a, cwd=t):
                return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
                                      cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

            g("init", "-q", "-b", "main", "src")
            g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "src")
            for name in ("alpha", "beta"):
                g("clone", "-q", "--bare", str(t / "src"), f"{name}.git")
                g("worktree", "add", "-q", str(t / f"{name}-wt"), "main", cwd=t / f"{name}.git")
            with mock.patch.dict(os.environ, {"KERYX_CONFIG": str(t / "cfg" / "config.json")}):
                self.assertEqual(_cli(t / "alpha-wt", ["remember", "--repo", "alpha keeps its fixtures in db/"])[0], 0)
                self.assertNotIn("alpha keeps its fixtures", _cli(t / "beta-wt", ["recall"])[1])
            for name in ("alpha", "beta"):
                self.assertEqual(_cli(t / f"{name}-wt", ["log", "--slug", "fix-auth", "intake", f"from {name}", "w",
                                                         "e", "ok"])[0], 0)
            alpha = (t / "alpha.git" / ".keryx" / "runs" / "fix-auth" / "decisions.tsv").read_text()
            beta = (t / "beta.git" / ".keryx" / "runs" / "fix-auth" / "decisions.tsv").read_text()
            self.assertIn("from alpha", alpha)
            self.assertNotIn("from beta", alpha)
            self.assertIn("from beta", beta)


class ReportLeavesSiblingFoldersAlone(unittest.TestCase):
    """Stripping the checkout's path stops at a path boundary: a sibling folder that shares its name is not garbled."""

    def test_a_sibling_folder_sharing_the_checkouts_name_is_not_garbled(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            self.assertEqual(_cli(repo, ["log", "--slug", "sb", "ruling",
                                         f"Ruling: keep {top}-other/calendar.py and {top}/app.py", "why", "ev",
                                         "ok"])[0], 0)
            self.assertEqual(_cli(repo, ["report", "--slug", "sb"])[0], 0)
            text = next((top / "docs" / "keryx").glob("*-sb.md")).read_text()
            # since 1.2.1 the sibling, a local path too, becomes a placeholder rather than staying as it was
            self.assertNotIn(f"{top}-other", text)
            self.assertIn("<!-- a local path was here --> and app.py", text)
            self.assertNotIn(".-other", text)


class ReportPathsAtTheEndOfASentence(unittest.TestCase):
    """A path that ends a sentence is still a path, and a bare repository's worktree is a checkout too: the report
    names neither."""

    def test_a_path_before_a_full_stop_is_stripped(self):
        w, h = Path("/no-such-root-w/proj"), Path("/no-such-root-h")
        self.assertEqual(cloud.strip_local_paths("run it from /no-such-root-w/proj.", w, h), "run it from ..")
        self.assertEqual(cloud.strip_local_paths("see /no-such-root-w/proj/app.py.", w, h), "see app.py.")
        self.assertEqual(cloud.strip_local_paths("notes in /no-such-root-h/notes.", w, h), "notes in ~/notes.")
        kept = "/no-such-root-w/proj.v2 and /no-such-root-w/proj-other stay"
        self.assertEqual(cloud.strip_local_paths(kept, w, h), kept)

    def test_a_bare_repositorys_worktree_report_names_no_local_path(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()

            def g(*a, cwd=t):
                return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
                                      cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

            g("init", "-q", "-b", "main", "src")
            g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "src")
            g("clone", "-q", "--bare", str(t / "src"), "alpha.git")
            g("worktree", "add", "-q", str(t / "alpha-wt"), "main", cwd=t / "alpha.git")
            wt = t / "alpha-wt"
            self.assertEqual(_cli(wt, ["log", "--slug", "bw", "ruling", f"Ruling: keep {wt}/app.py as it is.", "why",
                                       "ev", "ok"])[0], 0)
            self.assertEqual(_cli(wt, ["report", "--slug", "bw"])[0], 0)
            text = next((wt / "docs" / "keryx").glob("*-bw.md")).read_text()
            self.assertNotIn(str(t), text)
            self.assertIn("keep app.py as it is.", text)


class WorktreesOfABareRepositoryOrASubmodule(unittest.TestCase):
    """A subagent's worktree blocks pushes through a config of its own (extensions.worktreeConfig). Under that
    extension git reads core.bare and core.worktree from the shared config in every worktree, so they belong in the
    main worktree's config.worktree (git-worktree(1), CONFIGURATION FILE). 1.2.0 left them shared: every worktree
    of a bare repository failed `git status`, and a submodule's linked worktree lost its own checkout."""

    @staticmethod
    def _g(t):
        import os
        import subprocess
        # Without the GIT_CONFIG_* overrides an executor's own shell carries (its pushurl would answer instead).
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}

        def g(*a, cwd=t, check=True):
            return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                   "-c", "protocol.file.allow=always", *a],
                                  cwd=cwd, check=check, capture_output=True, text=True, env=env)
        return g

    def _bare(self, t):
        g = self._g(t)
        g("init", "-q", "-b", "main", "src")
        g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "src")
        g("clone", "-q", "--bare", str(t / "src"), "bare.git")
        g("worktree", "add", "-q", str(t / "wt-a"), "main", cwd=t / "bare.git")
        g("worktree", "add", "-q", "-b", "b2", str(t / "wt-b"), cwd=t / "bare.git")
        (t / "brief.md").write_text("Mode: IMPLEMENT\n")
        return g

    def _round(self, t, where, slug):
        return _cli(where, ["create", "--slug", slug, "--runner", "subagent", "--prompt-file", str(t / "brief.md"),
                            "--ref", "main"])

    def test_every_worktree_of_a_bare_repository_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()
            g = self._bare(t)
            code, out = self._round(t, t / "wt-a", "bs")
            self.assertEqual(code, 0, out)
            sub = t / "bare.git" / ".worktrees" / "sub-bs"
            for wt in (t / "wt-a", t / "wt-b", sub):
                self.assertEqual(g("status", "--porcelain", cwd=wt, check=False).returncode, 0, wt)
            self.assertEqual(g("rev-parse", "--is-bare-repository", cwd=t / "bare.git").stdout.strip(), "true")
            self.assertEqual(g("config", "--get", "remote.origin.pushurl", cwd=sub).stdout.strip(),
                             "https://push-disabled.invalid/keryx")
            self.assertEqual(g("config", "--get", "remote.origin.pushurl", cwd=t / "wt-a", check=False).stdout, "")

    def test_a_submodules_linked_worktree_keeps_its_own_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()
            g = self._g(t)
            g("init", "-q", "-b", "main", "sub")
            g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "sub")
            g("init", "-q", "-b", "main", "sup")
            g("submodule", "-q", "add", str(t / "sub"), "mod", cwd=t / "sup")
            mod = t / "sup" / "mod"
            g("worktree", "add", "-q", "-b", "side", str(t / "mod-wt"), cwd=mod)
            (t / "brief.md").write_text("Mode: IMPLEMENT\n")
            code, out = self._round(t, mod, "ms")
            self.assertEqual(code, 0, out)
            for wt in (mod, t / "mod-wt", mod / ".worktrees" / "sub-ms"):
                self.assertEqual(Path(g("rev-parse", "--show-toplevel", cwd=wt).stdout.strip()).resolve(), wt, wt)
            self.assertEqual(g("status", "--porcelain", cwd=t / "sup", check=False).returncode, 0)

    def test_a_repository_1_2_0_left_broken_is_repaired_by_the_next_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()
            g = self._bare(t)
            g("config", "extensions.worktreeConfig", "true", cwd=t / "bare.git")
            self.assertNotEqual(g("status", cwd=t / "wt-b", check=False).returncode, 0, "the state 1.2.0 left")
            code, out = self._round(t, t / "wt-a", "rp")
            self.assertEqual(code, 0, out)
            for wt in (t / "wt-a", t / "wt-b"):
                self.assertEqual(g("status", "--porcelain", cwd=wt, check=False).returncode, 0, wt)


class RunReportFromTheWholeRun(unittest.TestCase):
    """Drafting 1.2.0's own report showed four gaps: a multi-line acceptance check cut at its first line, the slices'
    executor rounds left out, a replaced ruling listed as if it still stood, and a review row that merely mentioned
    "deferred" listed as a deferred item. finish printed a ruling's evidence where its reason belongs."""

    @staticmethod
    def _draft(repo, run, slug):
        code, out = _cli(repo, ["report", "--slug", slug])
        assert code == 0, out
        return next((Path(run("rev-parse", "--show-toplevel")) / "docs" / "keryx").glob(f"*-{slug}.md")).read_text()

    @staticmethod
    def _reviewed(repo, base, head, slug, state):
        assert _cli(repo, ["review-brief", "--slug", slug, "--base", base, "--head", head])[0] == 0
        (state / "review" / f"{base[:12]}..{head[:12]}.findings.md").write_text(FinishGate.GOOD.format(head=head))
        assert _cli(repo, ["log", "--slug", slug, "finish", "findings reported", "why", "ev", "reported"])[0] == 0

    def test_the_whole_acceptance_check_is_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "ac"
            self.assertEqual(_cli(repo, ["log", "--slug", "ac", "intake", "size M", "why", "ev", "M"])[0], 0)
            (state / "PLAN.md").write_text("# ac: f returns 2\n\n## Acceptance check\nAt the base commit:\n"
                                           "- `python3 -m unittest` → FAILED (failures=2)\n"
                                           "- `python3 app.py` → prints 1\n\n## Ground truth\n- Fact: x\n")
            text = self._draft(repo, run, "ac")
            for line in ("At the base commit:", "`python3 -m unittest` → FAILED (failures=2)",
                         "`python3 app.py` → prints 1"):
                self.assertIn(line, text)
            self.assertNotIn("Fact: x", text)

    def test_the_slices_rounds_count_with_the_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            runs = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs"
            (runs / "sl-old").mkdir(parents=True)
            (runs / "sl-old" / "decisions.tsv").write_text("ts\tphase\tdecision\twhy\tevidence\tresult\n"
                                                           "2020-01-01T00:00:00Z\tintake\tan older run\tw\te\tM\n")
            self.assertEqual(_cli(repo, ["log", "--slug", "sl", "intake", "size L", "why", "ev", "L"])[0], 0)
            (runs / "sl" / "PLAN.md").write_text("# sl: slices\n\n## Slices\n- sl-a: owns a.py\n- sl-b: owns b.py\n")
            for name, modes in (("sl-a", ("IMPLEMENT", "FIX")), ("sl-b", ("IMPLEMENT",)), ("sl-old", ("FIX",) * 5),
                                ("sl-later", ("FIX",) * 4)):  # a later run the plan does not name is no slice
                if name != "sl-old":
                    self.assertEqual(_cli(repo, ["log", "--slug", name, "dispatch", "slice", "w", "e", "ok"])[0], 0)
                for i, mode in enumerate(modes, 1):
                    r = runs / name / "rounds" / f"{i:02d}"
                    r.mkdir(parents=True)
                    (r / "prompt.md").write_text(f"Mode: {mode}\nGoal: x\n")
            text = self._draft(repo, run, "sl")
            for part in ("3 executor rounds (1 FIX)", "sl-a 2", "sl-b 1"):
                self.assertIn(part, text)
            self.assertNotIn("sl-old", text)
            # since the second review an unnamed later run is not counted but named for the coordinator
            self.assertIn("<!-- sl-later (4 rounds, 4 FIX) started after this run", text)
            self._reviewed(repo, base, head, "sl", runs / "sl")
            code, out = _cli(repo, ["finish", "--slug", "sl", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)
            self.assertIn("3 executor rounds, 1 of them FIX", out)

    def test_a_replaced_ruling_is_left_out_and_log_names_each_rows_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            log = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "rr" / "decisions.tsv"
            self.assertEqual(_cli(repo, ["log", "--slug", "rr", "intake", "size M", "why", "ev", "M"])[0], 0)
            code, out = _cli(repo, ["log", "--slug", "rr", "ruling", "Ruling: deny the whole folder", "privacy", "ev",
                                    "if wrong: x"])
            self.assertEqual(code, 0, out)
            self.assertIn("row 2", out)
            for bad in ("Ruling (replaces row 1): no", "Ruling (replaces row 7): no"):
                self.assertEqual(_cli(repo, ["log", "--slug", "rr", "ruling", bad, "w", "e", "r"])[0], 1, bad)
            self.assertEqual(len(log.read_text().splitlines()), 3, "a refused row is not written")
            self.assertEqual(_cli(repo, ["log", "--slug", "rr", "ruling", "Ruling (replaces row 2): deny only qa/",
                                         "its config lives there", "ev", "if wrong: y"])[0], 0)
            text = self._draft(repo, run, "rr")
            self.assertIn("deny only qa/", text)
            self.assertNotIn("deny the whole folder", text)

    def test_only_rows_marked_deferred_are_deferred_and_finish_shows_a_rulings_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "df"
            for row in (["review", "minor (deferred): f has no docstring", "P3", "app.py:1", "deferred"],
                        ["review", "second review (two finders): none above P3; security P3 1 (deferred)",
                         "converged", "ev", "converged"],
                        ["ruling", "Ruling: keep the name f", "callers use it", "seen at app.py:1",
                         "if wrong: a rename"]):
                self.assertEqual(_cli(repo, ["log", "--slug", "df", *row])[0], 0)
            text = self._draft(repo, run, "df")
            self.assertIn("minor (deferred): f has no docstring", text)
            self.assertNotIn("second review", text)
            self._reviewed(repo, base, head, "df", state)
            code, out = _cli(repo, ["finish", "--slug", "df", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)
            deferred = [line for line in out.splitlines() if line.startswith("deferred")]
            self.assertEqual(deferred, ["deferred  minor (deferred): f has no docstring"])
            ruling = next(line for line in out.splitlines() if line.startswith("ruling"))
            self.assertIn("callers use it", ruling)
            self.assertNotIn("seen at app.py:1", ruling)


class ReportNamesNoLocalPath(unittest.TestCase):
    """1.2.0 stripped the checkout and the home folder from what the report copies; any other local path (a scratch
    folder, a sibling such as <checkout>.git, a checkout reached through a symlink) stayed as it was. Each now
    becomes a placeholder the coordinator rewrites, and finish refuses a report that still has one."""

    def test_any_other_local_path_becomes_a_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            state = top / ".keryx" / "runs" / "op"
            self.assertEqual(_cli(repo, ["log", "--slug", "op", "ruling",
                                         f"Ruling: keep {top}.git/hooks and {tmp}/repo/app.py; POST /api/v1/agents "
                                         "stays", "why", "ev", "ok"])[0], 0)
            (state / "PLAN.md").write_text("# op: f returns 2\n\n## Acceptance check\n"
                                           "`python3 /tmp/keryx-probe/run.py` — on the base: 1\n")
            self.assertEqual(_cli(repo, ["report", "--slug", "op"])[0], 0)
            text = next((top / "docs" / "keryx").glob("*-op.md")).read_text()
            for local in (f"{top}.git", str(Path(tmp)), "/tmp/keryx-probe"):
                self.assertNotIn(local, text)
            self.assertIn("POST /api/v1/agents stays", text)
            self.assertIn("`python3 <!-- a local path was here -->`", text)

    def test_a_sibling_with_a_non_ascii_name_is_not_garbled(self):
        w, h = Path("/no-such-root-w/proj"), Path("/no-such-root-h")
        self.assertEqual(cloud.strip_local_paths("/no-such-root-w/proj/a.py and /no-such-root-w/projé/b.py", w, h),
                         "a.py and /no-such-root-w/projé/b.py")

    def test_a_path_through_a_symlinked_folder_is_named_from_the_checkout(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            link = Path(tmp) / "link"
            link.symlink_to(repo, target_is_directory=True)
            old = os.getcwd()
            os.chdir(repo)
            try:
                self.assertEqual(cloud.repo_relative(link / ".git" / "cursor-loop" / "x" / "QA.md"),
                                 os.path.join(".git", "cursor-loop", "x", "QA.md"))
            finally:
                os.chdir(old)

    def test_from_a_linked_worktree_paths_name_the_worktree_and_the_main_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            top = Path(run("rev-parse", "--show-toplevel"))
            wt = top / ".worktrees" / "rel"
            run("worktree", "add", "-q", "-b", "rel", str(wt))
            self.assertEqual(_cli(wt, ["log", "--slug", "wo", "ruling",
                                       f"Ruling: change {wt}/app.py, keep {top}/CLAUDE.md", "why", "ev", "ok"])[0], 0)
            self.assertEqual(_cli(wt, ["report", "--slug", "wo"])[0], 0)
            text = next((wt / "docs" / "keryx").glob("*-wo.md")).read_text()
            self.assertIn("Ruling: change app.py, keep CLAUDE.md", text)


class KeryxAfterASubagentRoundInASubmodule(unittest.TestCase):
    """The settings move puts a submodule's core.worktree into the main worktree's config.worktree, so keryx must look
    for it there too. 1.2.1's first cut read only the shared config: from the submodule's linked worktree a log row
    went into a second log inside .git/modules, `mark` found no loop, and a create left .keryx without its
    .gitignore (found by the fresh review)."""

    def test_commands_from_the_submodules_linked_worktree_find_its_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve()
            g = WorktreesOfABareRepositoryOrASubmodule._g(t)
            g("init", "-q", "-b", "main", "sub")
            g("commit", "-q", "--allow-empty", "-m", "b", cwd=t / "sub")
            g("init", "-q", "-b", "main", "sup")
            g("submodule", "-q", "add", str(t / "sub"), "mod", cwd=t / "sup")
            mod, linked = t / "sup" / "mod", t / "mod-wt"
            g("worktree", "add", "-q", "-b", "side", str(linked), cwd=mod)
            (t / "brief.md").write_text("Mode: IMPLEMENT\n")
            create = ["--runner", "subagent", "--prompt-file", str(t / "brief.md"), "--ref", "main"]
            self.assertEqual(_cli(mod, ["create", "--slug", "ms", *create])[0], 0)
            self.assertEqual(_cli(linked, ["log", "--slug", "ms", "check", "from the linked worktree", "w", "e",
                                           "ok"])[0], 0)
            self.assertIn("from the linked worktree", (mod / ".keryx" / "runs" / "ms" / "decisions.tsv").read_text())
            self.assertFalse((t / "sup" / ".git" / "modules" / "mod" / ".keryx").exists())
            self.assertEqual(_cli(linked, ["mark", "--slug", "ms", "--status", "FINISHED"])[0], 0)
            code, out = _cli(linked, ["create", "--slug", "fw", *create])
            self.assertEqual(code, 0, out)
            self.assertEqual((mod / ".keryx" / ".gitignore").read_text(), "*\n")
            self.assertNotIn(".keryx", g("status", "--porcelain", cwd=mod).stdout)


class GlmConfigNeedsNoRepository(unittest.TestCase):
    """Where a GLM run's config goes follows from the run's folder alone, so it needs no repository around the current
    directory (seen on Linux: the suite runs from an export without .git, and 1.2.1's first cut asked git)."""

    def test_the_config_dir_follows_the_run_folder(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            old = os.getcwd()
            os.chdir(tmp)
            try:
                plain = cloud.write_glm_config(t / "loops" / "s")
                beside = cloud.write_glm_config(t / "x" / ".keryx" / "runs" / "s")
            finally:
                os.chdir(old)
            self.assertEqual(plain, t / "loops" / "s" / "claude-config")
            self.assertEqual(beside, t / "x" / ".keryx" / "glm" / "s")
            self.assertEqual((t / "x" / ".keryx" / ".gitignore").read_text(), "*\n")


class RunReportDraftDetails(unittest.TestCase):
    """Found by the fresh review and by re-drafting 1.2.0's report from its own log: indentation inside the acceptance
    check, a Run line with nothing after its colon, an unrelated later <slug>-<name> run counted as a slice, a
    two-finder review showing one finder's counts, and two rulings replacing the same row."""

    def test_indentation_inside_the_acceptance_check_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "in"
            self.assertEqual(_cli(repo, ["log", "--slug", "in", "intake", "size M", "why", "ev", "M"])[0], 0)
            (state / "PLAN.md").write_text("# in\n\n## Acceptance check\nAt base:\n  - nested\n    - deeper\n")
            text = RunReportFromTheWholeRun._draft(repo, run, "in")
            self.assertIn("- Acceptance check:\n  At base:\n    - nested\n      - deeper\n", text)

    def test_a_run_line_without_rounds_ends_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "big"
            self.assertEqual(_cli(repo, ["log", "--slug", "big", "intake", "size L", "why", "ev", "L"])[0], 0)
            (state / "PLAN.md").write_text("# big\n\n## Slices\n- big-a: done inline\n")
            self.assertEqual(_cli(repo, ["log", "--slug", "big-a", "dispatch", "inline", "w", "e", "ok"])[0], 0)
            text = RunReportFromTheWholeRun._draft(repo, run, "big")
            self.assertRegex(text, r"wall clock, 0 executor rounds \(0 FIX\)\n")

    def test_a_slice_counts_when_the_runs_log_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            runs = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs"
            self.assertEqual(_cli(repo, ["log", "--slug", "nm", "plan", "slice nm-a to GLM", "why", "ev", "ok"])[0], 0)
            for name in ("nm-a", "nm-other"):
                self.assertEqual(_cli(repo, ["log", "--slug", name, "dispatch", "x", "w", "e", "ok"])[0], 0)
                (runs / name / "rounds" / "01").mkdir(parents=True)
                (runs / name / "rounds" / "01" / "prompt.md").write_text("Mode: IMPLEMENT\n")
            text = RunReportFromTheWholeRun._draft(repo, run, "nm")
            self.assertIn("1 executor rounds (0 FIX): nm-a 1 <!-- nm-other (1 rounds, 0 FIX) started after this run",
                          text)

    def test_the_second_finders_counts_are_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "two"
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "two", "--base", base, "--head", head,
                                         "--risk"])[0], 0)
            stem = f"{base[:12]}..{head[:12]}"
            (state / "review" / f"{stem}.findings.md").write_text(FinishGate.GOOD.format(head=head))
            (state / "review" / f"{stem}.security.findings.md").write_text(
                f"Head: {head}\nReach: one caller\nSpec: matches\nFindings:\n"
                "- app.py:2 — f() leaks a path — any call — P2 — 0.6\nTests: none\n")
            self.assertEqual(_cli(repo, ["log", "--slug", "two", "finish", "x", "w", "e", "ok"])[0], 0)
            text = RunReportFromTheWholeRun._draft(repo, run, "two")
            self.assertIn(f"- Fresh review: `.keryx/runs/two/review/{stem}.findings.md`: P0 0 · P1 1 · P2 0 · P3 1\n",
                          text)
            self.assertIn(f"- Second finder: `.keryx/runs/two/review/{stem}.security.findings.md`: "
                          "P0 0 · P1 0 · P2 1 · P3 0\n", text)

    def test_a_replaced_ruling_cannot_be_replaced_a_second_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            for decision in ("Ruling: A", "Ruling (replaces row 1): B"):
                self.assertEqual(_cli(repo, ["log", "--slug", "tw", "ruling", decision, "w", "e", "r"])[0], 0)
            self.assertEqual(_cli(repo, ["log", "--slug", "tw", "ruling", "Ruling (replaces row 1): C", "w", "e",
                                         "r"])[0], 1, "row 1 already stands replaced: replace row 2")
            self.assertEqual(_cli(repo, ["log", "--slug", "tw", "ruling", "Ruling (replaces row 2): C", "w", "e",
                                         "r"])[0], 0)


class ReportPathShapes(unittest.TestCase):
    """Local paths in the shapes reports quote them: after a colon (a compiler's location, the second entry of a PATH),
    after a flag, in a file:// URL. System folders that say nothing about the person (/dev, /usr, /bin, /etc …)
    stay, so `2>/dev/null` needs no rewrite (found by the fresh review)."""

    def test_paths_in_quoted_shapes(self):
        w, h = Path("/no-such-root-w/proj"), Path("/no-such-root-h")
        hidden = cloud.LOCAL_PATH
        for text, want in (("err:/tmp/a.py:3", f"err:{hidden}:3"),
                           ("file:///tmp/x.html", f"file://{hidden}"),
                           ("PATH=/no-such-root-a:/tmp/x/y", f"PATH=/no-such-root-a:{hidden}"),
                           ("-I/tmp/inc", f"-I{hidden}"),
                           ("cmd 2>/dev/null", "cmd 2>/dev/null"),
                           ("/usr/bin/env python3", "/usr/bin/env python3"),
                           ("https://example.com/tmp/x", "https://example.com/tmp/x")):
            self.assertEqual(cloud.strip_local_paths(text, w, h), want, text)


class RunLineOfARunWithoutSlices(unittest.TestCase):
    """A run with no slices keeps 1.2.0's Run line: the per-folder counts are for runs whose slices are counted too
    (the fix round's first cut named the run's own folder after every count)."""

    def test_no_folder_names_follow_the_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "solo"
            self.assertEqual(_cli(repo, ["log", "--slug", "solo", "intake", "size M", "why", "ev", "M"])[0], 0)
            for i, mode in enumerate(("IMPLEMENT", "FIX"), 1):
                (state / "rounds" / f"{i:02d}").mkdir(parents=True)
                (state / "rounds" / f"{i:02d}" / "prompt.md").write_text(f"Mode: {mode}\n")
            text = RunReportFromTheWholeRun._draft(repo, run, "solo")
            self.assertRegex(text, r"wall clock, 2 executor rounds \(1 FIX\)\n")
            RunReportFromTheWholeRun._reviewed(repo, base, head, "solo", state)
            code, out = _cli(repo, ["finish", "--slug", "solo", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)
            self.assertIn("rounds    2 executor rounds, 1 of them FIX\n", out)


class UnnamedLaterRunsAndSystemFolders(unittest.TestCase):
    """Found by the second review. A later <slug>-<name> run with rounds that the run never names was dropped from
    the count without a word (re-drafting 1.2.0's report gave 4 rounds instead of 7, as its plan said "slice A");
    now the draft names it in a placeholder the coordinator settles. And the system folders kept in a report were
    whole trees, /System/Volumes/Data (the user's data volume), /usr/home and /Library among them; now only
    system subtrees stay."""

    def test_an_unnamed_later_run_with_rounds_is_named_for_the_coordinator(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            runs = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs"
            self.assertEqual(_cli(repo, ["log", "--slug", "un", "plan", "slice A to GLM", "why", "ev", "ok"])[0], 0)
            self.assertEqual(_cli(repo, ["log", "--slug", "un-a", "dispatch", "x", "w", "e", "ok"])[0], 0)
            self.assertEqual(_cli(repo, ["log", "--slug", "un-b", "intake", "no rounds", "w", "e", "ok"])[0], 0)
            for i in (1, 2):
                (runs / "un-a" / "rounds" / f"{i:02d}").mkdir(parents=True)
                (runs / "un-a" / "rounds" / f"{i:02d}" / "prompt.md").write_text("Mode: IMPLEMENT\n")
            text = RunReportFromTheWholeRun._draft(repo, run, "un")
            run_line = next(line for line in text.splitlines() if "wall clock" in line)
            self.assertIn("0 executor rounds (0 FIX)", run_line)
            self.assertIn("<!--", run_line)
            # the note carries what the coordinator needs to count it in, since the draft is never re-drafted
            self.assertIn("un-a (2 rounds, 0 FIX)", run_line)
            self.assertNotIn("un-b", text, "a later run without rounds changes no count")
            RunReportFromTheWholeRun._reviewed(repo, base, head, "un", runs / "un")
            code, out = _cli(repo, ["finish", "--slug", "un", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)
            self.assertIn("unnamed   un-a: 2 executor rounds", out)

    def test_only_system_subtrees_stay_in_a_report(self):
        w, h = Path("/no-such-root-w/proj"), Path("/no-such-root-h")
        hidden = cloud.LOCAL_PATH
        for kept in ("2>/dev/null", "/usr/bin/env python3", "/bin/sh -c x", "/System/Library/Frameworks"):
            self.assertEqual(cloud.strip_local_paths(kept, w, h), kept)
        for local in ("/usr/home/alice/proj/x.py", "/usr/local/src/client/x", "/etc/nginx/client.conf",
                      "/dev/shm/clientco/cache.db", "/usr/share/nginx/html/clientsite/index.html",
                      "/System/Volumes/Data/Users/other/client-x", "/Library/WebServer/Documents/clientsite"):
            root = "/" + local.split("/")[1]
            if Path(root).is_dir():  # a folder this machine has: its paths are local ones
                self.assertEqual(cloud.strip_local_paths(local, w, h), hidden, local)


class HotfixLane(unittest.TestCase):
    """A hotfix is fixed fast by the session's own model, then the lasting fix runs as a follow-up: a hotfix run is
    finished only when its follow-up run exists, or a ruling says the hotfix is the lasting fix."""

    GOOD = FinishGate.GOOD

    def _hotfix_run(self, tmp, slug="hf"):
        repo, run, base, head = _two_commit_repo(tmp)
        state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / slug
        self.assertEqual(_cli(repo, ["log", "--slug", slug, "intake", "size S · lane hotfix: login returns 500 on production",
                                     "owner: prod is down", "health check red since 09:12", "S"])[0], 0)
        self.assertEqual(_cli(repo, ["review-brief", "--slug", slug, "--base", base, "--head", head, "--hotfix"])[0], 0)
        (state / "review" / f"{base[:12]}..{head[:12]}.findings.md").write_text(self.GOOD.format(head=head))
        self.assertEqual(_cli(repo, ["log", "--slug", slug, "finish", "PR #9 merged and deployed", "health check green",
                                     "deploy 77", "deployed"])[0], 0)
        return repo, run, base, head, state

    def test_a_hotfix_run_is_not_finished_without_its_follow_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head, state = self._hotfix_run(tmp)
            code, out = _cli(repo, ["finish", "--slug", "hf", "--head", head, "--findings-only"])
            self.assertEqual(code, 1, out)
            self.assertIn("missing  the follow-up run", out)
            self.assertFalse((state / "finished.json").exists())

    def test_a_follow_up_row_naming_an_opened_run_finishes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head, state = self._hotfix_run(tmp)
            self.assertEqual(_cli(repo, ["log", "--slug", "hf", "followup", "hf-root: move the session check into the domain",
                                         "the hotfix only catches the null session", "app.py:1", "opened"])[0], 0)
            self.assertEqual(_cli(repo, ["log", "--slug", "hf-root", "intake", "size M: the session check, properly",
                                         "follow-up of hf", "hf decisions.tsv", "M"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "hf", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)
            self.assertIn("followup  hf-root: move the session check into the domain", out)

    def test_a_follow_up_row_naming_a_run_never_opened_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head, state = self._hotfix_run(tmp)
            self.assertEqual(_cli(repo, ["log", "--slug", "hf", "followup", "hf-root: the lasting fix", "why", "ev", "planned"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "hf", "--head", head, "--findings-only"])
            self.assertEqual(code, 1, out)
            self.assertIn("hf-root", out)
            self.assertIn("has no run log", out)

    def test_a_ruling_that_the_hotfix_is_the_lasting_fix_finishes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head, state = self._hotfix_run(tmp)
            self.assertEqual(_cli(repo, ["log", "--slug", "hf", "ruling",
                                         "Ruling: no follow-up — the hotfix reverts the change that broke login; nothing new to fix",
                                         "a revert restores the reviewed code", "PR #9", "ruled"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "hf", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)

    def test_an_ordinary_run_needs_no_follow_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            state = Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "plain"
            self.assertEqual(_cli(repo, ["log", "--slug", "plain", "intake", "size M: the export button", "w", "e", "M"])[0], 0)
            self.assertEqual(_cli(repo, ["review-brief", "--slug", "plain", "--base", base, "--head", head])[0], 0)
            (state / "review" / f"{base[:12]}..{head[:12]}.findings.md").write_text(self.GOOD.format(head=head))
            self.assertEqual(_cli(repo, ["log", "--slug", "plain", "finish", "PR #3", "w", "e", "merged"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "plain", "--head", head, "--findings-only"])
            self.assertEqual(code, 0, out)
            self.assertNotIn("follow-up", out)

    def test_the_hotfix_brief_reviews_the_diff_for_p0_and_p1_on_the_strongest_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head = _two_commit_repo(tmp)
            code, out = _cli(repo, ["review-brief", "--slug", "hb", "--base", base, "--head", head, "--hotfix"])
            self.assertEqual(code, 0, out)
            self.assertIn("dispatch  model=opus", out)
            brief = (Path(run("rev-parse", "--show-toplevel")) / ".keryx" / "runs" / "hb" / "review"
                     / f"{base[:12]}..{head[:12]}.brief.md").read_text()
            self.assertIn("## Hotfix", brief)
            self.assertIn("P0 and P1 only", brief)
            self.assertIn("Findings:", brief)  # the same findings shape, so finish reads it as any review

    def test_the_report_of_a_hotfix_run_names_its_follow_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head, state = self._hotfix_run(tmp)
            code, out = _cli(repo, ["report", "--slug", "hf", "--head", head])
            self.assertEqual(code, 0, out)
            draft = next((Path(run("rev-parse", "--show-toplevel")) / "docs" / "keryx").glob("*-hf.md")).read_text()
            self.assertIn("- Follow-up: <!--", draft)  # none logged yet: a placeholder finish refuses
            self.assertEqual(_cli(repo, ["log", "--slug", "hf", "followup", "hf-root: move the session check into the domain",
                                         "w", "e", "opened"])[0], 0)
            for f in (Path(run("rev-parse", "--show-toplevel")) / "docs" / "keryx").glob("*-hf.md"):
                f.unlink()
            self.assertEqual(_cli(repo, ["report", "--slug", "hf", "--head", head])[0], 0)
            draft = next((Path(run("rev-parse", "--show-toplevel")) / "docs" / "keryx").glob("*-hf.md")).read_text()
            self.assertIn("- Follow-up: `hf-root`: move the session check into the domain", draft)

    def test_the_hotfix_skill_names_its_narrow_triggers_and_the_playbook(self):
        plugin = Path(__file__).resolve().parents[3]
        skill = (plugin / "skills" / "hotfix" / "SKILL.md").read_text()
        self.assertTrue(skill.startswith("---\nname: hotfix\ndescription: "))
        head = skill.split("---", 2)[1]
        for must in ("hotfix", "production", "never"):
            self.assertIn(must, head.lower())
        self.assertIn("../keryx/references/hotfix.md", skill)
        playbook = (plugin / "skills" / "keryx" / "references" / "hotfix.md").read_text()
        for must in ("lane hotfix", "followup", "review-brief --slug <slug> --hotfix", "rollback"):
            self.assertIn(must, playbook)


class HotfixFollowUpIsAnotherRun(unittest.TestCase):
    """The follow-up does the lasting fix in a run of its own: naming the hotfix run itself is no follow-up (QA found
    that it let finish pass)."""

    GOOD = FinishGate.GOOD

    def test_a_follow_up_naming_the_hotfix_run_itself_does_not_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head, state = HotfixLane._hotfix_run(self, tmp)
            self.assertEqual(_cli(repo, ["log", "--slug", "hf", "followup", "hf: the same run", "w", "e", "x"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "hf", "--head", head, "--findings-only"])
            self.assertEqual(code, 1, out)
            self.assertIn("missing  the follow-up run hf is this hotfix run itself", out)

    def test_a_follow_up_row_in_another_shape_is_no_follow_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, run, base, head, state = HotfixLane._hotfix_run(self, tmp)
            for decision in ("the root fix: move the check", "Hf-Root: move the check", "hf-root:", "hf-root move the check"):
                self.assertEqual(_cli(repo, ["log", "--slug", "hf", "followup", decision, "w", "e", "x"])[0], 0)
            code, out = _cli(repo, ["finish", "--slug", "hf", "--head", head, "--findings-only"])
            self.assertEqual(code, 1, out)
            self.assertIn("missing  the follow-up run: keryx.py log --slug hf followup", out)
