"""wi-brain-release-pin: brain release pin vX.Y.Z, the planning brain's pin PR as a plan, then --write in a pin
branch: engine.pin, the engine stores its classes: block misses, the shim's PIN line, the Upgrade steps that name
config.json, the open PRs that waited for the tag (docs/release.md, « 4. The pin and the machines »)."""

import json
import subprocess
from pathlib import Path

import pytest

from brain import cli, release, update

CHANGELOG = """\
# Changelog

## 0.5.1 — 2026-11-20 — Later

### Upgrade

1. **Install the engine**, in your own terminal: `brain update`, then `y`. It writes `engine.pin` and commits
   `config.json`.
2. **Declare the new store** in `config.json` `classes.stores` (brain classes --suggest).
3. **Restart the sessions.**

### Added

- 1. not a step: `config.json` named in Added.

## 0.5.0 — 2026-11-12 — Before

### Upgrade

1. **Old step** naming `config.json`, already done at the pin.
"""
CONFIG = {"v": 1, "engine": {"repo": "owner/engine", "pin": "v0.5.0", "installer": "install.ps1"},
          "adapters": {"claude": {"plugin": "core"}},
          "classes": {"stores": {"repo": {"class": "private", "paths": ["**"]}}}}
SHIM = 'import os\r\n\r\nPIN = "v0.5.0"         # config.json engine.pin\r\nENGINE = "owner/engine"\r\n'


@pytest.fixture
def brain(tmp_path):
    root = tmp_path / "planning"
    (root / "plugins" / "core" / "brain").mkdir(parents=True)
    text = json.dumps(CONFIG, indent=2) + "\n"
    (root / "config.json").write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))   # BOM, CRLF
    (root / "plugins" / "core" / "brain" / "__init__.py").write_bytes(SHIM.encode("utf-8"))
    return root


@pytest.fixture(autouse=True)
def chlog(monkeypatch):
    """The tag's CHANGELOG read through the opener a test gives (conftest stubs update.changelog: no network)."""
    def read(repo, tag, since, opener=None):
        try:
            with opener(update.CHANGELOG.format(repo=repo, tag=tag), timeout=1) as r:
                return update.sections(r.read().decode("utf-8"), since, tag[1:])
        except OSError:   # the test's offline opener: update.changelog says None for an unreadable CHANGELOG
            return None
    monkeypatch.setattr(update, "changelog", read)


def _opener(url, timeout):
    assert url == "https://raw.githubusercontent.com/owner/engine/v0.5.1/packages/brain/CHANGELOG.md"

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return CHANGELOG.encode("utf-8")
    return R()


def _gh(prs):
    def run(argv, **kw):
        assert argv[:3] == ["gh", "pr", "list"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(prs), "")
    return run


PRS = [{"number": 9, "title": "Wave 0.5.1, lot a", "body": ""}, {"number": 8, "title": "x", "body": "for v0.5.1"},
       {"number": 7, "title": "wave-0.5.10 lot", "body": "0.5.1.2"}, {"number": 6, "title": "y", "body": None}]


def test_the_plan_names_the_pin_the_stores_the_shim_the_upgrade_steps_and_the_waiting_prs(brain):
    p = release.pin_plan(brain, "v0.5.1", opener=_opener, runner=_gh(PRS))
    assert (p.prev, p.tag) == ("v0.5.0", "v0.5.1") and "ledger" in p.stores and "repo" not in p.stores
    assert p.shim is not None and 'PIN = "v0.5.1"' in p.shim_text and p.shim_text.count("\r\n") == 4
    assert p.upgrade == ["0.5.1 step 2: Declare the new store"]   # the standard Install step left out
    assert [w["number"] for w in p.waiting] == [9, 8]   # 0.5.10 and 0.5.1.2 are other versions
    lines = release.pin_lines(p)
    assert lines[0].endswith("v0.5.0 -> v0.5.1") and lines[1].startswith("edit     stores: classes.stores + ")
    assert "edit     shim: plugins/core/brain/__init__.py PIN v0.5.0 -> v0.5.1" in lines
    assert "  #9 Wave 0.5.1, lot a" in lines
    assert "upgrade  1 step(s) name config.json, to read (what this command writes aside, by hand):" in lines
    assert (brain / "config.json").read_bytes().startswith(b"\xef\xbb\xbf")   # a plan writes nothing


