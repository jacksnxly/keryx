"""Runs one system under test on one case through the Claude Agent SDK, isolated from the owner's setup."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, SystemMessage
from claude_agent_sdk.types import (
    TERMINAL_TASK_STATUSES,
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    RateLimitEvent,
    StreamEvent,
    TaskNotificationMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
)

from keryx_bench.case import Case
from keryx_bench.leaks import (deny_paths, find_executor_leaks, find_leaks, find_subagent_leaks, path_deny_rules,
                               scan_paths)
from keryx_bench.owner import StandIn, model_says_yes
from keryx_bench.safety import DENY_RULES, removed_keys, safe_env
from keryx_bench.sessions import keep_subagent_transcripts, remove_session_dir, session_dir_for
from keryx_bench.systems import System
from keryx_bench.usage import collect_executor_usage
from keryx_bench.workspace import Workspace

__all__ = ["RESULT_RULE", "RunRecord", "UsageWindow", "build_options", "build_prompt", "check_isolation", "classify_result",
           "decide_after_stop", "limit_pause", "run_case", "session_dir_for", "track_tasks"]

RESULT_RULE = (
    "Autonomy for this run: {autonomy}\n"
    "Leave your final result committed on the branch {branch} that is checked out in this directory. "
    "If you create other work branches or worktrees, merge them into {branch} before you finish."
)
IS_QUESTION = ("Does this message ask the owner a question, or ask for approval or a decision, "
               "before the work can continue?")
CLAIMS_DONE = "Does this report claim the task is complete?"
# Empty on purpose: every call then reaches can_use_tool (which answers questions and allows the rest),
# while the deny rules still refuse first.
ALLOWED_TOOLS: list[str] = []


@dataclass
class RunRecord:
    case_id: str
    system: str
    run_id: str
    status: str
    wall_s: float = 0.0
    cost_usd: float = 0.0
    usage: dict = field(default_factory=dict)
    num_turns: int = 0
    interruptions: int = 0
    resumes: int = 0
    waits: int = 0
    final_text: str = ""
    cwd: str = ""
    loaded_skills: tuple[str, ...] = ()
    loaded_plugins: tuple[str, ...] = ()
    mcp_servers: list = field(default_factory=list)
    executor_usage: dict = field(default_factory=dict)
    model_usage: dict = field(default_factory=dict)
    unanswered: list = field(default_factory=list)
    leaks: list = field(default_factory=list)
    stray_processes: int = 0
    error: str | None = None
    limit_pauses: int = 0  # times the run waited for a usage window to reset, then went on
    paused_s: float = 0.0  # time spent in those waits; not part of wall_s
    weekly_use: float | None = None  # the seven-day window's highest utilization seen during the run
    tmp_removed: list = field(default_factory=list)  # the run's own /tmp scratch, removed after it


def build_prompt(case: Case, system: System, ws: Workspace) -> str:
    task = system.entry[case.mode].replace("{prompt}", case.prompt.strip())
    rule = RESULT_RULE.replace("{autonomy}", case.owner.autonomy).replace("{branch}", ws.branch)
    return f"{task}\n\n{rule}"


EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def edit_allowed(tool_name: str, input_data: dict, root: Path) -> bool:
    """File edits stay inside the run's own directory or the system temp dirs; reads are not limited here."""
    if tool_name not in EDIT_TOOLS:
        return True
    target = input_data.get("file_path") or input_data.get("notebook_path") or ""
    if not target:
        return True
    real = os.path.realpath(target)
    allowed = [os.path.realpath(root), os.path.realpath(tempfile.gettempdir()), "/private/tmp", "/tmp"]
    return any(real == a or real.startswith(a + os.sep) for a in allowed)


async def _keep_open(input_data, tool_use_id, context):
    return {"continue_": True}


def build_options(case: Case, *, model: str, plugin_dirs: Sequence[Path], ws: Workspace, can_use_tool,
                  extra_env: Mapping[str, str], extra_deny: Sequence[str] = (),
                  setting_sources: Sequence[str] = ()) -> ClaudeAgentOptions:
    env = safe_env(os.environ, {**case.env, **extra_env})
    # The SDK merges env over the inherited environment, so removal needs an explicit empty value.
    env.update({key: "" for key in removed_keys(os.environ)})
    return ClaudeAgentOptions(
        cwd=str(ws.repo),
        model=model,
        # Without this the SDK sends an empty system prompt, unlike a real session.
        system_prompt={"type": "preset", "preset": "claude_code"},
        setting_sources=list(setting_sources),
        plugins=[{"type": "local", "path": str(p)} for p in plugin_dirs],
        strict_mcp_config=True,
        mcp_servers={},
        permission_mode="default",
        allowed_tools=list(ALLOWED_TOOLS),
        disallowed_tools=[*DENY_RULES, *extra_deny],
        env=env,
        max_budget_usd=case.budget.max_usd,
        can_use_tool=can_use_tool,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_keep_open])]},
    )


