# keryx bench v0 Implementation Plan

> **For agentic workers:** implement task by task, in order. Steps use checkbox (`- [ ]`) syntax for tracking. The locked tests are exact code: add them first, see them fail for the stated reason, never change them.

**Goal:** a replay benchmark that runs a coordinator setup on cases with a known good outcome and scores quality, speed and cost — then measures today's setup as the baseline keryx v1 must hold.

**Architecture:** Python package `keryx_bench` under `bench/`. A case is a directory (`case.yaml`, `prompt.md`, `owner.yaml`, `hidden/`) kept outside the workspace. The runner clones the case's repo at its base commit, runs the system under test through the Claude Agent SDK with personal settings, connectors and memory switched off, answers its questions from the owner's scripted answers, then scores the committed result with the hidden checks. Results and private cases live outside the repo.

**Tech Stack:** Python ≥ 3.12 (3.14 locally), `claude-agent-sdk` (0.2.174 at planning time), `PyYAML`, `pytest`; `uv` for the virtualenv.

**Spec:** `docs/design/2026-10-24-keryx-v1-design.md` (§7 Benchmark, §7.5 Baseline, §8 Repository).

**Not in this plan:** the keryx skills and loop, executor adapters, the `claude plugin eval` layer (needs a keryx plugin first), weekly live-run summaries, Codex. Each gets its own plan after the baseline numbers exist.

## Global Constraints

- No committed file names an external skill pack. Private cases, system files, results and the provenance file live outside the repo: `~/.config/keryx/` (cases, systems, forbidden-names list) and `~/.local/share/keryx/bench-results/`.
- Nothing copied from an external skill pack is committed by this plan. A baseline plugin is assembled at run time in a temp directory from local install paths.
- Dependencies: latest versions, installed with `uv pip install`, then pinned in `bench/requirements.txt` to the installed versions. No other dependency without the owner's OK.
- Commits: Conventional Commits; never name an AI assistant or tool; no co-author trailers; stage files by name, never `git add -A`.
- All work on the local branch `v1`. No push, tag push or PR without the owner's explicit go.
- The system under test never reaches infrastructure: deny rules plus a safe environment (Task 6). These are guard rails, not a sandbox.
- A run's result counts only when committed on its branch `bench/<run-id>`; uncommitted edits score nothing.
- Never print or store credentials. Transcripts stay in the private results directory.
- Unit tests make no model calls. Live tests run only with `KERYX_LIVE=1`.
- Facts checked on 2026-10-24 that the design rests on (re-check if a step behaves differently): with `setting_sources=[]` a run loads no user skills, plugins or hooks; `strict_mcp_config=True` plus `mcp_servers={}` removes the account's claude.ai connectors (otherwise they load, including the paid Product A one); `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` sets `memory_paths` to `None`; `AskUserQuestion` reaches `can_use_tool` and the returned `answers` are used; a plugin passed in `plugins` loads its skills as `<plugin>:<skill>`; each run still writes a session folder under `~/.claude/projects/` named after its cwd with every non-alphanumeric character replaced by `-`.

## Review Focus

1. **Hidden checks reachable by the agent** — the hidden directory must never be inside the workspace before scoring; otherwise the run can read the answers. Test: Task 3 `test_the_workspace_starts_at_base_without_hidden_files`.
2. **Personal setup leaking into a run** (owner skills, plugins, connectors, memory) — the arms stop being comparable and a paid connector can be called. Tests: Task 6 `test_isolation_breach_is_reported`, `test_options_isolate_the_run`; Task 8 live test asserts the loaded skills and connectors.
3. **A case that rewards doing nothing** — checks that already pass on the base. Test: Task 3 `test_a_case_whose_checks_already_pass_on_base_is_rejected`.
4. **A run that stops on a question** gets stuck or is scored as done. Tests: Task 4 `test_a_stop_that_asks_for_approval_gets_the_autonomy_answer`; Task 6 `test_resumes_are_capped_and_then_stall`; Task 7 `test_a_stalled_run_is_never_a_false_done`.
5. **Comparing different case sets or edited cases** — a verdict across mismatched cases is meaningless. Test: Task 7 `test_different_case_sets_cannot_be_compared`.

---

### Task 1: Archive the release-notes tool and scaffold `bench/`

**Files:**
- Remove (on `v1` only): `src/`, `tests/`, `Cargo.toml`, `Cargo.lock`, `clippy.toml`, `dist-workspace.toml`, `CHANGELOG.md`, `.github/`, `.claude/`, `.agent/`, `.issues/`.
- Replace: `README.md`, `AGENTS.md`, `CLAUDE.md` (identical to `AGENTS.md`), `.gitignore`.
- Keep: `LICENSE` (MIT, jacksnxly), `docs/`.
- Create: `bench/requirements.txt`, `bench/pytest.ini`, `bench/keryx_bench/__init__.py` (`__version__ = "0.0.1"`), `bench/keryx_bench/__main__.py`, `bench/tests/helpers.py`, `bench/tests/conftest.py`, `bench/tests/test_package.py`.

The last release of the old tool is already tagged `v0.6.2`; its GitHub release and installers stay as they are. `main` is not touched until the owner merges `v1`.

- [ ] **Step 1:** `git switch -c v1 design/keryx-v1`, then `git rm -r` the files listed above.
- [ ] **Step 2:** Write `README.md` (what keryx is in two sentences, status "under construction", how to run the bench tests), `AGENTS.md`/`CLAUDE.md` (the Global Constraints above that apply to anyone working in this repo, plus the test command), `.gitignore` (`.venv/`, `__pycache__/`, `.pytest_cache/`, `.DS_Store`, `bench/results/`).
- [ ] **Step 3:** `cd bench && uv venv .venv && uv pip install --python .venv/bin/python claude-agent-sdk pyyaml pytest`; write `requirements.txt` with the three installed versions (`uv pip freeze` filtered to them).
- [ ] **Step 4: Add the locked test infrastructure and the smoke test**

`bench/pytest.ini`:

```ini
[pytest]
testpaths = tests
markers =
    live: makes real model calls; runs only with KERYX_LIVE=1
```

`bench/tests/helpers.py`:

