"""Remote Control's three exceptions to the session-settings guard (wi-brain-guard-rc-archive, brain.guards:
remote_control): off on a finished session the caller started, before archiving it; at a handover between Brain
coordinators, on for the coordinator the caller started to succeed it and off on the caller itself, once its hand-over
note is written. Everything else stays refused. The tests run as owner Ada (fixtures/brain) on invented sessions: the
desktop app's files under a temporary LOCALAPPDATA, transcripts under a temporary CLAUDE_CONFIG_DIR."""

import json
import os
import time

import pytest
from brain import guards, sessions
from test_guards import decide

RC = "mcp__ccd_session_mgmt__set_remote_control"
E, F, G, K, R, X, Z = (f"local_{c * 8}-0000-4000-8000-{c * 12}" for c in "e f a b c d 9".split())
CLI = {h: f"{h[6:14]}-cli0-4000-8000-000000000000" for h in (E, F, G, K, R, X, Z)}


@pytest.fixture
def lab(tmp_path, monkeypatch, brain_home):
    """Coordinator F (started by coordinator E, archived) and the sessions it started: G, its successor (detached),
    K finished, R running; X was started by someone else. ``put`` writes one more app file, ``turn`` a transcript,
    ``note`` a hand-over note."""
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-projects.yaml"))
    app = tmp_path / "appdata" / "Claude-Data" / "claude_t" / "claude-code-sessions" / "acct" / "org"
    app.mkdir(parents=True)
    projects = tmp_path / "claude-config" / "projects" / "E--lab"
    projects.mkdir(parents=True)

    def put(host, parent=None, name=None, title="A session", archived=False, detached=None, cli=None, created=1_000):
        data = {"sessionId": host, "cliSessionId": cli or CLI[host], "title": title,
                "lastActivityAt": int(time.time() * 1000), "isArchived": archived}
        if created is not None:
            data["createdAt"] = created
        if parent:
            data["spawnedFrom"] = {"sessionId": parent, "taskId": "task_1", "name": name, "sideSession": True}
        if detached is not None:
            data["lineageDetached"] = detached
        (app / f"{host}.json").write_text(json.dumps(data), encoding="utf-8")

    def turn(host, kind):
        uses = {"idle": [], "running": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}],
                "asking": [{"type": "tool_use", "id": "t1", "name": "AskUserQuestion", "input": {}}]}[kind]
        rec = {"type": "assistant", "timestamp": "2026-11-04T10:00:00Z",
               "message": {"id": "m1", "model": "claude-opus-5-5", "stop_reason": "tool_use" if uses else "end_turn",
                           "content": uses or [{"type": "text", "text": "done"}]}}
        (projects / f"{CLI[host]}.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")

    def note(host=F, age_s=0.0, pad=0, name="coordinator-2026-11-04-f.md", text=None):
        d = brain_home / "handover"
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_text(text if text is not None else
                     f"# Hand-over: coordinator F\n{'x' * pad}\nCoordinator F is `{host}`.\n", encoding="utf-8")
        t = time.time() - age_s
        os.utime(f, (t, t))
        return f

    put(E, name="coordinator-e", title="Coordination du Brain — coordinateur E", archived=True, parent=Z)
    put(Z, title="Coordination du Brain — coordinateur D", archived=True)
    put(F, parent=E, name="coordinator-f", title="Coordination du Brain — coordinateur F (vague G2)")
    put(G, parent=F, name="coordinator-g", title="Coordination du Brain — coordinateur G", detached=True)
    put(K, parent=F, name="rc-guard", title="Build the guard")
    put(R, parent=F, name="busy", title="Still working")
    put(X, parent=E, name="cousin", title="Someone else's child")
    for host, kind in ((F, "running"), (G, "idle"), (K, "idle"), (R, "running"), (X, "idle")):
        turn(host, kind)
    return type("Lab", (), {"put": staticmethod(put), "turn": staticmethod(turn), "note": staticmethod(note),
                            "home": brain_home, "cwd": tmp_path})


