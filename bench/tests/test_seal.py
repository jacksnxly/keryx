import subprocess

from helpers import git
from keryx_bench.case import load_case
from keryx_bench.workspace import prepare_workspace


def test_the_workspace_holds_no_history_after_base(toy_case, toy_repo, tmp_path):
    repo, base, good = toy_repo
    git(repo, "tag", "v-before", base)
    git(repo, "tag", "v-after", good)
    ws = prepare_workspace(load_case(toy_case), tmp_path / "runs", "r1")
    assert good not in git(ws.repo, "rev-list", "--all").split()
    assert subprocess.run(["git", "-C", str(ws.repo), "cat-file", "-e", good], capture_output=True).returncode != 0
    assert git(ws.repo, "tag") == "v-before"
    assert subprocess.run(["git", "-C", str(ws.repo), "fetch", "origin"], capture_output=True).returncode != 0