```python
import subprocess
import sys
from pathlib import Path

PYTEST = f"{sys.executable} -m pytest -q -p no:cacheprovider test_hidden.py"
GIT_ID = ["-c", "user.email=bench@example.invalid", "-c", "user.name=bench"]


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def make_toy_repo(root: Path) -> tuple[Path, str, str]:
    repo = root / "toy"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    git(repo, "add", "calc.py")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    git(repo, "commit", "-q", "-am", "fix")
    good = git(repo, "rev-parse", "HEAD")
    return repo, base, good


def write_case(case_dir: Path, repo: Path, base: str, good: str, *, mode: str = "bug",
               checks: list[tuple[str, str]] | None = None, extra: str = "",
               prompt: str = "calc.add(2, 3) returns -1; it must return 5.\n") -> Path:
    checks = checks if checks is not None else [("hidden-add", PYTEST)]
    (case_dir / "hidden").mkdir(parents=True)
    (case_dir / "hidden" / "test_hidden.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    (case_dir / "prompt.md").write_text(prompt)
    (case_dir / "owner.yaml").write_text(
        "autonomy: Commit locally on your own branch only. Do not push.\n"
        "answers:\n"
        "  - about: function name\n"
        "    answer: Keep the name add.\n"
        "default: No preference. Make the call and log it.\n")
    check_yaml = "".join(f"    - name: {n}\n      run: \"{r}\"\n      timeout_s: 120\n" for n, r in checks)
    (case_dir / "case.yaml").write_text(
        "id: toy-add\n"
        f"mode: {mode}\n"
        f"repo: {repo}\n"
        f"base: {base}\n"
        f"good: {good}\n"
        "prompt: prompt.md\n"
        "owner: owner.yaml\n"
        "hidden:\n"
        "  files: hidden\n"
        "  checks:\n"
        f"{check_yaml}"
        "budget: {timeout_min: 10, max_usd: 1.0}\n"
        + extra)
    return case_dir
```

`bench/tests/conftest.py`:

```python
import pytest

from helpers import make_toy_repo, write_case


@pytest.fixture
def toy_repo(tmp_path):
    return make_toy_repo(tmp_path)


@pytest.fixture
def toy_case(tmp_path, toy_repo):
    repo, base, good = toy_repo
    return write_case(tmp_path / "case", repo, base, good)
```

`bench/tests/test_package.py`:

```python
import keryx_bench


def test_the_package_imports():
    assert keryx_bench.__version__ == "0.0.1"
```

