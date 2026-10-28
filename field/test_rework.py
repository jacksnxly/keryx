import subprocess

import rework


def _git(repo, *args, date=None):
    env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {}
    import os
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "-C", str(repo), *args],
                   check=True, capture_output=True, env={**os.environ, **env})


def _commit(repo, name, text, message, date):
    (repo / name).write_text(text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message, date=date)


def test_a_fix_to_the_same_files_soon_after_counts_as_rework(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "a.py", "1", "feat: add a", "2026-10-20T10:05:00Z")      # made during the turn
    _commit(repo, "b.py", "1", "fix: unrelated b", "2026-10-20T12:00:00Z")  # other file: not rework
    _commit(repo, "a.py", "2", "fix: a was wrong", "2026-10-21T09:00:00Z")  # same file, < 72 h: rework
    commits = rework.repo_commits(repo)
    turn = rework.TurnWindow(start="2026-10-20T10:00:00Z", end="2026-10-20T10:30:00Z")
    made, redo = rework.rework_for(turn, commits)
    assert [c.subject for c in made] == ["feat: add a"]
    assert [c.subject for c in redo] == ["fix: a was wrong"]


def test_later_work_that_is_not_a_fix_or_is_too_late_does_not_count(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "a.py", "1", "feat: add a", "2026-10-20T10:05:00Z")
    _commit(repo, "a.py", "2", "feat: extend a", "2026-10-20T15:00:00Z")    # same file, not a fix
    _commit(repo, "a.py", "3", "fix: a again", "2026-10-25T10:00:00Z")      # a fix, but > 72 h later
    made, redo = rework.rework_for(rework.TurnWindow("2026-10-20T10:00:00Z", "2026-10-20T10:30:00Z"),
                                   rework.repo_commits(repo))
    assert len(made) == 1 and redo == []


def test_a_revert_counts_whatever_its_wording():
    assert rework.is_rework_subject('Revert "feat: add a"')
    assert rework.is_rework_subject("fix(api): sign of funding")
    assert rework.is_rework_subject("hotfix: broken deploy")
    assert not rework.is_rework_subject("feat: add the fix-up command")
    assert not rework.is_rework_subject("docs: describe fixes")
