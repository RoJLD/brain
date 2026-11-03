"""wi-brain-project-views: the registry's keys, --project / --all on every view, brain status, brain projects, and
the ids unique across every store of every project."""

import json
import shutil
import sys
import types
from pathlib import Path

import pytest

from brain import cli, codeindex, graph, projects, stacks, status

from test_stacks import REGISTRY as STACKS, Fake



def _registry(tmp_path, monkeypatch, text):
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    reg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return reg


def _two(tmp_path, monkeypatch, store, extra=""):
    """demo (the fixture's store) and other (a copy of it, so every id is shared), plus ``extra``."""
    root = store.parents[1]
    other = tmp_path / "other"
    shutil.copytree(root, other)
    _registry(tmp_path, monkeypatch, f"demo: {{root: {root.as_posix()}}}\nother:\n  root: {other.as_posix()}\n{extra}")
    return root, other


# --- the registry ---

def test_registry_reads_lists_titles_ledgers_and_the_reserved_plugin_key(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, """\
lab:
  root: ../lab
  title: a lab
  journal: [notes/journal.md, notes/notebook.md]
  decisions: [notes/decisions.md, notes/sdr.md]
  ledgers: {runs: data/runs.jsonl}
  shared_ids: {adr-x: the same decision in two logs}
  plugin: demo_lab.brain_plugin
plain: {root: ../plain}
""")
    lab, plain = projects.load()["lab"], projects.load()["plain"]
    root = (tmp_path / "lab").resolve()
    assert lab.title == "a lab" and lab.plugin == "demo_lab.brain_plugin"
    assert lab.journal == root / "notes/journal.md" and lab.journals[1] == root / "notes/notebook.md"
    assert lab.decisions == root / "notes/decisions.md" and lab.decision_logs[1] == root / "notes/sdr.md"
    assert lab.ledgers == {"runs": root / "data/runs.jsonl"} and lab.shared_ids == {"adr-x": "the same decision in "
                                                                                             "two logs"}
    assert plain.journals == [plain.journal] and plain.title == "" and plain.plugin is None  # the defaults
    assert projects.get("lab", tmp_path / "wt").journals[1] == tmp_path / "wt" / "notes/notebook.md"
    assert projects.check() == []


def test_registry_check_refuses_what_load_tolerates(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, """\
typo: {root: ., storse: [notes/graph], title: [x]}
shapes: {journal: 3, ledgers: [a.jsonl], shared_ids: {adr-x: short}, stacks: [x], repos: [{path: ., lang: go}]}
text: not a mapping
""")
    reg = projects.load()  # never fails: the other commands keep working
    assert reg["shapes"].journals[0].name == "journal.md" and reg["text"].stores
    errors = projects.check()
    assert "project typo: unknown key(s) storse (brain projects --keys lists them)" in errors
    assert "project typo: title is a string" in errors
    assert "project shapes: journal is a path or a list of paths" in errors
    assert "project shapes: ledgers is a mapping of name -> path" in errors
    assert "project shapes: shared_ids 'adr-x': a reason of 15 characters at least" in errors
    assert "project shapes: stacks is a mapping or a file name" in errors
    assert "project shapes: repos[0]: lang is py or ts" in errors
    assert "project text: an entry is a mapping (brain projects --keys)" in errors


def test_collisions_across_stores_waivers_and_stale_waivers(tmp_path, monkeypatch, store):
    _two(tmp_path, monkeypatch, store)
    found = projects.collisions(list(projects.load().values()))
    assert found["stores"] == 2 and found["stale"] == []
    assert [c["id"] for c in found["collisions"]] == ["adr-2026-10-30-x", "ms-x", "spec-x", "wi-one", "wi-two"]
    assert found["collisions"][3] == {"id": "wi-one", "where": ["demo:notes/graph/nodes/work.yaml",
                                                                "other:notes/graph/nodes/work.yaml"], "waived": ""}
    _two(tmp_path / "again", monkeypatch, store,
         "  shared_ids: {wi-one: copied on purpose for the test, wi-gone: no longer anywhere at all}\n")
    found = projects.collisions(list(projects.load().values()))
    assert found["collisions"][3]["waived"] == "other: copied on purpose for the test"
    assert found["stale"] == ["other: wi-gone"]


# --- check --all, sync --all, refresh --all ---

