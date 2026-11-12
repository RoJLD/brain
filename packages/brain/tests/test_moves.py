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
    hit = lambda line: [m.old for m in moves.find_in_line(line, t)]   # noqa: E731
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
    assert found[("doc.dead-ref", "README.md#plugins/kit/engine/cli.py")] == "P0"   # once per doc and prefix
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
    about = lambda data: [e for e in schema.validate("config", data, "strict")[0] if "moved" in e]   # noqa: E731
    assert about({"moved": TABLE}) == []
    assert about({"moved": {"a/": {"to": "b/", "date": "soon"}}})
