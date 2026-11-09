"""installer/release_check.py, the version PR's job, on small git repos shaped like this one."""
from __future__ import annotations

import importlib.util
import os
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


def changelogs(repo: Path, version: str, brain_body: str = "- A change.\n", theme: str = " — A theme") -> None:
    write(repo, ROOT_LOG, f"# Changelog\n\n## {version} — 2026-11-09\n\n- Nothing new.\n\n## 0.2.5 — 2026-11-04\n\n- Old.\n")
    write(repo, BRAIN_LOG, f"# Changelog\n\n## {version} — 2026-11-09{theme}\n\n{brain_body}\n"
                           "## 0.2.5 — 2026-11-04\n\n### Upgrade\n\n1. An old step.\n")


# The standard steps as an owner reads them (docs/release.md), continuation lines, a sub-step and prose included
STANDARD_UPGRADE = (
    "### Upgrade\n\nFrom 0.2.5, in this order.\n\n"
    "1. **Install the engine**, in your own terminal: `brain update`, then `y`.\n"
    "   A brain that declares `engine.installer`: its `-Apply`.\n"
    "2. **Restart the Claude Code sessions**, so that they run the hooks `brain sync` rendered.\n"
    "   1. a nested line is part of its step.\n"
    "3. **Refresh the public stamp:** `brain check --public --history` in each public repo's checkout.\n\n"
    "Nothing to run for the rest.\n\n- A note.\n\n### Fixes\n\n- A fix.\n")


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
    versions(repo, "0.3.0")
    changelogs(repo, "0.3.0")
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "FAILED" in text and CONFIG_SCHEMA in text and "### Upgrade" in text
    assert "number the standard steps" in text and "nothing to run" not in text


def test_schema_changed_with_an_upgrade_section_passes(repo, capsys):
    versions(repo, "0.3.0")
    changelogs(repo, "0.3.0", "### Upgrade\n\n1. Run brain sync.\n\n### Changes\n\n- A change.\n")
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
    versions(repo, "0.3.0")
    changelogs(repo, "0.3.0")
    write(repo, STORE_SCHEMA, "node_types: [Lesson]\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert STORE_SCHEMA in text


def test_a_removed_schema_counts_too(repo, capsys):
    versions(repo, "0.3.0")
    changelogs(repo, "0.3.0")
    (repo / CONFIG_SCHEMA).unlink()
    commit(repo)
    assert run(repo, capsys)[0] == 1


def test_a_schema_changed_in_an_earlier_pr_since_the_tag_still_counts(repo, capsys):
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')
    commit(repo)
    versions(repo, "0.3.0")
    changelogs(repo, "0.3.0")
    commit(repo)
    assert run(repo, capsys)[0] == 1


@pytest.mark.parametrize("body", [
    "### Upgrade\n\n### Changes\n\n- A change.\n",   # an empty section says nothing
    "### Upgrade\n",
    "- ### Upgrade is only named here.\n",
    "### Changes\n\n- Upgrade by hand.\n",
])
def test_an_upgrade_section_that_says_nothing_does_not_count(repo, capsys, body):
    versions(repo, "0.3.0")
    changelogs(repo, "0.3.0", body)
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


def test_the_script_writes_utf_8_to_a_pipe_whatever_the_code_page(repo):
    """A message that quotes « a title » reaches a UTF-8 reader as written (on Windows a pipe is in the ANSI page)."""
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6", theme="")
    commit(repo)
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}   # what a Windows pipe gets (-I drops it)
    done = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo)], capture_output=True, env=env, check=False)
    assert done.returncode == 1
    assert "« The version policy »" in done.stderr.decode("utf-8")


# The version policy (docs/release.md, « The version policy »)


@pytest.mark.parametrize("tag, version, patch", [
    ("v0.2.5", "0.2.6", True),
    ("v0.2.5", "0.2.9", True),
    ("v0.2.5", "0.3.0", False),
    ("v0.2.5", "1.0.0", False),
    ("v1.0.0", "1.0.1", True),
    ("v0.2.5", "0.2.5", False),
    ("v0.2.5", "0.2.4", False),
    ("v0.2.5", "0.2.6rc1", False),
])
def test_a_patch_moves_only_the_last_number(tag, version, patch):
    assert release_check.is_patch(tag, version) is patch


