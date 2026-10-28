#!/usr/bin/env python3
"""keryx Cursor adapter: drive one Cursor implementer per slice from the coordinator's session.

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

The ladder of executors a machine has, in the order to try them, is saved once with `setup`;
after a failed run, `create` on the same slug hands it to the next executor (the last rung is
"inline": the coordinator writes the code itself).

State lives in <git-common-dir>/cursor-loop/<slug>/ so it is per repository,
shared by its worktrees, and never committed.

Usage (run from inside the target repository):
  cursor.py preflight [--runner cli|cloud|glm|subagent]
  cursor.py setup     [--executors LIST] [--detect]   (save this machine's ladder; probe what works here)
  cursor.py executors [--after RUNNER]                (the saved ladder; the next executor after a runner)
  cursor.py remember [--repo] NOTE                   (keep a choice or trap for later runs; never a secret)
  cursor.py recall                                   (print the user's and this repository's keryx memory)
  cursor.py mark --slug S --status STATUS            (close a subagent round: FINISHED, ERROR, STALLED, CANCELLED)
  cursor.py models    [--runner cli|cloud|glm]
  cursor.py create    --slug S --prompt-file F [--runner cli|cloud|glm|subagent] [--model ID] [--ref REF]
                    [--env NAME=value]... [--param id=value]... [--mode agent|plan] [--image P]...
                    [--escalate]
                    (local runners only: --env; cloud-only: --param --image; on a failed run,
                    re-create switches to the new executor on the same slug; --escalate also takes
                    over a finished one)
  cursor.py followup  --slug S --prompt-file F [--mode agent|plan]
  cursor.py wait      --slug S [--timeout SECONDS]
  cursor.py status    --slug S
  cursor.py fetch     --slug S
  cursor.py gates     --slug S [--ref REF]  (did the run touch an architecture or CI gate file?)
  cursor.py locked    --slug S [--ref REF]  (check locked test blocks against the implementer's head;
                    --ref checks a commit `fetch` cannot read, e.g. a subagent's branch)
  cursor.py mark      --slug S --status FINISHED|ERROR|STALLED|CANCELLED   (record a subagent round's outcome)
  cursor.py cancel    --slug S
  cursor.py scrub     --slug S                (cli: strip Cursor's attribution trailer from local commits)
  cursor.py artifacts --slug S [--download]   (cloud)
  cursor.py usage     --slug S                (cloud)
  cursor.py archive   --slug S                (cloud)
  cursor.py log       --slug S PHASE DECISION WHY EVIDENCE RESULT   (the coordinator's own row)

Every command that changes loop state appends a row to <state>/decisions.tsv (one tab-separated row
per decision); the coordinator adds its own rows with `cursor.py log`.

Cloud runner: the API key comes from $CURSOR_API_KEY or the macOS keychain item
"cursor-api-key"; it is never printed or written to disk by this script.
CLI runner: uses the CLI's own login (`agent login`).
GLM runner: the plan key comes from $GLM_API_KEY or ~/.config/glm/coding-plan.key; it is never printed
or written into the state dir by this script.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import fnmatch
import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("CURSOR_API_BASE", "https://api.cursor.com")
USER_AGENT = "cursor-loop/0.2"
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
    "GIT_CONFIG_VALUE_0": "https://push-disabled.invalid/cursor-loop",
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
    # Seen 2026-10-25: a GLM run printed the non-secret lines of a checkout's .env.local while debugging.
    "Read(**/.env)", "Read(**/.env.*)", "Read(//**/.env)", "Read(//**/.env.*)", "Edit(**/.env*)", "Edit(//**/.env*)",
    "Bash(cp *.env*)", "Bash(cat *.env*)", "Bash(grep *.env*)", "Bash(source *.env*)",
]


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


def state_root() -> Path:
    return common_dir() / "cursor-loop"


def slug_dir(slug: str, *, must_exist: bool = True) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}", slug):
        raise LoopError("slug must be lowercase letters, digits and dashes (2-61 chars)")
    d = state_root() / slug
    if must_exist and not (d / "agent.json").exists():
        raise LoopError(f"no loop state for {slug!r} at {d} (run `create` first)")
    return d


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


def current_round(d: Path) -> Path:
    rs = rounds(d)
    if not rs:
        raise LoopError(f"{d} has no rounds")
    return rs[-1]


def new_round(d: Path, prompt_file: str) -> Path:
    r = d / "rounds" / f"{len(rounds(d)) + 1:02d}"
    r.mkdir(parents=True, exist_ok=False)
    (r / "prompt.md").write_text(Path(prompt_file).read_text())
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
        if key in ("KUBECONFIG", "SSH_AUTH_SOCK", "PATH", "EXIT_FILE", "CURSOR_CONFIG_DIR") or key.startswith(
                ("GIT_CONFIG", "ANTHROPIC", "CLAUDE", "GLM_")):
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
    return squash_ws(block) in squash_ws(file_text)


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


def write_glm_config(d: Path) -> Path:
    """A config dir of its own (no user memory, skills, hooks, plugins or MCP servers), attribution off, denies."""
    cfg_dir = d / "claude-config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    settings = {"attribution": {"commit": "", "pr": "", "sessionUrl": False}, "autoMemoryEnabled": False,
                "permissions": {"deny": GLM_DENY}}
    (cfg_dir / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return cfg_dir


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


def usage_limit(text: str) -> dict | None:
    """Read a usage-limit message a run already printed: {"kind", "resetsAt", "resetsIn"}, else None.

    Never probes anything: the GLM (Z.ai) and Cursor messages are the only two recognised."""
    m = GLM_LIMIT.search(text or "")
    if m:
        local = dt.datetime.strptime(m.group("at"), "%Y-%m-%d %H:%M:%S")
        return {"kind": m.group("kind") or m.group("span").lower(),
                "resetsAt": (local - GLM_UTC_OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "resetsIn": None}
    m = CURSOR_LIMIT.search(text or "")
    if m:
        return {"kind": m.group("kind").lower(), "resetsAt": None, "resetsIn": m.group("span")}
    return None


def round_usage_limit(r: Path) -> dict | None:
    """The usage limit a finished round ran into, from its own report (result.md, stderr.log) only: the event
    log can quote a limit message from a file the executor read."""
    texts = []
    for name in ("result.md", "stderr.log"):
        if (r / name).exists():
            texts.append((r / name).read_text(errors="replace"))
    for text in texts:
        found = usage_limit(text)
        if found:
            return found
    return None


def report_usage_limit(d: Path, r: Path, limit: dict) -> None:
    when = f"resets at {limit['resetsAt']}" if limit.get("resetsAt") else f"resets in {limit['resetsIn']}"
    print(f"USAGE_LIMIT  {limit['kind']} limit; {when}")
    print("      reset within ~45 min: wait, then followup on this slug (or create on it again if followup finds "
          "no session); later: the next rung (cursor.py executors --after RUNNER; inline means you)")
    append_log(d, "dispatch", f"round {r.name}: usage limit ({limit['kind']})", "the executor reported its limit",
               f"{r / 'result.md'}", when)


SETUP_NOTE = ("keryx is not set up on this machine: run `cursor.py setup --detect`, then ask the owner "
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
        return state_root() / "memory.md"
    except LoopError:
        return None


def parse_executors(text: str) -> list[str]:
    """Comma-separated executor names: whitespace stripped, duplicates dropped keeping the first."""
    out: list[str] = []
    for name in (part.strip() for part in text.split(",")):
        if not name:
            continue
        if name not in EXECUTORS:
            raise LoopError(f"unknown executor {name!r}; choose from {', '.join(EXECUTORS)}")
        if name not in out:
            out.append(name)
    if not out:
        raise LoopError("no executors in the list")
    return out


def load_config(environ: dict) -> dict:
    """The saved ladder, or the Claude subagent alone when it was never saved."""
    path = config_path(environ)
    if not path.exists():
        return {"executors": ["subagent"]}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise LoopError(f"{path} is not valid JSON: {exc}") from exc
    names = data.get("executors") if isinstance(data, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise LoopError(f'{path}: "executors" must be a list of names')
    try:
        ladder = parse_executors(",".join(names))
    except LoopError as exc:
        raise LoopError(f"{path}: {exc}") from exc
    return {"executors": ladder}


def next_executor(ladder: list[str], current: str) -> str:
    """The executor to try after `current`: the next rung, the first rung for a runner outside the
    ladder, and "inline" (the coordinator writes the code itself) after the last."""
    if current not in ladder:
        return ladder[0]
    rest = ladder[ladder.index(current) + 1:]
    return rest[0] if rest else "inline"


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
    events; Claude Code puts tool_use parts in assistant messages and tool_result parts in user messages."""
    kind = event.get("type")
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
    """One progress line for a CLI stream-json event (https://cursor.com/docs/cli/reference/output-format)."""
    kind = event.get("type")
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