def check_isolation(init_data: Mapping) -> str | None:
    if init_data.get("mcp_servers"):
        names = ", ".join(str(s.get("name")) for s in init_data["mcp_servers"])
        return f"isolation breach: mcp servers loaded ({names})"
    if init_data.get("memory_paths"):
        return f"isolation breach: memory loaded ({init_data['memory_paths']})"
    return None


LIMIT_MAX_PAUSE_S = 5 * 3600 + 600  # a five-hour window, plus slack; a later reset is not waited for
LIMIT_SLACK_S = 60
CONTINUE = "Continue where you left off."


def limit_pause(info, now: float, max_s: float = LIMIT_MAX_PAUSE_S) -> float | None:
    """Seconds to wait when a usage window rejected the run and resets within reach; None otherwise.

    The SDK's RateLimitEvent says to back off when its status is "rejected"; resets_at is a Unix time.
    """
    if info is None or info.status != "rejected" or not info.resets_at:
        return None
    wait = max(0.0, info.resets_at - now) + LIMIT_SLACK_S
    return wait if wait <= max_s else None


@dataclass
class UsageWindow:
    """The subscription's seven-day window as a run's cases see it, shared by all of them.

    The bench shares the owner's subscription, so it stops starting work at `weekly_cap` to leave them room.
    """
    weekly_cap: float = 0.5
    weekly: float | None = None

    def note(self, info) -> None:
        week = ((info.raw or {}).get("unifiedWindows") or {}).get("seven_day") or {}
        if week.get("utilization") is not None:
            self.weekly = float(week["utilization"])

    @property
    def over_cap(self) -> bool:
        return self.weekly is not None and self.weekly >= self.weekly_cap


INFRA_STATUS = {429, 500, 502, 503, 504, 529}
INFRA_WORDS = ("rate limit", "usage limit", "overloaded", "quota")


def classify_result(subtype: str, is_error: bool, api_error_status: int | None, errors: Sequence[str] | None) -> str:
    """ok, budget, infra (rate or usage limits, provider outages: re-run, do not score) or error."""
    if subtype == "error_max_budget_usd":
        return "budget"
    if api_error_status in INFRA_STATUS or any(w in " ".join(errors or []).lower() for w in INFRA_WORDS):
        return "infra"
    return "ok" if subtype == "success" and not is_error else "error"


def track_tasks(active: set[str], message) -> None:
    """Keeps the ids of background tasks that are still running; a finished one injects a new turn."""
    if isinstance(message, TaskStartedMessage):
        active.add(message.task_id)
    elif isinstance(message, TaskNotificationMessage) and message.status in TERMINAL_TASK_STATUSES:
        active.discard(message.task_id)
    elif isinstance(message, TaskUpdatedMessage):
        status = message.status or (message.patch or {}).get("status")
        if status in TERMINAL_TASK_STATUSES:
            active.discard(message.task_id)


def decide_after_stop(reply: str | None, resumes: int, max_resumes: int) -> str:
    if reply is None:
        return "finish"
    return "resume" if resumes < max_resumes else "stalled"


WAIT_IDLE_S = 60 * 60  # a run waiting on its own background job is given up after this much silence


def next_step(active_tasks: int, reply: str | None, resumes: int, max_resumes: int,
              claims_done: bool = False) -> str:
    """After a turn ends: answer a question, wait for its own running background work, or finish.

    A run that reports the task done is finished even if something it started (a dev server, a watcher)
    still runs; leftover processes are stopped by the runner.
    """
    if reply is None and active_tasks and not claims_done:
        return "wait"  # the job's completion injects the next turn
    return decide_after_stop(reply, resumes, max_resumes)


def resets_wait(message) -> bool:
    """Whether a message ends the silence a waiting run is timed on; rate-limit notices and stream deltas do not."""
    return not isinstance(message, (RateLimitEvent, StreamEvent))


def _to_json(message) -> str:
    if dataclasses.is_dataclass(message):
        payload = {"type": type(message).__name__, **dataclasses.asdict(message)}
    else:
        payload = {"type": type(message).__name__, "value": repr(message)}
    return json.dumps(payload, default=str)


