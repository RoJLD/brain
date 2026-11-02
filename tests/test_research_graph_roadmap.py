"""Generated roadmap (research_graph.roadmap): rendered from the milestones, written with the kanban, never over a
hand-written file, flagged when stale; the real notes/roadmap_graph.md is not stale."""

from __future__ import annotations

import pytest

from research_graph.cli import main
from research_graph.kanban import DEFAULT_OUT as KANBAN_OUT
from research_graph.loader import load_store
from research_graph.roadmap import (
    DEFAULT_OUT,
    MARKER,
    render_roadmap,
    roadmap_stale,
    write_roadmap,
)
from tests.backlog_world import write_store


@pytest.fixture
def store(tmp_path):
    return write_store(tmp_path / "research-lab")


def test_render(store):
    text = render_roadmap(load_store(store))
    lines = text.splitlines()
    assert lines[0].startswith(MARKER)
    assert "4 milestones: pending 2, reached 2." in text
    assert [ln for ln in lines if ln.startswith("## ")] == [
        "## ms-sub — Sub [pending]", "## ms-top — Top [pending]", "## ms-old — Old [reached]",
        "## ms-older — Older [reached]"]
    assert "| ms-top — Top | pending | 1/3 | all done |" in lines
    assert "| ms-old — Old | reached | 1/1 | 2026-09-15 |" in lines
    top = text.split("## ms-top — Top [pending]")[1].split("## ms-old")[0]
    assert "Items: 3 (doing 1, done 1, todo 1). Critical path: wi-doing → wi-todo." in top
    assert "- [ ] wi-doing — Doing item (P1, doing)" in top
    assert "- [x] wi-done-dated — Closed with a date" in top
    assert "Open prerequisites outside it (depends_on):\n\n- [ ] wi-prereq" in top
    assert "Items that name it:\n\n- [ ] wi-ext2 — Waits on the cluster (blocked)" in top
    assert "Reached: 2026-09-15: evidence" in text
    assert render_roadmap(load_store(store)) == text


def test_write_refuses_a_hand_written_file_and_flags_staleness(store, tmp_path):
    g = load_store(store)
    hand = tmp_path / "roadmap.md"
    hand.write_text("# Roadmap by hand\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not a generated view"):
        write_roadmap(g, hand)
    repo = tmp_path / "repo"
    assert roadmap_stale(g, repo) == []
    write_roadmap(g, repo / DEFAULT_OUT)
    assert roadmap_stale(g, repo) == [] and b"\r\n" not in (repo / DEFAULT_OUT).read_bytes()
    (store / "nodes" / "more.yaml").write_text(
        "- {id: ms-new, type: Milestone, status: pending, title: new}\n", encoding="utf-8")
    assert roadmap_stale(load_store(store), repo) == [
        f"{DEFAULT_OUT} is stale: run `research_graph kanban --write`"]


def test_kanban_write_regenerates_both_views_and_check_flags_a_stale_roadmap(store, tmp_path, capsys):
    repo = tmp_path / "out"
    args = ["--store", str(store), "--repo-root", str(repo)]
    assert main(args + ["kanban", "--write"]) == 0
    assert (repo / KANBAN_OUT).exists() and (repo / DEFAULT_OUT).read_text(encoding="utf-8").startswith(MARKER)
    other = tmp_path / "board.md"
    assert main(args + ["kanban", "--write", "--out", str(other)]) == 0  # --out names the board only
    assert "and" not in capsys.readouterr().out.splitlines()[-1]
    (repo / DEFAULT_OUT).write_text(MARKER + " old -->\n", encoding="utf-8")
    main(args + ["check"])
    assert f"advisory: {DEFAULT_OUT} is stale" in capsys.readouterr().out
    assert main(args + ["roadmap", "--write", "--out", str(tmp_path / "r.md")]) == 0
    assert main(args + ["roadmap", "--markdown"]) == 0
    assert capsys.readouterr().out.endswith(render_roadmap(load_store(store)))