# ---------------------------------------------------------------- cli runner


def worktree_path(slug: str, runner: str = "cli") -> Path:
    top = Path(git("rev-parse", "--show-toplevel", cwd=common_dir().parent))
    return top / ".worktrees" / f"{WORKTREE_PREFIX.get(runner, 'cursor')}-{slug}"


def ensure_excluded(pattern: str) -> None:
    exclude = common_dir() / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    if pattern not in lines:
        with exclude.open("a") as fh:
            fh.write(("\n" if lines and lines[-1] else "") + pattern + "\n")


ATTRIBUTION_TRAILER = re.compile(
    r"(?im)^(co-authored-by:[^\n]*(cursor|claude|anthropic|glm|z\.ai|zhipu)[^\n]*|made with cursor[^\n]*"
    r"|\W*generated with \[?claude code[^\n]*)\n?")


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
    cfg = workspace / ".cursor" / "cli.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(cfg.read_text()) if cfg.exists() else {}
    perms = data.setdefault("permissions", {})
    perms.setdefault("allow", [])
    perms["deny"] = sorted(set(perms.get("deny", [])) | set(CLI_DENY))
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


def cli_launch(d: Path, r: Path, agent: dict, prompt: str, mode: str) -> int:
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


def cmd_preflight(args) -> int:
    if args.runner == "subagent":
        # The coordinator's own Claude session runs it; there is nothing on this machine to check.
        print("ok    Claude subagent: the coordinator dispatches it with the keryx executor agent")
        return 0
    problems = 0
    repo = ""
    if args.runner == "cloud":  # only a cloud agent clones from GitHub; a local run works in any checkout
        try:
            repo = normalize_repo_url(git("remote", "get-url", "origin"))
            print(f"ok    origin = {repo}")
        except LoopError as exc:
            print(f"FAIL  {exc}")
            return 1
    if args.runner == "glm":
        return _preflight_glm()
    if args.runner == "cli":
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
    probe = state_root() / "_glm-preflight"
    cfg = write_glm_config(probe)
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


