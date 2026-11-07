"""Offline tests for a provider executor: a provider declared in config.json, run through `codex exec`."""

import datetime as dt
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402

MISTRAL = {
    "runner": "codex",
    "baseUrl": "https://api.mistral.ai/v1",
    "keyFile": "~/.config/mistral/vibe.key",
    "model": "zai-glm-5-3",
    "effort": "high",
    "codexConfig": {"web_search": "disabled"},
}
AT = dt.datetime(2026, 11, 7, 10, 0, tzinfo=dt.timezone.utc)


def _config(d, data):
    p = Path(d) / "config.json"
    p.write_text(json.dumps(data))
    return {"KERYX_CONFIG": str(p), "HOME": d}


class ProvidersConfig(unittest.TestCase):
    def test_a_declared_provider_is_an_executor(self):
        with tempfile.TemporaryDirectory() as d:
            env = _config(d, {"executors": ["mistral-vibe", "glm", "subagent"], "providers": {"mistral-vibe": MISTRAL}})
            cfg = keryx.load_config(env)
            self.assertEqual(cfg["executors"], ["mistral-vibe", "glm", "subagent"])
            self.assertEqual(cfg["providers"]["mistral-vibe"]["runner"], "codex")
            self.assertEqual(cfg["providers"]["mistral-vibe"]["model"], "zai-glm-5-3")

    def test_no_providers_reads_as_none(self):
        with tempfile.TemporaryDirectory() as d:
            env = _config(d, {"executors": ["glm", "subagent"]})
            self.assertEqual(keryx.load_config(env)["providers"], {})
        self.assertEqual(keryx.load_config({"KERYX_CONFIG": "/no-such-root-keryx/config.json"})["providers"], {})

    def test_an_undeclared_name_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            env = _config(d, {"executors": ["mistral-vibe", "subagent"]})
            with self.assertRaisesRegex(keryx.LoopError, "mistral-vibe"):
                keryx.load_config(env)
        with self.assertRaises(keryx.LoopError):
            keryx.parse_executors("cli,codex", {"mistral-vibe": MISTRAL})
        self.assertEqual(keryx.parse_executors("mistral-vibe,cli", {"mistral-vibe": MISTRAL}), ["mistral-vibe", "cli"])

    def test_bad_providers_are_refused(self):
        bad = [
            {"glm": MISTRAL},
            {"Mistral Vibe": MISTRAL},
            {"mistral-vibe": {**MISTRAL, "runner": "cursor"}},
            {"mistral-vibe": {**MISTRAL, "baseUrl": "http://api.mistral.ai/v1"}},
            {"mistral-vibe": {**MISTRAL, "key": "abc"}},
            {"mistral-vibe": {k: v for k, v in MISTRAL.items() if k != "model"}},
            {"mistral-vibe": {**MISTRAL, "codexConfig": {"web_search": ["x"]}}},
            {"mistral-vibe": {**MISTRAL, "codexConfig": {"sandbox_mode": "read-only"}}},
        ]
        for providers in bad:
            with tempfile.TemporaryDirectory() as d:
                env = _config(d, {"executors": ["subagent"], "providers": providers})
                with self.assertRaises(keryx.LoopError, msg=json.dumps(providers)):
                    keryx.load_config(env)

    def test_a_provider_takes_part_in_the_reset_order(self):
        with tempfile.TemporaryDirectory() as d:
            env = _config(d, {"executors": ["glm", "mistral-vibe", "subagent"], "order": "resets",
                              "providers": {"mistral-vibe": MISTRAL},
                              "resets": {"glm": {"next": "2026-11-11T03:24:16Z", "every": "week"},
                                         "mistral-vibe": {"next": "2026-12-01", "every": "month"}}})
            cfg = keryx.load_config(env)
            at = dt.datetime(2026, 11, 28, tzinfo=dt.timezone.utc)
            self.assertEqual(keryx.ordered_ladder(cfg, at), ["mistral-vibe", "glm", "subagent"])


