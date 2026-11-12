"""Blue-green engine slots (wi-brain-update-blue-green, brain.slots): brain update installs a version beside the old in
<BRAIN_HOME>/venvs/vX.Y.Z, runs the health gate there, switches <BRAIN_HOME>/venv (a link) and the launcher, and
switches back when the watchdog fails. The links are real (a junction on Windows, a symlink elsewhere), in each test's
own BRAIN_HOME; the venvs and pip are a fake runner's."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from brain import slots, update

NOW = 1_793_700_000.0
TAGS = ["v0.2.1", "v0.2.2", "v0.2.3"]


def _venv(folder: Path, launcher: bytes, base: Path | None = None) -> Path:
    """A venv's layout: its interpreter, its launcher, Textual (the tui extra), and pyvenv.cfg naming ``base``."""
    scripts = folder / ("Scripts" if slots.WINDOWS else "bin")
    scripts.mkdir(parents=True)
    (scripts / ("python.exe" if slots.WINDOWS else "python")).write_bytes(b"python")
    (scripts / ("brain.exe" if slots.WINDOWS else "brain")).write_bytes(launcher)
    site = folder / ("Lib/site-packages" if slots.WINDOWS else "lib/python3.12/site-packages")
    (site / "textual-1.0.0.dist-info").mkdir(parents=True)
    (site / "pip").mkdir()
    (site / "pip" / "__init__.py").write_text("", encoding="utf-8")
    if base:
        (folder / "pyvenv.cfg").write_text(f"home = {base.parent}\nexecutable = {base}\nversion = 3.12.0\n",
                                           encoding="utf-8")
    return folder


@pytest.fixture
def machine(brain_home, tmp_path, monkeypatch):
    """The machine as the installer leaves it: <BRAIN_HOME>/venv a real folder (brain 0.2.2), its launcher copied
    into <BRAIN_HOME>/bin, made from a base interpreter; Ada's brain (a config.json) the smoke's root."""
    brain = tmp_path / "ada-brain"
    brain.mkdir()
    (brain / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / "config.json"))
    base = tmp_path / "python312" / ("python.exe" if slots.WINDOWS else "python3")
    base.parent.mkdir()
    base.write_bytes(b"base")
    _venv(brain_home / "venv", b"launcher 0.2.2", base)
    if slots.WINDOWS:
        (brain_home / "bin").mkdir()
        (brain_home / "bin" / "brain.exe").write_bytes(b"launcher 0.2.2")
    return brain_home


