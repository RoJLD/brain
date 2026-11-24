"""The guard's archive case (wi-brain-coordinator-handover-no-prompt, brain.guards: archive): the owner's allow rules
for archive_session and set_remote_control lift the app's card, so the guard bounds both. archive_session passes
(nothing printed, logged allowed) only for a finished session the caller started or the caller's predecessor at a
hand-over, with no child blocking, its PRs merged or closed and its folder clean or gone; any other call, and an error,
gets permissionDecision ask (the card no allow rule lifts). The exact rule mcp__ccd_session_mgmt__set_remote_control
leaves security-settings (GUARD_BOUNDED); its guard keeps refusing outside its three cases. Invented sessions, as
test_guards_remote_control's lab."""

import io
import json
import os
import subprocess

import pytest
from brain import guards, permissions, sessions
from test_guards import PLUGIN, bash, decide, payload, pwsh
import test_guards_remote_control as rclab
from test_guards_remote_control import CLI, E, F, G, K, R, RC, X, call, rows

lab = rclab.lab   # its fixture, the same invented sessions

ARCHIVE = "mcp__ccd_session_mgmt__archive_session"


def hook(p) -> tuple[str | None, str]:
    """(permissionDecision, reason) the hook prints, (None, '') when the call passes."""
    out = io.StringIO()
    assert guards.main(stdin=io.StringIO(json.dumps(p)), stdout=out) == 0
    if not out.getvalue():
        return None, ""
    hso = json.loads(out.getvalue())["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse" and "\n" not in hso["permissionDecisionReason"]
    return hso["permissionDecision"], hso["permissionDecisionReason"]


def arc(lab, target, caller=F):
    return call(lab, target, None, caller=caller, tool=ARCHIVE, reason="PR merged")


def work(lab, host, prs=(), cwd="gone", **more):
    """Add to a session's app file its PRs (state per PR, or a raw entry) and its folder (gone: a path that does not
    exist, under the lab)."""
    f = next((lab.cwd / "appdata").rglob(f"{host}.json"))
    data = json.loads(f.read_text(encoding="utf-8"))
    data["prs"] = [p if not isinstance(p, str) else {"prNumber": 10 + i, "repo": "acme/x", "state": p}
                   for i, p in enumerate(prs)]
    data["cwd"] = str(lab.cwd / "worktrees" / host) if cwd == "gone" else cwd
    data.update(more)
    f.write_text(json.dumps(data), encoding="utf-8")


def asked(lab, p, why):
    decision, reason = hook(p)
    assert decision == "ask", reason
    assert "archive_session is left to Ada's approval" in reason and why in reason, reason
    return reason


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=60,
                   env={**os.environ, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": "a",
                        "GIT_COMMITTER_EMAIL": "a@x"})


# --- the child case ---

def test_a_finished_child_merged_and_gone_passes_and_is_logged(lab):
    work(lab, K, prs=["MERGED", "closed"])
    assert hook(arc(lab, K)) == (None, "")
    [row] = rows(lab)
    assert (row["guard"], row["check"], row["decision"], row["case"]) == ("owner", "session-archive", "allowed",
                                                                          "child")
    assert row["what"]["session_id"] == K


def test_a_child_with_a_pr_left_open_asks(lab):
    work(lab, K, prs=["MERGED", "OPEN"])
    asked(lab, arc(lab, K), f"{K} has 1 PR(s) neither merged nor closed: acme/x#11 (OPEN)")
    assert [(r["decision"], r["check"], r["case"]) for r in rows(lab)] == [("asked", "session-archive", "outside")]


@pytest.mark.parametrize("entry,named", [({"prNumber": 3, "repo": "acme/x"}, "acme/x#3 (no state)"),
                                         ("not a mapping", "?#? (no state)")])
def test_a_pr_the_guard_cannot_read_counts_open(lab, entry, named):
    work(lab, K)
    f = next((lab.cwd / "appdata").rglob(f"{K}.json"))
    data = json.loads(f.read_text(encoding="utf-8"))
    data["prs"] = [entry]
    f.write_text(json.dumps(data), encoding="utf-8")
    asked(lab, arc(lab, K), named)


def test_prs_that_are_not_a_list_ask(lab):
    work(lab, K)
    f = next((lab.cwd / "appdata").rglob(f"{K}.json"))
    data = json.loads(f.read_text(encoding="utf-8"))
    data["prs"] = {"10": "MERGED"}
    f.write_text(json.dumps(data), encoding="utf-8")
    asked(lab, arc(lab, K), f"{K}'s app file cannot be read again")


def test_the_folder_must_be_clean(lab, tmp_path):
    repo = tmp_path / "wt-k"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", "a")
    work(lab, K, prs=["MERGED"], cwd=str(repo))
    assert hook(arc(lab, K)) == (None, "")
    (repo / "b.txt").write_text("b", encoding="utf-8")   # untracked
    (repo / "a.txt").write_text("changed", encoding="utf-8")
    asked(lab, arc(lab, K), f"{repo} has 2 uncommitted change(s) the archive would remove with its worktree")


