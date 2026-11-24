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
from test_guards import PLUGIN, decide
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
    asked(lab, arc(lab, K), f"{plain} is not a checkout git can read")


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


def test_the_two_allow_rules_pass_the_permissions_check(tmp_path, monkeypatch):
    from test_permissions import _brain, _rules
    _brain(tmp_path, monkeypatch, _rules('allow: "mcp__ccd_session_mgmt__set_remote_control"',
                                         'allow: "mcp__ccd_session_mgmt__archive_session"'))
    assert permissions.check() == []
    _brain(tmp_path / "b", monkeypatch, _rules('allow: "mcp__ccd_session_mgmt__set_session_permission_mode"'))
    assert any("falls in security-settings" in e for e in permissions.check())


# --- sessions.app_work ---

def test_app_work_reads_only_the_prs_and_the_folder(lab):
    work(lab, K, prs=["merged", {"prNumber": 2}], cwd="C:/x", title="secret text")
    assert sessions.app_work(K) == {"prs": [("acme/x", "10", "MERGED"), ("", "2", "")], "cwd": "C:/x"}
    assert sessions.app_work("local_77777777-0000-4000-8000-777777777777") is None
