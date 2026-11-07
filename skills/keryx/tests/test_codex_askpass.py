"""A codex provider round gets no askpass program: git and ssh cannot ask one for the owner's credentials."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import keryx  # noqa: E402


class NoAskpass(unittest.TestCase):
    def test_askpass_programs_are_dropped(self):
        base = {"PATH": "/usr/bin", "HOME": "/no-such-root-keryx", "GIT_ASKPASS": "/x/askpass.sh",
                "SSH_ASKPASS": "/x/ssh-askpass", "SSH_ASKPASS_REQUIRE": "force", "VSCODE_GIT_ASKPASS_MAIN": "/x/main.js"}
        env = keryx.codex_env(base, "/run/codex-home", "k")
        for gone in ("GIT_ASKPASS", "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "VSCODE_GIT_ASKPASS_MAIN"):
            self.assertNotIn(gone, env)


if __name__ == "__main__":
    unittest.main()
