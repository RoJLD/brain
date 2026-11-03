"""The session-settings guard (wi-brain-guard-session-settings, brain.guards: check_session_settings): a session's
Remote Control and permission mode are security-settings, the owner's alone; the refusal is queued for the owner and
the override does not lift it. The tests run as owner Ada (fixtures/brain), on invented sessions."""

import json

import pytest
from test_guards import bash, decide, payload, pwsh
from test_guards_owner_power import _store

from brain import guards, permissions, projects, queue

AT = "2026-11-03T12:00:00Z"


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-projects.yaml"))
    w = tmp_path / "work"
    w.mkdir()
    return w


@pytest.mark.parametrize("tool,args", [
    ("mcp__ccd_session_mgmt__set_remote_control", {"session_id": "self", "enabled": True}),
    ("mcp__ccd_session_mgmt__set_remote_control", {"session_id": "local_ada-2", "enabled": False}),
    ("mcp__other_server__set_remote_control", {"session_id": "self", "enabled": True}),   # any MCP prefix
    ("mcp__ccd_session_mgmt__set_session_permission_mode", {"session_id": "self", "mode": "bypassPermissions"}),
    ("mcp__ccd_session_mgmt__set_session_permission_mode", {"session_id": "local_ada-3", "mode": "plan"}),  # lower too
    ("mcp__ccd_settings__set_setting", {"key": "connect_new_sessions_to_remote_control", "value": True}),
])
def test_a_session_setting_is_refused_whatever_its_value(work, tool, args):
    reason = decide(payload(tool, work, **args))
    assert reason and f"{tool} refused: security-settings is Ada's alone" in reason
    assert "brain queue add --kind action --guard guard-" in reason or "put it in Ada's queue" in reason
    assert "No override: security-settings is Ada's alone, in the app." in reason


@pytest.mark.parametrize("tool,args", [
    ("mcp__ccd_settings__set_setting", {"key": "output_style", "value": "Explanatory"}),
    ("mcp__ccd_settings__set_setting", {"key": "auto_archive_on_pr_close", "value": True}),
    ("mcp__ccd_session_mgmt__set_session_model", {"session_id": "self", "model": "x"}),
    ("mcp__ccd_session_mgmt__get_usage", {}),
])
def test_other_settings_pass(work, tool, args):
    assert decide(payload(tool, work, **args)) is None


def test_the_override_cannot_lift_it_not_even_all(work, brain_home, monkeypatch):
    (brain_home / "ledger").mkdir(parents=True)
    call = payload("mcp__ccd_session_mgmt__set_remote_control", work, session_id="self", enabled=True)
    for allow in ("owner", "owner:security-settings", "all"):
        monkeypatch.setenv(guards.ALLOW_ENV, allow)
        assert "security-settings is Ada's alone" in decide(call)
    rows = [json.loads(line) for f in (brain_home / "ledger").glob("guards-*.jsonl")
            for line in f.read_text(encoding="utf-8").splitlines()]
    assert {(r["guard"], r["check"], r["decision"]) for r in rows} == {("owner", "security-settings", "denied")}
    assert rows[0]["request"]["what"] == 'set_remote_control enabled=true session_id="self"'
    monkeypatch.setenv(guards.ALLOW_ENV, "owner")   # other owner categories still lift
    assert decide(payload("mcp__scheduled-tasks__create_scheduled_task", work, taskId="t")) is None


def test_the_category_is_never_grantable(work):
    cats = permissions.default_categories()
    assert "security-settings" in {c.name for c in cats}
    assert permissions.never_rule("mcp__ccd_session_mgmt__set_remote_control", cats) == "security-settings"
    assert permissions.never_rule("mcp__ccd_session_mgmt__set_session_permission_mode", cats) == "security-settings"
    assert permissions.never_category("turn on Remote Control for the session", cats) == "security-settings"
    assert permissions.never_category("switch it to bypassPermissions", cats) == "security-settings"
    assert permissions.never_category("start the remote controller service", cats) != "security-settings"


def test_the_refusal_goes_to_the_owners_queue(work, tmp_path, brain_home, monkeypatch):
    root = _store(tmp_path)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    (tmp_path / "projects.yaml").write_text(f"brain: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    reason = decide(payload("mcp__ccd_session_mgmt__set_session_permission_mode", root, session_id="local_ada-4",
                            mode="bypassPermissions", _consent="app"))
    ref = reason.split("--guard ")[1].split()[0]
    entry = next(e for e in queue.collect([projects.for_root(root)], with_graph=False)[0]["entries"]
                 if e["id"] == ref)
    assert entry["category"] == "security-settings" and "_consent" not in entry["title"]
    assert entry["title"] == 'set_session_permission_mode mode="bypassPermissions" session_id="local_ada-4"'
    ddr, _, _ = queue.add(root, kind="action", title="", what="", at=AT, guard=ref)
    assert ddr["title"].startswith("Ada's alone (security-settings): set_session_permission_mode")


def test_the_usage_override_is_refused_to_a_session(work, brain_home):
    for command in ("brain usage allow --hours 2", "python -m brain usage allow", "brain --project x usage allow"):
        reason = bash(work, command)
        assert reason and "brain usage allow refused: it lifts the usage guard" in reason, command
    assert "refused: it lifts the usage guard" in pwsh(work, "brain.exe usage allow --hours 8")
    allow = (brain_home / "usage" / "allow.json").as_posix()
    assert "lifts the usage guard" in bash(work, f"echo '{{}}' > {allow}")
    assert "lifts the usage guard" in decide(payload("Write", work, file_path=allow, content="{}"))
    assert bash(work, "brain usage guard") is None and bash(work, "brain usage quota --observe 41") is None


def test_the_prefilter_starts_python_for_the_usage_override():
    from test_guards import _needs_python
    assert _needs_python(["brain usage allow --hours 2", "python -m brain usage  allow", "brain usage guard"]) == [
        True, True, False]
