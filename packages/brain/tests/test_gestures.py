"""The owner's gestures, declared once (brain.gestures, wi-brain-owner-only-registry): each one is refused to an agent's
session by the owner guard, through guard.sh's pre-filter, and by the command line where it gates it; the runbook's
table lists each. A gesture added to the list without its refusals fails here. The tests run as owner Ada."""

import dataclasses
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
    out = [f"brain {tail}", f"python -X utf8 -m brain {tail}", f"python -mbrain {tail}", f"python -Imbrain {tail}",
           f"python -Im brain {tail}", f"uv run brain {tail}", f"brain --project lab {tail}",
           f"~/.brain/venv/bin/python -m brain --root ~/b {tail} --json",
           # found by the review of the registry: brain's options by prefix, --store, quoted words, options between
           f"brain --store x {tail}", f"brain --proj lab {tail}", f"brain --ro ~/b {tail}", f"brain --root=~/b {tail}",
           "brain " + " ".join(f"'{w}'" for w in (*g.words, *g.flags[:1]))]
    if len(g.words) > 1:
        out.append(f"brain {g.words[0]} --json {' '.join(g.words[1:])} {' '.join(g.flags[:1])}")
        out.append(f"brain {g.words[0]} --reason x {' '.join(g.words[1:])} {' '.join(g.flags[:1])}")
    if g.flags and g.flags[0].startswith("--"):
        out += [f"brain {' '.join(g.words)} {g.flags[0][:5]}", f"brain {' '.join(g.words)} {g.flags[0][:3]}",
                f"brain {' '.join(g.words)} {g.flags[0][:6]}=1"]
    return out


def test_the_list_is_well_formed():
    names = [g.name for g in gestures.GESTURES]
    assert len(names) == len(set(names))
    assert gestures.VALUE_OPTS == tuple(a.option_strings[0] for a in cli.build_parser()._actions
                                        if a.option_strings and a.nargs is None and a.dest != "help")
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


@pytest.mark.parametrize("g", BRAIN, ids=lambda g: g.name)
def test_the_prefilter_starts_python_for_a_wide_spelling(g):
    """Under guards.gestures_wide the guard matches a gesture through a variable (``$B release $T``): the pre-filter
    must start Python for it, the subcommand's first word after a variable (review of wi-brain-release-tag-command)."""
    assert all(_needs_python([f"$B {g.words[0]} $x {' '.join(g.flags[:1])}"])), g.name


@pytest.mark.parametrize("command", [
    "brain usage guard", "brain usage quota --observe 41", "brain schedule install", "brain schedule install --json",
    "brain vault status", "brain vault reseal", "brain update --check", "brain uninstall", "brain queue",
    "brain queue add --kind action --title t --what 'brain vault open'", "brain handover check",
    "brain ipc token", "brain usage allow --help", "brain vault open -h", "grep -rn 'usage allow' docs/",
    "git commit -m 'brain vault open is refused'", "brain item update wi-x --status doing",
    # found by the review of the registry: brain named, not run
    "echo brain update", "cp -r brain update", "git add brain update", "echo run brain queue apply in your terminal",
    "brain queue add --kind action --title t apply", "ls packages/brain update",
])
def test_reads_and_mentions_pass(owner, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, strict=True)
    assert bash(owner, command) is None, command


def test_a_loose_gesture_is_refused_even_after_a_double_dash(owner, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, strict=None)
    assert "marks a coordinators' chain root" in bash(owner, "brain handover root -- -h")
    assert bash(owner, "brain usage allow --help") is None and bash(owner, "brain usage allow -- -h")


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
    "brain release tag": lambda env: detail.refused(env),   # brain.releasetag.main, after its plan
    "brain release apply": lambda env: detail.refused(env),   # brain.releaseapply.main, after the installer's plan
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


# The automation catalogue (wi-brain-automation-catalogue): its ids as 0.7.0 publishes them, a public contract that
# config.json's automation section keys (wi-brain-automation-config). An id may be added; one listed here stays in the
# catalogue or moves to gestures.RETIRED, never renamed, never reused.
IDS_V1 = (
    "engine-clone-pull", "session-archive", "handover-remote-control", "merge-go", "workflow-launch", "release-tag",
    "release-apply", "installer-apply", "engine-update", "usage-allow", "queue-apply", "uninstall", "handover-root",
    "remote-control", "permission-mode", "schedule-install", "otel-headers", "vault-open", "vault-drill",
    "vault-device-init", "vault-device-forget-previous", "vault-reseal", "elevated", "rules-text", "automation-raise",
    "money", "arming", "visibility", "accounts", "legal",
)
AUTOMATION_DOC = Path(__file__).resolve().parents[1] / "docs" / "automation.md"


def test_the_catalogue_is_well_formed():
    ids = [a.id for a in gestures.CATALOGUE]
    assert len(ids) == len(set(ids))
    assert not set(ids) & set(gestures.RETIRED)
    for a in gestures.CATALOGUE:
        assert re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", a.id), a.id
        assert a.ceiling in gestures.LEVELS and a.default in gestures.LEVELS, a.id
        assert gestures.LEVELS.index(a.default) <= gestures.LEVELS.index(a.ceiling), a.id   # its default fits
        assert a.runs in gestures.RUNS and a.label, a.id
        assert a.floor == "" or a.floor in gestures.FLOOR, a.id
        # where it runs bounds it (review of #310): the elevated terminal is the floor's, the harness's own
        # confirmation is never raised by the Brain
        assert a.runs != "elevated" or a.floor == "elevated", a.id
        assert a.runs != "harness" or a.ceiling in ("manual", "ask"), a.id


