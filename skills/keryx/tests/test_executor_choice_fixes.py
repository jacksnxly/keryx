"""Review fixes for Part 3: the chooser reads meters fresh (a cached reading must not clear a newer limit record),
and a login left out for an exhausted or blocked meter says so on stderr."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402
from test_field_adapter import cli, machine  # noqa: E402
from test_keryx import _two_commit_repo  # noqa: E402

CONFIG = {"budget": True, "executors": ["codex-a", "subagent"],
          "providers": {"codex-a": {"runner": "codex", "codexHome": "~/.config/keryx/codex/a", "model": "m"}}}
SPENT = {"plan": "plus", "reached": None, "credits": [],
         "windows": [{"minutes": 300, "usedPercent": 100, "resetsAt": "2099-01-01T05:00:00Z"},
                     {"minutes": 10080, "usedPercent": 40, "resetsAt": "2099-01-05T00:00:00Z"}]}


class ChooserReadsFresh(unittest.TestCase):
    def test_executors_mode_reads_every_meter_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, **CONFIG)
            with mock.patch.object(keryx, "codex_meters", return_value={"codex-a": None}) as meters:
                code, _, _ = cli(repo, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
            self.assertEqual(code, 0)
            self.assertEqual(meters.call_count, 1)
            self.assertEqual(meters.call_args.kwargs.get("max_age"), 0)


class LeftOutSaysWhy(unittest.TestCase):
    def test_an_exhausted_login_names_its_reset_on_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, **CONFIG)
            with mock.patch.object(keryx, "codex_meters", return_value={"codex-a": SPENT}):
                code, out, err = cli(repo, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
            self.assertEqual((code, out.split()), (0, ["subagent"]))
            self.assertRegex(err, r"(?m)^codex-a: .*2099-01-01T05:00:00Z")

    def test_a_blocked_login_says_it_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _two_commit_repo(tmp)[0]
            env = machine(tmp, **CONFIG)
            blocked = {**SPENT, "reached": "workspace_owner_usage_limit_reached",
                       "windows": [{**SPENT["windows"][0], "usedPercent": 10}, SPENT["windows"][1]]}
            with mock.patch.object(keryx, "codex_meters", return_value={"codex-a": blocked}):
                code, out, err = cli(repo, ["executors", "--mode", "IMPLEMENT", "--size", "M"], env)
            self.assertEqual(out.split(), ["subagent"])
            self.assertRegex(err, r"(?m)^codex-a: .*workspace_owner_usage_limit_reached")


if __name__ == "__main__":
    unittest.main()
