"""One real keryx run as one result: the same numbers a bench run gives, read from what the run leaves behind.

Sources, all local and read-only: the coordinator's session transcript and its subagents' transcripts
(`~/.claude/projects/...`), the Cursor executor's event logs and the keryx run log (`<main checkout>/.keryx/runs/`, or `<git-common-dir>/cursor-loop/` for runs started before 1.2).
No model calls; no message text is kept. Re-run it at any time: mid-run it is a snapshot, and defects found after
"done" are added with `defect` and survive later snapshots.

  python field/run.py record --session <transcript.jsonl> --repo <repo> --slug <keryx slug>
      [--since ISO]                 the first keryx call at or after it starts the run (a session with several runs)
      [--start ISO] [--until ISO]   exact bounds, for a run that did not call keryx or shares its session
      [--name NAME]                 save as NAME.json (two runs on one slug)
      [--loops P1,P2]               executor loop prefixes, when slices were not named after the slug
  python field/run.py defect --slug <record name> "what broke"
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

OUT = Path.home() / ".local" / "share" / "keryx" / "field-runs"
IDLE_GAP_S = 10 * 60  # a longer silence is waiting (on the owner, an executor, a limit), not work
STALL_MIN = 10  # as the adapter: an executor silent this long without a final result has stalled
KERYX_SKILLS = ("keryx:keryx", "keryx")
FAILED_ROUND = ("ERROR", "STALLED", "EXPIRED", "CANCELLED")  # run.json statuses that end a round without success


def _t(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def _lines(path: Path):
    with open(path, errors="replace") as handle:
        for line in handle:
            if '"user"' not in line and '"assistant"' not in line and '"pr-link"' not in line:
                continue  # the many other entry kinds carry nothing this record uses
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("timestamp"):
                yield entry


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def _start(entries: list[dict], since: str | None) -> str | None:
    """The owner's prompt that started the run: the last one before the first keryx skill call."""
    last_prompt = None
    for e in entries:
        if since and e["timestamp"] < since:
            continue
        if e.get("type") == "user" and (e.get("origin") or {}).get("kind") == "human":
            last_prompt = e["timestamp"]
        if e.get("type") == "assistant":
            for b in (e.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill" \
                        and (b.get("input") or {}).get("skill") in KERYX_SKILLS:
                    return last_prompt or e["timestamp"]
    return None


def _usage(by_model: dict, message: dict, seen: dict) -> None:
    """Count one API message once, at its largest usage: subagent transcripts write an entry per streamed chunk
    with growing usage, the coordinator's repeat the same final usage on every content block."""
    u = message.get("usage") or {}
    now = (int(u.get("output_tokens") or 0),
           int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0),
           int(u.get("cache_read_input_tokens") or 0))
    key = message.get("id")
    before = seen.get(key, (0, 0, 0))
    best = tuple(max(a, b) for a, b in zip(before, now))
    seen[key] = best
    m = by_model[message.get("model") or "?"]
    m["output"] += best[0] - before[0]
    m["fresh"] += best[1] - before[1]
    m["cached"] += best[2] - before[2]


def _models():
    return defaultdict(lambda: {"output": 0, "fresh": 0, "cached": 0})


def _busy_min(times: list[float]) -> float:
    times = sorted(times)
    return round(sum(b - a for a, b in zip(times, times[1:]) if b - a <= IDLE_GAP_S) / 60, 1)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


