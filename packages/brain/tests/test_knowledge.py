"""wi-brain-notes-home: the owner's notes home (brain.knowledge, brain notes): init by plan that never overwrites,
--from copies a vault, check's findings, find over FTS5 and its LIKE fallback, the private and confidential classes,
the registry's kind: knowledge entry and config.json's knowledge key."""

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from brain import cli, config, knowledge, projects, schema

GH_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # a key's shape, never a real one


def note(root: Path, rel: str, front: dict | None, body: str = "") -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    head = "" if front is None else "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n"
    f.write_text(head + body, encoding="utf-8")
    return f


def front(nid: str, type_: str = "note", **more) -> dict:
    return {"id": nid, "type": type_, "title": f"Title {nid}", **more}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A laid-out notes home, and a config.json that names it (knowledge.path, relative to the file's folder)."""
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "config.json").write_text(json.dumps({"v": 1, "knowledge": {"path": "../notes"}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / "config.json"))
    monkeypatch.setenv("BRAIN_PROJECTS", str(brain / "projects.yaml"))
    root = tmp_path / "notes"
    knowledge.apply(root, knowledge.plan(root))
    return root


# --- init ---

def test_init_plans_the_layout_then_writes_it_and_never_overwrites(tmp_path):
    root = tmp_path / "notes"
    steps = knowledge.plan(root)
    assert {s.path for s in steps if s.action == "mkdir"} == {f"{n}/" for n in knowledge.LAYOUT}
    assert {f"templates/{t}.md" for t in knowledge.TYPES} <= {s.path for s in steps if s.action == "write"}
    assert not root.exists()                                      # a plan writes nothing
    knowledge.apply(root, steps)
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {"/daily/", "/people/", "/sealed/", "/_brain/", "/_maps/"} <= set(ignore)
    assert "/notes/" not in ignore and (root / "notes" / ".gitkeep").is_file()
    (root / "README.md").write_text("mine", encoding="utf-8")
    again = knowledge.plan(root)
    assert {s.action for s in again} == {"keep"}                  # everything there: kept, nothing to write
    knowledge.apply(root, again)
    assert (root / "README.md").read_text(encoding="utf-8") == "mine"


def test_apply_keeps_a_file_written_after_the_plan(tmp_path):
    root = tmp_path / "notes"
    steps = knowledge.plan(root)
    root.mkdir()
    (root / "CLAUDE.md").write_text("the owner's", encoding="utf-8")
    done = knowledge.apply(root, steps)
    assert "kept   CLAUDE.md: written meanwhile" in done
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "the owner's"
    assert not list(root.rglob("*.brain-tmp"))


def test_every_template_passes_the_schema_once_filled():
    for t in knowledge.TYPES:
        text = knowledge.template(t).replace("{{date:YYYYMMDD}}", "20261116").replace("{{time:HHmm}}", "0930") \
            .replace("{{title}}", "A title").replace("{{date:YYYY-MM-DD}}", "2026-11-16")
        data, _ = knowledge.front_matter(text)
        assert schema.validate("notes", data, schema.STRICT) == ([], []), t


def test_from_copies_a_vault_into_inbox_and_attachments_and_leaves_it_as_it_was(tmp_path):
    vault = tmp_path / "vault"
    note(vault, "Ideas/first.md", None, "an idea")
    (vault / "img.png").write_bytes(b"\x89PNG")
    note(vault, ".obsidian/app.json", None, "{}")
    root = tmp_path / "notes"
    steps = knowledge.plan(root, vault)
    copies = {s.path for s in steps if s.action == "copy"}
    assert copies == {"inbox/Ideas/first.md", "attachments/img.png"}   # .obsidian/ is the editor's, never copied
    knowledge.apply(root, steps)
    assert (root / "inbox/Ideas/first.md").read_text(encoding="utf-8") == "an idea"
    assert (vault / "Ideas/first.md").is_file()                        # a copy, never a move
    assert {s.action for s in knowledge.plan(root, vault) if s.path in copies} == {"keep"}


def test_init_refuses_a_file_a_missing_vault_and_a_vault_inside_the_home(tmp_path):
    f = tmp_path / "file"
    f.write_text("x", encoding="utf-8")
    assert "is a file" in knowledge.refuse_init(f)
    assert "no such folder" in knowledge.refuse_init(tmp_path / "n", tmp_path / "missing")
    (tmp_path / "n" / "v").mkdir(parents=True)
    assert "inside one another" in knowledge.refuse_init(tmp_path / "n", tmp_path / "n" / "v")
    assert "inside one another" in knowledge.refuse_init(tmp_path / "n" / "v", tmp_path / "n")
    assert knowledge.refuse_init(tmp_path / "n") == ""


def test_the_cli_plans_by_default_and_applies_on_request(tmp_path, capsys):
    root = tmp_path / "notes"
    assert cli.main(["notes", "init", str(root)]) == 0
    assert "the plan" in capsys.readouterr().out and not root.exists()
    assert cli.main(["notes", "init", str(root), "--apply", "--json"]) == 0
    assert "write  README.md" in json.loads(capsys.readouterr().out)
    assert cli.main(["notes", "init", str(root / "README.md")]) == 2
    assert "is a file" in capsys.readouterr().err


# --- check ---

def test_a_clean_home_has_no_finding(home):
    note(home, "notes/a.md", front("n-20261116-0001", tags=["Method"]), "see [[n-20261116-0002]]")
    note(home, "inbox/capture.md", None, "no front matter yet: an inbox capture may")
    assert knowledge.check(home, known=set()) == []


def test_check_finds_each_kind_of_fault(home):
    note(home, "notes/no-front.md", None, "body")
    note(home, "notes/bad.md", {"id": "n-1", "type": "essay", "title": "t", "cssclasses": ["w"]})
    note(home, "notes/a.md", front("n-20261116-0001", tags=["Method"], links=["wi-gone"]), "[[wi-there]] [[adr-gone]]")
    note(home, "sources/a.md", front("n-20261116-0001", "source", tags=["method"]))
    note(home, "notes/secret.md", front("n-20261116-0003"), f"token {GH_TOKEN}\n")
    note(home, "notes/contact.md", front("n-20261116-0004"), "write to someone@example.org")
    note(home, "people/p.md", front("n-20261116-0005", "person"), "someone@example.org +33 6 12 34 56 78")
    note(home, "daily/d.md", front("n-20261116-0006", "daily", share=["notion"]))
    note(home, "notes/lowered.md", front("n-20261116-0007", **{"class": "private"}))
    note(home, "daily/lowered.md", front("n-20261116-0008", "daily", **{"class": "private"}))
    lines = [f.line() for f in knowledge.check(home, known={"wi-there"})]
    want = [
        "error  notes/no-front.md: no front matter",
        "error  notes/bad.md: type: 'essay' not in",
        "warn   notes/bad.md: ",                                            # an editor's key: noted, kept
        "warn   notes/a.md: wi-gone: no such Brain id",
        "warn   notes/a.md: adr-gone: no such Brain id",
        "error  sources/a.md: id n-20261116-0001 is notes/a.md's too",
        "error  notes/secret.md:6: a secret pattern (github-token)",   # the line of the file
        "warn   notes/contact.md: an e-mail address or a phone number outside people/",
        "error  daily/d.md: share on a confidential note",
        "error  daily/lowered.md: class private is under its folder's (confidential)",
        "warn   tags: Method and method differ only by case",
    ]
    for w in want:
        assert any(line.startswith(w) for line in lines), (w, lines)
    assert not any("wi-there" in line or line.startswith(("warn   people/", "error  notes/lowered.md"))
                   for line in lines)
    assert not any(GH_TOKEN in line for line in lines)                      # the secret is never printed


def test_contact_data_is_an_address_or_nine_digits_never_an_id_or_a_date():
    for text in ("someone@example.org", "+33 6 12 34 56 78", "call 06.12.34.56.78", "(555) 0100 2000 3"):
        assert knowledge.contact(text), text
    for text in ("[[n-20261116-0930]]", "on 2026-11-16", "in 2026", "v0.5.1", "see 12 345", "docs/2026-11-16-x.md",
                 "at 10:30:00"):
        assert not knowledge.contact(text), text


def test_check_leaves_links_unchecked_without_a_graph(home):
    note(home, "notes/a.md", front("n-20261116-0001", links=["wi-gone"]))
    assert knowledge.check(home, known=None) == []


def test_check_finds_a_missing_ignore_line_and_a_tracked_confidential_file(home, monkeypatch):
    (home / ".gitignore").write_text("/sealed/\n", encoding="utf-8")
    monkeypatch.setattr(knowledge, "_git_tracked", lambda root, folder: [f"{folder}/x.md"] if folder == "daily" else [])
    lines = [f.line() for f in knowledge.check(home, known=set())]
    assert "error  .gitignore: /people/ is missing: git would hold people/" in lines
    assert "error  daily/x.md: tracked by git, in daily/ (never in git): git rm --cached it" in lines
    assert not any("/sealed/ is missing" in line for line in lines)


def test_a_folder_class_is_raised_by_config_never_lowered(home, monkeypatch, tmp_path):
    cfg = tmp_path / "brain" / "config.json"
    cfg.write_text(json.dumps({"v": 1, "knowledge": {"path": "../notes", "folders": {"notes": "sealed",
                                                                                    "daily": "private"}}}),
                   encoding="utf-8")
    classes = knowledge.folder_classes()
    assert classes["notes"] == "sealed" and classes["daily"] == "confidential"
    note(home, "notes/a.md", front("n-20261116-0001"), "hidden word")
    assert knowledge.find(home, "hidden", confidential=True) == []          # sealed now: never indexed


def test_the_cli_check_exits_1_on_an_error_and_2_without_a_home(home, capsys, monkeypatch, tmp_path):
    assert cli.main(["notes", "check"]) == 0
    assert "no finding" in capsys.readouterr().out
    note(home, "notes/no-front.md", None, "body")
    assert cli.main(["notes", "check", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)[0]["level"] == "error"
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "none.json"))
    assert cli.main(["notes", "check"]) == 2
    assert "no notes home" in capsys.readouterr().err
    assert cli.main(["notes", "check", "--dir", str(home)]) == 1


