"""brain collisions and brain brief on a temporary project: an origin, its main checkout, a worktree with committed
and uncommitted changes, a branch without a worktree, and a graph whose items name their surface in different ways."""

import shutil

import pytest
from conftest import FIXTURES, GIT_ENV, git_init, run_git

from brain import brief, cli, collisions, config, projects

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not available")

NODES = """\
- {id: wi-a, type: WorkItem, status: todo, title: "A feature's code", props: {priority: P1}}
- {id: wi-b, type: WorkItem, status: todo, title: "Rewrite the guide x.md", props: {priority: P1}}
- {id: wi-c, type: WorkItem, status: todo, title: "Touch other.py", props: {priority: P1}}
- {id: wi-d, type: WorkItem, status: todo, title: "No surface", props: {priority: P1, open: "which way?"}}
- {id: wi-e, type: WorkItem, status: todo, title: "After A", props: {priority: P1}}
- {id: wi-demo-lane, type: WorkItem, status: todo, title: "On its branch", props: {priority: P2}}
- {id: wi-m, type: WorkItem, status: todo, title: "By module", props: {priority: P1, module: core}}
- {id: feat-a, type: Feature, status: have, title: "A", props: {module: core}}
- {id: "code:main:src/app.py", type: CodeRef, status: active, title: "app"}
- {id: spec-s, type: Spec, status: active, title: "The spec", anchor: "docs/spec.md#top"}
"""
EDGES = """\
- {from: wi-a, to: feat-a, type: delivers}
- {from: feat-a, to: "code:main:src/app.py", type: implemented_by}
- {from: wi-e, to: wi-a, type: depends_on}
- {from: wi-a, to: spec-s, type: specified_by}
"""
RULES = """\
# Ada's rules

## Definition of done

An item is done when it is tested and merged.

## Never

- Never tag.
- Never add an attribution line.

## Other

Never in other sections when a Never section exists.
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    origin = tmp_path / "origin.git"
    git_init(origin, bare=True)
    main = tmp_path / "main"
    (main / "notes" / "graph" / "nodes").mkdir(parents=True)
    (main / "notes" / "graph" / "edges").mkdir(parents=True)
    (main / "src").mkdir()
    (main / "docs").mkdir()
    git_init(main)
    run_git(main, "config", "commit.gpgsign", "false")
    (main / "notes" / "graph" / "schema.yaml").write_text("owner: Ada\n", encoding="utf-8")
    (main / "notes" / "graph" / "nodes" / "work.yaml").write_text(NODES, encoding="utf-8")
    (main / "notes" / "graph" / "edges" / "work.yaml").write_text(EDGES, encoding="utf-8")
    (main / "notes" / "journal.md").write_text("# Journal\n", encoding="utf-8")
    (main / ".gitattributes").write_text("notes/journal.md merge=brain\n", encoding="utf-8")
    for f in ("src/app.py", "src/other.py", "docs/x.md"):
        (main / f).write_text("x\n", encoding="utf-8")
    run_git(main, "add", "-A")
    run_git(main, "commit", "-q", "-m", "init")
    run_git(main, "remote", "add", "origin", str(origin))
    run_git(main, "push", "-q", "-u", "origin", "main")
    run_git(main, "remote", "set-head", "origin", "main")
    # a worktree: app.py committed, the journal (the driver's) committed, a new file not committed
    wt = tmp_path / "wt"
    run_git(main, "worktree", "add", "-q", "-b", "claude/feature", str(wt))
    (wt / "src" / "app.py").write_text("y\n", encoding="utf-8")
    (wt / "notes" / "journal.md").write_text("# Journal\n- a line\n", encoding="utf-8")
    run_git(wt, "commit", "-q", "-am", "work")
    (wt / "src" / "new.py").write_text("n\n", encoding="utf-8")
    # a branch without a worktree, on docs/x.md; and one named after an item
    run_git(main, "branch", "claude/docs")
    run_git(main, "checkout", "-q", "claude/docs")
    (main / "docs" / "x.md").write_text("y\n", encoding="utf-8")
    run_git(main, "commit", "-q", "-am", "docs")
    run_git(main, "checkout", "-q", "-b", "claude/demo-lane-1", "main")
    (main / "README.md").write_text("r\n", encoding="utf-8")
    run_git(main, "add", "-A")
    run_git(main, "commit", "-q", "-m", "lane")
    run_git(main, "checkout", "-q", "main")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {main.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    cfg = tmp_path / "brain"
    cfg.mkdir()
    (cfg / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}, "rules": ["rules.md"]}',
                                     encoding="utf-8")
    (cfg / "rules.md").write_text(RULES, encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg / "config.json"))
    monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", "local_coord")
    return projects.get("demo", main)


def test_branches_and_their_files(project):
    rep = collisions.report([project])
    by = {b.label: b for b in rep.branches}
    assert set(by) == {"claude/feature", "claude/docs", "claude/demo-lane-1"}
    assert by["claude/feature"].files == ["src/app.py", "src/new.py"] and by["claude/feature"].uncommitted == 1
    assert by["claude/feature"].shared == ["notes/journal.md"]   # merge=brain: never a collision
    assert by["claude/docs"].files == ["docs/x.md"] and not by["claude/docs"].worktree


def test_items_can_start_or_wait(project):
    rep = collisions.report([project], frontier=True)
    items = {i.id: i for i in rep.items}
    assert "wi-e" not in items                                # it depends on wi-a, open
    assert [w["branch"] for w in items["wi-a"].waits] == ["claude/feature"]
    assert items["wi-a"].waits[0]["files"] == ["src/app.py"]
    assert items["wi-m"].paths == [("main", "src/app.py")]   # its module's features' CodeRefs
    assert [w["branch"] for w in items["wi-b"].waits] == ["claude/docs"]
    assert items["wi-c"].known and not items["wi-c"].waits
    assert not items["wi-d"].known
    assert items["wi-demo-lane"].on == ["claude/demo-lane-1"]
    text = "\n".join(collisions.render(rep))
    assert "Can start now (1):\n- wi-c [P1]: other.py" in text
    assert "src/app.py with claude/feature" in text and "No known surface (1)" in text


def test_p0_p1_only_by_default(project):
    ids = {i.id for i in collisions.report([project]).items}
    assert "wi-demo-lane" not in ids and "wi-a" in ids


def test_cli_json(project, capsys):
    assert cli.main(["--project", "demo", "collisions", "--json"]) == 0
    import json
    data = json.loads(capsys.readouterr().out)
    assert {o["file"] for o in data["overlaps"]} == set()
    assert any(i["id"] == "wi-a" and i["waits"] for i in data["items"])


def test_a_surface_hook_adds_files(project, monkeypatch):
    monkeypatch.setattr(collisions, "SURFACE_HOOKS", [lambda node, st: [("", "docs/x.md")] if node["id"] == "wi-c"
                                                      else []])
    items = {i.id: i for i in collisions.report([project]).items}
    assert [w["branch"] for w in items["wi-c"].waits] == ["claude/docs"]


def test_brief_holds_the_graph_and_the_rules(project):
    b = brief.build(project, "wi-a", task_class="trivial")
    text = brief.render(b)
    assert b.model == "haiku" and b.effort == "low" and b.budget == "400k"
    assert b.coordinator == "local_coord"
    assert "- specified_by -> spec-s (Spec, active; docs/spec.md#top): The spec" in text
    assert "- <- depends_on from wi-e (WorkItem, todo): After A" in text
    assert "Waits on claude/feature" in text and "src/app.py" in text
    assert "An item is done when it is tested and merged." in text
    assert "- Never tag.\n- Never add an attribution line." in text
    assert "Never in other sections" not in text
    assert "## To decide (the coordinator)" in text


def test_brief_never_list_without_a_never_section(project, tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_CONFIG", str(FIXTURES / "brain" / "config.json"))   # Ada's fixture: no such sections
    b = brief.build(project, "wi-d", coordinator="local_x", budget="600k")
    assert b.never == ["- Ada decides: repository visibility, new scheduled tasks or services, anything touching "
                       "money, keys or accounts.", "- Never type a secret: Ada adds keys herself."]
    assert "no 'Definition of done' section" in "; ".join(b.warnings)
    text = brief.render(b)
    assert "**Open questions (props.open):**\n- open: which way?" in text and "600k" in text


def test_brief_classes_from_config(project, tmp_path, monkeypatch):
    cfg = tmp_path / "brain2"
    cfg.mkdir()
    (cfg / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}, "brief": {"classes": {"standard": '
                                     '{"model": "sonnet", "budget": "600k"}}}}', encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg / "config.json"))
    assert config.check() == []   # the schema knows brief
    b = brief.build(project, "wi-c")
    assert (b.model, b.budget) == ("sonnet", "600k")
    with pytest.raises(brief.BriefError):
        brief.build(project, "wi-c", task_class="huge")
    with pytest.raises(brief.BriefError):
        brief.build(project, "wi-nope")


def test_brief_says_what_to_do_after_the_merge(project):
    """wi-brain-archive-after-merge: the brief carries close-item step 5, between the coordinator's section and the
    owner's definition of done."""
    b = brief.build(project, "wi-c")
    text = brief.render(b)
    assert b.after_merge == list(brief.AFTER_MERGE) and b.as_dict()["after_merge"] == list(brief.AFTER_MERGE)
    head = "## After the merge (close-item step 5)"
    assert text.index("## To decide (the coordinator)") < text.index(head) < text.index("## Definition of done")
    for line in brief.AFTER_MERGE:
        assert line in text


