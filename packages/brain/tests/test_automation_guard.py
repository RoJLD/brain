"""The automation levels enforced (wi-brain-automation-guard, spec-brain-automation-levels S3; docs/automation.md):
brain.automation.enforce's table (manual refused inside the conditions too, ask left to the native rule inside them and
asked outside, auto allowed inside them; ask reads manual in a permission mode with no card, or none given), the guard
hook on archive_session and set_remote_control at each level, the native rules brain permissions render writes for the
app's tools (the highest level of their gestures, the other verdicts taken out, an allow no guard sees withheld), and
the engine clone's pull, which a session does at auto only, through both of its paths (brain refresh, brain release
apply). Each door refuses on both of its paths: the hook's and the render's, refresh's and release apply's."""

import json
from types import SimpleNamespace

import pytest

from brain import automation, engineclone, gestures, guards, permissions, releaseapply
from brain.commands import refresh
from conftest import BRAIN
import test_guards_archive as arclab
import test_guards_remote_control as rclab
from test_guards_archive import ARCHIVE, arc, hook, work
from test_guards_remote_control import G, K, RC, call, rows
from test_engine_clone import clones, git as egit  # noqa: F401 (clones: a fixture)

lab = rclab.lab   # the invented sessions of test_guards_remote_control

SESSION_GESTURES = ("session-archive", "handover-remote-control")


def set_levels(tmp_path, monkeypatch, **levels) -> None:
    """The tests' config.json (Ada's) with an automation section of ``levels`` (underscores read as hyphens), read as
    the config.json found without BRAIN_CONFIG (so that it may raise a level, as the owner's merge does)."""
    data = json.loads(BRAIN.read_text(encoding="utf-8"))
    data["automation"] = {"v": 1, "levels": {k.replace("_", "-"): v for k, v in levels.items()}}
    f = tmp_path / "config-levels.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    monkeypatch.setattr(automation, "anchor_config", lambda cfg: None)


def resolved(level: str, source: str = "config") -> automation.Resolved:
    return automation.Resolved("session-archive", level, source, ())


# --- the table ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("level,inside,mode,decision", [
    ("manual", True, "default", "deny"), ("manual", False, "auto", "deny"),
    ("manual", True, "bypassPermissions", "deny"),
    ("ask", True, "default", ""), ("ask", True, "auto", ""), ("ask", True, "acceptEdits", ""),
    ("ask", False, "default", "ask"), ("ask", False, "auto", "ask"), ("ask", False, "plan", "ask"),
    ("ask", True, "bypassPermissions", "deny"), ("ask", False, "dontAsk", "deny"),
    ("ask", True, None, "deny"), ("ask", False, "a-mode-of-later", "deny"), ("ask", True, 3, "deny"),
    ("auto", True, "default", "allow"), ("auto", True, "bypassPermissions", "allow"), ("auto", True, None, "allow"),
    ("auto", False, "auto", "ask"), ("auto", False, "dontAsk", "deny"), ("auto", False, None, "deny"),
])
def test_the_table_of_levels_conditions_and_modes(level, inside, mode, decision):
    got = automation.enforce("session-archive", inside, mode, resolved(level))
    assert got.decision == decision, got.why
    assert got.level == ("manual" if decision == "deny" else level)
    assert "brain automation explain session-archive" in got.why and "\n" not in got.why


def test_a_level_the_engine_cannot_read_is_manual(monkeypatch):
    def boom(*a, **kw):
        raise OSError("the disk is gone")
    monkeypatch.setattr(automation, "layers", boom)
    r = automation.one("session-archive")
    assert (r.level, r.source) == ("manual", "error") and "the disk is gone" in r.steps[0]
    assert automation.enforce("session-archive", True, "default").decision == "deny"
    assert automation.one("no-such-gesture").level == "manual"
    assert automation.enforce("session-archive", True, "default", resolved("not-a-level")).decision == "deny"


def test_the_engines_defaults_keep_todays_behaviour(lab):
    """No automation section: archive and Remote Control at ask, so the guard keeps quiet inside the conditions (the
    owner's native rule decides, as before) and asks or refuses outside them; the clone's pull at auto."""
    levels = {g: automation.one(g).level for g in (*SESSION_GESTURES, engineclone.GESTURE)}
    assert levels == {"session-archive": "ask", "handover-remote-control": "ask", "engine-clone-pull": "auto"}
    work(lab, K, prs=["MERGED"])
    assert hook(arc(lab, K)) == (None, "")
    assert [(r["decision"], r["level"]) for r in rows(lab)] == [("allowed", "ask")]


