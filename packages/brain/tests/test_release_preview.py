"""installer/release_check.py --preview, the release preview on every PR (wi-brain-release-preview), and the
refusal of a standard step two Upgrade fragments ask; on the small git repos of test_release_check.py."""
from __future__ import annotations

from pathlib import Path

from test_release_check import (CONFIG_SCHEMA, MOVED, OTHER, ROOT, commit, git, release_check, repo,
                                run, versions, write)

# The release preview (wi-brain-release-preview): on any PR, would the next release be a patch of the last tag?

FRAGMENTS = "packages/brain/changes"
STANDARD_FRAGMENT = ("section: Upgrade\n\n1. **Install the engine**: `brain update`.\n"
                     "2. **Restart the Claude Code sessions**.\n3. **Refresh the public stamp**: in each public repo.\n")


def preview(repo: Path, capsys, tmp_path, base: str | None = "base") -> tuple[int, str, str]:
    summary = tmp_path / "summary.md"
    rc = release_check.main(["--repo", str(repo), "--preview", "--summary", str(summary)]
                            + (["--base", base] if base else []))
    out = capsys.readouterr()
    return rc, out.out + out.err, summary.read_text(encoding="utf-8") if summary.exists() else ""


def branch(repo: Path) -> None:
    """main's state at the PR's fork is the branch ``base``; the PR's commits come after it."""
    git(repo, "branch", "base")


def test_preview_a_pr_that_moves_a_format_makes_the_next_release_a_minor(repo, capsys, tmp_path):
    branch(repo)
    write(repo, CONFIG_SCHEMA, MOVED)
    commit(repo)
    rc, text, summary = preview(repo, capsys, tmp_path)
    assert rc == 0, text   # advisory: it says, it never fails the PR
    assert "a minor, 0.3.0, not the patch 0.2.6, because of this PR" in text
    assert f"a registered schema moved since v0.2.5: {CONFIG_SCHEMA} (this PR)" in text
    assert summary.startswith("### Release preview: Minor\n") and CONFIG_SCHEMA in summary


def test_preview_a_pr_with_nothing_that_moves_is_a_patch(repo, capsys, tmp_path):
    branch(repo)
    write(repo, OTHER, "x = 2\n")
    write(repo, CONFIG_SCHEMA, '{"properties": {"new": {}}}\n')   # an optional key: a patch's
    write(repo, f"{FRAGMENTS}/standard-upgrade.md", STANDARD_FRAGMENT)
    write(repo, f"{FRAGMENTS}/wi-z-note.md", "section: Upgrade\n\nNothing to run for the rest.\n")
    write(repo, f"{FRAGMENTS}/wi-x.md", "section: Fixes\n\n- a fix\n")
    commit(repo)
    rc, text, summary = preview(repo, capsys, tmp_path)
    assert rc == 0 and "a patch, 0.2.6: nothing pending moves a format" in text, text
    assert "grown by optional keys only" in text and "no pending Upgrade step beyond the standard ones" in text
    assert summary.startswith("### Release preview: Patch\n")


def test_preview_an_upgrade_step_beyond_the_standard_ones_numbered_or_not(repo, capsys, tmp_path):
    write(repo, f"{FRAGMENTS}/standard-upgrade.md", STANDARD_FRAGMENT)
    commit(repo)
    branch(repo)
    write(repo, f"{FRAGMENTS}/wi-y.md", "section: Upgrade\n\n**Move the store**: `brain store move`, once.\n")
    rc, text, _ = preview(repo, capsys, tmp_path)   # not committed yet: the preview runs before a commit too
    assert rc == 0
    assert "a minor, 0.3.0, not the patch 0.2.6, because of this PR" in text, text
    assert (f"an Upgrade step beyond the standard ones: {FRAGMENTS}/wi-y.md: **Move the store**: `brain store move`, "
            f"once. (this PR)") in text
    assert release_check.fragment_steps("4. **A**: x\n   more\n5. **B**") == ["4. **A**: x", "5. **B**"]
    assert release_check.fragment_steps("Nothing to run for the rest.") == []


def test_preview_a_minor_already_before_this_pr(repo, capsys, tmp_path):
    write(repo, CONFIG_SCHEMA, MOVED)
    commit(repo)
    branch(repo)
    write(repo, OTHER, "x = 2\n")
    commit(repo)
    rc, text, _ = preview(repo, capsys, tmp_path)
    assert rc == 0 and "already before this PR, which adds no reason" in text, text
    rc, text, _ = preview(repo, capsys, tmp_path, base=None)   # without --base: the verdict alone
    assert "a minor, 0.3.0, not the patch 0.2.6\n" in text


