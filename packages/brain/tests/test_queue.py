import json
from datetime import date

import pytest
import yaml

from brain import cli, decisions, graph, projects, queue, records

AT = "2026-11-01T09:00:00Z"
TODAY = date(2026, 11, 3)


def _root(store):
    return store.parents[1]


def _graph(store):
    """wi-a <- wi-b <- wi-c -> ms-x (depends_on, part_of); wi-d is done; props that wait on Ada (the owner), or do not."""
    with open(store / "nodes" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write(
            "- {id: wi-a, type: WorkItem, status: todo, title: \"A\"}\n"
            "- {id: wi-b, type: WorkItem, status: todo, title: \"B\",\n"
            "   props: {open: \"Ada (security): rotate the forge's admin password, seen on 2026-11-02\"}}\n"
            "- {id: wi-c, type: WorkItem, status: doing, title: \"C\",\n"
            "   props: {external_blocker: \"the cluster is not available yet (Ada, 2026-10-29)\"}}\n"
            "- {id: wi-d, type: WorkItem, status: done, title: \"D\", props: {open: \"an old question\"}}\n"
            "- {id: wi-own, type: WorkItem, status: todo, title: \"Consult a notary before any share\",\n"
            "   props: {owner: Ada, idea: \"Ada, 2026-11-02\"}}\n"
            "- {id: wi-perm, type: WorkItem, status: todo, title: \"Perm\",\n"
            "   props: {needs: \"Ada's approval to restart Claude Code\"}}\n"
            "- {id: wi-q, type: WorkItem, status: todo, title: \"Q\", props: {open: \"which host first?\"}}\n"
            "- {id: wi-wait, type: WorkItem, status: todo, title: \"Wait\",\n"
            "   props: {waiting: \"ddr-2026-11-01-blocking-one\"}}\n")
    with open(store / "edges" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("- {from: wi-b, to: wi-a, type: depends_on}\n- {from: wi-c, to: wi-b, type: depends_on}\n"
                 "- {from: wi-c, to: ms-x, type: part_of}\n- {from: wi-d, to: wi-a, type: depends_on}\n")


def _ask(root, title, items, **kw):
    return decisions.ask(root, title=title, question=f"{title}?", options=["Yes: go", "No"], why="simplest", at=AT,
                         items=items, project="demo", **kw)


# --- categories and the rules' lists ---

@pytest.mark.parametrize("text, category", [
    ("rotate the box1 admin password", "keys"),
    ("add an ntfy topic", "keys"),
    ("put the Telegram token in the vault", "keys"),
    ("its recovery key kept offline", "keys"),
    ("gh repo edit RoJLD/x --visibility public", "visibility"),
    ("ask GitHub support to purge the old commits", "accounts"),
    ("Ada's go-ahead for a new scheduled task", "scheduled"),
    ("Register-ScheduledTask -TaskName cycle", "scheduled"),
    ("the GitHub Actions budget", "money"),
    ("arm the testnet", "arming"),
    ("consult a notary", "legal"),
    ("read the exchange's terms of service", "legal"),
    ("powershell -File install.ps1 -Apply", ""),
    ("token-free scripts and key decisions", ""),
    ("docker compose up -d", ""),
])
def test_owner_only_categories(text, category):
    assert queue.owner_only(text) == category


def test_the_rules_lists_are_read_and_covered(tmp_path):
    data = queue.rules()
    assert data["files"] and data["uncovered"] == []
    assert {"repository visibility", "keys", "accounts", "anything touching money"} <= set(data["terms"])
    text = ("- **Ada's alone**: secrets (never in git, never typed by Claude), arming the fund and live orders,\n"
            "  repository visibility, new scheduled tasks.\n- Ada decides: the logo's colour.\n")
    assert queue._list_terms(text) == ["secrets", "arming the fund", "live orders", "repository visibility",
                                       "new scheduled tasks", "the logo's colour"]
    assert queue._list_terms(text, owner="Bob") == []  # the lists of the owner config.json names, no one else's
    assert queue._list_terms("- The owner decides: the logo's colour.\n", owner="Bob") == ["the logo's colour"]
    proj = projects.for_root(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")
    assert queue.rules(proj)["uncovered"] == ["the logo's colour"]


# --- the queue of a project ---

def test_build_sorts_by_what_each_entry_unblocks(store):
    root = _root(store)
    _graph(store)
    _ask(root, "Unblocks A", ["wi-a"])
    _ask(root, "Blocking one", ["wi-c"], blocking=True)
    _ask(root, "Answered", ["wi-a"])
    decisions.answer(root, "answered", ["Yes"], at=AT)
    queue.add(root, kind="action", title="Enter the exchange key", what="in the vault", at=AT, items=["wi-q"])
    data = queue.build(projects.for_root(root), today=TODAY, with_graph=False, transcripts=False)
    got = [(e["id"], e["kind"], e["unblocks"]) for e in data["entries"]]
    assert got == [
        ("ddr-2026-11-01-blocking-one", "decision", 3),  # wi-c, ms-x and wi-wait, whose props name it; band now
        ("ddr-2026-11-01-unblocks-a", "decision", 4),    # then the score: the count, the effort, the age
        ("wi-b:open", "action", 3),
        ("ddr-2026-11-01-enter-the-exchange-key", "action", 1),
        ("wi-perm:needs", "permission", 1),
        ("wi-q:open", "decision", 1),
        ("wi-own:owner", "action", 1)]
    assert data["bands"] == {"now": 1, "week": 0, "later": 6}
    by = {e["id"]: e for e in data["entries"]}
    assert by["ddr-2026-11-01-unblocks-a"]["unblocked"] == ["ms-x", "wi-a", "wi-b", "wi-c"]
    assert by["ddr-2026-11-01-unblocks-a"]["recommended"] == "Yes" and by["ddr-2026-11-01-blocking-one"]["blocking"]
    assert by["wi-b:open"]["category"] == "keys" and by["wi-b:open"]["since"] == "2026-11-02"
    assert by["wi-own:owner"]["category"] == "legal" and by["wi-own:owner"]["age_days"] == 1
    assert "brain queue done ddr-2026-11-01-enter-the-exchange-key" in by[
        "ddr-2026-11-01-enter-the-exchange-key"]["how"]
    assert data["counts"] == {"decision": 3, "action": 3, "permission": 1}
    only = queue.build(projects.for_root(root), kinds=("permission",), today=TODAY, with_graph=False,
                       transcripts=False)
    assert [e["id"] for e in only["entries"]] == ["wi-perm:needs"]
    text = "\n".join(queue.render(data))
    assert "   2.17   4  decision          ddr-2026-11-01-unblocks-a 2 d: Unblocks A -> recommended: Yes" in text
    assert " now (1): blocking" in text and " when you can (6)" in text
    assert "ddr-2026-11-01-blocking-one [blocking]" in text and "action:keys" in text


def test_spec_questions_and_proposed_specs(store, monkeypatch):
    root = _root(store)
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: {
        "open_questions": [], "blocked_on_owner": [],
        "spec_questions": [{"id": "spec-x", "date": "2026-11-01", "anchor": "docs/x.md#top",
                            "questions": [{"label": "Q2", "question": "Which venue?", "section": "Questions"}]}],
        "proposed_specs": [{"id": "spec-x", "title": "Spec X", "date": "2026-11-01", "anchor": "docs/x.md#top"}]})
    data = queue.build(projects.for_root(root), today=TODAY, transcripts=False)
    by = {e["id"]: e for e in data["entries"]}
    assert by["spec-x:Q2"]["title"] == "Which venue?" and by["spec-x:Q2"]["unblocked"] == ["wi-one"]
    assert by["spec-x:validate"]["kind"] == "decision"
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)
    assert queue.build(projects.for_root(root), today=TODAY, transcripts=False)["notes"]
    assert not queue.build(projects.for_root(root), today=TODAY, with_graph=False, transcripts=False)["entries"]


# --- denied tool calls ---

def _call(tid, ts, cwd, name, inp):
    return {"type": "assistant", "timestamp": ts, "sessionId": "s1", "cwd": cwd, "gitBranch": "b",
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def _result(tid, ts, cwd, text, error=True):
    block = {"type": "tool_result", "tool_use_id": tid, "content": text}
    if error:
        block["is_error"] = True
    return {"type": "user", "timestamp": ts, "sessionId": "s1", "cwd": cwd, "gitBranch": "b",
            "message": {"role": "user", "content": [block]}}


CLASSIFIER = ("Permission for this action was denied by the Claude Code auto mode classifier. Reason: "
              "[Self-Modification]. If you have other tasks that don't depend on this action, continue.")
SAFETY = ("Permission for this command was denied by a built-in Claude Code safety check, not by the user. Only a "
          "person may approve such a removal.")


def _transcripts(tmp_path, root, monkeypatch):
    cfg = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    wt = str(root / ".claude" / "worktrees" / "one-a1b2c3")
    elsewhere = str(tmp_path / "elsewhere")
    lines = [
        _call("t1", "2026-11-02T10:00:00Z", wt, "Bash", {"command": "powershell -File install.ps1 -Apply"}),
        _result("t1", "2026-11-02T10:00:01Z", wt, CLASSIFIER),
        _call("t2", "2026-11-02T10:01:00Z", wt, "Bash", {"command": "rm -rf $X/venv"}),
        _result("t2", "2026-11-02T10:01:01Z", wt, [{"type": "text", "text": SAFETY}]),
        _call("t3", "2026-11-02T10:02:00Z", wt, "Bash", {"command": "rm -rf $X/venv"}),
        _result("t3", "2026-11-02T10:02:01Z", wt, "", error=False),  # granted: the same call went through
        _call("t4", "2026-11-02T10:03:00Z", wt, "Bash", {"command": "git commit -m x"}),
        _result("t4", "2026-11-02T10:03:01Z", wt, "PreToolUse:Bash hook error: brain-core guard: git commit "
                "message refused"),
        _call("t5", "2026-11-02T10:04:00Z", wt, "Bash", {"command": "gh repo edit --visibility public"}),
        _result("t5", "2026-11-02T10:04:01Z", wt, "Error: " + CLASSIFIER.replace("Self-Modification", "Repo")),
        _call("t6", "2026-11-02T10:05:00Z", wt, "Bash", {"command": "ls"}),
        _result("t6", "2026-11-02T10:05:01Z", wt, "The user doesn't want to proceed with this tool use."),
        _call("t7", "2026-10-01T10:00:00Z", wt, "Bash", {"command": "old"}),
        _result("t7", "2026-10-01T10:00:01Z", wt, CLASSIFIER),
        _call("t8", "2026-11-02T11:00:00Z", elsewhere, "Edit", {"file_path": "C:/Users/x/.claude/settings.json"}),
        _result("t8", "2026-11-02T11:00:01Z", elsewhere, "Permission to use Edit has been denied."),
    ]
    d = cfg / "projects" / "p1"
    d.mkdir(parents=True)
    (d / "s1.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return cfg


def test_scan_places_denials_and_done_stamps_them(tmp_path, store, monkeypatch, brain_home):
    root = _root(store)
    _graph(store)
    _transcripts(tmp_path, root, monkeypatch)
    ledger = brain_home / "ledger"
    ledger.mkdir(parents=True)
    (ledger / "guards-2026-11.jsonl").write_text(
        json.dumps({"at": "2026-11-02T10:03:00Z", "event": "guard", "guard": "attribution", "decision": "denied",
                    "cwd": str(root)}) + "\n", encoding="utf-8")
    scanned = queue.scan(7, TODAY)
    calls = sorted(d["call"] for d in scanned["denials"])
    assert calls == ["Bash: gh repo edit --visibility public", "Bash: powershell -File install.ps1 -Apply",
                     "Edit: C:/Users/x/.claude/settings.json"]
    proj = projects.for_root(root)
    data = queue.collect([proj], today=TODAY, with_graph=False)
    mine = {e["title"]: e for e in data[0]["entries"] if e["source"] == "denial"}
    install = mine["Bash: powershell -File install.ps1 -Apply"]
    assert install["kind"] == "permission" and install["detail"] == "auto-mode classifier: Self-Modification"
    assert install["unblocked"] == ["wi-one"]  # the worktree one-a1b2c3 is wi-one's
    assert mine["Bash: gh repo edit --visibility public"]["kind"] == "action"
    assert data[0]["guard_refusals"] == 1
    assert [d["project"] for d in data] == [proj.name, queue.OUTSIDE]
    assert data[1]["entries"][0]["detail"] == "permission rule: Edit"
    print(queue.done(root, install["id"], at="2026-11-02T12:00:00Z", note="ran it myself"))
    again = queue.collect([proj], today=TODAY, with_graph=False)
    assert install["id"] not in {e["id"] for e in again[0]["entries"]}
    cfg_file = tmp_path / "claude" / "projects" / "p1" / "s1.jsonl"
    wt = str(root / ".claude" / "worktrees" / "one-a1b2c3")
    with open(cfg_file, "a", encoding="utf-8") as fh:  # denied again after the stamp: back in the queue
        fh.write(json.dumps(_call("t9", "2026-11-02T13:00:00Z", wt, "Bash",
                                  {"command": "powershell -File install.ps1 -Apply"})) + "\n")
        fh.write(json.dumps(_result("t9", "2026-11-02T13:00:01Z", wt, CLASSIFIER)) + "\n")
    back = queue.collect([proj], today=TODAY, with_graph=False)
    assert install["id"] in {e["id"] for e in back[0]["entries"]}
    assert queue.scan(0, date(2026, 11, 30))["denials"] == []


# --- add and done ---

def test_add_and_done_lifecycle(store):
    root = _root(store)
    ddr, out, note = queue.add(root, kind="permission", title="Allow brain resume", what="add Bash(brain resume:*)",
                               at=AT, items=["wi-one"])
    assert ddr["kind"] == "permission" and out.is_file() and not note and "options" not in ddr
    key, _, note = queue.add(root, kind="permission", title="Rotate the API key", what="the exchange's", at=AT)
    assert key["kind"] == "action" and "keys is Ada's alone" in note
    with pytest.raises(queue.QueueError):
        queue.add(root, kind="decision", title="x", what="y", at=AT)
    _ask(root, "A choice", ["wi-one"])
    assert records.check(root) == ([], [])
    board = decisions.view(root, "demo")
    assert "Done: grant a narrow allow rule, or do it once, then `brain queue done ddr-2026-11-01-allow-brain-" \
           "resume`" in board and "Done: do it, then `brain queue done ddr-2026-11-01-rotate-the-api-key`" in board
    assert "(permission: brain queue done ID)" in "\n".join(decisions.render_pending(
        decisions.pending(projects.for_root(root), with_graph=False)))
    records.write_graph(root, store)  # a DDR without options or recommendation has its graph node
    nodes = {n["id"]: n for n in yaml.safe_load(
        (store / "nodes" / "_generated_records.yaml").read_text(encoding="utf-8"))}
    assert nodes["ddr-2026-11-01-allow-brain-resume"]["props"] == {"kind": "permission"}
    msg = queue.done(root, "allow-brain", at="2026-11-02T10:00:00Z", note="allow rule in acme #60")
    assert "answered (done: allow rule in acme #60)" in msg
    _, d = decisions.find(root, "allow-brain")
    assert d["status"] == "answered" and d["answer"]["other"] == "done: allow rule in acme #60"
    with pytest.raises(queue.QueueError, match="is a decision"):
        queue.done(root, "a-choice", at=AT)
    with pytest.raises(queue.QueueError, match="brain item set wi-b open="):
        queue.done(root, "wi-b:open", at=AT)


def test_cli_queue(tmp_path, monkeypatch, store, capsys):
    root = _root(store)
    _graph(store)
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)
    base = ["--project", "demo", "queue"]
    assert cli.main(base + ["add", "--kind", "permission", "--title", "Apply the installer", "--what",
                            "install.ps1 -Apply", "--item", "wi-a", "--at", AT]) == 0
    assert (root / "notes" / "decision_queue.md").is_file()
    capsys.readouterr()
    assert cli.main(base + ["--json", "--no-graph"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["entries"][0]["id"] == "ddr-2026-11-01-apply-the-installer" and data["entries"][0]["unblocks"] == 4
    assert cli.main(["queue", "--project", "demo", "--kind", "permission"]) == 0
    out = capsys.readouterr().out
    assert "demo (" in out and "2 waiting on Ada: 0 decision(s), 0 action(s), 2 permission(s)" in out
    assert "note: research_graph pending did not run" not in out  # --kind permission: no spec questions asked
    assert cli.main(base + ["done", "apply-the", "--note", "ran it"]) == 0
    assert cli.main(base + ["done", "wi-b:open"]) == 1
    assert cli.main(["queue", "--all", "--no-graph"]) == 0
    out = capsys.readouterr().out
    assert "all: 4 waiting on Ada in 1 of 1 group(s)" in out and out.count("a decision: brain decision") == 1
