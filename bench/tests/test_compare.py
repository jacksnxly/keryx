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
