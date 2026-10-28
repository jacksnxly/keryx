"""Field metrics: how the workflow does in the owner's real sessions, read from Claude Code's own transcripts.

No model calls and no new runs: it reads ~/.claude/projects. The unit is one owner turn, from a prompt the owner
typed to the next one. Per turn: busy time, tokens (subagents included), the workflow its skills point to, whether
the owner interrupted it, whether the owner's next prompt pushed back, and "claimed done, then pushback" as a proxy
for a false done. The words are matched locally; only counts and rates leave this module, never message text.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import rework

PROJECTS = Path.home() / ".claude" / "projects"
SNAPSHOTS = Path.home() / ".local" / "share" / "keryx" / "field"
IDLE_GAP_S = 10 * 60  # a longer silence inside a turn is waiting (on a job, on a limit), not work
# A skill is tagged only on the turn that invokes it, but its process runs through the owner's follow-ups: a turn
# without a workflow of its own carries the session's last one while the owner keeps replying within 2 h, for at
# most 30 turns. A guess at where one task ends; the per-turn tags alone credit 89 % of turns to no workflow.
CARRY_GAP_S = 2 * 3600
CARRY_TURNS = 30
_GENERIC = ("none", "triple-check only", "other skills")
SKIP_PROJECTS = ("-Users-Shared-keryx", "-private-")  # bench runs and throwaway scratch sessions

_PUSHBACK = [re.compile(p, re.I) for p in (
    r"\b(doesn'?t|does not|didn'?t|did not|isn'?t|is not|not) work", r"\bstill (broken|wrong|fail\w*|not|the same|"
    r"there|missing|no|shows?|empty)\b", r"\byou said\b", r"\bnope\b", r"\bwrong\b", r"\bbroken\b", r"^\s*no[,.! ]",
    r"\bthat'?s not\b", r"\bnot what i\b", r"\bwhy did you\b", r"\bdoesn'?t (show|load|render|compile|build)",
    r"funktioniert (immer noch |noch )?nicht", r"geht (immer noch |noch )?nicht", r"\bimmer noch\b", r"\bfalsch\b",
    r"\bkaputt\b", r"^\s*nein\b", r"klappt (immer noch |noch )?nicht")]
_DONE = re.compile(r"\b(done|fixed|complete[d]?|all (tests|checks) pass\w*|merged|deployed|shipped|works now|"
                   r"is live|erledigt|fertig)\b", re.I)
_COMMIT_LINE = re.compile(r"^\[[^\]\s]+(?: \(root-commit\))? ([0-9a-f]{7,40})\] ", re.M)
_PROCESS_SKILLS = ("subagent-driven-development", "executing-plans", "writing-plans", "brainstorming",
                   "systematic-debugging", "test-driven-development")  # plugin skills that set a way of working


def is_pushback(text: str) -> bool:
    return any(p.search(text) for p in _PUSHBACK)


def workflow_of(skills: set[str]) -> str:
    """The most specific workflow a turn's skills point to. A plugin skill keeps its `<plugin>:<name>` label."""
    bare = {s.split(":", 1)[-1] for s in skills}
    if any("cursor-loop" in s for s in bare):
        return "cursor-loop"
    if any(s.startswith("keryx") for s in bare):
        return "keryx"
    for name in _PROCESS_SKILLS:
        for s in sorted(skills):
            if s.split(":", 1)[-1] == name:
                return s if ":" in s else name
    plugins = sorted(s.split(":", 1)[0] for s in skills if ":" in s)
    if plugins:
        return f"{plugins[0]}:other"
    if bare - {"triple-check"}:
        return "other skills"
    return "triple-check only" if bare else "none"


@dataclass
class Turn:
    session: str
    project: str
    start: str
    end: str = ""
    cwd: str = ""
    busy_s: float = 0.0
    output_tokens: int = 0
    fresh_tokens: int = 0  # input + cache writes: what a turn adds
    cached_tokens: int = 0
    subagents: int = 0
    interrupted: bool = False
    claimed_done: bool = False
    pushback_next: bool = False
    skills: set[str] = field(default_factory=set)
    carried: str | None = None  # the workflow this turn continues, when it has none of its own
    shas: set[str] = field(default_factory=set)  # short SHAs the turn's own `git commit` calls printed
    commits: int = 0  # of those, the ones found in the repository
    reworked: bool = False  # a fix or revert touched the same files within 72 h after it ended
    _times: list = field(default_factory=list, repr=False)
    _last_text: str = field(default="", repr=False)

    @property
    def workflow(self) -> str:
        own = workflow_of(self.skills)
        return self.carried if own in _GENERIC and self.carried else own

    @property
    def false_done_proxy(self) -> bool:
        return self.claimed_done and self.pushback_next


