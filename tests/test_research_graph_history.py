"""The graph's history from git (research_graph.history) on a fake repository: first-parent steps dated by their
merge, PR refs, moves between files, unparsable versions, the store on a given day."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date

import pytest

from research_graph import history
from research_graph.cli import main as cli_main
from research_graph.loader import ValidationError, read_foreign
from tests.backlog_world import make_history
from tests.two_stores import two_stores


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    return make_history(tmp_path_factory.mktemp("hist"))


def _store(repo):
    return repo / "notes" / "graph"


def _brief(events):
    return [(e.day, e.commit.ref if e.commit.ref.startswith("#") else e.commit.subject[:1], e.id, e.describe())
            for e in events]


def test_repo_location_gives_the_store_inside_its_repository(repo):
    top, prefix = history.repo_location(_store(repo))
    assert top.resolve() == repo.resolve() and prefix == "notes/graph"


def test_timeline_follows_first_parent_and_dates_by_merge(repo):
    events = history.timeline(_store(repo))
    assert _brief(events) == [
        ("2026-10-01", "A", "ms-1", "created [pending]"),
        ("2026-10-01", "A", "wi-a", "created [todo]"),
        ("2026-10-01", "A", "wi-b", "created [todo]"),
        ("2026-10-01", "A", "wi-c", "created [todo]"),
        ("2026-10-01", "A", "wi-gone", "created [todo]"),
        # the branch's two commits land as one step, dated and named by the merge
        ("2026-10-04", "#7", "wi-a", "status todo -> doing"),
        ("2026-10-04", "#7", "wi-a", "props +pr"),
        # wi-c moved from other.yaml to work.yaml: no event
        ("2026-10-05", "D", "wi-b", "status todo -> done"),
        ("2026-10-05", "D", "wi-b", "title changed"),
        ("2026-10-05", "D", "wi-d", "created [todo]"),
        ("2026-10-05", "D", "wi-gone", "removed (was todo)"),
        # 2026-10-06's work.yaml does not parse: skipped, its nodes keep their state
        ("2026-10-07", "F", "wi-d", "status todo -> doing"),
    ]
    props = events[6]
    assert props.old == {"pr": None} and props.new == {"pr": "research-lab #7"}
    assert props.to_json()["commit"]["ref"] == "#7"


def test_timeline_types(repo):
    assert {e.type for e in history.timeline(_store(repo), types={"Milestone"})} == {"Milestone"}
    assert len(history.timeline(_store(repo), types=None)) == len(history.timeline(_store(repo)))


def test_commit_on_a_day(repo):
    assert history.commit_on(_store(repo), date(2026, 9, 30)) is None
    assert history.commit_on(_store(repo), date(2026, 10, 3)).subject == "A: seed"  # branch commits are not on main
    c = history.commit_on(_store(repo), date(2026, 10, 4))
    assert c.ref == "#7" and c.day == "2026-10-04"


def test_load_store_at(repo):
    g = history.load_store_at(_store(repo), history.commit_on(_store(repo), date(2026, 10, 4)).sha)
    assert {n: a["status"] for n, a in g.nodes(data=True) if a["type"] == "WorkItem"} == {
        "wi-a": "doing", "wi-b": "todo", "wi-c": "todo", "wi-gone": "todo"}
    with pytest.raises(ValidationError):  # 2026-10-06: work.yaml does not parse
        history.load_store_at(_store(repo), history.commit_on(_store(repo), date(2026, 10, 6)).sha)


def test_store_absent_at_a_commit(repo, tmp_path):
    (repo / "elsewhere" / "nodes").mkdir(parents=True)
    with pytest.raises(history.GitError, match="does not exist"):
        history.load_store_at(repo / "elsewhere", history.commit_on(_store(repo), date(2026, 10, 7)).sha)


def test_not_a_repository(tmp_path):
    (tmp_path / "plain" / "nodes").mkdir(parents=True)
    with pytest.raises(history.GitError):
        history.timeline(tmp_path / "plain")
    with pytest.raises(history.GitError, match="no store"):
        history.repo_location(tmp_path / "missing")


def test_commit_dates_read_on_every_supported_python():
    """git writes UTC as ``Z``, which Python 3.10's fromisoformat refuses; the engine supports 3.10."""
    from datetime import datetime, timezone

    assert history._when("2026-10-07T12:00:00Z") == datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    assert history._when("2026-10-07T14:00:00+02:00") == datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def _two_stores_committed(tmp_path) -> tuple:
    """(home, parent, sha): the two stores committed on 2026-10-01 in a repo at ``tmp_path``."""
    home, parent = two_stores(tmp_path)
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-01T12:00:00Z", "GIT_COMMITTER_DATE": "2026-10-01T12:00:00Z"}
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit",
                                                 "-qm", "two stores"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, env=env)
    sha = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], check=True, capture_output=True,
                         text=True).stdout.strip()
    return home, parent, sha


def test_load_store_at_takes_the_other_stores_ids(tmp_path):
    """wi-brain-cross-store-edges: asof loads a past version whose edges name another store's ids."""
    home, parent, sha = _two_stores_committed(tmp_path)
    with pytest.raises(ValidationError):
        history.load_store_at(home, sha)
    g = history.load_store_at(home, sha, read_foreign([("parent", parent)]))
    assert g.nodes["wi-s"]["foreign"] == "parent" and g["wi-a"]["wi-s"]["type"] == "depends_on"


def test_asof_command_gives_the_past_version_the_foreign_stores(tmp_path, capsys):
    """research_graph --foreign-store ... asof DAY: the option reaches the past version's load, as check's."""
    home, parent, _ = _two_stores_committed(tmp_path)
    base = ["--store", str(home), "--repo-root", str(tmp_path)]
    assert cli_main([*base, "asof", "2026-10-02"]) == 1
    assert "unknown target 'wi-s'" in capsys.readouterr().err
    assert cli_main([*base, "--foreign-store", f"parent:graph={parent}", "asof", "2026-10-02", "--json"]) == 0
    rows = {r["id"]: r for r in json.loads(capsys.readouterr().out)["items"]}
    assert set(rows) == {"wi-a", "wi-b"}   # the work items; another store's wi-s is never listed as this store's
