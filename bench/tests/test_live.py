import asyncio
import os

import pytest

from helpers import write_case
from keryx_bench.case import load_case
from keryx_bench.driver import session_dir_for
from keryx_bench.runner import run_one
from keryx_bench.systems import System

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(os.environ.get("KERYX_LIVE") != "1", reason="live model calls; set KERYX_LIVE=1")]


def test_a_live_run_asks_gets_the_script_and_leaves_a_scored_result(tmp_path, toy_repo):
    repo, base, good = toy_repo
    case = load_case(write_case(tmp_path / "c", repo, base, good, prompt=(
        "calc.add(2, 3) returns -1; it must return 5. Before you edit anything, ask the owner exactly one "
        "question with the AskUserQuestion tool: which function name to keep. Then fix it.\n")))
    system = System(name="plain", model="haiku", plugins=(), assemble=None,
                    entry={"bug": "{prompt}", "review": "{prompt}", "feature": "{prompt}"}, env={})
    record, score = asyncio.run(run_one(case, system, tmp_path / "runs", tmp_path / "results", "live1"))
    assert record.status == "finished", record.error
    assert record.interruptions >= 1
    assert record.mcp_servers == []
    assert not any(s.startswith("keryx") or s == "cursor-loop" for s in record.loaded_skills)
    assert score.quality == 1.0
    assert (tmp_path / "results" / "live1" / "toy-add" / "transcript.jsonl").exists()
    assert not session_dir_for(record.cwd).exists()


def test_a_run_waiting_for_its_background_job_is_not_cut_off(tmp_path, toy_repo):
    repo, base, good = toy_repo
    case = load_case(write_case(tmp_path / "c", repo, base, good, prompt=(
        "First start this shell command in the background (Bash with run_in_background): "
        "`sleep 20; echo ok > done.txt`. End your turn right after starting it and wait for its completion "
        "notification. Only after it has finished: fix calc.add so add(2, 3) == 5, and commit calc.py.\n")))
    system = System(name="plain", model="haiku", plugins=(), assemble=None,
                    entry={"bug": "{prompt}", "review": "{prompt}", "feature": "{prompt}"}, env={})
    record, score = asyncio.run(run_one(case, system, tmp_path / "runs", tmp_path / "results", "live2"))
    assert record.status == "finished", record.error
    assert score.quality == 1.0