class CodexCommand(unittest.TestCase):
    def test_first_turn(self):
        self.assertEqual(keryx.codex_command("zai-glm-5-3", "-do it", None, "agent", "high"),
                         ["codex", "exec", "--json", "-m", "zai-glm-5-3", "-c", 'model_reasoning_effort="high"',
                          "-s", "danger-full-access", "--", "-do it"])

    def test_plan_mode_is_read_only(self):
        self.assertEqual(keryx.codex_command("zai-glm-5-3", "look", None, "plan", None),
                         ["codex", "exec", "--json", "-m", "zai-glm-5-3", "-s", "read-only", "--", "look"])

    def test_resume_puts_the_options_before_resume(self):
        self.assertEqual(keryx.codex_command("zai-glm-5-3", "go on", "01a1-thread", "agent", "high"),
                         ["codex", "exec", "--json", "-m", "zai-glm-5-3", "-c", 'model_reasoning_effort="high"',
                          "-c", 'sandbox_mode="danger-full-access"', "resume", "01a1-thread", "--", "go on"])


class CodexHome(unittest.TestCase):
    def test_config_names_the_provider_never_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / ".keryx" / "runs" / "s1"
            run.mkdir(parents=True)
            home = keryx.write_codex_home(run, MISTRAL)
            self.assertEqual(home, Path(d) / ".keryx" / "codex" / "s1")
            cfg = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(cfg["model_provider"], "keryx")
            prov = cfg["model_providers"]["keryx"]
            self.assertEqual(prov["base_url"], "https://api.mistral.ai/v1")
            self.assertEqual(prov["env_key"], "KERYX_CODEX_API_KEY")
            self.assertEqual(prov["wire_api"], "responses")
            self.assertEqual(cfg["model"], "zai-glm-5-3")
            self.assertEqual(cfg["model_reasoning_effort"], "high")
            self.assertEqual(cfg["web_search"], "disabled")
            self.assertEqual(cfg["approval_policy"], "never")
            self.assertIn("KERYX_CODEX_API_KEY", cfg["shell_environment_policy"]["exclude"])
            self.assertEqual(keryx.CODEX_KEY_ENV, "KERYX_CODEX_API_KEY")


class CodexEnv(unittest.TestCase):
    def test_only_the_provider_key_reaches_codex(self):
        with tempfile.TemporaryDirectory() as d:
            key_file = Path(d) / "vibe.key"
            key_file.write_text("test-key-" + "x" * 8 + "\n")
            provider = {**MISTRAL, "keyFile": str(key_file)}
            base = {"PATH": "/usr/bin", "HOME": d, "OPENAI_API_KEY": "o", "CODEX_API_KEY": "c",
                    "ANTHROPIC_AUTH_TOKEN": "a", "GH_TOKEN": "g", "SSH_AUTH_SOCK": "/s", "MY_SECRET": "m",
                    "CODEX_HOME": "/elsewhere"}
            env = keryx.codex_env(base, "/run/codex-home", keryx.codex_key(provider, base))
            for gone in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_AUTH_TOKEN", "SSH_AUTH_SOCK",
                         "MY_SECRET"):
                self.assertNotIn(gone, env)
            self.assertNotEqual(env.get("GH_TOKEN"), "g")
            self.assertEqual(env["CODEX_HOME"], "/run/codex-home")
            self.assertEqual(env["KERYX_CODEX_API_KEY"], "test-key-xxxxxxxx")
            pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
                     for i in range(int(env["GIT_CONFIG_COUNT"]))}
            self.assertEqual(pairs["remote.origin.pushurl"], "https://push-disabled.invalid/keryx")

    def test_a_key_file_under_tilde_uses_home(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".config" / "mistral").mkdir(parents=True)
            (Path(d) / ".config" / "mistral" / "vibe.key").write_text("k1\n")
            self.assertEqual(keryx.codex_key(MISTRAL, {"HOME": d}), "k1")

    def test_a_missing_key_file_names_the_file(self):
        with self.assertRaisesRegex(keryx.LoopError, "no-such-root-keryx"):
            keryx.codex_key({**MISTRAL, "keyFile": "/no-such-root-keryx/vibe.key"}, {"HOME": "/no-such-root-keryx"})

    def test_env_cannot_override_the_codex_guard_rails(self):
        for pair in ("CODEX_HOME=/x", "KERYX_CODEX_API_KEY=y", "OPENAI_BASE_URL=z"):
            with self.assertRaises(keryx.LoopError, msg=pair):
                keryx.parse_env([pair])