# --- archive_session ----------------------------------------------------------------------------------------------

def test_archive_at_auto_is_allowed_inside_and_asked_outside(lab, tmp_path, monkeypatch):
    set_levels(tmp_path, monkeypatch, session_archive="auto")
    work(lab, K, prs=["MERGED"])
    decision, reason = hook(arc(lab, K))
    assert decision == "allow" and "session-archive is at level auto (config" in reason and "no card" in reason
    work(lab, K, prs=["OPEN"])
    arclab.asked(lab, arc(lab, K), "neither merged nor closed")   # the conditions never change with the level
    assert [(r["decision"], r.get("case"), r["level"]) for r in rows(lab)] == [("allowed", "child", "auto"),
                                                                                ("asked", "outside", "auto")]


@pytest.mark.parametrize("prs", [["MERGED"], ["OPEN"]])
def test_archive_at_manual_is_refused_inside_the_conditions_too(lab, tmp_path, monkeypatch, prs):
    set_levels(tmp_path, monkeypatch, session_archive="manual")
    work(lab, K, prs=prs)
    decision, reason = hook(arc(lab, K))
    assert decision == "deny", reason
    assert "session-archive is at level manual" in reason and "props.external_blocker" in reason
    [row] = rows(lab)
    assert (row["decision"], row["check"], row["level"]) == ("denied", "session-archive", "manual")
    assert row["case"] == ("child" if prs == ["MERGED"] else "outside")


def test_a_machine_file_lowers_the_archive_to_manual(lab, tmp_path, monkeypatch):
    set_levels(tmp_path, monkeypatch, session_archive="auto")
    (lab.home / "automation.json").parent.mkdir(parents=True, exist_ok=True)
    (lab.home / "automation.json").write_text(json.dumps({"v": 1, "levels": {"session-archive": "manual"}}),
                                              encoding="utf-8")
    work(lab, K, prs=["MERGED"])
    assert hook(arc(lab, K))[0] == "deny"


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk", None, "a-mode-of-later"])
def test_archive_at_ask_reads_manual_where_an_ask_shows_no_card(lab, mode):
    work(lab, K, prs=["MERGED"])
    decision, reason = hook(call(lab, K, None, tool=ARCHIVE, perm=mode, reason="PR merged"))
    assert decision == "deny", reason
    assert "shows no card for an ask: it reads manual" in reason
    work(lab, K, prs=["OPEN"])   # outside the conditions: the guard's own ask has no card either
    assert hook(call(lab, K, None, tool=ARCHIVE, perm=mode, reason="PR merged"))[0] == "deny"


def test_archive_at_auto_needs_no_card_whatever_the_mode(lab, tmp_path, monkeypatch):
    set_levels(tmp_path, monkeypatch, session_archive="auto")
    work(lab, K, prs=["MERGED"])
    for mode in ("bypassPermissions", "dontAsk", None):
        assert hook(call(lab, K, None, tool=ARCHIVE, perm=mode, reason="x"))[0] == "allow"


def test_a_permission_mode_is_quoted_on_one_line(lab):
    """The payload's permission_mode is the caller's text: quoted and cut in the reason, which stays one JSON line."""
    work(lab, K, prs=["MERGED"])
    weird = 'by"pass\nmode %PATH% $HOME &amp; <x>'
    decision, reason = hook(call(lab, K, None, tool=ARCHIVE, perm=weird, reason="x"))
    assert decision == "deny" and "\n" not in reason and json.dumps(weird)[:40] in reason


def test_a_pass_the_ledger_does_not_take_is_no_allow(lab, tmp_path, monkeypatch):
    set_levels(tmp_path, monkeypatch, session_archive="auto")
    work(lab, K, prs=["MERGED"])
    monkeypatch.setattr(guards, "_record", lambda *a, **kw: False)
    arclab.asked(lab, arc(lab, K), "the pass could not be logged in the guards ledger")


# --- set_remote_control -------------------------------------------------------------------------------------------

