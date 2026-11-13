"""wi-brain-release-prepare: brain release prepare X.Y.Z --theme T, the version PR's mechanical part as a plan, then
--write in order, stopping at the first step that fails (docs/release.md, « The version PR »)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from brain import cli, release

ENGINE = Path(__file__).resolve().parents[3]   # this checkout


@pytest.fixture
def repo(tmp_path):
    """A copy of this checkout's version files, at their version, with a line of history that must stay."""
    r = tmp_path / "engine"
    for rel in release.VERSION_FILES:
        src = ENGINE / rel
        if src.is_file():
            (r / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, r / rel)
    prev = release.current_version(r)
    with (r / "docs" / "pilot.md").open("a", encoding="utf-8", newline="") as fh:
        fh.write(f"\r\nFixes come as new tags ({prev} brought the history line, then later ones)\r\n")
    return r


class Runs:
    def __init__(self, fail: str = ""):
        self.calls, self.fail = [], fail

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        bad = self.fail and any(self.fail in str(a) for a in argv)
        return subprocess.CompletedProcess(argv, 1 if bad else 0, "out", "boom" if bad else "")


def _next(v: str) -> str:
    x, y, z = v.split(".")
    return f"{x}.{y}.{int(z) + 1}"


def test_the_plan_names_each_step_in_order_and_writes_nothing(repo):
    before = {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    prev = release.current_version(repo)
    got, steps = release.plan(repo, _next(prev), "a theme", planning=repo.parent / "planning", store="S")
    assert got == prev and [s.name for s in steps] == ["versions", "freeze", "changelog", "features", "reference",
                                                       "check"]
    assert steps[0].line.startswith(f"edit     versions {prev} -> {_next(prev)}: packages/brain/src/brain/__init__.py")
    assert steps[1].argv[-1] == f"v{prev}" and steps[-1].argv[-2:] == ["--store", "S"]
    assert {p: p.read_bytes() for p in repo.rglob("*") if p.is_file()} == before


def test_write_moves_the_version_lines_only_and_keeps_line_endings_and_history(repo):
    prev = release.current_version(repo)
    new = _next(prev)
    _, steps = release.plan(repo, new, "t", freeze=False)
    runs = Runs()
    rows = release.apply(repo, steps, runner=runs)
    assert [r["outcome"] for r in rows][:3] == ["done", "skip", "done"]
    assert release.current_version(repo) == new
    pilot = (repo / "docs" / "pilot.md").read_bytes().decode("utf-8")
    assert f"({prev} brought the history line" in pilot and f"blob/v{new}" in pilot and f"blob/v{prev}" not in pilot
    assert "\r\n" in pilot
    for rel in ("packages/brain/pyproject.toml", "README.md", "docs/install.md",
                "packages/brain/installer/stranger_test.py"):
        text = (repo / rel).read_text(encoding="utf-8")
        assert f"v{prev}" not in text and f"v{new}" in text, rel
    assert f"brain_version={new}" in (repo / "packages/brain/src/brain/adapters/claude/hooks/common.sh").read_text(
        encoding="utf-8")


def test_a_second_run_after_a_partial_write_resumes_from_the_last_tag(repo):
    """Review of wi-brain-release-prepare: the previous version is the last tag, not __version__ (moved by the first
    run), and a compiled changelog is not compiled again."""
    prev = release.current_version(repo)
    new = _next(prev)
    for argv in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m",
                                                 "x"], ["tag", f"v{prev}"]):
        subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)
    release.apply(repo, release.plan(repo, new, "t", freeze=False)[1], runner=Runs(fail="release_check"))
    log = repo / "packages" / "brain" / "CHANGELOG.md"
    log.write_text(f"# Changelog\n\n## {new} — 2026-11-13 — t\n", encoding="utf-8")   # what the compile wrote
    got, steps = release.plan(repo, new, "t")
    by = {s.name: s for s in steps}
    assert got == prev and by["versions"].state == "same" and by["changelog"].state == "same"
    assert by["freeze"].argv[-1] == f"v{prev}"   # the store the last release wrote, not the new one
    with pytest.raises(release.ReleaseError, match="not after the last release"):
        release.plan(repo, prev, "t")


def test_a_theme_reaches_the_script_as_typed():
    theme = 'Quotes "x", $HOME, 100% & <tags>'
    _, steps = release.plan(ENGINE, _next(release.current_version(ENGINE)), theme, freeze=False)
    argv = next(s.argv for s in steps if s.name == "changelog")
    assert argv[argv.index("--theme") + 1] == theme and argv[-1] == "--write"


def test_the_first_failing_step_stops_the_rest(repo):
    _, steps = release.plan(repo, _next(release.current_version(repo)), "t", planning=repo, freeze=False)
    runs = Runs(fail="changelog.py")
    rows = release.apply(repo, steps, runner=runs)
    by = {r["step"]: r["outcome"] for r in rows}
    assert by["changelog"] == "failed (exit 1)" and by["features"] == by["reference"] == by["check"] == "not run"
    assert len(runs.calls) == 1


def test_the_check_runs_then_its_preview(repo):
    _, steps = release.plan(repo, _next(release.current_version(repo)), "t", freeze=False)
    runs = Runs()
    rows = release.apply(repo, steps, runner=runs)
    assert [r["step"] for r in rows][-2:] == ["check", "preview"] and runs.calls[-1][-1] == "--preview"


def test_a_frozen_store_is_not_frozen_again_and_no_planning_brain_is_said(repo):
    prev = release.current_version(repo)
    (repo / release.STORES / f"v{prev}").mkdir(parents=True)
    _, steps = release.plan(repo, _next(prev), "t")
    by = {s.name: s for s in steps}
    assert by["freeze"].state == "same" and by["features"].state == "skip" and "reference" not in by


@pytest.mark.parametrize("version, error", [("v0.9.0", "a version X.Y.Z"), ("0.0.1", "is not after the last release"),
                                            ("1.0", "a version X.Y.Z")])
def test_a_bad_version_is_refused(repo, version, error):
    with pytest.raises(release.ReleaseError, match=error):
        release.plan(repo, version, "t")


def test_cli_plan_then_refusals(repo, capsys, tmp_path):
    nxt = _next(release.current_version(repo))
    assert cli.main(["release", "prepare", nxt, "--theme", "t", "--repo", str(repo), "--planning",
                     str(tmp_path / "none")]) == 2   # no brain there: refused before anything is written
    assert "no brain there" in capsys.readouterr().err
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "config.json").write_text("{}", encoding="utf-8")
    assert cli.main(["release", "prepare", nxt, "--theme", "t", "--repo", str(repo), "--planning",
                     str(tmp_path / "planning")]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"release  {release.current_version(repo)} -> {nxt}") and "plan only" in out
    assert "by hand  the ### Upgrade section" in out
    assert cli.main(["release", "prepare", nxt, "--theme", " ", "--repo", str(repo)]) == 2
    assert "--theme" in capsys.readouterr().err
    assert cli.main(["release", "prepare", nxt, "--theme", "t", "--repo", str(tmp_path)]) == 2
    assert "no packages/brain/src/brain/__init__.py" in capsys.readouterr().err