def test_a_fragment_that_copies_a_standard_step_fails_every_pr(repo, capsys, tmp_path):
    """les-brain-upgrade-fragment-copies-standard: views-one-writer's fragment repeated the three standard steps."""
    write(repo, f"{FRAGMENTS}/standard-upgrade.md", STANDARD_FRAGMENT)
    write(repo, f"{FRAGMENTS}/wi-views.md", "section: Upgrade\n\n**Restart the Claude Code sessions.**\n")
    commit(repo)
    rc, text = run(repo, capsys)
    assert rc == 1 and "not a version PR" in text
    assert ("the standard step **Restart the Claude Code sessions** is asked 2 times by the Upgrade fragments "
            f"({FRAGMENTS}/standard-upgrade.md, {FRAGMENTS}/wi-views.md)") in text
    rc, text, _ = preview(repo, capsys, tmp_path, base=None)
    assert rc == 0 and "a fragment copies a standard step" in text
    assert "a patch, 0.2.6" in text   # a copy is a mistake to fix, not a reason for a minor


def test_preview_with_no_tag_cannot_tell(tmp_path, capsys):
    here = tmp_path / "untagged"
    here.mkdir()
    git(here, "init", "-q")
    versions(here, "0.2.6")
    commit(here)
    assert release_check.main(["--repo", str(here), "--preview", "--summary", ""]) == 2
    assert "release-preview: cannot tell" in capsys.readouterr().err


def test_ci_runs_the_preview_on_every_pr_as_an_advisory_job():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci.split("  release-preview:", 1)[1].split("\n  release-check:", 1)[0]
    assert "github.event_name == 'pull_request'" in job and "fetch-depth: 0" in job
    assert "continue-on-error: true" in job
    assert "release_check.py --preview --base \"origin/${{ github.base_ref }}\"" in job
    page = (ROOT / "docs" / "release.md").read_text(encoding="utf-8")
    assert "### The release preview" in page and "--preview" in page


def test_preview_on_a_version_pr_leaves_it_to_release_check(repo, capsys, tmp_path):
    versions(repo, "0.2.6")
    commit(repo)
    rc, text, _ = preview(repo, capsys, tmp_path, base=None)
    assert rc == 0 and "a version PR: release-check judges it" in text


def test_one_fragment_that_asks_a_standard_step_twice_is_a_copy_too(repo):
    write(repo, f"{FRAGMENTS}/standard-upgrade.md", STANDARD_FRAGMENT + "4. **Install the engine** again.\n")
    import changelog   # beside release_check.py, which put its folder on sys.path
    found = release_check.standard_step_copies(repo, changelog.load(repo, "brain")[0])
    assert len(found) == 1 and "**Install the engine** is asked 2 times" in found[0]


def test_each_bold_paragraph_of_an_unnumbered_fragment_is_a_step():
    assert release_check.fragment_steps("Before installing:\n\n**Move the store**: x.") == ["**Move the store**: x."]
    assert release_check.fragment_steps("**Move the store**: x.\n\n**Restart the Claude Code sessions**, then y.\n"
                                        "**not a paragraph**, a line of the one above") == [
        "**Move the store**: x.", "**Restart the Claude Code sessions**, then y."]


def test_preview_on_a_version_pr_reads_its_upgrade_section(repo, capsys, tmp_path):
    versions(repo, "0.2.6")
    write(repo, "packages/brain/CHANGELOG.md", "# Changelog\n\n## 0.2.6 — 2026-11-09 — t\n\n### Upgrade\n\n"
                                               "1. **Install the engine**.\n2. **Move the store**: once.\n\n"
                                               "## 0.2.5 — 2026-11-04\n\n- Old.\n")
    commit(repo)
    rc, text, summary = preview(repo, capsys, tmp_path, base=None)
    assert rc == 0 and "a minor, 0.3.0, not the patch 0.2.6" in text
    assert "packages/brain/CHANGELOG.md: 2. **Move the store**: once." in text and "Minor" in summary


def test_preview_says_what_it_cannot_read_and_never_fails_on_its_summary(repo, capsys, tmp_path):
    write(repo, f"{FRAGMENTS}/wi-z.md", "section: Fixes\n\n- x\n")
    (repo / FRAGMENTS / "wi-z.md").write_bytes("section: Fixes\n\n- caf\xe9\n".encode("cp1252"))
    assert release_check.main(["--repo", str(repo), "--preview", "--summary", ""]) == 2
    assert "release-preview: cannot tell" in capsys.readouterr().err
    (repo / FRAGMENTS / "wi-z.md").unlink()
    missing = tmp_path / "no" / "such" / "folder" / "summary.md"
    assert release_check.main(["--repo", str(repo), "--preview", "--summary", str(missing)]) == 0
    assert "the summary not written" in capsys.readouterr().err