def test_a_hand_over_at_auto_is_allowed_and_at_manual_refused(lab, tmp_path, monkeypatch):
    lab.note()
    set_levels(tmp_path, monkeypatch, handover_remote_control="auto")
    decision, reason = hook(call(lab, G, True))
    assert decision == "allow" and "handover-remote-control is at level auto" in reason
    set_levels(tmp_path, monkeypatch, handover_remote_control="manual")
    decision, reason = hook(call(lab, G, True))
    assert decision == "deny" and "handover-remote-control is at level manual" in reason
    assert [(r["decision"], r["case"], r["level"]) for r in rows(lab)] == [("allowed", "handover-on", "auto"),
                                                                            ("denied", "handover-on", "manual")]


def test_the_off_before_an_archive_follows_the_archives_level(lab, tmp_path, monkeypatch):
    set_levels(tmp_path, monkeypatch, session_archive="manual", handover_remote_control="auto")
    decision, reason = hook(call(lab, K, False))
    assert decision == "deny" and "session-archive is at level manual" in reason
    set_levels(tmp_path, monkeypatch, session_archive="auto", handover_remote_control="manual")
    assert hook(call(lab, K, False))[0] == "allow"


def test_remote_control_outside_its_cases_stays_refused_at_auto(lab, tmp_path, monkeypatch):
    set_levels(tmp_path, monkeypatch, session_archive="auto", handover_remote_control="auto")
    rclab.refused(lab, call(lab, G, True), "no hand-over note")   # no note: no hand-over, the floor's
    assert hook(call(lab, K, True))[0] == "deny"                  # on for a child: never


def test_a_hand_over_at_ask_reads_manual_in_bypass_mode(lab):
    lab.note()
    assert hook(call(lab, G, True))[0] is None   # the default, ask, in the default mode: the native rule decides
    decision, reason = hook(call(lab, G, True, perm="bypassPermissions"))
    assert decision == "deny" and "it reads manual" in reason


def test_a_session_cannot_raise_a_level_through_brain_config(lab, tmp_path, monkeypatch):
    """BRAIN_CONFIG names a file a session may write: it only lowers (wi-brain-automation-config's anchor)."""
    data = json.loads(BRAIN.read_text(encoding="utf-8"))
    data["automation"] = {"v": 1, "levels": {"session-archive": "auto"}}
    f = tmp_path / "written-by-a-session.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    work(lab, K, prs=["MERGED"])
    assert hook(arc(lab, K)) == (None, "")   # still ask: quiet, the native rule decides; never allow


# --- the native rules (brain permissions render --level user) ----------------------------------------------------

@pytest.fixture
def seen(monkeypatch):
    """The core plugin's guard sees both tools here (an allow rule for them is not withheld)."""
    monkeypatch.setattr(permissions, "guard_unseen", lambda tool: "")


def test_the_defaults_render_an_ask_rule_for_each_tool(seen):
    want, gone = permissions.automation_rules()
    assert want == {ARCHIVE: "ask", RC: "ask"}
    assert gone == {"deny": [ARCHIVE, RC], "ask": [], "allow": [ARCHIVE, RC]}


def test_each_tool_takes_the_highest_level_of_its_gestures(tmp_path, monkeypatch, seen):
    set_levels(tmp_path, monkeypatch, session_archive="auto", handover_remote_control="manual")
    native = automation.native_rules()
    assert native[ARCHIVE]["verdict"] == "allow" and native[RC] == {
        "level": "auto", "verdict": "allow", "gestures": ["handover-remote-control", "session-archive"]}
    set_levels(tmp_path, monkeypatch, session_archive="manual", handover_remote_control="manual")
    want, gone = permissions.automation_rules()
    assert want == {ARCHIVE: "deny", RC: "deny"} and gone["allow"] == gone["ask"] == [ARCHIVE, RC]


def test_an_allow_no_guard_sees_is_withheld_and_taken_out(tmp_path, monkeypatch):
    set_levels(tmp_path, monkeypatch, session_archive="auto", handover_remote_control="auto")
    monkeypatch.setattr(permissions, "guard_unseen", lambda tool: "no guard here")
    want, gone = permissions.automation_rules()
    assert want == {} and all(gone[v] == [ARCHIVE, RC] for v in permissions.VERDICTS)


