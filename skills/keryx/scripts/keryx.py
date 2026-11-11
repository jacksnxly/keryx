#!/usr/bin/env python3
"""keryx adapter: start and follow the executor of each slice (the Cursor CLI, a GLM Coding Plan, a Claude subagent, a Cursor Cloud Agent) from the coordinator's session.

Claude Code is the coordinator. This script starts and follows the implementer
and reads its git output; every judgement (plan, review, QA, merge) stays with
the coordinator. Two runners do the implementing:

  cli    (default) the Cursor CLI in headless mode on this machine
         (`agent -p --force`, https://cursor.com/docs/cli/headless), in its own
         git worktree <repo>/.worktrees/cursor-<slug> on branch cursor/<slug>.
         Draws from the plan's included usage. Commits stay local; nothing is pushed.
  cloud  a Cursor Cloud Agent through the Cloud Agents API v1
         (https://cursor.com/docs/cloud-agent/api/endpoints). Commits land on a
         remote cursor/* branch. Needs prepaid credit on the X Subscription.
  glm    Claude Code in headless mode (https://code.claude.com/docs/en/headless) against
         Z.ai's GLM Coding Plan endpoint (https://docs.z.ai/devpack/tool/claude), for when
         Cursor's usage is spent. Same worktree model: .worktrees/glm-<slug>, branch glm/<slug>.
  subagent  a Claude subagent the coordinator dispatches itself with the keryx executor agent;
         it needs no key and no install, so it is the whole ladder when nothing is configured.
         `create --runner subagent` prepares its worktree (.worktrees/sub-<slug>, branch sub/<slug>)
         and loop state but starts no process; the coordinator marks the round's outcome with `mark`.
         The subagent's worktree cannot push (a per-worktree push URL goes nowhere).
  <name>  a provider declared in config.json ("providers": {name: {"runner": "codex", "baseUrl": …,
         "keyFile": …, "model": …}}), run through `codex exec` against that provider's API. Same
         worktree model: .worktrees/<name>-<slug>, branch <name>/<slug>. The key is read from keyFile
         and passed only as $KERYX_CODEX_API_KEY in the executor's own CODEX_HOME; it is never printed.

The ladder of executors a machine has, in the order to try them, is saved once with `setup`;
after a failed run, `create` on the same slug hands it to the next executor (the last rung is
"inline": the coordinator writes the code itself).

State lives in <main checkout>/.keryx/runs/<slug>/: per repository, shared by its worktrees,
ignored by git through .keryx/.gitignore, and outside .git, a protected path where an agent's
writes prompt or are denied. Runs started before 1.2 keep <git-common-dir>/cursor-loop/<slug>/.

Usage (run from inside the target repository):
  keryx.py preflight [--runner cli|cloud|glm|subagent|<provider>]
  keryx.py setup     [--executors LIST] [--order ladder|resets] [--reset RUNNER=WHEN[/EVERY]] [--detect]
                     (save this machine's ladder; probe what works here)
  keryx.py executors [--after RUNNER]                (the ladder still available; the next executor after a runner)
  keryx.py remember [--repo] NOTE                   (keep a choice or trap for later runs; never a secret)
  keryx.py recall                                   (print the user's and this repository's keryx memory)
  keryx.py mark --slug S --status STATUS            (close a subagent round: FINISHED, ERROR, STALLED, CANCELLED)
  keryx.py models    [--runner cli|cloud|glm]
  keryx.py create    --slug S --prompt-file F [--runner cli|cloud|glm|subagent|<provider>] [--model ID] [--ref REF]
                    [--env NAME=value]... [--param id=value]... [--mode agent|plan] [--image P]...
                    [--escalate]
                    (local runners only: --env; cloud-only: --param --image; on a failed run,
                    re-create switches to the new executor on the same slug; --escalate also takes
                    over a finished one)
  keryx.py followup  --slug S --prompt-file F [--mode agent|plan]
  keryx.py wait      --slug S [--timeout SECONDS]
  keryx.py status    --slug S
  keryx.py fetch     --slug S
  keryx.py gates     --slug S [--ref REF]  (did the run touch an architecture or CI gate file?)
  keryx.py locked    --slug S [--ref REF]  (check locked test blocks against the implementer's head;
                    --ref checks a commit `fetch` cannot read, e.g. a subagent's branch)
  keryx.py mark      --slug S --status FINISHED|ERROR|STALLED|CANCELLED   (record a subagent round's outcome)
  keryx.py cancel    --slug S
  keryx.py scrub     --slug S                (cli: strip Cursor's attribution trailer from local commits)
  keryx.py artifacts --slug S [--download]   (cloud)
  keryx.py usage     --slug S                (cloud)
  keryx.py archive   --slug S                (cloud)
  keryx.py log       --slug S PHASE DECISION WHY EVIDENCE RESULT   (the coordinator's own row)
  keryx.py review-brief --slug S [--base REF] [--head REF] [--risk] [--hotfix]   (write the fresh reviewer's brief;
                        print how to dispatch it)
  keryx.py report    --slug S [--head REF]   (draft docs/keryx/<date>-<slug>.md, the run report the coordinator fills in)
  keryx.py finish   --slug S [--head REF] [--findings-only]   (the run is finished only when this prints FINISHED;
                    --findings-only: a findings-only review changes nothing, so no run report)

Every command that changes loop state appends a row to <state>/decisions.tsv (one tab-separated row
per decision); the coordinator adds its own rows with `keryx.py log`.

Cloud runner: the API key comes from $CURSOR_API_KEY or the macOS keychain item
"cursor-api-key"; it is never printed or written to disk by this script.
CLI runner: uses the CLI's own login (`agent login`).
GLM runner: the plan key comes from $GLM_API_KEY or ~/.config/glm/coding-plan.key; it is never printed
or written into the state dir by this script.
Provider runner: the key comes from the provider's keyFile in config.json; it is never printed or
written to disk by this script.
"""

from __future__ import annotations

import argparse
import base64
import calendar
import datetime as dt
import fnmatch
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("CURSOR_API_BASE", "https://api.cursor.com")
USER_AGENT = "keryx/1.2"
TERMINAL_RUN_STATES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}
KEYCHAIN_SERVICE = "cursor-api-key"
DEFAULT_CLI_MODEL = "grok-4.7-xhigh"

# Commands the CLI implementer may never run, even with --force (the CLI honours
# explicit denies: https://cursor.com/docs/cli/reference/parameters, --force).
# The base is the command's first token (https://cursor.com/docs/cli/reference/permissions).
CLI_DENY = [
    "Shell(kubectl)", "Shell(helm)", "Shell(argocd)", "Shell(ssh)", "Shell(scp)", "Shell(sftp)",
    "Shell(rsync)", "Shell(gh)", "Shell(security)", "Shell(sudo)", "Shell(sops)", "Shell(vercel)",
    "Shell(wrangler)", "Shell(flyctl)", "Shell(aws)", "Shell(gcloud)",
]
# A push from the implementer's worktree goes nowhere: git reads these as
# config overrides for every git command the CLI starts.
NO_PUSH_ENV = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "remote.origin.pushurl",
    "GIT_CONFIG_VALUE_0": "https://push-disabled.invalid/keryx",
}

# Runners that work in a local worktree on this machine, and each one's worktree and branch prefix
# (sub/<slug> for a Claude subagent, which the coordinator dispatches itself).
LOCAL_RUNNERS = ("cli", "glm", "subagent")
WORKTREE_PREFIX = {"cli": "cursor", "glm": "glm", "subagent": "sub"}
# The GLM runner is Claude Code on the Coding Plan's own Anthropic endpoint; the general API endpoint would bill the
# pay-as-you-go balance instead (https://docs.z.ai/devpack/tool/claude). A plan bought on Zhipu's China platform
# answers on open.bigmodel.cn; $GLM_BASE_URL or ~/.config/glm/base-url picks it.
GLM_BASE_URLS = ("https://api.z.ai/api/anthropic", "https://open.bigmodel.cn/api/anthropic")
DEFAULT_GLM_MODEL = "opus"
GLM_ENV = {
    # Z.ai's manual Claude Code setup (docs.z.ai/devpack/tool/claude, checked 2026-10-26).
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.3[1m]",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.3[1m]",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-5.3-flash[1m]",
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_AUTOUPDATER": "1",
}
# The model behind this runner is a third party's: it gets the repository, never the owner's credentials.
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL", re.I)
# Deny rules block in every permission mode, bypassPermissions included (https://code.claude.com/docs/en/permission-modes).
GLM_DENY = [f"Bash({c} *)" for c in (
    "kubectl", "helm", "argocd", "ssh", "scp", "sftp", "rsync", "gh", "security", "sudo", "sops", "vercel",
    "wrangler", "flyctl", "aws", "gcloud", "git push",
)] + [f"Bash({c})" for c in ("kubectl", "ssh", "gh", "vercel", "env", "printenv")] + [
    "Read(~/.ssh/**)", "Read(~/.config/glm/**)", "Read(~/.kube/**)", "Read(~/.cursor/**)",
    "Read(~/Library/Application Support/com.vercel.cli/**)",
    # A third party's model reads no run (a run's QA evidence and reproductions can show real people) and not
    # the repository's memory; its own config lives in .keryx/glm/<slug>/, beside the runs and still readable
    # to the executor that reads its large tool outputs back from it.
    "Read(**/.keryx/runs/**)", "Read(//**/.keryx/runs/**)",
    "Read(**/.keryx/memory.md)", "Read(//**/.keryx/memory.md)",
    # Seen 2026-10-25: a GLM run printed the non-secret lines of a checkout's .env.local while debugging.
    "Read(**/.env)", "Read(**/.env.*)", "Read(//**/.env)", "Read(//**/.env.*)", "Edit(**/.env*)", "Edit(//**/.env*)",
    "Bash(cp *.env*)", "Bash(cat *.env*)", "Bash(grep *.env*)", "Bash(source *.env*)",
]
# A provider declared in config.json ("providers") runs on this machine through `codex exec`; Codex is the
# only provider runner today. Its key file is named in the config, and the key itself reaches the executor
# only as $KERYX_CODEX_API_KEY in the environment of its own CODEX_HOME.
PROVIDER_RUNNERS = ("codex",)
CODEX_KEY_ENV = "KERYX_CODEX_API_KEY"
# A provider name is no built-in executor (EXECUTORS): lowercase, 2-31 characters, a letter first.
PROVIDER_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
# codexConfig may carry any scalar Codex setting except the ones keryx writes itself.
CODEX_OWNED_CONFIG = ("model_provider", "model_providers", "model", "model_reasoning_effort", "sandbox_mode",
                      "approval_policy", "shell_environment_policy")


class LoopError(RuntimeError):
    """A failure the coordinator must see; never swallowed."""


# ---------------------------------------------------------------- credentials (cloud)


def api_key() -> str:
    key = os.environ.get("CURSOR_API_KEY", "").strip()
    if key:
        return key
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        raise LoopError("no CURSOR_API_KEY and no macOS `security` tool to read the keychain") from exc
    if out.returncode != 0 or not out.stdout.strip():
        raise LoopError(
            "no Cursor API key: set CURSOR_API_KEY or store it with "
            f"`security add-generic-password -a \"$USER\" -s {KEYCHAIN_SERVICE} -w`"
        )
    return out.stdout.strip()


# ---------------------------------------------------------------- http (cloud)


def _request(method: str, path: str, body: dict | None = None, *, accept: str = "application/json",
             extra_headers: dict | None = None, timeout: float = 60):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    token = base64.b64encode(f"{api_key()}:".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Accept": accept, "User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def call(method: str, path: str, body: dict | None = None, *, timeout: float = 60) -> dict:
    try:
        with _request(method, path, body, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        raise LoopError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LoopError(f"{method} {path} -> network error: {exc.reason}") from exc
    return json.loads(raw) if raw else {}


# ---------------------------------------------------------------- git + state


def git(*args: str, cwd: str | Path | None = None, check: bool = True) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    if check and out.returncode != 0:
        raise LoopError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def normalize_repo_url(remote: str) -> str:
    """git@github.com:o/r.git, ssh://git@github.com/o/r, https://github.com/o/r.git -> https://github.com/o/r"""
    remote = remote.strip()
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    raise LoopError(f"cannot turn remote {remote!r} into a repository URL")


def common_dir() -> Path:
    common = Path(git("rev-parse", "--git-common-dir"))
    return common if common.is_absolute() else (Path.cwd() / common).resolve()


def main_worktree() -> Path:
    """The repository's main checkout, where .keryx/ lives, in every layout: this checkout when its git
    dir is the common dir (the main checkout itself, a separate git dir, a submodule), the folder above
    a .git common dir (a linked worktree), the checkout the common dir's config names (a submodule's
    worktree: core.worktree, in the shared config or, once the settings move, the main worktree's own
    config.worktree), else the bare repository's own folder, which its worktrees share — and
    which no other bare repository in the same folder shares with it. Paths are compared resolved,
    because git prints each one as it found it."""
    common = common_dir().resolve()
    current = Path(git("rev-parse", "--absolute-git-dir")).resolve()
    if current == common:
        top = git("rev-parse", "--show-toplevel", check=False)
        if top:
            return Path(top).resolve()
    if common.name == ".git":
        return common.parent.resolve()
    worktree = git("config", "--file", str(common / "config"), "--get", "core.worktree", check=False)
    if not worktree:  # extensions.worktreeConfig moved it into the main worktree's own file (keryx does too)
        worktree = git("config", "--file", str(common / "config.worktree"), "--get", "core.worktree", check=False)
    if worktree:
        named = Path(worktree)
        return (common / named).resolve() if not named.is_absolute() else named.resolve()
    return common


def state_root() -> Path:
    return main_worktree() / ".keryx" / "runs"


def legacy_root() -> Path:
    """Where a run started before 1.2 lives: under the git common dir, which nothing writes to now."""
    return common_dir() / "cursor-loop"


def slug_dir(slug: str, *, must_exist: bool = True) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", slug):
        raise LoopError("slug must be lowercase letters, digits and dashes (1-61 chars)")
    d = state_root() / slug
    try:
        legacy = legacy_root() / slug
    except LoopError:  # no repository here (state_root may be pointed elsewhere): no legacy run either
        pass
    else:
        if legacy.is_dir() and not d.is_dir():
            d = legacy
    if must_exist and not (d / "agent.json").exists():
        raise LoopError(f"no loop state for {slug!r} at {d} (run `create` first)")
    return d


def ensure_ignored(folder: Path) -> None:
    """Before anything is written into `folder` (the .keryx folder the run root sits in, or .worktrees), its
    .gitignore exists with exactly `*` (created if missing, never overwritten), so git status never shows a
    run's files or an executor's worktree. The folder itself is passed in, so this needs no repository around
    the current directory."""
    ignore = folder / ".gitignore"
    if not ignore.exists():
        folder.mkdir(parents=True, exist_ok=True)
        ignore.write_text("*\n")


def repo_relative(path: Path) -> str:
    """A path relative to the repository's main checkout (.keryx/runs/<slug>/… for a run, or
    .git/cursor-loop/<slug>/… for one started before 1.2): a folder outside the checkout is named
    with ../ segments — never an absolute path, never an exception. The path is resolved first, so a
    checkout reached through a symlink is still named from the checkout itself."""
    return os.path.relpath(Path(path).resolve(), main_worktree())


LOCAL_PATH = "<!-- a local path was here -->"
# Any other absolute path: segments with no spaces, brackets or colons in them (a compiler's "file.py:3" ends
# before the colon, and each PATH entry is its own match), and a leading "/" that starts a path of its own —
# after a space, "=", ">", ":" or a flag ("-I/tmp"), or the "//" of a file:// URL — not one glued into a word
# or a URL's host ("example.com/tmp"), which is why the lookbehind stops a match only after two word characters.
ANY_ABSOLUTE_PATH = re.compile(r"(?<!\w\w)(?<![.~])/[^\s/`'\"()\[\]{}<>|;,:]+(?:/[^\s/`'\"()\[\]{}<>|;,:]+)*")
# The system's own programs, libraries and devices, which name no person's files: "2>/dev/null" and "/usr/bin/env"
# say nothing private, so they stay as they are. Only these: /System/Volumes/Data is the user's data volume on
# macOS, /usr/home is FreeBSD's home folder, and /usr/local, /usr/share/nginx, /dev/shm, /etc and /Library can
# name a client (found by the second and third reviews).
SYSTEM_PATHS = ("/bin/", "/sbin/", "/lib/", "/lib64/", "/usr/bin/", "/usr/sbin/", "/usr/lib/", "/usr/libexec/",
                "/usr/include/", "/proc/self/", "/System/Library/")
SYSTEM_DEVICES = ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom", "/dev/tty", "/dev/stdin", "/dev/stdout",
                  "/dev/stderr")


def strip_local_paths(text: str, checkouts: Path | list[Path], home: Path) -> str:
    """Text as a committed report may hold it: each checkout's path becomes repo-relative (its bare form
    becomes "."), then the home directory becomes "~", and every other absolute path whose first segment is a
    directory on this machine becomes a placeholder — a report names no local path. Each is replaced
    only where it ends at a path boundary: a "/", the end of the text, or anything but a character that
    continues a path name ("." and "-" continue one only when a name character follows, so a path that
    ends a sentence is still replaced and a sibling folder that shares its name is left as it is)."""
    checkouts = [checkouts] if isinstance(checkouts, Path) else checkouts
    for path, inside, bare in [(c, "", ".") for c in checkouts] + [(home, "~/", "~")]:
        at_boundary = re.escape(str(path)) + r"(?!\w|[.-]\w)(/)?"
        text = re.sub(at_boundary, lambda m: inside if m.group(1) else bare, text)

    def hide(match: re.Match) -> str:
        path, kept = match.group(0), ""
        while path[-1:] == ".":  # a full stop can end the sentence, not the path
            kept = path[-1] + kept
            path = path[:-1]
        first = path.lstrip("/").split("/", 1)[0]
        system = path in SYSTEM_DEVICES or (path + "/").startswith(SYSTEM_PATHS)
        real = first and not system and os.path.isdir("/" + first)
        return LOCAL_PATH + kept if real else match.group(0)

    return ANY_ABSOLUTE_PATH.sub(hide, text)


def load_agent(d: Path) -> dict:
    return json.loads((d / "agent.json").read_text())


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tsv_cell(value) -> str:
    """One line, and no leading character a spreadsheet would run as a formula."""
    v = re.sub(r"[\t\n\r]", " ", str(value))
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def append_log(d: Path, phase: str, decision: str, why: str, evidence: str, result: str) -> None:
    """Append a row to <state>/decisions.tsv (columns: ts phase decision why evidence result)."""
    d.mkdir(parents=True, exist_ok=True)
    log = d / "decisions.tsv"
    with log.open("a") as fh:
        if log.stat().st_size == 0:
            fh.write("ts\tphase\tdecision\twhy\tevidence\tresult\n")
        fh.write("\t".join(tsv_cell(c) for c in (now(), phase, decision, why, evidence, result)) + "\n")


def rounds(d: Path) -> list[Path]:
    return sorted(p for p in (d / "rounds").glob("[0-9][0-9]") if p.is_dir())


# A later row may retire an earlier one: "Ruling (replaces row 3): …" stands in for row 3.
REPLACES_ROW = re.compile(r"(?i)\breplaces row (\d+)\b")


def read_log_rows(d: Path) -> list[tuple[int, list[str]]]:
    """The run log's rows, each with its number: row N is the Nth line after the header. A malformed line
    keeps its number for the rows after it but is not returned."""
    log = d / "decisions.tsv"
    if not log.exists():
        return []
    return [(n, c) for n, c in enumerate((line.split("\t") for line in log.read_text().splitlines()[1:]), 1)
            if len(c) >= 6]


STANDARD_PHASES = {
    "intake", "size", "ground-truth", "plan", "dispatch", "execute", "check", "qa", "probe", "review",
    "ruling", "waiting", "answer", "next", "ci", "ship", "deploy", "release", "merge", "cleanup",
    "followup", "finish", "done", "note", "repro",
}
PHASE = re.compile(r"[a-z][a-z-]{1,19}")
FINISH_PHASE = re.compile(r"finish-[a-z][a-z0-9-]{1,19}")


def normalise_phase(phase: str) -> str:
    """The one spelling a program can read, before the shape is checked."""
    phase = phase.strip().lower()
    if phase in {"ground truth", "ground", "groundtruth"}:
        return "ground-truth"
    return phase


def standard_phase(phase: str) -> bool:
    return phase in STANDARD_PHASES or phase.startswith("finish-")


def run_size(rows: list[tuple[int, list[str]]]) -> str | None:
    """The latest size row's letter, or None when the run never logged one."""
    return next((c[2] for _, c in reversed(rows) if c[1] == "size" and c[2] in {"S", "M", "L"}), None)


def is_ruling(phase: str, decision: str) -> bool:
    """A ruling row: the phase says so, or the decision starts with "Ruling"."""
    return phase == "ruling" or decision.lower().startswith("ruling")


def standing_rulings(rows: list[tuple[int, list[str]]]) -> list[tuple[int, list[str]]]:
    """The rulings that still stand: no later row names one as the row it replaces."""
    replaced = set()
    for _, c in rows:
        m = REPLACES_ROW.search(c[2])
        if m:
            replaced.add(int(m.group(1)))
    return [(n, c) for n, c in rows if is_ruling(c[1], c[2]) and n not in replaced]


def deferred_rows(rows: list[tuple[int, list[str]]]) -> list[tuple[int, list[str]]]:
    """The rows marked deferred in their decision's label (the text before its first colon) — a row that only
    mentions the word later in its sentence is not one."""
    return [(n, c) for n, c in rows if "(deferred" in c[2].split(":", 1)[0].lower()]


def is_hotfix_run(rows: list[tuple[int, list[str]]]) -> bool:
    """A hotfix run: its log has an intake row that declares the lane as a field — `lane hotfix` at the start or after
    a separator (`size S · lane hotfix: …`, `size S, lane hotfix`) — never a mention inside a sentence: "not lane
    hotfix", or a follow-up's "the lasting fix behind the lane hotfix hf", is no hotfix."""
    return bool(hotfix_started(rows))


def hotfix_started(rows: list[tuple[int, list[str]]]) -> str:
    """The time of the run's first hotfix intake row, or "" when the run is not a hotfix."""
    stamps = [c[0] for _, c in rows if c[1] == "intake" and re.search(r"(?i)(?:^|[·,;|])\s*lane hotfix\b", c[2])]
    return min(stamps) if stamps else ""


def followup_rows(rows: list[tuple[int, list[str]]]) -> list[tuple[str, str]]:
    """The run's follow-up rows: phase `followup`, decision `<slug>: <what the lasting fix does>`, the slug matching
    the slug rule. A row in another shape is not a follow-up."""
    found = []
    for _, c in rows:
        m = re.fullmatch(r"([a-z0-9][a-z0-9-]{0,60}): (.+)", c[2]) if c[1] == "followup" else None
        if m:
            found.append((m.group(1), m.group(2)))
    return found


def followup_waived(rulings: list[tuple[int, list[str]]]) -> bool:
    """A standing ruling whose text after `Ruling: ` (or `Ruling (replaces row N): `) is `no follow-up — <why>`
    (case-insensitive; a dash, en dash, em dash or colon before the reason) waives the follow-up: the ruling says the
    hotfix itself is the lasting fix."""
    text_after = re.compile(r"(?i)^ruling(?: \(replaces row \d+\))?:\s*(.*)$")
    for _, c in rulings:
        m = text_after.match(c[2])
        # the phrase, a separator and a reason (`no follow-up — <why>`), not prose like "no follow-up run is open yet"
        if m and re.match(r"(?i)no follow-ups?(?:\s+[—–-]\s*|\s*:\s*)\S", m.group(1)):
            return True
    return False


_DROP_FOLLOWUP = re.compile(r"(?i)^ruling(?: \(replaces row \d+\))?:\s*drop follow-up ([a-z0-9][a-z0-9-]{0,60})(?![\w-])")


def standing_followups(rows: list[tuple[int, list[str]]], rulings: list[tuple[int, list[str]]]) -> list[tuple[str, str]]:
    """The follow-ups still asked for: every follow-up row, less those a standing ruling drops
    (`Ruling: drop follow-up <slug> — <why>`, for a row logged by mistake). `finish` checks these, the report names
    them, so the two never disagree."""
    dropped = {m.group(1) for _, c in rulings for m in [_DROP_FOLLOWUP.match(c[2])] if m}
    return [(slug, what) for slug, what in followup_rows(rows) if slug not in dropped]


def run_folders(d: Path) -> list[Path]:
    """The run's own folder and its slices': every folder named <slug>-<name> beside it, in either layout, that
    the run itself names as a whole name (in its plan or in a cell of one of its rows) and whose log starts no
    earlier than this run's — a later, separate run that merely shares the prefix is not a slice. A run with
    no rows of its own counts no slices."""
    return [d] + _later_prefix_folders(d)[0]


def unnamed_later_runs(d: Path) -> list[Path]:
    """The later <slug>-<name> folders with executor rounds that the run does not name: perhaps slices of a plan
    that called them "slice A", perhaps separate runs. Neither counted nor dropped without a word: the report
    names them for the coordinator to settle (found by the second review)."""
    return [f for f in _later_prefix_folders(d)[1] if rounds(f)]


def _later_prefix_folders(d: Path) -> tuple[list[Path], list[Path]]:
    """(named, unnamed): the <slug>-<name> folders, in either layout, whose log starts no earlier than the run's,
    split by whether the run names them."""
    rows = read_log_rows(d)
    if not rows:
        return [], []

    def started(folder: Path) -> str:
        first = read_log_rows(folder)
        return first[0][1][0] if first else ""

    own = rows[0][1][0]
    # a hotfix's follow-ups are separate runs, never its slices; an ordinary run has no follow-ups to set aside
    follow_ups = ({slug for slug, _ in standing_followups(rows, standing_rulings(rows))} if is_hotfix_run(rows)
                  else set())  # a row dropped by a ruling sets nothing aside
    follow_ups.discard(d.name)  # a row naming the run itself must not set its own later runs aside

    def a_follow_up(name: str) -> bool:  # the follow-up run, or one of its own slices
        return any(name == f or name.startswith(f + "-") for f in follow_ups)
    named = (d / "PLAN.md").read_text() if (d / "PLAN.md").exists() else ""
    named += "\n" + "\n".join("\t".join(c) for _, c in rows)
    later = []
    roots = [state_root()]
    try:
        roots.append(legacy_root())
    except LoopError:  # no repository here: only the state root can hold a slice
        pass
    for root in roots:
        later += [s for s in sorted(root.glob(f"{d.name}-*"))
                  if s.is_dir() and len(s.name) > len(d.name) + 1 and started(s) >= own and not a_follow_up(s.name)]
    is_named = [bool(re.search(rf"(?<![\w-]){re.escape(s.name)}(?![\w-])", named)) for s in later]
    return (sorted((s for s, n in zip(later, is_named) if n), key=lambda s: s.name),
            sorted((s for s, n in zip(later, is_named) if not n), key=lambda s: s.name))


def folder_rounds(folder: Path) -> tuple[int, int]:
    """(rounds, FIX rounds) in one run folder."""
    rs = rounds(folder)
    fixes = sum(1 for r in rs if (r / "prompt.md").exists()
                and any(line.startswith("Mode: FIX") for line in (r / "prompt.md").read_text().splitlines()))
    return len(rs), fixes


def current_round(d: Path) -> Path:
    rs = rounds(d)
    if not rs:
        raise LoopError(f"{d} has no rounds")
    return rs[-1]


def new_round(d: Path, prompt_file: str) -> Path:
    try:
        prompt = Path(prompt_file).read_text()
    except OSError as exc:
        raise LoopError(f"cannot read the brief {prompt_file}: {exc.strerror or exc}") from exc
    if not prompt.strip():
        raise LoopError(f"{prompt_file} is empty")
    r = d / "rounds" / f"{len(rounds(d)) + 1:02d}"
    r.mkdir(parents=True, exist_ok=False)
    (r / "prompt.md").write_text(prompt)
    return r


def read_prompt(prompt_file: str) -> str:
    text = Path(prompt_file).read_text()
    if not text.strip():
        raise LoopError(f"{prompt_file} is empty")
    return text


def prompt_payload(prompt_file: str, images: list[str]) -> dict:
    payload: dict = {"text": read_prompt(prompt_file)}
    if images:
        if len(images) > 5:
            raise LoopError("the API takes at most 5 images per prompt")
        payload["images"] = []
        for p in images:
            mime = mimetypes.guess_type(p)[0]
            if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                raise LoopError(f"{p}: unsupported image type {mime}")
            payload["images"].append({"data": base64.b64encode(Path(p).read_bytes()).decode(), "mimeType": mime})
    return payload


def pin_base(ref: str) -> str:
    """A full SHA as given; a remote branch or tag fetched fresh from origin; otherwise a local ref."""
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    fetched = subprocess.run(["git", "fetch", "--quiet", "origin", ref], capture_output=True, text=True)
    if fetched.returncode == 0:
        return git("rev-parse", "FETCH_HEAD")
    local = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], capture_output=True, text=True)
    if local.returncode == 0:
        return local.stdout.strip()
    raise LoopError(f"cannot resolve {ref!r}: not on origin ({fetched.stderr.strip()}) and not a local ref")


