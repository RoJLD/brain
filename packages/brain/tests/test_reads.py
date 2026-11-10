"""wi-brain-read-commands: the read commands (brain item show, brain items, brain adr show, brain spec show, brain
journal last, each with --json) answer what sessions read the brain's files for by hand, and the PreToolUse hint
(readhint.sh, brain.readhint) names them when a session reads those files anyway, never refusing the call."""

import json
import os
import subprocess
import sys

import pytest
from test_capture import PLUGIN, _bash

from brain import brief, cli, decisions, notes, projects, readhint

AT = "2026-11-01T10:00:00Z"
LOG = ("# Decisions\n\n## 2026-10-30 — X\n\n**Context.** c\n\n**Decision.** d\n\n"
       "## 2026-10-31 — Y (ADR)\n\n**Context.** y\n\n### A sub-heading stays in its ADR\n\nmore\n")
JOURNAL = ("# Journal\n\nOne entry per day.\n\n## 2026-11-01 — One\n\n- a\n\n## 2026-11-02 — Two\n\n- b\n\n"
           "## 2026-11-02 — Three\n\n- c\n")
SPEC = ("# Spec X\n\nintro\n\n## 1. First\n\none\n\n### 1.1 Sub\n\nsub\n\n## 2. Second\n\n```\n## 9. not a heading\n"
        "```\ntwo\n")


def _brain(store):
    """The store fixture with a decision log, a journal, a spec, an ADR that supersedes another, a wave and edges."""
    root = store.parents[1]
    (root / "notes" / "decisions.md").write_text(LOG, encoding="utf-8")
    (root / "notes" / "journal.md").write_text(JOURNAL, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "x.md").write_text(SPEC, encoding="utf-8")
    with (store / "nodes" / "_generated_decisions.yaml").open("a", encoding="utf-8") as f:
        f.write('- {id: adr-2026-10-31-y-adr, type: ADR, title: "Y (ADR)", status: active, '
                'anchor: "notes/decisions.md#2026-10-31-y-adr"}\n')
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {id: wave-0.9.0, type: Milestone, status: pending, title: \"Wave 0.9.0\",\n"
                "   props: {kind: wave, release: 0.9.0}}\n"
                "- {id: wi-three, type: WorkItem, status: todo, title: \"Third\",\n"
                "   props: {wave: \"0.9.0, week of 2026-11-16\"}}\n")
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {from: wi-one, to: adr-2026-10-30-x, type: decided_by}\n"
                "- {from: adr-2026-10-31-y-adr, to: adr-2026-10-30-x, type: supersedes}\n"
                "- {from: wi-one, to: ms-x, type: part_of}\n"
                "- {from: wi-two, to: wi-one, type: depends_on}\n"
                "- {from: wi-two, to: wave-0.9.0, type: part_of}\n")
    return root


def _run(capsys, root, *argv) -> tuple[int, str, str]:
    rc = cli.main(["--root", str(root), *argv])
    out = capsys.readouterr()
    return rc, out.out, out.err


# --- the logs read back ---

def test_dated_sections_and_adr_ids_follow_the_headings():
    sections = notes.dated_sections(JOURNAL)
    assert [(s["day"], s["title"]) for s in sections] == [("2026-11-01", "One"), ("2026-11-02", "Two"),
                                                          ("2026-11-02", "Three")]
    assert sections[0]["text"] == "## 2026-11-01 — One\n\n- a" and sections[0]["line"] == 5
    adrs = notes.adr_entries(LOG)
    assert [a["id"] for a in adrs] == ["adr-2026-10-30-x", "adr-2026-10-31-y-adr"]   # research_graph sync's ids
    assert adrs[0]["text"].endswith("**Decision.** d") and "### A sub-heading" in adrs[1]["text"]
    assert [a["id"] for a in notes.adr_entries(LOG, "sdr")][0] == "sdr-2026-10-30-x"


# --- brain item show ---

