"""installer/release_check.py, the version PR's job, on small git repos shaped like this one."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
SCRIPT = PACKAGE / "installer" / "release_check.py"

spec = importlib.util.spec_from_file_location("release_check", SCRIPT)
release_check = importlib.util.module_from_spec(spec)
sys.modules["release_check"] = release_check
spec.loader.exec_module(release_check)

GRAPH_INIT = "src/research_graph/__init__.py"
BRAIN_INIT = "packages/brain/src/brain/__init__.py"
PYPROJECT = "packages/brain/pyproject.toml"
COMMON = "packages/brain/src/brain/adapters/claude/hooks/common.sh"
ROOT_LOG = "CHANGELOG.md"
BRAIN_LOG = "packages/brain/CHANGELOG.md"
CONFIG_SCHEMA = "packages/brain/src/brain/schemas/config.schema.json"
STORE_SCHEMA = "src/research_graph/templates/schema.yaml"
OTHER = "packages/brain/src/brain/cockpit.py"


def write(repo: Path, path: str, text: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                    "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args], check=True, capture_output=True)


def versions(repo: Path, version: str) -> None:
    write(repo, GRAPH_INIT, f'__version__ = "{version}"\n')
    write(repo, BRAIN_INIT, f'__version__ = "{version}"\n')
    write(repo, PYPROJECT, f'dependencies = ["research-graph @ git+https://github.com/RoJLD/brain.git@v{version}",\n]\n')
    write(repo, COMMON, f"#!/usr/bin/env bash\nbrain_version={version}\nnext=1\n")


def changelogs(repo: Path, version: str, brain_body: str = "- A change.\n") -> None:
    write(repo, ROOT_LOG, f"# Changelog\n\n## {version} — 2026-11-09\n\n- Nothing new.\n\n## 0.2.5 — 2026-11-04\n\n- Old.\n")
    write(repo, BRAIN_LOG, f"# Changelog\n\n## {version} — 2026-11-09\n\n{brain_body}\n"
                           "## 0.2.5 — 2026-11-04\n\n### Upgrade\n\n1. An old step.\n")


@pytest.fixture
def repo(tmp_path):
    """A repo tagged v0.2.5, with a schema of each kind and an ordinary module."""
    here = tmp_path / "repo"
    here.mkdir()
    git(here, "init", "-q")
    versions(here, "0.2.5")
    write(here, ROOT_LOG, "# Changelog\n\n## 0.2.5 — 2026-11-04\n\n- Old.\n")
    write(here, BRAIN_LOG, "# Changelog\n\n## 0.2.5 — 2026-11-04\n\n### Upgrade\n\n1. An old step.\n")
    write(here, CONFIG_SCHEMA, '{"properties": {}}\n')
    write(here, STORE_SCHEMA, "node_types: []\n")
    write(here, OTHER, "x = 1\n")
    git(here, "add", "-A")
    git(here, "commit", "-qm", "first")
    git(here, "tag", "v0.2.5")
    return here


def commit(repo: Path) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "next")


def run(repo: Path, capsys) -> tuple[int, str]:
    rc = release_check.main(["--repo", str(repo)])
    out = capsys.readouterr()
    return rc, out.out + out.err


# The two cases the job is for


def test_schema_changed_without_an_upgrade_section_fails(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "FAILED" in text and CONFIG_SCHEMA in text and "### Upgrade" in text


def test_schema_changed_with_an_upgrade_section_passes(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6", "### Upgrade\n\n1. Run brain sync.\n\n### Changes\n\n- A change.\n")
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 0, text
    assert CONFIG_SCHEMA in text and "FAILED" not in text


# Around them


def test_a_version_pr_without_a_schema_change_needs_no_upgrade_section(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    write(repo, OTHER, "x = 2\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 0, text
    assert "no registered schema changed" in text


def test_a_store_schema_counts_too(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    write(repo, STORE_SCHEMA, "node_types: [Lesson]\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert STORE_SCHEMA in text


def test_a_removed_schema_counts_too(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    (repo / CONFIG_SCHEMA).unlink()
    commit(repo)
    assert run(repo, capsys)[0] == 1


def test_a_schema_changed_in_an_earlier_pr_since_the_tag_still_counts(repo, capsys):
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')
    commit(repo)
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    commit(repo)
    assert run(repo, capsys)[0] == 1


@pytest.mark.parametrize("body", [
    "### Upgrade\n\n### Changes\n\n- A change.\n",   # an empty section says nothing
    "### Upgrade\n",
    "- ### Upgrade is only named here.\n",
    "### Changes\n\n- Upgrade by hand.\n",
])
def test_an_upgrade_section_that_says_nothing_does_not_count(repo, capsys, body):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6", body)
    write(repo, CONFIG_SCHEMA, "{}\n")
    commit(repo)
    assert run(repo, capsys)[0] == 1


def test_the_upgrade_section_of_another_version_does_not_count():
    log = ("## Unreleased\n\n### Upgrade\n\n1. Later.\n\n## 0.2.6 — d\n\n- No section.\n\n"
           "## 0.2.5 — d\n\n### Upgrade\n\n1. Old.\n")
    assert release_check.upgrade_section(log, "0.2.6") is None
    assert release_check.upgrade_section(log, "0.2.5") == "1. Old."
    assert release_check.upgrade_section(log, "0.2.4") is None


def test_the_upgrade_section_ends_at_the_next_heading():
    log = "## 0.2.6 — d\n\n### Upgrade\n\n1. Step.\n\n### Changes\n\n- Other.\n\n## 0.2.5 — d\n\n- Old.\n"
    assert release_check.upgrade_section(log, "0.2.6") == "1. Step."


def test_any_other_pr_passes_at_once_even_with_a_schema_change(repo, capsys):
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 0, text
    assert "not a version PR" in text


@pytest.mark.parametrize("left_behind, expected", [
    (GRAPH_INIT, "the versions differ"),
    (BRAIN_INIT, "the versions differ"),
    (PYPROJECT, "does not pin research-graph at v0.2.6"),
    (COMMON, "brain_version=0.2.6"),
])
def test_a_place_the_version_pr_left_behind_fails(repo, capsys, left_behind, expected):
    before = (repo / left_behind).read_text(encoding="utf-8")
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    write(repo, left_behind, before)
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert expected in text


@pytest.mark.parametrize("log", [ROOT_LOG, BRAIN_LOG])
def test_a_changelog_without_the_versions_section_fails(repo, capsys, log):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    write(repo, log, "# Changelog\n\n## Unreleased\n\n- Not dated yet.\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert f"{log} has no section ## 0.2.6" in text


def test_a_section_without_a_date_fails(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    write(repo, ROOT_LOG, "# Changelog\n\n## 0.2.6\n\n- Not dated.\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "has no date" in text


def test_a_version_behind_the_tag_fails(repo, capsys):
    versions(repo, "0.2.4")
    changelogs(repo, "0.2.4")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "is not after the last tag" in text


def test_no_version_found_fails(repo, capsys):
    write(repo, GRAPH_INIT, "nothing = 1\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "no __version__" in text


def test_no_tag_is_neither_a_pass_nor_a_failure(tmp_path, capsys):
    here = tmp_path / "untagged"
    here.mkdir()
    git(here, "init", "-q")
    versions(here, "0.2.6")
    commit(here)
    rc, text = run(here, capsys)
    assert rc == 2
    assert "cannot tell" in text


def test_a_tag_that_does_not_exist_is_neither_a_pass_nor_a_failure(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    rc = release_check.main(["--repo", str(repo), "--against", "v9.9.9"])
    assert rc == 2
    assert "cannot tell" in capsys.readouterr().err


def test_the_script_runs_alone_as_ci_runs_it(repo):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    write(repo, CONFIG_SCHEMA, "{}\n")
    commit(repo)
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(repo)], capture_output=True, text=True,
                          encoding="utf-8", check=False)
    assert done.returncode == 1
    assert "FAILED" in done.stderr


# This repo's own contract


def test_every_registered_format_has_its_schema_declared():
    folders = {p.name for p in (PACKAGE / "tests" / "fixtures" / "formats").iterdir() if p.is_dir()}
    assert folders <= set(release_check.SCHEMAS)
    assert set(release_check.SCHEMAS) - folders == {"store"}


def test_every_json_schema_of_the_engine_is_registered():
    registered = {path for paths in release_check.SCHEMAS.values() for path in paths}
    found = {p.relative_to(ROOT).as_posix() for p in (PACKAGE / "src" / "brain" / "schemas").glob("*.schema.json")}
    assert found and found <= registered


def test_only_permissions_has_no_schema_file():
    assert [name for name, paths in release_check.SCHEMAS.items() if not paths] == ["permissions"]


def test_every_registered_schema_file_exists():
    for paths in release_check.SCHEMAS.values():
        for path in paths:
            assert (ROOT / path).is_file(), path


def test_the_real_version_files_are_where_the_script_reads_them():
    for path in (*release_check.VERSIONS.values(),):
        assert release_check.version_in(ROOT, path)
    assert "brain_version=" in (ROOT / COMMON).read_text(encoding="utf-8")
    assert "research-graph @ git+https://github.com/RoJLD/brain.git@v" in (ROOT / PYPROJECT).read_text(encoding="utf-8")


def test_the_changelog_says_each_upgrade():
    """The 0.2.5 section, and the steps from 0.2.5 (the item's part 1)."""
    log = (ROOT / BRAIN_LOG).read_text(encoding="utf-8")
    assert "brain sync" in release_check.upgrade_section(log, "0.2.5")
    # Unreleased until the version PR dates it: this test must pass on that PR as well
    upgrade = release_check.upgrade_section(log, "0.2.6")
    if upgrade is None:
        unreleased = log.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
        upgrade = unreleased.split("### Upgrade", 1)[1].split("\n### ", 1)[0]
    for needed in ("brain update", "engine.pin", "brain config --check", "brain check --public --history",
                   "Restart the Claude Code sessions"):
        assert needed in upgrade, needed


def test_ci_runs_the_job_on_pull_requests():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci.split("  release-check:", 1)[1].split("\n  release-tag:", 1)[0]
    assert "github.event_name == 'pull_request'" in job
    assert "fetch-depth: 0" in job     # describe and diff need the tags
    assert "packages/brain/installer/release_check.py" in job


def test_the_release_page_says_each_step():
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    for needed in ("### Upgrade", "release-check", "compat-prev", "release-tag", "git tag -a", "engine.pin",
                   "brain check --public --history", "tests/fixtures/formats", "brain_version"):
        assert needed in page, needed
