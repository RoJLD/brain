"""wi-brain-ledger-engine-sessions: a session that ran in the engine's checkout or one of its worktrees (a repo the
personal brain's project declares under ``repos:``) is credited to the project it serves, its brief's item first, so
brain usage, the quota pacing and the forecast see it; before, it landed in « other folders »."""

import pytest
from conftest import run_git
from test_cost import ITEMS, row

from brain import cost, projects, queue


@pytest.fixture
def two(tmp_path, store, git_repo):
    """``mine``: a personal brain whose project declares the engine's checkout (``git_repo``, beside it) as a repo;
    ``acme``: another project, with a repo of its own."""
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(ITEMS)
    root = store.parents[1]
    engine = tmp_path / "brain"
    git_repo.rename(engine)
    acme = tmp_path / "acme"
    (acme / "lab").mkdir(parents=True)
    mine = projects.Project(name="mine", root=root, stores=[store], repos=[".", str(engine)])
    other = projects.Project(name="acme", root=acme, repos=[".", "lab"])
    return mine, other, engine


def test_the_engine_checkout_and_its_worktrees_are_the_project_s(two, tmp_path):
    mine, other, engine = two
    place = queue.Placer([mine, other])
    assert place(str(engine)) == "mine"
    assert place(str(engine / ".claude" / "worktrees" / "speed-d0f7b1")) == "mine"  # gone or not: under the repo
    assert place(str(tmp_path / "brain-wt-023")) == "mine"            # a checkout beside it, gone
    assert place(str(mine.root)) == "mine" and place(str(other.root / "lab")) == "acme"
    assert place(str(tmp_path / "elsewhere")) == "" and place(str(tmp_path / "acme-wt-x")) == "acme"
    assert place(str(tmp_path / "brainy-wt-1")) == ""                 # only a known repo's name


def test_a_worktree_elsewhere_is_placed_by_its_main_checkout(two, tmp_path):
    mine, other, engine = two
    wt = tmp_path / "far" / "engine-copy"
    run_git(engine, "worktree", "add", "-q", "-b", "claude/x", str(wt))
    assert queue.Placer([mine, other])(str(wt)) == "mine"


def test_a_project_root_wins_over_another_project_s_repo_at_the_same_place(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    place = queue.Placer([projects.Project(name="a", root=a, repos=[".", str(b)]), projects.Project(name="b", root=b)])
    assert place(str(b / "src")) == "b" and place(str(a)) == "a"


def test_a_bad_repos_entry_does_not_stop_the_placing(tmp_path):
    good = projects.Project(name="good", root=tmp_path)
    bad = projects.Project(name="bad", root=tmp_path / "x", repos="not a list")
    assert queue.Placer([good, bad])(str(tmp_path / "y")) == "good"


def test_brain_usage_credits_the_engine_sessions(two, tmp_path):
    mine, other, engine = two
    rows = [row("s-root", folder=str(mine.root)),
            row("s-engine", folder=str(engine / ".claude" / "worktrees" / "guards-quota-af1c97")),
            row("s-wt", folder=str(tmp_path / "brain-wt-023")),
            row("s-acme", folder=str(other.root / "lab")),
            # a sub-session that ran in acme's repo for an item of mine: the project it serves
            row("s-serves", folder=str(other.root), brief={"side": True, "items": ["wi-b"], "class": "standard"}),
            # a main session whose first prompt names an item: its folder decides
            row("s-main", folder=str(other.root), brief={"side": False, "items": ["wi-b"], "class": "standard"}),
            row("s-away", folder=str(tmp_path / "elsewhere"))]
    led = cost.Ledger(rows, [mine], queue.Placer([mine, other]))
    got = {r["session_id"]: r["project"] for r in led.rows}
    assert got == {"s-root": "mine", "s-engine": "mine", "s-wt": "mine", "s-acme": "acme", "s-serves": "mine",
                   "s-main": "acme", "s-away": queue.OUTSIDE}
    assert {r["session_id"] for r in cost.scoped(led, [mine], False).rows} == {"s-root", "s-engine", "s-wt",
                                                                               "s-serves"}
