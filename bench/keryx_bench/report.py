"""A run's summary table."""
from __future__ import annotations

from pathlib import Path

from keryx_bench.score import Score


def fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}m{total % 60:02d}s"


def write_summary(run_dir: Path, system: str, scores: list[Score]) -> Path:
    lines = [
        f"# Benchmark run — {system}",
        "",
        "| case | mode | status | quality | time | cost | questions |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        quality = f"{s.quality:.2f}"
        if s.defects_total is not None:
            quality += f" ({s.defects_found}/{s.defects_total} defects)"
        if s.false_done:
            quality += " FALSE DONE"
        if s.contaminated:
            quality += " CONTAMINATED"
        if s.tests_total:
            quality += f" (tests {s.tests_passed}/{s.tests_total})"
        lines.append(f"| {s.case_id} | {s.mode} | {s.status} | {quality} | {fmt_duration(s.wall_s)} | "
                     f"${s.cost_usd:.2f} | {s.interruptions} |")
    total_time = sum(s.wall_s for s in scores)
    total_cost = sum(s.cost_usd for s in scores)
    lines += ["", f"Total: {len(scores)} cases, {fmt_duration(total_time)} of run time, ${total_cost:.2f}."]
    path = Path(run_dir) / "summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path