# ---------------------------------------------------------------- pure helpers (tested)


def parse_sse(lines):
    """Yield (event_id, event_type, data_dict_or_text) from an iterable of decoded SSE lines."""
    ev_id, ev_type, data = None, "message", []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                text = "\n".join(data)
                try:
                    payload = json.loads(text)
                except ValueError:
                    payload = text
                yield ev_id, ev_type, payload
            ev_type, data = "message", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "id":
            ev_id = value
        elif field == "event":
            ev_type = value
        elif field == "data":
            data.append(value)
    if data:
        text = "\n".join(data)
        try:
            yield ev_id, ev_type, json.loads(text)
        except ValueError:
            yield ev_id, ev_type, text


def parse_params(pairs: list[str]) -> list[dict]:
    """["reasoning_effort=xhigh", "fast=false"] -> [{"id": ..., "value": ...}] for model.params."""
    out = []
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key or not value:
            raise LoopError(f"--param expects id=value, got {pair!r}")
        out.append({"id": key.strip(), "value": value.strip()})
    return out


def parse_env(pairs: list[str]) -> dict:
    """["CARGO_BUILD_JOBS=6"] -> {"CARGO_BUILD_JOBS": "6"}; the guard-rail variables cannot be overridden."""
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise LoopError(f"--env expects NAME=value, got {pair!r}")
        if (key in ("KUBECONFIG", "SSH_AUTH_SOCK", "PATH", "EXIT_FILE", "CURSOR_CONFIG_DIR", "CODEX_HOME",
                    CODEX_KEY_ENV, "GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN", "GIT_SSH_COMMAND",
                    "GIT_TERMINAL_PROMPT")
                or key.startswith(("GIT_CONFIG", "ANTHROPIC", "CLAUDE", "GLM_", "OPENAI", "CODEX"))
                or "ASKPASS" in key.upper()):
            raise LoopError(f"--env may not set {key} (a guard rail of the local runners)")
        out[key] = value
    return out


def squash_ws(text: str) -> str:
    """Whitespace-insensitive form of code: runs collapse to one space, and space next to
    punctuation goes, so a formatter's line wraps (`a\n    .b()` vs `a.b()`) compare equal
    while `let x` and `letx` stay different."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r" ?([^\w ]) ?", r"\1", text)
    return re.sub(r",([)\]}])", r"\1", text)  # a formatter's trailing comma before a closing bracket


def locked_block_present(block: str, file_text: str) -> bool:
    """A locked test block counts as present when it appears with only whitespace changes."""
    body = squash_ws(file_text)
    if squash_ws(block) in body:
        return True
    if block.rstrip().endswith(","):
        return squash_ws(block.rstrip()[:-1]) in body
    return False


def inherited(d: Path, name: str) -> Path:
    """A slice's own file, else the same file in the nearest run it belongs to, else its own path."""
    own = d / name
    if own.exists():
        return own
    prefixes = sorted((p for p in d.parent.iterdir()
                       if p != d and p.is_dir() and d.name.startswith(p.name + "-")),
                      key=lambda p: len(p.name), reverse=True)
    for folder in prefixes:
        candidate = folder / name
        if candidate.exists():
            return candidate
    return own


# A finding's last fields: <sep> P<0-3> <sep> <confidence from 0 to 1>, where the separator is an em or en
# dash or one or two hyphens, with optional spaces (`— P1 — 0.8`, `- P2 - .6`).
FINDING_TAIL = re.compile(r"\s*(?:—|–|--|-)\s*(P[0-3])\s*(?:—|–|--|-)\s*(1(?:\.0+)?|0?\.\d+|0)\s*$")
FINDING_HEADER = re.compile(r"^(Head|Reach|Spec|Findings|Tests):")


def review_findings(text: str) -> dict:
    """Parse a reviewer's findings file: the reviewed head, a count per grade, and every way the file is
    not well-formed (the brief tells the reviewer the exact shape to write)."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = FINDING_HEADER.match(line)
        if m:
            current = m.group(1)
            sections.setdefault(current, []).append(line[m.end():])
        elif current is not None:
            sections[current].append(line)
    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    problems = []
    head = next((a.strip() for a in sections.get("Head", [])
                 if re.fullmatch(r"[0-9a-f]{7,40}", a.strip())), None)
    if head is None:
        problems.append("no Head line with the reviewed commit")
    for name in ("Reach", "Spec"):
        if not "\n".join(sections.get(name, [])).strip():
            problems.append(f"no {name} answer")
    if "Findings" not in sections:
        problems.append("no Findings section")
    else:
        answer = "\n".join(sections["Findings"]).strip()
        if not answer:
            problems.append("Findings is empty; write 'Findings: none'")
        elif answer.lower() != "none":
            findings = []
            for line in answer.splitlines():
                if line.startswith("- "):
                    findings.append(line[2:].strip())
                elif line.strip():
                    if findings:  # a wrapped finding continues the line above it
                        findings[-1] += " " + line.strip()
                    else:  # a list that lost its dash is still a finding, so the grade check names it
                        findings.append(line.strip())
            for f in findings:
                m = FINDING_TAIL.search(f)
                if m:
                    counts[m.group(1)] += 1
                else:
                    problems.append(f"finding without a P-grade and a confidence: {f[:80]}")
    return {"head": head, "counts": counts, "problems": problems}


def push_triggers_for(workflow: dict, branch: str) -> bool:
    """True when a GitHub Actions workflow runs on a push to `branch`."""
    on = workflow.get(True, workflow.get("on"))
    if on == "push" or (isinstance(on, list) and "push" in on):
        return True
    if not isinstance(on, dict) or "push" not in on:
        return False
    push = on["push"] or {}
    branches, ignore = push.get("branches"), push.get("branches-ignore")
    if branches is None and ignore is None:
        return not push.get("tags")  # tags-only filters never fire on branch pushes
    if branches is not None:
        hit = any(fnmatch.fnmatch(branch, pat) for pat in branches if not pat.startswith("!"))
        miss = any(fnmatch.fnmatch(branch, pat[1:]) for pat in branches if pat.startswith("!"))
        return hit and not miss
    return not any(fnmatch.fnmatch(branch, pat) for pat in ignore)


def cli_command(model: str, workspace: str, prompt: str, session_id: str | None, mode: str) -> list[str]:
    """The headless Cursor CLI invocation for one run (https://cursor.com/docs/cli/headless)."""
    cmd = ["agent", "-p", "--force", "--trust", "--workspace", workspace,
           "--output-format", "stream-json", "--model", model]
    if mode == "plan":
        cmd += ["--mode", "plan"]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd + [prompt]


def cli_env(base: dict) -> dict:
    """The implementer's environment: no cluster credentials, no SSH agent, pushes go nowhere."""
    env = {k: v for k, v in base.items() if k not in ("SSH_AUTH_SOCK", "KUBECONFIG", "GH_TOKEN", "GITHUB_TOKEN")}
    env["KUBECONFIG"] = "/dev/null"
    env["PATH"] = os.path.expanduser("~/.local/bin") + os.pathsep + base.get("PATH", "")
    env.update(NO_PUSH_ENV)
    return env


def glm_command(model: str, prompt: str, session_id: str | None, mode: str, settings: str) -> list[str]:
    """The headless Claude Code invocation for one GLM run (https://code.claude.com/docs/en/cli-reference): our
    settings on top of the repository's, and no MCP server at all (--strict-mcp-config without --mcp-config)."""
    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", model,
           "--permission-mode", "plan" if mode == "plan" else "bypassPermissions",
           "--settings", settings, "--strict-mcp-config"]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd + ["--", prompt]


def _glm_file(environ: dict, name: str) -> Path:
    return Path(environ.get("HOME") or os.path.expanduser("~")) / ".config" / "glm" / name


def glm_key(environ: dict) -> str:
    key = (environ.get("GLM_API_KEY") or "").strip()
    path = _glm_file(environ, "coding-plan.key")
    if not key and path.is_file():
        key = path.read_text().strip()
    if not key:
        raise LoopError(f"no GLM Coding Plan key: set $GLM_API_KEY or write it to {path} (mode 600)")
    return key


def glm_base_url(environ: dict) -> str:
    path = _glm_file(environ, "base-url")
    url = (environ.get("GLM_BASE_URL") or (path.read_text().strip() if path.is_file() else "") or GLM_BASE_URLS[0])
    if url not in GLM_BASE_URLS:
        raise LoopError(f"GLM_BASE_URL must be one of the Coding Plan endpoints {GLM_BASE_URLS}, not {url}")
    return url


def glm_env(base: dict, config_dir: str) -> dict:
    """The cli runner's guard rails, without credentials or this session's own Claude settings, on the plan."""
    key, url = glm_key(base), glm_base_url(base)
    env = {k: v for k, v in cli_env(base).items()
           if not k.startswith(("CLAUDE", "ANTHROPIC", "GLM_")) and not SECRET_ENV.search(k)}
    env.update(NO_PUSH_ENV)  # GIT_CONFIG_KEY_0 matches the secret filter; half a guard breaks every git command
    env.update(GLM_ENV)
    env.update({"ANTHROPIC_BASE_URL": url, "ANTHROPIC_AUTH_TOKEN": key, "CLAUDE_CONFIG_DIR": config_dir})
    return env


def glm_config_dir(d: Path) -> Path:
    """Where a GLM run's Claude Code config lives: beside the runs (.keryx/glm/<slug>/), so the deny rules can
    cover every run while the config itself stays readable to the executor that reads its large tool outputs
    back from it — told from the run's folder alone, with no repository around the current directory. A run
    started before 1.2 keeps its config inside its own folder."""
    if d.parent.name == "runs" and d.parent.parent.name == ".keryx":
        return d.parent.parent / "glm" / d.name
    return d / "claude-config"


