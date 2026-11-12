"""installer/freeze_store.py, the old-store fixture's freeze (wi-brain-old-store-fixture): its seams, fast; the install
of a tag and the freeze itself run by hand at the version PR (docs/release.md, « The fixture freeze »)."""

import importlib.util
import json
from pathlib import Path

import pytest

from brain import cli

SCRIPT = Path(__file__).resolve().parents[1] / "installer" / "freeze_store.py"


@pytest.fixture(scope="module")
def fz():
    spec = importlib.util.spec_from_file_location("freeze_store", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake(fz, monkeypatch, tmp_path, failed: str = "", path_in: str = ""):
    """The install and the steps faked: each step ok but ``failed``; ``path_in`` a file that names the work folder.
    No machine term (this machine's names are not the test's to see)."""
    scripts = tmp_path / "venv" / "Scripts"
    monkeypatch.setattr(fz, "machine", lambda: {})
    monkeypatch.setattr(fz.st, "install", lambda work, ref, source, pre_tag: (scripts, [
        {"step": "install", "cmd": f"pip install {ref}", "rc": 0, "ok": True, "out": ""}]))

    def run_steps(steps, env, root):
        (root / "config.json").write_text('{"v": 1}\n', encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        if path_in:
            (root / path_in).write_text(f"root: {root.parent}\n", encoding="utf-8")
        return [{"step": s[0], "cmd": " ".join(s[1]), "rc": 2 if s[0] == failed else 0, "ok": s[0] != failed,
                 "out": "brain 0.3.1\n" if s[0] == "version" else "an error\n"} for s in steps]
    monkeypatch.setattr(fz.st, "run_steps", run_steps)


def test_a_store_is_frozen_with_what_ran(fz, monkeypatch, tmp_path, capsys):
    fake(fz, monkeypatch, tmp_path, failed="lesson")
    out = tmp_path / "stores"
    assert fz.main(["v0.3.1", "--out", str(out), "--work", str(tmp_path / "work")]) == 0
    info = json.loads((out / "v0.3.1" / "freeze.json").read_text(encoding="utf-8"))
    assert info["tag"] == "v0.3.1" and info["engine"] == "0.3.1" and info["source"] == "tag"
    steps = {s["step"]: s["ok"] for s in info["steps"]}
    assert steps["lesson"] is False and steps["check"] is True     # a command the engine lacks: recorded, skipped
    assert (out / "v0.3.1" / "brain" / "config.json").is_file()
    assert not (out / "v0.3.1" / "brain" / ".git").exists()         # the repository is the test's to make
    assert "skip lesson" in capsys.readouterr().out


@pytest.mark.parametrize("step", ["init apply", "first commit", "check"])
def test_a_store_without_what_it_needs_is_not_frozen(fz, monkeypatch, tmp_path, capsys, step):
    fake(fz, monkeypatch, tmp_path, failed=step)
    out = tmp_path / "stores"
    assert fz.main(["v0.3.1", "--out", str(out), "--work", str(tmp_path / "work")]) == 1
    assert not out.exists() and f"freeze: {step} failed" in capsys.readouterr().err


def test_a_store_naming_the_work_folder_is_not_frozen(fz, monkeypatch, tmp_path, capsys):
    fake(fz, monkeypatch, tmp_path, path_in="projects.yaml")
    out = tmp_path / "stores"
    assert fz.main(["v0.3.1", "--out", str(out), "--work", str(tmp_path / "work")]) == 1
    assert not out.exists() and "name the work folder" in capsys.readouterr().err


def test_the_machines_names_are_replaced_by_invented_ones(fz, monkeypatch, tmp_path):
    """brain init writes this machine's host and user into public.deny: the engine is public, so the fixture holds
    invented names in their place (as test_init's), its other bytes kept."""
    fake(fz, monkeypatch, tmp_path)
    monkeypatch.setattr(fz, "machine", lambda: {"BOXA12": "host-a", "someone7": "ada-l"})
    real = fz.st.run_steps

    def with_names(steps, env, root):
        out = real(steps, env, root)
        (root / "config.json").write_bytes(b'{"deny": {"hosts": ["BOXA12"], "users": ["SOMEONE7"]},\r\n'
                                           b' "keep": "BOXA12-ish someone7x"}\n')
        return out
    monkeypatch.setattr(fz.st, "run_steps", with_names)
    out = tmp_path / "stores"
    assert fz.main(["v0.3.1", "--out", str(out), "--work", str(tmp_path / "work")]) == 0
    assert (out / "v0.3.1" / "brain" / "config.json").read_bytes() == (
        b'{"deny": {"hosts": ["host-a"], "users": ["ada-l"]},\r\n "keep": "BOXA12-ish someone7x"}\n')
    assert json.loads((out / "v0.3.1" / "freeze.json").read_text(encoding="utf-8"))["neutralized"] == ["config.json"]


def test_a_store_still_naming_the_machine_is_found(fz, tmp_path):
    (tmp_path / "a.md").write_text("on host boxa12 today\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("on host-a today\n", encoding="utf-8")
    assert fz.named(tmp_path, tmp_path / "elsewhere", {"BOXA12": "host-a"}) == ["a.md"]
    assert fz.named(tmp_path, tmp_path / "elsewhere") == []
    terms = fz.machine()
    assert set(terms.values()) <= {"host-a", "ada-l"} and all(len(t) >= 3 for t in terms)


def test_a_frozen_store_is_never_replaced_without_force(fz, monkeypatch, tmp_path, capsys):
    out = tmp_path / "stores"
    (out / "v0.3.1").mkdir(parents=True)
    monkeypatch.setattr(fz.st, "install", lambda *a: pytest.fail("installed over a frozen store"))
    assert fz.main(["v0.3.1", "--out", str(out)]) == 1
    assert "never edited" in capsys.readouterr().err
    fake(fz, monkeypatch, tmp_path)
    assert fz.main(["v0.3.1", "--out", str(out), "--work", str(tmp_path / "work"), "--force"]) == 0


def test_every_step_is_a_command_this_engine_still_takes(fz):
    """The next freeze runs the same steps on the next tag: each brain command parses under this checkout's CLI."""
    parser = cli.build_parser()
    brain = "brain"
    for name, cmd, *_ in fz.steps(brain):
        if cmd[0] == brain and name != "version":
            parser.parse_args(cmd[1:])   # SystemExit on a command or an option the engine dropped


def test_the_frozen_stores_were_written_by_their_tags():
    stores = Path(__file__).parent / "fixtures" / "stores"
    for info in stores.glob("v*/freeze.json"):
        data = json.loads(info.read_text(encoding="utf-8"))
        assert data["tag"] == info.parent.name and data["source"] == "tag", info