def _main_and_common(repo: Path) -> tuple[Path, Path]:
    """The main checkout and the common git dir, by the adapter's rule (keryx.py main_worktree)."""
    if (repo / ".git").is_dir():
        return repo, repo / ".git"
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common_path = (Path(common) if Path(common).is_absolute() else repo / common).resolve()
    git_dir = _git(repo, "rev-parse", "--absolute-git-dir")
    if git_dir and Path(git_dir).resolve() == common_path:
        top = _git(repo, "rev-parse", "--show-toplevel")
        if top:
            return Path(top).resolve(), common_path
    if common_path.name == ".git":
        return common_path.parent, common_path
    worktree = _git(common_path, "config", "--file", str(common_path / "config"), "core.worktree")
    if not worktree:
        # extensions.worktreeConfig keeps it in the main worktree's own file, where the adapter moves it
        worktree = _git(common_path, "config", "--file", str(common_path / "config.worktree"), "core.worktree")
    if worktree:
        return (common_path / worktree).resolve(), common_path
    return common_path, common_path


def _loops_dirs(repo: Path) -> list[Path]:
    """Both layouts a run can live in, the keryx folder first; only those that exist."""
    main, common_path = _main_and_common(Path(repo))
    return [d for d in (main / ".keryx" / "runs", common_path / "cursor-loop") if d.is_dir()]


def _started(run_json: Path, default: float) -> float:
    try:
        return _t(json.loads(run_json.read_text())["startedAt"])
    except (OSError, ValueError, KeyError):
        return default


def _failed_status(run_json: Path) -> str | None:
    try:
        status = str(json.loads(run_json.read_text()).get("status") or "").upper()
    except (OSError, ValueError, AttributeError):
        return None
    return status.lower() if status in FAILED_ROUND else None


def _executor_runs(roots: list[Path], prefixes: list[str], now: float) -> list[dict]:
    runs = []
    for loop in sorted({p for root in roots for prefix in prefixes for p in root.glob(f"{prefix}*") if p.is_dir()},
                       key=lambda p: (p.name, str(p))):
        rounds = sorted(p for p in (loop / "rounds").glob("*") if p.is_dir())
        if not rounds:
            continue
        minutes = out_tokens = 0.0
        status, silent = "running", 0.0
        for r in rounds:
            events = r / "events.ndjson"
            if not events.exists():
                # A Claude-subagent round has run.json only (prepared by the adapter, marked by the
                # coordinator): outcome and times come from there, and it used no tokens of its own.
                try:
                    run_json = json.loads((r / "run.json").read_text())
                except (OSError, ValueError):
                    run_json = {}
                try:
                    ended = _t(run_json["finishedAt"]) if run_json.get("finishedAt") else now
                except ValueError:
                    ended = now
                minutes += max(0.0, (ended - _started(r / "run.json", ended)) / 60)
                silent = round((now - ended) / 60, 1)
                status = {"FINISHED": "success", "DISPATCHED": "running", "RUNNING": "running"}.get(
                    run_json.get("status"), "error")
                continue
            stamps, result = [], None
            for line in events.read_text(errors="replace").splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("timestamp_ms"):
                    stamps.append(e["timestamp_ms"] / 1000)
                if e.get("type") == "result":
                    result = e
            if result:
                minutes += (result.get("duration_ms") or 0) / 60000 or ((max(stamps) - min(stamps)) / 60 if stamps else 0)
                usage = result.get("usage") or {}  # Cursor: camelCase; Claude Code (the glm runner): snake_case
                out_tokens += int(usage.get("outputTokens") or usage.get("output_tokens") or 0)
                status, silent = str(result.get("subtype") or "done"), 0.0
            else:
                last = max(stamps) if stamps else events.stat().st_mtime  # Claude Code's events carry no time
                first = min(stamps) if stamps else _started(events.parent / "run.json", last)
                minutes += (last - first) / 60
                silent = round((now - last) / 60, 1)
                status = "stalled" if silent >= STALL_MIN else "running"
            failed = _failed_status(events.parent / "run.json")  # run.json knows rounds that died or were cut off
            if failed:
                status, silent = failed, 0.0
        runs.append({"loop": loop.name, "rounds": len(rounds), "status": status, "minutes": round(minutes, 1),
                     "output_tokens": int(out_tokens), "silent_min": silent})
    return runs


