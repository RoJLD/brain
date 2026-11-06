"""The public and secrets checks fail closed (COMPAT-4, wi-brain-guards-fail-closed): an unexpected configuration, an
empty config discovery although a personal brain is named, or a guard.sh with no Python that imports brain refuses
git commit and git push, the reason naming its fix; the SessionStart health says so. An unknown key never refuses."""

import io
import json
import os
import subprocess

import pytest

from brain import config, guards, stacks
from test_guards import PLUGIN, decide, payload

GOOD = {"v": 1, "identity": {"owner": "Ada"}, "public": {"repos": ["acme/engine"]}}

# (case, config.json's text, a word of the refusal's fix)
BROKEN = [("unreadable", '{"v": 1, "identity": {"owner": "Ada"},}', "brain config --check"),
          ("not an object", "[1, 2]", "an object, got list"),
          ("public not an object", json.dumps({**GOOD, "public": ["acme/engine"]}), "public is a list"),
          ("v above the known one", json.dumps({**GOOD, "v": 99}), "brain update")]


def _config(tmp_path, monkeypatch, text):
    f = tmp_path / "cfg" / config.FILE
    f.parent.mkdir(exist_ok=True)
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    return f


# --- what "unexpected" is ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("case,text,fix", BROKEN, ids=[b[0] for b in BROKEN])
def test_unexpected_configs_name_their_fix(tmp_path, monkeypatch, case, text, fix):
    _config(tmp_path, monkeypatch, text)
    assert fix in config.unexpected()


def test_an_unknown_key_or_an_older_v_is_never_unexpected(tmp_path, monkeypatch):
    _config(tmp_path, monkeypatch, json.dumps({**GOOD, "from_a_newer_brain": {"x": 1}, "public": {"later": 1}}))
    assert config.unexpected() == ""
    _config(tmp_path, monkeypatch, json.dumps({**GOOD, "v": 0}))
    assert config.unexpected() == ""
    _config(tmp_path, monkeypatch, json.dumps({k: v for k, v in GOOD.items() if k != "public"}))
    assert config.unexpected() == ""


def test_brain_config_naming_no_file_is_unexpected(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "gone" / config.FILE))
    assert "BRAIN_CONFIG names" in config.unexpected() and "unset it" in config.unexpected()


def test_an_empty_discovery_is_unexpected_only_when_a_personal_brain_is_named(tmp_path, monkeypatch, brain_home):
    monkeypatch.delenv("BRAIN_CONFIG")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config.paths, "package_repo", lambda: None)
    monkeypatch.setattr(config.paths, "installed_checkout", lambda: None)
    assert config.unexpected() == ""   # no personal brain named: the defaults, nothing to trust or distrust
    brain_home.mkdir(parents=True, exist_ok=True)
    (brain_home / "personal.json").write_text(json.dumps({"root": str(tmp_path / "renamed-brain")}), encoding="utf-8")
    why = config.unexpected()
    assert "renamed-brain, which does not exist" in why and "install.ps1 -Apply" in why
    (tmp_path / "renamed-brain").mkdir()
    assert "holds no config.json" in config.unexpected()
    monkeypatch.setenv("BRAIN_PERSONAL", str(tmp_path / "elsewhere"))
    assert config.unexpected().startswith("BRAIN_PERSONAL names the personal brain")
    monkeypatch.delenv("BRAIN_PERSONAL")
    (tmp_path / "renamed-brain" / config.FILE).write_text(json.dumps(GOOD), encoding="utf-8")
    assert config.unexpected() == ""


# --- the guards: a broken-config test per guard in scope -----------------------------------------------------------

COMMITS = ["git commit -m x", "git add -A && git commit -am x", 'git -C "{d}" commit -m x']
PUSHES = ["git push", "git push origin main", 'git -C "{d}" push -u origin HEAD']


@pytest.mark.parametrize("case,text,fix", BROKEN, ids=[b[0] for b in BROKEN])
def test_a_broken_config_refuses_commits_and_pushes(tmp_path, monkeypatch, case, text, fix):
    _config(tmp_path, monkeypatch, text)
    for command in COMMITS + PUSHES:
        reason = decide(payload("Bash", tmp_path, command=command.format(d=tmp_path.as_posix())))
        assert reason and "cannot trust the configuration, so they fail closed" in reason and fix in reason, command
        assert "BRAIN_GUARD_ALLOW=public" in reason   # the owner's override, as for every public check
    reason = decide(payload("PowerShell", tmp_path, command="git push origin main"))
    assert reason and "git push refused" in reason
    for command in ("git status", "git log --grep push", "ls -la", "git push --help", "git commit --help"):
        assert decide(payload("Bash", tmp_path, command=command)) is None, command


def test_a_good_config_or_an_override_lets_the_check_pass(tmp_path, monkeypatch, brain_home):
    _config(tmp_path, monkeypatch, json.dumps(GOOD))
    assert guards.check_config(guards.calls("git commit -m x", str(tmp_path))) is None
    _config(tmp_path, monkeypatch, "not json")
    assert guards.check_config(guards.calls("git commit -m x", str(tmp_path)))
    (brain_home / "ledger").mkdir(parents=True)
    monkeypatch.setenv(guards.ALLOW_ENV, "public:config")
    assert decide(payload("Bash", tmp_path, command="git commit -m x")) is None
    rows = [json.loads(line) for f in (brain_home / "ledger").glob("guards-*.jsonl")
            for line in f.read_text(encoding="utf-8").splitlines()]
    assert [(r["guard"], r["check"], r["decision"]) for r in rows] == [("public", "config", "overridden")]


