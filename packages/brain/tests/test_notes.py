import pytest
import yaml

from brain import graph, notes

JOURNAL = "# Journal\n\nOne entry per day.\n\n## 2026-10-31 — Old day\n\n- done\n"
LOG = ("# Decisions\n\n## 2026-10-30 — Old rule (ADR)\n\n**Context.** c\n\n**Décision.** d\n\n"
       "## 2026-10-30 — Old rule (ADR)\n\n**Context.** again\n")


def _file(tmp_path, name, text, crlf=False):
    f = tmp_path / name
    f.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    return f


def test_journal_new_entry_then_lines_append_only(tmp_path):
    f = _file(tmp_path, "journal.md", JOURNAL)
    assert notes.journal_add(f, ["first", "- already a bullet\n  continued", "two\nlines\n\n1. numbered"],
                             title="New  day", day="2026-11-01") == "entry"
    assert notes.journal_add(f, ["second " + "word " * 30], day="2026-11-01") == "lines"
    text = f.read_text(encoding="utf-8")
    assert text.startswith(JOURNAL.rstrip())
    tail = text[len(JOURNAL.rstrip()):]
    assert tail.startswith("\n\n## 2026-11-01 — New day\n\n- first\n- already a bullet continued\n- two lines\n"
                           "1. numbered\n- second word")
    assert all(len(line) <= notes.WIDTH for line in text.splitlines())
    assert text.splitlines()[-1].startswith("  word")  # wrapped under the bullet's text


def test_journal_refuses_another_day_and_secrets(tmp_path):
    f = _file(tmp_path, "journal.md", JOURNAL)
    with pytest.raises(notes.NotesError, match="last entry is 2026-10-31"):
        notes.journal_add(f, ["x"], day="2026-11-01")
    with pytest.raises(notes.NotesError, match="secret"):
        notes.journal_add(f, ["token " + "ghp_" + "a" * 36], day="2026-10-31")
    assert f.read_text(encoding="utf-8") == JOURNAL
    with pytest.raises(notes.NotesError, match="no journal"):
        notes.journal_add(tmp_path / "none.md", ["x"], title="t")


def test_journal_keeps_crlf(tmp_path):
    f = _file(tmp_path, "journal.md", JOURNAL, crlf=True)
    notes.journal_add(f, ["line"], day="2026-10-31")
    raw = f.read_bytes().decode("utf-8")
    assert raw.endswith("- done\r\n- line\r\n") and "\n" not in raw.replace("\r\n", "")


def test_adr_new_template_label_and_todo(tmp_path):
    f = _file(tmp_path, "decisions.md", LOG)
    out = notes.adr_new(f, "New rule (ADR)", {"context": "Why now.", "decision": "Do it:\n- one\n- two",
                                             "why_not_script": "needs judgement"}, day="2026-11-01")
    assert out == {"id": "adr-2026-11-01-new-rule-adr", "title": "New rule (ADR)", "supersedes": "",
                   "todo": ["why", "revisit"]}
    tail = f.read_text(encoding="utf-8")[len(LOG.rstrip()):]
    assert tail == ("\n\n## 2026-11-01 — New rule (ADR)\n\n**Context.** Why now.\n\n**Décision.** Do it:\n- one\n- two"
                    "\n\n**Why.** TODO\n\n**Revisit if.** TODO\n\n**Why not a script.** needs judgement\n")


def test_adr_ids_follow_research_graph_and_reversal(tmp_path):
    f = _file(tmp_path, "decisions.md", LOG)
    text = f.read_text(encoding="utf-8")
    assert notes.find_adr(text, "Old rule")[2] == "adr-2026-10-30-old-rule-adr-1"  # the second heading
    assert notes.find_adr(text, "adr-2026-10-30-old-rule-adr")[1] == "Old rule (ADR)"
    out = notes.adr_new(f, "", {"trigger": "it broke", "decision": "undo"}, day="2026-11-01",
                        reverses="adr-2026-10-30-old-rule-adr-1")
    assert out["title"] == "REVERSAL: Old rule"
    assert out["id"] == "adr-2026-11-01-reversal-old-rule"
    assert out["supersedes"] == "adr-2026-10-30-old-rule-adr-1"
    tail = f.read_text(encoding="utf-8")[len(LOG.rstrip()):]
    assert "**Supersedes.** 2026-10-30 — Old rule (ADR) (`adr-2026-10-30-old-rule-adr-1`)" in tail
    assert tail.index("**Trigger.**") < tail.index("**New decision.** undo") < tail.index("**Migration.** TODO")
    with pytest.raises(notes.NotesError, match="no ADR"):
        notes.adr_new(f, "", {}, reverses="adr-nope")


def test_graph_edits_keep_crlf(store):
    for f in (store / "nodes" / "work.yaml", store / "edges" / "work.yaml"):
        f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    graph.add_item(store, "wi-three", "Third", after=["wi-one"], today="2026-11-01")
    graph.close_item(store, "wi-one", "engine #1", "ok", today="2026-11-01")
    for f in (store / "nodes" / "work.yaml", store / "edges" / "work.yaml"):
        raw = f.read_bytes()
        assert raw.count(b"\n") == raw.count(b"\r\n")
    nodes = {n["id"]: n for n in yaml.safe_load((store / "nodes" / "work.yaml").read_text(encoding="utf-8"))}
    assert nodes["wi-one"]["props"]["done"] == "2026-11-01 ok" and nodes["wi-one"]["status"] == "done"
