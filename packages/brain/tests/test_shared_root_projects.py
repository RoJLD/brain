"""wi-brain-shared-root-projects: two registered projects at one root. The first registered owns the root (its
records, its decision queue, its rendered files, its views in notes/, its repos); the next keeps its own store,
journal, decision log and views beside its store, and its passes never write the owner's files. Run with the real
research_graph engine, nothing faked."""

import json
import os

import pytest
from research_graph.cli import main as research_graph

from brain import cli, projects

OWNER_VIEWS = ("notes/kanban_graph.md", "notes/roadmap_graph.md", "notes/decision_queue.md")
PROG = ("  title: a programme kept in the same repo\n  stores: [prog/graph]\n  journal: prog/journal.md\n"
        "  decisions: prog/decisions.md\n")


def _root(tmp_path):
    """lab's repo: its store and ADR log from the engine's examples, then prog's store, log and journal beside it."""
    root = tmp_path / "lab"
    assert research_graph(["--store", str(root / "notes" / "graph"), "--repo-root", str(root), "init", "--owner",
                           "Ada", "--examples"]) == 0
    assert research_graph(["--store", str(root / "prog" / "graph"), "--repo-root", str(root), "--decisions",
                           "prog/decisions.md", "--views", "prog", "init", "--owner", "Ada"]) == 0
    (root / "prog" / "graph" / "nodes" / "work.yaml").write_text(
        "- {id: wi-prog-first, type: WorkItem, status: todo, title: \"The programme's first step\"}\n",
        encoding="utf-8")
    with (root / "prog" / "decisions.md").open("a", encoding="utf-8", newline="\n") as f:
        f.write("\n## 2026-11-05 — The programme's own call\n\n**Context.** c\n\n**Decision.** d\n")
    (root / "prog" / "journal.md").write_text("# Journal\n", encoding="utf-8")
    (root / "notes" / "journal.md").write_text("# Journal\n", encoding="utf-8")
    (root / "records" / "ddr").mkdir(parents=True)  # the root's records: its decision queue is written
    return root


def _registry(tmp_path, monkeypatch, root, prog=PROG):
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    text = f"lab:\n  root: {root.as_posix()}\n  title: the lab\n"
    reg.write_text(text + (f"prog:\n  root: {root.as_posix()}\n{prog}" if prog is not None else ""), encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))


def _bytes(root, rels):
    return {rel: (root / rel).read_bytes() for rel in rels}


def _ids(store):
    return set(projects.node_ids(store))


def test_two_projects_at_one_root_keep_their_own_views_and_logs(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root, prog=None)
    assert cli.main(["sync", "--all"]) == 0  # lab alone: its views as they are without prog
    alone = _bytes(root, OWNER_VIEWS)
    _registry(tmp_path, monkeypatch, root)
    assert cli.main(["sync", "--all"]) == 0
    out = capsys.readouterr().out
    assert _bytes(root, OWNER_VIEWS) == alone  # prog's passes never wrote the owner's views
    board = (root / "prog" / "kanban_graph.md").read_text(encoding="utf-8")
    assert "wi-prog-first" in board and "wi-first-step" not in board and (root / "prog" / "roadmap_graph.md").exists()
    assert "prog shares its root with lab" in out
    lab_adrs = {i for i in _ids(root / "notes" / "graph") if i.startswith("adr-")}
    assert lab_adrs and not lab_adrs & _ids(root / "prog" / "graph")  # no ADR of notes/decisions.md came over
    gen = (root / "prog" / "graph" / "nodes" / "_generated_decisions.yaml").read_text(encoding="utf-8")
    assert 'anchor: "prog/decisions.md#2026-11-05-the-programme-s-own-call"' in gen
    assert cli.main(["check", "--all"]) == 0
    assert "registry: 2 project(s), 2 store(s), ids unique" in capsys.readouterr().out


def test_the_first_registered_owns_the_root_and_the_next_spans_no_repo(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root)
    reg = projects.load()
    assert projects.for_root(root).name == "lab"
    assert reg["lab"].shares_root_with == "" and reg["prog"].shares_root_with == "lab"
    assert projects.repos_of(reg["prog"]) == [] and [r.path for r in projects.repos_of(reg["lab"])] == [root]
    assert [p.name for p in projects.at_root(root)] == ["lab", "prog"]
    assert projects.get("prog", root).shares_root_with == "lab"  # also at a given root (a worktree's)
    assert projects.check() == []


