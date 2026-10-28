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
