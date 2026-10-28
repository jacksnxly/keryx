import json
from pathlib import Path

import pytest

from keryx_bench.systems import SystemConfigError, load_system, materialize


def make_skill(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test skill {name}\n---\nBody of {name}.\n")
    return d


def write_system(path: Path, skill_dirs, text_file=None) -> Path:
    lines = ["name: test-system", "model: haiku", "assemble:", "  name: assembled", "  skills:"]
    lines += [f"    - {d}" for d in skill_dirs]
    if text_file:
        lines.append(f"  session_start_text: {text_file}")
    lines += ["entry:", "  bug: '{prompt}'", "  review: '{prompt}'", "  feature: '{prompt}'"]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_system_needs_an_entry_for_every_mode(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("name: s\nmodel: haiku\nentry:\n  bug: '{prompt}'\n")
    with pytest.raises(SystemConfigError, match="review"):
        load_system(p)


def test_the_assembled_plugin_has_a_manifest_and_real_copies(tmp_path):
    real = make_skill(tmp_path / "src", "alpha")
    (tmp_path / "links").mkdir()
    (tmp_path / "links" / "alpha").symlink_to(real)
    system = load_system(write_system(tmp_path / "s.yaml", [tmp_path / "links" / "alpha"]))
    [plugin] = materialize(system, tmp_path / "out")
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "assembled"
    assert (plugin / "skills" / "alpha" / "SKILL.md").read_text().endswith("Body of alpha.\n")
    assert not any(p.is_symlink() for p in plugin.rglob("*"))


def test_session_start_text_is_wired_as_a_hook(tmp_path):
    real = make_skill(tmp_path / "src", "alpha")
    text = tmp_path / "policy.md"
    text.write_text("EVIDENCE BEFORE DONE\n")
    system = load_system(write_system(tmp_path / "s.yaml", [real], text_file=text))
    [plugin] = materialize(system, tmp_path / "out")
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text())
    assert "SessionStart" in hooks["hooks"]
    assert (plugin / "session-start.md").read_text() == "EVIDENCE BEFORE DONE\n"


def test_the_repo_names_no_external_skill_pack():
    names_file = Path.home() / ".config" / "keryx" / "forbidden-names.txt"
    if not names_file.exists():
        pytest.skip("no local forbidden-names list")
    names = [n.strip().lower() for n in names_file.read_text().splitlines() if n.strip()]
    repo = Path(__file__).resolve().parents[2]
    hits = []
    for path in repo.rglob("*"):
        if not path.is_file() or {".git", ".venv"} & set(path.parts):
            continue
        text = path.read_text(errors="ignore").lower()
        hits += [f"{path.relative_to(repo)}: {n}" for n in names if n in text]
    assert hits == []