def _runner(ran: list, *, version="0.2.3", smoke_fails="", watch_version=None):
    """The fake world: ``-m venv`` lays a slot out, pip succeeds, the new engine says ``version``; ``smoke_fails``
    names a smoke step that fails (doctor or guards); ``watch_version`` is what brain --version says through
    <BRAIN_HOME>/venv after the switch."""
    def run(cmd, **kw):
        ran.append(cmd)
        args = [str(c) for c in cmd]
        if args[1:3] == ["-m", "venv"]:
            _venv(Path(args[3]), b"launcher 0.2.3")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if "--version" in args:
            through_link = Path(args[0]).parent.parent.name == "venv" or Path(args[0]).name.startswith("brain")
            said = watch_version if (through_link and watch_version) else version
            return subprocess.CompletedProcess(cmd, 0, f"brain {said}\n", "")
        if "doctor" in args:
            return subprocess.CompletedProcess(cmd, 1 if smoke_fails == "doctor" else 0, "{}", "")
        if "-c" in args:
            return subprocess.CompletedProcess(cmd, 1 if smoke_fails == "guards" else 0, "[]", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


def _plan():
    info = update.check(fetch=lambda repo: list(TAGS), now=NOW, installed="0.2.2")
    return update.plan(info, read_changelog=lambda *a: [], verify=lambda *a: {
        "status": "verified", "tag": "v0.2.3", "signer": "ada", "commit": "c" * 40, "why": "", "source": ""})


# --- the link -------------------------------------------------------------------------------------------------------

def test_the_first_switch_moves_the_real_venv_into_its_slot(machine):
    new = _venv(slots.slot("v0.2.3"), b"launcher 0.2.3")
    before = slots.switch(new, aside_for="v0.2.2")
    assert before == slots.slot("v0.2.2") and (before / "pyvenv.cfg").is_file()   # moved whole
    assert slots.is_link(slots.active_path()) and Path(os.path.realpath(slots.active_path())) == Path(
        os.path.realpath(new))
    assert slots.active() is not None and (slots.active_path() / "pyvenv.cfg").is_file() is False   # the new one's
    again = slots.switch(before)   # and back: the same rename
    assert Path(os.path.realpath(again)) == Path(os.path.realpath(new))
    assert (slots.active_path() / "pyvenv.cfg").is_file() and (new / ("Scripts" if slots.WINDOWS else "bin")).is_dir()
    assert not [p for p in machine.iterdir() if p.name.endswith(".tmp")]   # no link left aside


def test_a_switch_keeps_the_targets_files_and_works_with_a_file_open_inside(machine):
    a = _venv(slots.slot("v0.2.3"), b"a")
    b = _venv(slots.slot("v0.2.4"), b"b")
    slots.switch(a, aside_for="v0.2.2")
    with open(slots.active_path() / "pyvenv-open.txt", "w", encoding="utf-8") as held:   # a running brain's handle
        held.write("x")
        slots.switch(b)
    assert (a / "pyvenv-open.txt").is_file() and Path(os.path.realpath(slots.active_path())) == Path(
        os.path.realpath(b))
    slots.remove_link(slots.active_path())   # a link removed: never its target's files
    assert b.is_dir() and any(b.iterdir())


def test_base_python_reads_pyvenv_cfg(machine, tmp_path):
    assert slots.base_python(machine / "venv") == tmp_path / "python312" / (
        "python.exe" if slots.WINDOWS else "python3")
    (machine / "venv" / "pyvenv.cfg").unlink()
    assert slots.base_python(machine / "venv") is None


# --- brain update, blue-green ---------------------------------------------------------------------------------------

def test_the_plan_installs_beside_the_old_and_says_the_gate(machine):
    p = _plan()
    assert p["slot"] == str(slots.slot("v0.2.3")) and p["base"].endswith(("python.exe", "python3"))
    text = "\n".join(update.lines(p))
    assert f"into {slots.slot('v0.2.3')}, beside brain 0.2.2" in text
    assert "check    run by v0.2.3 before any switch: brain --version, brain doctor --quick" in text
    assert "else back to 0.2.2" in text


def test_a_healthy_version_is_switched_in(machine):
    ran = []
    code, done = update.apply(_plan(), runner=_runner(ran))
    assert code == 0, done
    assert ran[0][1:3] == ["-m", "venv"] and ran[1][1:3] == ["-m", "pip"]
    assert Path(os.path.realpath(slots.active_path())) == Path(os.path.realpath(slots.slot("v0.2.3")))
    assert (slots.slot("v0.2.2") / "pyvenv.cfg").is_file()   # the old one kept, for a way back
    assert any(d.startswith("switched ") for d in done)
    if slots.WINDOWS:
        assert (machine / "bin" / "brain.exe").read_bytes() == b"launcher 0.2.2"   # left: it runs venv's Python
    smoke = [c for c in ran if "doctor" in c or "-c" in c]
    assert smoke and all(Path(c[0]) == slots.python_of(slots.slot("v0.2.3")) for c in smoke)   # run by the new one


@pytest.mark.parametrize("step", ["doctor", "guards"])
def test_a_failing_health_gate_switches_nothing(machine, step):
    code, done = update.apply(_plan(), runner=_runner([], smoke_fails=step))
    assert code == 1 and any(d.startswith("kept     brain 0.2.2: not switched") for d in done)
    assert not slots.is_link(slots.active_path()) and (machine / "venv" / "pyvenv.cfg").is_file()
    if slots.WINDOWS:
        assert (machine / "bin" / "brain.exe").read_bytes() == b"launcher 0.2.2"


def test_a_wrong_version_never_reaches_the_switch(machine):
    code, done = update.apply(_plan(), runner=_runner([], version="0.2.2"))
    assert code == 1 and any("brain --version: not 0.2.3" in d for d in done)
    assert not slots.is_link(slots.active_path())


def test_the_watchdog_switches_back(machine):
    """The switch done, brain --version through <BRAIN_HOME>/venv fails: the link and the launcher go back."""
    code, done = update.apply(_plan(), runner=_runner([], watch_version="9.9.9"))
    assert code == 1
    assert any(d.startswith("watch    venv") for d in done) and any(d.startswith("back     ") for d in done)
    assert Path(os.path.realpath(slots.active_path())) == Path(os.path.realpath(slots.slot("v0.2.2")))
    if slots.WINDOWS:
        assert (machine / "bin" / "brain.exe").read_bytes() == b"launcher 0.2.2"


def test_a_venv_without_a_base_interpreter_installs_in_place(machine):
    (machine / "venv" / "pyvenv.cfg").unlink()
    p = _plan()
    assert p["slot"] is None and "in place: its pyvenv.cfg names no base interpreter" in "\n".join(update.lines(p))
    ran = []
    code, _ = update.apply(p, runner=_runner(ran))
    assert code == 0 and ran[0][1:3] == ["-m", "pip"] and not slots.is_link(slots.active_path())


def test_the_old_slots_are_pruned_never_the_active_nor_the_previous(machine):
    for v in ("v0.1.0", "v0.1.1", "v0.2.0", "v0.2.1"):
        _venv(slots.slot(v), v.encode())
    slots.switch(_venv(slots.slot("v0.2.3"), b"x"), aside_for="v0.2.2")
    (slots.slots_dir() / "notes.txt").write_text("not a slot", encoding="utf-8")
    said = slots.prune([slots.slot("v0.1.0")])
    left = sorted(p.name for p in slots.slots_dir().iterdir())
    assert left == ["notes.txt", "v0.1.0", "v0.2.1", "v0.2.2", "v0.2.3"]   # 3 newest, plus the previous one named
    assert len(said) == 2 and all(s.startswith("pruned") for s in said)


def test_the_smoke_runs_doctor_in_the_brains_root_and_the_real_guards(machine, tmp_path):
    """The guards' step for real (this test's Python imports brain): git status passes, so it exits 0; doctor gets
    --root, and without a root it is skipped (brain doctor needs one)."""
    import sys

    real = subprocess.run([sys.executable, "-I", "-c", slots.SMOKE_GUARD, str(tmp_path)], capture_output=True,
                          text=True, timeout=120, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert real.returncode == 0 and real.stdout.strip() == "[]", real.stdout + real.stderr
    ran = []
    assert slots.smoke(Path("py"), "0.2.3", tmp_path / "ada-brain", _runner(ran)) == []
    assert ["py", "-I", "-m", "brain", "--root", str(tmp_path / "ada-brain"), "doctor", "--quick", "--json"] in [
        [str(c) for c in cmd] for cmd in ran]
    ran.clear()
    assert slots.smoke(Path("py"), "0.2.3", None, _runner(ran)) == [] and not any("doctor" in c for c in ran)


def test_a_half_made_slot_is_made_anew_and_the_active_one_never_installed_over(machine, tmp_path):
    """A slot an interrupted try left (its python but no pip) is removed and made again; a slot that is the active
    one is refused (review of wi-brain-update-blue-green)."""
    half = slot_dir = slots.slot("v0.2.3")
    (half / ("Scripts" if slots.WINDOWS else "bin")).mkdir(parents=True)
    slots.python_of(half).write_bytes(b"python")   # no pip: half made
    ran = []
    assert slots.create(slot_dir, tmp_path / "base", "brain", _runner(ran)) == []
    assert ran[0][1:3] == ["-m", "venv"] and slots._has_pip(slot_dir)
    slots.switch(slot_dir, aside_for="v0.2.2")
    said = slots.create(slot_dir, tmp_path / "base", "brain", _runner([]))
    assert said and "is the active one" in said[0]


def test_stale_links_of_an_interrupted_switch_are_cleared_and_a_failed_cleanup_is_no_failure(machine, monkeypatch):
    a = _venv(slots.slot("v0.2.3"), b"a")
    stale = machine / "venv.switch-99999.tmp"
    slots.make_link(a, stale)
    slots.switch(a, aside_for="v0.2.2")
    assert not slots.is_link(stale) and a.is_dir()   # the link cleared, its target kept
    b = _venv(slots.slot("v0.2.4"), b"b")
    real_remove = slots.remove_link

    def remove(link):
        if ".prev-" in link.name:
            raise OSError("in use")
        real_remove(link)

    monkeypatch.setattr(slots, "remove_link", remove)
    assert Path(os.path.realpath(slots.switch(b))) == Path(os.path.realpath(a))   # done, not an error
    assert Path(os.path.realpath(slots.active_path())) == Path(os.path.realpath(b))


def test_base_python_takes_the_same_minor_version_first(tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "WINDOWS", False)
    bindir = tmp_path / "usr-bin"
    bindir.mkdir()
    for name in ("python3", "python3.10"):
        (bindir / name).write_bytes(b"")
    venv = tmp_path / "v"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text(f"home = {bindir}\nversion = 3.10.12\n", encoding="utf-8")
    assert slots.base_python(venv) == bindir / "python3.10"


def test_brain_python_instead_of_the_venv_installs_in_place(machine, monkeypatch, tmp_path):
    """$BRAIN_PYTHON stands for a missing <BRAIN_HOME>/venv: no slot, no link made from nothing."""
    other = _venv(tmp_path / "elsewhere", b"x", tmp_path / "python312" / ("python.exe" if slots.WINDOWS else
                                                                           "python3"))
    import shutil

    shutil.rmtree(machine / "venv")
    monkeypatch.setenv("BRAIN_PYTHON", str(slots.python_of(other)))
    p = _plan()
    assert p["python"] == str(slots.python_of(other)) and p["slot"] is None


@pytest.mark.skipif(not slots.WINDOWS, reason="a file held open blocks a rename on Windows only")
def test_a_slot_a_process_holds_is_kept_whole(machine):
    for v in ("v0.1.0", "v0.2.0", "v0.2.1"):
        _venv(slots.slot(v), v.encode())
    slots.switch(_venv(slots.slot("v0.2.3"), b"x"), aside_for="v0.2.2")
    with open(slots.slot("v0.1.0") / "held.txt", "w", encoding="utf-8"):
        said = slots.prune([])
    assert any(s.startswith("kept     ") and "v0.1.0" in s for s in said)
    assert (slots.slot("v0.1.0") / "pyvenv-held").exists() is False and (slots.slot("v0.1.0") / "held.txt").is_file()
    assert any(s.startswith("pruned") and "v0.2.0" in s for s in said)


def test_the_venvs_store_is_declared():
    from brain import classes

    assert classes.ENGINE_STORES["venvs"].path == "$BRAIN_HOME/venvs"
    assert json.dumps(slots.SLOTS) == '"venvs"'