@pytest.mark.parametrize("cwd,why", [("", "its folder cannot be read from its app file"),
                                     ("relative/wt", "is not an absolute path"),
                                     (None, "its folder cannot be read from its app file")])
def test_a_folder_the_guard_cannot_read_asks(lab, cwd, why):
    work(lab, K, cwd=cwd)
    asked(lab, arc(lab, K), why)


def test_a_folder_that_is_no_checkout_asks(lab, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    work(lab, K, cwd=str(plain))
    asked(lab, arc(lab, K), f"{plain} is not the top of a checkout git can read")


def test_a_child_with_a_blocking_child_asks(lab, monkeypatch):
    q = "local_34343434-0000-4000-8000-343434343434"
    monkeypatch.setitem(CLI, q, "34343434-cli0-4000-8000-000000000000")
    lab.put(q, parent=K, name="grandchild")
    lab.turn(q, "idle")
    work(lab, K)
    asked(lab, arc(lab, K), f"{K} has 1 child session(s) neither archived nor detached")
    lab.put(q, parent=K, name="grandchild", detached=True)
    assert hook(arc(lab, K)) == (None, "")


@pytest.mark.parametrize("target,why", [
    (R, f"{R} is running, not finished"),
    (X, f"{X} was not started by this session, nor is it the coordinator that started it"),
    (G, f"{G} is a coordinator: its own successor archives it"),
    ("self", "a session's own archive is the owner's"),
    (F, "a session's own archive is the owner's"),
    ("local_77777777-0000-4000-8000-777777777777", "is not in the desktop app's session files"),
    (" ", "its session_id is not another session's app id"),
])
def test_any_other_archive_asks(lab, target, why):
    for h in (K, R, X, G):
        work(lab, h)
    asked(lab, arc(lab, target), why)


def test_an_archived_or_asking_child_asks(lab):
    work(lab, K)
    lab.turn(K, "asking")
    asked(lab, arc(lab, K), f"{K} is asking, not finished")
    lab.put(K, parent=F, name="rc-guard", archived=True)
    asked(lab, arc(lab, K), f"{K} is archived already")


def test_a_title_makes_no_child_archivable_coordinator(lab):
    lab.put(K, parent=F, name="rc-guard", title="Coordination du Brain — coordinateur K")
    work(lab, K)
    asked(lab, arc(lab, K), f"{K} is a coordinator")


# --- the predecessor case ---

def _handed_over(lab):
    """F handed over to G: F idle, its other children archived (K) or detached (R)."""
    lab.turn(F, "idle")
    lab.put(K, parent=F, name="rc-guard", archived=True)
    lab.put(R, parent=F, name="busy", detached=True)
    work(lab, F, prs=["MERGED", "MERGED"])
    lab.note(host=F)


def test_the_successor_archives_its_predecessor(lab):
    _handed_over(lab)
    assert hook(arc(lab, F, caller=G)) == (None, "")
    [row] = rows(lab)
    assert (row["decision"], row["case"]) == ("allowed", "predecessor")


def test_a_predecessor_with_a_blocking_child_asks(lab):
    _handed_over(lab)
    lab.put(R, parent=F, name="busy")   # not detached: R works under F
    asked(lab, arc(lab, F, caller=G), f"{F} has 1 child session(s) neither archived nor detached")


def test_a_predecessor_still_running_asks(lab):
    _handed_over(lab)
    lab.turn(F, "running")
    asked(lab, arc(lab, F, caller=G), f"{F} is running, not finished")


def test_only_its_coordinator_successor_archives_the_predecessor(lab):
    _handed_over(lab)
    lab.put(R, parent=F, name="busy", detached=True)
    lab.turn(R, "idle")
    asked(lab, arc(lab, F, caller=R), f"this session is not {F}'s successor")
    lab.put(G, parent=F, name="coordinator-g", detached=False)   # G not detached yet
    asked(lab, arc(lab, F, caller=G), f"this session is not {F}'s successor")


def test_a_predecessor_that_is_no_coordinator_asks(lab, monkeypatch):
    q = "local_45454545-0000-4000-8000-454545454545"
    monkeypatch.setitem(CLI, q, "45454545-cli0-4000-8000-000000000000")
    lab.put(q, parent=K, name="coordinator-q", detached=True)
    lab.turn(q, "idle")
    work(lab, K)
    asked(lab, arc(lab, K, caller=q), f"{K}, which started this session, is not a Brain coordinator")


def test_the_grand_predecessor_is_no_predecessor(lab):
    """E started F, which started G: G archives F, never E."""
    lab.put(E, name="coordinator-e", title="Coordination du Brain — coordinateur E")   # not archived here
    work(lab, E)
    asked(lab, arc(lab, E, caller=G), f"{E} was not started by this session, nor is it the coordinator")


# --- failing closed ---

def test_a_pass_the_ledger_does_not_take_asks(lab, monkeypatch):
    work(lab, K)
    monkeypatch.setenv("BRAIN_CAPTURE", "0")
    asked(lab, arc(lab, K), "the pass could not be logged in the guards ledger")


def test_an_error_in_the_archive_case_asks(lab, monkeypatch):
    work(lab, K)

    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(guards, "archive", broken)
    asked(lab, arc(lab, K), "the session tree, the session's work or the ledger could not be read")


def test_an_error_of_the_whole_guard_asks(lab, monkeypatch):
    work(lab, K)

    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(guards, "refusals", broken)
    decision, reason = hook(arc(lab, K))
    assert decision == "ask" and "the guard failed, so the card asks" in reason


def test_no_app_files_ask(lab, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nowhere"))
    asked(lab, arc(lab, K), "the desktop app's session files are not on this machine")


def test_another_servers_archive_is_not_this_guards(lab):
    work(lab, X)
    p = arc(lab, X)
    p["tool_name"] = "mcp__other__archive_session"
    assert hook(p) == (None, "") and rows(lab) == []


def test_remote_control_outside_its_cases_is_still_refused(lab):
    """The allow rule for set_remote_control changes nothing for the guard: outside the three cases it denies."""
    reason = decide(call(lab, R, False))
    assert reason and "none of the three exceptions" in reason and "No override" in reason


# --- guard.sh with no Python that imports brain ---

@pytest.mark.parametrize("tool,decision", [(ARCHIVE, "ask"), (RC, "deny"),
                                           ("mcp__x__set_session_permission_mode", "deny"),
                                           ("mcp__other__archive_session", None)])
def test_guard_sh_fails_closed_for_the_session_tools(tmp_path, tool, decision):
    from test_capture import _bash
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    env = {k: v for k, v in os.environ.items() if k != "BRAIN_PYTHON"}
    env.update(BRAIN_HOME=str(tmp_path / "home"), BRAIN_SELFTIME="0", PATH=str(tmp_path / "no-python"))
    p = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": tool,
         "tool_input": {"session_id": K, "enabled": True}}
    out = subprocess.run([sh, str(PLUGIN / "hooks" / "guard.sh"), "tool"], input=json.dumps(p), capture_output=True,
                         text=True, env=env, timeout=60)
    assert out.returncode == 0
    if decision is None:
        assert out.stdout == ""
        return
    hso = json.loads(out.stdout)["hookSpecificOutput"]
    assert hso["permissionDecision"] == decision and "the guards cannot run" in hso["permissionDecisionReason"]


def test_hooks_json_sends_archive_session_to_the_guard():
    pre = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    import re
    [m] = [m for m in pre if "archive_session" in m["matcher"]]
    rx = re.compile(m["matcher"])
    assert m["hooks"][0]["command"].endswith("guard.sh\" tool")
    assert rx.search(ARCHIVE) and rx.search(RC) and not rx.search("mcp__ccd_session_mgmt__unarchive_session")
    assert guards.ARCHIVE_TOOL.match(ARCHIVE) and not guards.ARCHIVE_TOOL.match("mcp__other__archive_session")


# --- the allow rules ---

@pytest.mark.parametrize("rule,category", [
    ("mcp__ccd_session_mgmt__set_remote_control", ""),
    ("mcp__ccd_session_mgmt__archive_session", ""),
    ("mcp__other__set_remote_control", "security-settings"),
    ("mcp__ccd_session_mgmt__set_remote_control*", "security-settings"),
    ("mcp__ccd_session_mgmt__set_session_permission_mode", "security-settings"),
    ("mcp__ccd_session_mgmt__*", ""),   # names no category: broad() is what refuses a wildcard tool (below)
])
def test_only_the_exact_remote_control_rule_is_guard_bounded(rule, category):
    cats, _ = permissions.categories({})
    assert permissions.never_rule(rule, cats) == category
    assert permissions.never_category(rule, cats) == ("security-settings" if "remote_control" in rule or
                                                      "permission_mode" in rule else "")


def _installed(tmp_path, hooks=None, enabled=True):
    """The core plugin as Claude Code installed it under the test's Claude home: its hooks.json the engine's (or
    ``hooks``), in installed_plugins.json, enabled or not in the user settings."""
    from brain import config
    names = config.claude(config.load())
    key = f"{names['plugin']}@{names['marketplace']}"
    home = permissions.claude_home()
    folder = tmp_path / "plugin-cache" / "abc"
    (folder / "hooks").mkdir(parents=True, exist_ok=True)
    text = (PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8") if hooks is None else json.dumps(hooks)
    (folder / "hooks" / "hooks.json").write_text(text, encoding="utf-8")
    (home / "plugins").mkdir(parents=True, exist_ok=True)
    (home / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {key: [{"scope": "user", "installPath": str(folder)}]}}), encoding="utf-8")
    (home / "settings.json").write_text(json.dumps({"enabledPlugins": {key: enabled}}), encoding="utf-8")
    return folder


