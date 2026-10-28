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
