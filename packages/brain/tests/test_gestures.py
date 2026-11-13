"""The owner's gestures, declared once (brain.gestures, wi-brain-owner-only-registry): each one is refused to an agent's
session by the owner guard, through guard.sh's pre-filter, and by the command line where it gates it; the runbook's
table lists each. A gesture added to the list without its refusals fails here. The tests run as owner Ada."""

import json
import re
from pathlib import Path

import pytest
from test_guards import _needs_python, bash, pwsh

from brain import cli, detail, gestures, guards, succession, vault

PERMISSIONS = Path(__file__).resolve().parent / "fixtures" / "permissions.yaml"  # installer declared
DOC = Path(__file__).resolve().parents[1] / "docs" / "guards.md"
BRAIN = [g for g in gestures.GESTURES if g.program == "brain"]
AGENT = {"CLAUDECODE": "1"}


@pytest.fixture
def owner(tmp_path, monkeypatch):
    """Ada's permissions.yaml and config.json (guards.owner_strict as each test sets it), a working folder."""
    monkeypatch.setenv("BRAIN_PERMISSIONS", str(PERMISSIONS))
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-projects.yaml"))
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    for var in gestures.AGENT_ENV:
        monkeypatch.delenv(var, raising=False)
    work = tmp_path / "work"
    work.mkdir()
    return work


def config(tmp_path, monkeypatch, strict: bool | None):
    data = {"v": 1, "identity": {"owner": "Ada", "kind": "person"}}
    if strict is not None:
        data["guards"] = {"owner_strict": strict}
    cfg = tmp_path / "ada-config.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    return data


def spellings(g):
    """The ways a session runs a gesture: brain, its .exe, python -m (with options before -m), -mbrain, options of
    brain before the subcommand, a flag's argparse prefix."""
    tail = " ".join((*g.words, *g.flags[:1]))
    out = [f"brain {tail}", f"python -X utf8 -m brain {tail}", f"python -mbrain {tail}",
           f"brain --project lab {tail}", f"~/.brain/venv/bin/python -m brain --root ~/b {tail} --json"]
    if g.flags and g.flags[0].startswith("--"):
        out.append(f"brain {' '.join(g.words)} {g.flags[0][:5]}")
    return out


def test_the_list_is_well_formed():
    names = [g.name for g in gestures.GESTURES]
    assert len(names) == len(set(names))
    for g in gestures.GESTURES:
        assert g.guard in ("always", "strict") and g.cli in ("own", "gate", "none") and g.why.startswith("it ")
        assert g.category and re.fullmatch(r"[a-z-]+", g.category)


@pytest.mark.parametrize("g", BRAIN, ids=lambda g: g.name)
def test_the_guard_refuses_each_gesture_to_a_session(owner, tmp_path, monkeypatch, g):
    config(tmp_path, monkeypatch, strict=True)
    for command in spellings(g):
        reason = bash(owner, command)
        assert reason and f"{guards.ALLOW_ENV}=owner (or owner:{g.category})" in reason, command
        assert "Ada" in reason, command
    assert pwsh(owner, f"brain.exe {' '.join((*g.words, *g.flags[:1]))}"), g.name


@pytest.mark.parametrize("g", [g for g in BRAIN if g.guard == "strict"], ids=lambda g: g.name)
def test_a_strict_gesture_passes_the_guard_without_owner_strict(owner, tmp_path, monkeypatch, g):
    command = f"brain {' '.join((*g.words, *g.flags[:1]))}"
    for strict in (None, False):
        config(tmp_path, monkeypatch, strict=strict)
        assert bash(owner, command) is None, (strict, command)


@pytest.mark.parametrize("g", BRAIN, ids=lambda g: g.name)
def test_the_prefilter_starts_python_for_each_gesture(g):
    assert all(_needs_python(spellings(g))), g.name


@pytest.mark.parametrize("command", [
    "brain usage guard", "brain usage quota --observe 41", "brain schedule install", "brain schedule install --json",
    "brain vault status", "brain vault reseal", "brain update --check", "brain uninstall", "brain queue",
    "brain queue add --kind action --title t --what 'brain vault open'", "brain handover check",
    "brain ipc token", "brain usage allow --help", "brain vault open -h", "grep -rn 'usage allow' docs/",
    "git commit -m 'brain vault open is refused'", "brain item update wi-x --status doing",
])
def test_reads_and_mentions_pass(owner, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, strict=True)
    assert bash(owner, command) is None, command


