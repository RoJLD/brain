"""brain release apply (wi-brain-release-apply; docs/release.md, « 4. The pin and the machines »): the install in one
owner gesture, with a fake installer and a fake engine made in the test (no real install, no network): the
installer's plan, one y, -Apply, the version against the pin, the engine clone fast-forwarded by its rule, brain
release verify, the open sessions named. Each step stops the rest when it fails and says which; the command refuses an
agent's session."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain import cli, gestures, releaseapply

needs_git = pytest.mark.skipif(not shutil.which("git"), reason="git missing")
INSTALLER = '''import os, sys
from pathlib import Path
log = Path(os.environ["FAKE_LOG"])
with log.open("a", encoding="utf-8") as fh:
    fh.write("installer " + " ".join(sys.argv[1:]) + "\\n")
if "-Apply" not in sys.argv:
    print("plan: install brain " + os.environ["FAKE_PIN"])
    sys.exit(int(os.environ.get("FAKE_PLAN_EXIT", "0")))
if os.environ.get("FAKE_APPLY_EXIT"):
    print("install failed")
    sys.exit(int(os.environ["FAKE_APPLY_EXIT"]))
Path(os.environ["FAKE_INSTALLED"]).write_text(os.environ.get("FAKE_GETS", os.environ["FAKE_PIN"]), encoding="utf-8")
print("installed")
'''
BRAIN = '''import os, sys
from pathlib import Path
with Path(os.environ["FAKE_LOG"]).open("a", encoding="utf-8") as fh:
    fh.write("brain " + " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["--version"]:
    print("brain " + Path(os.environ["FAKE_INSTALLED"]).read_text(encoding="utf-8").lstrip("v"))
    sys.exit(0)
if sys.argv[1:3] == ["release", "verify"]:
    print("verify   passed" if not os.environ.get("FAKE_VERIFY_EXIT") else "verify   FAILED")
    sys.exit(int(os.environ.get("FAKE_VERIFY_EXIT", "0")))
sys.exit(3)
'''


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A planning brain at pin v1.2.0 with a fake installer (install.py), a fake engine command, the installed
    version 1.1.0, an engine clone one commit behind its remote: SimpleNamespace(root, log, brain, clone, behind)."""
    cfgfile = tmp_path / "gitconfig"
    cfgfile.write_text("[user]\n\tname = Ada\n\temail = ada@example.com\n[commit]\n\tgpgsign = false\n"
                       "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfgfile))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in gestures.MARKER_NAMES:
        monkeypatch.delenv(var, raising=False)
    remote, clone, other = tmp_path / "engine.git", tmp_path / "clone", tmp_path / "other"
    git(tmp_path, "init", "--quiet", "--bare", str(remote))
    git(tmp_path, "clone", "--quiet", str(remote), str(other))
    (other / "a.txt").write_text("a\n", encoding="utf-8")
    git(other, "add", "a.txt")
    git(other, "commit", "--quiet", "-m", "a")
    git(other, "push", "--quiet", "origin", "main")
    git(tmp_path, "clone", "--quiet", str(remote), str(clone))
    (other / "b.txt").write_text("b\n", encoding="utf-8")
    git(other, "add", "b.txt")
    git(other, "commit", "--quiet", "-m", "b")
    git(other, "push", "--quiet", "origin", "main")
    root = tmp_path / "brain"
    root.mkdir()
    (root / "config.json").write_text(json.dumps({"v": 1, "engine": {
        "repo": "ada/engine", "pin": "v1.2.0", "installer": "install.py", "clone": str(clone)}}), encoding="utf-8")
    (root / "install.py").write_text(INSTALLER, encoding="utf-8")
    fake = tmp_path / "fake_brain.py"
    fake.write_text(BRAIN, encoding="utf-8")
    installed = tmp_path / "installed.txt"
    installed.write_text("1.1.0", encoding="utf-8")
    log = tmp_path / "log.txt"
    for k, v in {"FAKE_LOG": log, "FAKE_PIN": "v1.2.0", "FAKE_INSTALLED": installed}.items():
        monkeypatch.setenv(k, str(v))
    for k in ("FAKE_PLAN_EXIT", "FAKE_APPLY_EXIT", "FAKE_GETS", "FAKE_VERIFY_EXIT"):
        monkeypatch.delenv(k, raising=False)
    return SimpleNamespace(root=root, log=log, brain=[sys.executable, str(fake)], clone=clone,
                           behind=git(other, "rev-parse", "HEAD"))


def args(b, **kw):
    base = dict(planning=str(b.root), root=None, yes=True, tests=True, offline=False)
    return SimpleNamespace(**{**base, **kw})


def run(b, capsys, refused="", sessions=lambda: ["local_abcd1234 a coordinator (idle)"], **kw):
    code = releaseapply.main(args(b, **kw), brain=b.brain, refused=refused, sessions=sessions)
    return code, capsys.readouterr().out


def logged(b) -> list[str]:
    return b.log.read_text(encoding="utf-8").splitlines() if b.log.exists() else []


def ran(out: str, step: str) -> bool:
    return any(ln.startswith(f"{step:<9}{o}") for ln in out.splitlines()
               for o in ("done", "same", "skipped", "failed"))


@needs_git
def test_the_install_runs_in_order_and_names_the_sessions(brain, capsys):
    code, out = run(brain, capsys)
    assert code == 0, out
    assert logged(brain) == ["installer ", "installer -Apply", "brain --version",
                             f"brain release verify --planning {brain.root}"]
    assert "plan: install brain v1.2.0" in out
    assert "version  done    brain 1.2.0 = engine.pin v1.2.0" in out
    assert git(brain.clone, "rev-parse", "HEAD") == brain.behind and "clone    done" in out
    assert "restart these 1 session(s) to run v1.2.0 (nothing restarted)" in out and "local_abcd1234" in out
    assert "next     brain release status 1.2.0" in out


@needs_git
def test_an_agent_session_sees_the_plan_and_nothing_runs(brain, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    code = cli.main(["release", "apply", "--planning", str(brain.root), "--yes"])
    out = capsys.readouterr().out
    assert code == 1 and "plan: install brain v1.2.0" in out
    assert "not from a Claude Code session's shell (CLAUDECODE is set)" in out
    assert logged(brain) == ["installer "]   # the plan only: no -Apply
    assert git(brain.clone, "rev-parse", "HEAD") != brain.behind


@needs_git
def test_a_plan_that_fails_stops_before_the_y(brain, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_PLAN_EXIT", "2")
    asked = []
    code = releaseapply.main(args(brain, yes=False), brain=brain.brain, refused="", ask=asked.append)
    out = capsys.readouterr().out
    assert code == 1 and "stopped  at plan: install.py's plan failed (exit 2); nothing installed" in out
    assert not asked and logged(brain) == ["installer "]


@needs_git
@pytest.mark.parametrize("env, step, said", [
    ({"FAKE_APPLY_EXIT": "1"}, "install", "install.py -Apply failed (exit 1)"),
    ({"FAKE_GETS": "v1.1.9"}, "version", "brain 1.1.9 runs, not the pin v1.2.0: the install did not take"),
    ({"FAKE_VERIFY_EXIT": "1"}, "verify", "brain release verify failed (exit 1)"),
])
def test_a_failed_step_stops_the_rest_and_says_which(brain, capsys, monkeypatch, env, step, said):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    code, out = run(brain, capsys)
    assert code == 1 and f"{step:<9}failed  {said}" in out and f"stopped  at {step}" in out
    after = releaseapply.STEPS[releaseapply.STEPS.index(step) + 1:]
    assert not any(ran(out, s) for s in after)
    if step == "install":
        assert git(brain.clone, "rev-parse", "HEAD") != brain.behind   # the clone is not touched either


@needs_git
def test_a_clone_off_main_is_said_and_left_not_a_failure(brain, capsys):
    git(brain.clone, "switch", "--quiet", "-c", "feat/mine")
    code, out = run(brain, capsys)
    assert code == 0 and "clone    skipped" in out and "on feat/mine, not main: left as it is" in out
    assert git(brain.clone, "branch", "--show-current") == "feat/mine"


@needs_git
def test_offline_and_no_tests(brain, capsys):
    code, out = run(brain, capsys, offline=True, tests=False)
    assert code == 0 and "clone    skipped --offline" in out
    assert logged(brain)[-1] == f"brain release verify --planning {brain.root} --no-tests"
    assert git(brain.clone, "rev-parse", "HEAD") != brain.behind


@needs_git
def test_no_open_session_is_said(brain, capsys):
    code, out = run(brain, capsys, sessions=lambda: [])
    assert code == 0 and "sessions done    no open session found: new ones run v1.2.0" in out


@needs_git
def test_no_y_installs_nothing(brain, capsys, monkeypatch):
    code = releaseapply.main(args(brain, yes=False), brain=brain.brain, refused="", ask=lambda q: "n")
    assert code == 0 and "nothing installed" in capsys.readouterr().out and logged(brain) == ["installer "]
    monkeypatch.setattr(sys, "stdin", open(__file__, encoding="utf-8"))   # no terminal, no --yes: a failure
    code = releaseapply.main(args(brain, yes=False), brain=brain.brain, refused="")
    sys.stdin.close()
    assert code == 1 and "no terminal to answer y; --yes runs it (nothing installed)" in capsys.readouterr().out


@pytest.mark.parametrize("engine, said", [
    ({"repo": "ada/engine", "pin": "v1.2.0"}, "no engine.installer: brain update is this brain's install"),
    ({"repo": "ada/engine", "pin": "main", "installer": "install.py"}, "engine.pin is 'main', not a release tag"),
    ({"repo": "ada/engine", "pin": "v1.2.0", "installer": "missing.ps1"}, "missing.ps1: the installer"),
])
def test_nothing_to_apply_is_refused(tmp_path, capsys, engine, said):
    (tmp_path / "config.json").write_text(json.dumps({"v": 1, "engine": engine}), encoding="utf-8")
    code = releaseapply.main(SimpleNamespace(planning=str(tmp_path), root=None, yes=True, tests=True, offline=False),
                             refused="")
    assert code == 2 and said in capsys.readouterr().err


def test_the_commands_it_runs_pass_the_real_parser(tmp_path):
    parser = cli.build_parser()
    ns = parser.parse_args(["release", "verify", "--planning", str(tmp_path), "--no-tests"])
    assert ns.release_cmd == "verify" and ns.tests is False
    ns = parser.parse_args(["release", "apply", "--planning", str(tmp_path), "--yes", "--no-tests", "--offline"])
    assert ns.release_cmd == "apply" and ns.yes and not ns.tests and ns.offline


def test_installer_argv():
    assert releaseapply.installer_argv(Path("i.py"), ["-Apply"]) == [sys.executable, "i.py", "-Apply"]
    assert releaseapply.installer_argv(Path("install.ps1"), ["-Apply"])[-2:] == ["install.ps1", "-Apply"]