def test_check_all_fails_on_a_shared_id_and_passes_once_waived(tmp_path, monkeypatch, store, capsys):
    calls = []
    monkeypatch.setattr(graph, "research_graph", lambda root, st, *a: calls.append((root.name, a)) or 0)
    root, other = _two(tmp_path, monkeypatch, store)
    for f in (other / "notes" / "graph" / "nodes").glob("*.yaml"):
        f.write_text(f.read_text(encoding="utf-8").replace("wi-two", "wi-other-two").replace("ms-x", "ms-other")
                     .replace("spec-x", "spec-other").replace("adr-2026-10-30-x", "adr-2026-10-31-y"), encoding="utf-8")
    assert cli.main(["check", "--all"]) == 1
    out = capsys.readouterr().out
    assert calls == [(root.name, ("check",)), ("other", ("check",))]
    assert ("error: id wi-one is in demo:notes/graph/nodes/work.yaml, other:notes/graph/nodes/work.yaml (rename one, "
            "or waive it under shared_ids: with its reason)") in out
    assert "registry: 2 project(s), 2 store(s), 1 error(s)" in out and "check: 1 project(s) failed: registry" in out
    reg = Path(projects.registry_file())
    reg.write_text(reg.read_text(encoding="utf-8") + "  shared_ids: {wi-one: the fixture copies this item}\n",
                   encoding="utf-8")
    assert cli.main(["check", "--all"]) == 0
    out = capsys.readouterr().out
    assert "waived: id wi-one is in" in out and "(shared_ids of other: the fixture copies this item)" in out
    assert "registry: 2 project(s), 2 store(s), ids unique" in out
    monkeypatch.chdir(root)
    assert cli.main(["check"]) == 0  # one project: no registry line
    assert "registry:" not in capsys.readouterr().out


