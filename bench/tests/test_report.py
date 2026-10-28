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