def test_the_user_render_holds_them_and_takes_out_the_old_level(tmp_path, monkeypatch, seen):
    model = permissions.load()
    ctx = permissions.context(model)
    want = permissions.wanted(model, ctx, "user")
    assert ARCHIVE in want["ask"] and RC in want["ask"] and ARCHIVE not in want["allow"]
    gone = permissions.expired_rules(model, ctx, "user")
    assert ARCHIVE in gone["allow"] and RC in gone["deny"]
    assert ARCHIVE not in permissions.wanted(model, ctx, "project")["ask"]   # the user scope's alone


def test_install_reads_them_from_the_user_render(tmp_path, monkeypatch, seen, capsys):
    from brain import cli
    from test_permissions import _brain
    root = _brain(tmp_path, monkeypatch)
    set_levels(tmp_path, monkeypatch, session_archive="manual")
    assert cli.main(["--root", str(root), "permissions", "render", "--level", "user", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert ARCHIVE in out["deny"] and RC in out["ask"] and ARCHIVE in out["expired"]["allow"]
    assert out["automation"][ARCHIVE]["level"] == "manual"


def test_explain_says_what_enforces_each_level(tmp_path, monkeypatch, capsys):
    from brain import cli
    set_levels(tmp_path, monkeypatch, session_archive="auto")
    assert cli.main(["automation", "explain", "session-archive"]) == 0
    out = capsys.readouterr().out
    assert "enforced: inside its conditions the guard allows it, no card" in out
    data = automation.explain()
    by = {g["id"]: g["enforced"] for g in data["gestures"]}
    assert by["release-tag"].startswith("refused to a session at every level")
    assert by["vault-open"].startswith("the floor") and by["merge-go"].startswith("the harness")
    assert "pull it in a session" in by["engine-clone-pull"]


# --- the engine clone's pull: brain refresh and brain release apply ----------------------------------------------

@pytest.fixture
def clone(clones):
    """test_engine_clone's remote and clones, with its git helper."""
    return SimpleNamespace(**vars(clones), git=egit)


def engine_brain(tmp_path, monkeypatch, clone, level=None):
    root = tmp_path / "brain"
    root.mkdir(exist_ok=True)
    data = {"v": 1, "engine": {"repo": "ada/engine", "pin": "v1.0.0", "clone": str(clone.clone)}}
    if level:
        data["automation"] = {"v": 1, "levels": {"engine-clone-pull": level}}
    (root / "config.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    (root / "projects.yaml").write_text("{}\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("level", ["ask", "manual"])
def test_a_session_leaves_the_pull_to_the_owner_below_auto_on_both_paths(clone, tmp_path, monkeypatch, capsys,
                                                                         level):
    root = engine_brain(tmp_path, monkeypatch, clone, level)
    monkeypatch.setenv("BRAIN_AGENT_SESSION", "1")
    refresh._clone(SimpleNamespace(offline=False, no_clone=False), root)
    out = capsys.readouterr().out
    assert f"not pulled: engine-clone-pull is at level {level}" in out and "git merge --ff-only" in out
    assert clone.git(clone.clone, "rev-parse", "HEAD") == clone.first
    outcome, said = releaseapply._clone(SimpleNamespace(root=root), {"offline": False})
    assert outcome == "skipped" and "not pulled" in said
    assert clone.git(clone.clone, "rev-parse", "HEAD") == clone.first


def test_the_owners_terminal_pulls_at_every_level(clone, tmp_path, monkeypatch, capsys):
    root = engine_brain(tmp_path, monkeypatch, clone, "manual")
    assert not gestures.agent_session()
    refresh._clone(SimpleNamespace(offline=False, no_clone=False), root)
    assert "main fast-forwarded" in capsys.readouterr().out


def test_a_session_pulls_at_auto(clone, tmp_path, monkeypatch, capsys):
    root = engine_brain(tmp_path, monkeypatch, clone)
    monkeypatch.setenv("BRAIN_AGENT_SESSION", "1")
    refresh._clone(SimpleNamespace(offline=False, no_clone=False), root)
    assert "main fast-forwarded" in capsys.readouterr().out
    assert clone.git(clone.clone, "rev-parse", "HEAD") == clone.last