def cmd_setup(args) -> int:
    environ = dict(os.environ)
    if args.executors:
        ladder = parse_executors(args.executors)
        save_json(config_path(environ), {"executors": ladder, "updatedAt": now()})
        print(config_path(environ))
    if args.detect:
        _detect_executors()
    if not args.executors and not args.detect:
        print("\n".join(load_config(environ)["executors"]))
        print(config_path(environ))
    return 0


def cmd_executors(args) -> int:
    note = setup_note(dict(os.environ))
    if note:
        print(note, file=sys.stderr)
    ladder = load_config(dict(os.environ))["executors"]
    print(next_executor(ladder, args.after) if args.after else "\n".join(ladder))
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
    if agent.get("runner") in LOCAL_RUNNERS:
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


def block_pushes(wt: Path) -> None:
    """A subagent's worktree cannot push: a per-worktree push URL for origin (even before that remote
    exists) and every configured remote, under extensions.worktreeConfig — never the main worktree's
    or the shared config."""
    if not git("config", "--get", "extensions.worktreeConfig", check=False):
        git("config", "extensions.worktreeConfig", "true")
    for name in ["origin"] + [r for r in git("remote").split() if r != "origin"]:
        git("config", "--worktree", f"remote.{name}.pushurl", "https://push-disabled.invalid/keryx", cwd=wt)


def _refuse_subagent(agent: dict) -> None:
    """`wait` and `cancel` have no process to act on: a subagent reports to the coordinator."""
    if agent.get("runner") == "subagent":
        raise LoopError("a Claude subagent reports to the coordinator; there is nothing to wait for")