def test_item_show_gives_props_edges_decisions_and_ddrs(store, capsys):
    root = _brain(store)
    decisions.ask(root, title="Which colour", question="Which colour for wi-one?", options=["Blue: calm", "Red: loud"],
                  why="calm", at=AT, items=["wi-one"])
    rc, out, _ = _run(capsys, root, "item", "show", "wi-one")
    assert rc == 0
    assert out.startswith("wi-one  [WorkItem todo]  priority P0\n  First: with a colon, and a comma")
    assert "  idea: Ada, 2026-10-30" in out and "specified_by  spec-x [Spec active]" in out
    assert "open items waiting on it: wi-two" in out
    assert "decided by (brain adr show <id> prints one):\n  adr-2026-10-30-x [ADR active]  X  -> superseded by " \
           "adr-2026-10-31-y-adr" in out
    assert "DDRs that name it:\n  ddr-" in out and "Which colour" in out
    assert "history" not in out   # --history only: a replay of the store's git history
    rc, out, _ = _run(capsys, root, "item", "show", "wi-one", "--json")
    data = json.loads(out)
    assert rc == 0 and data["decisions"]["direct"][0]["superseded_by"] == "adr-2026-10-31-y-adr"
    assert [d["status"] for d in data["ddrs"]] == ["pending"] and data["history"] is None
    assert data["props"]["theme"] == "3.1" and data["waiting_on_it"] == ["wi-two"]


def test_item_show_history_from_git(make_repo, capsys):
    work = ("- {id: wi-a, type: WorkItem, status: todo, title: \"A\"}\n")
    repo = make_repo("r", {"notes/graph/schema.yaml": "node_types: [WorkItem]\nedge_types: [depends_on]\n"
                                                      "statuses: [todo, doing, done]\n",
                           "notes/graph/edges.yaml": "", "notes/graph/nodes/work.yaml": work})
    make_repo.commit(repo, {"notes/graph/nodes/work.yaml": work.replace("todo", "doing")}, date="2026-10-02T12:00:00Z")
    rc, out, err = _run(capsys, repo, "item", "show", "wi-a", "--history")
    assert rc == 0, err
    assert "history (git, first-parent): 2 change(s)" in out and "status todo -> doing" in out
    rc, out, _ = _run(capsys, repo, "item", "show", "wi-a", "--history", "--json")
    assert [e["kind"] for e in json.loads(out)["history"]] == ["created", "status"]


def test_item_show_of_an_unknown_id_says_so(store, capsys):
    rc, _, err = _run(capsys, _brain(store), "item", "show", "wi-nope")
    assert rc == 1 and "wi-nope: no such node" in err


# --- brain items ---

def _ids(out: str) -> list[str]:
    return [r["id"] for r in json.loads(out)]


def test_items_filters(store, capsys):
    root = _brain(store)
    assert _ids(_run(capsys, root, "items", "--json")[1]) == ["wi-two", "wi-one", "wi-three"]   # open, by status
    assert _ids(_run(capsys, root, "items", "--priority", "P0", "--json")[1]) == ["wi-one"]
    assert _ids(_run(capsys, root, "items", "--status", "doing", "--json")[1]) == ["wi-two"]
    assert _ids(_run(capsys, root, "items", "--milestone", "ms-x", "--json")[1]) == ["wi-one"]
    assert _ids(_run(capsys, root, "items", "--prop", "theme=3.1", "--json")[1]) == ["wi-one"]
    assert _ids(_run(capsys, root, "items", "--text", "colon comma", "--json")[1]) == ["wi-one"]
    assert _ids(_run(capsys, root, "items", "--type", "Milestone", "--status", "pending", "--json")[1]) == \
        ["ms-x", "wave-0.9.0"]
    rc, out, _ = _run(capsys, root, "items", "--limit", "1")
    assert rc == 0 and out.startswith("wi-two") and "... 2 more: --limit 0 lists them all" in out


def test_items_of_a_wave_by_release_or_id_and_by_free_text(store, capsys):
    root = _brain(store)
    for ref in ("0.9.0", "wave-0.9.0"):
        assert _ids(_run(capsys, root, "items", "--wave", ref, "--json")[1]) == ["wi-two", "wi-three"]
    assert _ids(_run(capsys, root, "items", "--wave", "1.0.0", "--json")[1]) == []


# --- brain adr show ---