OLD_MATCHER = "mcp__.*__set_(remote_control|session_permission_mode|setting)"   # 0.6.1's: no archive_session


def _old_hooks(matcher=OLD_MATCHER, managed=False):
    hook = ({"type": "command", "command": "C:/py.exe", "args": ["-I", "hook.py", "guard", "tool"]} if managed else
            {"type": "command", "command": 'bash -p "${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh" tool'})
    return {"hooks": {"PreToolUse": [{"matcher": matcher, "hooks": [hook]}]}}


TWO = ('allow: "mcp__ccd_session_mgmt__set_remote_control"', 'allow: "mcp__ccd_session_mgmt__archive_session"')


def _user(model):
    """(the allow rules of the session tools the user scope renders, those it takes out), the engine's left aside."""
    ctx = permissions.context(model, "", "BOX1")
    wanted = permissions.wanted(model, ctx, "user")["allow"]
    gone = permissions.expired_rules(model, ctx, "user")["allow"]
    return [r for r in wanted if r.startswith("mcp__")], [r for r in gone if r.startswith("mcp__")]


def test_the_two_allow_rules_pass_the_permissions_check_where_the_guard_sees_them(tmp_path, monkeypatch):
    from test_permissions import _brain, _rules
    _brain(tmp_path, monkeypatch, _rules(*TWO))
    _installed(tmp_path)
    assert permissions.check() == []
    allow, gone = _user(permissions.load())
    assert {RC, ARCHIVE} <= set(allow) and gone == []
    _brain(tmp_path / "b", monkeypatch, _rules('allow: "mcp__ccd_session_mgmt__set_session_permission_mode"'))
    assert any("falls in security-settings" in e for e in permissions.check())


