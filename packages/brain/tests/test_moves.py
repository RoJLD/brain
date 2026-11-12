"""wi-brain-moved-paths: config.json moved: {old prefix: {to, date}} read by brain audit's doc.dead-ref and brain
check (the brain's instructions, memory notes, skills and scripts), at zero token."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import run_git
from test_audit import README, _found, _measure

from brain import config, moves, projects
from brain.commands._stores import _moved_names, check_registry

TABLE = {"D:/work/old-notes": {"to": "D:/work/notes", "date": "2026-11-20", "note": "the folder rename"},
         "plugins/kit/engine/": {"to": "packages/brain/src/brain/", "date": "2026-11-04"},
         "plugins/kit/engine/cli.py": {"to": "packages/brain/src/brain/cli.py", "date": "2026-11-04"}}


def _table():
    return moves.table(config.Config(None, Path("."), {"moved": TABLE}))


def test_a_prefix_matches_where_a_path_starts_and_ends_either_slash_any_case():
    t = _table()

    def hit(line):
        return [m.old for m in moves.find_in_line(line, t)]

    assert hit(r"cd D:\work\old-notes\notes") == ["D:/work/old-notes"]
    assert hit("cd d:/WORK/Old-Notes") == ["D:/work/old-notes"]
    assert hit("D:/work/old-notes-help/x") == []            # a longer name is another folder
    assert hit("see plugins/kit/engine/cli.py") == ["plugins/kit/engine/cli.py"]   # the longest first
    assert hit("`plugins/kit/engine/graph.py`") == ["plugins/kit/engine/"]
    assert hit("moved from D:/work/old-notes to D:/work/notes") == []   # history names both


def test_the_table_reads_entries_and_says_the_move():
    t = _table()
    assert [m.old for m in t][0] == "plugins/kit/engine/cli.py"
    m = next(m for m in t if m.old == "D:/work/old-notes")
    assert m.says() == "D:/work/old-notes moved to D:/work/notes on 2026-11-20 (the folder rename)"
    assert moves.table(config.Config(None, Path("."), {"moved": {"x": "not a mapping"}})) == []


def test_doc_dead_ref_flags_an_old_prefix_with_its_new_one(monkeypatch):
    t = _table()
    monkeypatch.setattr(moves, "table", lambda cfg=None: t)
    res = _measure({"lab": {"README.md": README + "Run plugins/kit/engine/cli.py, then the rest.\n"
                                                  "It lived in plugins/kit/engine/cli.py, see above.\n",
                            "docs/x.md": "Nothing moved here.\n", "src/lab/__init__.py": ""}})
    found = _found(res, "lab")
    assert found[("doc.dead-ref", "README.md#plugins/kit/engine/cli.py")] == "P0"
    units = [f["unit"] for r in res["repos"] for f in r["findings"] if f["check"] == "doc.dead-ref"]
    assert units.count("README.md#plugins/kit/engine/cli.py") == 1   # once per doc and prefix
    f = next(f for f in res["repos"][0]["findings"] if f["unit"] == "README.md#plugins/kit/engine/cli.py")
    assert f["why"].startswith("README.md:") and f["fix"] == "write packages/brain/src/brain/cli.py"
    assert not any(u.startswith("docs/x.md#") for _, u in found)


def test_brain_check_flags_the_brains_instructions_memory_skills_and_scripts(tmp_path, monkeypatch, capsys):
    root = tmp_path / "brain"
    files = {"CLAUDE.md": "Run from D:\\work\\old-notes.\n", "memory/note.md": "plugins/kit/engine/ holds it\n",
             "plugins/core/skills/x/SKILL.md": "cd D:/work/old-notes\n", "install.ps1": "# D:/work/notes\n",
             "docs/guide.md": "D:/work/old-notes (a doc: the audit's)\n", "untracked.ps1": None}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text or "D:/work/old-notes\n", encoding="utf-8")
    (root / "config.json").write_text(json.dumps({"moved": TABLE}), encoding="utf-8")
    run_git(tmp_path, "init", "-q", str(root))
    run_git(root, "add", *[r for r, t in files.items() if t is not None], "config.json")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    lines = _moved_names(None)
    assert [ln.split(" names ")[0] for ln in lines] == ["CLAUDE.md:1", "memory/note.md:1",
                                                         "plugins/core/skills/x/SKILL.md:1"]
    assert lines[0].endswith("; write D:/work/notes")
    reg = tmp_path / "projects.yaml"
    reg.write_text("", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    check_registry(None, list(projects.load().values()))
    assert "warning: moved: CLAUDE.md:1 names D:/work/old-notes" in capsys.readouterr().out


def test_the_schema_takes_the_table_and_refuses_a_bad_date():
    from brain import schema

    def about(data):
        return [e for e in schema.validate("config", data, "strict")[0] if "moved" in e]

    assert about({"moved": TABLE}) == []
    assert about({"moved": {"a/": {"to": "b/", "date": "soon"}}})


def _one(old, new, line):
    return [m.old for m in moves.find_in_line(line, moves.table(config.Config(None, Path("."), {"moved": {
        old: {"to": new, "date": "2026-11-04"}}})))]


def test_a_prefix_starts_a_path_and_a_folder_prefix_ends_at_a_slash():
    """Review of the PR, finding 4."""
    assert _one("plugins/kit/engine/", "x/", "see plugins/kit/engine.py") == []        # a sibling file
    assert _one("engine/", "core/", "see tools/engine/x.py") == []                     # another folder's engine/
    assert _one("engine/", "core/", "see ./engine/x.py") == ["engine/"]
    assert _one("old-notes", "notes", "see old-notes.md") == []                         # another file
    assert _one("old-notes", "notes", "code:old-notes:src/x.py") == []                  # a CodeRef id: the audit's
    assert _one("old-notes", "notes", "the old-notes repo.") == ["old-notes"]           # a repo's name, by design


def test_history_is_the_new_prefix_outside_the_old_one():
    """Review of the PR, findings 2 and 3: a new prefix inside the old one is no history; a longer move judged
    history keeps a shorter one from flagging the same text."""
    assert _one("a/b/c", "a/b", "see a/b/c/x.py") == ["a/b/c"]
    assert _one("a/b", "a/b/c", "see a/b/x.py and a/b/c/y.py") == ["a/b"]
    table = moves.table(config.Config(None, Path("."), {"moved": {
        "docs/old/a.md": {"to": "archive/a.md", "date": "2026-11-04"},
        "docs/old/": {"to": "docs/new/", "date": "2026-11-04"}}}))
    assert moves.find_in_line("moved docs/old/a.md to archive/a.md", table) == []


def test_the_audit_reads_the_moves_of_the_brain_the_project_came_from(tmp_path, monkeypatch):
    """Review of the PR, finding 5: the registry's brain, not whatever config.json sits at the project's root."""
    from brain import audit
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "config.json").write_text(json.dumps({"moved": TABLE}), encoding="utf-8")
    p = projects.Project("demo", tmp_path / "lab", [])
    p.registry_dir = brain
    assert {m.old for m in audit._moved(p)} == set(TABLE)


def test_brain_check_outside_git_says_it_did_not_check(tmp_path, monkeypatch):
    """Review of the PR, finding 6."""
    (tmp_path / "config.json").write_text(json.dumps({"moved": TABLE}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "config.json"))
    assert _moved_names(tmp_path) == [f"not checked: {tmp_path} is not a git checkout (its tracked files are what "
                                      "is read)"]


def test_the_brains_rules_agents_hooks_and_settings_are_read():
    """Review of the PR, finding 7."""
    files = [".claude/agents/x.md", "plugins/core/rules/global.md", "plugins/core/skills/x/references/y.md",
             "plugins/core/hooks/hooks.json", ".claude/settings.json", "plugins/core/hooks/guard.py", "Claude.md",
             "docs/guide.md", "src/x.py"]
    assert moves.brain_files(Path("."), files) == files[:7]