- [ ] **Step 5:** Run `cd bench && .venv/bin/pytest -q` — expected: FAIL with `ModuleNotFoundError: No module named 'keryx_bench'` until `__init__.py` exists; then add it (and a `__main__.py` that calls `keryx_bench.cli.main` once Task 8 exists — until then it raises `SystemExit("cli not built yet")`). Run again: `1 passed`.
- [ ] **Step 6: Commit** — `chore!: archive the release-notes tool and start the keryx bench` (body: the tool's last release stays at tag v0.6.2).

### Task 2: Case format

**Files:** Create `bench/keryx_bench/case.py`, `bench/keryx_bench/owner.py` (data types only), `bench/tests/test_case.py`.

**Interfaces:**
- Produces (`owner.py`): `@dataclass(frozen=True) Answer(about: str, answer: str)`; `@dataclass(frozen=True) OwnerScript(autonomy: str, answers: tuple[Answer, ...], default: str)`; `load_owner(path: Path) -> OwnerScript`.
- Produces (`case.py`): `MODES = ("bug", "review", "feature")`; `class CaseError(ValueError)`; frozen dataclasses `Check(name: str, run: str, timeout_s: int = 900)`, `KnownDefect(id: str, check: str)`, `Budget(timeout_min: int = 30, max_usd: float = 5.0)`, `Case(id: str, mode: str, repo: str, base: str, good: str, prompt: str, owner: OwnerScript, hidden_dir: Path, checks: tuple[Check, ...], known_defects: tuple[KnownDefect, ...], env: Mapping[str, str], prepare: str | None, budget: Budget, tags: tuple[str, ...], path: Path)`; `load_case(case_dir: Path) -> Case`; `case_hash(case: Case) -> str`.

`case.yaml` keys: `id`, `mode`, `repo` (local path or git URL), `base` and `good` (full 40-hex SHAs; for review cases `base` is the branch to review and `good` its fixed head), `prompt` and `owner` (file names in the case dir), `hidden.files` (dir in the case dir), `hidden.checks` (list of `name`/`run`/`timeout_s`), `known_defects` (review only; each `check` names a hidden check), `env`, `prepare` (optional untimed warm-up command), `budget`, `tags`. Errors name the offending key.

- [ ] **Step 1: Write the locked tests** — `bench/tests/test_case.py`:

```python
import pytest

from helpers import write_case
from keryx_bench.case import CaseError, case_hash, load_case


def test_a_valid_case_loads(toy_case):
    case = load_case(toy_case)
    assert case.id == "toy-add"
    assert case.mode == "bug"
    assert case.prompt.startswith("calc.add(2, 3)")
    assert [c.name for c in case.checks] == ["hidden-add"]
    assert case.owner.default.startswith("No preference")
    assert case.owner.answers[0].about == "function name"
    assert case.budget.timeout_min == 10


def test_an_unknown_mode_is_refused(tmp_path, toy_repo):
    repo, base, good = toy_repo
    with pytest.raises(CaseError, match="mode"):
        load_case(write_case(tmp_path / "c", repo, base, good, mode="chat"))


def test_a_short_base_sha_is_refused(tmp_path, toy_repo):
    repo, base, good = toy_repo
    with pytest.raises(CaseError, match="base"):
        load_case(write_case(tmp_path / "c", repo, base[:9], good))


def test_a_review_case_needs_known_defects(tmp_path, toy_repo):
    repo, base, good = toy_repo
    with pytest.raises(CaseError, match="known_defects"):
        load_case(write_case(tmp_path / "c", repo, base, good, mode="review"))


def test_a_known_defect_must_name_a_check(tmp_path, toy_repo):
    repo, base, good = toy_repo
    extra = "known_defects:\n  - id: wrong-sign\n    check: no-such-check\n"
    with pytest.raises(CaseError, match="no-such-check"):
        load_case(write_case(tmp_path / "c", repo, base, good, mode="review", extra=extra))


def test_the_hash_changes_when_a_hidden_file_changes(toy_case):
    before = case_hash(load_case(toy_case))
    assert case_hash(load_case(toy_case)) == before
    (toy_case / "hidden" / "test_hidden.py").write_text("def test_x():\n    assert True\n")
    assert case_hash(load_case(toy_case)) != before
```

- [ ] **Step 2:** `.venv/bin/pytest -q tests/test_case.py` — expected: FAIL, `ModuleNotFoundError: keryx_bench.case`.
- [ ] **Step 3:** Implement `owner.py` data types + `load_owner`, and `case.py` with the signatures above. `case_hash` = SHA-256 over `case.yaml`, `prompt.md`, `owner.yaml` and every file under the hidden dir (sorted relative paths, path then bytes).
- [ ] **Step 4:** `.venv/bin/pytest -q` — expected: all pass.
- [ ] **Step 5: Commit** — `feat(bench): load and hash benchmark cases`.

### Task 3: Workspaces, hidden checks and case validation

**Files:** Create `bench/keryx_bench/workspace.py`, `bench/keryx_bench/validate.py`, `bench/tests/test_workspace.py`, `bench/tests/test_validate.py`.

**Interfaces:**
- Consumes: `Case`, `load_case` (Task 2).
- Produces (`workspace.py`): `NO_PUSH_URL = "no-push://disabled"`; frozen dataclasses `Workspace(root: Path, repo: Path, run_id: str, branch: str)` and `CheckResult(name: str, passed: bool, exit_code: int, seconds: float, output_tail: str)`; `prepare_workspace(case: Case, runs_root: Path, run_id: str) -> Workspace` (root `runs_root/run_id/case.id`, repo `root/"repo"`, branch `bench/<run_id>` checked out at `case.base`, push URL of every remote set to `NO_PUSH_URL`); `tree_at(case: Case, dest: Path, ref: str) -> Path` (fresh clone checked out detached at `ref`); `result_checkout(ws: Workspace, name: str) -> Path` (fresh tree of the committed head of `ws.branch` at `ws.root/name`); `apply_hidden(tree: Path, case: Case) -> list[Path]`; `run_checks(tree: Path, case: Case, env: Mapping[str, str] | None = None) -> list[CheckResult]` (each check via the shell in `tree`, with `case.env` and `env` merged over the process env, killed at `timeout_s`, last 4,000 characters of output kept).
- Produces (`validate.py`): frozen `Validation(ok: bool, base_failed: tuple[str, ...], good_failed: tuple[str, ...], reasons: tuple[str, ...])`; `validate_case(case: Case, runs_root: Path) -> Validation`. Rules: bug/feature — at least one check fails on `base` (else reason `"every check passes on base"`); review — every known defect's check fails on `base` (else `"known defect <id> passes on base"`); all checks pass on `good` (else `"check <name> fails on good"`).

Scoring trees are always fresh checkouts; a build cache may be shared only between fresh trees, never with the system under test's own trees (a mutant or stale artifact can otherwise be linked as fresh).

- [ ] **Step 1: Write the locked tests** — `bench/tests/test_workspace.py`:

```python
import subprocess

from helpers import git
from keryx_bench.case import load_case
from keryx_bench.workspace import NO_PUSH_URL, apply_hidden, prepare_workspace, result_checkout, run_checks


def test_the_workspace_starts_at_base_without_hidden_files(toy_case, tmp_path):
    case = load_case(toy_case)
    ws = prepare_workspace(case, tmp_path / "runs", "r1")
    assert git(ws.repo, "rev-parse", "HEAD") == case.base
    assert git(ws.repo, "branch", "--show-current") == "bench/r1"
    assert not (ws.repo / "test_hidden.py").exists()
    assert ws.root not in case.hidden_dir.resolve().parents


def test_pushing_from_the_workspace_goes_nowhere(toy_case, tmp_path):
    ws = prepare_workspace(load_case(toy_case), tmp_path / "runs", "r1")
    assert git(ws.repo, "remote", "get-url", "--push", "origin") == NO_PUSH_URL
    push = subprocess.run(["git", "-C", str(ws.repo), "push", "origin", "HEAD"], capture_output=True)
    assert push.returncode != 0


def test_uncommitted_edits_score_nothing(toy_case, tmp_path):
    case = load_case(toy_case)
    ws = prepare_workspace(case, tmp_path / "runs", "r1")
    (ws.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    tree = result_checkout(ws, "score")
    apply_hidden(tree, case)
    [result] = run_checks(tree, case)
    assert result.name == "hidden-add"
    assert result.passed is False


def test_a_committed_fix_passes_the_checks(toy_case, tmp_path):
    case = load_case(toy_case)
    ws = prepare_workspace(case, tmp_path / "runs", "r1")
    (ws.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    git(ws.repo, "commit", "-q", "-am", "fix")
    tree = result_checkout(ws, "score")
    apply_hidden(tree, case)
    assert [r.passed for r in run_checks(tree, case)] == [True]
```

`bench/tests/test_validate.py`:

```python
from helpers import PYTEST, write_case
from keryx_bench.case import load_case
from keryx_bench.validate import validate_case


def test_a_case_that_fails_on_base_and_passes_on_good_is_valid(toy_case, tmp_path):
    v = validate_case(load_case(toy_case), tmp_path / "runs")
    assert v.ok, v.reasons
    assert v.base_failed == ("hidden-add",)
    assert v.good_failed == ()


def test_a_case_whose_checks_already_pass_on_base_is_rejected(tmp_path, toy_repo):
    repo, base, good = toy_repo
    case = load_case(write_case(tmp_path / "c", repo, base, good, checks=[("hidden-add", "true")]))
    v = validate_case(case, tmp_path / "runs")
    assert not v.ok
    assert "every check passes on base" in v.reasons


def test_a_case_whose_good_result_fails_is_rejected(tmp_path, toy_repo):
    repo, base, good = toy_repo
    v = validate_case(load_case(write_case(tmp_path / "c", repo, base, base)), tmp_path / "runs")
    assert not v.ok
    assert "check hidden-add fails on good" in v.reasons


def test_every_known_defect_must_fail_on_base(tmp_path, toy_repo):
    repo, base, good = toy_repo
    extra = ("known_defects:\n  - id: wrong-sign\n    check: hidden-add\n"
             "  - id: phantom\n    check: always-green\n")
    case = load_case(write_case(tmp_path / "c", repo, base, good, mode="review",
                                checks=[("hidden-add", PYTEST), ("always-green", "true")], extra=extra))
    v = validate_case(case, tmp_path / "runs")
    assert not v.ok
    assert "known defect phantom passes on base" in v.reasons
```

- [ ] **Step 2:** `.venv/bin/pytest -q tests/test_workspace.py tests/test_validate.py` — expected: FAIL, `ModuleNotFoundError: keryx_bench.workspace`.
- [ ] **Step 3:** Implement both modules with the signatures above. Clone with `git clone --no-checkout <repo> <dest>`, then `git checkout -q -B <branch> <sha>` (workspace) or `git checkout -q --detach <ref>` (trees). `result_checkout` clones the workspace repo itself, so it sees only committed history.
- [ ] **Step 4:** `.venv/bin/pytest -q` — expected: all pass.
- [ ] **Step 5: Commit** — `feat(bench): prepare workspaces and validate cases against base and good`.

### Task 4: The owner stand-in

**Files:** Modify `bench/keryx_bench/owner.py`; create `bench/tests/test_owner.py`.

**Interfaces:**
- Consumes: `OwnerScript`, `Answer` (Task 2).
- Produces: `class Matcher(Protocol): async def pick(self, question: str, script: OwnerScript) -> str | None`; `class KeywordMatcher` (first `Answer` whose every word of `about` occurs case-insensitively in the question; else `None`); `class ModelMatcher(model: str = "haiku")` (asks a cheap model through the SDK, no tools, `setting_sources=[]`, `strict_mcp_config=True`, to pick one scripted answer by number or say none — it never writes its own answer); `async def model_says_yes(question: str, text: str, model: str = "haiku") -> bool` (yes/no classifier, same isolation); `class StandIn(script: OwnerScript, matcher: Matcher)` with `interruptions: int`, `fallback: str` (= `script.autonomy + " " + script.default`), `async def answer(self, questions: list[dict]) -> dict[str, str]` (one call = one interruption; each question gets the matched answer or `fallback`), `async def on_stop(self, final_text: str, is_question: Callable[[str], Awaitable[bool]]) -> str | None` (`None` when the text is not a question; otherwise the matched answer or `fallback`, counted as one interruption).

Answers are returned as free text, which `AskUserQuestion` accepts in place of an option label.

- [ ] **Step 1: Write the locked tests** — `bench/tests/test_owner.py`:

```python
import asyncio

from keryx_bench.owner import Answer, KeywordMatcher, OwnerScript, StandIn

SCRIPT = OwnerScript(
    autonomy="Commit locally on your own branch only. Do not push.",
    answers=(Answer(about="function name", answer="Keep the name add."),),
    default="No preference. Make the call and log it.",
)


def ask(*questions):
    return [{"question": q, "header": "Q", "multiSelect": False,
             "options": [{"label": "A", "description": ""}, {"label": "B", "description": ""}]}
            for q in questions]


async def yes(text):
    return True


async def no(text):
    return False


def test_a_scripted_question_gets_its_answer():
    s = StandIn(SCRIPT, KeywordMatcher())
    answers = asyncio.run(s.answer(ask("Which function name should I use?")))
    assert answers == {"Which function name should I use?": "Keep the name add."}


def test_an_unscripted_question_gets_autonomy_and_default():
    s = StandIn(SCRIPT, KeywordMatcher())
    answers = asyncio.run(s.answer(ask("Should I also refactor the module?")))
    assert answers["Should I also refactor the module?"] == SCRIPT.autonomy + " " + SCRIPT.default


def test_one_call_with_several_questions_is_one_interruption():
    s = StandIn(SCRIPT, KeywordMatcher())
    asyncio.run(s.answer(ask("Which function name?", "Anything else?")))
    assert s.interruptions == 1


def test_a_final_report_gets_no_reply():
    s = StandIn(SCRIPT, KeywordMatcher())
    assert asyncio.run(s.on_stop("Done: add fixed, tests pass.", no)) is None
    assert s.interruptions == 0


def test_a_stop_that_asks_for_approval_gets_the_autonomy_answer():
    s = StandIn(SCRIPT, KeywordMatcher())
    reply = asyncio.run(s.on_stop("Should I push the branch and open a PR?", yes))
    assert reply == SCRIPT.autonomy + " " + SCRIPT.default
    assert s.interruptions == 1
```

- [ ] **Step 2:** `.venv/bin/pytest -q tests/test_owner.py` — expected: FAIL, `ImportError: cannot import name 'KeywordMatcher'`.
- [ ] **Step 3:** Implement the interfaces above. `ModelMatcher` and `model_says_yes` follow the Agent SDK docs (`code.claude.com/docs/en/agent-sdk/python`); they are exercised only by the live test in Task 8.
- [ ] **Step 4:** `.venv/bin/pytest -q` — expected: all pass.
- [ ] **Step 5: Commit** — `feat(bench): answer the system's questions from the owner's script`.

### Task 5: Systems under test

**Files:** Create `bench/keryx_bench/systems.py`, `bench/systems/example.yaml`, `bench/tests/test_systems.py`.

**Interfaces:**
- Produces: `class SystemConfigError(ValueError)`; frozen dataclasses `Assemble(name: str, skills: tuple[Path, ...], session_start_text: Path | None)` and `System(name: str, model: str, plugins: tuple[Path, ...], assemble: Assemble | None, entry: Mapping[str, str], env: Mapping[str, str])`; `load_system(path: Path) -> System` (expands `~`; `entry` must have `bug`, `review` and `feature`, each containing `{prompt}`; the error names the missing mode); `materialize(system: System, dest: Path) -> list[Path]` (the listed plugin dirs, plus — when `assemble` is set — a plugin built at `dest/<assemble.name>` with `.claude-plugin/plugin.json` (`{"name": ..., "version": "0.0.0", "description": ...}`), `skills/<dir name>/` copied with symlinks resolved, and, when `session_start_text` is set, `session-start.md` plus `hooks/hooks.json` whose `SessionStart` command hook prints it).

Hook file shape per the plugins reference (`code.claude.com/docs/en/plugins-reference`): a top-level `"hooks"` wrapper around the event map; the command refers to the file through `"${CLAUDE_PLUGIN_ROOT}"`. SessionStart stdout is added to the model's context (`code.claude.com/docs/en/hooks`). Plugin names must not start with `claude-`, `anthropic-` or `cc-plugin-`.

`bench/systems/example.yaml` is a template with placeholders only; real system files live in `~/.config/keryx/systems/` and are never committed.

- [ ] **Step 1: Write the locked tests** — `bench/tests/test_systems.py`:

```python
import json
from pathlib import Path

import pytest

from keryx_bench.systems import SystemConfigError, load_system, materialize


def make_skill(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test skill {name}\n---\nBody of {name}.\n")
    return d


def write_system(path: Path, skill_dirs, text_file=None) -> Path:
    lines = ["name: test-system", "model: haiku", "assemble:", "  name: assembled", "  skills:"]
    lines += [f"    - {d}" for d in skill_dirs]
    if text_file:
        lines.append(f"  session_start_text: {text_file}")
    lines += ["entry:", "  bug: '{prompt}'", "  review: '{prompt}'", "  feature: '{prompt}'"]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_system_needs_an_entry_for_every_mode(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("name: s\nmodel: haiku\nentry:\n  bug: '{prompt}'\n")
    with pytest.raises(SystemConfigError, match="review"):
        load_system(p)


def test_the_assembled_plugin_has_a_manifest_and_real_copies(tmp_path):
    real = make_skill(tmp_path / "src", "alpha")
    (tmp_path / "links").mkdir()
    (tmp_path / "links" / "alpha").symlink_to(real)
    system = load_system(write_system(tmp_path / "s.yaml", [tmp_path / "links" / "alpha"]))
    [plugin] = materialize(system, tmp_path / "out")
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "assembled"
    assert (plugin / "skills" / "alpha" / "SKILL.md").read_text().endswith("Body of alpha.\n")
    assert not any(p.is_symlink() for p in plugin.rglob("*"))


def test_session_start_text_is_wired_as_a_hook(tmp_path):
    real = make_skill(tmp_path / "src", "alpha")
    text = tmp_path / "policy.md"
    text.write_text("EVIDENCE BEFORE DONE\n")
    system = load_system(write_system(tmp_path / "s.yaml", [real], text_file=text))
    [plugin] = materialize(system, tmp_path / "out")
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text())
    assert "SessionStart" in hooks["hooks"]
    assert (plugin / "session-start.md").read_text() == "EVIDENCE BEFORE DONE\n"


def test_the_repo_names_no_external_skill_pack():
    names_file = Path.home() / ".config" / "keryx" / "forbidden-names.txt"
    if not names_file.exists():
        pytest.skip("no local forbidden-names list")
    names = [n.strip().lower() for n in names_file.read_text().splitlines() if n.strip()]
    repo = Path(__file__).resolve().parents[2]
    hits = []
    for path in repo.rglob("*"):
        if not path.is_file() or {".git", ".venv"} & set(path.parts):
            continue
        text = path.read_text(errors="ignore").lower()
        hits += [f"{path.relative_to(repo)}: {n}" for n in names if n in text]
    assert hits == []
```

- [ ] **Step 2:** `.venv/bin/pytest -q tests/test_systems.py` — expected: FAIL, `ModuleNotFoundError: keryx_bench.systems`.
- [ ] **Step 3:** Implement the interfaces above and the placeholder template.
- [ ] **Step 4:** `.venv/bin/pytest -q` — expected: all pass (the forbidden-names test skips until the coordinator creates the local list in Task 9).
- [ ] **Step 5: Commit** — `feat(bench): describe systems under test and assemble their plugin`.

### Task 6: Safety, run driver and executor usage

**Files:** Create `bench/keryx_bench/safety.py`, `bench/keryx_bench/driver.py`, `bench/keryx_bench/usage.py`, `bench/tests/test_driver.py`, `bench/tests/test_usage.py`.

**Interfaces:**
- Consumes: `Case` (2), `Workspace` (3), `StandIn` (4), `System` (5).
- Produces (`safety.py`): `DENY_RULES: tuple[str, ...]` = `Bash(git push*)`, `Bash(kubectl *)`, `Bash(helm *)`, `Bash(ssh *)`, `Bash(scp *)`, `Bash(rsync *)`, `Bash(gh *)`, `Bash(sops *)`, `Bash(security *)`, `Bash(sudo *)`, `Bash(terraform *)`, `Bash(argocd *)`, `Bash(vercel *)`, `Bash(flyctl *)`, `Bash(docker push*)`, `Bash(npm publish*)`, `Bash(cargo publish*)`; `safe_env(base: Mapping[str, str], extra: Mapping[str, str]) -> dict[str, str]` (copy of `base` without `SSH_AUTH_SOCK`, `GH_TOKEN`, `GITHUB_TOKEN`; with `KUBECONFIG=/dev/null`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`; then `extra` on top).
- Produces (`driver.py`): `RESULT_RULE` (appended to every prompt: the run's autonomy text, and "leave your final result committed on the branch `{branch}` checked out in this directory; merge any work branches you create into it before you finish"); `@dataclass RunRecord(case_id: str, system: str, run_id: str, status: str, wall_s: float = 0.0, cost_usd: float = 0.0, usage: dict = {}, num_turns: int = 0, interruptions: int = 0, resumes: int = 0, final_text: str = "", cwd: str = "", loaded_skills: tuple[str, ...] = (), loaded_plugins: tuple[str, ...] = (), mcp_servers: list = [], executor_usage: dict = {}, error: str | None = None)` (mutable defaults via `field(default_factory=...)`); status is one of `finished`, `stalled`, `timeout`, `budget`, `error`; `build_prompt(case: Case, system: System, ws: Workspace) -> str`; `build_options(case: Case, *, model: str, plugin_dirs: Sequence[Path], ws: Workspace, can_use_tool, extra_env: Mapping[str, str]) -> ClaudeAgentOptions`; `check_isolation(init_data: Mapping) -> str | None`; `decide_after_stop(reply: str | None, resumes: int, max_resumes: int) -> str` (`"finish"` when `reply is None`, `"resume"` while `resumes < max_resumes`, else `"stalled"`); `session_dir_for(cwd: str) -> Path`; `async def run_case(case: Case, system: System, ws: Workspace, plugin_dirs: Sequence[Path], standin: StandIn, transcript: Path, *, max_resumes: int = 3) -> RunRecord`.
- Produces (`usage.py`): `collect_executor_usage(repo: Path) -> dict[str, dict[str, float]]` — sums the `result` events of `repo/.git/cursor-loop/*/rounds/*/events.ndjson` under the key `"cursor"`: `runs`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `seconds`.

`build_options`: `cwd=ws.repo`, `model`, `setting_sources=[]`, `plugins=[{"type": "local", "path": str(p)}]`, `strict_mcp_config=True`, `mcp_servers={}`, `permission_mode="default"`, `allowed_tools` = the usual coding tools except `AskUserQuestion` (so questions reach `can_use_tool`), `disallowed_tools=list(DENY_RULES)`, `env=safe_env(os.environ, {**case.env, **extra_env})`, `max_budget_usd=case.budget.max_usd`. `run_case` uses `ClaudeSDKClient` (streaming input, required for `can_use_tool` in Python): `can_use_tool` routes `AskUserQuestion` to `standin.answer` and allows everything else; on the init message it records skills/plugins/connectors and aborts with status `error` when `check_isolation` reports a breach; on each `ResultMessage` it asks `standin.on_stop(text, is_question)` (`model_says_yes` with "does this message ask the owner a question or for approval before continuing?") and follows `decide_after_stop`; it writes every message as one JSON line to `transcript`, maps `error_max_budget_usd` to `budget`, enforces `case.budget.timeout_min` as `timeout`, fills `executor_usage`, and finally deletes `session_dir_for(record.cwd)` only if that folder exists and its name contains `ws.run_id`. Follow `code.claude.com/docs/en/agent-sdk/user-input` for the callback; if a keep-open hook is still needed with `ClaudeSDKClient`, add it as the docs show.

- [ ] **Step 1: Write the locked tests** — `bench/tests/test_driver.py`:

```python
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
```

`bench/tests/test_usage.py`:

```python
from keryx_bench.usage import collect_executor_usage


def test_cursor_loop_usage_is_summed(tmp_path):
    rounds = tmp_path / ".git" / "cursor-loop" / "slug" / "rounds"
    (rounds / "01").mkdir(parents=True)
    (rounds / "02").mkdir()
    (rounds / "01" / "events.ndjson").write_text(
        '{"type":"system","subtype":"init","model":"Grok"}\n'
        '{"type":"result","duration_ms":1000,"usage":{"inputTokens":10,"outputTokens":5,"cacheReadTokens":100}}\n')
    (rounds / "02" / "events.ndjson").write_text(
        '{"type":"result","duration_ms":500,"usage":{"inputTokens":1,"outputTokens":2,"cacheReadTokens":3}}\n')
    assert collect_executor_usage(tmp_path) == {
        "cursor": {"runs": 2, "input_tokens": 11, "output_tokens": 7, "cache_read_tokens": 103, "seconds": 1.5}}


def test_no_executor_runs_means_no_usage(tmp_path):
    (tmp_path / ".git").mkdir()
    assert collect_executor_usage(tmp_path) == {}
```

- [ ] **Step 2:** `.venv/bin/pytest -q tests/test_driver.py tests/test_usage.py` — expected: FAIL, `ModuleNotFoundError: keryx_bench.driver` / `keryx_bench.usage`.
- [ ] **Step 3:** Implement the three modules as specified.
- [ ] **Step 4:** `.venv/bin/pytest -q` — expected: all pass.
- [ ] **Step 5: Commit** — `feat(bench): drive a system under test in an isolated session`.

### Task 7: Scores, comparison and the summary

**Files:** Create `bench/keryx_bench/score.py`, `bench/keryx_bench/compare.py`, `bench/keryx_bench/report.py`, `bench/tests/test_score.py`, `bench/tests/test_compare.py`, `bench/tests/test_report.py`.

**Interfaces:**
- Consumes: `Case` (2), `CheckResult` (3), `RunRecord` (6).
- Produces (`score.py`): frozen `Score(case_id: str, mode: str, status: str, quality: float, defects_found: int | None, defects_total: int | None, false_done: bool, wall_s: float, cost_usd: float, interruptions: int)`; `score_run(case: Case, record: RunRecord, checks: list[CheckResult], claims_done: bool) -> Score` — quality = share of checks passed; review cases count known defects whose check passed; `false_done` = status `finished` and `claims_done` and quality < 1.0.
- Produces (`compare.py`): frozen `RunSet(system: str, case_hashes: Mapping[str, str], scores: Mapping[str, Score])`, frozen `Verdict(winner: str, reasons: tuple[str, ...], rerun: tuple[str, ...])`; `load_runset(run_dir: Path) -> RunSet`; `compare_runs(a: RunSet, b: RunSet, cost_cap_usd: float | None) -> Verdict` — `a` is the current setup, `b` the candidate. Rules in order: different case ids or hashes → `invalid`; per mode, mean quality of `b` below `a` → `A`, with `rerun` = that group's cases where `b` scored lower; more false dones, or fewer known defects found → `A`; `b`'s total cost above the cap → `A`; median wall time of `b` below 95 % of `a`'s → `B`; within 5 % → `tie`; else `A`.
- Produces (`report.py`): `fmt_duration(seconds: float) -> str` (`125.0` → `2m05s`); `write_summary(run_dir: Path, system: str, scores: list[Score]) -> Path` (`run_dir/summary.md` with header `| case | mode | status | quality | time | cost | questions |` and one row per case).

- [ ] **Step 1: Write the locked tests** — `bench/tests/test_score.py`:

```python
from helpers import write_case
from keryx_bench.case import load_case
from keryx_bench.driver import RunRecord
from keryx_bench.score import score_run
from keryx_bench.workspace import CheckResult


def cr(name, ok):
    return CheckResult(name=name, passed=ok, exit_code=0 if ok else 1, seconds=1.0, output_tail="")


def rec(status):
    return RunRecord(case_id="toy-add", system="s", run_id="r", status=status, wall_s=60.0, cost_usd=0.5, interruptions=1)


def test_quality_is_the_share_of_checks_passed(toy_case):
    s = score_run(load_case(toy_case), rec("finished"), [cr("a", True), cr("b", False)], claims_done=False)
    assert s.quality == 0.5
    assert s.false_done is False
    assert (s.wall_s, s.cost_usd, s.interruptions) == (60.0, 0.5, 1)


def test_claiming_done_with_a_failing_check_is_a_false_done(toy_case):
    s = score_run(load_case(toy_case), rec("finished"), [cr("hidden-add", False)], claims_done=True)
    assert s.false_done is True


def test_a_stalled_run_is_never_a_false_done(toy_case):
    s = score_run(load_case(toy_case), rec("stalled"), [cr("hidden-add", False)], claims_done=True)
    assert s.false_done is False


def test_review_cases_count_known_defects_fixed(tmp_path, toy_repo):
    repo, base, good = toy_repo
    extra = "known_defects:\n  - id: one\n    check: d1\n  - id: two\n    check: d2\n"
    case = load_case(write_case(tmp_path / "c", repo, base, good, mode="review",
                                checks=[("d1", "true"), ("d2", "false")], extra=extra))
    s = score_run(case, rec("finished"), [cr("d1", True), cr("d2", False)], claims_done=False)
    assert (s.defects_found, s.defects_total) == (1, 2)
```

`bench/tests/test_compare.py`:

```python
from keryx_bench.compare import RunSet, compare_runs
from keryx_bench.score import Score


def sc(case_id, mode="bug", quality=1.0, wall=100.0, cost=1.0, false_done=False, found=None, total=None):
    return Score(case_id=case_id, mode=mode, status="finished", quality=quality, defects_found=found,
                 defects_total=total, false_done=false_done, wall_s=wall, cost_usd=cost, interruptions=0)


def rs(system, scores, hashes=None):
    return RunSet(system=system, case_hashes=hashes or {s.case_id: "h-" + s.case_id for s in scores},
                  scores={s.case_id: s for s in scores})


def test_different_case_sets_cannot_be_compared():
    assert compare_runs(rs("a", [sc("x")]), rs("b", [sc("x")], hashes={"x": "other"}), None).winner == "invalid"


def test_a_faster_candidate_that_loses_quality_in_one_group_loses():
    a = rs("a", [sc("x", "bug", 1.0, 100), sc("y", "review", 1.0, 100)])
    b = rs("b", [sc("x", "bug", 1.0, 10), sc("y", "review", 0.5, 10)])
    v = compare_runs(a, b, None)
    assert v.winner == "A"
    assert v.rerun == ("y",)


def test_more_false_dones_lose_even_with_equal_quality():
    a = rs("a", [sc("x", quality=0.5)])
    b = rs("b", [sc("x", quality=0.5, wall=10, false_done=True)])
    assert compare_runs(a, b, None).winner == "A"


def test_fewer_known_defects_found_loses():
    a = rs("a", [sc("x", "review", found=3, total=5)])
    b = rs("b", [sc("x", "review", wall=10, found=2, total=5)])
    assert compare_runs(a, b, None).winner == "A"


def test_a_candidate_that_holds_quality_and_is_faster_wins():
    a = rs("a", [sc("x", wall=100), sc("y", wall=100)])
    b = rs("b", [sc("x", wall=50), sc("y", wall=60)])
    assert compare_runs(a, b, None).winner == "B"


def test_a_candidate_over_the_cost_cap_loses():
    a = rs("a", [sc("x", wall=100, cost=1.0)])
    b = rs("b", [sc("x", wall=50, cost=9.0)])
    assert compare_runs(a, b, 5.0).winner == "A"


def test_speed_within_five_percent_is_a_tie():
    assert compare_runs(rs("a", [sc("x", wall=100)]), rs("b", [sc("x", wall=97)]), None).winner == "tie"
```

`bench/tests/test_report.py`:

```python
from keryx_bench.report import fmt_duration, write_summary
from keryx_bench.score import Score


def test_durations_read_as_minutes_and_seconds():
    assert fmt_duration(125.0) == "2m05s"
    assert fmt_duration(3725.0) == "62m05s"


def test_the_summary_lists_every_case_with_quality_time_and_cost(tmp_path):
    s = Score(case_id="x", mode="bug", status="finished", quality=1.0, defects_found=None, defects_total=None,
              false_done=False, wall_s=125.0, cost_usd=0.42, interruptions=1)
    text = write_summary(tmp_path, system="baseline", scores=[s]).read_text()
    assert "| case | mode | status | quality | time | cost | questions |" in text
    assert "| x | bug | finished | 1.00 | 2m05s | $0.42 | 1 |" in text
```

- [ ] **Step 2:** `.venv/bin/pytest -q tests/test_score.py tests/test_compare.py tests/test_report.py` — expected: FAIL, `ModuleNotFoundError`.
- [ ] **Step 3:** Implement the three modules as specified; `load_runset` reads the files Task 8 writes.
- [ ] **Step 4:** `.venv/bin/pytest -q` — expected: all pass.
- [ ] **Step 5: Commit** — `feat(bench): score runs and compare two setups`.

### Task 8: Runner and command line

**Files:** Create `bench/keryx_bench/runner.py`, `bench/keryx_bench/cli.py`; modify `bench/keryx_bench/__main__.py`; create `bench/tests/test_cli.py`, `bench/tests/test_live.py`.

**Interfaces:**
- Consumes: everything above.
- Produces (`runner.py`): `async def run_one(case: Case, system: System, runs_root: Path, results_root: Path, run_id: str, *, matcher: Matcher | None = None) -> tuple[RunRecord, Score]` — prepare the workspace; run `case.prepare` untimed; materialize the system into `runs_root/run_id/plugins`; `run_case`; `result_checkout` → `apply_hidden` → `run_checks`; `claims_done` via `model_says_yes("does this report claim the task is complete?", final_text)` (skipped, `False`, when status is not `finished`); `score_run`; write `results_root/run_id/<case.id>/{record.json, score.json, transcript.jsonl}` (`ModelMatcher` when `matcher` is `None`). `async def run_many(cases, system, runs_root, results_root, run_id, parallel: int) -> list[tuple[RunRecord, Score]]` — at most `parallel` cases at once; writes `results_root/run_id/run.json` (system name, start/end, case hashes) and `summary.md`.
- Produces (`cli.py`): `build_parser() -> argparse.ArgumentParser`; `main(argv: list[str] | None = None) -> int`. Commands: `validate CASE_DIR... [--runs DIR]` (exit 1 if any case is invalid, printing its reasons); `run --system NAME_OR_PATH --cases DIR [--only ID ...] [--parallel 1-3] [--results DIR] [--runs DIR]`; `compare RUN_A RUN_B [--cost-cap USD]`; `rerun RUN_DIR --case ID [--times 3]`. A bare system name resolves to `~/.config/keryx/systems/<name>.yaml`; results default to `~/.local/share/keryx/bench-results`; run ids are UTC timestamps. `python -m keryx_bench` calls `main`.

- [ ] **Step 1: Write the locked tests** — `bench/tests/test_cli.py`:

```python
import pytest

from helpers import write_case
from keryx_bench.cli import build_parser, main


def test_parallel_is_capped_at_three():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--system", "s", "--cases", "c", "--parallel", "4"])


def test_validate_exit_code_reflects_invalid_cases(tmp_path, toy_repo, capsys):
    repo, base, good = toy_repo
    ok = write_case(tmp_path / "ok", repo, base, good)
    bad = write_case(tmp_path / "bad", repo, base, good, checks=[("hidden-add", "true")])
    assert main(["validate", str(ok), "--runs", str(tmp_path / "runs")]) == 0
    assert main(["validate", str(ok), str(bad), "--runs", str(tmp_path / "runs")]) == 1
    assert "every check passes on base" in capsys.readouterr().out
```

`bench/tests/test_live.py`:

```python
import asyncio
import os

import pytest

from helpers import write_case
from keryx_bench.case import load_case
from keryx_bench.driver import session_dir_for
from keryx_bench.runner import run_one
from keryx_bench.systems import System

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("KERYX_LIVE") != "1", reason="live model calls; set KERYX_LIVE=1")]


