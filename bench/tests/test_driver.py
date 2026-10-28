from pathlib import Path

from keryx_bench.case import load_case
from keryx_bench.driver import build_options, check_isolation, decide_after_stop, session_dir_for
from keryx_bench.safety import DENY_RULES, safe_env
from keryx_bench.workspace import prepare_workspace


def test_safe_env_blocks_cluster_ssh_agent_tokens_and_memory():
    env = safe_env({"PATH": "/usr/bin", "SSH_AUTH_SOCK": "/tmp/agent", "GH_TOKEN": "x", "KUBECONFIG": "/real"},
                   {"CARGO_BUILD_JOBS": "6"})
    assert env["KUBECONFIG"] == "/dev/null"
    assert "SSH_AUTH_SOCK" not in env
    assert "GH_TOKEN" not in env
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["CARGO_BUILD_JOBS"] == "6"
    assert env["PATH"] == "/usr/bin"


def test_deny_rules_cover_pushes_and_infrastructure():
    for rule in ("Bash(git push*)", "Bash(kubectl *)", "Bash(ssh *)", "Bash(gh *)", "Bash(helm *)"):
        assert rule in DENY_RULES


def test_options_isolate_the_run(toy_case, tmp_path):
    case = load_case(toy_case)
    ws = prepare_workspace(case, tmp_path / "runs", "r1")

    async def allow(tool_name, input_data, context):
        return None

    opts = build_options(case, model="haiku", plugin_dirs=[tmp_path / "p"], ws=ws, can_use_tool=allow, extra_env={})
    assert opts.setting_sources == []
    assert opts.strict_mcp_config is True
    assert opts.mcp_servers == {}
    assert opts.plugins == [{"type": "local", "path": str(tmp_path / "p")}]
    assert str(opts.cwd) == str(ws.repo)
    assert set(DENY_RULES) <= set(opts.disallowed_tools)
    assert "AskUserQuestion" not in opts.allowed_tools
    assert opts.max_budget_usd == case.budget.max_usd
    assert opts.env["KUBECONFIG"] == "/dev/null"


def test_isolation_breach_is_reported():
    assert check_isolation({"mcp_servers": [], "memory_paths": None}) is None
    assert "mcp" in check_isolation({"mcp_servers": [{"name": "x"}], "memory_paths": None})
    assert "memory" in check_isolation({"mcp_servers": [], "memory_paths": {"auto": "/x"}})


def test_resumes_are_capped_and_then_stall():
    assert decide_after_stop(None, 0, 3) == "finish"
    assert decide_after_stop("answer", 2, 3) == "resume"
    assert decide_after_stop("answer", 3, 3) == "stalled"


def test_session_dir_matches_claude_code_naming():
    got = session_dir_for("/private/var/folders/fc/vtrqdj8x65s7bj5_ln3_7hth0000gn/T/tmpbq2wys6s")
    assert got == Path.home() / ".claude" / "projects" / "-private-var-folders-fc-vtrqdj8x65s7bj5-ln3-7hth0000gn-T-tmpbq2wys6s"


def test_background_tasks_are_tracked_until_they_end():
    from claude_agent_sdk.types import TaskNotificationMessage, TaskStartedMessage, TaskUpdatedMessage

    from keryx_bench.driver import track_tasks

    active: set[str] = set()
    track_tasks(active, TaskStartedMessage(subtype="task_started", data={}, task_id="wait", description="",
                                           uuid="u1", session_id="s"))
    track_tasks(active, TaskStartedMessage(subtype="task_started", data={}, task_id="shell", description="",
                                           uuid="u2", session_id="s"))
    assert active == {"wait", "shell"}
    track_tasks(active, TaskNotificationMessage(subtype="task_notification", data={}, task_id="wait",
                                                status="completed", output_file="", summary="", uuid="u3",
                                                session_id="s"))
    track_tasks(active, TaskUpdatedMessage(subtype="task_updated", data={}, task_id="shell",
                                           patch={"status": "killed"}))
    assert active == set()