def write_glm_config(d: Path) -> Path:
    """A config dir of its own (no user memory, skills, hooks, plugins or MCP servers), attribution off, denies."""
    if d.parent.name == "runs" and d.parent.parent.name == ".keryx":
        ensure_ignored(d.parent.parent)  # .keryx/ ignores itself from its first file on
    cfg_dir = glm_config_dir(d)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    settings = {"attribution": {"commit": "", "pr": "", "sessionUrl": False}, "autoMemoryEnabled": False,
                "permissions": {"deny": GLM_DENY}}
    (cfg_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return cfg_dir


# ---------------------------------------------------------------- provider runner (codex exec)


def codex_command(model: str, prompt: str, session_id: str | None, mode: str, effort: str | None) -> list[str]:
    """The `codex exec` invocation for one provider run. Full access, not workspace-write: Codex's sandbox
    refuses writes under .git even with the main .git in writable_roots, so it cannot commit from a linked
    worktree (probed 2026-11-07); plan mode still gets read-only. `resume` takes no -s and no config of its
    own after it, so a resumed turn carries its sandbox as -c sandbox_mode, and a prompt that starts with -
    needs the `--` before it."""
    sandbox = "read-only" if mode == "plan" else "danger-full-access"
    cmd = ["codex", "exec", "--json", "-m", model]
    if effort:
        cmd += ["-c", f'model_reasoning_effort="{effort}"']
    if session_id:
        cmd += ["-c", f'sandbox_mode="{sandbox}"', "resume", session_id]
    else:
        cmd += ["-s", sandbox]
    return cmd + ["--", prompt]


def codex_probe_command(model: str, effort: str | None) -> list[str]:
    """The preflight probe, which runs in a temporary directory that is not a repository. Codex refuses
    that unless `--skip-git-repo-check` is set, and the probe needs no write access, so the sandbox is
    read-only. Executor rounds stay on `codex_command` inside their worktree."""
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-m", model]
    if effort:
        cmd += ["-c", f'model_reasoning_effort="{effort}"']
    return cmd + ["-s", "read-only", "--", "Reply with exactly: KERYX_OK"]


def codex_key_file(provider: dict, environ: dict) -> Path:
    """The provider's key file path, a leading ~ read against the run's HOME."""
    name = str(provider.get("keyFile") or "")
    home = str(environ.get("HOME") or os.path.expanduser("~"))
    return Path(home + name[1:]) if name.startswith("~") else Path(name)


def codex_key(provider: dict, environ: dict) -> str:
    """The provider's key, read from its keyFile (~ is the run's HOME). Never printed or written to disk."""
    path = codex_key_file(provider, environ)
    key = path.read_text().strip() if path.is_file() else ""
    if not key:
        raise LoopError(f"the provider key file {path} is missing or empty; write the key to it (mode 600)")
    return key


def codex_env(base: dict, codex_home: str, key: str) -> dict:
    """The cli runner's guard rails, without credentials or any other runner's settings, with the provider's
    key the only one reaching Codex — through its own CODEX_HOME and env_key. gh gets a placeholder token
    so gh commands fail (an empty GH_CONFIG_DIR is not enough: `gh auth token` still reads the keychain);
    no git credential helper, askpass program, or SSH. The push URL still goes nowhere. These stop mistakes,
    not a determined executor that runs with the owner's rights (keychain, SSH keys). NO_PUSH_ENV itself is
    unchanged (the cli and glm runners keep the one push pair)."""
    env = {k: v for k, v in cli_env(base).items()
           if not k.startswith(("CODEX", "OPENAI", "ANTHROPIC", "CLAUDE")) and not SECRET_ENV.search(k)
           and "ASKPASS" not in k}
    env.update(NO_PUSH_ENV)  # GIT_CONFIG_KEY_0 matches the secret filter; half a guard breaks every git command
    # A second pair after the push block: an empty credential helper, so git cannot use the owner's store.
    env["GIT_CONFIG_COUNT"] = "2"
    env["GIT_CONFIG_KEY_1"] = "credential.helper"
    env["GIT_CONFIG_VALUE_1"] = ""
    env["GIT_SSH_COMMAND"] = "false"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_CONFIG_DIR"] = str(Path(codex_home) / "gh")
    env.pop("GITHUB_TOKEN", None)  # gh prefers GH_TOKEN; a real GITHUB_TOKEN must not survive beside it
    env["GH_TOKEN"] = "keryx-provider-round-has-no-github-access"
    env["CODEX_HOME"] = codex_home
    env[CODEX_KEY_ENV] = key
    return env


def _codex_home_dir(d: Path) -> Path:
    """Where a provider run's Codex config lives: beside the runs (.keryx/codex/<slug>/), like the GLM
    runner's own config dir; a run folder somewhere else keeps it inside itself."""
    if d.parent.name == "runs" and d.parent.parent.name == ".keryx":
        return d.parent.parent / "codex" / d.name
    return d / "codex-home"


def _toml(value) -> str:
    """One TOML scalar: strings quoted (inner quotes and backslashes escaped), numbers and booleans bare."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)


def write_codex_home(d: Path, provider: dict) -> Path:
    """A CODEX_HOME of the run's own: the provider's endpoint behind $KERYX_CODEX_API_KEY, its model and
    effort, approvals off (keryx runs headless) and the key kept out of the executor's shells. No login,
    no MCP servers, no user config, and never the key itself. Rewriting it takes the provider as passed,
    so a follow-up sees a changed endpoint or codexConfig. `gh/` is an empty GH_CONFIG_DIR."""
    if d.parent.name == "runs" and d.parent.parent.name == ".keryx":
        ensure_ignored(d.parent.parent)  # .keryx/ ignores itself from its first file on
    home = _codex_home_dir(d)
    home.mkdir(parents=True, exist_ok=True)
    lines = ['model_provider = "keryx"', f"model = {_toml(provider['model'])}"]
    if provider.get("effort"):
        lines.append(f"model_reasoning_effort = {_toml(provider['effort'])}")
    lines.append('approval_policy = "never"')
    lines += [f"{key} = {_toml(value)}" for key, value in (provider.get("codexConfig") or {}).items()]
    lines += ["", "[model_providers.keryx]", 'name = "keryx"', f"base_url = {_toml(provider['baseUrl'])}",
              f"env_key = {_toml(CODEX_KEY_ENV)}", 'wire_api = "responses"',
              "", "[shell_environment_policy]", f"exclude = [{_toml(CODEX_KEY_ENV)}]"]
    (home / "config.toml").write_text("\n".join(lines) + "\n")
    (home / "gh").mkdir(exist_ok=True)
    return home


# ---------------------------------------------------------------- executor ladder + gates (tested)

# The executors a person may have, in the order to try them: cli = Cursor CLI, glm = GLM Coding Plan,
# cloud = Cursor Cloud Agent, subagent = a Claude subagent the coordinator dispatches itself.
EXECUTORS = ("cli", "glm", "cloud", "subagent")

# Files whose changes are architecture or release gates: the coordinator reviews those itself instead
# of trusting an executor with them. A repository's own guard or boundary tests belong in
# <state>/gates.txt, not here (these must not catch an ordinary source or test file).
DEFAULT_GATE_GLOBS = [
    "**/.importlinter", "**/.dependency-cruiser*", "**/*architecture*test*", "**/test_*architecture*",
    "**/*archunit*", ".github/workflows/**", "**/eslint.config.*", "**/.eslintrc*",
    "**/deny.toml", "**/clippy.toml",
]

# The reviewer's bar ships as files: the brief template, and where a repository keeps its architecture rules.
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
RULE_FILES = ("CLAUDE.md", "AGENTS.md", "ARCHITECTURE.md", "docs/adr", "docs/decisions", "doc/adr", "adr")


def config_path(environ: dict) -> Path:
    """Where the ladder is saved: $KERYX_CONFIG, else the XDG config home, else ~/.config."""
    if environ.get("KERYX_CONFIG"):
        return Path(environ["KERYX_CONFIG"])
    if environ.get("XDG_CONFIG_HOME"):
        return Path(environ["XDG_CONFIG_HOME"]) / "keryx" / "config.json"
    return Path(environ.get("HOME") or os.path.expanduser("~")) / ".config" / "keryx" / "config.json"


# Z.ai: [1308][Usage limit reached for 5 hour. Your limit will reset at …] and
# [1310][Weekly/Monthly Limit Exhausted. Your limit will reset at …] (both seen in the field).
GLM_LIMIT = re.compile(r"\[13\d\d\]\[(?:Usage limit reached for (?P<kind>[^.\]]+?)|(?P<span>\w+(?:/\w+)*) Limit Exhausted)\. "
                       r"Your limit will reset at (?P<at>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
CURSOR_LIMIT = re.compile(r"(?P<kind>\w+) usage limit reached\. It resets in (?P<span>[^.]+?)\.", re.I)
GLM_UTC_OFFSET = dt.timedelta(hours=8)  # Z.ai prints its reset time in UTC+8, no DST
# A provider endpoint behind `codex exec`: an allowance spent answers HTTP 402 (Mistral's monthly Vibe
# Code allowance with pay-as-you-go off) and a rate limit answers 429. Codex prints one of three shapes,
# and only these: "unexpected status 402", "last status: 402" once retries are spent, or
# "raw_status_code":402. The same three for 429. A looser "status 402" would match another runner's words.
CODEX_ALLOWANCE = re.compile(r'unexpected status 402\b|last status: 402\b|"raw_status_code":402\b')
CODEX_RATE = re.compile(r'unexpected status 429\b|last status: 429\b|"raw_status_code":429\b')


def _first_of_next_month(at: dt.datetime) -> dt.datetime:
    """00:00:00 UTC on the first day of the month after `at`: a monthly allowance resets then."""
    moment = _as_utc(at)
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    return dt.datetime(year, month, 1, tzinfo=dt.timezone.utc)


def usage_limit(text: str, at: dt.datetime | None = None, codex: bool = True) -> dict | None:
    """Read a usage-limit message a run already printed: {"kind", "resetsAt", "resetsIn"}, else None.

    Never probes anything. GLM (Z.ai) and Cursor messages count for every runner. A codex provider's
    HTTP 402 and 429 count only when `codex` is set, which is a codex round's own report: another
    runner's words can contain the same text. A 402 lasts until the first of the next month after `at`
    (now UTC); a 429 lasts ten minutes. 401 and 400 are not limits."""
    m = GLM_LIMIT.search(text or "")
    if m:
        local = dt.datetime.strptime(m.group("at"), "%Y-%m-%d %H:%M:%S")
        return {"kind": m.group("kind") or m.group("span").lower(),
                "resetsAt": (local - GLM_UTC_OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "resetsIn": None}
    m = CURSOR_LIMIT.search(text or "")
    if m:
        return {"kind": m.group("kind").lower(), "resetsAt": None, "resetsIn": m.group("span")}
    if not codex:
        return None
    body = text or ""
    if CODEX_ALLOWANCE.search(body):
        moment = at or dt.datetime.now(dt.timezone.utc)
        return {"kind": "allowance", "resetsAt": _stamp(_first_of_next_month(moment)), "resetsIn": None}
    if CODEX_RATE.search(body):
        return {"kind": "rate", "resetsAt": None, "resetsIn": "10 minutes"}
    return None


def _round_is_codex(r: Path) -> bool:
    """True when the run that owns this round folder was started on a codex provider."""
    try:
        agent = json.loads((r.parent.parent / "agent.json").read_text())
    except (OSError, ValueError):
        return False
    return isinstance(agent, dict) and agent.get("runnerKind") == "codex"


def round_usage_limit(r: Path) -> dict | None:
    """The usage limit a finished round ran into, from its own report (result.md, stderr.log) only: the event
    log can quote a limit message from a file the executor read. Codex's 402 and 429 wording counts only
    for a round whose runnerKind is codex."""
    codex = _round_is_codex(r)
    texts = []
    for name in ("result.md", "stderr.log"):
        if (r / name).exists():
            texts.append((r / name).read_text(errors="replace"))
    for text in texts:
        found = usage_limit(text, codex=codex)
        if found:
            return found
    return None


def report_usage_limit(d: Path, r: Path, limit: dict) -> None:
    when = f"resets at {limit['resetsAt']}" if limit.get("resetsAt") else f"resets in {limit['resetsIn']}"
    print(f"USAGE_LIMIT  {limit['kind']} limit; {when}")
    print("      reset within ~45 min: wait, then followup on this slug (or create on it again if followup finds "
          "no session); later: the next rung (keryx.py executors --after RUNNER; inline means you)")
    append_log(d, "dispatch", f"round {r.name}: usage limit ({limit['kind']})", "the executor reported its limit",
               f"{r / 'result.md'}", when)
    runner = load_agent(d).get("runner")
    if isinstance(runner, str) and runner:
        # The same limit applies to every session on this machine, not only this round's run.json.
        # A limits file that cannot be written must not take down wait or status: the round already ended.
        try:
            until = record_limit(dict(os.environ), runner, limit, dt.datetime.now(dt.timezone.utc))
        except OSError as exc:
            print(f"could not record the limit for {runner}: {exc.strerror or exc}")
        else:
            if until:
                print(f"recorded   {runner} is left out of keryx.py executors until {until}")


SETUP_NOTE = ("keryx is not set up on this machine: run `keryx.py setup --detect`, then ask the owner "
              "which executors to use, in which order")


def setup_note(environ: dict) -> str | None:
    """A one-line note while no executor ladder has been saved; None once it exists."""
    return None if config_path(environ).exists() else SETUP_NOTE


def looks_secret(text: str) -> bool:
    """True for a credential-looking NAME=value pair, a known token prefix, or a long opaque run."""
    for m in re.finditer(r"([A-Za-z_][\w.-]*)\s*[=:]\s*(\S+)", text):
        if SECRET_ENV.search(m.group(1)):
            return True
    if re.search(r"(?:ghp_|github_pat_|sk-|xox|AKIA|glpat-)[A-Za-z0-9_-]{16,}", text):
        return True
    return re.search(r"[A-Za-z0-9]{32,}", text) is not None


def memory_file(scope: str, environ: dict) -> Path | None:
    if scope == "user":
        return config_path(environ).parent / "memory.md"
    try:
        return main_worktree() / ".keryx" / "memory.md"
    except LoopError:
        return None


def legacy_memory_file() -> Path | None:
    """The repository's memory as a pre-1.2 run left it, under the git common dir; None outside a repository."""
    try:
        return legacy_root() / "memory.md"
    except LoopError:
        return None


def parse_executors(text: str, providers=()) -> list[str]:
    """Comma-separated executor names: whitespace stripped, duplicates dropped keeping the first. A provider
    declared in `providers` (the config's name -> entry mapping, or the names alone) is an executor; bare
    `codex` never is: a provider has a name of its own."""
    declared = list(providers)  # a dict yields its names, the config view yields the same
    out: list[str] = []
    for name in (part.strip() for part in text.split(",")):
        if not name:
            continue
        if name not in EXECUTORS and name not in declared:
            choose = ", ".join(EXECUTORS + tuple(declared))
            raise LoopError(f"unknown executor {name!r}; choose from {choose}")
        if name not in out:
            out.append(name)
    if not out:
        raise LoopError("no executors in the list")
    return out


_ORDERS = ("ladder", "resets")
_RESET_EVERY = ("month", "week")
# A date alone is midnight UTC. Anything else, including a time with no Z, is not a reset.
_RESET_NEXT = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})Z)?$")


def _parse_next(value: object) -> dt.datetime | None:
    """YYYY-MM-DD (midnight UTC) or YYYY-MM-DDTHH:MM:SSZ. None when it is neither, or not a real date."""
    if not isinstance(value, str):
        return None
    match = _RESET_NEXT.fullmatch(value)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        return dt.datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0),
                           int(second or 0), tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _validated_resets(path: Path, resets: object, providers=()) -> dict:
    """`resets` as saved. Every refusal names `path` first. `every` absent or null is a one-off."""
    if not isinstance(resets, dict):
        raise LoopError(f'{path}: "resets" must be an object')
    for name, spec in resets.items():
        if name not in EXECUTORS and name not in providers:
            raise LoopError(f"{path}: unknown executor {name!r} in resets")
        if not isinstance(spec, dict):
            raise LoopError(f"{path}: reset for {name} must be an object")
        if _parse_next(spec.get("next")) is None:
            raise LoopError(f"{path}: reset for {name} needs next as YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ")
        if "every" in spec and spec.get("every") is not None and spec.get("every") not in _RESET_EVERY:
            raise LoopError(f"{path}: reset for {name} every must be month or week")
    return resets


def _validated_providers(path: Path, providers: object) -> dict:
    """`providers` as saved: name -> a normalised entry (runner, baseUrl, keyFile, model, effort?,
    codexConfig?). Every refusal names `path` first. A provider names a key file, never a key."""
    if not isinstance(providers, dict):
        raise LoopError(f'{path}: "providers" must be an object')
    out: dict[str, dict] = {}
    for name, spec in providers.items():
        if name in EXECUTORS or not PROVIDER_NAME.fullmatch(name):
            raise LoopError(f"{path}: provider name {name!r} must be 2-31 characters of lowercase letters, "
                            f"digits and dashes, and not a built-in executor ({', '.join(EXECUTORS)})")
        where = f"{path}: provider {name}"
        if not isinstance(spec, dict):
            raise LoopError(f"{where} must be an object")
        if spec.get("runner") not in PROVIDER_RUNNERS:
            raise LoopError(f'{where} "runner" must be one of: {", ".join(PROVIDER_RUNNERS)}')
        if "key" in spec:
            raise LoopError(f'{where} names a key file (keyFile), never a key ("key")')
        if not isinstance(spec.get("baseUrl"), str) or not spec["baseUrl"].startswith("https://"):
            raise LoopError(f'{where} "baseUrl" must be an https:// URL')
        if not isinstance(spec.get("keyFile"), str) or not spec["keyFile"].strip():
            raise LoopError(f'{where} needs "keyFile" as a path holding the API key')
        if not isinstance(spec.get("model"), str) or not spec["model"].strip():
            raise LoopError(f'{where} needs "model" as the model id to run')
        if spec.get("effort") is not None and not isinstance(spec["effort"], str):
            raise LoopError(f'{where} "effort" must be a string (the model\'s reasoning effort)')
        config = spec.get("codexConfig")
        if config is not None:
            if not isinstance(config, dict):
                raise LoopError(f'{where} "codexConfig" must be an object of Codex settings')
            for key, value in config.items():
                if key in CODEX_OWNED_CONFIG:
                    raise LoopError(f'{where} "codexConfig" may not set {key} (keryx owns it)')
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
                    raise LoopError(f"{where} codexConfig setting {key!r} is not a plain setting name")
                if not isinstance(value, (str, int, float, bool)):
                    raise LoopError(f"{where} codexConfig setting {key!r} needs a string, number or boolean value")
        entry = {"runner": spec["runner"], "baseUrl": spec["baseUrl"], "keyFile": spec["keyFile"],
                 "model": spec["model"]}
        if spec.get("effort") is not None:
            entry["effort"] = spec["effort"]
        if config is not None:
            entry["codexConfig"] = config
        out[name] = entry
    return out


def _config_view(path: Path, data: object) -> dict:
    """executors, order, resets, providers, caps and roots. Unknown keys are ignored. Every refusal names
    `path` first.

    While the order is `ladder` a bad `resets` is read as none, so the dates can never break the saved order;
    in the `resets` order it is refused."""
    if not isinstance(data, dict):
        raise LoopError(f'{path}: "executors" must be a list of names')
    names = data.get("executors")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise LoopError(f'{path}: "executors" must be a list of names')
    providers = _validated_providers(path, data.get("providers", {}))
    try:
        ladder = parse_executors(",".join(names), providers)
    except LoopError as exc:
        raise LoopError(f"{path}: {exc}") from exc
    order = data.get("order", "ladder")
    if order not in _ORDERS:
        raise LoopError(f"{path}: unknown order {order!r}; choose from {', '.join(_ORDERS)}")
    try:
        resets = _validated_resets(path, data.get("resets", {}), providers)
    except LoopError:
        if order == "resets":
            raise
        resets = {}
    caps = data.get("maxParallel", {})
    if not isinstance(caps, dict) or not all(isinstance(name, str) and name
                                             and isinstance(value, int) and not isinstance(value, bool)
                                             and value >= 1 for name, value in caps.items()):
        raise LoopError(f'{path}: "maxParallel" must map each runner to a whole number of at least 1')
    roots = data.get("roots", [])
    if not isinstance(roots, list) or not all(isinstance(root, str) for root in roots):
        raise LoopError(f'{path}: "roots" must be a list of folders that hold repositories')
    return {"executors": ladder, "order": order, "resets": resets, "providers": providers,
            "maxParallel": caps, "roots": roots}


def load_config(environ: dict) -> dict:
    """The saved ladder, or the Claude subagent alone when it was never saved.

    `order` is `ladder` (the saved order) unless the file says `resets`. `resets` is read either way
    and changes the order only when `order` is `resets`. `providers` is the declared provider runners,
    an empty mapping when none are declared."""
    path = config_path(environ)
    if not path.exists():
        return {"executors": ["subagent"], "order": "ladder", "resets": {}, "providers": {},
                "maxParallel": {}, "roots": []}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise LoopError(f"{path} is not valid JSON: {exc}") from exc
    return _config_view(path, data)


def _add_months(anchor: dt.datetime, k: int) -> dt.datetime:
    """`anchor` plus `k` calendar months. The day is `anchor`'s own day, clamped to that month's end."""
    index = (anchor.month - 1) + k
    year = anchor.year + index // 12
    month = index % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def _month_after(anchor: dt.datetime, at: dt.datetime) -> dt.datetime:
    """The monthly reset strictly after `at`. `k` is the month distance, not a step per month."""
    k = (at.year - anchor.year) * 12 + (at.month - anchor.month)
    if k < 0:
        k = 0
    when = _add_months(anchor, k)
    if when <= at:
        when = _add_months(anchor, k + 1)
    return when