def test_adr_show_by_id_title_and_the_start_of_an_id(store, capsys):
    root = _brain(store)
    rc, out, _ = _run(capsys, root, "adr", "show", "adr-2026-10-30-x")
    assert rc == 0 and out.startswith("== adr-2026-10-30-x  (notes/decisions.md:3)\n## 2026-10-30 — X")
    assert "**Decision.** d" in out and "Y (ADR)" not in out
    assert "## 2026-10-31 — Y (ADR)" in _run(capsys, root, "adr", "show", "Y")[1]   # the title, "(ADR)" optional
    assert "## 2026-10-31 — Y (ADR)" in _run(capsys, root, "adr", "show", "adr-2026-10-31")[1]   # one starts so
    rc, _, err = _run(capsys, root, "adr", "show", "adr-2026-10")
    assert rc == 1 and "2 ADRs start so (adr-2026-10-30-x, adr-2026-10-31-y-adr): give one" in err
    rc, _, err = _run(capsys, root, "adr", "show", "nothing-here")
    assert rc == 1 and "no ADR of notes/decisions.md" in err


def test_adr_show_of_a_node_gives_the_adrs_that_decide_it(store, capsys):
    root = _brain(store)
    rc, out, _ = _run(capsys, root, "adr", "show", "wi-one")
    assert rc == 0 and out.startswith("wi-one [WorkItem]: decided by 1 ADR(s)\n== adr-2026-10-30-x")
    assert "-> superseded by adr-2026-10-31-y-adr" in out and "**Decision.** d" in out
    rc, out, _ = _run(capsys, root, "adr", "show", "wi-one", "--titles")
    assert out.splitlines()[1].endswith("2026-10-30 X") and "**Decision.**" not in out
    data = json.loads(_run(capsys, root, "adr", "show", "wi-one", "--json")[1])
    assert data["node"]["id"] == "wi-one" and data["adrs"][0]["file"] == "notes/decisions.md"


# --- brain spec show ---

def test_spec_show_whole_a_section_or_its_headings(store, capsys):
    root = _brain(store)
    rc, out, _ = _run(capsys, root, "spec", "show", "spec-x")
    assert rc == 0 and out.startswith("<!-- docs/x.md -->\n# Spec X") and "two" in out
    out = _run(capsys, root, "spec", "show", "spec-x", "--section", "1")[1]
    assert out.startswith("<!-- docs/x.md § 1 -->\n## 1. First") and "### 1.1 Sub" in out and "Second" not in out
    assert _run(capsys, root, "spec", "show", "spec-x", "--section", "1.1")[1].splitlines()[1:] == ["### 1.1 Sub", "",
                                                                                                    "sub"]
    out = _run(capsys, root, "spec", "show", "spec-x", "--section", "second")[1]   # the start of its title
    assert "## 9. not a heading" in out and out.rstrip().endswith("two")   # a heading in a code fence is text
    assert _run(capsys, root, "spec", "show", "doc:root:docs/x.md::2")[1].startswith("<!-- docs/x.md § 2 -->")
    assert _run(capsys, root, "spec", "show", "docs/x.md", "--section", "1.1")[0] == 0   # a path
    rc, out, _ = _run(capsys, root, "spec", "show", "spec-x", "--toc")
    assert rc == 0 and [line.split()[0] for line in out.splitlines()[1:]] == ["spec-x", "1", "1.1", "2"]
    rc, _, err = _run(capsys, root, "spec", "show", "spec-x", "--section", "7")
    assert rc == 1 and "section '7': no such heading (spec-x, 1, 1.1, 2" in err
    data = json.loads(_run(capsys, root, "spec", "show", "spec-x", "--section", "2", "--json")[1])
    assert data["file"] == "docs/x.md" and data["section"] == "2" and data["title"] == "2. Second"


# --- brain journal last ---

def test_journal_last_entries(store, capsys):
    root = _brain(store)
    rc, out, _ = _run(capsys, root, "journal", "last")
    assert rc == 0 and out == "## 2026-11-02 — Three\n\n- c\n"
    assert _run(capsys, root, "journal", "last", "2", "--titles")[1] == "2026-11-02  Two\n2026-11-02  Three\n"
    assert len(json.loads(_run(capsys, root, "journal", "last", "0", "--json")[1])) == 3
    rc, _, err = _run(capsys, root, "journal", "last", "--file", str(root / "none.md"))
    assert rc == 1 and "no journal here" in err


# --- the briefs name them ---

def test_the_brief_names_the_read_commands(store):
    root = _brain(store)
    lines = brief._start(projects.for_root(root), {"id": "wi-one"})
    assert any("brain --project root item show wi-one" in line and "brain journal last" in line for line in lines)


# --- the hint ---

@pytest.fixture
def registered(store, monkeypatch, tmp_path):
    root = _brain(store)
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: '{root.as_posix()}'}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return root