# --- find ---

def test_find_ranks_private_notes_and_keeps_confidential_and_sealed_out(home):
    note(home, "notes/a.md", front("n-20261116-0001", scope=["pro/acme"], tags=["graph"]), "A wikilink graph of notes")
    note(home, "sources/b.md", front("n-20261116-0002", "source"), "notes about graph databases")
    note(home, "daily/c.md", front("n-20261116-0003", "daily"), "graph meeting notes")
    note(home, "sealed/d.md", front("n-20261116-0004"), "graph notes, sealed")
    found = knowledge.find(home, "graph notes")
    assert {h["path"] for h in found} == {"notes/a.md", "sources/b.md"}
    assert all("graph" in h["snippet"].lower() for h in found)
    conf = {h["path"]: h["class"] for h in knowledge.find(home, "graph notes", confidential=True)}
    assert conf == {"notes/a.md": "private", "sources/b.md": "private", "daily/c.md": "confidential"}
    assert [h["path"] for h in knowledge.find(home, "graph", scope="pro/acme")] == ["notes/a.md"]
    assert knowledge.find(home, "  ") == [] and knowledge.find(home, "absent") == []


def test_the_index_is_rebuilt_only_when_a_note_changed(home):
    note(home, "notes/a.md", front("n-20261116-0001"), "first words")
    db = knowledge.index(home)
    assert db.parent.name == "notes-index" and db.parent.parent == knowledge.paths.brain_home()
    stamp = db.stat().st_mtime_ns
    assert knowledge.index(home).stat().st_mtime_ns == stamp
    note(home, "notes/b.md", front("n-20261116-0002"), "second words")
    assert {h["path"] for h in knowledge.find(home, "words")} == {"notes/a.md", "notes/b.md"}


