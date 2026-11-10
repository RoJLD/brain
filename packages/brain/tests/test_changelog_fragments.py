"""installer/changelog.py: the engine's changelog fragments (wi-brain-changelog-unreleased-collisions)."""

import importlib.util
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("changelog", PACKAGE / "installer" / "changelog.py")
changelog = importlib.util.module_from_spec(spec)
sys.modules["changelog"] = changelog
spec.loader.exec_module(changelog)

BRAIN_LOG = "# Changelog — brain\n\nIntro.\n\n## 0.2.8 — 2026-11-09 — the review fixes\n\n### Fixes\n\n- old\n"
RG_LOG = "# Changelog — research-graph\n\nIntro.\n\n## 0.2.8 — 2026-11-09\n\n- No change.\n"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "packages" / "brain" / "changes").mkdir(parents=True)
    (tmp_path / "changes").mkdir()
    (tmp_path / "packages" / "brain" / "CHANGELOG.md").write_text(BRAIN_LOG, encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(RG_LOG, encoding="utf-8")
    (tmp_path / "packages" / "brain" / "changes" / "README.md").write_text("How to write one.\n", encoding="utf-8")
    return tmp_path


def _frag(repo, name, text, dist="brain"):
    folder = repo / ("packages/brain/changes" if dist == "brain" else "changes")
    (folder / f"{name}.md").write_text(text, encoding="utf-8")


def test_two_prs_write_two_files_and_the_version_pr_compiles_them_in_section_order(repo):
    _frag(repo, "wi-b-fix", "section: Fixes\n\n- the second fix\n")
    _frag(repo, "wi-a-added", "section: Added\n\n- a new command\n")
    _frag(repo, "wi-c-upgrade", "section: Upgrade\n\n**Install the engine**, as always.\n")
    assert changelog.check(repo) == []
    out = changelog.compile_release(repo, "0.3.0", "Sigma's home", "2026-11-10", write=True)
    brain = (repo / "packages/brain/CHANGELOG.md").read_text(encoding="utf-8")
    assert brain.startswith("# Changelog — brain\n\nIntro.\n\n## 0.3.0 — 2026-11-10 — Sigma's home\n")
    assert brain.index("### Upgrade") < brain.index("### Added") < brain.index("### Fixes") < brain.index("## 0.2.8")
    assert "- the second fix" in brain and "- a new command" in brain
    rg = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.3.0 — 2026-11-10\n\n" + changelog.NO_CHANGE in rg   # no fragment: « No change », no theme
    assert changelog.fragment_files(repo, "brain") == [] and changelog.pending(repo) == []
    assert (repo / "packages/brain/changes/README.md").is_file()   # the folder's README stays
    assert set(out) == {"packages/brain/CHANGELOG.md", "CHANGELOG.md"}


def test_check_refuses_a_malformed_fragment_and_an_unreleased_section(repo):
    _frag(repo, "no-head", "- a bullet with no section line\n")
    _frag(repo, "bad-section", "section: Removed\n\n- x\n")
    _frag(repo, "empty", "section: Fixes\n\n")
    (repo / "CHANGELOG.md").write_text(RG_LOG.replace("## 0.2.8", "## Unreleased\n\n- x\n\n## 0.2.8"),
                                       encoding="utf-8")
    got = "\n".join(changelog.check(repo))
    assert "no-head.md: its first line is 'section:" in got
    assert "bad-section.md: section 'Removed' is one of Upgrade, Added, Fixes, Changes" in got
    assert "empty.md: no entry after its section line" in got
    assert "CHANGELOG.md: a '## Unreleased' section: write the entry as a fragment" in got
    with pytest.raises(ValueError):
        changelog.compile_release(repo, "0.3.0", "t", "2026-11-10")


def test_the_cli_plans_then_writes(repo, capsys):
    _frag(repo, "wi-x", "section: Changes\n\n- something\n", dist="research-graph")
    assert changelog.main(["--repo", str(repo), "compile", "0.3.0", "--theme", "t", "--date", "2026-11-10"]) == 0
    assert "not written: --write" in capsys.readouterr().out
    assert changelog.pending(repo)
    assert changelog.main(["--repo", str(repo), "compile", "0.3.0", "--theme", "t", "--date", "2026-11-10",
                           "--write"]) == 0
    assert "### Changes\n\n- something" in (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.main(["--repo", str(repo), "check"]) == 0
