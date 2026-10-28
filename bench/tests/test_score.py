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
