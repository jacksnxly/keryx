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
                # Seen: a coordinator spent five calls finding where its rows went.
                self.assertEqual(printed.getvalue().strip(), str(root / "s" / "decisions.tsv"))
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


class ThirdPartyExecutorAndTheFolder(unittest.TestCase):
    """A GLM executor gets the plan in its brief; it never reads keryx's folder, which can hold QA screenshots of
    real people and other runs' logs."""

    def test_glm_is_denied_the_keryx_folder(self):
        for rule in ("Read(**/.keryx/**)", "Read(//**/.keryx/**)"):
            self.assertIn(rule, cloud.GLM_DENY)