def cmd_create(args) -> int:
    d = slug_dir(args.slug, must_exist=False)
    switch = _switch_plan(d, args.slug, args.runner, args.escalate) if (d / "agent.json").exists() else None
    if switch:
        # A handover keeps the loop's base and ignores --ref entirely: it does not even resolve it.
        start, base_sha = switch["start"], switch["baseSha"]
        if args.runner == "cloud" and start != base_sha:
            raise LoopError(f"the cloud runner clones from GitHub and cannot start from {start[:12]}, which "
                            "exists only on this machine; switch to a local rung (cli, glm or subagent) instead")
    else:
        start = base_sha = pin_base(args.ref)
    if args.runner in LOCAL_RUNNERS:
        if args.param or args.image:
            raise LoopError("--param and --image are cloud-runner options")
        glm = args.runner == "glm"
        sub = args.runner == "subagent"
        model = args.model or ("sonnet" if sub else DEFAULT_GLM_MODEL if glm else DEFAULT_CLI_MODEL)
        read_prompt(args.prompt_file)
        wt = worktree_path(args.slug, args.runner)
        branch = f"{WORKTREE_PREFIX[args.runner]}/{args.slug}"
        if args.dry_run:
            shown = (f"keryx:executor with worktree {wt}" if sub
                     else glm_command(model, "<prompt>", None, args.mode, str(d / "claude-config" / "settings.json")) if glm
                     else cli_command(model, str(wt), "<prompt>", None, args.mode))
            print(json.dumps({"runner": args.runner, "worktree": str(wt), "branch": branch, "base": start,
                              "model": model, "command": shown}, indent=2))
            return 0
        extra_env = parse_env(args.env)
        if glm:
            glm_env(dict(os.environ), "")  # no key, or a wrong endpoint: fail before a worktree exists
        if switch:
            _reuse_worktree(wt, branch, start)
        else:
            if wt.exists():
                raise LoopError(f"{wt} already exists")
            git("worktree", "add", "-b", branch, str(wt), start)
        if args.runner == "cli":
            write_cli_permissions(wt)
        if sub:
            block_pushes(wt)
        if switch:
            # Everything that can fail has succeeded; only now does the loop change hands.
            _archive_switch(d, switch, args.runner)
        if sub:
            agent = {"slug": args.slug, "runner": "subagent", "workspace": str(wt), "branch": branch,
                     "baseSha": base_sha, "baseRef": (switch or {}).get("baseRef", args.ref),
                     "model": model, "createdAt": now()}
            save_json(d / "agent.json", agent)
            r = new_round(d, args.prompt_file)
            save_json(r / "run.json", {"status": "DISPATCHED", "startedAt": now()})
            append_log(d, "dispatch", f"run {r.name}: prepared a Claude subagent "
                                      f"(dispatch keryx:executor with worktree {wt})", "cursor-loop create",
                       f"branch {branch}, base {start[:12]}", "DISPATCHED")
            print(f"run {r.name} prepared: dispatch keryx:executor with worktree {wt}\nbranch   {branch}")
            return 0
        agent = {"slug": args.slug, "runner": args.runner, "workspace": str(wt), "branch": branch, "baseSha": base_sha,
                 "baseRef": (switch or {}).get("baseRef", args.ref), "model": model, "sessionId": None,
                 "createdAt": now(), "env": extra_env,
                 "configDir": str(write_glm_config(d) if glm else write_cli_config(d))}
        save_json(d / "agent.json", agent)
        r = new_round(d, args.prompt_file)
        pid = cli_launch(d, r, agent, read_prompt(args.prompt_file), args.mode)
        who = "GLM (Claude Code on the GLM Coding Plan)" if glm else "Cursor CLI"
        append_log(d, "dispatch", f"run {r.name}: started {who} ({args.mode} mode, model {model})", "cursor-loop create",
                   f"pid {pid}, worktree {wt}, branch {branch}, base {start[:12]}", "RUNNING")
        print(f"run {r.name} started: pid {pid}\nworktree {wt}\nbranch   {branch}\nevents   {r / 'events.ndjson'}")
        return 0
    body: dict = {
        "prompt": prompt_payload(args.prompt_file, args.image),
        "repos": [{"url": normalize_repo_url(git("remote", "get-url", "origin")), "startingRef": start}],
        "workOnCurrentBranch": False,
        "autoCreatePR": False,
        "mode": args.mode,
        "name": f"cursor-loop: {args.slug}"[:100],
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
    if switch:
        _archive_switch(d, switch, args.runner)
    save_json(d / "agent.json", {
        "slug": args.slug, "runner": "cloud", "agentId": agent["id"], "url": agent.get("url"),
        "repo": body["repos"][0]["url"], "baseSha": base_sha,
        "baseRef": (switch or {}).get("baseRef", args.ref), "model": args.model,
        "modelParams": args.param, "createdAt": now(),
    })
    r = new_round(d, args.prompt_file)
    save_json(r / "run.json", run)
    append_log(d, "dispatch", f"run {r.name}: created cloud agent ({args.mode} mode, model {args.model or 'default'})",
               "cursor-loop create", f"agent {agent['id']} run {run['id']} base {base_sha[:12]} {agent.get('url', '')}",
               str(run.get("status")))
    print(f"agent {agent['id']}  run {run['id']}  status {run.get('status')}\n{agent.get('url', '')}")
    return 0


def cmd_followup(args) -> int:
    d = slug_dir(args.slug)
    agent = load_agent(d)
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
                   "cursor-loop followup", f"round {r.name}, branch {agent['branch']}", "DISPATCHED")
        print(f"run {r.name} prepared: dispatch keryx:executor with worktree {agent['workspace']}")
        return 0
    if agent.get("runner") in LOCAL_RUNNERS:
        prev = current_round(d)
        if not (prev / "exit.code").exists() and pid_alive(json.loads((prev / "run.json").read_text())["pid"]):
            raise LoopError(f"run {prev.name} is still going; `wait` for it or `cancel` it first")
        if not agent.get("sessionId"):
            raise LoopError("no session id recorded yet; run `wait` on the previous run first")
        r = new_round(d, args.prompt_file)
        pid = cli_launch(d, r, agent, read_prompt(args.prompt_file), args.mode)
        append_log(d, "dispatch", f"run {r.name}: follow-up ({args.mode} mode)", "cursor-loop followup",
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
    append_log(d, "dispatch", f"run {r.name}: follow-up ({args.mode} mode)", "cursor-loop followup",
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
                    if calls or event.get("type") == "result":
                        seen.append(event)
                    for action, call_id, command in calls:
                        if action == "start":
                            # Claude Code's events carry no timestamps: a call counts from when wait read it.
                            started = (event.get("timestamp_ms") or time.time() * 1000) / 1000
                            in_flight[call_id] = (started, command)
                        else:
                            in_flight.pop(call_id, None)
                    if event.get("type") == "result":
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
        last = next((e for e in reversed(events_all) if e.get("type") == "result"), {})
        code = 0 if not last.get("is_error") else 1
    outcome = cli_outcome(events_all, code)
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
    if limit:
        report_usage_limit(d, r, limit)
    if is_stalled:
        print("the executor stopped talking without a final report; its commits are on the branch above: "
              "fetch and check them, and follow up for anything missing")
        return 4
    return 0 if outcome["status"] == "FINISHED" else (3 if timed_out else 2)


def cmd_wait(args) -> int:
    d = slug_dir(args.slug)
    agent = load_agent(d)
    _refuse_subagent(agent)
    if agent.get("runner") in LOCAL_RUNNERS:
        return _wait_cli(d, args)
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
    if agent.get("runner") in LOCAL_RUNNERS:
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
    if agent.get("runner") in LOCAL_RUNNERS:
        branch = agent["branch"]
        head = git("rev-parse", "HEAD", cwd=agent["workspace"])
        git("update-ref", f"refs/cursor-loop/{args.slug}", head)
        dirty = git("status", "--porcelain", cwd=agent["workspace"])
        if dirty:
            print("WARN  the worktree has uncommitted changes; only commits are reviewed:\n" + dirty)
    else:
        branch = branch_of(d)
        if branch in ("main", "master") or not branch.startswith("cursor/"):
            print(f"WARN  agent branch is {branch!r}, not a cursor/* branch")
        git("fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/cursor-loop/{args.slug}")
        head = git("rev-parse", f"refs/cursor-loop/{args.slug}")
    (d / "head.txt").write_text(head + "\n")
    print(f"branch {branch}\nhead   {head}\nbase   {agent['baseSha']}\nref    refs/cursor-loop/{args.slug}")
    print(git("diff", "--stat", f"{agent['baseSha']}...{head}"))
    append_log(d, "review", f"round {current_round(d).name}: read the implementer's head on {branch}",
               "review needs the implementer's head", f"refs/cursor-loop/{args.slug} = {head}", "fetched")
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
        raise LoopError("run `fetch` first")
    return head


def cmd_gates(args) -> int:
    """Did the run touch a gate file (architecture, lint, dependency or CI configuration)? Those are
    the owner's call, not the executor's."""
    d = slug_dir(args.slug)
    base = load_agent(d)["baseSha"]
    head = resolve_head(d, args.ref)
    globs = list(DEFAULT_GATE_GLOBS)
    extra = d / "gates.txt"
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
    specs = sorted((d / "locked").glob("*.json"))
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
    if agent.get("runner") not in LOCAL_RUNNERS:
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
    if agent.get("runner") in LOCAL_RUNNERS:
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
    append_log(state_root() / args.slug, args.phase, args.decision, args.why, args.evidence, args.result)
    print(state_root() / args.slug / "decisions.tsv")
    return 0


def cmd_remember(args) -> int:
    if looks_secret(args.note):
        raise LoopError("that note looks like a credential; keryx memory never stores secrets")
    path = memory_file("repo" if args.repo else "user", dict(os.environ))
    if path is None:
        raise LoopError("--repo needs a git repository")
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
        if path is None or not path.exists():
            continue
        print(f"# keryx memory ({title})")
        print(path.read_text().rstrip("\n"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="cursor.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("preflight")
    pf.add_argument("--runner", choices=["cli", "cloud", "glm", "subagent"], default="cli")
    su = sub.add_parser("setup")
    su.add_argument("--executors", metavar="LIST", help="save this executor order, e.g. cli,glm,subagent")
    su.add_argument("--detect", action="store_true", help="print one line per executor: can this machine run it?")
    ex = sub.add_parser("executors")
    ex.add_argument("--after", metavar="RUNNER", help="print only the executor after this one (inline = the coordinator)")
    rm = sub.add_parser("remember")
    rm.add_argument("--repo", action="store_true", help="save for this repository only")
    rm.add_argument("note")
    sub.add_parser("recall")
    mo = sub.add_parser("models")
    mo.add_argument("--runner", choices=["cli", "cloud", "glm"], default="cli")
    c = sub.add_parser("create")
    c.add_argument("--slug", required=True)
    c.add_argument("--prompt-file", required=True)
    c.add_argument("--runner", choices=list(LOCAL_RUNNERS) + ["cloud"], default="cli")
    c.add_argument("--model")
    c.add_argument("--param", action="append", default=[], help="cloud: model parameter id=value, e.g. reasoning_effort=xhigh")
    c.add_argument("--ref", default="main")
    c.add_argument("--escalate", action="store_true",
                   help="also take over a FINISHED round: escalate to the next executor")
    c.add_argument("--mode", choices=["agent", "plan"], default="agent")
    c.add_argument("--image", action="append", default=[], help="cloud: image for the prompt")
    c.add_argument("--env", action="append", default=[], help="cli/glm: extra environment NAME=value for every run, e.g. CARGO_BUILD_JOBS=6")
    c.add_argument("--dry-run", action="store_true")
    f = sub.add_parser("followup")
    f.add_argument("--slug", required=True)
    f.add_argument("--prompt-file", required=True)
    f.add_argument("--mode", choices=["agent", "plan"], default="agent")
    w = sub.add_parser("wait")
    w.add_argument("--slug", required=True)
    w.add_argument("--timeout", type=int, default=3 * 3600)
    w.add_argument("--stall", type=int, default=STALL_S,
                   help="cli: stop a run silent this many seconds with nothing in flight and no result")
    w.add_argument("--tool-timeout", type=int, default=TOOL_S,
                   help="cli: stop a run when one tool call runs this many seconds")
    w.add_argument("--result-grace", type=int, default=RESULT_GRACE_S,
                   help="cli: seconds a run may stay alive after reporting its result")
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
    a = sub.add_parser("artifacts")
    a.add_argument("--slug", required=True)
    a.add_argument("--download", action="store_true")
    args = p.parse_args(argv)
    handler = globals()[f"cmd_{args.cmd}"]
    try:
        return handler(args)
    except LoopError as exc:
        print(f"cursor-loop: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
