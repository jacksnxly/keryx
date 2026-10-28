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
