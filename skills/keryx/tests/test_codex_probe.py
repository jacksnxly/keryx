"""The Codex preflight probe runs outside any repository, so it skips Codex's git-repository check."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402


class CodexProbeCommand(unittest.TestCase):
    def test_the_probe_is_read_only_and_skips_the_repository_check(self):
        self.assertEqual(keryx.codex_probe_command("zai-glm-5-3", "high"),
                         ["codex", "exec", "--json", "--skip-git-repo-check", "-m", "zai-glm-5-3",
                          "-c", 'model_reasoning_effort="high"', "-s", "read-only", "--", "Reply with exactly: KERYX_OK"])
        self.assertEqual(keryx.codex_probe_command("zai-glm-5-3", None),
                         ["codex", "exec", "--json", "--skip-git-repo-check", "-m", "zai-glm-5-3",
                          "-s", "read-only", "--", "Reply with exactly: KERYX_OK"])


if __name__ == "__main__":
    unittest.main()
