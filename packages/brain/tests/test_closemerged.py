"""brain wave close-merged (wi-brain-close-from-fragments, brain.closemerged): the PRs merged since the last release
tag, read from git alone, each mapped to its items by the changelog fragment it added or an id in its title; the plan,
then --write closes them with their PR, outcome and merge date. Fixtures only: a repo built here, the tests' Ada."""

import json
import os
import shutil
import subprocess

import pytest
import yaml
from conftest import GIT_ENV, git_init, run_git

from brain import cli, closemerged

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not available")

SCHEMA = ("node_types: [WorkItem, Milestone]\nedge_types: [part_of, depends_on]\n"
          "statuses: [todo, doing, blocked, done, dropped, pending, reached]\n")
NODES = """\
- {id: wave-1.0.0, type: Milestone, status: reached, title: "Wave 1.0.0", props: {kind: wave, release: 1.0.0}}
- {id: wave-1.1.0, type: Milestone, status: pending, title: "Wave 1.1.0", props: {kind: wave, release: 1.1.0}}
- {id: wave-1.2.0, type: Milestone, status: pending, title: "Wave 1.2.0", props: {kind: wave, release: 1.2.0}}
- {id: wi-start, type: WorkItem, status: todo, title: "Start", props: {priority: P1}}
- {id: wi-start-two, type: WorkItem, status: todo, title: "Start, two"}
- {id: wi-doing, type: WorkItem, status: doing, title: "Doing"}
- {id: wi-done, type: WorkItem, status: done, title: "Done already", props: {pr: "engine #0"}}
- {id: wi-waits, type: WorkItem, status: todo, title: "No PR yet"}
- {id: wi-next, type: WorkItem, status: todo, title: "Next wave"}
"""
EDGES = """\
- {from: wi-start, to: wave-1.1.0, type: part_of}
- {from: wi-start-two, to: wave-1.1.0, type: part_of}
- {from: wi-doing, to: wave-1.1.0, type: part_of}
- {from: wi-done, to: wave-1.1.0, type: part_of}
- {from: wi-waits, to: wave-1.1.0, type: part_of}
- {from: wi-next, to: wave-1.2.0, type: part_of}
"""


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "brain"
    store = r / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(SCHEMA, encoding="utf-8")
    (store / "edges.yaml").write_text("", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(NODES, encoding="utf-8", newline="\n")
    (store / "edges" / "work.yaml").write_text(EDGES, encoding="utf-8", newline="\n")
    return r


def _commit(repo, files: dict, message: str, day: str = "2030-01-02") -> None:
    for path, text in files.items():
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    run_git(repo, "add", "-A")
    env = dict(os.environ, **GIT_ENV, GIT_AUTHOR_DATE=f"{day}T10:00:00", GIT_COMMITTER_DATE=f"{day}T10:00:00")
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True, env=env)


