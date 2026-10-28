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