def test_sync_and_check_without_all_cover_every_project_at_the_root(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root)
    monkeypatch.chdir(root)
    assert cli.main(["sync"]) == 0
    out = capsys.readouterr().out
    assert "== lab: " in out and "== prog: " in out
    assert (root / "prog" / "kanban_graph.md").exists() and (root / "notes" / "kanban_graph.md").exists()
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "== lab: " in out and "== prog: " in out and "check: 0 project(s) failed" in out
    assert cli.main(["--project", "prog", "check"]) == 0  # one named: that one only
    assert "== lab" not in capsys.readouterr().out
    assert cli.main(["item", "add", "wi-prog-second", "--title", "Second", "--project", "prog"]) == 0
    assert "wi-prog-second" in (root / "prog" / "graph" / "nodes" / "work.yaml").read_text(encoding="utf-8")
    assert cli.main(["journal", "add", "--project", "prog", "--title", "Day", "--date", "2026-11-05", "x"]) == 0
    assert "## 2026-11-05 — Day" in (root / "prog" / "journal.md").read_text(encoding="utf-8")
    assert (root / "notes" / "journal.md").read_text(encoding="utf-8") == "# Journal\n"


def test_a_project_at_a_shared_root_that_would_write_the_owners_files_is_not_loaded(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root, prog="  stores: [prog/graph]\n")  # the defaults are lab's files
    assert projects.check() == [
        "project prog: shares its root with lab: it declares no journal of its own (the default is lab's: give it "
        "journal:)",
        "project prog: shares its root with lab: it declares no decision log of its own (the default is lab's: give it "
        "decisions:)"]
    assert list(projects.load()) == ["lab"]  # until it declares them, no command writes lab's files through it
    with pytest.raises(SystemExit, match="'prog' is not loaded: project prog: shares its root with lab: it declares"):
        cli.main(["journal", "add", "--project", "prog", "--title", "Day", "x"])
    assert (root / "notes" / "journal.md").read_text(encoding="utf-8") == "# Journal\n"
    _registry(tmp_path, monkeypatch, root, prog="  stores: []\n  journal: prog/journal.md\n  decisions: prog/d.md\n")
    assert projects.check() == ["project prog: shares its root with lab: it declares no store of its own (the default "
                                "is lab's: give it stores:)"]
    _registry(tmp_path, monkeypatch, root, prog=PROG.replace("prog/graph", "notes/graph"))
    assert projects.check() == ["project prog: shares its root with lab: its store notes/graph is lab's too (give it "
                                "its own: stores:)"]
    _registry(tmp_path, monkeypatch, root, prog=PROG.replace("prog/decisions.md", "notes/scientific_decisions.md"))
    assert projects.check() == [  # research_graph covers it for lab's store by default
        "project prog: shares its root with lab: its decision log notes/scientific_decisions.md is lab's too (give it "
        "its own: decisions:)"]
    _registry(tmp_path, monkeypatch, root, prog=PROG.replace("prog/decisions.md", "../elsewhere/decisions.md"))
    assert projects.check() == ["project prog: its decision log ../elsewhere/decisions.md is outside its root (a "
                                "decision's anchor is a path inside it)"]


def test_a_store_whose_views_folder_another_store_uses_is_never_synced(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root, prog=PROG.replace("[prog/graph]", "[notes/prog-graph]"))
    clash = ("project prog: its store notes/prog-graph writes its views in notes, as lab's store notes/graph does "
             "(give each store a folder of its own)")
    assert projects.check() == [clash]
    before = (root / "notes" / "kanban_graph.md").read_bytes()
    assert cli.main(["--project", "prog", "sync"]) == 1
    assert f"error: {clash}: not synced" in capsys.readouterr().out
    assert (root / "notes" / "kanban_graph.md").read_bytes() == before  # lab's board is not written over
    assert cli.main(["--project", "prog", "check"]) == 1


def test_a_second_store_of_a_project_keeps_its_views_beside_it_and_covers_no_decision_log(tmp_path, monkeypatch,
                                                                                          capsys):
    root = tmp_path / "team"
    assert research_graph(["--store", str(root / "notes" / "graph"), "--repo-root", str(root), "init",
                           "--examples"]) == 0
    assert research_graph(["--store", str(root / "ops" / "graph"), "--repo-root", str(root), "--no-decisions",
                           "--views", "ops", "init"]) == 0
    (root / "ops" / "graph" / "nodes" / "work.yaml").write_text(
        "- {id: wi-ops-first, type: WorkItem, status: todo, title: \"Operations first\"}\n", encoding="utf-8")
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"team:\n  root: {root.as_posix()}\n  stores: [notes/graph, ops/graph]\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    before = (root / "notes" / "kanban_graph.md").read_bytes()
    assert cli.main(["sync", "--all"]) == 0
    assert (root / "notes" / "kanban_graph.md").read_bytes() == before  # the second store's board is its own
    assert "wi-ops-first" in (root / "ops" / "kanban_graph.md").read_text(encoding="utf-8")
    assert not any(i.startswith("adr-") for i in _ids(root / "ops" / "graph"))
    assert cli.main(["check", "--all"]) == 0
    assert projects.views_dir(projects.load()["team"], root / "ops" / "graph") == root / "ops"
    capsys.readouterr()