class CodexOutcome(unittest.TestCase):
    OK = [
        {"type": "thread.started", "thread_id": "01a1-thread"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": "Working on it."}},
        {"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "Status: DONE\nran the tests"}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
    ]

    def test_a_finished_turn(self):
        out = keryx.codex_outcome(self.OK, 0)
        self.assertEqual(out["status"], "FINISHED")
        self.assertEqual(out["session_id"], "01a1-thread")
        self.assertEqual(out["result"], "Status: DONE\nran the tests")

    def test_a_failed_turn_reports_the_error(self):
        events = self.OK[:2] + [{"type": "turn.failed",
                                 "error": {"message": "unexpected status 402 Payment Required: {}"}}]
        out = keryx.codex_outcome(events, 1)
        self.assertEqual(out["status"], "ERROR")
        self.assertIn("unexpected status 402 Payment Required", out["result"])

    def test_running_and_cancelled(self):
        self.assertEqual(keryx.codex_outcome(self.OK[:2], None)["status"], "RUNNING")
        self.assertEqual(keryx.codex_outcome(self.OK[:2], 137)["status"], "CANCELLED")
        self.assertEqual(keryx.codex_outcome(self.OK, 1)["status"], "ERROR")


class CodexUsageLimit(unittest.TestCase):
    def test_payment_required_lasts_until_the_first_of_next_month(self):
        text = 'unexpected status 402 Payment Required: {"detail":"x"}, url: https://api.mistral.ai/v1/responses'
        self.assertEqual(keryx.usage_limit(text, AT),
                         {"kind": "allowance", "resetsAt": "2026-12-01T00:00:00Z", "resetsIn": None})
        self.assertEqual(keryx.usage_limit(text, dt.datetime(2026, 12, 15, tzinfo=dt.timezone.utc))["resetsAt"],
                         "2027-01-01T00:00:00Z")

    def test_the_raw_status_form_counts_too(self):
        text = '{"object":"error","message":"no credit","type":"payment_required","code":"x","raw_status_code":402}'
        self.assertEqual(keryx.usage_limit(text, AT)["kind"], "allowance")

    def test_too_many_requests_is_a_short_limit(self):
        self.assertEqual(keryx.usage_limit("unexpected status 429 Too Many Requests: {}", AT),
                         {"kind": "rate", "resetsAt": None, "resetsIn": "10 minutes"})

    def test_a_bad_key_or_request_is_not_a_limit(self):
        self.assertIsNone(keryx.usage_limit('unexpected status 401 Unauthorized: {"detail":"Invalid API Key"}', AT))
        self.assertIsNone(keryx.usage_limit('{"object":"error","message":"bad effort","raw_status_code":400}', AT))


class CodexToolCalls(unittest.TestCase):
    def test_command_items_open_and_close_a_call(self):
        start = {"type": "item.started", "item": {"id": "item_3", "type": "command_execution",
                                                  "command": "/bin/zsh -lc ls", "status": "in_progress"}}
        end = {"type": "item.completed", "item": {"id": "item_3", "type": "command_execution",
                                                  "command": "/bin/zsh -lc ls", "exit_code": 0}}
        self.assertEqual(keryx.tool_calls(start), [("start", "item_3", "/bin/zsh -lc ls")])
        self.assertEqual(keryx.tool_calls(end), [("end", "item_3", "")])
        self.assertEqual(keryx.tool_calls({"type": "item.completed",
                                           "item": {"id": "i", "type": "agent_message", "text": "x"}}), [])


if __name__ == "__main__":
    unittest.main()
