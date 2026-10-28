"""Fresh checkouts for a run, for scoring and for validation, and the hidden checks run in them."""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from keryx_bench.case import Case

NO_PUSH_URL = "no-push://disabled"
OUTPUT_TAIL = 4000


@dataclass(frozen=True)
class Workspace:
    root: Path
    repo: Path
    run_id: str
    branch: str


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    exit_code: int
    seconds: float
    output_tail: str
    tests_passed: int | None = None  # diagnostic only: the check's pass/fail is what scores
    tests_failed: int | None = None


_PYTEST = re.compile(r"^=*\s*(?:(\d+) failed, )?(\d+) passed(?:, (\d+) failed)?", re.M)
_CARGO = re.compile(r"^test result: \w+\. (\d+) passed; (\d+) failed;", re.M)
_JEST = re.compile(r"^Tests:\s+(?:(\d+) failed, )?(?:\d+ skipped, )?(\d+) passed, \d+ total", re.M)
_VITEST = re.compile(r"^\s*Tests\s+(?:(\d+) failed \| )?(\d+) passed", re.M)


def count_tests(output: str) -> tuple[int, int] | None:
    """(passed, failed) from a pytest, cargo test, jest or vitest summary; None when there is none."""
    cargo = _CARGO.findall(output)
    if cargo:
        return sum(int(p) for p, _ in cargo), sum(int(f) for _, f in cargo)
    for pattern in (_JEST, _VITEST):
        found = pattern.findall(output)
        if found:
            failed, passed = found[-1]
            return int(passed), int(failed or 0)
    found = _PYTEST.findall(output)
    if found:
        failed_before, passed, failed_after = found[-1]
        return int(passed), int(failed_before or failed_after or 0)
    return None


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _clone(source: str | Path, dest: Path) -> None:
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--no-checkout", str(source), str(dest)], check=True, capture_output=True)
    for remote in _git(dest, "remote").split():
        _git(dest, "remote", "set-url", "--push", remote, NO_PUSH_URL)


def _sealed_fetch(source: str, dest: Path, sha: str, branch: str) -> None:
    """A repo holding only `sha` and its ancestors, plus the tags already reachable from it.

    Later commits (the known good result, other branches) are never fetched, so the system under
    test cannot read the answer from history; the remote points nowhere, so it cannot fetch it either.
    """
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    dest.mkdir(parents=True)
    _git(dest, "init", "-q")
    subprocess.run(["git", "-C", str(dest), "fetch", "-q", "--no-tags", str(source), sha], check=True,
                   capture_output=True)
    if Path(source).is_dir():
        tags = _git(Path(source), "tag", "--merged", sha).split()
        if tags:
            refspecs = [f"refs/tags/{t}:refs/tags/{t}" for t in tags]
            subprocess.run(["git", "-C", str(dest), "fetch", "-q", "--no-tags", str(source), *refspecs],
                           check=True, capture_output=True)
    _git(dest, "checkout", "-q", "-B", branch, sha)
    (dest / ".git" / "FETCH_HEAD").unlink(missing_ok=True)  # it names the source repository
    _git(dest, "remote", "add", "origin", NO_PUSH_URL)
    _git(dest, "remote", "set-url", "--push", "origin", NO_PUSH_URL)


def prepare_workspace(case: Case, runs_root: Path, run_id: str) -> Workspace:
    root = Path(runs_root) / run_id / case.id
    repo = root / "repo"
    branch = f"bench/{run_id}"
    _sealed_fetch(case.repo, repo, case.base, branch)
    return Workspace(root=root, repo=repo, run_id=run_id, branch=branch)


def tree_at(case: Case, dest: Path, ref: str) -> Path:
    _clone(case.repo, dest)
    _git(dest, "checkout", "-q", "--detach", ref)
    return dest


def result_checkout(ws: Workspace, name: str) -> Path:
    head = _git(ws.repo, "rev-parse", f"refs/heads/{ws.branch}")
    dest = ws.root / name
    _clone(ws.repo, dest)
    _git(dest, "checkout", "-q", "--detach", head)
    return dest


def apply_hidden(tree: Path, case: Case) -> list[Path]:
    copied = []
    for src in sorted(p for p in case.hidden_dir.rglob("*") if p.is_file()):
        dest = Path(tree) / src.relative_to(case.hidden_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(dest)
    return copied


def _shell(command: str, cwd: Path, env: Mapping[str, str], timeout_s: int) -> tuple[int, str, float]:
    start = time.monotonic()
    proc = subprocess.Popen(command, shell=True, cwd=cwd, env=dict(env), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        output, _ = proc.communicate(timeout=timeout_s)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        output, _ = proc.communicate()
        output = (output or "") + f"\n[timed out after {timeout_s}s]"
        code = -9
    return code, output or "", time.monotonic() - start


def check_env(case: Case, env: Mapping[str, str] | None = None) -> dict[str, str]:
    # Checks run the system's own code, so they get the same guard rails as the session.
    from keryx_bench.safety import safe_env

    return {**safe_env(os.environ, {**case.env, **(env or {})}), **case.check_env}


def run_prepare(tree: Path, case: Case, env: Mapping[str, str] | None = None) -> None:
    if not case.prepare:
        return
    code, output, _ = _shell(case.prepare, Path(tree), check_env(case, env), timeout_s=3600)
    if code != 0:
        raise RuntimeError(f"prepare failed in {tree} (exit {code}): {output[-OUTPUT_TAIL:]}")


def run_checks(tree: Path, case: Case, env: Mapping[str, str] | None = None) -> list[CheckResult]:
    merged = check_env(case, env)
    results = []
    for check in case.checks:
        code, output, seconds = _shell(check.run, Path(tree), merged, check.timeout_s)
        counts = count_tests(output)
        results.append(CheckResult(name=check.name, passed=code == 0, exit_code=code, seconds=round(seconds, 3),
                                   output_tail=output[-OUTPUT_TAIL:],
                                   tests_passed=counts[0] if counts else None,
                                   tests_failed=counts[1] if counts else None))
    return results


def _names(command: str, path: str) -> bool:
    return path + "/" in command or path + " " in command or command.endswith(path)


def stop_strays(root: Path, grace_s: float = 3.0, also: Sequence[str] = ()) -> list[int]:
    """Stops processes whose command line names this run's directory, such as a detached executor, or one
    of the paths in `also` (the run's own scratch outside it, such as a database server under /tmp).

    Executors started in the background can outlive the session that started them; only processes tied to
    `root` or `also` are touched, never another session's.
    """
    paths = [str(Path(root).resolve()), *also]
    # POSIX form plus -ww: BSD-style `-axo` lists no other processes under Linux procps, and piped procps output
    # is cut at the terminal width, which drops the run directory from long command lines.
    listing = subprocess.run(["ps", "-ww", "-eo", "pid=,args="], capture_output=True, text=True).stdout
    pids = []
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        tied = any(_names(command, p) for p in paths)
        if tied and pid.isdigit() and int(pid) != os.getpid():
            pids.append(int(pid))
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + grace_s
    for pid in pids:
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return pids


@contextlib.contextmanager
def cache_lock(cache_dir: str | None) -> Iterator[None]:
    """One scoring or validation tree at a time per shared build cache, across threads and processes.

    Cargo judges local sources fresh by modification time, so two trees building into one target
    directory at once could test each other's artifacts.
    """
    if not cache_dir:
        yield
        return
    lock = Path(cache_dir).expanduser().with_name(Path(cache_dir).name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def score_lock(case: Case):
    return cache_lock(case.check_env.get("CARGO_TARGET_DIR"))
