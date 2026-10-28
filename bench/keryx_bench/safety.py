"""Guard rails for a system under test: commands it may not run and credentials it does not get.

These narrow what a runaway run can reach; they are not a sandbox.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

DENY_RULES: tuple[str, ...] = (
    "Bash(git push*)",
    "Bash(kubectl *)",
    "Bash(helm *)",
    "Bash(ssh *)",
    "Bash(scp *)",
    "Bash(rsync *)",
    "Bash(gh *)",
    "Bash(sops *)",
    "Bash(security *)",
    "Bash(sudo *)",
    "Bash(terraform *)",
    "Bash(argocd *)",
    "Bash(vercel *)",
    "Bash(flyctl *)",
    "Bash(docker push*)",
    "Bash(npm publish*)",
    "Bash(cargo publish*)",
)

REMOVED_VARS = ("SSH_AUTH_SOCK", "GH_TOKEN", "GITHUB_TOKEN")
_SECRET = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY|PRIVATE_KEY|CREDENTIALS?)$|^SOPS_|AGE_KEY")
_MODEL_AUTH = ("ANTHROPIC_", "CLAUDE_CODE_OAUTH")  # the session needs these to reach the model
# git may not use the owner's SSH keys, with or without an agent.
NO_SSH = "ssh -F /dev/null -o IdentitiesOnly=yes -o IdentityFile=/dev/null -o BatchMode=yes"


def removed_keys(base: Mapping[str, str]) -> list[str]:
    return [k for k in base if k in REMOVED_VARS or (_SECRET.search(k) and not k.startswith(_MODEL_AUTH))]


def safe_env(base: Mapping[str, str], extra: Mapping[str, str]) -> dict[str, str]:
    gone = set(removed_keys(base))
    env = {k: v for k, v in base.items() if k not in gone}
    env["KUBECONFIG"] = "/dev/null"
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    env["GIT_SSH_COMMAND"] = NO_SSH
    env.update(extra)
    return env