async def run_case(case: Case, system: System, ws: Workspace, plugin_dirs: Sequence[Path], standin: StandIn,
                   transcript: Path, *, max_resumes: int = 3, scan_extra: Sequence[str] = (),
                   usage: UsageWindow | None = None, max_pauses: int = 3) -> RunRecord:
    record = RunRecord(case_id=case.id, system=system.name, run_id=ws.run_id, status="error", cwd=str(ws.repo))
    transcript.parent.mkdir(parents=True, exist_ok=True)

    async def can_use_tool(tool_name, input_data, context):
        if not edit_allowed(tool_name, input_data, ws.root):
            return PermissionResultDeny(message="Edits outside this run's directory are not allowed in this run.")
        if tool_name == "AskUserQuestion":
            questions = input_data.get("questions", [])
            answers = await standin.answer(questions)
            return PermissionResultAllow(updated_input={"questions": questions, "answers": answers})
        return PermissionResultAllow(updated_input=input_data)

    async def is_question(text: str) -> bool:
        return await model_says_yes(IS_QUESTION, text)

    forbidden = scan_paths(case, extra=scan_extra)
    options = build_options(case, model=system.model, plugin_dirs=plugin_dirs, ws=ws, can_use_tool=can_use_tool,
                            extra_env=system.env, extra_deny=path_deny_rules(deny_paths(case)),
                            setting_sources=system.setting_sources)

    usage = usage if usage is not None else UsageWindow()

    async def session(log, deadline) -> None:
        active: set[str] = set()
        limit = None  # the latest usage-window notice
        async with ClaudeSDKClient(options=options) as client:
            await client.query(build_prompt(case, system, ws))
            messages = client.receive_messages().__aiter__()
            wait_until = None  # monotonic deadline while waiting on the run's own background work
            while True:
                timeout = max(0.0, wait_until - time.monotonic()) if wait_until is not None else None
                try:
                    message = await asyncio.wait_for(messages.__anext__(), timeout=timeout)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    record.status = "stalled"
                    record.error = f"gave up waiting for background work after {WAIT_IDLE_S // 60} min of silence"
                    return
                if wait_until is not None and resets_wait(message):
                    wait_until = None
                log.write(_to_json(message) + "\n")
                log.flush()
                track_tasks(active, message)
                if isinstance(message, RateLimitEvent):
                    limit = message.rate_limit_info
                    usage.note(limit)
                    if usage.weekly is not None:
                        record.weekly_use = max(record.weekly_use or 0.0, usage.weekly)
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    data = message.data
                    record.cwd = str(data.get("cwd") or record.cwd)
                    record.loaded_skills = tuple(data.get("skills") or ())
                    record.loaded_plugins = tuple(p.get("name", "") for p in data.get("plugins") or ())
                    record.mcp_servers = list(data.get("mcp_servers") or [])
                    breach = check_isolation(data)
                    if breach:  # the environment leaked into the run: the harness's failure, not the system's
                        record.status, record.error = "harness", breach
                        await client.interrupt()
                        return
                if not isinstance(message, ResultMessage):
                    continue
                record.cost_usd = float(message.total_cost_usd or 0.0)
                record.usage = dict(message.usage or {})
                record.num_turns += int(message.num_turns or 0)
                record.model_usage = {k: dict(v) for k, v in (message.model_usage or {}).items()}
                record.final_text = message.result or record.final_text
                outcome = classify_result(message.subtype, message.is_error, message.api_error_status, message.errors)
                pause = limit_pause(limit, time.time()) if outcome == "infra" else None
                if pause is not None and record.limit_pauses < max_pauses and not usage.over_cap:
                    # The owner would wait for the window to reset and say "continue"; so does the run.
                    # The wait is not the system's time: it is left out of wall_s and of the case's timeout.
                    record.limit_pauses += 1
                    record.paused_s += pause
                    deadline.reschedule(deadline.when() + pause)
                    await asyncio.sleep(pause)
                    limit = None
                    await client.query(CONTINUE)
                    continue
                if outcome != "ok":
                    record.status = outcome
                    record.error = f"result {message.subtype} ({message.api_error_status}): {message.errors}"
                    return
                reply = await standin.on_stop(record.final_text, is_question)
                claims_done = bool(active and reply is None and await model_says_yes(CLAIMS_DONE, record.final_text))
                step = next_step(len(active), reply, record.resumes, max_resumes, claims_done=claims_done)
                if step == "wait":
                    record.waits += 1
                    wait_until = time.monotonic() + WAIT_IDLE_S
                    continue
                if step == "finish":
                    record.status = "finished"
                    return
                if step == "stalled":
                    record.status = "stalled"
                    return
                record.resumes += 1
                await client.query(reply)
            record.status, record.error = "error", "session ended without a final result"

    start = time.monotonic()
    try:
        with transcript.open("w") as log:
            async with asyncio.timeout(case.budget.timeout_min * 60) as deadline:
                await session(log, deadline)
    except asyncio.TimeoutError:
        record.status, record.error = "timeout", f"no result within {case.budget.timeout_min} min"
    except Exception as err:  # the record must survive any SDK or process failure; the error is kept
        infra = any(w in str(err).lower() for w in INFRA_WORDS)
        record.status, record.error = ("infra" if infra else "error"), f"{type(err).__name__}: {err}"
    finally:
        record.wall_s = round(time.monotonic() - start - record.paused_s, 3)
        record.interruptions = standin.interruptions
        record.unanswered = list(standin.unanswered)
        subagents = keep_subagent_transcripts(record.cwd, transcript.parent / "subagents")
        runs_root = str(Path(ws.root).resolve().parents[1])  # <runs>/<run id>/<case id>
        scan = {"allow": ws.run_id, "runs_root": runs_root}
        record.leaks = sorted(set(find_leaks(transcript, forbidden, base_dir=str(ws.repo), **scan))
                              | set(find_subagent_leaks(subagents, forbidden, base_dir=str(ws.repo), **scan))
                              | set(find_executor_leaks(ws.repo, forbidden, **scan)))
        record.executor_usage = collect_executor_usage(ws.repo)
        remove_session_dir(record.cwd, must_contain=ws.run_id)
    return record
