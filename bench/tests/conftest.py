import pytest

from helpers import make_toy_repo, write_case


@pytest.fixture
def toy_repo(tmp_path):
    return make_toy_repo(tmp_path)


@pytest.fixture
def toy_case(tmp_path, toy_repo):
    repo, base, good = toy_repo
    return write_case(tmp_path / "case", repo, base, good)


@pytest.fixture(autouse=True)
def _private_tmp_and_lock(tmp_path_factory, monkeypatch):
    """No test touches the machine's real /tmp or holds the real runner lock."""
    from keryx_bench import runner, scratch

    monkeypatch.setattr(scratch, "TMP_ROOT", tmp_path_factory.mktemp("tmp-root"))
    monkeypatch.setattr(runner, "RUNNER_LOCK", tmp_path_factory.mktemp("lock") / "runner.lock")