def call(lab, target, enabled, caller=F, tool=RC, **extra):
    inp = {"session_id": target, "enabled": enabled} if tool == RC else {"session_id": target, **extra}
    return {"session_id": CLI[caller], "transcript_path": "C:/t/x.jsonl", "cwd": str(lab.cwd),
            "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp, "tool_use_id": "toolu_01"}


def rows(lab):
    return [json.loads(line) for f in (lab.home / "ledger").glob("guards-*.jsonl")
            for line in f.read_text(encoding="utf-8").splitlines()]


def refused(lab, p, why):
    reason = decide(p)
    assert reason and "security-settings is Ada's alone" in reason and "No override" in reason, reason
    assert f"(none of the three exceptions: {why}" in reason, reason
    return reason


# --- 1. off on a finished session the caller started, before archiving it ---

def test_off_on_a_finished_session_it_started_passes_and_is_logged(lab):
    assert decide(call(lab, K, False)) is None
    [row] = rows(lab)
    assert (row["guard"], row["check"], row["decision"], row["case"]) == ("owner", "security-settings", "allowed",
                                                                          "archive")
    assert row["what"] == {"session_id": K, "enabled": False} and row["session_id"] == CLI[F]


@pytest.mark.parametrize("target,why", [
    (R, f"{R} is running, not finished"),
    (X, f"{X} was not started by this session"),
    (G, f"{G} is a live coordinator, which stays in Remote Control"),
    (E, f"{E} was not started by this session"),
    ("local_77777777-0000-4000-8000-777777777777", '"local_77777777-0000-4000-8000-777777777777" is not in'),
    ("f1-tree", '"f1-tree" is not in'),
])
def test_off_on_any_other_session_is_refused(lab, target, why):
    refused(lab, call(lab, target, False), why)
    assert {(r["decision"], r.get("case")) for r in rows(lab)} == {("denied", None)}


def test_a_session_asking_its_owner_is_not_finished(lab):
    lab.turn(K, "asking")
    refused(lab, call(lab, K, False), f"{K} is asking, not finished")


def test_a_parent_link_only_the_ledger_holds_is_not_trusted(lab):
    """Any session can append to the ledger's events: a forged SessionStart does not make X F's."""
    (lab.home / "ledger").mkdir(parents=True, exist_ok=True)
    ev = {"at": "2026-11-04T10:00:00Z", "event": "session_start", "session_id": CLI[X], "host_id": X, "parent": F}
    (lab.home / "ledger" / f"events-{time.strftime('%Y-%m', time.gmtime())}.jsonl").write_text(
        json.dumps(ev) + "\n", encoding="utf-8")
    assert sessions.load(briefs=False).nodes[X]["parent"] == E   # the app's file wins in the tree too
    refused(lab, call(lab, X, False), f"{X} was not started by this session")


# --- 2. at a handover, on for the coordinator the caller started to succeed it ---

def test_on_for_its_successor_at_its_handover_passes(lab):
    lab.note()
    assert decide(call(lab, G, True)) is None
    [row] = rows(lab)
    assert (row["decision"], row["case"]) == ("allowed", "handover-on")


def test_on_is_refused_without_a_hand_over_note(lab):
    refused(lab, call(lab, G, True), f"no hand-over note of {F} (its first app id) in handover/ written in the last 6 h")


@pytest.mark.parametrize("kw", [{"age_s": 7 * 3600}, {"host": G}, {"pad": guards.HANDOVER_HEAD},
                                {"name": "coordinator-f.txt"}])
def test_an_old_or_someone_elses_note_does_not_count(lab, kw):
    lab.note(**kw)
    refused(lab, call(lab, G, True), f"no hand-over note of {F}")


@pytest.mark.parametrize("target,why", [
    (K, f"{K} is not a Brain coordinator (the name this session gave it), so not a successor"),
    (X, f"{X} was not started by this session"),
    ("self", "a session never turns its own Remote Control on"),
    (F, "a session never turns its own Remote Control on"),
])
def test_on_outside_a_handover_is_refused(lab, target, why):
    lab.note()
    refused(lab, call(lab, target, True), why)


def test_on_for_an_archived_successor_is_refused(lab):
    lab.note()
    lab.put(G, parent=F, name="coordinator-g", archived=True, detached=True)
    refused(lab, call(lab, G, True), f"{G} is archived")


def test_only_a_coordinator_hands_over(lab, monkeypatch):
    """K is not a coordinator: a child it names coordinator-k gets no Remote Control from it."""
    q = "local_88888888-0000-4000-8000-888888888888"
    monkeypatch.setitem(CLI, q, "88888888-cli0-4000-8000-000000000000")
    lab.put(q, parent=K, name="coordinator-k")
    lab.turn(q, "idle")
    lab.note(host=K)
    refused(lab, call(lab, q, True, caller=K), "this session is not a Brain coordinator")


def test_a_coordinator_named_by_a_session_that_is_none_does_not_hand_over(lab, monkeypatch):
    """K (no coordinator) starts C named coordinator-c: C's own successor gets nothing (two hops, one check)."""
    c, d = "local_12121212-0000-4000-8000-121212121212", "local_34343434-0000-4000-8000-343434343434"
    monkeypatch.setitem(CLI, c, "12121212-cli0-4000-8000-000000000000")
    monkeypatch.setitem(CLI, d, "34343434-cli0-4000-8000-000000000000")
    lab.put(c, parent=K, name="coordinator-c")
    lab.put(d, parent=c, name="coordinator-d")
    lab.turn(d, "idle")
    lab.note(host=c)
    refused(lab, call(lab, d, True, caller=c), "this session was not started by a Brain coordinator")


def test_a_title_that_mentions_a_coordinator_is_no_coordinator(lab):
    lab.put(K, parent=F, name="report-to-g", title="Report to coordinator G, then build X")
    lab.note()
    refused(lab, call(lab, K, True), f"{K} is not a Brain coordinator")


# --- 3. at that handover, off on the caller itself ---

def test_off_on_itself_at_its_handover_passes(lab):
    lab.note()
    for target in ("self", F):
        assert decide(call(lab, target, False)) is None
    got = rows(lab)
    assert len(got) == 2 and {(r["decision"], r["case"]) for r in got} == {("allowed", "handover-off")}
    assert [r["what"]["session_id"] for r in got] == ["self", F] and G in got[0]["reason"]


def test_off_on_itself_without_a_note_is_refused(lab):
    refused(lab, call(lab, "self", False), f"no hand-over note of {F}")


@pytest.mark.parametrize("change", [{"detached": None}, {"detached": False}, {"archived": True, "detached": True}])
def test_off_on_itself_needs_a_live_detached_successor(lab, change):
    lab.note()
    lab.put(K, parent=F, name="rc-guard", detached=True)   # a detached child that is no coordinator does not count
    lab.put(G, parent=F, name="coordinator-g", title="Coordination du Brain — coordinateur G", **change)
    refused(lab, call(lab, "self", False), "it has started no live coordinator to succeed it, detached")


def test_a_session_that_is_no_coordinator_never_turns_its_own_off(lab):
    lab.note(host=K)
    refused(lab, call(lab, "self", False, caller=K), "this session is not a Brain coordinator")


# --- everything else stays refused ---

@pytest.mark.parametrize("mode", ["bypassPermissions", "default", "plan"])
def test_the_permission_mode_stays_refused_even_at_a_handover(lab, mode):
    lab.note()
    reason = decide(call(lab, G, None, tool="mcp__ccd_session_mgmt__set_session_permission_mode", mode=mode))
    assert reason and "set_session_permission_mode refused: security-settings is Ada's alone" in reason
    assert "three exceptions" not in reason


def test_the_app_setting_stays_refused(lab):
    lab.note()
    p = call(lab, G, True)
    p.update(tool_name="mcp__ccd_settings__set_setting",
             tool_input={"key": "connect_new_sessions_to_remote_control", "value": True})
    assert "security-settings is Ada's alone" in decide(p)


@pytest.mark.parametrize("inp", [{"session_id": G}, {"session_id": G, "enabled": "true"}, {"enabled": True},
                                 {"session_id": "", "enabled": True}, {"session_id": ["x"], "enabled": False}])
def test_an_input_it_cannot_read_is_refused(lab, inp):
    lab.note()
    p = call(lab, G, True)
    p["tool_input"] = inp
    refused(lab, p, "its session_id or enabled cannot be read")


def test_a_caller_it_cannot_identify_is_refused(lab, monkeypatch):
    lab.note()
    p = call(lab, G, True)
    p["session_id"] = "not-a-known-transcript"
    refused(lab, p, "this session is not in the desktop app's session files")
    monkeypatch.setenv(sessions.HOST_ENV, K)   # the app's id in the environment says another session
    refused(lab, call(lab, G, True), "this session's app id and its transcript's disagree")


def test_no_app_on_the_machine_is_refused(lab, monkeypatch, tmp_path):
    lab.note()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nothing"))
    refused(lab, call(lab, G, True), "the desktop app's session files are not on this machine")


def test_an_error_is_a_refusal_never_a_pass(lab, monkeypatch):
    lab.note()

    def broken():
        raise OSError("disk")
    monkeypatch.setattr(sessions, "app_index", broken)
    refused(lab, call(lab, G, True), "the session tree or the ledger could not be read")


def test_the_override_still_lifts_nothing(lab, monkeypatch):
    monkeypatch.setenv(guards.ALLOW_ENV, "all")
    refused(lab, call(lab, R, False), f"{R} is running, not finished")


# --- the review's findings (RETRO-1/2/9) ---

def test_a_successor_unknown_on_this_machine_does_not_count(lab, tmp_path):
    lab.note()
    (tmp_path / "claude-config" / "projects" / "E--lab" / f"{CLI[G]}.jsonl").unlink()
    refused(lab, call(lab, "self", False), "it has started no live coordinator to succeed it, detached")
    refused(lab, call(lab, G, True), f"{G} is unknown")


# --- a successor just started, with no transcript yet (wi-brain-rc-handover-starting) ---

def starting(lab, host=G, age_s=4.0, created=None, name="coordinator-g", parent=F, detached=True,
             title="Coordination du Brain — coordinateur G"):
    """``host`` started ``age_s`` ago by its app file's createdAt (or ``created`` as is), its transcript not written."""
    lab.put(host, parent=parent, name=name, title=title, detached=detached,
            created=created if created is not None else int((time.time() - age_s) * 1000))
    (lab.cwd / "claude-config" / "projects" / "E--lab" / f"{CLI[host]}.jsonl").unlink(missing_ok=True)


def test_on_for_a_successor_just_started_passes(lab):
    """The outgoing coordinator turns it on seconds after start_session: the app has its file, not yet a transcript."""
    lab.note()
    starting(lab)
    assert decide(call(lab, G, True)) is None
    [row] = rows(lab)
    assert (row["decision"], row["case"]) == ("allowed", "handover-on")
    assert "has no transcript yet and was created" in row["reason"]


def test_on_for_a_successor_just_inside_the_start_window_passes(lab):
    lab.note()
    starting(lab, age_s=guards.HANDOVER_START_S - 30)
    assert decide(call(lab, G, True)) is None


@pytest.mark.parametrize("age_s", [guards.HANDOVER_START_S + 60, 30 * 24 * 3600, -3600])   # too old, or in the future
def test_on_for_an_unknown_successor_outside_the_start_window_is_refused(lab, age_s):
    lab.note()
    starting(lab, age_s=age_s)
    refused(lab, call(lab, G, True), f"{G} is unknown: no transcript yet and was created")


@pytest.mark.parametrize("created", ["2026-11-12T10:00:00Z", True, 0, -5, float("nan"), float("inf"), "missing"])
def test_on_for_an_unknown_successor_whose_creation_time_cannot_be_read_is_refused(lab, created):
    lab.note()
    starting(lab)
    f = next((lab.cwd / "appdata").rglob(f"{G}.json"))
    data = json.loads(f.read_text(encoding="utf-8"))
    if created == "missing":
        del data["createdAt"]
    else:
        data["createdAt"] = created
    f.write_text(json.dumps(data), encoding="utf-8")
    refused(lab, call(lab, G, True), f"{G} is unknown: no transcript yet and its creation time cannot be read")


def test_off_on_itself_with_a_successor_just_started_passes(lab):
    lab.note()
    starting(lab)
    assert decide(call(lab, "self", False)) is None
    [row] = rows(lab)
    assert (row["decision"], row["case"]) == ("allowed", "handover-off")
    assert f"{G} (starting: has no transcript yet and was created" in row["reason"]


@pytest.mark.parametrize("kw", [{"age_s": guards.HANDOVER_START_S + 60}, {"detached": None}])
def test_off_on_itself_with_an_old_or_attached_starting_successor_is_refused(lab, kw):
    lab.note()
    starting(lab, **kw)
    refused(lab, call(lab, "self", False), "it has started no live coordinator to succeed it, detached")


def test_starting_widens_nothing_else(lab):
    """A just-started session that is no coordinator, or not the caller's, gets nothing; nor does the archive case
    take a starting session for a finished one; nor does a session turn its own on."""
    lab.note()
    starting(lab, host=K, name="rc-guard", title="Build the guard")
    refused(lab, call(lab, K, True), f"{K} is not a Brain coordinator")
    refused(lab, call(lab, K, False), f"{K} is unknown, not finished")
    starting(lab, host=X, name="coordinator-x", parent=E)
    refused(lab, call(lab, X, True), f"{X} was not started by this session")
    starting(lab, host=F, name="coordinator-f", parent=E, detached=None)
    refused(lab, call(lab, F, True), "a session never turns its own Remote Control on")


@pytest.mark.parametrize("kw", [
    {"age_s": -3600},                                                   # written in the future
    {"age_s": guards.HANDOVER_NOTE_S + 60},                             # just too old
    {"pad": guards.HANDOVER_MAX},                                       # too big to read
    {"text": f"# Hand-over\nCoordinator F is `x{F}`.\n"},               # a longer token, not the id
    {"text": f"# Hand-over\nCoordinator F is `{F}-extra`.\n"},
    {"text": f"# Hand-over: coordinator G\nG is `{G}`, started by coordinator F (`{F}`).\n"},   # G's own note
])
def test_a_note_that_is_not_the_callers_own_does_not_count(lab, kw):
    lab.note(**kw)
    refused(lab, call(lab, G, True), f"no hand-over note of {F}")


def test_a_note_just_inside_the_window_counts(lab):
    lab.note(age_s=guards.HANDOVER_NOTE_S - 60)
    assert decide(call(lab, G, True)) is None


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need a privilege on Windows")
def test_a_linked_note_does_not_count(lab, tmp_path):
    real = tmp_path / "elsewhere.md"
    real.write_text(f"# Hand-over\nCoordinator F is `{F}`.\n", encoding="utf-8")
    (lab.home / "handover").mkdir(parents=True, exist_ok=True)
    (lab.home / "handover" / "coordinator-f.md").symlink_to(real)
    refused(lab, call(lab, G, True), f"no hand-over note of {F}")


def test_a_title_never_makes_a_coordinator(lab, monkeypatch):
    """A session can retitle itself (set_session_title): K titled « Coordination du Brain » is still K."""
    lab.put(K, parent=F, name="rc-guard", title="Coordination du Brain — coordinateur K")
    q = "local_56565656-0000-4000-8000-565656565656"
    monkeypatch.setitem(CLI, q, "56565656-cli0-4000-8000-000000000000")
    lab.put(q, parent=K, name="coordinator-q")
    lab.turn(q, "idle")
    lab.note(host=K)
    refused(lab, call(lab, q, True, caller=K), "this session is not a Brain coordinator")
    lab.note()   # nor does a title make F's successor
    lab.put(K, parent=F, name="rc-guard", title="Coordination du Brain — coordinateur K", detached=True)
    lab.put(G, parent=F, name="coordinator-g", detached=False)
    refused(lab, call(lab, K, True), f"{K} is not a Brain coordinator")
    refused(lab, call(lab, "self", False), "it has started no live coordinator")
    refused(lab, call(lab, K, False), f"{K} is a live coordinator")   # but it protects one from the archive case


@pytest.mark.parametrize("name", ["coordinator-report", "coordination-notes", "coordinator", "coordinator-gg-2"])
def test_a_name_that_only_starts_like_a_coordinator_is_none(lab, name):
    lab.note()
    lab.put(K, parent=F, name=name, title="A child")
    refused(lab, call(lab, K, True), f"{K} is not a Brain coordinator")
    assert decide(call(lab, K, False)) is None   # and it is archived like any finished child


def test_a_coordinator_started_by_no_one_does_not_hand_over(lab):
    """No parent in the app's file is no proof the owner started it: the owner switches a root's Remote Control."""
    f = next((lab.cwd / "appdata").rglob(f"{F}.json"))
    data = json.loads(f.read_text(encoding="utf-8"))
    data["spawnedFrom"] = {"name": "coordinator-f", "taskId": "task_1"}   # a name, but no parent's id
    f.write_text(json.dumps(data), encoding="utf-8")
    lab.note()
    refused(lab, call(lab, G, True), "this session was not started by a Brain coordinator")


def test_an_ambiguous_caller_or_target_is_refused(lab, tmp_path):
    lab.note()
    lab.put(Z, title="A twin", cli=CLI[F])   # two app files with F's transcript
    refused(lab, call(lab, G, True), "this session is not in the desktop app's session files")
    lab.put(Z, title="Coordination du Brain — coordinateur D", archived=True)
    other = tmp_path / "appdata" / "Claude-Data" / "claude_u" / "claude-code-sessions" / "acct" / "org"
    other.mkdir(parents=True)
    src = tmp_path / "appdata" / "Claude-Data" / "claude_t" / "claude-code-sessions" / "acct" / "org" / f"{G}.json"
    (other / f"{G}.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")   # G in two accounts
    refused(lab, call(lab, G, True), f'"{G}" is not in the desktop app\'s session files')


def test_a_pass_the_ledger_does_not_take_is_refused(lab, monkeypatch):
    lab.note()
    monkeypatch.setenv("BRAIN_CAPTURE", "0")
    refused(lab, call(lab, G, True), "the pass could not be logged in the guards ledger")


def test_another_servers_tool_gets_no_exception(lab):
    lab.note()
    p = call(lab, G, True)
    p["tool_name"] = "mcp__other__set_remote_control"
    reason = decide(p)
    assert reason and "security-settings is Ada's alone" in reason and "three exceptions" not in reason


@pytest.mark.parametrize("tool", [RC, "mcp__ccd_session_mgmt__set_session_permission_mode"])
def test_an_error_in_the_guard_fails_closed_for_security_settings(lab, monkeypatch, tool):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(guards, "check_owner", broken)
    monkeypatch.setattr(guards, "remote_control", lambda payload: (None, "x"))
    reason = decide(call(lab, R, False, tool=tool, mode="plan"))
    assert reason and "the guard failed, so it refuses" in reason


# --- the chain root the owner marked (wi-brain-handover-command) ---

NO_ROOT = "this session is not a Brain coordinator (the name its starter gave it), nor a chain root"


def _mark(*hosts):
    """The owner's mark, as brain handover root writes it in their own terminal (no CLAUDECODE)."""
    from brain import succession
    for h in hosts:
        succession.mark_root(h, "test", env={})


@pytest.fixture
def chain(lab, monkeypatch):
    """O, a root the owner started (no parent, no name), started C1 (coordinator-c1, detached), which started C2
    (coordinator-c2, detached): the first two hand-overs of a new chain."""
    o, c1, c2 = (f"local_{c * 8}-0000-4000-8000-{c * 12}" for c in "123")
    for h in (o, c1, c2):
        monkeypatch.setitem(CLI, h, f"{h[6:14]}-cli0-4000-8000-000000000000")
    lab.put(o, title="Coordinateur Brain handover")
    lab.put(c1, parent=o, name="coordinator-c1", detached=True)
    lab.put(c2, parent=c1, name="coordinator-c2", detached=True)
    for h, kind in ((o, "running"), (c1, "running"), (c2, "idle")):
        lab.turn(h, kind)
    return o, c1, c2


def test_an_unmarked_root_does_not_hand_over(lab, chain):
    o, c1, _ = chain
    lab.note(host=o)
    refused(lab, call(lab, c1, True, caller=o), NO_ROOT)
    refused(lab, call(lab, "self", False, caller=o), NO_ROOT)


def test_a_marked_root_hands_over_without_a_name(lab, chain):
    o, c1, _ = chain
    _mark(o)
    lab.note(host=o)
    assert decide(call(lab, c1, True, caller=o)) is None
    assert decide(call(lab, "self", False, caller=o)) is None
    assert [r["case"] for r in rows(lab)] == ["handover-on", "handover-off"]


def test_the_first_successor_of_a_marked_root_hands_over(lab, chain):
    o, c1, c2 = chain
    lab.note(host=c1)
    refused(lab, call(lab, c2, True, caller=c1), "this session was not started by a Brain coordinator")
    _mark(o)
    assert decide(call(lab, c2, True, caller=c1)) is None
    assert decide(call(lab, "self", False, caller=c1)) is None


def test_a_marked_session_that_a_session_started_is_no_root(lab, chain, monkeypatch):
    """The mark is for a session the owner started: a marked id whose app file names a parent counts for nothing."""
    from brain import succession
    _, c1, _ = chain
    with pytest.raises(succession.SuccessionError, match="not by the owner"):
        succession.mark_root(K, env={})
    guards.roots_file().parent.mkdir(parents=True, exist_ok=True)
    guards.roots_file().write_text(json.dumps({"v": 1, "roots": {K: {}, c1: {}}}), encoding="utf-8")   # forged
    q = "local_78787878-0000-4000-8000-787878787878"
    monkeypatch.setitem(CLI, q, "78787878-cli0-4000-8000-000000000000")
    lab.put(q, parent=K, name="coordinator-q", detached=True)
    lab.turn(q, "idle")
    lab.note(host=K)
    refused(lab, call(lab, q, True, caller=K), "this session is not a Brain coordinator")
    assert guards.chain_root(c1, guards.app_reader(sessions.app_index())(c1)) is False


@pytest.mark.parametrize("text", ["not json", json.dumps({"roots": ["x"]}), json.dumps({"roots": {"o": {}}})])
def test_a_broken_mark_file_marks_no_root(lab, chain, text):
    o, c1, _ = chain
    lab.note(host=o)
    guards.roots_file().parent.mkdir(parents=True, exist_ok=True)
    guards.roots_file().write_text(text, encoding="utf-8")
    refused(lab, call(lab, c1, True, caller=o), NO_ROOT)