def test_brief_after_merge_from_config(project, tmp_path, monkeypatch):
    cfg = tmp_path / "brain3"
    cfg.mkdir()
    (cfg / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}, "brief": {"after_merge": '
                                     '["- Ada archives every session herself."]}}', encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg / "config.json"))
    assert config.check() == []   # the schema knows brief.after_merge
    text = brief.render(brief.build(project, "wi-c"))
    assert "## After the merge (close-item step 5)\n\n- Ada archives every session herself." in text
    assert brief.AFTER_MERGE[0] not in text
    (cfg / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}, "brief": {"after_merge": []}}',
                                     encoding="utf-8")
    assert "## After the merge" not in brief.render(brief.build(project, "wi-c"))
    (cfg / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}, "brief": {"after_merge": "x"}}',
                                     encoding="utf-8")
    assert config.check()   # a string is no list of lines


def test_brief_cli_writes(project, tmp_path, capsys):
    out = tmp_path / "brief.md"
    assert cli.main(["--project", "demo", "brief", "wi-c", "--coordinator", "local_c", "--write", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Brief — wi-c")
    assert "local_c" in capsys.readouterr().out


def test_section_and_sentences():
    text = "# T\n\n## Never\n\n- a\n\n### sub\n- b\n\n## Next\n- c\n"
    assert brief.section(text, "never") == ["- a", "", "### sub", "- b"]
    assert brief.never_list(["Never do x. Then y. Never do z.\n- Ada decides: money."], ["Ada"]) == \
        ["Never do x.", "Never do z.", "Ada decides: money."]