def test_a_queued_category_is_an_action_for_the_owner(owner, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, strict=True)
    reason = bash(owner, "brain vault open lab")
    assert "keys is Ada's alone" in reason and "brain queue add --kind action --guard guard-" in reason
    reason = bash(owner, "brain queue apply ddr-1")
    assert "brain queue apply refused: it runs an action the owner queued as theirs; it is Ada's" in reason
    assert "brain queue add" not in reason


@pytest.mark.parametrize("g", [g for g in BRAIN if g.cli == "gate"], ids=lambda g: g.name)
def test_the_command_line_gates_its_gestures_under_owner_strict(owner, tmp_path, monkeypatch, capsys, g):
    data = config(tmp_path, monkeypatch, strict=True)
    argv = [*g.words, *g.flags[:1]]
    assert gestures.cli_refusal(argv, env=AGENT, data=data).startswith(f"{g.name} is Ada's, in their own terminal")
    assert gestures.cli_refusal(argv, env={}, data=data) == ""                       # the owner's own terminal
    assert gestures.cli_refusal(argv, env=AGENT, data={"v": 1}) == ""               # owner_strict off
    assert gestures.cli_refusal(["--project", "lab", *argv], env=AGENT, data=data)  # brain's options first
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(argv) == 2                                                       # refused before it runs
    assert "refused in an agent's session (CLAUDECODE is set" in capsys.readouterr().err


# The command's own check, for each gesture the command line refuses itself (cli: own): a new one is listed here.
OWN = {
    "brain handover root": lambda env: succession._refused(env),
    "brain vault open": lambda env: _vault(env, "brain vault open"),
    "brain vault drill": lambda env: _vault(env, "brain vault drill"),
    "brain vault device init": lambda env: _vault(env, "brain vault device init"),
    "brain vault device forget-previous": lambda env: _vault(env, "brain vault device forget-previous"),
    "brain update": lambda env: detail.refused(env),
    "brain uninstall --apply": lambda env: detail.refused(env),
    "brain queue apply": lambda env: detail.refused(env),
}


def _vault(env, what):
    with pytest.MonkeyPatch.context() as mp:
        for var in vault.AGENT_ENV:
            mp.delenv(var, raising=False)
        for k, v in env.items():
            mp.setenv(k, v)
        try:
            vault.human_only(what)
        except vault.VaultError as exc:
            return str(exc)
    return ""


@pytest.mark.parametrize("g", [g for g in BRAIN if g.cli == "own"], ids=lambda g: g.name)
def test_each_own_check_refuses_an_agent_session(owner, tmp_path, monkeypatch, g):
    config(tmp_path, monkeypatch, strict=None)
    assert g.name in OWN, f"{g.name}: name the command's own refusal in OWN"
    assert OWN[g.name](AGENT), g.name
    assert not OWN[g.name]({}), g.name


def test_owner_strict_is_off_unless_said(owner, tmp_path, monkeypatch):
    for data in ({"v": 1}, {"guards": None}, {"guards": {"owner_strict": "yes"}}, []):
        assert gestures.strict(data) is False
    config(tmp_path, monkeypatch, strict=True)
    assert gestures.strict() is True
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(bad))
    assert gestures.strict() is False


def test_the_runbook_lists_each_gesture():
    text = DOC.read_text(encoding="utf-8")
    for g in gestures.GESTURES:
        assert f"| `{g.name}" in text, g.name


@pytest.mark.parametrize("words, name", [
    (["brain", "usage", "allow", "--hours", "2"], "brain usage allow"),
    (["python", "-I", "-m", "brain.cli", "schedule", "install", "--app"], "brain schedule install --apply"),
    (["brain", "ipc", "$x"], "brain ipc otel-headers"),
    (["r=root;", "brain", "handover", "%R%"], "brain handover root"),
    (["uv", "run", "brain", "update"], "brain update"),
    ([".\\install.ps1", "-Apply"], None),          # a script: the owner guard's own table
    (["brain", "update", "--check"], None),
    (["brain", "update", "--help"], None),
    (["brain", "journal", "add", "usage allow"], None),
])
def test_match(words, name):
    g = gestures.match(words)
    assert (g.name if g else None) == name
