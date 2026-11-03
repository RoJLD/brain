"""research_graph.yamlio (wi-brain-yaml-fast-load): libyaml, a per-process memo keyed by (path, size, mtime_ns), a
fresh copy on each read, and a racy mtime checked against the text."""

import os

import pytest
import yaml

from research_graph import yamlio


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("RESEARCH_GRAPH_YAML_MEMO", raising=False)
    yamlio.clear()
    yield
    yamlio.clear()


def _write(path, text, mtime_ns=None):
    path.write_text(text, encoding="utf-8")
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))


OLD = 1_700_000_000 * 10**9   # long before any read: not racy


def test_loads_uses_libyaml_when_present():
    assert yamlio.LOADER is getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    assert yamlio.loads("- {id: a, n: 1}\n- é « x »\n") == [{"id": "a", "n": 1}, "é « x »"]


def test_a_file_is_parsed_once_and_each_read_is_a_copy(tmp_path):
    f = tmp_path / "work.yaml"
    _write(f, "- {id: wi-a, status: todo}\n", OLD)
    first = yamlio.load(f)
    first[0]["status"] = "changed by a caller"
    second = yamlio.load(f)
    assert second == [{"id": "wi-a", "status": "todo"}] and second is not first
    assert yamlio.stats == {"hits": 1, "misses": 1}


def test_a_changed_file_is_parsed_again(tmp_path):
    f = tmp_path / "work.yaml"
    _write(f, "- {id: wi-a, status: todo}\n", OLD)
    yamlio.load(f)
    _write(f, "- {id: wi-a, status: doing}\n", OLD + 10**9)      # another size and time
    assert yamlio.load(f)[0]["status"] == "doing"


def test_a_same_size_write_in_the_same_clock_tick_is_seen(tmp_path):
    """todo -> done keeps the size; within one tick the mtime may not move either: the text's digest decides."""
    f = tmp_path / "work.yaml"
    _write(f, "- {id: wi-a, status: todo}\n")
    tick = f.stat().st_mtime_ns
    assert yamlio.load(f)[0]["status"] == "todo"
    _write(f, "- {id: wi-a, status: done}\n", tick)
    assert yamlio.load(f)[0]["status"] == "done"
    assert yamlio.load(f)[0]["status"] == "done"   # same text: a hit after the check
    assert yamlio.stats["hits"] == 1


def test_errors_are_not_kept(tmp_path):
    f = tmp_path / "bad.yaml"
    _write(f, "a: [1, 2\n", OLD)
    with pytest.raises(yaml.YAMLError):
        yamlio.load(f)
    _write(f, "a: [1, 2]\n", OLD + 10**9)
    assert yamlio.load(f) == {"a": [1, 2]}
    with pytest.raises(OSError):
        yamlio.load(tmp_path / "missing.yaml")


def test_the_memo_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_GRAPH_YAML_MEMO", "0")
    f = tmp_path / "x.yaml"
    _write(f, "a: 1\n", OLD)
    yamlio.load(f)
    yamlio.load(f)
    assert yamlio.stats == {"hits": 0, "misses": 2}


def test_the_store_loader_reads_through_it(tmp_path):
    from research_graph.loader import load_store

    s = tmp_path / "graph"
    (s / "nodes").mkdir(parents=True)
    (s / "schema.yaml").write_text("node_types: [WorkItem]\nedge_types: [depends_on]\nstatuses: [todo]\n",
                                   encoding="utf-8")
    (s / "edges.yaml").write_text("", encoding="utf-8")
    (s / "nodes" / "work.yaml").write_text("- {id: wi-a, type: WorkItem, status: todo, title: A}\n", encoding="utf-8")
    load_store(s)
    load_store(s)
    assert yamlio.stats == {"hits": 3, "misses": 3}   # schema, the node file and edges.yaml, parsed once