def test_the_examples_registry_checks_clean(monkeypatch):
    example = os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples", "projects.yaml")
    monkeypatch.setenv("BRAIN_PROJECTS", os.path.abspath(example))
    assert projects.check() == []
    reg = projects.load()
    assert reg["prog"].shares_root_with == "lab" and "upstream" in projects.readonly()


def test_a_module_map_and_the_resume_pack_name_the_views_beside_the_store(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    (root / "prog" / "graph" / "modules.yaml").write_text(
        "- {id: M1, name: first-module, brick: M, phase: MVP, status: tree}\n", encoding="utf-8")
    _registry(tmp_path, monkeypatch, root)
    assert cli.main(["sync", "--all"]) == 0
    assert "first-module" in (root / "prog" / "modules_graph.md").read_text(encoding="utf-8")
    assert not (root / "notes" / "modules_graph.md").exists()
    capsys.readouterr()
    assert cli.main(["--project", "prog", "resume", "--budget", "0", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "prog/kanban_graph.md" in out and "notes/kanban_graph.md" not in out


def test_the_roots_records_queue_and_audit_view_stay_the_owners(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root)
    assert cli.main(["--project", "prog", "decision", "ask", "--title", "Pick", "--question", "Which?", "--option",
                     "A: a", "--option", "B: b", "--why", "w", "--at", "2026-11-02T10:00:00Z"]) == 0
    queue = (root / "notes" / "decision_queue.md").read_text(encoding="utf-8")
    assert queue.startswith("# Decision queue — lab\n") and "Pick" in queue  # asked from prog: the root's queue
    capsys.readouterr()
    assert cli.main(["decision", "pending", "--all", "--json"]) == 0
    data = {d["project"]: d for d in json.loads(capsys.readouterr().out)}
    assert [e["id"] for e in data["lab"]["pending"]] == ["ddr-2026-11-02-pick"] and data["prog"]["pending"] == []
    assert cli.main(["decision", "view", "--all"]) == 0
    assert capsys.readouterr().out.count("# Decision queue — ") == 1
    with pytest.raises(SystemExit, match="prog shares its root with lab: notes/audit.md is lab's"):
        cli.main(["--project", "prog", "audit", "--write"])


def test_a_project_not_loaded_keeps_its_guards_and_claims_any_kind_of_file(tmp_path, monkeypatch):
    from brain import guards
    root = _root(tmp_path)
    (tmp_path / "lab-prod").mkdir()
    _registry(tmp_path, monkeypatch, root, prog="  stores: [prog/graph]\n  production: [../lab-prod]\n")
    assert "prog" not in projects.load()  # it declares no journal nor decision log of its own
    prod = {os.path.normcase(os.path.abspath(p)) for p in guards.production_roots()}
    assert os.path.normcase(str(tmp_path / "lab-prod")) in prod  # a refusal to load never lifts a guard
    _registry(tmp_path, monkeypatch, root, prog=PROG.replace("prog/journal.md", "notes/decisions.md"))
    assert projects.check() == ["project prog: shares its root with lab: its journal notes/decisions.md is lab's "
                                "decision log (give it its own: journal:)"]


def test_a_store_the_project_does_not_list_keeps_the_defaults(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root)
    lab, prog = projects.load()["lab"], projects.load()["prog"]
    assert projects.layout(lab, root / "graph") == [] and projects.views_dir(lab, root / "graph") == root / "notes"
    assert projects.layout(lab, root / "notes" / "graph") == []
    assert projects.layout(prog, root / "prog" / "graph") == ["--views", "prog", "--decisions", "prog/decisions.md"]
    team = projects.Project("team", root, [root / "notes" / "graph", root / "ops" / "graph"])
    assert projects.layout(team, root / "ops" / "graph") == ["--views", "ops", "--no-decisions"]


def test_a_store_named_by_store_runs_as_the_project_that_lists_it(tmp_path, monkeypatch, capsys):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root)
    monkeypatch.chdir(root)
    assert cli.main(["sync", "--offline"]) == 0
    owner = _bytes(root, OWNER_VIEWS)
    gen = root / "prog" / "graph" / "nodes" / "_generated_decisions.yaml"
    stub = gen.read_bytes()
    capsys.readouterr()
    assert cli.main(["--store", "prog/graph", "sync", "--offline"]) == 0  # no --project: prog's store is prog's
    out = capsys.readouterr().out
    assert "prog shares its root with lab" in out and "== lab" not in out
    assert _bytes(root, OWNER_VIEWS) == owner  # lab's board and roadmap are not written over with prog's
    assert gen.read_bytes() == stub  # prog's ADR stub stays prog's own, not one of notes/decisions.md
    assert "wi-prog-first" in (root / "prog" / "kanban_graph.md").read_text(encoding="utf-8")
    assert cli.main(["--store", str(root / "prog" / "graph"), "check"]) == 0
    assert "prog shares its root with lab" in capsys.readouterr().out
    assert cli.main(["--store", "notes/graph", "check"]) == 0  # the owner's store: the owner, as before
    assert "prog shares its root" not in capsys.readouterr().out


def test_store_at_a_shared_root_fails_closed_when_its_project_is_not_loaded_or_none_lists_it(tmp_path, monkeypatch):
    """Without --project, --store never runs as the owner with its defaults at a root several projects share: the
    store of a project not loaded is refused with the reason, and a store no project lists is refused too."""
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root, prog="  stores: [prog/graph]\n")  # prog not loaded: no journal, no log
    monkeypatch.chdir(root)
    before = {rel: (root / rel).read_bytes() if (root / rel).exists() else None for rel in OWNER_VIEWS}
    with pytest.raises(SystemExit, match="'prog' is not loaded: project prog: shares its root with lab"):
        cli.main(["--store", "prog/graph", "sync", "--offline"])
    assert {rel: (root / rel).read_bytes() if (root / rel).exists() else None for rel in OWNER_VIEWS} == before
    _registry(tmp_path, monkeypatch, root)  # prog loaded; ops/graph is neither's
    with pytest.raises(SystemExit, match="no registered project lists it, at a root 2 projects share"):
        cli.main(["--store", "ops/graph", "check"])
    _registry(tmp_path, monkeypatch, root, prog=None)  # lab alone: a store it does not list keeps the defaults
    assert projects.lister((root / "ops" / "graph").resolve(), root) is None


def test_an_edge_of_a_later_store_to_a_stub_the_first_store_derives_says_why(tmp_path, monkeypatch, capsys):
    """Before wi-brain-shared-root-projects every store ran with research_graph's defaults, so a second store derived
    the stubs of notes/decisions.md too and an item of it could be decided_by one; it now covers no decision log."""
    root = tmp_path / "team"
    assert research_graph(["--store", str(root / "notes" / "graph"), "--repo-root", str(root), "init",
                           "--examples"]) == 0
    ops = root / "ops" / "graph"
    assert research_graph(["--store", str(ops), "--repo-root", str(root), "init", "--examples"]) == 0  # as before
    adr = sorted(i for i in _ids(ops) if i.startswith("adr-"))[0]
    (ops / "nodes" / "work.yaml").write_text(
        "- {id: wi-ops-first, type: WorkItem, status: todo, title: \"Operations first\"}\n", encoding="utf-8")
    (ops / "edges" / "work.yaml").write_text(f"- {{from: wi-ops-first, to: {adr}, type: decided_by}}\n",
                                             encoding="utf-8")
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"team:\n  root: {root.as_posix()}\n  stores: [notes/graph, ops/graph]\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    why = (f"error: ops/graph: edge wi-ops-first -> {adr}: that ADR stub is notes/graph's only (a store listed "
           "after its project's first covers no decision log): move the edge to notes/graph, or remove it")
    assert cli.main(["sync", "--all", "--offline"]) == 1
    assert why in capsys.readouterr().out
    assert cli.main(["check", "--all"]) == 1
    assert why in capsys.readouterr().out
    (ops / "edges" / "work.yaml").write_text("", encoding="utf-8")  # the edge moved away: nothing more to say
    assert cli.main(["sync", "--all", "--offline"]) == 0
    assert cli.main(["check", "--all"]) == 0
    assert "that ADR stub" not in capsys.readouterr().out


def test_an_owner_with_no_store_listed_still_holds_notes_graph(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _registry(tmp_path, monkeypatch, root, prog=PROG.replace("prog/graph", "notes/graph"))
    reg = tmp_path / "brain" / "projects.yaml"
    reg.write_text(reg.read_text(encoding="utf-8").replace("  title: the lab\n", "  title: the lab\n  stores: []\n"),
                   encoding="utf-8")
    assert projects.load()["lab"].stores == []  # brain sync and check run its notes/graph all the same
    assert list(projects.load()) == ["lab"]
    assert projects.check() == ["project prog: shares its root with lab: its store notes/graph is lab's too (give it "
                                "its own: stores:)"]


def test_a_store_listed_twice_is_refused_and_keeps_its_place(tmp_path, monkeypatch):
    root = _root(tmp_path)
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"lab:\n  root: {root.as_posix()}\n  stores: [notes/graph, notes/graph]\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    lab = projects.load()["lab"]
    assert projects.layout(lab, root / "notes" / "graph") == []  # the first store keeps the defaults
    assert projects.check() == ["project lab: its store notes/graph is listed twice"]