def _pr(repo, n: int, title: str, files: dict, day: str, squash: bool = False) -> None:
    """A PR merged as GitHub merges one: a merge commit (or a squash commit), on main."""
    run_git(repo, "checkout", "-q", "-b", f"pr{n}", "main")
    _commit(repo, files, title, day)
    run_git(repo, "checkout", "-q", "main")
    env = dict(os.environ, **GIT_ENV, GIT_AUTHOR_DATE=f"{day}T12:00:00", GIT_COMMITTER_DATE=f"{day}T12:00:00")
    if squash:
        subprocess.run(["git", "-C", str(repo), "merge", "-q", "--squash", f"pr{n}"], check=True, env=env,
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", f"{title} (#{n})"], check=True, env=env)
    else:
        subprocess.run(["git", "-C", str(repo), "merge", "-q", "--no-ff", "-m",
                        f"Merge pull request #{n} from demo/pr{n}\n\n{title}", f"pr{n}"], check=True, env=env)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    repo = git_init(tmp_path / "engine")
    _commit(repo, {"README.md": "engine\n", "changes/README.md": "fragments\n",
                   "changes/wi-start-two.md": "section: Added\n\n- before the tag\n"}, "base", "2030-01-01")
    run_git(repo, "tag", "v1.0.0")
    _pr(repo, 1, "The start (fragment)", {"changes/wi-start.md": "section: Added\n\n- start\n"}, "2030-01-03")
    _pr(repo, 2, "Fix wi-doing; wi-done's follow-up", {"src/a.py": "x = 1\n"}, "2030-01-04", squash=True)
    _pr(repo, 3, "An upgrade step", {"packages/brain/changes/wi-next-upgrade.md": "section: Upgrade\n\n1. x\n"},
        "2030-01-05")
    _pr(repo, 4, "Release chores", {"CHANGELOG.md": "# Changelog\n"}, "2030-01-06")
    _pr(repo, 5, "Start again (wi-start)", {"src/b.py": "y = 2\n"}, "2030-01-07")
    _commit(repo, {"src/c.py": "z = 3\n"}, "A direct commit naming wi-waits", "2030-01-08")
    return repo


def _nodes(root):
    return {n["id"]: n for n in yaml.safe_load((root / "notes" / "graph" / "nodes" / "work.yaml").read_text("utf-8"))}


def test_the_plan_maps_fragments_and_titles_and_lists_the_rest(root, engine):
    p = closemerged.plan(root / "notes" / "graph", [("engine", engine)], "1.1.0", root=root)
    assert p.ranges == {"engine": "v1.0.0..HEAD"}   # no origin here: the checkout's HEAD
    assert [x.number for x in p.prs] == [1, 2, 3, 4, 5]   # the direct commit merged no PR; the tag's past is not read
    assert {i: [x.ref for x in v] for i, v in p.to_close.items()} == {
        "wi-start": ["engine #1", "engine #5"], "wi-doing": ["engine #2"], "wi-next": ["engine #3"]}
    assert list(p.closed) == ["wi-done"]
    assert p.outside == ["wi-next"]
    assert [x.number for x in p.unmapped] == [4]
    assert p.waiting == ["wi-start-two", "wi-waits"]   # its fragment came before the tag; a commit that is no PR
    assert p.prs[1].title == "Fix wi-doing; wi-done's follow-up" and p.prs[0].fragments == ["changes/wi-start.md"]


def test_write_closes_with_the_prs_the_titles_and_the_merge_date(root, engine, capsys):
    base = ["--root", str(root), "wave", "close-merged", "1.1.0", "--repo-dir", str(engine)]
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert 'to close: wi-start --pr "engine #1, engine #5" --outcome "The start (fragment); Start again (wi-start)"' \
        in out
    assert "to close: wi-next (not in this wave)" in out and "names no item: engine #4 Release chores" in out
    assert "no merged PR: wi-waits" in out and "not written: --write" in out
    assert _nodes(root)["wi-start"]["status"] == "todo"
    assert cli.main(base + ["--write"]) == 0
    assert "3 item(s) closed, 1 already closed, 2 with no merged PR; written" in capsys.readouterr().out
    nodes = _nodes(root)
    assert nodes["wi-start"]["status"] == "done"
    assert nodes["wi-start"]["props"]["pr"] == "engine #1, engine #5"
    assert nodes["wi-start"]["props"]["done"] == "2030-01-07 The start (fragment); Start again (wi-start)"
    assert nodes["wi-doing"]["props"]["done"].startswith("2030-01-04 Fix wi-doing")
    assert nodes["wi-done"]["props"] == {"pr": "engine #0"}   # already closed: untouched
    assert cli.main(base + ["--json"]) == 0   # closed now: nothing left to close
    data = json.loads(capsys.readouterr().out)
    assert data["close"] == {} and set(data["closed"]) == {"wi-start", "wi-doing", "wi-next", "wi-done"}


def test_a_tagged_release_reads_up_to_its_tag(root, engine):
    run_git(engine, "tag", "v1.1.0", "HEAD~2")   # PR 5 and the direct commit after the tag
    p = closemerged.plan(root / "notes" / "graph", [("engine", engine)], "1.1.0")
    assert p.ranges == {"engine": "v1.0.0..v1.1.0"}
    assert [x.number for x in p.prs] == [1, 2, 3, 4]
    assert [x.ref for x in p.to_close["wi-start"]] == ["engine #1"]


def test_since_and_until_override_the_range(root, engine):
    p = closemerged.plan(root / "notes" / "graph", [("engine", engine)], "1.1.0", since="HEAD~3", until="HEAD~1")
    assert [x.number for x in p.prs] == [4, 5]


def test_no_tag_before_the_release_is_said_and_exits_1(root, engine, capsys):
    assert cli.main(["--root", str(root), "wave", "close-merged", "1.1.0", "--repo-dir", str(engine),
                     "--since", ""]) == 0   # an empty --since is the default: the tag
    capsys.readouterr()
    run_git(engine, "tag", "-d", "v1.0.0")
    assert cli.main(["--root", str(root), "wave", "close-merged", "1.1.0", "--repo-dir", str(engine)]) == 1
    assert "no release tag before 1.1.0 (--since REF)" in capsys.readouterr().err
    assert cli.main(["--root", str(root), "wave", "close-merged", "9.9.9", "--repo-dir", str(engine)]) == 1
    assert "no wave of that release" in capsys.readouterr().err


@pytest.mark.parametrize("body, want", [
    ("Merge pull request #12 from demo/x\n\nThe title\n", (12, "The title")),
    ("Merge pull request #12 from demo/x\n", (12, "")),
    ("The title (#7)\n\n* a squashed commit\n", (7, "The title")),
    ("A direct commit\n", None),
    ("Merge branch 'main' into feature\n", None),
])
def test_pr_of(body, want):
    assert closemerged._pr_of(body) == want


def test_items_of_a_fragment_a_slug_and_a_title():
    ids = {"wi-a", "wi-a-b", "wi-c"}
    pr = closemerged.MergedPR("r", 1, "Fixes wi-c, and wi-zz.", "sha", "2030-01-01",
                              ["changes/wi-a-b-upgrade.md", "packages/x/changes/wi-a.md", "changes/other.md"])
    assert closemerged.items_of(pr, ids) == ["wi-a-b", "wi-a", "wi-c"]
    assert closemerged.is_fragment("changes/wi-a.md") and not closemerged.is_fragment("changes/README.md")
    assert not closemerged.is_fragment("docs/wi-a.md")