def _run_log(roots: list[Path], slug: str, prefixes: list[str] | None = None) -> dict:
    # a run that switched runner copied its log into <slug>-glm/ and kept logging there: read them all,
    # in every layout, the slug's own log first
    own = [root / slug for root in roots]
    dirs = own + sorted({p for root in roots for prefix in prefixes or [slug] for p in root.glob(f"{prefix}*")
                         if p.is_dir() and p not in own}, key=lambda p: (p.name, str(p)))
    rows, kept = [], set()
    for d in dirs:
        path = d / "decisions.tsv"
        if not path.is_file():
            continue
        for r in csv.DictReader(path.open(), delimiter="\t"):
            row = tuple(sorted((k or "?", str(v)) for k, v in r.items()))
            if row not in kept:  # the copied rows repeat exactly
                kept.add(row)
                rows.append(r)
    return {"rows": len(rows),
            "rulings": sum(1 for r in rows if "ruling" in (r.get("result"), r.get("phase"))
                           or (r.get("decision") or "").startswith("Ruling")),
            "phases": dict(Counter(r.get("phase") or "?" for r in rows))}


def record(session: Path, repo: Path, slug: str, now: datetime | None = None, since: str | None = None,
           start: str | None = None, until: str | None = None, name: str | None = None,
           loops: list[str] | None = None) -> dict:
    session = Path(session)
    now_s = (now or datetime.now(timezone.utc)).timestamp()
    entries = [e for e in _lines(session) if not until or e["timestamp"] <= until]
    start = start or _start(entries, since)
    if start is None:
        raise SystemExit(f"no keryx run found in {session}")
    coord, tools, seen = _models(), Counter(), {}
    times, prompts, interruptions = [], 0, 0
    asked: dict[str, str] = {}
    questions = []
    first_seen: dict[str, str] = {}  # the transcript repeats the session's current PR on every turn
    for e in entries:
        if e.get("type") == "pr-link" and e.get("prUrl"):
            first_seen.setdefault(e["prUrl"], e["timestamp"])
    prs = [url for url, when in first_seen.items() if when >= start]
    for e in entries:
        if e["timestamp"] < start:
            continue
        kind, message = e.get("type"), e.get("message") or {}
        if kind == "pr-link":
            continue
        times.append(_t(e["timestamp"]))
        if kind == "user":
            if (e.get("origin") or {}).get("kind") == "human" and not e.get("isMeta"):
                prompts += 1
            if _text(message.get("content")).lstrip().startswith("[Request interrupted"):
                interruptions += 1
            for b in message.get("content") or [] if isinstance(message.get("content"), list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in asked:
                    when = asked.pop(b["tool_use_id"])
                    questions.append({"asked": when, "answered": e["timestamp"],
                                      "waited_min": round((_t(e["timestamp"]) - _t(when)) / 60, 1)})
        elif kind == "assistant":
            _usage(coord, message, seen)
            for b in message.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tools[b.get("name")] += 1
                    if b.get("name") == "AskUserQuestion":
                        asked[b.get("id")] = e["timestamp"]
    questions += [{"asked": when, "answered": None, "waited_min": None} for when in asked.values()]
    subs, sub_seen, sub_files = _models(), {}, 0
    for agent in sorted((session.parent / session.stem / "subagents").glob("*.jsonl")):
        used = False
        for e in _lines(agent):
            if e.get("type") == "assistant" and start <= e["timestamp"] and (not until or e["timestamp"] <= until):
                _usage(subs, e.get("message") or {}, sub_seen)
                used = True
        sub_files += used
    roots = _loops_dirs(repo)
    runs = _executor_runs(roots, loops or [slug], now_s)
    last = max(times) if times else _t(start)
    return {
        "slug": slug, "name": name or slug, "session": str(session), "repo": str(repo), "start": start, "until": until,
        "last_activity": datetime.fromtimestamp(last, timezone.utc).isoformat().replace("+00:00", "Z"),
        "wall_min": round((last - _t(start)) / 60, 1), "busy_min": _busy_min(times),
        "owner": {"prompts": prompts, "questions": questions, "interruptions": interruptions,
                  "waited_min": round(sum(q["waited_min"] or 0 for q in questions), 1)},
        "coordinator": {"by_model": dict(coord), "tool_calls": dict(tools)},
        "subagents": {"transcripts": sub_files, "by_model": dict(subs)},
        "executor": {"runs": runs, "stalled": [r["loop"] for r in runs if r["status"] == "stalled"],
                     "minutes": round(sum(r["minutes"] for r in runs), 1),
                     "output_tokens": sum(r["output_tokens"] for r in runs)},
        "log": _run_log(roots, slug, loops or [slug]),
        "outcome": {"prs": prs},
        "escaped_defects": [],
    }


def save(rec: dict, out: Path = OUT) -> Path:
    path = Path(out) / f"{rec.get('name') or rec['slug']}.json"
    if path.exists():
        rec["escaped_defects"] = json.loads(path.read_text()).get("escaped_defects", [])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=2) + "\n")
    return path