def test_sync_all_skips_a_main_checkout_and_refresh_all_checks_the_registry(tmp_path, monkeypatch, git_repo,
                                                                             capsys):
    (git_repo / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(graph, "research_graph", lambda root, st, *a: calls.append((root.name, a)) or 0)
    _registry(tmp_path, monkeypatch, f"demo: {{root: {git_repo.as_posix()}}}\n")
    assert cli.main(["sync", "--all"]) == 0
    assert calls == [] and "(main checkout on main: not written, skipped)" in capsys.readouterr().out
    assert cli.main(["refresh", "--all"]) == 0
    out = capsys.readouterr().out
    assert calls == [("repo", ("check",))] and "== registry" in out and "refresh: 0 project(s) failed" in out


# --- --project after the subcommand, --project with --all ---

def test_project_goes_after_the_subcommand_and_not_with_all(tmp_path, monkeypatch, store, capsys):
    root, _ = _two(tmp_path, monkeypatch, store)
    (root / "notes" / "journal.md").write_text("# Journal\n", encoding="utf-8")
    assert cli.main(["journal", "add", "--project", "demo", "--title", "Day", "--date", "2026-11-02", "x"]) == 0
    assert "## 2026-11-02 — Day" in (root / "notes" / "journal.md").read_text(encoding="utf-8")
    assert cli.main(["item", "set", "wi-two", "status=done", "--project", "demo"]) == 0
    with pytest.raises(SystemExit, match="--project or --all, not both"):
        cli.main(["status", "--project", "demo", "--all"])
    with pytest.raises(SystemExit, match="--project or --all, not both"):
        cli.main(["--project", "demo", "decision", "pending", "--all"])
    with pytest.raises(SystemExit, match="unknown project 'nope'"):
        cli.main(["health", "--project", "nope"])


def test_decision_view_all_prints_every_board_and_writes_none(tmp_path, monkeypatch, store, capsys):
    _two(tmp_path, monkeypatch, store)
    assert cli.main(["decision", "view", "--all"]) == 0
    out = capsys.readouterr().out
    assert "# Decision queue — demo\n" in out and "# Decision queue — other\n" in out
    with pytest.raises(SystemExit, match="takes one project"):
        cli.main(["decision", "view", "--all", "--write"])
    assert cli.main(["milestone", "suggest", "--all"]) == 0
    out = capsys.readouterr().out
    assert "== demo: " in out and "== other: " in out and out.count("suggest: ") == 2
    with pytest.raises(SystemExit, match="takes one project"):
        cli.main(["milestone", "suggest", "--all", "--write"])


# --- up / down / health / index --project ---

def test_stacks_narrowed_to_a_project_keep_their_dependencies(tmp_path, monkeypatch, capsys):
    f = tmp_path / "projects.yaml"
    f.write_text(STACKS.format(tmp=tmp_path.as_posix(), extra=""), encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    fake = Fake(monkeypatch)
    assert cli.main(["up", "--project", "app"]) == 0  # app's gitnexus, after infra's docker
    assert [c[1] for c in fake.calls] == ["docker-desktop", "docker compose up -d"]
    assert capsys.readouterr().out.splitlines()[-1].startswith("gitnexus OK")
    assert cli.main(["health", "--project", "infra"]) == 0
    assert capsys.readouterr().out == "docker OK\n"
    assert cli.main(["--project", "infra", "down", "gitnexus"]) == 2
    assert "gitnexus: not a stack of infra (it declares docker)" in capsys.readouterr().err
    assert stacks.of_project(stacks.load(), "app", []) == ["gitnexus"]


def test_code_index_narrowed_to_a_project(tmp_path):
    repos = {"a": codeindex.Repo("a", "one", tmp_path), "b": codeindex.Repo("b", "two", tmp_path)}
    assert list(codeindex.of_project(repos, "two")) == ["b"] and list(codeindex.of_project(repos, None)) == ["a", "b"]


# --- brain status ---

STATUS_STORE_EXTRA = (
    "- {id: ms-done, type: Milestone, status: reached, title: \"Done\"}\n"
    "- {id: wi-three, type: WorkItem, status: todo, title: \"Third\", props: {priority: P1, open: \"Ada decides\"}}\n"
    "- {id: wi-four, type: WorkItem, status: done, title: \"Fourth\"}\n"
    "- {id: wi-five, type: WorkItem, status: todo, title: \"Fifth\", props: {priority: P2}}\n")


def _status_project(tmp_path, monkeypatch, store):
    root = store.parents[1]
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(STATUS_STORE_EXTRA)
    (store / "edges" / "work.yaml").write_text(
        "- {from: wi-one, to: ms-x, type: part_of}\n- {from: wi-four, to: ms-x, type: part_of}\n"
        "- {from: wi-five, to: wi-two, type: depends_on}\n", encoding="utf-8")
    (root / "notes" / "journal.md").write_text("# Journal\n\n## 2026-11-01 — A\n\n- a\n\n## 2026-11-02 — B\n",
                                              encoding="utf-8")
    ddr = root / "records" / "ddr"
    ddr.mkdir(parents=True)
    for name, st, blocking in (("ddr-a", "pending", "true"), ("ddr-b", "pending", "false"),
                               ("ddr-c", "answered", "false")):
        (ddr / f"{name}.yaml").write_text(f"id: {name}\nstatus: {st}\nblocking: {blocking}\n", encoding="utf-8")
    (root / "records" / "ar").mkdir()
    (root / "records" / "ar" / "2026-11.jsonl").write_text('{"id": 1}\n{"id": 2}\n', encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "runs.jsonl").write_text("{}\n{}\n{}\n", encoding="utf-8")
    _registry(tmp_path, monkeypatch, f"demo:\n  root: {root.as_posix()}\n  title: the demo\n"
                                     "  ledgers: {runs: data/runs.jsonl, gone: data/gone.jsonl}\n"
                                     "far: {root: ../nowhere}\n")
    return root


def test_status_quick_counts_items_decisions_milestones_and_records(tmp_path, monkeypatch, store, capsys):
    _status_project(tmp_path, monkeypatch, store)
    assert cli.main(["status", "--project", "demo", "--quick", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)["projects"][0]
    assert d["items"] == {"total": 5, "by_status": {"todo": 3, "doing": 1, "done": 1},
                          "open_by_priority": {"P0": 1, "P1": 1, "P2": 1, "none": 1},
                          "frontier": 2, "frontier_p0_p1": 2}  # wi-five waits on wi-two (doing)
    assert d["decisions"] == {"pending": 2, "blocking": 1, "answered": 1, "open_questions": 1,
                              "queue": {"decision": 3, "action": 0, "permission": 0,
                                        "bands": {"now": 1, "week": 1, "later": 1}}}  # brain queue's counts, bands
    assert d["milestones"] == {"reached": 1, "pending": [{"id": "ms-x", "title": "Milestone X", "items": 2,
                                                          "done": 1}]}
    assert d["journals"] == [{"path": "notes/journal.md", "exists": True, "last": "2026-11-02"}]
    assert d["records"] == {"ddr": 3, "sr": 0, "ar": 2}
    assert [(x["name"], x["lines"]) for x in d["ledgers"]] == [("runs", 3), ("gone", None)]
    assert d["audit"] == {"skipped": "skipped (--quick)"} and d["digest"] is None  # brain digest, none written
    assert cli.main(["status", "--project", "demo", "--quick"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"demo ({store.parents[1]}): the demo\n")
    assert "  decisions   2 waiting on Ada (1 blocking), 1 answered to integrate, 1 open question(s) on items" in out
    assert "  milestones  1 reached, 1 pending: ms-x 1/2" in out
    assert "  ledger gone data/gone.jsonl missing" in out
    assert "  journal     journal.md last entry 2026-11-02\n" in out and "  records     3 DDR, 0 SR, 2 AR\n" in out


def test_status_all_totals_ids_and_a_missing_project(tmp_path, monkeypatch, store, capsys):
    _status_project(tmp_path, monkeypatch, store)
    assert cli.main(["status", "--all", "--quick", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [(p["project"], p["found"]) for p in data["projects"]] == [("demo", True), ("far", False)]
    assert data["total"]["items"]["total"] == 5 and data["total"]["decisions"]["pending"] == 2
    assert data["ids"] == {"stores": 1, "collisions": [], "stale": []}
    assert cli.main(["status", "--all", "--quick"]) == 0
    out = capsys.readouterr().out
    assert "far (" in out and "not found on this machine" in out and "\nall (1 of 2 project(s) found)\n" in out
    assert "  ids         0 shared by two stores or more, 0 waived, across 1 store(s)" in out


def test_status_probes_audit_stacks_and_the_code_index(tmp_path, monkeypatch, store):
    root = _status_project(tmp_path, monkeypatch, store)
    p = projects.load()["demo"]
    monkeypatch.setattr(status, "audit_of", lambda p: {"counts": {"P0": 1, "P1": 0, "P2": 2, "info": 3}, "repos": 1,
                                                       "unreadable": []})
    s = stacks.Stack("web", "demo", ["run"], health_urls=["http://x"])
    monkeypatch.setattr(stacks, "state", lambda s: ("DOWN", "refused"))
    ix = codeindex.Indexer(s, "http://x", "c")
    repos = {"demo": codeindex.Repo("demo", "demo", root)}
    monkeypatch.setattr(codeindex, "state", lambda ix, r, rec, entries: codeindex.State(r, "main", "abc", "STALE",
                                                                                        "main moved"))
    d = status.collect(p, stack_reg={"web": s}, index=(ix, repos, {}, None))
    assert d["stacks"] == [{"name": "web", "state": "DOWN", "why": "refused"}]
    assert d["code_index"] == [{"repo": "demo", "state": "STALE", "why": "main moved"}]
    lines = status.render({"projects": [d]})
    assert "  audit       P0 1, P1 0, P2 2, info 3 (1 repo(s))" in lines
    assert "  stacks      0 of 1 OK; web DOWN (refused)" in lines
    assert "  code index  0 of 1 OK; demo STALE (main moved)" in lines
    err = status.collect(p, stack_reg=stacks.StackError("bad stack"), index=codeindex.CodeIndexError("bad index"))
    assert err["stacks"] == {"error": "bad stack"} and err["code_index"] == {"error": "bad index"}


def test_status_calls_the_queue_and_digest_data_functions_when_they_exist(tmp_path, monkeypatch, store):
    _status_project(tmp_path, monkeypatch, store)
    seen = {}
    queue = types.ModuleType("brain.queue")
    counts = {"decision": 4, "action": 1, "permission": 0}
    queue.collect = lambda projs, only=None, **kw: seen.update(kw, only=only and only.name) or [
        {"project": p.name, "counts": counts} for p in ([only] if only else projs)]
    digest = types.ModuleType("brain.digest")
    digest.latest = lambda name: Path(f"/x/{name}/2026-10-26_2026-11-02.md")
    monkeypatch.setitem(sys.modules, "brain.queue", queue)
    monkeypatch.setitem(sys.modules, "brain.digest", digest)
    data = status.run([projects.load()["demo"]], quick=True)
    d = data["projects"][0]
    assert d["decisions"]["queue"] == {"decision": 4, "action": 1, "permission": 0}
    assert seen == {"with_graph": False, "transcripts": False, "only": "demo"}
    assert d["digest"] == "2026-10-26_2026-11-02"
    assert status.run(list(projects.load().values()), every=True, quick=True)["projects"][0]["decisions"]["queue"]
    assert seen["only"] is None  # --all: every project in one call
    lines = status.render(data)
    assert "queue: 4 decision, 1 action, 0 permission" in " ".join(x.strip() for x in lines)
    assert "  digest      2026-10-26_2026-11-02" in lines


# --- brain projects ---

def test_projects_lists_the_registry_and_its_keys(tmp_path, monkeypatch, store, capsys):
    _status_project(tmp_path, monkeypatch, store)
    assert cli.main(["projects", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["projects"]
    assert [d["name"] for d in data] == ["demo", "far"] and data[0]["ledgers"] == {"gone": "data/gone.jsonl",
                                                                                  "runs": "data/runs.jsonl"}
    assert data[0]["repos"] == [store.parents[1].name] and data[1]["found"] is False
    assert cli.main(["projects", "--project", "demo"]) == 0
    out = capsys.readouterr().out
    assert "demo (" in out and "  ledgers     runs: data/runs.jsonl, gone: data/gone.jsonl" in out and "far" not in out
    assert cli.main(["projects", "--keys"]) == 0
    out = capsys.readouterr().out
    assert all(f"  {k:<11} " in out for k in projects.KEYS)