def test_the_ids_are_stable():
    ids = {a.id for a in gestures.CATALOGUE}
    assert [i for i in IDS_V1 if i not in ids and i not in gestures.RETIRED] == []
    assert gestures.CATALOGUE_V == 1


def test_a_floor_gesture_never_reads_above_manual():
    floor = [a for a in gestures.CATALOGUE if a.floor]
    assert {a.floor for a in floor} == set(gestures.FLOOR)   # every category of the floor is shown
    for a in floor:
        assert a.ceiling == "manual" and a.default == "manual", a.id
        assert [gestures.effective(a, lvl) for lvl in gestures.LEVELS] == ["manual"] * 3, a.id
    # what AUTO-1 names: Remote Control outside a hand-over, the permission mode, the rules' text, raising a level
    for gid in ("remote-control", "permission-mode", "rules-text", "automation-raise", "elevated"):
        assert gestures.automation(gid).floor, gid


def test_the_floor_copies_the_never_grantable_categories():
    from brain import permissions
    assert gestures.NEVER_GRANTABLE == tuple(c for c, *_ in permissions.NEVER)
    assert set(gestures.FLOOR) == {*gestures.NEVER_GRANTABLE, "elevated", "rules", "raise"}


def test_a_never_grantable_owner_gesture_is_a_floor_gesture():
    """A gesture of the owner-only list whose guard category is never-grantable is a floor gesture of the catalogue."""
    for g in gestures.GESTURES:
        if g.category in gestures.NEVER_GRANTABLE:
            a = next(a for a in gestures.CATALOGUE if g.name in a.commands)
            assert a.floor and a.ceiling == "manual", (g.name, a.id)


def test_each_owner_gesture_is_in_the_catalogue_once():
    for g in gestures.GESTURES:
        assert [a.id for a in gestures.CATALOGUE if g.name in a.commands] != [], g.name
        assert len([a for a in gestures.CATALOGUE if g.name in a.commands]) == 1, g.name


def test_the_session_run_gestures_are_declared():
    """spec-brain-automation-levels § 1, G3 to G7: what a session runs, and the harness's two, which stay ask."""
    runs = {a.id: a.runs for a in gestures.CATALOGUE}
    assert {k: runs[k] for k in ("engine-clone-pull", "session-archive", "handover-remote-control")} == \
        dict.fromkeys(("engine-clone-pull", "session-archive", "handover-remote-control"), "session")
    for gid in ("merge-go", "workflow-launch"):
        a = gestures.automation(gid)
        assert a.runs == "harness" and a.ceiling == "ask" and a.conditions, gid
    for gid in ("engine-clone-pull", "session-archive", "handover-remote-control"):
        assert gestures.automation(gid).conditions, gid   # a level changes who confirms, never the conditions


@pytest.mark.parametrize("level, expected", [
    ("manual", "manual"), ("ask", "ask"), ("auto", "manual"),   # above release-tag's ceiling (ask)
    ("AUTO", "manual"), ("", "manual"), (None, "manual"), (2, "manual"), (["ask"], "manual"),   # unreadable
])
def test_effective_fails_closed(level, expected):
    assert gestures.effective(gestures.automation("release-tag"), level) == expected


def test_an_unknown_gesture_reads_manual():
    assert gestures.automation("no-such-gesture") is None
    assert gestures.effective(None, "auto") == "manual"
    assert gestures.effective("engine-clone-pull", "auto") == "manual"   # an id, not its entry (review of #310)
    floor = gestures.automation("vault-open")
    assert gestures.effective(dataclasses.replace(floor, ceiling="auto"), "auto") == "manual"   # the floor wins
    assert gestures.effective(gestures.automation("engine-clone-pull"), "auto") == "auto"


def test_no_default_raises_today_s_behaviour():
    """The engine's defaults are today's behaviour: only the clone's fast-forward (brain refresh, 0.6.1) runs by itself;
    the archive and Remote Control at a hand-over stay the app's ask until a config raises them."""
    assert [a.id for a in gestures.CATALOGUE if a.default == "auto"] == ["engine-clone-pull"]
    for gid in ("session-archive", "handover-remote-control", "usage-allow", "installer-apply"):
        assert gestures.automation(gid).default != "auto", gid


def test_the_catalogue_data():
    data = gestures.catalogue()
    assert data["v"] == 1 and data["levels"] == ["manual", "ask", "auto"]
    assert [g["id"] for g in data["gestures"]] == [a.id for a in gestures.CATALOGUE]
    assert all(g["source"] == "default" for g in data["gestures"])
    assert all(g["level"] == "manual" for g in data["gestures"] if g["locked"])
    levels = {g["id"]: g["level"] for g in data["gestures"]}
    assert levels == {a.id: a.default for a in gestures.CATALOGUE}   # its level is its default, never its ceiling
    assert levels["session-archive"] == "ask" and levels["usage-allow"] == "manual"
    assert data["floor"] == list(gestures.FLOOR) and data["retired"] == list(gestures.RETIRED)


def test_the_automation_doc_lists_each_gesture():
    text = AUTOMATION_DOC.read_text(encoding="utf-8")
    for a in gestures.CATALOGUE:
        assert f"| `{a.id}` | {a.runs} | {a.ceiling} | {a.default} | {a.floor or ''} |".replace("|  |", "| |") \
            in text, a.id


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