def test_find_falls_back_to_like_without_fts5(home, monkeypatch):
    def no_fts(con):
        con.execute("CREATE TABLE notes (path, cls, scope, title, tags, body)")
        return False
    monkeypatch.setattr(knowledge, "_table", no_fts)
    note(home, "notes/a.md", front("n-20261116-0001"), "plain old search")
    note(home, "daily/b.md", front("n-20261116-0002", "daily"), "plain old search")
    assert [h["path"] for h in knowledge.find(home, "old plain")] == ["notes/a.md"]
    con = sqlite3.connect(knowledge.index_path(home))
    try:
        assert "fts5" not in con.execute("SELECT sql FROM sqlite_master WHERE name = 'notes'").fetchone()[0].lower()
    finally:
        con.close()


def test_the_cli_find(home, capsys):
    note(home, "notes/a.md", front("n-20261116-0001"), "a findable word")
    assert cli.main(["notes", "find", "findable", "--json"]) == 0
    assert [h["path"] for h in json.loads(capsys.readouterr().out)] == ["notes/a.md"]
    assert cli.main(["notes", "find", "nothing"]) == 0
    assert "no note holds every word" in capsys.readouterr().out


# --- the registry and the config key ---

def test_a_kind_knowledge_entry_is_listed_never_loaded_and_checked(tmp_path, monkeypatch):
    reg = tmp_path / "projects.yaml"
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    (tmp_path / "graph").mkdir()
    reg.write_text(yaml.safe_dump({
        "notes": {"kind": "knowledge", "root": "../notes", "title": "Notes"},
        "odd": {"kind": "library", "root": "x"},
        "extra": {"kind": "knowledge", "root": "y", "stores": ["g"]},
    }), encoding="utf-8")
    assert projects.knowledge(tmp_path) == {"notes": (tmp_path / "../notes").resolve(),
                                            "extra": (tmp_path / "y").resolve()}
    assert projects.load(tmp_path) == {}
    assert "is a notes home" in projects.unloaded("notes", tmp_path)
    errors = projects.check(tmp_path)
    assert any("kind is knowledge, not 'library'" in e for e in errors)
    assert any("holds title, kind, root, parent and classes only, not stores" in e for e in errors)
    assert "notes" in projects.repo_tokens(tmp_path)