def next_reset(spec: dict, at: dt.datetime) -> str | None:
    """The first reset strictly after `at`, as YYYY-MM-DDTHH:MM:SSZ.

    `week` adds 7 days and `month` adds calendar months, both counted from `next` itself
    (31 January, then 28 February, then 31 March). A one-off at or before `at` is None.
    A naive `at` is UTC, the same as a stamp with no zone. `k` is arithmetic, so an old `next`
    does not walk one period at a time."""
    if not isinstance(spec, dict):
        return None
    anchor = _parse_next(spec.get("next"))
    if anchor is None:
        return None
    moment = _as_utc(at)
    every = spec.get("every")
    if anchor > moment:
        when = anchor  # the next reset as saved: never counted back from it
    elif every == "week":
        elapsed = moment - anchor
        period = 7 * 86400 * 1_000_000
        microseconds = (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
        when = anchor + dt.timedelta(days=7 * (microseconds // period + 1))
    elif every == "month":
        when = _month_after(anchor, moment)
    else:
        return None  # a one-off reset that has passed
    return _stamp(when)


def ordered_ladder(config: dict, at: dt.datetime) -> list[str]:
    """Who to try, in order. `ladder` is the saved order. `resets` puts soonest-reset first.

    Executors with no reset still to come follow, in the saved order. A tie keeps the saved order.
    Nothing is removed for a usage limit."""
    ladder = list(config["executors"])
    if config.get("order", "ladder") != "resets":
        return ladder
    resets = config.get("resets") if isinstance(config.get("resets"), dict) else {}
    ranked: list[tuple[str, int, str]] = []
    rest: list[str] = []
    for index, name in enumerate(ladder):
        spec = resets.get(name)
        when = next_reset(spec, at) if isinstance(spec, dict) else None
        if when is None:
            rest.append(name)
        else:
            ranked.append((when, index, name))
    ranked.sort()
    return [name for _, _, name in ranked] + rest


def next_executor(ladder: list[str], current: str) -> str:
    """The executor to try after `current`: the next rung, the first rung for a runner outside the
    ladder, and "inline" (the coordinator writes the code itself) after the last."""
    if current not in ladder:
        return ladder[0]
    rest = ladder[ladder.index(current) + 1:]
    return rest[0] if rest else "inline"


# <n> minute(s) | hour(s) | day(s) | week(s). "an hour" and "soon" are not a time.
_LIMIT_SPAN = re.compile(r"(\d+)\s+(minute|hour|day|week)s?", re.IGNORECASE)
_LIMIT_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _limits_path(environ: dict) -> Path:
    """Machine-wide usage limits, beside the ladder: <config dir>/limits.json."""
    return config_path(environ).parent / "limits.json"


def _as_utc(at: dt.datetime) -> dt.datetime:
    if at.tzinfo is None:
        return at.replace(tzinfo=dt.timezone.utc)
    return at.astimezone(dt.timezone.utc)


def _stamp(at: dt.datetime) -> str:
    return _as_utc(at).strftime(_LIMIT_STAMP)


def _parse_stamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.strptime(value, _LIMIT_STAMP).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _until_from_limit(limit: dict, at: dt.datetime) -> str | None:
    """The reset time: resetsAt when it is set, otherwise a span added to `at`. Anything else is None."""
    if not isinstance(limit, dict):
        return None
    resets_at = limit.get("resetsAt")
    if isinstance(resets_at, str) and resets_at.strip():
        return resets_at
    span = limit.get("resetsIn")
    if not isinstance(span, str):
        return None
    match = _LIMIT_SPAN.fullmatch(span.strip())
    if not match:
        return None
    count = int(match.group(1))
    unit = match.group(2).lower()
    delta = {
        "minute": dt.timedelta(minutes=count),
        "hour": dt.timedelta(hours=count),
        "day": dt.timedelta(days=count),
        "week": dt.timedelta(weeks=count),
    }.get(unit)
    if delta is None:
        return None
    try:
        return _stamp(at + delta)
    except (OverflowError, ValueError):
        return None


def _read_limits(path: Path) -> dict:
    """The limits file, or {} when it is missing, unreadable, or not a JSON object. Never raises."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _kept_limit(entry: object) -> dict | None:
    """kind, until and recorded — the only fields a limits file may hold. A bad entry is no limit."""
    if not isinstance(entry, dict):
        return None
    until = entry.get("until")
    if _parse_stamp(until) is None or not isinstance(until, str) or looks_secret(until):
        return None
    kept: dict[str, str] = {"until": until}
    for key in ("kind", "recorded"):
        value = entry.get(key)
        if isinstance(value, str) and value and not looks_secret(value):
            kept[key] = value
    return kept


def _write_limits(path: Path, data: dict) -> None:
    """Publish limits.json by replacing it: a reader sees the old file or the new one, never a torn write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".limits-", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _saved_limits(path: Path) -> dict[str, dict]:
    current: dict[str, dict] = {}
    for name, entry in _read_limits(path).items():
        if not isinstance(name, str) or looks_secret(name):
            continue
        kept = _kept_limit(entry)
        if kept is not None:
            current[name] = kept
    return current


def _store_limit(path: Path, runner: str, kind: str, until: str, at: dt.datetime) -> str | None:
    """Save `runner`'s record. A reset that is already past does not replace one that is still live."""
    current = _saved_limits(path)
    existing = current.get(runner)
    moment = _as_utc(at)
    old_until = _parse_stamp(existing.get("until")) if existing else None
    new_until = _parse_stamp(until)
    if old_until is not None and old_until > moment and (new_until is None or new_until <= moment):
        return None
    current[runner] = {"kind": kind, "until": until, "recorded": _stamp(at)}
    _write_limits(path, current)
    return until


def record_limit(environ: dict, runner: str, limit: dict, at: dt.datetime) -> str | None:
    """Remember `runner`'s usage limit until it resets.

    Returns the "until" time, or None when the reset cannot be read or a still-live record is left
    as it is (and then nothing is written). The first record is saved whatever its time. A reset
    that is still ahead replaces the runner's old one. Two sessions can record at once: the write
    is a temp file in the same folder plus os.replace, and where fcntl exists a lock so one record
    does not erase the other. The file holds runner names, kinds and times only."""
    until = _until_from_limit(limit, at)
    if until is None or not isinstance(runner, str) or not runner:
        return None
    kind = limit.get("kind") if isinstance(limit, dict) else None
    kind = kind if isinstance(kind, str) else ""
    if looks_secret(runner) or looks_secret(kind) or looks_secret(until):
        return None
    path = _limits_path(environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    # fcntl is Unix-only. Without it the replace is still atomic; two writers can only lose an update.
    try:
        import fcntl
    except ImportError:
        return _store_limit(path, runner, kind, until, at)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _store_limit(path, runner, kind, until, at)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def limited_runners(environ: dict, at: dt.datetime) -> dict[str, str]:
    """Runners whose limit resets after `at`, mapped to that time. A missing, unreadable or
    malformed file, or a malformed entry, is no limit — this never raises."""
    try:
        moment = _as_utc(at)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return {}
    found: dict[str, str] = {}
    for name, entry in _read_limits(_limits_path(environ)).items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        until = entry.get("until")
        parsed = _parse_stamp(until)
        if parsed is not None and parsed > moment:
            found[name] = until
    return found


def available_ladder(ladder: list[str], environ: dict, at: dt.datetime) -> list[str]:
    """`ladder` in order, without the runners that are at a usage limit right now."""
    limited = limited_runners(environ, at)
    return [name for name in ladder if name not in limited]


def _executor_after(ladder: list[str], current: str, environ: dict, at: dt.datetime) -> str:
    """The first runner after `current` that is not at its limit. A runner outside the ladder
    starts at the first available one; "inline" when none remain."""
    limited = limited_runners(environ, at)
    start = ladder.index(current) + 1 if current in ladder else 0
    for name in ladder[start:]:
        if name not in limited:
            return name
    return "inline"


def _refuse_limited_runner(config: dict, runner: str, environ: dict) -> None:
    at = dt.datetime.now(dt.timezone.utc)
    until = limited_runners(environ, at).get(runner)
    if until is None:
        return
    next_rung = _executor_after(config["executors"], runner, environ, at)
    raise LoopError(f"{runner} is at its usage limit until {until}; next rung: {next_rung}")


def _running_round_count(config: dict, runner: str) -> int:
    roots = [state_root()]
    for root in config.get("roots", []):
        folder = Path(root)
        if not folder.is_dir():
            continue
        roots.extend(child / ".keryx" / "runs" for child in folder.iterdir()
                     if (child / ".keryx" / "runs").is_dir())
    counted = 0
    seen = set()
    for runs in roots:
        resolved = runs.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        for d in runs.iterdir():
            if not d.is_dir():
                continue
            try:
                agent = json.loads((d / "agent.json").read_text())
            except (OSError, ValueError):
                agent = {}
            for r in rounds(d):
                try:
                    run = json.loads((r / "run.json").read_text())
                except (OSError, ValueError):
                    continue
                pid = run.get("pid")
                round_runner = run.get("runner") or (agent.get("runner") if isinstance(agent, dict) else None)
                if (run.get("status") == "RUNNING" and round_runner == runner
                        and isinstance(pid, int) and pid_alive(pid)):
                    counted += 1
    return counted


def _refuse_parallel_cap(config: dict, runner: str, environ: dict) -> None:
    cap = config.get("maxParallel", {}).get(runner)
    if cap is None:
        return
    count = _running_round_count(config, runner)
    if count < cap:
        return
    at = dt.datetime.now(dt.timezone.utc)
    next_rung = _executor_after(config["executors"], runner, environ, at)
    plural = "s" if count != 1 else ""
    raise LoopError(f"maxParallel: {runner} already has {count} round{plural} running; next rung: {next_rung}")


def _refuse_busy_runner(config: dict, runner: str, environ: dict, ignore_limit: bool) -> None:
    if ignore_limit:
        return
    _refuse_limited_runner(config, runner, environ)
    _refuse_parallel_cap(config, runner, environ)


def can_switch(status) -> bool:
    """Only a failed run may hand its slug to the next executor; a live or finished one keeps it."""
    return status in ("ERROR", "STALLED", "EXPIRED", "CANCELLED")


def gate_hits(paths: list[str], globs: list[str]) -> list[str]:
    """The paths that touch a gate file, in input order without duplicates. Matching ignores case;
    a leading **/ glob with no other slash matches the file name only (a folder named like a gate
    never counts); any other glob matches the whole path, where a leading **/ also matches at the
    repository root."""
    name_pats, path_pats = [], []
    for g in globs:
        if g.startswith("**/") and "/" not in g[3:]:
            name_pats.append(g[3:])
        else:
            path_pats.append(g)
            if g.startswith("**/"):
                path_pats.append(g[3:])
    hits, seen = [], set()
    for p in paths:
        name = p.rsplit("/", 1)[-1]
        if p not in seen and (any(fnmatch.fnmatch(name.lower(), pat.lower()) for pat in name_pats)
                              or any(fnmatch.fnmatch(p.lower(), pat.lower()) for pat in path_pats)):
            seen.add(p)
            hits.append(p)
    return hits


def tool_calls(event: dict) -> list[tuple[str, str, str]]:
    """("start" | "end", call id, command) for each tool call an event opens or closes: Cursor sends tool_call
    events; Claude Code puts tool_use parts in assistant messages and tool_result parts in user messages;
    Codex opens a command_execution item on item.started and closes it on item.completed."""
    kind = event.get("type")
    if kind in ("item.started", "item.completed"):
        item = event.get("item") or {}
        if item.get("type") != "command_execution":
            return []
        if kind == "item.started":
            return [("start", item.get("id"), str(item.get("command") or "command_execution"))]
        return [("end", item.get("id"), "")]
    if kind == "tool_call":
        if event.get("subtype") != "started":
            return [("end", event.get("call_id"), "")]
        call_ = event.get("tool_call") or {}
        shell = (call_.get("shellToolCall") or {}).get("args") or {}
        return [("start", event.get("call_id"), str(shell.get("command") or next(iter(call_), "tool")))]
    content = (event.get("message") or {}).get("content") if kind in ("assistant", "user") else None
    out = []
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and part.get("type") == "tool_use":
            inp = part.get("input") or {}
            out.append(("start", part.get("id"), str(inp.get("command") or inp.get("file_path") or part.get("name"))))
        elif isinstance(part, dict) and part.get("type") == "tool_result":
            out.append(("end", part.get("tool_use_id"), ""))
    return out


def cli_summary(event: dict) -> str | None:
    """One progress line for a CLI stream-json event (https://cursor.com/docs/cli/reference/output-format),
    or for a `codex exec --json` event: init with the thread id, a tool line per command_execution item and
    a result line for the turn."""
    kind = event.get("type")
    if kind == "thread.started":
        return f"init  thread={event.get('thread_id')}"
    if kind == "item.started":
        item = event.get("item") or {}
        if item.get("type") == "command_execution":
            return f"tool  shell {str(item.get('command') or '')[:140]}".rstrip()
        return None
    if kind == "turn.completed":
        return "result completed"
    if kind == "turn.failed":
        message = str((event.get("error") or {}).get("message") or "")
        return f"result failed {message[:140]}".rstrip()
    if kind == "system" and event.get("subtype") == "init":
        return f"init  model={event.get('model')} session={event.get('session_id')}"
    if kind == "tool_call" and event.get("subtype") == "started":
        call_ = event.get("tool_call") or {}
        # The call sits under a key such as "shellToolCall" next to bookkeeping keys
        # (e.g. "hookAdditionalContexts"); the one carrying "args" is the call.
        name = next((k for k, v in call_.items() if isinstance(v, dict) and "args" in v), None)
        args = call_[name]["args"] if name else None
        if name is None and isinstance(call_.get("function"), dict):
            name, args = call_["function"].get("name", "?"), call_["function"].get("arguments")
        name = name or "?"
        detail = ""
        if isinstance(args, dict):
            detail = args.get("command") or args.get("path") or args.get("pattern") or ""
        return f"tool  {name} {str(detail)[:140]}".rstrip()
    if kind == "assistant":  # Claude Code: tool calls sit in the assistant message's content
        for part in (event.get("message") or {}).get("content", []) or []:
            if isinstance(part, dict) and part.get("type") == "tool_use":
                inp = part.get("input") or {}
                detail = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
                return f"tool  {part.get('name')} {str(detail)[:140]}".rstrip()
    if kind == "result":
        return f"result {event.get('subtype')} error={event.get('is_error')} in {event.get('duration_ms')} ms"
    return None


def cli_outcome(events: list[dict], exit_code: int | None) -> dict:
    """Status, session and final text of a finished CLI run, from its stream-json events."""
    session = next((e.get("session_id") for e in events if e.get("session_id")), None)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is not None and not result.get("is_error") and exit_code == 0:
        status = "FINISHED"
    elif exit_code is None:
        status = "RUNNING"
    elif exit_code < 0 or exit_code in (130, 137, 143):
        status = "CANCELLED"
    else:
        status = "ERROR"
    text = (result or {}).get("result") or ""
    if not text:
        text = "".join(
            part.get("text", "")
            for e in events if e.get("type") == "assistant"
            for part in (e.get("message") or {}).get("content", []) if isinstance(part, dict)
        )
    elif not re.search(r"(?m)^Status:", text):
        # A run woken again after its report (a background task ending) ends on a short aside, which may name the
        # status mid-sentence: only a line that starts with it is the report.
        reports = [e.get("result") or "" for e in events if e.get("type") == "result"]
        report = next((r for r in reversed(reports) if re.search(r"(?m)^Status:", r)), None)
        if report:
            text = report + "\n\n---\nLast message:\n" + text
    return {"status": status, "session_id": session, "result": text,
            "durationMs": (result or {}).get("duration_ms"), "exit": exit_code}


def _codex_error_message(event: dict) -> str:
    """A Codex error event's message: top-level `message`, or `error.message`."""
    return str(event.get("message") or (event.get("error") or {}).get("message") or "")


def _codex_agent_text(events: list[dict]) -> str:
    """The last agent_message text in a Codex event stream."""
    return next((str((e.get("item") or {}).get("text"))
                 for e in reversed(events)
                 if e.get("type") in ("item.started", "item.completed")
                 and (e.get("item") or {}).get("type") == "agent_message"
                 and (e.get("item") or {}).get("text")), "")


def _codex_failure_text(events: list[dict], failed: dict | None) -> str:
    """A failed turn's own error. Codex's `Reconnecting...` lines are retries, not the failure."""
    if failed is not None:
        message = _codex_error_message(failed)
        if message:
            return message
    for event in reversed(events):
        if event.get("type") != "error":
            continue
        message = _codex_error_message(event)
        if message and not message.startswith("Reconnecting..."):
            return message
    return ""


def codex_outcome(events: list[dict], exit_code: int | None) -> dict:
    """Status, thread and final text of a finished `codex exec` run, from its --json events, in the
    cli_outcome shape. The result is the last agent_message. Only an ERROR turn replaces that with its
    own failure (a `turn.failed` message, else a top-level error that is not a `Reconnecting...` retry),
    so a cancelled or stopped round keeps the executor's report and a real limit still reaches result.md."""
    session = next((e.get("thread_id") for e in events if e.get("thread_id")), None)
    failed = next((e for e in reversed(events) if e.get("type") == "turn.failed"), None)
    completed = any(e.get("type") == "turn.completed" for e in events)
    if completed and failed is None and exit_code == 0:
        status = "FINISHED"
    elif exit_code is None:
        status = "RUNNING"
    elif exit_code < 0 or exit_code in (130, 137, 143):
        status = "CANCELLED"
    else:
        status = "ERROR"
    text = _codex_agent_text(events)
    if status == "ERROR":
        failure = _codex_failure_text(events, failed)
        if failure:
            text = failure
    return {"status": status, "session_id": session, "result": text, "durationMs": None, "exit": exit_code}


# ---------------------------------------------------------------- cli runner


def worktree_path(slug: str, runner: str = "cli") -> Path:
    """A local runner's worktree: .worktrees/<prefix>-<slug>. A provider is its own prefix (mistral-vibe-<slug>)."""
    return main_worktree() / ".worktrees" / f"{WORKTREE_PREFIX.get(runner, runner)}-{slug}"


def ensure_excluded(pattern: str) -> None:
    exclude = common_dir() / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    if pattern not in lines:
        with exclude.open("a") as fh:
            fh.write(("\n" if lines and lines[-1] else "") + pattern + "\n")


ATTRIBUTION_TRAILER = re.compile(
    r"(?im)^(co-authored-by:[^\n]*(cursor|claude|anthropic|glm|z\.ai|zhipu|codex|openai|mistral)[^\n]*"
    r"|made with cursor[^\n]*|\W*generated with \[?claude code[^\n]*)\n?")


def write_cli_config(d: Path) -> Path:
    """A per-loop copy of the global CLI config with commit and PR attribution off.

    Attribution is a global-only CLI setting (https://cursor.com/docs/cli/reference/configuration);
    CURSOR_CONFIG_DIR points one run at another config dir, and the login is unaffected (checked
    2026-10-23: no `Co-authored-by: Cursor` trailer with the override, the trailer without it)."""
    src = Path(os.path.expanduser("~/.cursor/cli-config.json"))
    data = json.loads(src.read_text()) if src.exists() else {}
    data["attribution"] = {"attributeCommitsToAgent": False, "attributePRsToAgent": False}
    perms = data.setdefault("permissions", {})
    perms.setdefault("allow", [])
    perms["deny"] = sorted(set(perms.get("deny", [])) | set(CLI_DENY))
    cfg_dir = d / "cursor-config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "cli-config.json").write_text(json.dumps(data, indent=2) + "\n")
    return cfg_dir


def strip_attribution(message: str) -> str:
    """A commit message without an assistant's attribution lines, keeping one trailing newline."""
    return re.sub(r"\n{3,}", "\n\n", ATTRIBUTION_TRAILER.sub("", message)).rstrip() + "\n"


def write_cli_permissions(workspace: Path) -> None:
    """The workspace's own CLI config: the always-denied commands, and the runs' QA evidence and reproductions
    and the repository's memory under the main checkout — they can show real people, and the CLI's deny takes
    absolute paths."""
    cfg = workspace / ".cursor" / "cli.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(cfg.read_text()) if cfg.exists() else {}
    perms = data.setdefault("permissions", {})
    perms.setdefault("allow", [])
    runs = state_root()
    perms["deny"] = sorted(set(perms.get("deny", [])) | set(CLI_DENY) | {
        f"Read({runs}/*/qa/**)", f"Read({runs}/*/repro/**)", f"Read({runs.parent}/memory.md)"})
    cfg.write_text(json.dumps(data, indent=2) + "\n")
    ensure_excluded("/.cursor/cli.json")


def disable_mcp(workspace: str) -> list[str]:
    """Turns off, for the executor's workspace only, every MCP server the owner configured: an executor gets
    the repository and its tools, never the owner's databases or accounts (seen: each run started a Postgres
    MCP server). The CLI keeps this per workspace in ~/.cursor/projects/<workspace path>/mcp-disabled.json
    (found by test, 2026-10-25: the docs name no file), so the owner's own editor and sessions are untouched."""
    names: set[str] = set()
    for config in (Path(os.path.expanduser("~/.cursor/mcp.json")), Path(workspace) / ".cursor" / "mcp.json"):
        if config.is_file():
            try:
                names |= set((json.loads(config.read_text()).get("mcpServers") or {}).keys())
            except (ValueError, AttributeError):
                continue
    project = Path(os.path.expanduser("~/.cursor/projects")) / re.sub(
        r"[^A-Za-z0-9]+", "-", os.path.realpath(workspace)).strip("-")
    target = project / "mcp-disabled.json"
    if target.is_file():
        try:
            names |= set(json.loads(target.read_text()))
        except ValueError:
            pass
    project.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sorted(names), indent=2) + "\n")
    return sorted(names)


def _codex_provider(agent: dict, environ: dict) -> dict:
    """The declared provider a codex round runs on, re-read at every launch (a follow-up picks up a rotated
    key file or endpoint); the runner names it and runnerKind says codex."""
    providers = load_config(environ).get("providers") or {}
    provider = providers.get(agent.get("runner"))
    if not provider:
        raise LoopError(f"provider {agent.get('runner')!r} is not declared in {config_path(environ)} anymore; "
                        "add it back, or switch the slug to another executor")
    return provider


def cli_launch(d: Path, r: Path, agent: dict, prompt: str, mode: str) -> int:
    if agent.get("runnerKind") in PROVIDER_RUNNERS:
        environ = dict(os.environ)
        provider = _codex_provider(agent, environ)
        # create and followup both launch here, so a changed baseUrl or codexConfig is written first.
        home = write_codex_home(d, provider)
        agent["configDir"] = str(home)
        cmd = codex_command(agent["model"], prompt, agent.get("sessionId"), mode, provider.get("effort"))
        env = codex_env(environ, str(home), codex_key(provider, environ))
        env.update(agent.get("env") or {})
        return _spawn(r, agent, cmd, env, mode, "none (own CODEX_HOME)")
    if agent.get("runner") == "glm":
        settings = str(Path(agent["configDir"]) / "settings.json")
        cmd = glm_command(agent["model"], prompt, agent.get("sessionId"), mode, settings)
        env = glm_env(dict(os.environ), agent["configDir"])
        env.update(agent.get("env") or {})
        return _spawn(r, agent, cmd, env, mode, "none (--strict-mcp-config)")
    if not agent.get("configDir"):
        # Loops created before the per-loop config existed get one on their next run.
        agent["configDir"] = str(write_cli_config(d))
        save_json(d / "agent.json", agent)
    cmd = cli_command(agent["model"], agent["workspace"], prompt, agent.get("sessionId"), mode)
    disabled = disable_mcp(agent["workspace"])
    env = cli_env(dict(os.environ))
    env.update(agent.get("env") or {})
    if agent.get("configDir"):
        env["CURSOR_CONFIG_DIR"] = agent["configDir"]
    return _spawn(r, agent, cmd, env, mode, disabled)


def _spawn(r: Path, agent: dict, cmd: list[str], env: dict, mode: str, mcp_disabled) -> int:
    out = (r / "events.ndjson").open("ab")
    err = (r / "stderr.log").open("ab")
    exit_file = r / "exit.code"
    # The shell records the exit code, so `wait` can read it after this script has gone.
    wrapper = ['/bin/sh', '-c', '"$@"; echo $? > "$EXIT_FILE"', "sh", *cmd]
    env["EXIT_FILE"] = str(exit_file)
    proc = subprocess.Popen(wrapper, cwd=agent["workspace"], stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                            env=env, start_new_session=True)
    save_json(r / "run.json", {"runner": agent.get("runner", "cli"), "pid": proc.pid, "status": "RUNNING",
                               "startedAt": now(), "mode": mode, "resumedSession": agent.get("sessionId"),
                               "mcpDisabled": mcp_disabled})
    return proc.pid


# Three clocks, so a slow step is never taken for a hang (the pattern of codexmon's watchdog and of CI no-output
# limits): idle time counts only while nothing runs, one tool call has its own limit, and --timeout caps the run.
STALL_S = 10 * 60  # silent this long, with no tool call in flight and no final result: the run is over
TOOL_S = 60 * 60  # one shell or tool call running this long is a hang (a server started in the foreground)
RESULT_GRACE_S = 60  # the CLI can report its result and never exit (a known Cursor issue): stop it after this


def redact(text: str) -> str:
    """Masks credentials in a process line: URL passwords, --token style flags, KEY=value pairs."""
    text = re.sub(r"([a-zA-Z][\w+.-]*://)[^/\s:@]+:[^@\s]+@", r"\1***@", text)
    text = re.sub(r"(?i)(--(?:password|token|api[-_]?key|secret)[= ])\S+", r"\1***", text)
    return re.sub(r"(?i)\b(\w*(?:password|passwd|token|secret|api[_-]?key)\w*=)\S+", r"\1***", text)


def process_snapshot(pid: int) -> str:
    """What was running under a run when it was stopped, for the record; credentials masked."""
    listing = subprocess.run(["ps", "-ww", "-eo", "pid=,ppid=,etime=,args="], capture_output=True, text=True).stdout
    rows, children = {}, {}
    for line in listing.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = (parts[2], parts[3])
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    out, todo = [], [(pid, 0)]
    while todo:
        p, depth = todo.pop()
        if p in rows:
            out.append(f"{'  ' * depth}{p} {rows[p][0]} {redact(rows[p][1])[:300]}")
        todo += [(c, depth + 1) for c in reversed(children.get(p, []))]
    return "\n".join(out) + "\n"


def stuck_tool(in_flight: dict, now_s: float, limit_s: float) -> str | None:
    """The command of a tool call that has run past its limit, if any."""
    for started, command in in_flight.values():
        if now_s - started >= limit_s:
            return f"`{command[:120]}` ran {int((now_s - started) // 60)} min"
    return None


def stalled(events: list[dict], silent_s: float, after_s: float = STALL_S) -> bool:
    """A run that will never say it is done: no result, nothing running, and silent for `after_s`.

    A long command (a build, a test suite) sends no events until it ends, so a tool call still in flight is
    never a stall."""
    if silent_s < after_s or any(e.get("type") == "result" for e in events):
        return False
    in_flight = set()
    for e in events:
        for action, call_id, _ in tool_calls(e):
            (in_flight.add if action == "start" else in_flight.discard)(call_id)
    return not in_flight


def kill_tree(pid: int, grace_s: float = 5.0) -> list[int]:
    """Stops a process and everything below it, such as the dev servers an executor left running: they can sit
    in their own process groups, out of reach of a group kill."""
    listing = subprocess.run(["ps", "-ww", "-eo", "pid=,ppid="], capture_output=True, text=True).stdout
    children: dict[int, list[int]] = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and all(x.isdigit() for x in parts):
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    tree, todo = [], [pid]
    while todo:
        p = todo.pop()
        tree.append(p)
        todo += children.get(p, [])
    for p in reversed(tree):  # the leaves first, so nothing restarts what was just stopped
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and any(pid_alive(p) for p in tree):
        time.sleep(0.2)
    for p in tree:
        if pid_alive(p):
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return tree


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_events(path: Path) -> list[dict]:
    events = []
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                events.append({"type": "raw", "text": line[:500]})
    return events


# ---------------------------------------------------------------- commands


def _resolve_runner(name: str, environ: dict) -> tuple[str, dict | None]:
    """A --runner value: a built-in executor name, or a declared provider. Returns (the name, the
    provider's entry or None), with the same error text as an unknown executor."""
    if name in EXECUTORS:
        return name, None
    providers = load_config(environ).get("providers") or {}
    if name in providers:
        return name, providers[name]
    raise LoopError(f"unknown runner {name!r}; choose from {', '.join(EXECUTORS + tuple(providers))}")


def cmd_preflight(args) -> int:
    environ = dict(os.environ)
    runner, provider = _resolve_runner(args.runner, environ)
    if runner == "subagent":
        # The coordinator's own Claude session runs it; there is nothing on this machine to check.
        print("ok    Claude subagent: the coordinator dispatches it with the keryx executor agent")
        return 0
    problems = 0
    repo = ""
    if runner == "cloud":  # only a cloud agent clones from GitHub; a local run works in any checkout
        try:
            repo = normalize_repo_url(git("remote", "get-url", "origin"))
            print(f"ok    origin = {repo}")
        except LoopError as exc:
            print(f"FAIL  {exc}")
            return 1
    if runner == "glm":
        return _preflight_glm()
    if provider is not None:
        return _preflight_codex(runner, provider)
    if runner == "cli":
        env = cli_env(dict(os.environ))
        found = subprocess.run(["sh", "-c", "command -v agent"], capture_output=True, text=True, env=env)
        if found.returncode != 0:
            print("FAIL  Cursor CLI not found: install with `curl https://cursor.com/install -fsS | bash`, then `agent login`")
            return 1
        version = subprocess.run(["agent", "--version"], capture_output=True, text=True, env=env).stdout.strip()
        print(f"ok    Cursor CLI {version} at {found.stdout.strip()}")
        status = subprocess.run(["agent", "status"], capture_output=True, text=True, env=env)
        if "Logged in" in status.stdout:
            print("ok    " + status.stdout.strip().splitlines()[0].lstrip("✓ ").strip())
        else:
            print("FAIL  Cursor CLI is not logged in: run `agent login` (browser login draws from the plan's included usage)")
            problems += 1
        models = subprocess.run(["agent", "models"], capture_output=True, text=True, env=env).stdout
        if f"{DEFAULT_CLI_MODEL} " in models:
            print(f"ok    default model {DEFAULT_CLI_MODEL} is available")
        else:
            print(f"WARN  {DEFAULT_CLI_MODEL} not listed by `agent models`; pass --model explicitly")
        print(f"ok    worktrees go to {worktree_path('example').parent}/cursor-<slug>")
        gcfg = Path(os.path.expanduser("~/.cursor/cli-config.json"))
        attribution = (json.loads(gcfg.read_text()).get("attribution") or {}) if gcfg.exists() else {}
        if attribution.get("attributeCommitsToAgent", True):
            print("ok    global attributeCommitsToAgent is on; loop runs use a per-loop config with it off "
                  "(CURSOR_CONFIG_DIR), so their commits carry no Co-authored-by: Cursor trailer")
    else:
        try:
            key = api_key()
            print("ok    api key found (not shown)")
        except LoopError as exc:
            print(f"FAIL  {exc}")
            return 1
        if key.startswith("grok_"):
            print("WARN  this is a grok_ key (X Subscription). Cursor's secrets API rejects grok_ keys, and cloud "
                  "endpoints answered with a false Privacy Mode (Legacy) error for one; an older crsr_ key worked")
            problems += 1
        try:
            models = call("GET", "/v1/models").get("items", [])
            grok = [m["id"] for m in models if "grok" in m["id"].lower()]
            print(f"ok    {len(models)} models; grok: {', '.join(grok) or 'none'}")
        except LoopError as exc:
            print(f"FAIL  models: {exc}")
            problems += 1
        try:
            listed = [r["url"].rstrip("/").removesuffix(".git").lower()
                      for r in call("GET", "/v1/repositories", timeout=120).get("items", [])]
            if repo.lower() in listed:
                print("ok    repository is visible to Cursor's GitHub app")
            else:
                print(f"WARN  {repo} not in /v1/repositories ({len(listed)} listed): install or extend the Cursor GitHub app")
                problems += 1
        except LoopError as exc:
            print(f"WARN  repositories check skipped: {exc}")
        try:
            envs = call("GET", "/v1/environments").get("items", [])
            print(f"ok    {len(envs)} saved cloud environment(s): " + ", ".join(e.get("name") or e.get("id", "?") for e in envs))
        except LoopError as exc:
            if "Privacy Mode" in str(exc):
                print("FAIL  Cursor account is in Privacy Mode (Legacy), which blocks every cloud agent endpoint. "
                      "Switch to Privacy Mode at https://cursor.com/dashboard/cloud-agents")
                problems += 1
            else:
                print(f"WARN  environments check skipped: {exc}")
        print("NOTE  cloud runs started through the API were refused with usage_limit_exceeded while credit was $0 "
              "(2026-10-23), although included usage was left; the cli runner is the default for that reason")
        top = Path(git("rev-parse", "--show-toplevel"))
        wf_dir = top / ".github" / "workflows"
        fired = []
        if wf_dir.is_dir():
            try:
                import yaml  # type: ignore
            except ImportError:
                yaml = None
                print("WARN  PyYAML missing: workflow push-trigger check skipped")
            if yaml:
                for f in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
                    try:
                        wf = yaml.safe_load(f.read_text()) or {}
                    except yaml.YAMLError as exc:
                        print(f"WARN  {f.name}: unreadable YAML ({exc.__class__.__name__})")
                        continue
                    if isinstance(wf, dict) and push_triggers_for(wf, "cursor/example-branch"):
                        fired.append(f.name)
        if fired:
            print("WARN  a push to cursor/* runs these workflows: " + ", ".join(fired) + " (check none deploys)")
            problems += 1
        else:
            print("ok    no workflow runs on a push to cursor/* branches")
    return 1 if problems else 0


def _preflight_glm() -> int:
    """Claude Code present, the plan key readable and private, and one tiny run answered by a GLM model."""
    found = subprocess.run(["sh", "-c", "command -v claude"], capture_output=True, text=True)
    if found.returncode != 0:
        print("FAIL  Claude Code (`claude`) not found")
        return 1
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    print(f"ok    Claude Code {version} at {found.stdout.strip()}")
    environ = dict(os.environ)
    try:
        glm_key(environ)
        url = glm_base_url(environ)
    except LoopError as exc:
        print(f"FAIL  {exc}")
        return 1
    print("ok    GLM Coding Plan key found (not shown)")
    problems = 0
    key_file = _glm_file(environ, "coding-plan.key")
    if key_file.is_file() and key_file.stat().st_mode & 0o077:
        print(f"WARN  {key_file} is readable by others: chmod 600 it")
        problems += 1
    print(f"ok    endpoint {url} (the plan's own, not the pay-as-you-go API)")
    print(f"ok    worktrees go to {worktree_path('example', 'glm').parent}/glm-<slug>, branches glm/<slug>")
    runs = state_root()
    probe = runs / "_glm-preflight"
    ensure_ignored(runs.parent)  # the probe's config is written under .keryx/, which ignores itself first
    cfg = write_glm_config(probe)
    probe.mkdir(parents=True, exist_ok=True)  # the probe run's working directory; its config lives beside the runs
    res = subprocess.run(["claude", "-p", "--output-format", "json", "--model", DEFAULT_GLM_MODEL, "--settings",
                          str(cfg / "settings.json"), "--strict-mcp-config", "--", "Reply with exactly the word OK."],
                         capture_output=True, text=True, env=glm_env(environ, str(cfg)), cwd=str(probe), timeout=300,
                         stdin=subprocess.DEVNULL)
    try:
        out = json.loads(res.stdout)
    except ValueError:
        print(f"FAIL  probe run gave no JSON (exit {res.returncode}): {redact((res.stderr or res.stdout)[-400:])}")
        return problems + 1
    models = sorted((out.get("modelUsage") or {}).keys())
    text = str(out.get("result", "")).strip()
    if out.get("is_error") or "OK" not in text:
        print(f"FAIL  probe run: is_error={out.get('is_error')} result={text[:200]!r}")
        problems += 1
    elif not models or not all("glm" in m.lower() for m in models):
        # The run would draw on another account (the owner's Claude usage) instead of the plan.
        print(f"FAIL  probe run was answered by {models or 'an unnamed model'}, not a GLM model")
        problems += 1
    else:
        print(f"ok    probe run answered {text[:20]!r} by {', '.join(models)}")
    return 1 if problems else 0


def _preflight_codex(name: str, provider: dict) -> int:
    """Codex CLI present, the provider's key readable and private, and one tiny read-only `codex exec`
    probe through the provider's own CODEX_HOME that answered KERYX_OK. The probe runs outside a
    repository, so it skips Codex's git-repository check. Prints the model and base URL, never the key."""
    problems = 0
    found = subprocess.run(["sh", "-c", "command -v codex"], capture_output=True, text=True)
    if found.returncode != 0:
        print("FAIL  Codex CLI (`codex`) not found: install it, then declare the provider in config.json")
        return 1
    version = subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip()
    print(f"ok    Codex CLI {version} at {found.stdout.strip()}")
    environ = dict(os.environ)
    try:
        key = codex_key(provider, environ)
    except LoopError as exc:
        print(f"FAIL  {exc}")
        return 1
    print("ok    provider key found (not shown)")
    key_file = codex_key_file(provider, environ)
    if key_file.is_file() and key_file.stat().st_mode & 0o077:
        print(f"WARN  {key_file} is readable by others: chmod 600 it")
        problems += 1
    print(f"ok    model {provider['model']} at {provider['baseUrl']}")
    print(f"ok    worktrees go to {worktree_path('example').parent}/{name}-<slug>, branches {name}/<slug>")
    with tempfile.TemporaryDirectory() as tmp:  # the probe's own CODEX_HOME, thrown away with its session
        home = write_codex_home(Path(tmp), provider)
        cmd = codex_probe_command(provider["model"], provider.get("effort"))
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, env=codex_env(environ, str(home), key),
                                 cwd=tmp, timeout=300, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            print("FAIL  probe run did not answer within 300s")
            return problems + 1
        events = []
        for line in res.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        outcome = codex_outcome(events, res.returncode)
        if outcome["status"] == "FINISHED" and "KERYX_OK" in outcome["result"]:
            print(f"ok    probe run answered {outcome['result'][:30]!r}")
        else:
            detail = outcome["result"] or res.stderr or res.stdout or ""
            print(f"FAIL  probe run: exit {res.returncode}, {outcome['status']}: {redact(str(detail)[-300:])}")
            problems += 1
    return 1 if problems else 0


def _detect_executors() -> None:
    """One line per executor: can this machine run it? Keys are looked up, never printed."""
    print("subagent  yes  always available")
    env = cli_env(dict(os.environ))  # the runner's PATH: where a CLI install actually lands
    found = subprocess.run(["sh", "-c", "command -v agent"], capture_output=True, text=True, env=env)
    if found.returncode != 0:
        print("cli  no  Cursor CLI not found: install with `curl https://cursor.com/install -fsS | bash`, then `agent login`")
    else:
        status = subprocess.run(["agent", "status"], capture_output=True, text=True, env=env)
        if "Logged in" in status.stdout:
            print(f"cli  yes  Cursor CLI at {found.stdout.strip()}, logged in")
        else:
            print("cli  no  Cursor CLI is not logged in: run `agent login`")
    try:
        glm_key(dict(os.environ))
        print("glm  yes  GLM Coding Plan key found (not shown)")
    except LoopError as exc:
        print(f"glm  no  {exc}")
    try:
        api_key()
        print("cloud  yes  Cursor API key found (not shown)")
    except LoopError as exc:
        print(f"cloud  no  {exc}")
    environ = dict(os.environ)
    try:
        providers = load_config(environ).get("providers") or {}
    except LoopError as exc:  # detect is a probe: a bad config is one more finding, not a dead command
        print(f"provider  no  {exc}")
        providers = {}
    for name, provider in providers.items():
        installed = subprocess.run(["sh", "-c", "command -v codex"], capture_output=True, text=True).returncode == 0
        try:
            codex_key(provider, environ)
            key_state = "key file present"
            usable = installed
        except LoopError as exc:
            key_state = str(exc)
            usable = False
        codex_state = "codex installed" if installed else "codex not installed"
        print(f"{name}  {'yes' if usable else 'no'}  {codex_state}, {key_state}")


def _setup_base(path: Path, new_ladder: bool) -> tuple[dict, str | None]:
    """What setup starts from: the saved file with every key kept. With no saved file, or one that is not a JSON
    object, only a new ladder may start one (as in 1.4.0): an order or a reset alone would save a ladder nobody
    chose and silence the first-use setup note. The second value says what is wrong with a file the new ladder
    replaces; the caller keeps that file as <name>.broken once the new one is sure to be written."""
    if not path.exists():
        if not new_ladder:
            raise LoopError(f"{path} does not exist yet: save the ladder first with setup --executors LIST")
        return {}, None
    try:
        data = json.loads(path.read_text())
        problem = None if isinstance(data, dict) else "is not a JSON object"
    except ValueError as exc:
        problem = f"is not valid JSON ({exc})"
    if problem is None:
        return data, None
    if not new_ladder:
        raise LoopError(f"{path} {problem}: fix it, or replace it with setup --executors LIST")
    return {}, problem


def _apply_reset(path: Path, resets: dict, text: str, providers=()) -> None:
    """`RUNNER=WHEN[/EVERY]` saves that reset; `RUNNER=none` clears it. `next` is stored as given.
    A declared provider has a reset date like any plan."""
    if text.count("=") != 1:
        raise LoopError(f"{path}: reset must be RUNNER=WHEN[/EVERY], not {text!r}")
    runner, rest = text.split("=", 1)
    runner = runner.strip()
    if runner not in EXECUTORS and runner not in providers:
        raise LoopError(f"{path}: unknown executor {runner!r}; "
                        f"choose from {', '.join(EXECUTORS + tuple(providers))}")
    rest = rest.strip()
    if rest == "none":
        resets.pop(runner, None)
        return
    parts = rest.split("/")
    if len(parts) > 2:
        raise LoopError(f"{path}: reset {text!r} has an extra '/'")
    when, every = parts[0].strip(), parts[1].strip() if len(parts) == 2 else None
    if every is not None and every not in _RESET_EVERY:
        raise LoopError(f"{path}: reset for {runner} every must be month or week")
    if _parse_next(when) is None:
        raise LoopError(f"{path}: reset for {runner} needs next as YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ")
    spec = {"next": when}
    if every:
        spec["every"] = every
    resets[runner] = spec


def _print_setup(environ: dict) -> None:
    cfg = load_config(environ)
    print("\n".join(cfg["executors"]))
    print(f"order: {cfg['order']}")
    for name, spec in cfg["resets"].items():
        every = spec.get("every") if isinstance(spec, dict) else None
        nxt = spec.get("next") if isinstance(spec, dict) else ""
        print(f"{name} {nxt}" + (f" {every}" if every else ""))
    print(config_path(environ))


def cmd_setup(args) -> int:
    """Save the ladder, the order and when each plan resets, or print what is saved.

    Starts from the whole saved file, so a key keryx does not know stays. The file is written only
    after `load_config` would read the result: setup never saves a file keryx then refuses, and the off
    switch, `--order ladder`, works even while a bad date stops the reset order."""
    environ = dict(os.environ)
    path = config_path(environ)
    reset_args = list(args.reset or [])
    writing = bool(args.executors or args.order or reset_args)
    if writing:
        data, broken = _setup_base(path, bool(args.executors))
        providers = data.get("providers")
        providers = providers if isinstance(providers, dict) else {}
        if args.executors:
            data["executors"] = parse_executors(args.executors, providers)
        if args.order:
            data["order"] = args.order
        if reset_args:
            current = data.get("resets", {})
            if not isinstance(current, dict):
                raise LoopError(f'{path}: "resets" must be an object')
            resets = dict(current)
            for text in reset_args:
                _apply_reset(path, resets, text, providers)
            data["resets"] = resets
        data["updatedAt"] = now()
        _config_view(path, data)
        if broken:
            kept = path.with_name(path.name + ".broken")
            os.replace(path, kept)
            print(f"keryx: {path} {broken}; kept it as {kept} and started a new one", file=sys.stderr)
        save_json(path, data)
        print(path)
    if args.detect:
        _detect_executors()
    if not writing and not args.detect:
        _print_setup(environ)
    return 0


def _resets_line(config: dict, ladder: list[str], at: dt.datetime) -> str:
    """One line: `order: resets`, then each executor's next reset or `no reset`."""
    resets = config.get("resets") if isinstance(config.get("resets"), dict) else {}
    parts = []
    for name in ladder:
        spec = resets.get(name)
        when = next_reset(spec, at) if isinstance(spec, dict) else None
        parts.append(f"{name} resets {when}" if when else f"{name} no reset")
    return "order: resets, soonest first: " + ", ".join(parts)


def cmd_executors(args) -> int:
    """The ladder a session can use now. A runner at its usage limit is left out until that limit resets."""
    environ = dict(os.environ)
    note = setup_note(environ)
    if note:
        print(note, file=sys.stderr)
    config = load_config(environ)
    at = dt.datetime.now(dt.timezone.utc)
    ladder = ordered_ladder(config, at)
    if config.get("order") == "resets":
        print(_resets_line(config, ladder, at), file=sys.stderr)
    if args.after:
        _resolve_runner(args.after, environ)  # a typo'd rung is an error, not the ladder's first rung
        print(_executor_after(ladder, args.after, environ, at))
        return 0
    limited = limited_runners(environ, at)
    for name in ladder:
        if name in limited:
            print(f"{name}: usage limit until {limited[name]}; left out until then", file=sys.stderr)
    available = available_ladder(ladder, environ, at)
    print("\n".join(available) if available else "inline")
    return 0


def cmd_models(args) -> int:
    if args.runner == "glm":
        print(f"{DEFAULT_GLM_MODEL} / sonnet -> {GLM_ENV['ANTHROPIC_DEFAULT_OPUS_MODEL']}, "
              f"haiku -> {GLM_ENV['ANTHROPIC_DEFAULT_HAIKU_MODEL']} (GLM Coding Plan)")
        return 0
    if args.runner == "cli":
        return subprocess.run(["agent", "models"], env=cli_env(dict(os.environ))).returncode
    for m in call("GET", "/v1/models").get("items", []):
        variants = ", ".join(v.get("displayName", "") for v in m.get("variants", []) or [])
        print(f"{m['id']:<40} {m.get('displayName', '')}" + (f"  [{variants}]" if variants else ""))
    return 0


def _handover_commit(d: Path, agent: dict) -> str:
    """Where a replacement executor starts: the failed one's head when it committed, else the base.
    The branch survives its worktree being removed; if neither exists there is nothing to name."""
    base = agent["baseSha"]
    head = ""
    if agent_is_local(agent):
        if agent.get("workspace") and Path(agent["workspace"]).is_dir():
            head = git("rev-parse", "HEAD", cwd=agent["workspace"], check=False)
        if not head:
            head = git("rev-parse", "--verify", "--quiet", f"refs/heads/{agent['branch']}", check=False)
        if not head:
            raise LoopError(f"neither the worktree {agent.get('workspace')} nor branch {agent['branch']!r} "
                            "exists; no handover commit to start the next executor from")
    elif (d / "head.txt").exists():
        head = (d / "head.txt").read_text().strip()
    ahead = git("rev-list", "--count", f"{base}..{head}", check=False) if head else ""
    return head if head and ahead.strip().isdigit() and int(ahead) > 0 else base


def _switch_plan(d: Path, slug: str, runner: str, escalate: bool = False) -> dict:
    """Read-only check of a re-create on an existing loop: may the loop change hands, and where would
    the next executor start? A live round keeps the existing error instead; --escalate also allows
    taking over a FINISHED round. Nothing is archived until every step of the new create has
    succeeded (see _archive_switch)."""
    agent = load_agent(d)
    r = current_round(d)
    run = json.loads((r / "run.json").read_text()) if (r / "run.json").exists() else {}
    status = run.get("status")
    if not (can_switch(status) or (escalate and status == "FINISHED")):
        raise LoopError(f"{slug} already has an implementer; use `followup`, or pick a new slug")
    return {"start": _handover_commit(d, agent), "baseSha": agent["baseSha"], "baseRef": agent.get("baseRef"),
            "old": agent.get("runner", "cli"), "round": r.name, "status": status,
            "verb": "switch" if can_switch(status) else "escalate"}


def _archive_switch(d: Path, plan: dict, runner: str) -> None:
    """Now that nothing else can fail: archive agent.json and log the handover."""
    (d / "agent.json").rename(d / f"agent.{plan['round']}.json")
    append_log(d, "dispatch", f"{plan['verb']} executor {plan['old']} -> {runner} after {plan['status']}",
               "the executor failed; the next executor takes over the same slug",
               f"agent.json -> agent.{plan['round']}.json, rounds continue, worktree from {plan['start'][:12]}",
               plan["verb"] + "ed")


def _reuse_worktree(wt: Path, branch: str, start: str) -> None:
    """A worktree on `branch` at `start` for a replacement executor (the runner may be the same one):
    reuse the existing worktree when it is clean, and never reset away commits `start` does not contain."""
    ref = f"refs/heads/{branch}"
    has_branch = bool(git("rev-parse", "--verify", "--quiet", ref, check=False))
    if has_branch:
        head = git("rev-parse", ref)
        kept = subprocess.run(["git", "merge-base", "--is-ancestor", ref, start], capture_output=True)
        if kept.returncode != 0:
            raise LoopError(f"{branch} is at {head[:12]}, which the new start {start[:12]} does not contain; "
                            "moving the branch would drop the executor's commits")
    if wt.is_dir():
        if git("status", "--porcelain", cwd=wt):
            raise LoopError(f"{wt} has uncommitted changes; commit or discard them before switching executors")
        git("checkout", "--quiet", branch, cwd=wt)
        git("reset", "--hard", start, cwd=wt)
    elif has_branch:
        git("worktree", "add", str(wt), branch)
        git("reset", "--hard", start, cwd=wt)
    else:
        git("worktree", "add", "-b", branch, str(wt), start)


def keep_main_worktree_settings() -> None:
    """Under extensions.worktreeConfig git applies core.bare and core.worktree from the shared config to every
    worktree, so a bare repository's worktrees stop being work trees and a submodule's linked worktree reports
    the submodule's git dir as its top level. Both settings belong to the main worktree alone: they move into
    its config.worktree, as git's own worktree machinery does for a bare repository (git-worktree(1),
    CONFIGURATION FILE). Idempotent, so a repository an older keryx left broken is repaired by the next round."""
    shared = common_dir() / "config"
    own = common_dir() / "config.worktree"
    if git("config", "--type=bool", "--file", str(shared), "--get", "core.bare", check=False) == "true":
        git("config", "--file", str(own), "core.bare", "true")
        git("config", "--file", str(shared), "--unset", "core.bare")
    worktree = git("config", "--file", str(shared), "--get", "core.worktree", check=False)
    if worktree:
        git("config", "--file", str(own), "core.worktree", worktree)
        git("config", "--file", str(shared), "--unset", "core.worktree")


def block_pushes(wt: Path) -> None:
    """A subagent's worktree cannot push: a per-worktree push URL for origin (even before that remote
    exists) and every configured remote, under extensions.worktreeConfig — never the main worktree's
    or the shared config."""
    if not git("config", "--get", "extensions.worktreeConfig", check=False):
        git("config", "extensions.worktreeConfig", "true")
    keep_main_worktree_settings()
    for name in ["origin"] + [r for r in git("remote").split() if r != "origin"]:
        git("config", "--worktree", f"remote.{name}.pushurl", "https://push-disabled.invalid/keryx", cwd=wt)


def _refuse_subagent(agent: dict) -> None:
    """`wait` and `cancel` have no process to act on: a subagent reports to the coordinator."""
    if agent.get("runner") == "subagent":
        raise LoopError("a Claude subagent reports to the coordinator; there is nothing to wait for")


def agent_is_local(agent: dict) -> bool:
    """A round this machine runs in a worktree: a built-in local runner, or a declared provider (whose
    agent.json carries a runnerKind). Rounds from before providers have no runnerKind and resolve by name."""
    return agent.get("runner") in LOCAL_RUNNERS or agent.get("runnerKind") in PROVIDER_RUNNERS


def cmd_create(args) -> int:
    environ = dict(os.environ)
    runner, provider = _resolve_runner(args.runner, environ)
    config = load_config(environ)
    _refuse_busy_runner(config, runner, environ, args.ignore_limit)
    d = slug_dir(args.slug, must_exist=False)
    switch = _switch_plan(d, args.slug, runner, args.escalate) if (d / "agent.json").exists() else None
    if switch:
        # A handover keeps the loop's base and ignores --ref entirely: it does not even resolve it.
        start, base_sha = switch["start"], switch["baseSha"]
        if runner == "cloud" and start != base_sha:
            raise LoopError(f"the cloud runner clones from GitHub and cannot start from {start[:12]}, which "
                            "exists only on this machine; switch to a local rung (cli, glm or subagent) instead")
    else:
        start = base_sha = pin_base(args.ref)
    if runner in LOCAL_RUNNERS or provider is not None:
        if args.param or args.image:
            raise LoopError("--param and --image are cloud-runner options")
        glm = runner == "glm"
        sub = runner == "subagent"
        model = args.model or (provider["model"] if provider else
                               "sonnet" if sub else DEFAULT_GLM_MODEL if glm else DEFAULT_CLI_MODEL)
        read_prompt(args.prompt_file)
        wt = worktree_path(args.slug, runner)
        branch = f"{WORKTREE_PREFIX.get(runner, runner)}/{args.slug}"
        if args.dry_run:
            shown = (f"keryx:executor with worktree {wt}" if sub
                     else glm_command(model, "<prompt>", None, args.mode, str(glm_config_dir(d) / "settings.json")) if glm
                     else codex_command(model, "<prompt>", None, args.mode, (provider or {}).get("effort")) if provider
                     else cli_command(model, str(wt), "<prompt>", None, args.mode))
            print(json.dumps({"runner": runner, "worktree": str(wt), "branch": branch, "base": start,
                              "model": model, "command": shown}, indent=2))
            return 0
        extra_env = parse_env(args.env)
        if glm:
            glm_env(dict(os.environ), "")  # no key, or a wrong endpoint: fail before a worktree exists
        if provider:
            codex_key(provider, dict(os.environ))  # no key file: fail before a worktree exists
        ensure_ignored(wt.parent)  # .worktrees/ ignores itself before a worktree lands in it, as .keryx/ does
        if switch:
            _reuse_worktree(wt, branch, start)
        else:
            if wt.exists():
                raise LoopError(f"{wt} already exists")
            git("worktree", "add", "-b", branch, str(wt), start)
        if runner == "cli":
            write_cli_permissions(wt)
        if sub:
            block_pushes(wt)
        runs = state_root()
        if d.parent == runs:  # a run under .keryx/, whose folder ignores itself; a legacy run keeps its own
            ensure_ignored(runs.parent)
        if switch:
            # Everything that can fail has succeeded; only now does the loop change hands.
            _archive_switch(d, switch, runner)
        if sub:
            agent = {"slug": args.slug, "runner": "subagent", "workspace": str(wt), "branch": branch,
                     "baseSha": base_sha, "baseRef": (switch or {}).get("baseRef", args.ref),
                     "model": model, "createdAt": now()}
            save_json(d / "agent.json", agent)
            r = new_round(d, args.prompt_file)
            save_json(r / "run.json", {"status": "DISPATCHED", "startedAt": now()})
            append_log(d, "dispatch", f"run {r.name}: prepared a Claude subagent "
                                      f"(dispatch keryx:executor with worktree {wt})", "keryx create",
                       f"branch {branch}, base {start[:12]}", "DISPATCHED")
            print(f"run {r.name} prepared: dispatch keryx:executor with worktree {wt}\nbranch   {branch}")
            return 0
        agent = {"slug": args.slug, "runner": runner, "workspace": str(wt), "branch": branch, "baseSha": base_sha,
                 "baseRef": (switch or {}).get("baseRef", args.ref), "model": model, "sessionId": None,
                 "createdAt": now(), "env": extra_env,
                 "configDir": str(write_glm_config(d) if glm else
                                  write_codex_home(d, provider) if provider else write_cli_config(d))}
        if provider:
            agent["runnerKind"] = "codex"
        save_json(d / "agent.json", agent)
        r = new_round(d, args.prompt_file)
        pid = cli_launch(d, r, agent, read_prompt(args.prompt_file), args.mode)
        who = (f"{runner} (codex exec on {provider['model']} at {provider['baseUrl']})" if provider
               else "GLM (Claude Code on the GLM Coding Plan)" if glm else "Cursor CLI")
        append_log(d, "dispatch", f"run {r.name}: started {who} ({args.mode} mode, model {model})", "keryx create",
                   f"pid {pid}, worktree {wt}, branch {branch}, base {start[:12]}", "RUNNING")
        print(f"run {r.name} started: pid {pid}\nworktree {wt}\nbranch   {branch}\nevents   {r / 'events.ndjson'}")
        return 0
    body: dict = {
        "prompt": prompt_payload(args.prompt_file, args.image),
        "repos": [{"url": normalize_repo_url(git("remote", "get-url", "origin")), "startingRef": start}],
        "workOnCurrentBranch": False,
        "autoCreatePR": False,
        "mode": args.mode,
        "name": f"keryx: {args.slug}"[:100],
    }
    if args.model:
        body["model"] = {"id": args.model}
        if args.param:
            body["model"]["params"] = parse_params(args.param)
    elif args.param:
        raise LoopError("--param needs --model")
    if args.dry_run:
        shown = json.loads(json.dumps(body))
        shown["prompt"]["text"] = shown["prompt"]["text"][:300] + "..."
        for img in shown["prompt"].get("images", []):
            img["data"] = f"<{len(img['data'])} base64 chars>"
        print(json.dumps(shown, indent=2))
        return 0
    resp = call("POST", "/v1/agents", body)
    agent, run = resp.get("agent", {}), resp.get("run", {})
    if not agent.get("id") or not run.get("id"):
        raise LoopError(f"unexpected create response: {json.dumps(resp)[:500]}")
    runs = state_root()
    if d.parent == runs:  # a run under .keryx/, whose folder ignores itself; a legacy run keeps its own
        ensure_ignored(runs.parent)
    if switch:
        _archive_switch(d, switch, runner)
    save_json(d / "agent.json", {
        "slug": args.slug, "runner": "cloud", "agentId": agent["id"], "url": agent.get("url"),
        "repo": body["repos"][0]["url"], "baseSha": base_sha,
        "baseRef": (switch or {}).get("baseRef", args.ref), "model": args.model,
        "modelParams": args.param, "createdAt": now(),
    })
    r = new_round(d, args.prompt_file)
    save_json(r / "run.json", run)
    append_log(d, "dispatch", f"run {r.name}: created cloud agent ({args.mode} mode, model {args.model or 'default'})",
               "keryx create", f"agent {agent['id']} run {run['id']} base {base_sha[:12]} {agent.get('url', '')}",
               str(run.get("status")))
    print(f"agent {agent['id']}  run {run['id']}  status {run.get('status')}\n{agent.get('url', '')}")
    return 0


def cmd_followup(args) -> int:
    environ = dict(os.environ)
    config = load_config(environ)
    d = slug_dir(args.slug)
    agent = load_agent(d)
    _refuse_busy_runner(config, str(agent.get("runner") or ""), environ, args.ignore_limit)
    if agent.get("runner") == "subagent":
        # A subagent's fix round: the coordinator dispatches it; this script only opens the round.
        prev = current_round(d)
        prev_run = json.loads((prev / "run.json").read_text()) if (prev / "run.json").exists() else {}
        if prev_run.get("status") == "DISPATCHED":
            raise LoopError("mark the current round first")
        r = new_round(d, args.prompt_file)
        save_json(r / "run.json", {"status": "DISPATCHED", "startedAt": now()})
        append_log(d, "dispatch", f"run {r.name}: prepared a Claude subagent follow-up "
                                  f"(dispatch keryx:executor with worktree {agent['workspace']})",
                   "keryx followup", f"round {r.name}, branch {agent['branch']}", "DISPATCHED")
        print(f"run {r.name} prepared: dispatch keryx:executor with worktree {agent['workspace']}")
        return 0
    if agent_is_local(agent):
        prev = current_round(d)
        if not (prev / "exit.code").exists() and pid_alive(json.loads((prev / "run.json").read_text())["pid"]):
            raise LoopError(f"run {prev.name} is still going; `wait` for it or `cancel` it first")
        if not agent.get("sessionId"):
            raise LoopError("no session id recorded yet; run `wait` on the previous run first")
        r = new_round(d, args.prompt_file)
        pid = cli_launch(d, r, agent, read_prompt(args.prompt_file), args.mode)
        append_log(d, "dispatch", f"run {r.name}: follow-up ({args.mode} mode)", "keryx followup",
                   f"pid {pid}, session {agent['sessionId']}", "RUNNING")
        print(f"run {r.name} started: pid {pid} (resuming session {agent['sessionId']})")
        return 0
    body = {"prompt": prompt_payload(args.prompt_file, []), "mode": args.mode}
    resp = call("POST", f"/v1/agents/{agent['agentId']}/runs", body)
    run = resp.get("run", resp)
    if not run.get("id"):
        raise LoopError(f"unexpected follow-up response: {json.dumps(resp)[:500]}")
    r = new_round(d, args.prompt_file)
    save_json(r / "run.json", run)
    append_log(d, "dispatch", f"run {r.name}: follow-up ({args.mode} mode)", "keryx followup",
               f"run {run['id']}", str(run.get("status")))
    print(f"run {r.name}: run {run['id']}  status {run.get('status')}")
    return 0


def _summarize(ev_type: str, payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    if ev_type == "status":
        return f"status {payload.get('status')}"
    if ev_type == "tool_call" and payload.get("status") in (None, "started", "running"):
        args = json.dumps(payload.get("args", ""))[:140]
        return f"tool  {payload.get('name')} {args}"
    if ev_type == "error":
        return f"ERROR {payload.get('code')}: {payload.get('message')}"
    if ev_type == "result":
        return f"result {payload.get('status')} in {payload.get('durationMs')} ms"
    return None


def _wait_cli(d: Path, args) -> int:
    agent = load_agent(d)
    r = current_round(d)
    run = json.loads((r / "run.json").read_text())
    pid, events_path, exit_file = run["pid"], r / "events.ndjson", r / "exit.code"
    codex = agent.get("runnerKind") in PROVIDER_RUNNERS
    # Codex ends a turn with turn.completed or turn.failed where the CLIs send one `result` event.
    result_types = ("turn.completed", "turn.failed") if codex else ("result",)
    deadline = time.monotonic() + args.timeout
    offset = 0
    timed_out = is_stalled = lingered = False
    stop_reason = ""
    seen: list[dict] = []
    in_flight: dict = {}  # call id -> (started, command)
    result_at = None
    while True:
        if events_path.exists():
            with events_path.open("rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
            complete, _, _ = chunk.rpartition(b"\n")
            if complete:
                offset += len(complete) + 1
                for line in complete.decode("utf-8", "replace").splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    calls = tool_calls(event)
                    if calls or event.get("type") in result_types:
                        seen.append(event)
                    for action, call_id, command in calls:
                        if action == "start":
                            # Claude Code's events carry no timestamps: a call counts from when wait read it.
                            started = (event.get("timestamp_ms") or time.time() * 1000) / 1000
                            in_flight[call_id] = (started, command)
                        else:
                            in_flight.pop(call_id, None)
                    if event.get("type") in result_types:
                        result_at = time.time()
                    summary = cli_summary(event)
                    if summary:
                        print(f"{now()} {summary}", flush=True)
        if exit_file.exists() or not pid_alive(pid):
            break
        if result_at is not None and time.time() - result_at >= args.result_grace:
            lingered, stop_reason = True, f"reported its result but did not exit within {args.result_grace}s"
        # Silence counts from the log's last write, so a wait started on a run that went quiet long ago sees it.
        silent = time.time() - events_path.stat().st_mtime if events_path.exists() else 0.0
        stuck = stuck_tool(in_flight, time.time(), args.tool_timeout) if result_at is None else None
        if not lingered and stuck:
            is_stalled, stop_reason = True, f"one tool call ran past {args.tool_timeout}s: {stuck}"
        elif not lingered and stalled(seen, silent, args.stall):
            is_stalled, stop_reason = True, f"silent {int(silent)}s with nothing in flight and no result"
        elif not lingered and time.monotonic() > deadline:
            timed_out, stop_reason = True, f"timed out after {args.timeout}s"
        if lingered or is_stalled or timed_out:
            (r / "processes.txt").write_text(process_snapshot(pid))
            kill_tree(pid)
            break
        time.sleep(3)
    code = None
    if exit_file.exists():
        raw = exit_file.read_text().strip()
        code = int(raw) if raw.lstrip("-").isdigit() else None
    elif timed_out:
        code = -15
    events_all = read_events(events_path)
    if lingered:  # it finished; only its exit was missing
        last = next((e for e in reversed(events_all) if e.get("type") in result_types), {})
        code = (0 if last.get("type") != "turn.failed" and not last.get("is_error") else 1) if codex \
            else (0 if not last.get("is_error") else 1)
    outcome = codex_outcome(events_all, code) if codex else cli_outcome(events_all, code)
    if timed_out:
        outcome["status"] = "CANCELLED"
    if is_stalled:
        outcome["status"] = "STALLED"
    if outcome["session_id"] and outcome["session_id"] != agent.get("sessionId"):
        agent["sessionId"] = outcome["session_id"]
        save_json(d / "agent.json", agent)
    run.update({"status": outcome["status"], "exit": outcome["exit"], "durationMs": outcome["durationMs"],
                "sessionId": outcome["session_id"], "endedAt": now()})
    (r / "result.md").write_text(outcome["result"])
    limit = round_usage_limit(r) if outcome["status"] == "ERROR" else None
    if limit:
        run["usageLimit"] = limit
    save_json(r / "run.json", run)
    head = git("rev-parse", "HEAD", cwd=agent["workspace"])
    dirty = git("status", "--porcelain", cwd=agent["workspace"])
    print(f"branch {agent['branch']} at {head}" + ("  (UNCOMMITTED changes in the worktree)" if dirty else ""))
    denied = [d for e in events_all if e.get("type") == "result" for d in e.get("permission_denials") or []]
    if denied:  # Claude Code lists the calls its deny rules refused
        print(f"{len(denied)} tool call(s) refused by the deny rules: "
              + ", ".join(str(x.get("tool_name", "?")) for x in denied[:10]))
    stderr = (r / "stderr.log").read_text(errors="replace").strip() if (r / "stderr.log").exists() else ""
    if stderr:
        print("stderr: " + stderr[-800:])
    why = (f"{stop_reason}; stopped with everything it started (processes.txt)" if stop_reason
           else "the CLI process ended")
    append_log(d, "dispatch", f"run {r.name}: ended", why, f"exit {outcome['exit']}, {r / 'result.md'}",
               f"{outcome['status']} in {outcome['durationMs']} ms")
    print(f"run {r.name} {outcome['status']} (exit {outcome['exit']}); result saved to {r / 'result.md'}")
    if is_stalled:
        print("the executor stopped talking without a final report; its commits are on the branch above: "
              "fetch and check them, and follow up for anything missing")
        return 4
    return 0 if outcome["status"] == "FINISHED" else (3 if timed_out else 2)


def _wait_local(d: Path, args) -> int:
    retries = max(0, args.rate_retries)
    while True:
        code = _wait_cli(d, args)
        r = current_round(d)
        run = json.loads((r / "run.json").read_text())
        limit = run.get("usageLimit")
        if not (isinstance(limit, dict) and limit.get("kind") == "rate" and retries > 0):
            if isinstance(limit, dict):
                report_usage_limit(d, r, limit)
            return code
        next_name = f"{len(rounds(d)) + 1:02d}"
        print(f"RATE_LIMIT  rate limit; retrying as run {next_name} in {args.rate_wait}s")
        append_log(d, "dispatch", f"run {r.name}: rate limit; retrying as run {next_name}",
                   "a rate limit clears within minutes, so the same brief is tried again",
                   f"{r / 'result.md'}", "retry")
        retries -= 1
        if args.rate_wait:
            time.sleep(args.rate_wait)
        prompt_path = r / "prompt.md"
        prompt = prompt_path.read_text()
        next_round = new_round(d, str(prompt_path))
        cli_launch(d, next_round, load_agent(d), prompt, run.get("mode") or "agent")


def cmd_wait(args) -> int:
    if args.rate_wait < 0 or args.rate_retries < 0:
        raise LoopError("--rate-wait and --rate-retries must be zero or more")
    d = slug_dir(args.slug)
    agent = load_agent(d)
    _refuse_subagent(agent)
    if agent_is_local(agent):
        return _wait_local(d, args)
    r = current_round(d)
    run = json.loads((r / "run.json").read_text())
    run_id, agent_id = run["id"], agent["agentId"]
    deadline = time.monotonic() + args.timeout
    last_id = None
    final = None
    with (r / "events.ndjson").open("a") as events:
        while time.monotonic() < deadline and final is None:
            headers = {"Last-Event-ID": last_id} if last_id else None
            try:
                with _request("GET", f"/v1/agents/{agent_id}/runs/{run_id}/stream",
                              accept="text/event-stream", extra_headers=headers, timeout=180) as resp:
                    lines = (raw.decode("utf-8", "replace") for raw in resp)
                    for ev_id, ev_type, payload in parse_sse(lines):
                        last_id = ev_id or last_id
                        if ev_type == "heartbeat":
                            continue
                        events.write(json.dumps({"id": ev_id, "type": ev_type, "data": payload}) + "\n")
                        events.flush()
                        line = _summarize(ev_type, payload)
                        if line:
                            print(f"{now()} {line}", flush=True)
                        if ev_type in ("result", "done"):
                            final = payload if ev_type == "result" else (final or {})
                            break
            except urllib.error.HTTPError as exc:
                if exc.code == 410:
                    print(f"{now()} stream expired; polling the run instead", flush=True)
                elif exc.code == 400 and last_id:
                    print(f"{now()} stream refused Last-Event-ID; reconnecting from the start", flush=True)
                    last_id = None
                else:
                    raise LoopError(f"stream -> HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                print(f"{now()} stream dropped ({exc.__class__.__name__}); checking run state", flush=True)
            state = call("GET", f"/v1/agents/{agent_id}/runs/{run_id}")
            if state.get("status") in TERMINAL_RUN_STATES:
                final = final or {}
                break
            if final is None:
                time.sleep(15)
    if final is None:
        append_log(d, "dispatch", f"run {r.name}: wait timed out after {args.timeout}s", "no terminal run state yet",
                   f"run {run_id}", "open")
        print(f"timed out after {args.timeout}s; run {run_id} may still be going (`status`, `cancel`)")
        return 3
    run = call("GET", f"/v1/agents/{agent_id}/runs/{run_id}")
    save_json(r / "run.json", run)
    (r / "result.md").write_text(str(run.get("result") or (final.get("text") if isinstance(final, dict) else "") or ""))
    for b in (run.get("git") or {}).get("branches") or []:
        print(f"branch {b.get('branch')}  pr {b.get('prUrl') or '-'}  ({b.get('repoUrl')})")
    status = run.get("status")
    append_log(d, "dispatch", f"run {r.name}: run ended", "terminal run state",
               f"run {run_id}, {r / 'result.md'}", f"{status} in {run.get('durationMs')} ms")
    print(f"run {run_id} {status}; result saved to {r / 'result.md'}")
    return 0 if status == "FINISHED" else 2


def cmd_status(args) -> int:
    d = slug_dir(args.slug)
    agent = load_agent(d)
    if agent.get("runner") == "subagent":
        # No process of ours to watch; the agent record is what there is to see.
        print(json.dumps(agent, indent=2, sort_keys=True))
        return 0
    r = current_round(d)
    run = json.loads((r / "run.json").read_text())
    if agent_is_local(agent):
        alive = pid_alive(run["pid"]) and not (r / "exit.code").exists()
        if not alive and run.get("status") == "ERROR":
            limit = run.get("usageLimit") or round_usage_limit(r)
            if limit:
                if "usageLimit" not in run:
                    run["usageLimit"] = limit
                    save_json(r / "run.json", run)
                    report_usage_limit(d, r, limit)
                else:
                    when = (f"resets at {limit['resetsAt']}" if limit.get("resetsAt")
                            else f"resets in {limit['resetsIn']}")
                    print(f"USAGE_LIMIT  {limit['kind']} limit; {when}")
        tail = [s for s in (cli_summary(e) for e in read_events(r / "events.ndjson")[-40:]) if s][-8:]
        print(json.dumps({"runner": agent["runner"], "round": r.name, "pid": run["pid"], "running": alive,
                          "status": "RUNNING" if alive else run.get("status"), "session": agent.get("sessionId"),
                          "workspace": agent["workspace"], "branch": agent["branch"],
                          "head": git("rev-parse", "HEAD", cwd=agent["workspace"]), "recent": tail}, indent=2))
        return 0
    meta = call("GET", f"/v1/agents/{agent['agentId']}")
    live = call("GET", f"/v1/agents/{agent['agentId']}/runs/{run['id']}")
    print(json.dumps({"agent": {k: meta.get(k) for k in ("id", "status", "url", "latestRunId")},
                      "round": r.name, "run": {k: live.get(k) for k in ("id", "status", "durationMs", "git")}}, indent=2))
    return 0


def branch_of(d: Path) -> str:
    agent = load_agent(d)
    for r in reversed(rounds(d)):
        run = json.loads((r / "run.json").read_text())
        for b in (run.get("git") or {}).get("branches") or []:
            if b.get("branch") and (b.get("repoUrl") or agent["repo"]).rstrip("/").removesuffix(".git").lower() == agent["repo"].lower():
                return b["branch"]
    raise LoopError("the agent has not reported a branch yet (has a run finished?)")


def cmd_fetch(args) -> int:
    d = slug_dir(args.slug)
    agent = load_agent(d)
    if agent_is_local(agent):
        branch = agent["branch"]
        head = git("rev-parse", "HEAD", cwd=agent["workspace"])
        git("update-ref", f"refs/keryx/{args.slug}", head)
        dirty = git("status", "--porcelain", cwd=agent["workspace"])
        if dirty:
            print("WARN  the worktree has uncommitted changes; only commits are reviewed:\n" + dirty)
    else:
        branch = branch_of(d)
        if branch in ("main", "master") or not branch.startswith("cursor/"):
            print(f"WARN  agent branch is {branch!r}, not a cursor/* branch")
        git("fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/keryx/{args.slug}")
        head = git("rev-parse", f"refs/keryx/{args.slug}")
    (d / "head.txt").write_text(head + "\n")
    print(f"branch {branch}\nhead   {head}\nbase   {agent['baseSha']}\nref    refs/keryx/{args.slug}")
    print(git("diff", "--stat", f"{agent['baseSha']}...{head}"))
    append_log(d, "review", f"round {current_round(d).name}: read the implementer's head on {branch}",
               "review needs the implementer's head", f"refs/keryx/{args.slug} = {head}", "fetched")
    return 0


def resolve_head(d: Path, ref: str | None) -> str:
    """The commit to review: the given ref (a branch a subagent wrote, which `fetch` cannot read),
    else the head `fetch` recorded."""
    if ref:
        sha = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        if not sha:
            raise LoopError(f"cannot resolve {ref!r}")
        return sha
    head = (d / "head.txt").read_text().strip() if (d / "head.txt").exists() else ""
    if not head:
        raise LoopError("no head recorded for this slug: run `fetch` for an executor loop, or name the commit "
                        "with --head (review-brief, finish) or --ref (gates, locked)")
    return head


def cmd_gates(args) -> int:
    """Did the run touch a gate file (architecture, lint, dependency or CI configuration)? Those are
    the owner's call, not the executor's."""
    d = slug_dir(args.slug)
    base = load_agent(d)["baseSha"]
    head = resolve_head(d, args.ref)
    globs = list(DEFAULT_GATE_GLOBS)
    extra = inherited(d, "gates.txt")
    if extra.exists():
        globs += [ln.strip() for ln in extra.read_text().splitlines()
                  if ln.strip() and not ln.lstrip().startswith("#")]
    hits = gate_hits([p for p in git("diff", "--name-only", "--no-renames",
                                     f"{base}...{head}").splitlines() if p], globs)
    for p in hits:
        print(f"GATE  {p}")
    append_log(d, "review", f"round {current_round(d).name}: gate check",
               "a gate file is the owner's call, not the executor's",
               f"git diff --name-only {base[:12]}...{head[:12]}",
               f"{len(hits)} gate files changed" if hits else "no gate file changed")
    if hits:
        return 1
    print("ok    no gate file changed")
    return 0


def cmd_locked(args) -> int:
    """Check locked test blocks: <state>/locked/<n>.json = {"path": ..., "block": ...}."""
    d = slug_dir(args.slug)
    head = resolve_head(d, args.ref)
    specs = sorted(inherited(d, "locked").glob("*.json"))
    if not specs:
        print("no locked test blocks registered (write <state>/locked/NN.json)")
        return 1
    bad = 0
    for spec in specs:
        s = json.loads(spec.read_text())
        shown = subprocess.run(["git", "show", f"{head}:{s['path']}"], capture_output=True, text=True)
        if shown.returncode != 0:
            print(f"MISSING  {s['path']} does not exist at {head[:12]}  ({spec.name})")
            bad += 1
        elif locked_block_present(s["block"], shown.stdout):
            print(f"ok       {s['path']}  ({spec.name})")
        else:
            print(f"CHANGED  {s['path']}: locked block not found verbatim  ({spec.name})")
            bad += 1
    append_log(d, "review", f"round {current_round(d).name}: locked-test check", "locked tests are the acceptance criteria",
               f"head {head[:12]}", f"{len(specs) - bad}/{len(specs)} intact")
    return 1 if bad else 0


# The section a hotfix lane brief ends with: minutes, not the whole bar, because the lasting fix follows in its own
# run (review-brief --hotfix).
HOTFIX_REVIEW_SECTION = (
    "\n## Hotfix\n\n"
    "This change is a hotfix: production is being harmed now, and the lasting fix follows in its own run. Review the\n"
    "diff only, for what makes things worse: report P0 and P1 only (data loss, security, wrong results served, a broken\n"
    "feature or contract, a change that cannot be rolled back), and leave P2 and P3 to the follow-up. Answer Reach and\n"
    "Spec in one line each, and keep to a few minutes.\n"
)


def cmd_review_brief(args) -> int:
    """Write the fresh reviewer's brief as a file (the bar, the paths, where to write the findings) and
    print how to dispatch it; field run 10 retyped the prompt and lost half of it."""
    d = slug_dir(args.slug, must_exist=False)
    if args.base:
        base = resolve_head(d, args.base)
    elif (d / "agent.json").exists() and load_agent(d).get("baseSha"):
        base = load_agent(d)["baseSha"]
    else:
        raise LoopError("--base is needed: this slug has no executor loop")
    head = resolve_head(d, args.head)
    name = f"{base[:12]}..{head[:12]}"
    rv = d / "review"
    runs = state_root()
    if d.parent == runs:  # a run under .keryx/, whose folder ignores itself; a legacy run keeps its own
        ensure_ignored(runs.parent)
    rv.mkdir(parents=True, exist_ok=True)
    diff_path = rv / f"{name}.diff"
    diff_path.write_text(f"{git('log', '--format=%h %s', f'{base}..{head}')}\n\n"
                         f"{git('diff', '--stat', base, head)}\n\n"
                         f"{git('diff', base, head)}\n")
    toplevel = git("rev-parse", "--show-toplevel")
    plan = inherited(d, "PLAN.md")
    task = (f"{plan} (it holds the acceptance check)" if plan.exists()
            else f"no plan file: take the commit messages (git log {base[:12]}..{head[:12]}) "
                 f"and the PR description as the task")
    rules_paths = [str(Path(toplevel) / entry) for entry in RULE_FILES if (Path(toplevel) / entry).exists()]
    rules = (f"- Architecture rules of this repository: {', '.join(rules_paths)}. "
             "A break of one of them is a defect too: cite the rule and what it lets go wrong."
             if rules_paths else "")
    # The reviewer reads code at the reviewed head: an executor's head lives in its own worktree, while the
    # repository's own checkout may still be at the base.
    checkout = f"- No checkout holds the head: read files with git show {head[:12]}:<path>, never from a working tree."
    where = None
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            where = line[len("worktree "):]
        elif where and line.startswith("HEAD ") and line[5:] == head:
            checkout = f"- The head is checked out in {where}: read the surrounding code there."
            break
    template = (PROMPTS / "reviewer.md").read_text()

    def brief_text(findings: Path, security: str) -> str:
        return (template.replace("{{repo}}", toplevel).replace("{{base}}", base).replace("{{head}}", head)
                .replace("{{package}}", str(diff_path)).replace("{{task}}", task).replace("{{rules}}", rules)
                .replace("{{checkout}}", checkout).replace("{{findings}}", str(findings))
                .replace("{{security}}", security)
                + (HOTFIX_REVIEW_SECTION if args.hotfix else ""))

    brief = rv / f"{name}.brief.md"
    brief.write_text(brief_text(rv / f"{name}.findings.md", ""))
    print(f"package   {diff_path}")
    print(f"dispatch  model={'opus' if args.risk or args.hotfix else 'sonnet'}  "
          f"prompt=\"Read {brief} and follow it exactly.\"")
    paths = [brief]
    if args.risk:  # a risk list diff gets a second finder with its own security pass
        security_brief = rv / f"{name}.security.brief.md"
        security_brief.write_text(brief_text(rv / f"{name}.security.findings.md",
                                             (PROMPTS / "reviewer-security.md").read_text().strip()))
        print(f"dispatch  model=sonnet  prompt=\"Read {security_brief} and follow it exactly.\"")
        paths.append(security_brief)
    finders = f"{2 if args.risk else 1} finder{'s' if args.risk else ''}" + (" (hotfix)" if args.hotfix else "")
    append_log(d, "review", f"review brief for {name}",
               "the reviewer gets keryx's bar from a file, not from memory",
               " ".join(str(p) for p in paths), finders)
    return 0


# scrub and archive log their own rows under the finish phase; they are adapter bookkeeping, never the run's
# finish row (this also covers run logs written before this release).
ADAPTER_FINISH_ROWS = ("scrubbed assistant attribution", "archived the cloud agent")


def parsed_reviews(d: Path) -> list[tuple[Path, dict]]:
    """Every first finder's findings file in the run's review folder, parsed, oldest name first."""
    parsed = []
    if (d / "review").is_dir():
        for p in sorted((d / "review").glob("*.findings.md")):
            if not p.name.endswith(".security.findings.md"):
                parsed.append((p, review_findings(p.read_text())))
    return parsed


def covering_review(parsed: list[tuple[Path, dict]], final: str) -> tuple[Path, dict] | None:
    """The review that counts for `final`: among the well-formed ones whose reviewed head is an ancestor
    of it, the closest to it (ties: the file written last). Another line of history never counts."""
    def is_ancestor(sha: str) -> bool:
        return subprocess.run(["git", "merge-base", "--is-ancestor", sha, final],
                              capture_output=True).returncode == 0

    covering = [(p, r) for p, r in parsed if r["head"] and is_ancestor(r["head"])]
    return min(covering,
               key=lambda pr: (int(git("rev-list", "--count", f"{pr[1]['head']}..{final}")),
                               -pr[0].stat().st_mtime),
               default=None)


def committed_report(final: str, slug: str) -> str | None:
    """The run report the change ships: the newest docs/keryx/<date>-<slug>.md committed at `final`
    (newest by name, so a later day's report for the same slug wins). --full-tree reads the pathspec
    from the tree's root, wherever the command runs from."""
    listed = [p for p in git("ls-tree", "-r", "--full-tree", "--name-only", final, "--", "docs/keryx").splitlines()
              if re.fullmatch(rf"docs/keryx/\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}\.md", p)]
    return max(listed) if listed else None


def _report_checkout(head: str, into: str | None) -> Path:
    """The checkout a report ships from: the named one, the one holding the shipped head, or this one."""
    current = Path(git("rev-parse", "--show-toplevel")).resolve()
    if into:
        top = git("rev-parse", "--show-toplevel", cwd=into, check=False)
        common = git("rev-parse", "--git-common-dir", cwd=into, check=False)
        if not top or not common:
            raise LoopError(f"{into} is not a checkout of this repository")
        common_path = Path(common)
        common_path = common_path.resolve() if common_path.is_absolute() else (Path(into) / common_path).resolve()
        if common_path != common_dir():
            raise LoopError(f"{into} is not a checkout of this repository")
        return Path(top).resolve()
    if head != git("rev-parse", "HEAD"):
        where = None
        for line in git("worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                where = Path(line[len("worktree "):]).resolve()
            elif where is not None and line.startswith("HEAD ") and line[5:] == head:
                if where != current:
                    return where
                where = None
    return current


def cmd_report(args) -> int:
    """Draft the run report docs/keryx/<date>-<slug>.md from the run's own record. The proof comes
    first and a Now block (live, waiting on the owner, next) closes it; what only the coordinator
    knows stays as <!-- --> placeholders, which `finish` refuses until they are gone. The file is
    never overwritten once it exists."""
    d = slug_dir(args.slug, must_exist=False)
    log = d / "decisions.tsv"
    if not log.exists():
        raise LoopError(f"no run log at {log}")
    if args.head:
        final = git("rev-parse", "--verify", "--quiet", f"{args.head}^{{commit}}", check=False)
        if not final:
            raise LoopError(f"cannot resolve {args.head!r}")
    else:
        final = git("rev-parse", "HEAD")  # the branch that ships, where the report gets committed
    top = _report_checkout(final, args.into)
    date = dt.date.today().isoformat()
    name = f"docs/keryx/{date}-{args.slug}.md"
    if (top / name).exists():
        raise LoopError(f"{name} already exists; the coordinator's prose is never overwritten")
    def safe(c: list[str]) -> bool:
        return not any(looks_secret(c[i]) for i in (2, 3, 5))

    rows = read_log_rows(d)
    left_out = sum(1 for _, c in rows if not safe(c))
    keep = {n for n, c in rows if safe(c)}  # a credential-looking row is left out, numbered or not
    rulings = [(n, c) for n, c in standing_rulings(rows) if n in keep]
    deferred = deferred_rows([(n, c) for n, c in rows if n in keep])
    followups = standing_followups([(n, c) for n, c in rows if n in keep], standing_rulings(rows))
    review = covering_review(parsed_reviews(d), final)
    plan = (d / "PLAN.md").read_text() if (d / "PLAN.md").exists() else ""

    def committed(text: str) -> str:
        """The report is committed, often to a public repository: nothing it copies names a local path."""
        # this checkout first (a bare repository's worktree lies outside its main folder), then the main one
        return strip_local_paths(text, list(dict.fromkeys((top, main_worktree()))), Path.home())

    title = next((re.sub(r"^#{1,6}\s+", "", line).strip() for line in plan.splitlines() if line.strip()),
                 args.slug)
    if looks_secret(title):
        title, left_out = args.slug, left_out + 1
    else:
        title = committed(title)
    # The whole Acceptance check section, up to the next heading, with its edge blank lines gone and its
    # indentation kept (nested bullets and indented code come out as they went in, one common indent less).
    check, inside = [], False
    for line in plan.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip() == "## Acceptance check"
        elif inside:
            check.append(line.rstrip())
    while check and not check[0]:
        check.pop(0)
    while check and not check[-1]:
        check.pop()
    check = textwrap.dedent("\n".join(check)).splitlines()
    if any(looks_secret(line) for line in check):
        check, left_out = [], left_out + 1
    if left_out:
        print("a row of the log was left out of the report: it looks like a credential", file=sys.stderr)
    if len(check) == 1:
        proof = f"- Acceptance check: {committed(check[0])}\n"
    elif check:
        proof = "- Acceptance check:\n" + "".join(f"  {committed(line)}\n" if line else "\n" for line in check)
    else:
        proof = "- Acceptance check: <!-- the check, failing on the base and passing now -->\n"
    qa = d / "qa" / "QA.md"
    counts = review[1]["counts"] if review is not None else None
    second_finder = ""
    if review is not None:
        stem = review[0].name.removesuffix(".findings.md")
        second = review[0].with_name(f"{stem}.security.findings.md")
        if review[0].with_name(f"{stem}.security.brief.md").exists() and second.exists():
            c2 = review_findings(second.read_text())["counts"]
            second_finder = (f"- Second finder: `{repo_relative(second)}`: "
                             f"P0 {c2['P0']} · P1 {c2['P1']} · P2 {c2['P2']} · P3 {c2['P3']}\n")
    folders = run_folders(d)
    counted = [folder_rounds(f) for f in folders]
    total, fixes = sum(n for n, _ in counted), sum(k for _, k in counted)
    parts = [(f.name, n) for f, (n, _) in zip(folders, counted) if n]
    started = dt.datetime.strptime(rows[0][1][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc) \
        if rows else dt.datetime.now(dt.timezone.utc)
    wall = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
    run_line = f"- {int(wall) // 3600}h {int(wall) % 3600 // 60:02d}m wall clock, {total} executor rounds ({fixes} FIX)"
    if len(folders) > 1 and parts:  # the slices' rounds are counted too, so each folder is named
        run_line += ": " + ", ".join(f"{name} {n}" for name, n in parts)
    unnamed = unnamed_later_runs(d)
    if unnamed:
        # the draft is never drafted again, so the note carries what it takes to count such a run in by hand
        run_line += (" <!-- " + ", ".join("{} ({} rounds, {} FIX)".format(f.name, *folder_rounds(f)) for f in unnamed)
                     + " started after this run, which never names it: if a slice, add its rounds to this line"
                     " and name it in the plan; if another run, delete this note -->")
    follow_up = ""  # a hotfix run reports the run that will do the lasting fix, until it is logged
    if is_hotfix_run(rows) and followup_waived(standing_rulings(rows)):
        # said in the report itself: the ruling may be one the Rulings section leaves out (it looks like a credential)
        follow_up = "- Follow-up: none — waived by a ruling (`Ruling: no follow-up — …` in the run log)\n"
    elif is_hotfix_run(rows):
        if followups:
            follow_up = "".join(f"- Follow-up: `{slug}`: {committed(what)}\n" for slug, what in followups)
        else:
            follow_up = (f"- Follow-up: <!-- the follow-up run that does the lasting fix: keryx.py log "
                         f"--slug {args.slug} followup \"{args.slug}-root: <what>\" WHY EVIDENCE RESULT, "
                         "then log its intake -->\n")
    text = (
        f"# {title}\n"
        "\n"
        f"{date} · keryx run `{args.slug}`\n"
        "\n"
        "## Proof\n"
        + proof
        + (f"- Fresh review: `{repo_relative(review[0])}`: "
           f"P0 {counts['P0']} · P1 {counts['P1']} · P2 {counts['P2']} · P3 {counts['P3']}\n"
           if review is not None else "- Fresh review: <!-- none yet -->\n")
        + second_finder
        + (f"- QA: `{repo_relative(qa)}` (kept where the run ran, not committed)\n" if qa.exists()
           else "- QA: <!-- what QA covered -->\n")
        + "<!-- Anything else that proves it: mutation probes, CI runs. -->\n"
        "\n"
        "## What changed\n"
        "<!-- For the person who uses it: what is different now, and where it lives (branch, commits, PR). -->\n"
        "\n"
        "## Open\n"
        "<!-- What was not verified, and why. -->\n"
        + "".join(f"- Deferred: {committed(c[2])}\n" for _, c in deferred)
        + follow_up
        + "\n"
        "## Rulings\n"
        + ("".join(f"- {committed(c[2])} — {committed(c[3])} — {committed(c[5])}\n" for _, c in rulings)
           or "- none\n")
        + "\n"
        "## Run\n"
        f"{run_line}\n"
        "\n"
        "## Now\n"
        "- Live: <!-- what is running or in use now, and where -->\n"
        "- Waiting on you: <!-- what needs the owner now, or \"nothing\" -->\n"
        "- Next: <!-- the next step, and who takes it -->\n"
    )
    (top / name).parent.mkdir(parents=True, exist_ok=True)
    (top / name).write_text(text)
    print(top / name)
    return 0


def cmd_finish(args) -> int:
    """The run is finished only when its log has a finish row and a fresh, well-formed review covers the
    shipped head; the newest review on that line of history decides, and nothing older rescues it."""
    d = slug_dir(args.slug, must_exist=False)
    log = d / "decisions.tsv"
    if not log.exists():
        raise LoopError(f"no run log at {log}")
    final = resolve_head(d, args.head)
    rows = read_log_rows(d)
    finish_rows = [c for _, c in rows if c[1].split("-")[0] == "finish"
                   and not c[2].startswith(ADAPTER_FINISH_ROWS)]
    rulings = standing_rulings(rows)
    deferred = deferred_rows(rows)
    followups = standing_followups(rows, rulings)
    hotfix = is_hotfix_run(rows)

    def commits_behind(sha: str) -> int:
        return int(git("rev-list", "--count", f"{sha}..{final}"))

    parsed = parsed_reviews(d)
    review = covering_review(parsed, final)

    problems = []
    if not finish_rows:
        problems.append(f"missing  a finish row: log one per PR or branch shipped with "
                        f"keryx.py log --slug {args.slug} finish WHAT WHY EVIDENCE RESULT")
    fresh = (f"missing  a fresh review of this head or an earlier commit of it: "
             f"keryx.py review-brief --slug {args.slug}, then the reviewer writes its findings file")
    if review is None:
        problems.append(fresh)
        problems += [f"bad      {p}: {'; '.join(r['problems'])}" for p, r in parsed if r["problems"]]
    elif review[1]["problems"]:
        problems.append(f"bad      {review[0]}: {'; '.join(review[1]['problems'])}")
        problems.append(fresh)
    second = None
    if review is not None:
        stem = review[0].name.removesuffix(".findings.md")
        if review[0].with_name(f"{stem}.security.brief.md").exists():  # this review was dispatched with --risk
            path = review[0].with_name(f"{stem}.security.findings.md")
            parsed_second = review_findings(path.read_text()) if path.exists() else None
            second = (path, parsed_second)
            if parsed_second is None or parsed_second["problems"]:
                if parsed_second is not None:
                    problems.append(f"bad      {path}: {'; '.join(parsed_second['problems'])}")
                problems.append(f"missing  the second finder's findings: {path}")
    report = None
    if not args.findings_only:  # a findings-only review changes nothing, so it ships no report
        report = committed_report(final, args.slug)
        if report is None:
            problems.append(f"missing  the run report at head {final[:12]}: keryx.py report --slug {args.slug}, "
                            "fill it in and commit it with the change (pass --head <the shipped commit> "
                            "when it ships from another branch)")
        elif "<!--" in git("show", f"{final}:{report}"):
            problems.append(f"missing  the run report at head {final[:12]}: {report} still has <!-- --> "
                            "placeholders (pass --head <the shipped commit> when it ships from another branch)")
    opened = []  # the follow-ups whose run was opened for this hotfix
    if hotfix and not followup_waived(rulings):  # the fast lane pays for itself: the lasting fix runs as its own
        unmet = []                               # keryx run, or a standing ruling says why not
        for slug, what in followups:
            if slug == args.slug:  # the lasting fix needs a run of its own, or the gate would wave itself through
                unmet.append(f"missing  the follow-up run {slug} is this hotfix run itself: name the run that "
                             f"does the lasting fix (keryx.py log --slug {args.slug} followup \"{args.slug}-root: …\")")
            elif not (slug_dir(slug, must_exist=False) / "decisions.tsv").exists():
                unmet.append(f"missing  the follow-up run {slug} has no run log: log its intake "
                             f"(keryx.py log --slug {slug} intake …)")
            elif not any(c[1] == "intake" and c[0] >= hotfix_started(rows)
                         for _, c in read_log_rows(slug_dir(slug, must_exist=False))):
                # a run opened before the hotfix, or one with only a note, is not the lasting fix's run
                unmet.append(f"missing  the follow-up run {slug} has no intake since this hotfix began: log its "
                             f"intake (keryx.py log --slug {slug} intake …)")
            else:
                opened.append((slug, what))
        if not followups:
            problems.append(f"missing  the follow-up run: keryx.py log --slug {args.slug} followup "
                            f"\"{args.slug}-root: <what the lasting fix does>\" WHY EVIDENCE RESULT, then that "
                            f"run's intake — or the waiver, when the hotfix is the lasting fix: keryx.py log "
                            f"--slug {args.slug} ruling \"Ruling: no follow-up — <why the hotfix is the lasting "
                            "fix>\" WHY EVIDENCE RESULT")
        problems += unmet  # every follow-up still asked for is opened; a row logged by mistake is dropped by a ruling
    if problems:
        print(f"NOT FINISHED  {args.slug}")
        for line in problems:
            print(line)
        return 1

    def review_line(path: Path, r: dict) -> str:
        behind = commits_behind(r["head"])
        where = "the final head" if behind == 0 else \
            f"{behind} commit{'s' if behind != 1 else ''} before the final head"
        c = r["counts"]
        return (f"review    {path}  head {r['head'][:12]}, {where}  "
                f"P0 {c['P0']} · P1 {c['P1']} · P2 {c['P2']} · P3 {c['P3']}")

    started = dt.datetime.strptime(rows[0][1][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    wall = (dt.datetime.now(dt.timezone.utc) - started).total_seconds()
    print(f"FINISHED  {args.slug}  head {final[:12]}")
    print(f"wall      {int(wall) // 3600}h {int(wall) % 3600 // 60:02d}m since {rows[0][1][0]}")
    reviews = [str(review[0])]
    print(review_line(review[0], review[1]))
    if second is not None:
        reviews.append(str(second[0]))
        print(review_line(second[0], second[1]))
    if report is not None:
        print(f"report    {report}")
    for c in finish_rows:
        print(f"shipped   {c[2]} — {c[5]}")
    for _, c in rulings:
        print(f"ruling    {c[2]} — {c[3]} — {c[5]}")
    for _, c in deferred:
        print(f"deferred  {c[2]}")
    for slug, what in opened:
        print(f"followup  {slug}: {what}")
    folders = run_folders(d)
    counted = [folder_rounds(f) for f in folders]
    total, fixes = sum(n for n, _ in counted), sum(k for _, k in counted)
    parts = [(f.name, n) for f, (n, _) in zip(folders, counted) if n]
    if total:
        line = f"rounds    {total} executor rounds, {fixes} of them FIX"
        if len(folders) > 1 and parts:  # the slices' rounds are counted too, so each folder is named
            line += " (" + ", ".join(f"{name} {n}" for name, n in parts) + ")"
        print(line)
    for f in unnamed_later_runs(d):
        n, k = folder_rounds(f)
        print(f"unnamed   {f.name}: {n} executor rounds ({k} FIX), started after this run, which never names it")
    qa = d / "qa" / "QA.md"
    print(f"qa        {qa}" if qa.exists() else f"qa        none (no {qa})")
    finished = {"slug": args.slug, "finishedAt": now(), "head": final,
                "reviews": reviews, "finishRows": len(finish_rows)}
    if hotfix:
        finished["followups"] = [slug for slug, _ in opened]
    if report is not None:
        finished["report"] = report
    save_json(d / "finished.json", finished)
    append_log(d, "done", "run finished", "a finish row and a fresh review cover the shipped head",
               f"head {final[:12]}", f"{len(finish_rows)} finish rows")
    return 0


def record_status(run_path: Path, status: str) -> None:
    """Write a round's outcome into its run.json, recording when it ended; the other fields stay."""
    run = json.loads(run_path.read_text()) if run_path.exists() else {}
    run["status"] = status
    run["finishedAt"] = now()
    save_json(run_path, run)


def cmd_mark(args) -> int:
    """Write a round's outcome into its run.json: the coordinator's judgement of a subagent round,
    which lets a failed one hand its slug to the next executor."""
    d = slug_dir(args.slug)
    r = current_round(d)
    record_status(r / "run.json", args.status)
    append_log(d, "review", f"round {r.name}: marked {args.status} by the coordinator",
               "the coordinator judged the round's report", str(r / "run.json"), args.status)
    return 0


def cmd_scrub(args) -> int:
    """Rewrite the messages of base..head without an assistant's attribution lines; trees, authors and dates stay."""
    d = slug_dir(args.slug)
    agent = load_agent(d)
    if not agent_is_local(agent):
        raise LoopError("scrub works on a local runner's branch; a pushed cloud branch needs the owner's call")
    wt, branch, base = agent["workspace"], agent["branch"], agent["baseSha"]
    if git("status", "--porcelain", cwd=wt):
        raise LoopError(f"{wt} has uncommitted changes; scrub needs a clean worktree")
    if subprocess.run(["git", "ls-remote", "--exit-code", "--heads", "origin", branch], capture_output=True).returncode == 0:
        raise LoopError(f"{branch} exists on origin; rewriting a pushed branch is the owner's call")
    old_head = git("rev-parse", "HEAD", cwd=wt)
    commits = git("rev-list", "--reverse", "--parents", f"{base}..{old_head}", cwd=wt).splitlines()
    if any(len(line.split()) != 2 for line in commits):
        raise LoopError("scrub handles a linear branch only (found a merge or a root commit)")
    parent, changed = base, 0
    for line in commits:
        sha = line.split()[0]
        message = git("log", "-1", "--format=%B", sha, cwd=wt) + "\n"
        clean = strip_attribution(message)
        changed += clean.strip() != message.strip()
        meta = dict(zip(("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
                         "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"),
                        git("log", "-1", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI", sha, cwd=wt).split("\0")))
        made = subprocess.run(["git", "commit-tree", f"{sha}^{{tree}}", "-p", parent, "-F", "-"], input=clean,
                              capture_output=True, text=True, cwd=wt, env={**os.environ, **meta})
        if made.returncode != 0:
            raise LoopError(f"git commit-tree failed for {sha}: {made.stderr.strip()}")
        parent = made.stdout.strip()
    if not changed:
        print(f"nothing to scrub on {branch} ({len(commits)} commits)")
        return 0
    if git("diff", old_head, parent, cwd=wt):
        raise LoopError("the rewritten branch differs in content; nothing was changed")
    git("update-ref", f"refs/heads/{branch}", parent, old_head, cwd=wt)
    print(f"{branch}: {old_head[:12]} -> {parent[:12]}, {changed}/{len(commits)} messages scrubbed, trees identical")
    append_log(d, "finish", f"scrubbed assistant attribution from {changed} commit message(s)",
               "commits must not name an assistant",
               f"{old_head} -> {parent} (same tree)", "scrubbed")
    return 0


def cmd_cancel(args) -> int:
    d = slug_dir(args.slug)
    agent = load_agent(d)
    _refuse_subagent(agent)
    r = current_round(d)
    run = json.loads((r / "run.json").read_text())
    if agent_is_local(agent):
        if pid_alive(run["pid"]):
            kill_tree(run["pid"])
        else:
            print(f"run {r.name} had already ended")
        record_status(r / "run.json", "CANCELLED")
        append_log(d, "dispatch", f"run {r.name}: stopped the {agent['runner']} executor", "coordinator cancelled",
                   f"pid {run['pid']}", "cancelled")
        print(f"stopped run {r.name} (pid {run['pid']})")
        return 0
    call("POST", f"/v1/agents/{agent['agentId']}/runs/{run['id']}/cancel")
    append_log(d, "dispatch", f"run {r.name}: cancelled the active run", "coordinator cancelled", f"run {run['id']}", "cancelled")
    print(f"cancelled run {run['id']}")
    return 0


def _cloud_only(agent: dict, what: str) -> None:
    if agent.get("runner") != "cloud":
        raise LoopError(f"`{what}` is a cloud-runner command; the cli runner keeps everything in {agent.get('workspace')}")


def cmd_artifacts(args) -> int:
    d = slug_dir(args.slug)
    agent = load_agent(d)
    _cloud_only(agent, "artifacts")
    items = call("GET", f"/v1/agents/{agent['agentId']}/artifacts").get("items", [])
    out_dir = current_round(d) / "artifacts"
    for it in items:
        print(f"{it.get('sizeBytes', 0):>10}  {it.get('updatedAt', '')}  {it['path']}")
        if args.download:
            from urllib.parse import quote
            link = call("GET", f"/v1/agents/{agent['agentId']}/artifacts/download?path={quote(it['path'])}")
            target = (out_dir / it["path"]).resolve()
            if out_dir.resolve() not in target.parents:
                raise LoopError(f"artifact path escapes the round folder: {it['path']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(link["url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                target.write_bytes(resp.read())
    if args.download and items:
        print(f"downloaded to {out_dir}")
    return 0


def cmd_usage(args) -> int:
    d = slug_dir(args.slug)
    agent = load_agent(d)
    _cloud_only(agent, "usage")
    print(json.dumps(call("GET", f"/v1/agents/{agent['agentId']}/usage"), indent=2))
    return 0


def cmd_archive(args) -> int:
    d = slug_dir(args.slug)
    agent = load_agent(d)
    _cloud_only(agent, "archive")
    call("POST", f"/v1/agents/{agent['agentId']}/archive")
    append_log(d, "finish", "archived the cloud agent", "loop finished", agent["agentId"], "archived")
    print(f"archived {agent['agentId']}")
    return 0


def cmd_log(args) -> int:
    phase = normalise_phase(args.phase)
    if not PHASE.fullmatch(phase) and not FINISH_PHASE.fullmatch(phase):
        raise LoopError("phase must be one word ([a-z][a-z-]{1,19}); the decision is the next argument")
    if phase == "size" and args.decision not in {"S", "M", "L"}:
        raise LoopError("a size row's decision must be S, M or L")
    d = slug_dir(args.slug, must_exist=False)
    runs = state_root()
    if d.parent == runs:  # a run under .keryx/, whose folder ignores itself; a legacy run keeps its own
        ensure_ignored(runs.parent)
    rows = read_log_rows(d)
    m = REPLACES_ROW.search(args.decision)
    if m:
        n = int(m.group(1))
        named = next((c for i, c in rows if i == n), None)
        if not (is_ruling(args.phase, args.decision) and named is not None and is_ruling(named[1], named[2])):
            raise LoopError(f'"replaces row {n}" needs row {n} to exist and be a ruling, and the new row to be one')
        for i, c in rows:  # a row already replaced once stays replaced: the new ruling takes the replacer's number
            r = REPLACES_ROW.search(c[2])
            if r and int(r.group(1)) == n:
                raise LoopError(f"row {n} was already replaced by row {i}; replace row {i} instead")
    append_log(d, phase, args.decision, args.why, args.evidence, args.result)
    lines = (d / "decisions.tsv").read_text().splitlines()
    print(f"{d / 'decisions.tsv'}  row {len(lines) - 1}")  # the header is not a row
    if not standard_phase(phase):
        print(f"{phase} is not a standard phase", file=sys.stderr)
    return 0


def cmd_remember(args) -> int:
    if looks_secret(args.note):
        raise LoopError("that note looks like a credential; keryx memory never stores secrets")
    path = memory_file("repo" if args.repo else "user", dict(os.environ))
    if path is None:
        raise LoopError("--repo needs a git repository")
    if args.repo:
        ensure_ignored(path.parent)  # the note is about to live in .keryx/, which ignores itself first
        legacy = legacy_memory_file()
        if legacy is not None and legacy.is_file() and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(path)  # a pre-1.2 memory moves in whole, so its notes are kept once
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text().splitlines() if path.exists() else []
    if not any(line.partition(" ")[2].partition(" ")[2] == args.note for line in existing if line.startswith("- ")):
        with path.open("a") as fh:
            fh.write(f"- {dt.date.today().isoformat()} {args.note}\n")
    print(path)
    return 0


def cmd_recall(args) -> int:
    env = dict(os.environ)
    for scope, title in (("user", "user"), ("repo", "this repository")):
        path = memory_file(scope, env)
        if scope == "repo" and path is not None and not path.exists():
            legacy = legacy_memory_file()
            if legacy is not None and legacy.exists():
                path = legacy
        if path is None or not path.exists():
            continue
        print(f"# keryx memory ({title})")
        print(path.read_text().rstrip("\n"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="keryx.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("preflight")
    pf.add_argument("--runner", metavar="RUNNER", default="cli",
                    help="cli, cloud, glm, subagent, or a provider declared in config.json")
    su = sub.add_parser("setup")
    su.add_argument("--executors", metavar="LIST", help="save this executor order, e.g. cli,glm,subagent")
    su.add_argument("--order", choices=["ladder", "resets"],
                    help="ladder (the saved order) or resets (the plan that resets soonest first)")
    su.add_argument("--reset", action="append", default=None, metavar="RUNNER=WHEN[/EVERY]",
                    help="when RUNNER's plan resets (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ, "
                         "optionally /month or /week); RUNNER=none clears it")
    su.add_argument("--detect", action="store_true", help="print one line per executor: can this machine run it?")
    ex = sub.add_parser("executors")
    ex.add_argument("--after", metavar="RUNNER",
                    help="print the next executor after this one that is not at a usage limit (inline = the coordinator)")
    rm = sub.add_parser("remember")
    rm.add_argument("--repo", action="store_true", help="save for this repository only")
    rm.add_argument("note")
    sub.add_parser("recall")
    mo = sub.add_parser("models")
    mo.add_argument("--runner", choices=["cli", "cloud", "glm"], default="cli")
    c = sub.add_parser("create")
    c.add_argument("--slug", required=True)
    c.add_argument("--prompt-file", required=True)
    c.add_argument("--runner", metavar="RUNNER", default="cli",
                   help="cli, glm, subagent, cloud, or a provider declared in config.json")
    c.add_argument("--model")
    c.add_argument("--param", action="append", default=[], help="cloud: model parameter id=value, e.g. reasoning_effort=xhigh")
    c.add_argument("--ref", default="main")
    c.add_argument("--escalate", action="store_true",
                   help="also take over a FINISHED round: escalate to the next executor")
    c.add_argument("--mode", choices=["agent", "plan"], default="agent")
    c.add_argument("--image", action="append", default=[], help="cloud: image for the prompt")
    c.add_argument("--env", action="append", default=[], help="cli/glm: extra environment NAME=value for every run, e.g. CARGO_BUILD_JOBS=6")
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--ignore-limit", action="store_true",
                   help="skip the usage-limit and parallel-cap checks (a limit that lifted early)")
    f = sub.add_parser("followup")
    f.add_argument("--slug", required=True)
    f.add_argument("--prompt-file", required=True)
    f.add_argument("--mode", choices=["agent", "plan"], default="agent")
    f.add_argument("--ignore-limit", action="store_true",
                   help="skip the usage-limit and parallel-cap checks (a limit that lifted early)")
    w = sub.add_parser("wait")
    w.add_argument("--slug", required=True)
    w.add_argument("--timeout", type=int, default=3 * 3600)
    w.add_argument("--stall", type=int, default=STALL_S,
                   help="cli: stop a run silent this many seconds with nothing in flight and no result")
    w.add_argument("--tool-timeout", type=int, default=TOOL_S,
                   help="cli: stop a run when one tool call runs this many seconds")
    w.add_argument("--result-grace", type=int, default=RESULT_GRACE_S,
                   help="cli: seconds a run may stay alive after reporting its result")
    w.add_argument("--rate-wait", type=int, default=600,
                   help="cli: seconds to wait before retrying a provider rate limit")
    w.add_argument("--rate-retries", type=int, default=2,
                   help="cli: how many times to retry a provider rate limit")
    for name in ("status", "fetch", "usage", "cancel", "archive", "scrub"):
        sub.add_parser(name).add_argument("--slug", required=True)
    gt = sub.add_parser("gates")
    gt.add_argument("--slug", required=True)
    gt.add_argument("--ref", help="check this commit instead of the fetched head (e.g. a subagent's branch)")
    lk = sub.add_parser("locked")
    lk.add_argument("--slug", required=True)
    lk.add_argument("--ref", help="check this commit instead of the fetched head (e.g. a subagent's branch)")
    mk = sub.add_parser("mark")
    mk.add_argument("--slug", required=True)
    mk.add_argument("--status", choices=["FINISHED", "ERROR", "STALLED", "CANCELLED"], required=True)
    lg = sub.add_parser("log")
    lg.add_argument("--slug", required=True)
    for col in ("phase", "decision", "why", "evidence", "result"):
        lg.add_argument(col)
    rb = sub.add_parser("review-brief")
    rb.add_argument("--slug", required=True)
    rb.add_argument("--base", help="the commit the change starts from, when the slug has no executor loop")
    rb.add_argument("--head", help="the commit to review (default: the head `fetch` recorded)")
    rb.add_argument("--risk", action="store_true",
                    help="auth, money, privacy or outside calls: dispatch a second finder with a security pass")
    rb.add_argument("--hotfix", action="store_true",
                    help="a hotfix: the diff only, P0 and P1 only, on the strongest model")
    rep = sub.add_parser("report")
    rep.add_argument("--slug", required=True)
    rep.add_argument("--head", help="the shipped commit (default: HEAD of this checkout, the branch that ships)")
    rep.add_argument("--into", help="write the report into this checkout of the repository")
    fn = sub.add_parser("finish")
    fn.add_argument("--slug", required=True)
    fn.add_argument("--head", help="the shipped commit (default: the head `fetch` recorded)")
    fn.add_argument("--findings-only", action="store_true",
                    help="a findings-only review changes nothing, so no run report is needed")
    a = sub.add_parser("artifacts")
    a.add_argument("--slug", required=True)
    a.add_argument("--download", action="store_true")
    args = p.parse_args(argv)
    handler = globals()[f"cmd_{args.cmd.replace('-', '_')}"]
    try:
        return handler(args)
    except LoopError as exc:
        print(f"keryx: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
