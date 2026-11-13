"""The release a wave will be (wi-brain-wave-version-forecast): release_check.py --preview --ref/--json, and
brain.nextrelease as brain next and brain wave check read it; on the small git repos of test_release_check.py."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from brain import nextrelease
from test_release_check import CONFIG_SCHEMA, MOVED, OTHER, PACKAGE, git, release_check, repo, write  # noqa: F401

FRAGMENTS = "packages/brain/changes"
STEP = "section: Upgrade\n\n**Move the store**: `brain store move`, once.\n"


def preview_json(repo: Path, capsys, *args: str) -> dict:
    rc = release_check.main(["--repo", str(repo), "--preview", "--json", *args])
    out = capsys.readouterr()
    assert rc == 0, out.err
    return json.loads(out.out)


def merge(repo: Path, branch: str, number: int, path: str, text: str) -> None:
    """A PR merged on main as GitHub merges it: a branch with one commit, then a merge commit that names the PR."""
    git(repo, "checkout", "-qb", branch)
    write(repo, path, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"the change of {branch}")
    git(repo, "checkout", "-q", "-")
    git(repo, "merge", "--no-ff", "-q", "-m", f"Merge pull request #{number} from someone/{branch}", branch)


def main_branch(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True,
                          check=True).stdout.strip()


# release_check.py --preview --ref --json


def test_the_preview_of_a_ref_reads_that_commit_not_the_working_tree(repo, capsys):
    write(repo, CONFIG_SCHEMA, MOVED)   # uncommitted: the working tree tips to a minor, HEAD does not
    assert preview_json(repo, capsys)["kind"] == "minor"
    data = preview_json(repo, capsys, "--ref", "HEAD")
    assert data["kind"] == "patch" and data["release"] == "0.2.6" and data["reasons"] == []
    assert (repo / CONFIG_SCHEMA).read_text(encoding="utf-8") == MOVED   # the working tree is left as it is


def test_the_preview_of_a_ref_reads_its_fragments_and_names_the_pr_that_tipped_it(repo, capsys):
    merge(repo, "fix-a", 7, OTHER, "x = 2\n")
    merge(repo, "step-b", 8, f"{FRAGMENTS}/wi-b.md", STEP)
    merge(repo, "schema-c", 9, CONFIG_SCHEMA, MOVED)
    data = preview_json(repo, capsys, "--ref", main_branch(repo))
    assert data["kind"] == "minor" and data["release"] == "0.3.0" and data["patch"] == "0.2.6"
    assert data["tipped_by"]["pr"] == 8 and data["tipped_by"]["subject"].startswith("Merge pull request #8")
    kinds = {r["kind"]: r for r in data["reasons"]}
    assert kinds["schema"]["path"] == CONFIG_SCHEMA and kinds["schema"]["first"]["pr"] == 9
    assert kinds["upgrade"]["step"].startswith("**Move the store**") and kinds["upgrade"]["first"]["pr"] == 8
    assert any(line.startswith("first tipped to a minor by") for line in data["lines"])


def test_an_uncommitted_reason_has_no_first_commit(repo, capsys):
    write(repo, f"{FRAGMENTS}/wi-b.md", STEP)
    data = preview_json(repo, capsys)
    assert data["kind"] == "minor" and data["tipped_by"] is None and data["reasons"][0]["first"] is None


def test_json_writes_no_summary(repo, capsys, tmp_path):
    summary = tmp_path / "summary.md"
    assert release_check.main(["--repo", str(repo), "--preview", "--json", "--summary", str(summary)]) == 0
    capsys.readouterr()
    assert not summary.exists()


def test_a_ref_git_cannot_read_cannot_tell(repo, capsys):
    assert release_check.main(["--repo", str(repo), "--preview", "--ref", "no-such-ref", "--json"]) == 2
    assert "cannot tell" in capsys.readouterr().err


# brain.nextrelease


@pytest.fixture
def engine(repo):
    """The fixture repo as an engine checkout: the preview's two scripts committed at their place."""
    for name in nextrelease.SCRIPTS:
        write(repo, f"packages/brain/installer/{name}", (PACKAGE / "installer" / name).read_text(encoding="utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "the scripts")
    return repo


def test_the_forecast_runs_the_commits_own_preview(engine):
    merge(engine, "schema-c", 9, CONFIG_SCHEMA, MOVED)
    (engine / "packages/brain/installer/release_check.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    fc = nextrelease.forecast([engine.parent / "elsewhere", engine], ref=main_branch(engine))
    assert "error" not in fc, fc   # the broken working-tree copy played no part
    assert fc["kind"] == "minor" and fc["repo"] == str(engine) and fc["tipped_by"]["pr"] == 9


def test_the_default_ref_is_the_remotes_default_branch_else_head(engine, tmp_path):
    assert nextrelease.default_ref(engine) == "HEAD"
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(engine), str(clone)], check=True, capture_output=True)
    assert nextrelease.default_ref(clone) == f"origin/{main_branch(engine)}"


def test_no_engine_checkout_no_forecast(tmp_path):
    assert nextrelease.forecast([tmp_path]) is None
    assert nextrelease.lines(None, "0.2.6") == []


def test_a_ref_without_the_scripts_is_said(engine):
    fc = nextrelease.forecast([engine], ref="v0.2.5")   # the tag predates changelog.py in this repo
    assert "has no changelog.py" in fc["error"]
    assert nextrelease.lines(fc, "9.9.9") == [f"release forecast unknown: {fc['error']}"]


def test_a_preview_that_predates_the_forecast_is_said(engine, monkeypatch):
    def old(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 2, "", "release_check.py: error: unrecognized arguments: --ref x")
    monkeypatch.setattr(nextrelease.subprocess, "run", old)
    monkeypatch.setattr(nextrelease, "_git", lambda repo, *a, **k: "text")
    assert "predates the forecast" in nextrelease.forecast([engine], ref="x")["error"]


@pytest.mark.parametrize("outcome", ["timeout", "garbage", "no-kind"])
def test_a_preview_that_hangs_or_prints_garbage_is_unknown(engine, monkeypatch, outcome):
    def run(cmd, **kw):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        return subprocess.CompletedProcess(cmd, 0, "not json" if outcome == "garbage" else '{"kind": "major"}', "")
    monkeypatch.setattr(nextrelease.subprocess, "run", run)
    monkeypatch.setattr(nextrelease, "_git", lambda repo, *a, **k: "text")
    fc = nextrelease.forecast([engine], ref="x", timeout=0.1)
    assert fc["error"] and nextrelease.lines(fc, "0.2.6")[0].startswith("release forecast unknown:")


MINOR = {"kind": "minor", "patch": "0.2.6", "minor": "0.3.0", "ref": "origin/main", "sha": "abc1234",
         "tipped_by": {"sha": "def5678", "subject": "Merge pull request #8 from a/b", "pr": 8},
         "reasons": [{"kind": "schema", "path": "s.json"}, {"kind": "upgrade", "path": "f.md", "step": "**Move**"}]}


def test_the_lines_of_a_minor_name_the_rename_the_pr_and_the_reasons():
    out = nextrelease.lines(MINOR, "0.2.6")
    assert out[0].startswith("release forecast: wave 0.2.6 ships as a minor, 0.3.0, not the patch 0.2.6")
    assert "rename it before the version PR" in out[0] and "origin/main at abc1234" in out[0]
    assert out[1] == "  first tipped by def5678 (PR #8): Merge pull request #8 from a/b"
    assert out[2:] == ["  a registered schema moved: s.json",
                       "  an Upgrade step beyond the standard ones: f.md: **Move**"]
    planned = nextrelease.lines(MINOR, "0.3.0")[0]
    assert planned.endswith("as planned (release_check --preview of origin/main at abc1234)")


def test_the_lines_of_a_patch_and_of_a_later_wave():
    patch = MINOR | {"kind": "patch", "tipped_by": None, "reasons": []}
    assert nextrelease.lines(patch, "0.2.6")[0].startswith("release forecast: wave 0.2.6 ships as the patch 0.2.6")
    assert "planned as the minor" in nextrelease.lines(patch, "0.3.0")[0]
    assert nextrelease.lines(patch, "0.2.7") == [] and nextrelease.lines(MINOR, "0.4.0") == []