def _time(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict))


def _entries(path: Path):
    with open(path, errors="replace") as handle:
        for line in handle:
            if '"user"' not in line and '"assistant"' not in line:  # cheap skip of the many other entry kinds
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("timestamp"):
                yield entry


def _add_usage(turn: Turn, message: dict, seen: set) -> None:
    key = message.get("id")
    if key in seen:
        return  # one API message is written as one entry per content block, each with the same usage
    seen.add(key)
    usage = message.get("usage") or {}
    turn.output_tokens += int(usage.get("output_tokens") or 0)
    turn.fresh_tokens += int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
    turn.cached_tokens += int(usage.get("cache_read_input_tokens") or 0)


def read_session(path: Path) -> list[Turn]:
    path = Path(path)
    project = path.parent.name
    turns: list[Turn] = []
    seen: set = set()
    for entry in _entries(path):
        kind, message = entry.get("type"), entry.get("message") or {}
        if kind == "user":
            text = _text(message.get("content"))
            if (entry.get("origin") or {}).get("kind") == "human" and not entry.get("isMeta"):
                if turns:
                    turns[-1].pushback_next = is_pushback(text)
                turns.append(Turn(session=path.stem, project=project, start=entry["timestamp"],
                                  cwd=entry.get("cwd") or ""))
                turns[-1]._times.append(_time(entry["timestamp"]))
                continue
            if text.lstrip().startswith("[Request interrupted by user") and turns:
                turns[-1].interrupted = True
                continue
        if not turns:
            continue
        turn = turns[-1]
        if kind == "assistant":
            turn._times.append(_time(entry["timestamp"]))
            turn.end = entry["timestamp"]
            turn.cwd = turn.cwd or entry.get("cwd") or ""
            _add_usage(turn, message, seen)
            if entry.get("attributionSkill"):
                turn.skills.add(entry["attributionSkill"])
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    turn._last_text = block["text"]
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    turn.skills.add(str((block.get("input") or {}).get("skill", "")))
        else:
            turn._times.append(_time(entry["timestamp"]))
            for block in message.get("content") or [] if isinstance(message.get("content"), list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    turn.shas |= set(_COMMIT_LINE.findall(_result_text(block.get("content"))))
    _add_subagents(path, turns)
    for turn in turns:
        times = sorted(turn._times)
        turn.busy_s = sum(b - a for a, b in zip(times, times[1:]) if b - a <= IDLE_GAP_S)
        turn.claimed_done = bool(_DONE.search(turn._last_text))
    _carry_workflows(turns)
    return turns


def _carry_workflows(turns: list[Turn]) -> None:
    current, left, last_start = None, 0, None
    for turn in turns:
        start = _time(turn.start)
        if last_start is not None and start - last_start > CARRY_GAP_S:
            current = None
        own = workflow_of(turn.skills)
        if own not in _GENERIC:
            current, left = own, CARRY_TURNS
        elif current and left > 0:
            turn.carried, left = current, left - 1
        last_start = start


def _add_subagents(path: Path, turns: list[Turn]) -> None:
    if not turns:
        return
    starts = [_time(t.start) for t in turns]

    def owner_of(stamp: float) -> Turn | None:
        index = max((i for i, s in enumerate(starts) if s <= stamp), default=None)
        return turns[index] if index is not None else None

    for agent in sorted((path.parent / path.stem / "subagents").glob("*.jsonl")):
        seen: set = set()
        first = None
        for entry in _entries(agent):
            if entry.get("type") != "assistant":
                continue
            stamp = _time(entry["timestamp"])
            turn = owner_of(stamp)
            if turn is None:
                continue
            first = first or turn
            _add_usage(turn, entry.get("message") or {}, seen)
        if first:
            first.subagents += 1


_REPOS: dict[str, list] = {}
_ROOTS: dict[str, Path | None] = {}


def _repo_root(cwd: str) -> Path | None:
    """The repository a session ran in; for a worktree that is gone, the repository it belonged to."""
    path = Path(cwd)
    while path != path.parent and not path.exists():
        path = path.parent
    if ".worktrees" in Path(cwd).parts:
        path = Path(*Path(cwd).parts[:Path(cwd).parts.index(".worktrees")])
    done = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if done.returncode:
        return None
    common = Path(done.stdout.strip())
    common = common if common.is_absolute() else (path / common).resolve()
    return common.parent


def _commits_for(cwd: str) -> list:
    if cwd not in _ROOTS:
        _ROOTS[cwd] = _repo_root(cwd) if cwd else None
    root = _ROOTS[cwd]
    if root is None:
        return []
    key = str(root)
    if key not in _REPOS:
        _REPOS[key] = rework.repo_commits(root)
    return _REPOS[key]


def attach_rework(turns: list[Turn]) -> None:
    """Only the commits a turn itself made count: the owner runs several sessions in one repository at once."""
    for turn in turns:
        if not turn.end or not turn.shas:
            continue
        made, redo = rework.rework_for(rework.TurnWindow(turn.start, turn.end), _commits_for(turn.cwd),
                                       own=turn.shas)
        turn.commits, turn.reworked = len(made), bool(redo)


def _median(values) -> float:
    values = list(values)
    return statistics.median(values) if values else 0.0


def summarize(turns: list[Turn]) -> dict[str, dict]:
    groups: dict[str, list[Turn]] = defaultdict(list)
    for turn in turns:
        groups[turn.workflow].append(turn)
    rows = {}
    for name, group in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        dones = [t for t in group if t.claimed_done]
        rows[name] = {
            "turns": len(group),
            "median_busy_min": round(_median(t.busy_s for t in group) / 60, 1),
            "median_output_tokens": _median(t.output_tokens for t in group),
            "median_fresh_tokens": _median(t.fresh_tokens for t in group),
            "pushback_rate": round(sum(t.pushback_next for t in group) / len(group), 3),
            "interrupt_rate": round(sum(t.interrupted for t in group) / len(group), 3),
            "done_claims": len(dones),
            "false_done_proxy_rate": round(sum(t.false_done_proxy for t in dones) / len(dones), 3) if dones else 0.0,
            "turns_with_commits": sum(1 for t in group if t.commits),
            "rework_rate": (round(sum(t.reworked for t in group if t.commits)
                                  / sum(1 for t in group if t.commits), 3) if any(t.commits for t in group) else 0.0),
        }
    return rows


def read_all(projects: Path = PROJECTS, since: str | None = None) -> list[Turn]:
    turns = []
    for path in sorted(Path(projects).glob("*/*.jsonl")):
        if path.parent.name.startswith(SKIP_PROJECTS):
            continue
        turns += [t for t in read_session(path) if not since or t.start >= since]
    return turns


def _table(rows: dict[str, dict]) -> str:
    lines = ["| workflow | turns | median busy | median output tok | median fresh tok | pushback | interrupted |"
             " done claims | claimed done → pushback | turns with commits | reworked |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in rows.items():
        lines.append(f"| {name} | {r['turns']} | {r['median_busy_min']} min | {r['median_output_tokens']:.0f} | "
                     f"{r['median_fresh_tokens']:.0f} | {r['pushback_rate']:.0%} | {r['interrupt_rate']:.0%} | "
                     f"{r['done_claims']} | {r['false_done_proxy_rate']:.0%} | {r['turns_with_commits']} | "
                     f"{r['rework_rate']:.0%} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="ISO date, e.g. 2026-10-01")
    parser.add_argument("--projects", default=str(PROJECTS))
    parser.add_argument("--save", action="store_true",
                        help="keep the per-turn numbers (no text) under ~/.local/share/keryx/field, since "
                             "Claude Code deletes old transcripts")
    args = parser.parse_args(argv)
    turns = read_all(Path(args.projects), args.since)
    attach_rework(turns)
    print(_table(summarize(turns)))
    if args.save:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        out = SNAPSHOTS / f"turns-{datetime.now().strftime('%Y%m%d')}.jsonl"
        with out.open("w") as handle:
            for t in turns:
                row = {k: v for k, v in asdict(t).items() if not k.startswith("_")}
                row.update(skills=sorted(t.skills), workflow=t.workflow, false_done_proxy=t.false_done_proxy)
                handle.write(json.dumps(row) + "\n")
        print(f"saved {len(turns)} turns to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