def test_a_patch_with_a_schema_change_fails_even_with_its_upgrade_section(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6", "### Upgrade\n\n1. Run brain sync.\n\n### Changes\n\n- A change.\n")
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "0.2.6 is a patch of v0.2.5 and registered schemas changed" in text and CONFIG_SCHEMA in text
    assert "minor version" in text


def test_the_same_change_as_a_minor_version_passes(repo, capsys):
    versions(repo, "0.3.0")
    changelogs(repo, "0.3.0", "### Upgrade\n\n1. **Edit config.json** by hand.\n\n### Changes\n\n- A change.\n")
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 0, text
    assert "a patch of" not in text


def test_a_patch_with_only_the_standard_steps_passes(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6", STANDARD_UPGRADE)
    write(repo, OTHER, "x = 2\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 0, text
    assert "a patch of v0.2.5" in text


def test_a_patch_without_an_upgrade_section_passes(repo, capsys):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6", "### Fixes\n\n- A fix.\n")
    commit(repo)
    assert run(repo, capsys)[0] == 0


@pytest.mark.parametrize("step", [
    "4. **Read this if a script of yours runs `brain --project P`:** it now acts on the worktree.",  # 0.2.7's step 4
    "4. **Check the configuration first**, with the old engine still installed.",
    "4. Run `brain merge-driver install --apply`.",                                               # no title at all
    "4) **Edit config.json**: add `usage.plans`.",
])
def test_a_patch_with_a_step_beyond_the_standard_ones_fails(repo, capsys, step):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6", STANDARD_UPGRADE.replace("\nNothing to run", f"{step}\n\nNothing to run"))
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "asks more than the standard steps" in text and step in text


def test_the_standard_steps_are_told_apart_by_their_title():
    upgrade = ("1. **install the engine.** again\n"
               "2. **Restart the Claude Code sessions:** now\n"
               "   3. **An indented line** is part of the step above\n"
               "10. **Refresh the public stamp**\n"
               "- 4. **A bullet** is not a step\n"
               "5. **Restart Claude Code's sessions**, another title\n"
               "6. Install the engine, with no bold title\n")
    assert release_check.steps_beyond_standard(upgrade) == [
        "5. **Restart Claude Code's sessions**, another title", "6. Install the engine, with no bold title"]
    assert release_check.steps_beyond_standard("Nothing to run.") == []


def test_a_minor_version_may_ask_anything(repo, capsys):
    versions(repo, "0.3.0")
    changelogs(repo, "0.3.0", STANDARD_UPGRADE.replace("\nNothing to run", "4. **Edit config.json**.\n\nNothing to run"))
    commit(repo)
    assert run(repo, capsys)[0] == 0


HOTFIX = "- A guard no longer refuses every commit: it reads the config\n  before the index.\n"


def test_an_entry_a_patch_from_release_x_y_released_fails_in_the_next_version(repo, capsys):
    """The fix merged on main, shipped in 0.2.6 from release/0.2; release/0.2 merged back and main's Unreleased kept it."""
    versions(repo, "0.3.0")
    write(repo, ROOT_LOG, "# Changelog\n\n## 0.3.0 — 2026-11-16\n\n- Nothing new.\n\n## 0.2.6 — 2026-11-10\n\n- Same.\n")
    write(repo, BRAIN_LOG, f"# Changelog\n\n## 0.3.0 — 2026-11-16 — A theme\n\n### Fixes\n\n- Another fix.\n"
                           f"{HOTFIX.replace('it reads', 'it  reads')}\n"
                           f"## 0.2.6 — 2026-11-10 — The guard\n\n### Fixes\n\n{HOTFIX}\n"
                           "## 0.2.5 — 2026-11-04\n\n### Upgrade\n\n1. An old step.\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "the section ## 0.3.0 repeats an entry that 0.2.6 released: A guard no longer refuses" in text
    assert "Another fix" not in text


def test_entries_are_bullets_with_their_continuation_lines():
    log = ("## Unreleased\n\n- Pending.\n\n## 0.2.6 — 2026-11-10 — T\n\n### Fixes\n\n- One\n  two.\n- Three.\n"
           "Not a bullet.\n  - nor this.\n\n## 0.2.5 — 2026-11-04\n\n1. A step.\n- Pending.\n")
    assert release_check.entries(log) == {"0.2.6": ["One two.", "Three."], "0.2.5": ["Pending."]}
    assert release_check.entries_already_released(log, "0.2.6") == []
    assert release_check.entries_already_released(log + "\n## 0.2.4 — 2026-11-01\n\n- Three.\n", "0.2.6") == [
        ("Three.", "0.2.4")]


def test_the_brain_changelog_repeats_no_released_entry():
    log = (ROOT / BRAIN_LOG).read_text(encoding="utf-8")
    for version in release_check.entries(log):
        assert release_check.entries_already_released(log, version) == [], version


@pytest.mark.parametrize("after_the_date", ["", " ", " —", " — :", " - "])
def test_a_section_heading_without_a_theme_fails(repo, capsys, after_the_date):
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6", theme=after_the_date)
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "names no theme" in text


def test_the_theme_is_what_follows_the_date():
    assert release_check.theme(" — 2026-11-10 — The review fixes") == "The review fixes"
    assert release_check.theme(" — 2026-11-10: guards") == "guards"
    assert release_check.theme(" — 2026-11-10") == ""
    assert release_check.theme(" — no date — a theme") == ""
    assert release_check.theme(" (2026-11-10) — guards") == "guards"


@pytest.mark.parametrize("heading", ["## 0.2.6 (2026-11-09)", "## 0.2.6 — 2026-11-09 — )", "## 0.2.6 [2026-11-09] — …",
                                     "## 0.2.6 — 2026-11-09 — « »"])
def test_punctuation_after_the_date_is_no_theme(repo, capsys, heading):
    """A theme says what the release is about: what is left after the date has a letter or a digit in it."""
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    log = (repo / BRAIN_LOG).read_text(encoding="utf-8").replace("## 0.2.6 — 2026-11-09 — A theme", heading)
    write(repo, BRAIN_LOG, log)
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1
    assert "names no theme" in text


def test_the_root_changelog_needs_no_theme(repo, capsys):
    """research-graph's section is often one line: the theme is said once, in the brain's."""
    versions(repo, "0.2.6")
    changelogs(repo, "0.2.6")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 0, text


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


def test_the_release_page_writes_the_version_policy():
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    policy = page.split("## The version policy", 1)[1].split("\n## ", 1)[0]
    for needed in ("minor", "patch", "theme", "cut from the last tag", "cadence", "review fixes", "0.2.7",
                   "## X.Y.Z — YYYY-MM-DD — theme"):
        assert needed in policy, needed


def test_the_policy_examples_say_they_were_patches_before_it():
    """0.2.5 and 0.2.6 were patches, released before the policy: an example that names them as minor versions says so,
    and the page says every release up to 0.2.7 predates the policy, not 0.2.7 alone."""
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    policy = page.split("## The version policy", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in policy.splitlines() if line.startswith("| ") and "`0.Y.0`" in line]
    assert rows
    for row in rows:
        for version in ("0.2.5", "0.2.6"):
            if version in row:
                assert f"{version}, a patch before this policy, would be 0.Y.0 under it" in row, row
    assert "Every release up to 0.2.7 predates this policy" in policy


def test_the_release_page_says_one_thing_of_a_release_with_nothing_else_to_do():
    """Every Upgrade numbers the standard steps, so no release has nothing to do: « The standard steps » and section 2
    both say « Nothing to run for the rest », and neither says a bare « Nothing to run »."""
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    standard = page.split("### The standard steps", 1)[1].split("\n## ", 1)[0]
    version_pr = page.split("## 2. The version PR", 1)[1].split("\n## ", 1)[0]
    for part in (standard, version_pr):
        assert "« Nothing to run for the rest »" in part
    assert "« Nothing to run »" not in page


def test_choose_the_number_gives_both_rows_of_the_policy_for_a_minor():
    """Section 1's bullet is the guidance read when choosing: a step beyond the standard ones, and a format that moves
    (a registered schema, what `brain init` wrote once) even with no step, each make it 0.Y.0."""
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    before = page.split("## 1. Before the version PR", 1)[1].split("\n## ", 1)[0]
    bullet = " ".join(before.split("**Choose the number**", 1)[1].split("\n- ", 1)[0].split())
    for needed in ("beyond the standard steps", "registered schema", "`brain init` wrote once", "even with no step",
                   "`0.Y.0`"):
        assert needed in bullet, needed


def test_the_tag_section_names_the_theme_and_the_patch_that_cannot_wait():
    """The policy names the theme in the tag message and cuts a fix that cannot wait from release/X.Y (« 3. The tag »):
    the tag section shows both, and says that release-tag does not check the theme."""
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    tag = page.split("## 3. The tag", 1)[1].split("\n## ", 1)[0]
    assert 'git tag -a vX.Y.Z -m "brain X.Y.Z and research-graph X.Y.Z — theme: what it brings"' in tag
    assert "git switch release/X.Y" in tag and "release/X.Y` merges back into main" in tag
    assert "does not check the theme" in tag
    assert "takes out of main's `## Unreleased` every entry that `## X.Y.Z+1`" in tag
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "theme" not in ci.split("  release-tag:", 1)[1]   # what the page says of the job stays true


def test_the_release_page_gives_each_standard_step_its_title():
    """The template an Upgrade section copies, so that a patch's steps are the ones the check knows."""
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    template = page.split("### The standard steps", 1)[1].split("\n#", 1)[0]
    assert release_check.steps_beyond_standard(template) == []
    for title in release_check.STANDARD_STEPS:
        assert f"**{title}**" in template, title


def test_0_2_7_is_the_last_release_before_the_policy():
    """Decided 2026-11-09: 0.2.7 stays a patch. Its Upgrade asked more than the standard steps: the policy, not 0.2.7,
    is what changed, so the check never runs against it (a version PR is checked against the tag before it).

    The check would refuse three of its four steps, and the page says which and why: step 4, the one beyond the
    standard steps, and steps 2 and 3, the standard ones under the titles they had before the policy named them."""
    upgrade = release_check.upgrade_section((ROOT / BRAIN_LOG).read_text(encoding="utf-8"), "0.2.7")
    assert release_check.is_patch("v0.2.6", "0.2.7")
    beyond = release_check.steps_beyond_standard(upgrade)
    titles = [release_check.TITLE_RE.match(release_check.STEP_RE.match(line).group(1)).group(1) for line in beyond]
    assert [line.split(".", 1)[0] for line in beyond] == ["2", "3", "4"], beyond
    assert titles[2].startswith("Read this if a script of yours runs `brain --project P`"), beyond
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    note = page.split("0.2.7 is the last release before this policy", 1)[1].split("\n\n", 1)[0]
    for old_title in titles[:2]:
        assert f"**{old_title}**" in note, old_title
    assert "`brain --project P`" in note