def test_a_rule_no_installed_guard_sees_is_withheld_and_taken_out(tmp_path, monkeypatch):
    """F3: an installed plugin older than the engine (0.6.1's matcher) sends no archive_session to the guard."""
    from test_permissions import _brain, _rules
    _brain(tmp_path, monkeypatch, _rules(*TWO))
    _installed(tmp_path, _old_hooks())
    [err] = permissions.check()
    assert f"allow {ARCHIVE} is withheld on this machine" in err and "sends " + ARCHIVE + " to no guard" in err
    allow, gone = _user(permissions.load())
    assert RC in allow and ARCHIVE not in allow and gone == [ARCHIVE]   # install.ps1 -Apply takes it out


@pytest.mark.parametrize("how", ["absent", "disabled", "unreadable", "not-the-guard"])
def test_a_plugin_that_cannot_be_read_withholds_both(tmp_path, monkeypatch, how):
    from test_permissions import _brain, _rules
    _brain(tmp_path, monkeypatch, _rules(*TWO))
    if how != "absent":
        folder = _installed(tmp_path, enabled=how != "disabled")
        if how == "unreadable":
            (folder / "hooks" / "hooks.json").write_text("{", encoding="utf-8")
        if how == "not-the-guard":
            hooks = _old_hooks(".*")
            hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/governor.sh"'
            (folder / "hooks" / "hooks.json").write_text(json.dumps(hooks), encoding="utf-8")
    errors = permissions.check()
    assert len(errors) == 2 and all("is withheld on this machine" in e for e in errors), errors
    assert _user(permissions.load()) == ([], [RC, ARCHIVE])


def _lock(managed_hooks):
    from brain import floor
    managed = floor.managed_file()
    managed.parent.mkdir(parents=True, exist_ok=True)
    if managed_hooks is not None:
        managed.write_text(json.dumps(managed_hooks), encoding="utf-8")
    floor.lock_dir().mkdir(parents=True, exist_ok=True)
    (floor.lock_dir() / floor.LOCK_FILE).write_text(json.dumps({"format": floor.LOCK_FORMAT, "managed": str(managed)}),
                                                    encoding="utf-8")


def test_a_locked_floor_reads_its_managed_hooks_alone(tmp_path, monkeypatch):
    """F3: a locked floor's managed hooks, written before the guard knew archive_session, hold it back even with the
    plugin up to date (allowManagedHooksOnly: the plugin's hooks do not run); brain floor lock --apply lets it through."""
    from brain import floorlock
    from test_permissions import _brain, _rules
    _brain(tmp_path, monkeypatch, _rules(*TWO))
    _installed(tmp_path)
    _lock(_old_hooks(managed=True))
    [err] = permissions.check()
    assert f"allow {ARCHIVE} is withheld" in err and "brain floor lock --apply" in err
    assert _user(permissions.load()) == ([RC], [ARCHIVE])
    _lock(floorlock.hooks_settings(tmp_path / "py.exe", tmp_path / "guard"))   # the managed hooks of this engine
    assert permissions.check() == [] and _user(permissions.load()) == ([RC, ARCHIVE], [])
    _lock(None)
    from brain import floor
    floor.managed_file().unlink()
    assert len(permissions.check()) == 2   # the managed file gone: nothing seen
    (floor.lock_dir() / floor.LOCK_FILE).write_text("{", encoding="utf-8")
    assert all("the floor lock cannot be read" in e for e in permissions.check())