def test_the_home_comes_from_config_else_the_registry(tmp_path, monkeypatch):
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "config.json").write_text(json.dumps({"v": 1}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / "config.json"))
    monkeypatch.setenv("BRAIN_PROJECTS", str(brain / "projects.yaml"))
    assert knowledge.home() is None
    (brain / "projects.yaml").write_text("notes: {kind: knowledge, root: ../n}\n", encoding="utf-8")
    assert knowledge.home() == (tmp_path / "n").resolve()
    (brain / "config.json").write_text(json.dumps({"v": 1, "knowledge": {"path": "../m", "repo": "o/n",
                                                                         "adapters": ["obsidian"]}}),
                                       encoding="utf-8")
    assert knowledge.home() == brain / "../m"
    assert config.load().data["knowledge"]["adapters"] == ["obsidian"]


def test_the_config_schema_holds_the_knowledge_key():
    k = schema.load("config")["properties"]["knowledge"]
    assert set(k["properties"]) == {"repo", "path", "adapters", "folders"} and k["additionalProperties"] is False
    def errors(knowledge_key):
        found, _ = schema.validate("config", {"v": 1, "knowledge": knowledge_key}, schema.STRICT)
        return [e for e in found if "knowledge" in e]
    assert errors({"repo": "o/n", "path": "x", "adapters": ["notion"], "folders": {"notes": "sealed"}}) == []
    assert len(errors({"repo": "o n", "folders": {"x": "public"}, "other": 1})) == 3


def test_the_notes_format_fixtures():
    fixtures = Path(__file__).parent / "fixtures" / "formats" / "notes" / "v1"
    older = yaml.safe_load((fixtures / "older.yaml").read_text(encoding="utf-8"))
    newer = yaml.safe_load((fixtures / "newer.yaml").read_text(encoding="utf-8"))
    assert schema.validate("notes", older, schema.STRICT) == ([], [])
    errors, unknown = schema.validate("notes", newer, schema.READ)
    assert errors == [] and len(unknown) == 1 and "cssclasses" in unknown[0]