def test_write_keeps_the_files_format_and_a_second_run_writes_nothing(brain):
    p = release.pin_plan(brain, "v0.5.1", opener=_opener, runner=_gh([]))
    done = release.pin_write(p)
    raw = (brain / "config.json").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b'\r\n  "engine": {' in raw
    data = json.loads(raw.decode("utf-8-sig"))
    assert data["engine"]["pin"] == "v0.5.1" and list(data) == list(CONFIG)   # its keys in their order
    stores = data["classes"]["stores"]
    assert stores["repo"] == CONFIG["classes"]["stores"]["repo"] and "ledger" in stores
    assert (brain / "plugins" / "core" / "brain" / "__init__.py").read_bytes() == SHIM.replace(
        'PIN = "v0.5.0"', 'PIN = "v0.5.1"').encode("utf-8")
    assert done[0] == "written  shim: plugins/core/brain/__init__.py"
    assert done[1].startswith("written  config.json: engine.pin v0.5.1, classes.stores + ")
    again = release.pin_plan(brain, "v0.5.1", opener=_opener, runner=_gh([]))
    assert not again.writes() and again.stores == {} and again.shim_line.startswith("same     shim")


def test_a_config_moved_since_the_plan_is_not_written(brain):
    p = release.pin_plan(brain, "v0.5.1", opener=_opener, runner=_gh([]))
    f = brain / "config.json"
    f.write_text(f.read_text(encoding="utf-8-sig").replace("v0.5.0", "v0.4.9"), encoding="utf-8")
    before = f.read_bytes()
    with pytest.raises(ValueError, match="engine.pin is no longer v0.5.0"):
        release.pin_write(p)
    assert f.read_bytes() == before


@pytest.mark.parametrize("tag, error", [("0.5.1", "a release tag vX.Y.Z"), ("v0.4.9", "before the pin v0.5.0")])
def test_a_bad_tag_is_refused(brain, tag, error):
    with pytest.raises(release.ReleaseError, match=error):
        release.pin_plan(brain, tag, opener=_opener, runner=_gh([]))


