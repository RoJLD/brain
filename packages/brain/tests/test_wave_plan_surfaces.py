"""wi-brain-wave-plan-surfaces: brain wave plan cuts lots by weighted surfaces (brain.collisions.weighted: strong what
an item says it edits, weak what only stands near it; a weak-weak meeting is listed, never a lot), files hot by the
repos' history (brain.lots.history_hot), broad items alone and last, and a lot cap that splits a lot over 8 items or a
chain over 3 by cutting its most shared file. Fixtures only: a store and a repo built here, the tests' Ada."""

import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml
from conftest import GIT_ENV, git_init, run_git

from brain import cli, closemerged, collisions, governor, lots, quota, resume
from brain.commands import next as next_cmd

SCHEMA = (
    "node_types: [WorkItem, Milestone, Feature]\n"
    "edge_types: [part_of, depends_on, delivers, implemented_by]\n"
    "statuses: [todo, doing, blocked, done, dropped, pending, reached, have]\n")


def _store(tmp_path, items: list[dict], edges: list[dict] = (), features: list[dict] = ()) -> object:
    """A store with one pending wave (1.1.0) holding ``items`` ({id, title, props?}); edges and features added."""
    root = tmp_path / "root"
    store = root / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("", encoding="utf-8")
    nodes = [{"id": "wave-1.1.0", "type": "Milestone", "status": "pending", "title": "Wave 1.1.0",
              "props": {"kind": "wave", "release": "1.1.0"}}]
    nodes += [{"type": "WorkItem", "status": "todo", **i} for i in items]
    nodes += [{"type": "Feature", "status": "have", **f} for f in features]
    links = [{"from": i["id"], "to": "wave-1.1.0", "type": "part_of"} for i in items] + list(edges)
    (store / "nodes" / "work.yaml").write_text(yaml.safe_dump(nodes, sort_keys=False), encoding="utf-8")
    (store / "edges" / "work.yaml").write_text(yaml.safe_dump(links, sort_keys=False), encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _guards(monkeypatch):
    monkeypatch.setattr(governor, "memory_info", lambda: {"committed": 40.0, "available_gb": 30.0})
    monkeypatch.setattr(quota, "load_status", lambda: {})


def _plan(root, **kw):
    return lots.plan(root / "notes" / "graph", root, wave="1.1.0", **kw)


def _lot_of(wp) -> dict:
    return {i: lot.n for lot in wp.lots for i in lot.items}


def _feature(fid: str, n: int, module: str = "") -> tuple[dict, list[dict]]:
    props = {"module": module} if module else {}
    return ({"id": fid, "title": fid, "props": props},
            [{"from": fid, "to": f"code:engine:src/{fid}/f{k}.py", "type": "implemented_by"} for k in range(n)])


def test_weighted_says_what_an_item_edits_strong_and_what_stands_near_it_weak(tmp_path):
    narrow, e1 = _feature("feat-narrow", 2)
    broad, e2 = _feature("feat-broad", 7)
    mod, e3 = _feature("feat-mod", 1, module="D1")
    root = _store(tmp_path, [{"id": "wi-a", "title": "views.py and docs/specs/plan.md",
                              "props": {"where": "engine (brain.lots, brain.commands.wave; brain.json is no module)",
                                        "size_reason": "a test in test_views.py", "module": "D1",
                                        "idea": "Ada, from notes/ideas.md"}}],
                  [{"from": "wi-a", "to": "feat-narrow", "type": "delivers"},
                   {"from": "wi-a", "to": "feat-broad", "type": "delivers"}, *e1, *e2, *e3], [narrow, broad, mod])
    st = resume.Store.load(root / "notes" / "graph")
    strong, weak = collisions.weighted(st.nodes["wi-a"], st)
    assert {"views.py", "test_views.py", "brain/lots.py", "brain/commands/wave.py", "brain.json",
            "engine:src/feat-narrow/f0.py", "engine:src/feat-narrow/f1.py"} == set(strong)
    assert "brain/json.py" not in strong   # a file name is no module
    assert "docs/specs/plan.md" in weak    # a spec document: weak, even in the title
    assert "notes/ideas.md" in weak        # a context prop
    assert "engine:src/feat-broad/f6.py" in weak and "engine:src/feat-mod/f0.py" in weak   # a broad feature, a module


def test_a_spec_shared_by_many_items_joins_no_lot_but_a_strong_meeting_does(tmp_path):
    spec = "spec docs/specs/roadmap.md Part 2"
    root = _store(tmp_path, [
        {"id": "wi-merged", "title": "Merged", "props": {"where": "engine (brain.lots, brain.closemerged)",
                                                          "idea": spec}},
        {"id": "wi-surfaces", "title": "Surfaces", "props": {"where": "engine (brain.lots, brain.collisions)",
                                                              "idea": spec}},
        {"id": "wi-grammar", "title": "Grammar", "props": {"where": "engine (brain.waves)", "idea": spec}},
        {"id": "wi-propose", "title": "Propose", "props": {"where": "engine (new brain.propose)", "idea": spec}}])
    wp = _plan(root)
    of = _lot_of(wp)
    assert of["wi-merged"] == of["wi-surfaces"]   # both edit brain/lots.py
    assert len({of["wi-merged"], of["wi-grammar"], of["wi-propose"]}) == 3
    assert {"items": ["wi-merged", "wi-surfaces"], "files": ["brain/lots.py"]} in wp.conflicts
    assert {"items": ["wi-grammar", "wi-propose"], "files": ["docs/specs/roadmap.md"]} in wp.possible
    text = "\n".join(lots.render(wp))
    assert "Possible conflicts (6), weak entries alone" in text


def test_a_strong_entry_meets_a_weak_one_and_joins(tmp_path):
    mod, e = _feature("feat-mod", 2, module="D1")
    root = _store(tmp_path, [{"id": "wi-x", "title": "In f0.py", "props": {}},
                             {"id": "wi-y", "title": "The module", "props": {"module": "D1"}}], e, [mod])
    wp = _plan(root)
    assert _lot_of(wp)["wi-x"] == _lot_of(wp)["wi-y"]


def test_a_lot_over_the_cap_is_split_at_its_most_shared_file(tmp_path):
    items = [{"id": f"wi-{k:02d}", "title": f"hub.py and own{k // 2}.py"} for k in range(10)]
    wp = _plan(_store(tmp_path, items))
    assert max(len(lot.items) for lot in wp.lots) <= lots.LOT_CAP
    assert [c["file"] for c in wp.cuts] == ["hub.py"] and len(wp.cuts[0]["items"]) == 10
    assert len(wp.lots) == 5   # the pairs that share their own file stay together
    text = "\n".join(lots.render(wp))
    assert "Lots split (1 file(s) cut, over 8 items or a chain over 3)" in text
    assert "  hub.py: wi-00 (lot " in text


def test_a_chain_over_three_is_split(tmp_path):
    items = [{"id": f"wi-c{k}", "title": "chain.py"} for k in range(4)]
    edges = [{"from": f"wi-c{k + 1}", "to": f"wi-c{k}", "type": "depends_on"} for k in range(3)]
    wp = _plan(_store(tmp_path, items, edges))
    assert len(wp.lots) == 4 and len(wp.rounds) == 4   # one item a lot, in the chain's order
    assert [wp.lots[r[0] - 1].items for r in wp.rounds] == [["wi-c0"], ["wi-c1"], ["wi-c2"], ["wi-c3"]]
    assert wp.cuts == [{"file": "chain.py", "items": ["wi-c0", "wi-c1", "wi-c2", "wi-c3"]}]
    three = _plan(_store(tmp_path / "three", items[:3], edges[:2]))
    assert len(three.lots) == 1 and three.cuts == []   # a chain of three fits


def test_a_broad_item_is_alone_and_last_unless_something_waits_on_it(tmp_path):
    many = ", ".join(f"m{k}.py" for k in range(lots.BROAD_FILES + 1))
    root = _store(tmp_path, [
        {"id": "wi-debt", "title": "The debt: shared.py", "props": {"audit_repo": "engine"}},
        {"id": "wi-wide", "title": "Everything", "props": {"files": many}},
        {"id": "wi-a", "title": "shared.py and m1.py"},
        {"id": "wi-b", "title": "shared.py"},
        {"id": "wi-needs", "title": "after the wide one: other.py"}],
        [{"from": "wi-needs", "to": "wi-wide", "type": "depends_on"}])
    wp = _plan(root)
    by = {i: lot for lot in wp.lots for i in lot.items}
    assert by["wi-debt"].items == ["wi-debt"] and by["wi-debt"].broad
    assert by["wi-wide"].items == ["wi-wide"] and by["wi-wide"].broad
    assert by["wi-a"] is by["wi-b"]
    assert by["wi-debt"].round == len(wp.rounds)   # nothing waits on it: the last round
    assert by["wi-wide"].round < by["wi-needs"].round   # something waits on it: its place
    assert any(x["items"] == ["wi-a", "wi-debt"] and x.get("broad") for x in wp.possible)
    assert "broad: alone" in "\n".join(lots.render(wp))


def _commit(repo, files: dict, message: str) -> None:
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text, encoding="utf-8")
    run_git(repo, "add", "-A")
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True,
                   env=dict(os.environ, **GIT_ENV), timeout=60)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """A repo whose registry.py every commit adds a line to, and whose views.py each rewrites."""
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    repo = git_init(tmp_path / "engine")
    registry, views = "", ""
    for k in range(12):
        registry += f"register({k})\n"
        views = f"draw({k})\n" * 3
        _commit(repo, {"src/registry.py": registry, "src/views.py": views, f"src/own{k}.py": "x = 1\n"}, f"c{k}")
    return repo


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_a_registry_every_commit_adds_to_is_hot_by_history(tmp_path, engine):
    h = lots.history_hot([("engine", engine)])
    assert h["read"] == {"engine": 12} and list(h["files"]) == ["src/registry.py"]   # views.py is rewritten
    assert h["files"]["src/registry.py"]["prs"] == 12 and h["files"]["src/registry.py"]["deleted"] == 0
    root = _store(tmp_path, [{"id": "wi-a", "title": "registry.py, a.py"}, {"id": "wi-b", "title": "registry.py"},
                             {"id": "wi-c", "title": "views.py"}, {"id": "wi-d", "title": "views.py"}])
    wp = _plan(root, repos=[("engine", engine)], read_merged=False)
    of = _lot_of(wp)
    assert of["wi-a"] != of["wi-b"] and of["wi-c"] == of["wi-d"]
    assert list(wp.hot) == ["registry.py"] and set(wp.hot["registry.py"]) == {"wi-a", "wi-b"}
    assert list(wp.history["files"]) == ["src/registry.py"]
    text = "\n".join(lots.render(wp))
    assert "Hot by history (1 the wave touches; 10% of the last 100 commits or more, mostly added): " \
           "src/registry.py (100%)" in text