def test_an_empty_discovery_refuses_a_push(tmp_path, monkeypatch, brain_home):
    monkeypatch.delenv("BRAIN_CONFIG")
    monkeypatch.setattr(config.paths, "package_repo", lambda: None)
    monkeypatch.setattr(config.paths, "installed_checkout", lambda: None)
    monkeypatch.setenv("BRAIN_PERSONAL", str(tmp_path / "old-brain"))   # renamed since
    reason = decide(payload("Bash", tmp_path, command="git push origin main"))
    assert reason and "BRAIN_PERSONAL names the personal brain" in reason


# --- guard.sh with no Python that imports brain --------------------------------------------------------------------

def _guard_sh(tmp_path, command, kind="shell", python=True):
    """guard.sh run on a payload, its Python a fake one that fails as an interpreter without brain does (``python``),
    or none at all: (exit code, stdout)."""
    from test_capture import _bash
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    env = {k: v for k, v in os.environ.items() if k not in ("BRAIN_PYTHON",)}
    env.update(BRAIN_HOME=str(tmp_path / "home"), BRAIN_SELFTIME="0", PATH=str(tmp_path / "no-python"))
    if python:
        fake = tmp_path / "python-without-brain"
        fake.write_text("#!/bin/sh\necho 'ModuleNotFoundError: No module named brain' >&2\nexit 1\n", encoding="utf-8")
        fake.chmod(0o755)
        env["BRAIN_PYTHON"] = fake.as_posix()
    p = payload("Bash" if kind == "shell" else "Write", tmp_path, command=command)
    out = subprocess.run([sh, str(PLUGIN / "hooks" / "guard.sh"), kind], input=json.dumps(p), capture_output=True,
                         text=True, env=env, timeout=60)
    return out.returncode, out.stdout


@pytest.mark.parametrize("python", [True, False], ids=["python-without-brain", "no-python"])
def test_guard_sh_refuses_commits_and_pushes_when_the_guards_cannot_run(tmp_path, python):
    for command in ("git commit -m x", "git push origin main", 'GIT -C "C:\\work\\x" push', "git -c a=b commit -m x",
                    '& "C:\\Program Files\\Git\\cmd\\git.exe" push origin HEAD',
                    "cd x && git add -A && git commit -m y"):
        rc, out = _guard_sh(tmp_path, command, python=python)
        assert rc == 0 and out, command
        hso = json.loads(out)["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny" and "the guards cannot run" in hso["permissionDecisionReason"]
        assert "brain update" in hso["permissionDecisionReason"]
        assert ("cannot import brain" if python else "no Python 3 found") in hso["permissionDecisionReason"]
    for command in ("git status", "rm -rf build", "echo x > f", "gitleaks detect"):
        assert _guard_sh(tmp_path, command, python=python) == (0, ""), command
    assert _guard_sh(tmp_path, "git commit -m x", kind="edit", python=python) == (0, "")


def test_the_prefilter_always_starts_python_for_a_commit_or_a_push():
    from test_guards import _needs_python
    shapes = ["git commit -m x", "GIT push", '"git" push origin main', "git.exe commit -m x",
              '& "C:\\Program Files\\Git\\cmd\\git.exe" push', "git -c user.name=x commit -m y", "git --no-pager push",
              "ls\ngit push", "git -C x push", "git add . && git commit -m x"]
    assert _needs_python(shapes) == [True] * len(shapes)


# --- the SessionStart health -------------------------------------------------------------------------------------

def test_the_health_hook_says_the_guards_refuse(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(stacks, "load", lambda *a, **k: [])
    monkeypatch.setattr(stacks, "watched_down", lambda *a, **k: [])
    _config(tmp_path, monkeypatch, "{oops")
    assert stacks.hook_main(["SessionStart"], io.StringIO("{}")) == 0
    text = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "refuse every git commit and git push" in text and "brain config --check" in text
    _config(tmp_path, monkeypatch, json.dumps(GOOD))
    assert stacks.hook_main(["SessionStart"], io.StringIO("{}")) == 0
    assert "git commit" not in capsys.readouterr().out


def test_health_sh_says_the_guards_cannot_run(tmp_path):
    from test_capture import _bash
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    env = {k: v for k, v in os.environ.items() if k != "BRAIN_PYTHON"}
    env.update(BRAIN_HOME=str(tmp_path / "home"), BRAIN_SELFTIME="0", PATH=str(tmp_path / "no-python"))
    out = subprocess.run([sh, str(PLUGIN / "hooks" / "health.sh"), "SessionStart"], input="{}", capture_output=True,
                         text=True, env=env, timeout=60)
    assert out.returncode == 0
    hso = json.loads(out.stdout)["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart" and "The brain guards cannot run" in hso["additionalContext"]