def test_a_live_run_asks_gets_the_script_and_leaves_a_scored_result(tmp_path, toy_repo):
    repo, base, good = toy_repo
    case = load_case(write_case(tmp_path / "c", repo, base, good, prompt=(
        "calc.add(2, 3) returns -1; it must return 5. Before you edit anything, ask the owner exactly one "
        "question with the AskUserQuestion tool: which function name to keep. Then fix it.\n")))
    system = System(name="plain", model="haiku", plugins=(), assemble=None,
                    entry={"bug": "{prompt}", "review": "{prompt}", "feature": "{prompt}"}, env={})
    record, score = asyncio.run(run_one(case, system, tmp_path / "runs", tmp_path / "results", "live1"))
    assert record.status == "finished", record.error
    assert record.interruptions >= 1
    assert record.mcp_servers == []
    assert not any(s.startswith("keryx") or s == "cursor-loop" for s in record.loaded_skills)
    assert score.quality == 1.0
    assert (tmp_path / "results" / "live1" / "toy-add" / "transcript.jsonl").exists()
    assert not session_dir_for(record.cwd).exists()
```

- [ ] **Step 2:** `.venv/bin/pytest -q tests/test_cli.py` — expected: FAIL, `ModuleNotFoundError: keryx_bench.cli`.
- [ ] **Step 3:** Implement `runner.py`, `cli.py` and `__main__.py` as specified.
- [ ] **Step 4:** `.venv/bin/pytest -q` — expected: all pass, live test skipped. Then `KERYX_LIVE=1 .venv/bin/pytest -q -m live` — expected: `1 passed` (a few cents of Haiku).
- [ ] **Step 5: Commit** — `feat(bench): run cases from the command line`.

### Task 9: The first ten cases (coordinator)

Coordinator work, not an executor task: it needs the transcripts, the private repos and judgment.

- [ ] **Step 1:** Create `~/.config/keryx/forbidden-names.txt` (the external pack names, one per line) and re-run the full suite; `test_the_repo_names_no_external_skill_pack` must pass.
- [ ] **Step 2:** Write ten cases under `~/.config/keryx/cases/<id>/`, at least three per mode, chosen from:
  - **feature slices** — the Product A company-page loops whose state is in `product-a/.git/cursor-loop/` (base = the loop's `baseSha`, good = its final head, hidden checks = its locked tests plus the crate's test command, prompt = the plan task the owner's session started from, not the loop's own PLAN.md);
  - **bugs** — Product B predicted funding (base `6763f19bda`, good `b5403e3887`, hidden = the three unit tests and the summary vitest; the live Binance smoke stays out because it is not deterministic) and two public SWE-bench Verified cases from July's harness (`psf__requests-1921`, `pallets__flask-5014`; hidden = their FAIL_TO_PASS tests in a venv built by `prepare`);
  - **review** — branches at a pre-fix head with known findings: Product A t1 (permit drop order) and t4b (nesting depth), Product B `liq-heatmap-polish` of 2026-07-02 (the five findings the short keryx chain fixed with RED→GREEN tests).
- [ ] **Step 3:** For each case: the prompt names every interface the hidden checks call; `owner.yaml` holds the owner's real answers from the transcripts and the autonomy "commit locally on your branch, no push"; `prepare` warms the build; budget fits the case.
- [ ] **Step 4:** `python -m keryx_bench validate ~/.config/keryx/cases/*` — expected: exit 0. A case that does not validate is fixed or replaced, never weakened.
- [ ] **Step 5:** Nothing from these cases is committed.

### Task 10: Baseline run (coordinator)

- [ ] **Step 1:** Write `~/.config/keryx/systems/baseline-2026-10.yaml` from `bench/systems/example.yaml`: coordinator model, today's skills assembled (the five keryx skills, cursor-loop, the external pack's skills from its install path), the triple-check text as session-start text, and per mode the way the owner starts that work today (from the transcripts).
- [ ] **Step 2: Preflight** — Cursor CLI logged in (`agent status`), the local Postgres the Product A cases need is up, Docker is running, at least 50 GB free disk.
- [ ] **Step 3:** One case first: `python -m keryx_bench run --system baseline-2026-10 --cases ~/.config/keryx/cases --only <a small bug case>`; read its transcript and record to confirm the harness measured what it claims (questions counted, init lists only the assembled plugin, result scored on the committed branch).
- [ ] **Step 4:** Full run: `--parallel 2`. Expected: `summary.md` with ten rows; wall time and cost noted against the 2 h / few-dollars target of the design (§7.4).
- [ ] **Step 5:** Write `docs/bench/2026-10-baseline.md` with aggregate numbers only (per mode: quality, false dones, defects found, median time, cost, questions; total wall time), no private code, prompts or names. Commit: `docs(bench): record the baseline of today's setup`.
- [ ] **Step 6:** Report the numbers to the owner; Plan 2 (the keryx loop) starts from them.