@pytest.mark.parametrize("fault", ["not a repo", "git missing", "git hangs"])
def test_a_history_that_cannot_be_read_is_said_and_heats_nothing(tmp_path, monkeypatch, fault):
    path = tmp_path / "plain"
    path.mkdir()
    if fault != "not a repo":
        exc = FileNotFoundError("git") if fault == "git missing" else subprocess.TimeoutExpired("git", 120)

        def boom(*a, **kw):
            raise exc
        monkeypatch.setattr(closemerged.subprocess, "run", boom)
    h = lots.history_hot([("engine", path)])
    assert h["files"] == {} and "engine" in h["skipped"]
    root = _store(tmp_path, [{"id": "wi-a", "title": "a.py"}])
    wp = _plan(root, repos=[("engine", path)], read_merged=False)
    assert any(line.startswith("  history not read in engine: ") for line in lots.render(wp))


def test_hot_files_shared_across_lots_are_listed_in_the_lots_order(tmp_path):
    root = _store(tmp_path, [{"id": "wi-z", "title": "README.md and z.py", "props": {"priority": "P1"}},
                             {"id": "wi-a", "title": "README.md and a.py", "props": {"priority": "P3"}}])
    wp = _plan(root)
    assert _lot_of(wp)["wi-z"] < _lot_of(wp)["wi-a"]
    assert wp.hot == {"README.md": ["wi-z", "wi-a"]}   # the merge order, not the alphabet


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_brain_next_cuts_its_lots_without_the_history(tmp_path, engine, monkeypatch, capsys):
    """brain next's summary leaves history_hot aside: one git log --numstat a repo on every call, in an MCP tool's
    time budget."""
    root = _store(tmp_path, [{"id": "wi-a", "title": "registry.py"}, {"id": "wi-b", "title": "registry.py"}])
    monkeypatch.setattr(next_cmd, "_repos", lambda args, root: [SimpleNamespace(name="engine", path=engine)])
    read = []
    monkeypatch.setattr(lots, "history_hot",
                        lambda *a, **kw: read.append(a) or {"files": {}, "read": {}, "skipped": {}})
    assert cli.main(["--root", str(root), "next"]) == 0
    out = capsys.readouterr().out
    assert "Lots (brain wave plan 1.1.0): 1 lot(s)" in out and read == []   # registry.py, not hot here, joins them
