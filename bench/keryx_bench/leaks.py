"""Paths a system under test must not read, because they hold the answer or the owner's own history.

Coverage: the coordinator's tool calls (from the transcript), its subagents' (from their own transcripts) and the
Cursor executor's (from its cursor-loop event logs). Other executors, and anything a program the agent starts
reads by itself, are not seen.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from keryx_bench.case import Case

DATA_HOME = Path.home() / ".local" / "share" / "keryx"
_SPLIT = re.compile(r"[\s'\"`;|&()<>=,:\[\]{}]+")
_RUN_ID = re.compile(r"\d{8}T\d{6}Z")


def _real(paths: Iterable[str]) -> list[str]:
    return sorted({os.path.realpath(p) for p in paths if p and "://" not in p and Path(p).exists()}
                  | {p for p in paths if p and "://" in p})


def deny_paths(case: Case) -> list[str]:
    """Never needed by a run: the source repo, the case and the private config. Reading them is denied."""
    return _real([case.repo, str(case.path), str(Path.home() / ".config" / "keryx")])


def scan_paths(case: Case, extra: Sequence[str] = ()) -> list[str]:
    """Everything a run must not touch except its own files: detected after the run, not denied, because the
    run legitimately reads its own session's saved tool output and its executor's output in these places."""
    home = Path.home()
    return _real([*deny_paths(case), str(home / ".claude" / "projects"), str(home / ".cursor" / "projects"),
                  str(DATA_HOME), *extra])


def forbidden_paths(case: Case) -> list[str]:
    return scan_paths(case)


def path_deny_rules(paths: Sequence[str]) -> list[str]:
    rules = []
    for p in paths:
        if p.startswith("/"):
            rules += [f"Read(/{p}/**)", f"Edit(/{p}/**)"]
    return rules


def _tokens(text: str, cwd: str | None) -> tuple[list[str], str | None]:
    """Path-like tokens of a command, with ~ and $HOME expanded and ../ resolved against the folder the
    command has `cd`'d into so far (starting from `cwd`), and the folder it ends in (None when unknown)."""
    home = str(Path.home())
    text = text.replace("\\n", " ").replace("${HOME}", home).replace("$HOME", home)
    tokens = []
    after_cd = False
    for token in _SPLIT.split(text):
        if token.startswith("~/") or token == "~":
            token = home + token[1:]
        if cwd and (token == ".." or token.startswith("../") or token.startswith("./")):
            token = os.path.normpath(os.path.join(cwd, token))
        if after_cd and token:
            if "$" in token:  # a folder named by a variable: where the command is now cannot be told
                cwd = None
            elif token.startswith("/"):
                cwd = token
            elif cwd:
                cwd = os.path.normpath(os.path.join(cwd, token))
        after_cd = token == "cd"
        tokens.append(token)
    return tokens, cwd


def _into_another_run(token: str, runs_root: str) -> bool:
    """Under the runs folder only another run's folder, or a glob over them, holds another run's work; the
    folder itself does not (seen: a reviewer walking up the parents looking for CLAUDE.md files)."""
    rest = token[token.find(runs_root) + len(runs_root):]
    if not rest.startswith("/"):
        return False
    first = rest[1:].split("/", 1)[0]
    return bool(_RUN_ID.match(first)) or any(c in first for c in "*?")


def _leaks_in(text: str, forbidden: Sequence[str], allow: str | None,
              cwd: str | None, runs_root: str | None = None) -> tuple[set[str], str | None]:
    found = set()
    tokens, cwd = _tokens(text, cwd)
    for token in tokens:
        for p in forbidden:
            if p in token and not (allow and allow in token):
                if p == runs_root and not _into_another_run(token, p):
                    continue
                found.add(p)
    return found, cwd


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def _scan_actions(actions: Iterable[tuple[str | None, object]], forbidden: Sequence[str], allow: str | None,
                  base_dir: str | None, runs_root: str | None = None) -> set[str]:
    """The forbidden paths in a sequence of (tool name, tool input), with the shell's folder followed across
    Bash calls: the shell keeps its folder between calls and goes back to the project folder (`base_dir`)
    when a call leaves it."""
    found: set[str] = set()
    shell_cwd = base_dir
    for name, tool_input in actions:
        action = json.dumps(tool_input)
        if name == "Bash":
            hits, after = _leaks_in(action, forbidden, allow, shell_cwd, runs_root)
            shell_cwd = after if after is None or base_dir is None or _within(after, base_dir) else base_dir
        else:
            hits, _ = _leaks_in(action, forbidden, allow, base_dir, runs_root)
        found |= hits
    return found


def _lines(path: Path) -> Iterable[dict]:
    for line in Path(path).read_text(errors="replace").splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _sdk_actions(path: Path) -> Iterable[tuple[str | None, object]]:
    for message in _lines(path):
        if message.get("type") == "AssistantMessage":
            for block in message.get("content") or []:
                if isinstance(block, dict):
                    yield block.get("name"), block.get("input")


def _native_actions(path: Path) -> Iterable[tuple[str | None, object]]:
    for message in _lines(path):
        if message.get("type") == "assistant":
            for block in (message.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield block.get("name"), block.get("input")


def find_leaks(transcript: Path, forbidden: Sequence[str], allow: str | None = None,
               base_dir: str | None = None, runs_root: str | None = None) -> list[str]:
    """The forbidden paths in what the coordinator asked its tools to do.

    A path token that also contains `allow` (the run id) is the run's own file, such as its executor's
    output under ~/.cursor/projects, and is not a leak. Relative paths are resolved against the folder the
    shell is in: `base_dir` at the start, then wherever a Bash call `cd`'d to.
    """
    if not Path(transcript).exists():
        return []
    return sorted(_scan_actions(_sdk_actions(transcript), forbidden, allow, base_dir, runs_root))


def find_subagent_leaks(transcripts: Iterable[Path], forbidden: Sequence[str], allow: str | None = None,
                        base_dir: str | None = None, runs_root: str | None = None) -> list[str]:
    """The same for the run's subagents, from their own transcripts (Claude Code's format): a background
    subagent's tool calls never reach the coordinator's stream."""
    found: set[str] = set()
    for path in transcripts:
        found |= _scan_actions(_native_actions(path), forbidden, allow, base_dir, runs_root)
    return sorted(found)


def find_executor_leaks(repo: Path, forbidden: Sequence[str], allow: str | None = None,
                        logs: Path | None = None, runs_root: str | None = None) -> list[str]:
    """The forbidden paths in the Cursor executor's own tool calls, read from its cursor-loop event logs: in the
    repo's .git folder, or in `logs` once they were kept outside the workspace."""
    found: set[str] = set()
    for events in (Path(logs) if logs else Path(repo) / ".git").glob("cursor-loop/*/rounds/*/events.ndjson"):
        for line in events.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "tool_call" and event.get("subtype") == "started":
                found |= _leaks_in(json.dumps(event.get("tool_call")), forbidden, allow, str(repo), runs_root)[0]
    return sorted(found)