@pytest.mark.parametrize("rule,tools", [(RC, [RC]), (ARCHIVE, [ARCHIVE]), ("mcp__ccd_session_mgmt", [RC, ARCHIVE]),
                                        ("mcp__ccd_session_mgmt__*", [RC, ARCHIVE]), ("mcp__ccd_session_mgmt__set_*", [RC]),
                                        ("mcp__other__archive_session", []), ("Bash(echo *)", []),
                                        (ARCHIVE + "(*)", [ARCHIVE]), ("mcp__ccd_session_mgmt(*)", [RC, ARCHIVE])])
def test_every_rule_that_lets_the_tools_through_waits_on_the_guard(rule, tools):
    assert permissions.guard_covers(rule) == tools


def test_the_render_for_install_says_what_it_withholds(tmp_path, monkeypatch, capsys):
    from brain import cli
    from test_permissions import _brain, _rules
    root = _brain(tmp_path, monkeypatch, _rules(*TWO))
    _installed(tmp_path, _old_hooks())
    assert cli.main(["--root", str(root), "permissions", "render", "--level", "user", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert ARCHIVE not in out["allow"] and out["expired"]["allow"] == [ARCHIVE] and out["errors"] == []
    assert len(out["withheld"]) == 1 and ARCHIVE in out["withheld"][0]
    assert cli.main(["--root", str(root), "permissions", "check"]) == 1
    assert "is withheld on this machine" in capsys.readouterr().out


@pytest.mark.parametrize("how", ["no-hooks", "project-only", "managed-off", "managed-only"])
def test_hooks_off_or_a_project_install_withholds_both(tmp_path, monkeypatch, how):
    from brain import floor
    from test_permissions import _brain, _rules
    _brain(tmp_path, monkeypatch, _rules(*TWO))
    _installed(tmp_path)
    home = permissions.claude_home()
    if how.startswith("managed"):   # no floor lock: Claude Code's managed settings still say
        floor.managed_dir().mkdir(parents=True, exist_ok=True)
        key = "disableAllHooks" if how == "managed-off" else "allowManagedHooksOnly"
        (floor.managed_dir() / "managed-settings.json").write_text(json.dumps({key: True}), encoding="utf-8")
    elif how == "no-hooks":
        data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        (home / "settings.json").write_text(json.dumps({**data, "disableAllHooks": True}), encoding="utf-8")
    else:
        f = home / "plugins" / "installed_plugins.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        for entries in data["plugins"].values():
            entries[0].update(scope="project", projectPath="C:/elsewhere")
        f.write_text(json.dumps(data), encoding="utf-8")
    assert len(permissions.check()) == 2


@pytest.mark.parametrize("level", ["project: mine", "tenant: acme", "session: review"])
def test_a_project_s_shared_settings_never_hold_them(tmp_path, monkeypatch, level):
    """A project's settings are committed and read by every machine, whose guard may not see the tool: refused."""
    from test_permissions import _brain, _rules
    _brain(tmp_path, monkeypatch, _rules(f'allow: "{ARCHIVE}", {level}'))
    _installed(tmp_path)
    assert any("only the user levels" in e for e in permissions.load().errors)


def test_another_machines_rule_is_not_this_ones_to_withhold(tmp_path, monkeypatch, capsys):
    from brain import cli
    from test_permissions import _brain, _rules
    root = _brain(tmp_path, monkeypatch, _rules(f'allow: "{ARCHIVE}", machine: BOX2'))
    assert permissions.load().errors == [] and permissions.check() == []   # BOX2's rule is never rendered on BOX1
    assert cli.main(["--root", str(root), "permissions", "render", "--level", "user", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["withheld"] == []
    _brain(tmp_path / "b", monkeypatch, _rules(f'allow: "{ARCHIVE}", machine: BOX1'))
    assert len(permissions.check()) == 1   # this machine's own is


def test_the_doctor_warns_of_a_withheld_rule(tmp_path, monkeypatch):
    from brain import tiers
    from test_permissions import _brain, _rules
    root = _brain(tmp_path, monkeypatch, _rules(*TWO))
    assert len(tiers._unguarded(root)) == 2
    _installed(tmp_path)
    assert tiers._unguarded(root) == []


# --- sessions.app_work ---

def test_app_work_reads_only_the_prs_and_the_folder(lab):
    work(lab, K, prs=["merged", {"prNumber": 2}], cwd="C:/x", title="secret text")
    assert sessions.app_work(K) == {"prs": [("acme/x", "10", "MERGED"), ("", "2", "")], "cwd": "C:/x",
                                    "folders": ["C:/x"]}
    work(lab, K, cwd="C:/x", worktreePath="D:/wt")
    assert sessions.app_work(K)["folders"] == ["C:/x", "D:/wt"]
    assert sessions.app_work("local_77777777-0000-4000-8000-777777777777") is None


def test_the_predecessor_needs_its_hand_over_note(lab):
    _handed_over(lab)
    note = lab.note(host=F, age_s=7 * 3600)   # too old: no note counts
    assert note.is_file()
    asked(lab, arc(lab, F, caller=G), f"no hand-over note of {F}")


def _repo(tmp_path, name="wt"):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text(".env\n__pycache__/\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-qm", "a")
    return repo


def test_what_git_ignores_but_caches_asks(lab, tmp_path):
    repo = _repo(tmp_path)
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_bytes(b"0")
    work(lab, K, cwd=str(repo))
    assert hook(arc(lab, K)) == (None, "")   # a cache goes with the worktree
    (repo / ".env").write_text("A=1", encoding="utf-8")
    asked(lab, arc(lab, K), "1 path(s) git ignores that the archive would remove with its worktree: .env")


def test_a_folder_inside_another_checkout_asks(lab, tmp_path):
    repo = _repo(tmp_path)
    sub = repo / "sub"
    sub.mkdir()
    work(lab, K, cwd=str(sub))
    asked(lab, arc(lab, K), f"{sub} is not the top of a checkout git can read")


def test_the_worktree_the_app_removes_is_checked_too(lab, tmp_path):
    repo = _repo(tmp_path)
    (repo / "new.txt").write_text("x", encoding="utf-8")
    work(lab, K, worktreePath=str(repo))   # cwd gone, the worktree dirty
    asked(lab, arc(lab, K), f"{repo} has 1 uncommitted change(s)")


def test_the_hook_outlives_its_git_calls():
    pre = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    [m] = [m for m in pre if "archive_session" in m["matcher"]]
    assert m["hooks"][0]["timeout"] >= 30 and guards.GIT_TOTAL_S <= m["hooks"][0]["timeout"] / 2
    assert 5 * guards.GIT_S <= guards.GIT_TOTAL_S   # one folder's five calls (config, top, gitlinks, status, ignored)


def test_every_folders_git_calls_share_one_deadline(lab, tmp_path, monkeypatch):
    """Two folders (cwd and worktreePath) make ten git calls: they share GIT_TOTAL_S, and past it the card asks."""
    import time
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    work(lab, K, cwd=str(a), worktreePath=str(b))
    assert hook(arc(lab, K)) == (None, "")
    seen = []
    real = guards._git_timeout

    def spy(deadline):
        seen.append(deadline)
        return real(deadline)
    monkeypatch.setattr(guards, "_git_timeout", spy)
    assert hook(arc(lab, K)) == (None, "") and len(seen) == 10 and len(set(seen)) == 1
    with pytest.raises(subprocess.TimeoutExpired):
        real(time.monotonic() - 1)
    assert 0 < real(time.monotonic() + 1) <= 1 and real(None) == guards.GIT_S
    monkeypatch.setattr(guards, "GIT_TOTAL_S", 0)
    monkeypatch.setattr(guards, "_git_timeout", real)
    asked(lab, arc(lab, K), "git cannot read the config of")


# --- F5: no program of the target repo runs ---

def test_a_filter_the_target_repo_declares_asks_and_never_runs(lab, tmp_path):
    repo = _repo(tmp_path)
    marker = tmp_path / "ran.txt"
    script = tmp_path / "filter.py"
    script.write_text(f"import sys\nopen({str(marker)!r}, 'w').write('x')\nsys.stdout.write(sys.stdin.read())\n",
                      encoding="utf-8")
    (repo / ".gitattributes").write_text("*.txt filter=x\n", encoding="utf-8")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    git(repo, "add", ".gitattributes", "a.txt")
    git(repo, "commit", "-qm", "b")
    import sys
    git(repo, "config", "filter.x.clean", f'"{sys.executable}" "{script}"')
    marker.unlink(missing_ok=True)
    os.utime(repo / "a.txt", (1, 1))   # stat dirty: git status would run the clean filter to compare
    work(lab, K, cwd=str(repo))
    asked(lab, arc(lab, K), f"{repo}'s git config declares filter.x.clean: a program git would run")
    assert not marker.exists()


@pytest.mark.parametrize("key,value", [("include.path", "other.cfg"), ("includeIf.gitdir:/x/.path", "o.cfg")])
def test_an_include_in_the_target_repo_asks(lab, tmp_path, key, value):
    repo = _repo(tmp_path)
    git(repo, "config", key, value)
    work(lab, K, cwd=str(repo))
    asked(lab, arc(lab, K), "'s git config declares include")


def test_submodules_ask(lab, tmp_path):
    repo = _repo(tmp_path)
    (repo / ".gitmodules").write_text("", encoding="utf-8")
    git(repo, "add", ".gitmodules")
    git(repo, "commit", "-qm", "m")
    work(lab, K, cwd=str(repo))
    asked(lab, arc(lab, K), f"{repo} has submodules")


def test_a_nested_repo_without_gitmodules_asks(lab, tmp_path):
    """A gitlink committed without .gitmodules: git status would run git in it, under its own config."""
    repo = _repo(tmp_path)
    nested = _repo(repo, "sub")
    git(repo, "add", "sub")
    git(repo, "commit", "-qm", "n")
    assert not (repo / ".gitmodules").exists()
    work(lab, K, cwd=str(repo))
    asked(lab, arc(lab, K), f"{repo} holds nested repo(s) git status would enter: sub")
    assert nested.is_dir()


def test_the_line_endings_git_reads_are_kept(tmp_path):
    repo = _repo(tmp_path)
    git(repo, "config", "core.autocrlf", "input")
    assert guards._git_runs_why(str(repo), guards._git_env()) == ("", ("-c", "core.autocrlf=input"))
    git(repo, "config", "core.eol", "x; rm")   # not a value git takes: not carried
    assert guards._git_runs_why(str(repo), guards._git_env())[1] == ("-c", "core.autocrlf=input")


def test_git_runs_without_the_hooks_variables_nor_the_system_and_global_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'filter.x.clean'='evil'")
    env = guards._git_env()
    assert "GIT_DIR" not in env and "GIT_CONFIG_PARAMETERS" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert f"core.hooksPath={os.devnull}" in guards.GIT_SAFE and "core.fsmonitor=false" in guards.GIT_SAFE


def test_a_clean_repo_still_passes_under_the_safe_git(lab, tmp_path):
    repo = _repo(tmp_path)
    work(lab, K, cwd=str(repo))
    assert hook(arc(lab, K)) == (None, "")


# --- F7: what a session writes is no confirmation ---

def test_a_forged_cache_hides_no_child(lab, monkeypatch):
    """The guard parses the app's files now, never the index's cache (a session could write it to hide a child)."""
    work(lab, K, prs=["MERGED"])
    z = "local_99999999-0000-4000-8000-999999999999"
    lab.put(z, parent=K, name="w", cli="cli-z")   # neither archived nor detached: blocking
    sessions.app_index()   # writes the cache
    cache = sessions.app_cache()
    data = json.loads(cache.read_text(encoding="utf-8"))
    for v in data.values():
        if v["meta"].get("host_id") == z:
            v["meta"].pop("parent", None)   # forged: z no longer K's child, its stat unchanged
    cache.write_text(json.dumps(data), encoding="utf-8")
    assert (sessions.app_index() or {})[z].get("parent") is None   # the cache's readers are fooled
    assert sessions.app_index(cached=False)[z]["parent"] == K
    asked(lab, arc(lab, K), f"{K} has 1 child session(s) neither archived nor detached")


@pytest.mark.parametrize("where", ["file", "folder", "account", "cache"])
def test_a_session_writes_no_app_file(lab, where):
    app = next((lab.cwd / "appdata").rglob(f"{K}.json"))
    target = {"file": app, "folder": app.parent / "new.json", "account": app.parents[3],   # the folder itself
              "cache": sessions.app_cache()}[where]
    for reason in (decide(payload("Write", lab.cwd, file_path=str(target), content="{}")),
                   decide(payload("Edit", lab.cwd, file_path=str(target), old_string="a", new_string="b")),
                   bash(lab.cwd, f"echo '{{}}' > '{target.as_posix()}'"),
                   bash(lab.cwd, f"cp /tmp/x.json '{target.as_posix()}'")):
        assert reason and "the desktop app" in reason and "session files" in reason, (where, reason)
    if os.name == "nt":
        assert "session files" in (pwsh(lab.cwd, f"Set-Content -Path '{target}' -Value x") or "")
    assert bash(lab.cwd, f"cat '{target.as_posix()}'") is None   # reading is no write


def test_a_session_writes_no_transcript_but_its_memory(lab):
    """A transcript's tail says whether a turn is finished (sessions.state_of): a session may not append one."""
    projects = lab.cwd / "claude-config" / "projects" / "E--lab"
    transcript = next(projects.glob("*.jsonl"), projects / "x.jsonl")
    sub = projects / "s1" / "subagents" / "agent-1.jsonl"
    for target in (transcript, sub):
        assert "session files" in (bash(lab.cwd, f"echo '{{}}' >> '{target.as_posix()}'") or ""), target
        assert "session files" in (decide(payload("Write", lab.cwd, file_path=str(target), content="{}")) or "")
    memory = projects / "memory" / "note.md"
    assert decide(payload("Write", lab.cwd, file_path=str(memory), content="m")) is None


def test_a_hard_link_to_an_app_file_is_one(lab, tmp_path):
    app = next((lab.cwd / "appdata").rglob(f"{K}.json"))
    link = tmp_path / "h.json"
    os.link(app, link)
    assert "session files" in (bash(lab.cwd, f"echo '{{}}' > '{link.as_posix()}'") or "")
    sub = lab.cwd / "claude-config" / "projects" / "E--lab" / "s1" / "subagents" / "agent-1.jsonl"
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text("{}\n", encoding="utf-8")
    os.link(sub, tmp_path / "t.txt")   # a subagent's transcript, under another name
    assert "session files" in (bash(lab.cwd, f"echo '{{}}' >> '{(tmp_path / 't.txt').as_posix()}'") or "")
    other = tmp_path / "plain.json"
    other.write_text("{}", encoding="utf-8")
    assert bash(lab.cwd, f"echo '{{}}' > '{other.as_posix()}'") is None


def test_the_notes_folder_beside_the_app_files_stays_writable(lab):
    notes = lab.cwd / "appdata" / "Claude-Data" / "claude_t" / "side-session-notes" / "local_x" / "note.md"
    assert decide(payload("Write", lab.cwd, file_path=str(notes), content="n")) is None


# --- round 2 of the review: folders copied in, a new account, the plugin disabled, brain check ---

def test_a_folder_copied_where_the_guards_read_transcripts_is_refused(lab, tmp_path):
    """A folder copied or moved into the transcripts' folder brings the .jsonl it holds."""
    projects = lab.cwd / "claude-config" / "projects"
    forged = tmp_path / "forged"
    forged.mkdir()
    for target in (projects / "E--forged", projects / "E--lab" / "s9", projects / "E--lab" / "s1" / "subagents",
                   projects / "E--lab" / "s1" / "subagents" / "x", projects):
        assert "session files" in (bash(lab.cwd, f"cp -r '{forged.as_posix()}' '{target.as_posix()}'") or ""), target
        assert "session files" in (bash(lab.cwd, f"mv '{forged.as_posix()}' '{target.as_posix()}'") or ""), target
    for target in (projects / "E--lab" / "memory" / "n.md", projects / "E--lab" / "s1" / "workflows" / "scripts" / "w.js",
                   projects / "E--lab" / "s1" / "tool-results" / "r.txt"):
        assert decide(payload("Write", lab.cwd, file_path=str(target), content="x")) is None, target


def test_a_new_account_folder_under_claude_data_is_refused(lab, tmp_path):
    """The app's glob reads every account's claude-code-sessions: a new account folder copied in would add one."""
    data = lab.cwd / "appdata" / "Claude-Data"
    forged = tmp_path / "acct"
    (forged / "claude-code-sessions").mkdir(parents=True)
    for target in (data / "fakeacc", data / "claude_t", data):
        assert "session files" in (bash(lab.cwd, f"cp -r '{forged.as_posix()}' '{target.as_posix()}'") or ""), target
    assert "session files" in (decide(payload("Write", lab.cwd, file_path=str(data / "new.json"), content="{}")) or "")


@pytest.fixture
def strict(monkeypatch):
    from brain import gestures
    monkeypatch.setattr(gestures, "strict", lambda data=None: True)


def test_disabling_the_core_plugin_is_refused_under_owner_strict(lab, strict):
    key = guards._core_key()
    settings = lab.cwd / ".claude" / "settings.local.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"enabledPlugins": {key: True}}), encoding="utf-8")
    edit = decide(payload("Edit", lab.cwd, file_path=str(settings), old_string=f'"{key}": true',
                          new_string=f'"{key}": false'))
    assert edit and "disables the" in edit
    write = decide(payload("Write", lab.cwd, file_path=str(settings),
                           content=json.dumps({"enabledPlugins": {key: False}})))
    assert write and "disables the" in write
    assert decide(payload("Write", lab.cwd, file_path=str(settings),
                          content=json.dumps({"enabledPlugins": {key: True, "other@x": False}}))) is None
    plugin = key.split("@")[0]
    for command in (f"claude plugin disable {plugin} --scope project", f"claude plugin uninstall {key}"):
        assert "disables the" in (bash(lab.cwd, command) or ""), command
    assert bash(lab.cwd, "claude plugin disable other-plugin") is None
    assert "disables the" in (bash(lab.cwd, f"echo '{{\"enabledPlugins\": {{}}}}' > '{settings.as_posix()}'") or "")


def test_disabling_the_core_plugin_passes_without_owner_strict(lab):
    key = guards._core_key()
    settings = lab.cwd / ".claude" / "settings.local.json"
    assert decide(payload("Write", lab.cwd, file_path=str(settings),
                          content=json.dumps({"enabledPlugins": {key: False}}))) is None


def test_brain_check_warns_where_permissions_check_fails(tmp_path, monkeypatch, capsys):
    """A repo's brain check reads the same on every machine: a withheld rule is a warning there, an error of brain
    permissions check (and the render withholds it either way)."""
    from test_permissions import _brain, _rules
    _brain(tmp_path, monkeypatch, _rules(*TWO))
    _installed(tmp_path, _old_hooks())
    assert permissions.check(machine=False) == []
    assert "warning: permissions: permissions.yaml" in capsys.readouterr().out
    assert len(permissions.check()) == 1