def _payload(tool: str, cwd, **inp) -> dict:
    return {"tool_name": tool, "cwd": str(cwd), "tool_input": inp, "hook_event_name": "PreToolUse"}


def test_the_hint_names_the_command_that_answers(registered):
    root = registered
    hint = readhint.hint(_payload("Read", root, file_path=str(root / "notes" / "graph" / "nodes" / "work.yaml")))
    assert hint.startswith("brain read hint: notes/graph/nodes/work.yaml is the graph YAML of the brain demo; "
                           "`brain --project demo item show <id>`") and "not a refusal" in hint
    hint = readhint.hint(_payload("Bash", root, command='grep -n "id: wi-one" notes/graph/nodes/work.yaml'))
    assert "`brain --project demo item show wi-one`" in hint
    hint = readhint.hint(_payload("Grep", root, pattern="spec-x", glob="notes/graph/nodes/*.yaml"))   # no path: cwd
    assert "`brain --project demo item show spec-x`" in hint
    hint = readhint.hint(_payload("Grep", root, pattern="adr-2026-10-30-x", path=str(root / "notes" / "decisions.md")))
    assert "decision log of the brain demo; `brain --project demo adr show adr-2026-10-30-x`" in hint
    assert "journal last" in readhint.hint(_payload("Read", root, file_path=str(root / "notes" / "journal.md")))
    assert "items` (filters" in readhint.hint(_payload("PowerShell", root,
                                                       command=f"Get-Content {root}\\notes\\kanban_graph.md"))
    assert "`brain --project demo next`" in readhint.hint(_payload("Read", root, file_path="notes/plan_graph.md"))
    assert "item show <id>" in readhint.hint(_payload("Grep", root, pattern="wave", path=str(root / "notes" / "graph")))


def test_no_hint_for_a_write_another_file_or_an_unregistered_brain(registered, tmp_path):
    root = registered
    assert readhint.hint(_payload("Bash", root, command="git add notes/graph/nodes/work.yaml")) == ""
    assert readhint.hint(_payload("Read", root, file_path=str(root / "docs" / "x.md"))) == ""
    other = tmp_path / "other"
    (other / "notes" / "graph" / "nodes").mkdir(parents=True)
    (other / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    assert readhint.hint(_payload("Read", other, file_path=str(other / "notes" / "graph" / "nodes" / "w.yaml"))) == ""
    stray = root / "data" / "nodes" / "x.yaml"   # a nodes/ folder outside a store
    assert readhint.hint(_payload("Read", root, file_path=str(stray))) == ""


def test_the_hint_reads_a_worktree_of_a_registered_checkout(registered, tmp_path):
    wt = tmp_path / "wt"
    (wt / "notes" / "graph").mkdir(parents=True)
    (wt / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    (wt / ".git").write_text(f"gitdir: {registered.as_posix()}/.git/worktrees/wt\n", encoding="utf-8")
    hint = readhint.hint(_payload("Read", wt, file_path=str(wt / "notes" / "graph" / "nodes" / "work.yaml")))
    assert "of the brain demo" in hint


def test_hook_main_prints_context_never_a_decision(registered, capsys):
    import io
    data = _payload("Read", registered, file_path=str(registered / "notes" / "journal.md"))
    assert readhint.hook_main([], io.BytesIO(json.dumps(data).encode("utf-8"))) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and "journal last" in out["additionalContext"]
    assert "permissionDecision" not in out
    assert readhint.hook_main([], io.BytesIO(b"not json")) == 0 and capsys.readouterr().out == ""


def test_readhint_sh_fast_path_and_python_path(registered):
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    env = dict(os.environ, BRAIN_PYTHON=sys.executable)

    def run(data: dict, **more) -> subprocess.CompletedProcess:
        return subprocess.run([bash, str(PLUGIN / "hooks" / "readhint.sh")], input=json.dumps(data),
                              capture_output=True, text=True, encoding="utf-8", env=dict(env, **more), timeout=60)

    miss = run(_payload("Read", registered, file_path=str(registered / "README.md")))
    assert miss.returncode == 0 and miss.stdout == ""
    data = _payload("Read", registered, file_path=str(registered / "notes" / "decisions.md"))
    hit = run(data)
    assert hit.returncode == 0 and "adr show" in json.loads(hit.stdout)["hookSpecificOutput"]["additionalContext"]
    assert run(data, BRAIN_READ_HINT="0").stdout == ""