def add_defect(out: Path, slug: str, what: str) -> None:
    path = Path(out) / f"{slug}.json"
    rec = json.loads(path.read_text())
    rec.setdefault("escaped_defects", []).append({"what": what, "found": datetime.now(timezone.utc).isoformat()})
    path.write_text(json.dumps(rec, indent=2) + "\n")


def _summary(rec: dict) -> str:
    coord = sum(m["output"] for m in rec["coordinator"]["by_model"].values())
    subs = sum(m["output"] for m in rec["subagents"]["by_model"].values())
    q = rec["owner"]["questions"]
    lines = [f"keryx run {rec['slug']} from {rec['start']}: {rec['wall_min']} min wall, {rec['busy_min']} min busy",
             f"owner: {rec['owner']['prompts']} prompts, {len(q)} questions, {rec['owner']['waited_min']} min waiting "
             f"for answers, {rec['owner']['interruptions']} interruptions",
             f"tokens out: coordinator {coord:,}, subagents {subs:,} ({rec['subagents']['transcripts']} transcripts), "
             f"executor {rec['executor']['output_tokens']:,} in {rec['executor']['minutes']} min",
             "executor runs: " + ", ".join(f"{r['loop']} {r['status']} {r['minutes']} min"
                                            + (f" (silent {r['silent_min']} min)" if r["status"] == "stalled" else "")
                                            for r in rec["executor"]["runs"]),
             f"log: {rec['log']['rows']} rows, {rec['log']['rulings']} rulings; PRs: {', '.join(rec['outcome']['prs']) or 'none'}"
             f"; escaped defects: {len(rec['escaped_defects'])}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("record")
    r.add_argument("--session", required=True)
    r.add_argument("--repo", required=True)
    r.add_argument("--slug", required=True)
    r.add_argument("--since", help="ISO time; the first keryx call at or after it starts the run")
    r.add_argument("--start", help="ISO time the run started, when it did not call keryx (overrides --since)")
    r.add_argument("--until", help="ISO time the run ended (its final report); later entries are left out")
    r.add_argument("--name", help="record name (default: the slug), for two runs on one slug")
    r.add_argument("--loops", help="comma-separated prefixes of the executor loops (default: the slug)")
    d = sub.add_parser("defect")
    d.add_argument("--slug", required=True, help="the record name (the slug unless --name was given)")
    d.add_argument("what")
    args = parser.parse_args(argv)
    if args.command == "record":
        rec = record(Path(args.session), Path(args.repo), args.slug, since=args.since, start=args.start,
                     until=args.until, name=args.name, loops=args.loops.split(",") if args.loops else None)
        path = save(rec)
        print(_summary(json.loads(path.read_text())))
        print(f"saved {path}", file=sys.stderr)
    else:
        add_defect(OUT, args.slug, args.what)
    return 0


if __name__ == "__main__":
    sys.exit(main())