def test_no_classes_no_shim_an_unreadable_changelog_and_no_gh_are_said(brain):
    data = dict(CONFIG)
    data.pop("classes")
    data["adapters"] = {}
    (brain / "config.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def no_gh(argv, **kw):
        raise OSError("gh: not found")
    p = release.pin_plan(brain, "v0.5.1", opener=lambda url, timeout: (_ for _ in ()).throw(OSError("offline")),
                         runner=no_gh)
    assert p.stores == {} and "declares no classes" in p.stores_note and p.shim is None
    assert "could not be read" in p.upgrade_note and "gh could not run" in p.waiting_note
    assert p.writes()   # the pin itself still moves


def test_the_same_tag_reads_no_changelog_and_moves_no_pin(brain):
    p = release.pin_plan(brain, "v0.5.0", opener=lambda *a: pytest.fail("read"), runner=_gh([]))
    assert p.upgrade == [] and release.pin_lines(p)[0] == "same     pin: config.json engine.pin is v0.5.0"


@pytest.mark.parametrize("head, default, error", [
    ("HEAD", "origin/main", "on no branch"), ("main", "", "on its default branch main"),
    ("trunk", "origin/trunk", "on its default branch trunk"), ("chore/pin-v0.5.1", "origin/main", "")])
def test_the_pin_is_written_in_a_branch_never_the_default_one(tmp_path, head, default, error):
    def run(argv, **kw):
        out = head if "--abbrev-ref" in argv else default
        return subprocess.CompletedProcess(argv, 0 if out else 1, out + "\n", "")
    if error:
        with pytest.raises(release.ReleaseError, match=error):
            release.pin_branch(tmp_path, run)
    else:
        assert release.pin_branch(tmp_path, run) == head


def test_config_steps_reads_numbered_steps_with_their_continuation_lines():
    lines = ["## 1.0.0 — d — t", "### Upgrade", "1. **A** first line", "   then `config.json`.", "2. Plain step",
             "   naming config.json too, untitled", "", "Nothing to run for the rest: config.json", "### Fixes",
             "1. **B** config.json"]
    assert release.config_steps(lines) == ["1.0.0 step 1: A", "1.0.0 step 2: Plain step naming config.json too, "
                                                              "untitled"]


def test_cli_plan_json_and_write(brain, monkeypatch, capsys):
    monkeypatch.setattr(update, "changelog", lambda repo, tag, since, opener=None: CHANGELOG.splitlines())
    monkeypatch.setattr(release, "waiting_prs", lambda root, tag, runner=None: ([{"number": 9, "title": "t"}], ""))
    monkeypatch.setattr(release, "pin_branch", lambda root, runner=None: "chore/pin")
    assert cli.main(["release", "pin", "v0.5.1", "--planning", str(brain), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pin"] == "v0.5.0" and data["waiting"] == [{"number": 9, "title": "t"}] and "ledger" in data["stores"]
    assert "v0.5.0" in (brain / "config.json").read_text(encoding="utf-8-sig")   # --json writes nothing
    assert cli.main(["release", "pin", "v0.5.1", "--planning", str(brain)]) == 0
    assert "plan only: --write writes config.json" in capsys.readouterr().out
    assert cli.main(["release", "pin", "v0.5.1", "--planning", str(brain), "--write"]) == 0
    out = capsys.readouterr().out
    assert "written  shim: plugins/core/brain/__init__.py" in out and "branch   chore/pin: commit them" in out
    assert cli.main(["release", "pin", "v0.4.0", "--planning", str(brain)]) == 2
    assert "before the pin v0.5.1" in capsys.readouterr().err
    assert cli.main(["release", "pin", "v0.5.1", "--planning", str(brain / "nope")]) == 2


def test_a_failed_config_write_after_the_shim_is_said_and_a_rerun_resumes(brain, monkeypatch):
    p = release.pin_plan(brain, "v0.5.1", opener=_opener, runner=_gh([]))
    said = []

    def locked(file, change):
        raise PermissionError("config.json is locked")
    with monkeypatch.context() as m:
        m.setattr(update, "rewrite_json", locked)
        with pytest.raises(PermissionError):
            release.pin_write(p, say=said.append)
    assert said == ["written  shim: plugins/core/brain/__init__.py"]   # told before the failure
    again = release.pin_plan(brain, "v0.5.1", opener=_opener, runner=_gh([]))
    assert again.shim is None and again.prev == "v0.5.0" and again.writes()   # only config.json is left
    assert release.pin_write(again)[0].startswith("written  config.json: engine.pin v0.5.1")


def test_a_moved_pin_is_refused_before_the_shim_is_written(brain):
    p = release.pin_plan(brain, "v0.5.1", opener=_opener, runner=_gh([]))
    f = brain / "config.json"
    f.write_text(f.read_text(encoding="utf-8-sig").replace("v0.5.0", "v0.4.9"), encoding="utf-8")
    shim = (brain / "plugins" / "core" / "brain" / "__init__.py").read_bytes()
    with pytest.raises(ValueError):
        release.pin_write(p)
    assert (brain / "plugins" / "core" / "brain" / "__init__.py").read_bytes() == shim


def test_a_classes_block_with_errors_adds_no_store(brain):
    data = json.loads((brain / "config.json").read_text(encoding="utf-8-sig"))
    data["classes"] = {"stores": ["not", "a", "mapping"]}
    (brain / "config.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    p = release.pin_plan(brain, "v0.5.1", opener=_opener, runner=_gh([]))
    assert p.stores == {} and "has errors" in p.stores_note


def test_the_default_branch_is_asked_of_the_remote_when_origin_head_is_not_set(tmp_path):
    def run(argv, **kw):
        if "--abbrev-ref" in argv:
            return subprocess.CompletedProcess(argv, 0, "trunk\n", "")
        if "symbolic-ref" in argv:
            return subprocess.CompletedProcess(argv, 128, "", "not a symbolic ref")
        return subprocess.CompletedProcess(argv, 0, "ref: refs/heads/trunk\tHEAD\nabc\tHEAD\n", "")
    with pytest.raises(release.ReleaseError, match="default branch trunk"):
        release.pin_branch(tmp_path, run)


def test_the_planning_brain_is_the_checkout_holding_the_current_folder(tmp_path, monkeypatch):
    import argparse
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: elsewhere", encoding="utf-8")   # a worktree's .git is a file
    (wt / "config.json").write_text("{}", encoding="utf-8")
    (wt / "notes").mkdir()
    args = argparse.Namespace(planning=None, root=None)
    assert release.planning_root(args, cwd=wt / "notes") == wt.resolve()
    args.planning = str(tmp_path)
    assert release.planning_root(args, cwd=wt) == tmp_path.resolve()


def test_write_json_writes_nothing(brain, monkeypatch, capsys):
    monkeypatch.setattr(release, "waiting_prs", lambda root, tag, runner=None: ([], ""))
    monkeypatch.setattr(update, "changelog", lambda repo, tag, since, opener=None: [])
    before = (brain / "config.json").read_bytes()
    assert cli.main(["release", "pin", "v0.5.1", "--planning", str(brain), "--write", "--json"]) == 0
    assert (brain / "config.json").read_bytes() == before


def test_a_wave_id_names_the_version():
    run = _gh([{"number": 1, "title": "x", "body": "closes wave-0.5.1"}])
    assert [w["number"] for w in release.waiting_prs(Path("."), "v0.5.1", run)[0]] == [1]
