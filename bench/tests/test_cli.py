import pytest

from helpers import write_case
from keryx_bench.cli import build_parser, main


def test_parallel_is_capped_at_three():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--system", "s", "--cases", "c", "--parallel", "4"])


def test_validate_exit_code_reflects_invalid_cases(tmp_path, toy_repo, capsys):
    repo, base, good = toy_repo
    ok = write_case(tmp_path / "ok", repo, base, good)
    bad = write_case(tmp_path / "bad", repo, base, good, checks=[("hidden-add", "true")])
    assert main(["validate", str(ok), "--runs", str(tmp_path / "runs")]) == 0
    assert main(["validate", str(ok), str(bad), "--runs", str(tmp_path / "runs")]) == 1
    assert "every check passes on base" in capsys.readouterr().out
