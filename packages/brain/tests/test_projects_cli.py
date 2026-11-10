import json
import shutil

import yaml

from brain import cli, graph, projects

from conftest import run_git


def _registry(tmp_path, monkeypatch, root, extra=""):
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\nother: {{root: ../other, journal: log.md}}\n{extra}",
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return reg


def test_registry_resolves_roots_and_layouts(tmp_path, monkeypatch, store):
    root = store.parents[1]
    _registry(tmp_path, monkeypatch, root)
    reg = projects.load()
    assert reg["demo"].root == root.resolve() and reg["demo"].stores == [root.resolve() / "notes" / "graph"]
    assert reg["other"].root == (tmp_path / "other").resolve()
    assert reg["other"].journal == (tmp_path / "other").resolve() / "log.md"
    wt = tmp_path / "wt"
    assert projects.get("other", wt).journal == wt / "log.md"  # the project's layout at another root
    assert projects.for_root(root).name == "demo"
    alone = projects.for_root(tmp_path / "alone")
    assert alone.name == "alone" and not alone.registered


def test_cli_project_journal_adr_and_item(tmp_path, monkeypatch, store, capsys):
    root = store.parents[1]
    _registry(tmp_path, monkeypatch, root)
    (root / "notes" / "journal.md").write_text("# Journal\n\n## 2026-10-31 — Day\n\n- x\n", encoding="utf-8")
    (root / "notes" / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (tmp_path / "why.md").write_text("a reason\nover two lines", encoding="utf-8")
    assert cli.main(["--project", "demo", "journal", "add", "--title", "Today", "--date", "2026-11-01", "one"]) == 0
    assert cli.main(["--project", "demo", "journal", "add", "--date", "2026-11-01", "two"]) == 0
    assert cli.main(["--project", "demo", "journal", "add", "--date", "2026-11-02", "three"]) == 1
    assert (root / "notes" / "journal.md").read_text(encoding="utf-8").endswith(
        "## 2026-11-01 — Today\n\n- one\n- two\n")
    assert cli.main(["--project", "demo", "item", "add", "wi-new", "--title", "New", "--priority", "P1",
                     "--reason", "because"]) == 0
    assert cli.main(["--project", "demo", "adr", "new", "Rule (ADR)", "--context", "c", "--decision", "d",
                     "--why", f"@{tmp_path / 'why.md'}", "--revisit", "r", "--decides", "wi-new",
                     "--date", "2026-11-01"]) == 0
    assert cli.main(["--project", "demo", "adr", "new", "--reverses", "Rule", "--decision", "undo",
                     "--date", "2026-11-02"]) == 0
    assert cli.main(["--project", "demo", "adr", "new", "Bad", "--decides", "wi-nope"]) == 1
    log = (root / "notes" / "decisions.md").read_text(encoding="utf-8")
    assert "**Why.** a reason over two lines\n" in log and "## 2026-11-02 — REVERSAL: Rule\n" in log
    assert "Bad" not in log
    edges = yaml.safe_load((store / "edges" / "work.yaml").read_text(encoding="utf-8"))
    assert {"from": "wi-new", "to": "adr-2026-11-01-rule-adr", "type": "decided_by"} in edges
    assert {"from": "adr-2026-11-02-reversal-rule", "to": "adr-2026-11-01-rule-adr", "type": "supersedes"} in edges
    nodes = {n["id"]: n for n in yaml.safe_load((store / "nodes" / "work.yaml").read_text(encoding="utf-8"))}
    assert nodes["wi-new"]["props"] == {"priority": "P1", "priority_reason": "because"}
    assert "fields left TODO" in capsys.readouterr().out


def test_cli_decision_flow_and_pending_all(tmp_path, monkeypatch, store, capsys):
    root = store.parents[1]
    other = tmp_path / "other"
    shutil.copytree(root, other)
    _registry(tmp_path, monkeypatch, root)
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: {
        "open_questions": [{"id": "wi-one", "open": "Ada decides"}], "spec_questions": [],
        "blocked_on_owner": [], "proposed_specs": []})
    base = ["--project", "demo", "decision"]
    assert cli.main(base + ["ask", "--title", "Pick", "--question", "Which?", "--option", "A: first",
                            "--option", "B", "--why", "simplest", "--at", "2026-11-01T08:00:00Z"]) == 0
    assert cli.main(base + ["ask", "--title", "Bad", "--question", "Q", "--option", "A", "--why", "w"]) == 1
    assert (root / "notes" / "decision_queue.md").is_file()
    assert cli.main(base + ["answer", "pick", "B", "--at", "2026-11-01T09:00:00Z"]) == 0
    assert cli.main(base + ["ack", "pick", "--applied", "wi-one", "--at", "2026-11-01T10:00:00Z"]) == 0
    capsys.readouterr()
    assert cli.main(["decision", "pending", "--all", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [d["project"] for d in data] == ["demo", "other"]
    assert data[0]["waiting_on_owner"] == 1 and data[0]["owner"] == "Ada" and data[0]["stores"][0]["open_questions"][0]["id"] == "wi-one"
    assert cli.main(["decision", "pending", "--all"]) == 0
    out = capsys.readouterr().out
    assert "all: 2 waiting on Ada in 2 of 2 project(s), 0 answer(s) to integrate" in out
    assert "## Archived (1)" in (root / "notes" / "decision_queue.md").read_text(encoding="utf-8")


def test_refresh_writes_in_a_worktree_and_only_checks_main(tmp_path, monkeypatch, git_repo, capsys):
    (git_repo / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(graph, "research_graph", lambda root, store, *a: calls.append((root.name, a)) or 0)
    _registry(tmp_path, monkeypatch, git_repo)
    assert cli.main(["--project", "demo", "refresh"]) == 0
    assert calls == [("repo", ("check",))]  # main checkout on main: check only
    assert "check only" in capsys.readouterr().out
    calls.clear()
    run_git(git_repo, "checkout", "-q", "-b", "feature")
    assert cli.main(["--project", "demo", "refresh"]) == 0
    assert calls == [("repo", ("sync", "--write")), ("repo", ("kanban", "--write")), ("repo", ("check",))]
    calls.clear()
    assert cli.main(["refresh", "--all"]) == 0  # the second project's root does not exist: skipped
    assert "other: " in capsys.readouterr().out and len(calls) == 3


def test_adr_new_writes_nothing_when_an_edge_is_impossible(tmp_path, monkeypatch, store):
    root = store.parents[1]
    _registry(tmp_path, monkeypatch, root)
    log = root / "notes" / "decisions.md"
    log.write_text("# Decisions\n\n## 2026-10-30 — Old\n\n**Context.** c\n", encoding="utf-8")
    schema = store / "schema.yaml"
    schema.write_text(schema.read_text(encoding="utf-8").replace("supersedes, ", ""), encoding="utf-8")
    before = log.read_text(encoding="utf-8")
    assert cli.main(["--project", "demo", "adr", "new", "--reverses", "Old", "--decision", "undo"]) == 1
    assert log.read_text(encoding="utf-8") == before


def test_adr_new_makes_the_stores_edges_folder_and_refuses_a_stray_path(tmp_path, monkeypatch, store):
    """The edge of --decides goes to the store's edges/ folder even when the store has none yet; a --edges-file that
    leaves edges/ (the store's own path given twice, the 2026-11-09 incident: notes/graph/edges/rules.yaml, which
    raised FileNotFoundError after the ADR was appended) is refused before the log is written, and makes no folder."""
    import shutil
    root = store.parents[1]
    _registry(tmp_path, monkeypatch, root)
    log = root / "notes" / "decisions.md"
    log.write_text("# Decisions\n", encoding="utf-8")
    assert cli.main(["--project", "demo", "item", "add", "wi-new", "--title", "New"]) == 0
    before = log.read_text(encoding="utf-8")
    assert cli.main(["--project", "demo", "adr", "new", "Stray", "--decision", "d", "--decides", "wi-new",
                     "--edges-file", "notes/graph/edges/rules.yaml"]) == 1
    assert log.read_text(encoding="utf-8") == before and not (store / "notes").exists()
    shutil.rmtree(store / "edges")
    (store / "nodes" / "work.yaml").write_text((store / "nodes" / "work.yaml").read_text(encoding="utf-8"),
                                               encoding="utf-8")
    assert cli.main(["--project", "demo", "adr", "new", "Rule", "--context", "c", "--decision", "d", "--why", "w",
                     "--revisit", "r", "--decides", "wi-new", "--edges-file", "edges/decisions.yaml",
                     "--date", "2026-11-01"]) == 0
    assert "decided_by" in (store / "edges" / "decisions.yaml").read_text(encoding="utf-8")


def test_item_add_refuses_a_layer_file_outside_the_store_before_writing_the_node(tmp_path, monkeypatch, store):
    root = store.parents[1]
    _registry(tmp_path, monkeypatch, root)
    nodes = (store / "nodes" / "work.yaml").read_text(encoding="utf-8")
    assert cli.main(["--project", "demo", "item", "add", "wi-x", "--title", "X", "--edges-file", "../edges.yaml"]) == 1
    assert (store / "nodes" / "work.yaml").read_text(encoding="utf-8") == nodes


def test_adr_new_without_a_graph_store_says_so_and_writes_nothing(tmp_path, monkeypatch, capsys):
    root = tmp_path / "bare"
    (root / "notes").mkdir(parents=True)
    log = root / "notes" / "decisions.md"
    log.write_text("# Decisions\n", encoding="utf-8")
    monkeypatch.chdir(root)
    assert cli.main(["--root", str(root), "adr", "new", "Rule", "--decision", "d"]) == 1
    assert "no graph store here" in capsys.readouterr().err
    assert log.read_text(encoding="utf-8") == "# Decisions\n"
