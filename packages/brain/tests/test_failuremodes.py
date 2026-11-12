"""brain.failuremodes: the invariants and failure modes to test, from what a change touches
(wi-brain-brief-failure-modes). The brief's and the review packet's section; their wiring is tested in
test_collisions_brief.py and test_review.py."""

from brain import failuremodes as fm


def keys(found):
    return [s.key for s, _ in found]


def test_paths_call_their_surfaces_in_the_tables_order_with_what_matched():
    found = fm.match(["packages/brain/src/brain/commands/item.py", "packages/brain/src/brain/schemas/ar.schema.json",
                      "packages/brain/src/brain/procedures/close-item/SKILL.md", "src\\brain\\guards.py"])
    assert keys(found) == ["store", "procedure", "cli", "guard"]
    why = dict((s.key, w) for s, w in found)
    assert why["store"] == "packages/brain/src/brain/schemas/ar.schema.json"
    assert why["guard"] == "src/brain/guards.py"   # a Windows path read as a posix one
    assert fm.match(["tests/test_guards.py", "tests/test_cost.py"]) == []   # a test named after a module is not it


def test_words_of_the_items_text_call_surfaces_case_ignored_and_say_the_words():
    found = fm.match([], ["Sizes checked against actuals: a BACKTEST",
                          "the GitHub API answers", "atomic rewrite of the manifest", "per project, at most 3"])
    assert keys(found) == ["external", "multiwrite", "heuristic", "counted"]
    assert dict((s.key, w) for s, w in found)["heuristic"] == "« BACKTEST »"


def test_a_diffs_lines_call_only_the_moved_test_surface():
    """Code names stores and guards everywhere: a diff's changed lines are read for a removed test only."""
    assert fm.match([], [], ["+    store = guard(schema)", "+    # the API"]) == []
    found = fm.match([], [], ["-def test_the_old_behaviour():", "+x = 1"])
    assert keys(found) == ["moved"]
    assert dict((s.key, w) for s, w in found)["moved"] == "« def test_the_old_behaviour( »"


def test_changed_lines_keep_their_sign_and_leave_the_headers():
    patch = "diff --git a/t.py b/t.py\n--- a/t.py\n+++ b/t.py\n@@ -1 +1 @@\n-def test_a(): pass\n+def test_b(): pass\n"
    assert fm.changed_lines(patch) == ["-def test_a(): pass", "+def test_b(): pass"]


def test_own_invariants_a_line_or_a_list_and_nothing_else():
    assert fm.own({"invariants": "one edge per pair"}) == ["one edge per pair"]
    assert fm.own({"invariants": ["a  b", "", "c"]}) == ["a b", "c"]
    assert fm.own({"invariants": {"x": 1}}) == [] and fm.own({}) == [] and fm.own(None) == []


def test_lines_and_for_item_put_the_public_engine_then_the_items_own_last():
    node = {"id": "wi-x", "title": "brain xy --json", "props": {"invariants": ["never two heads"],
                                                                "where": {"deep": ["an escaping helper"]}}}
    out = fm.for_item(node, ["src/brain/views.py"], public=True)
    assert out[0].startswith("- **a command line** (« brain xy -- »): the parent's flags after the subcommand")
    assert out[1].startswith("- **text written into another format** (src/brain/views.py): an escaping helper")
    assert out[-2].startswith("- **the public engine**: no private id")
    assert out[-1] == "- **the item's own** (props.invariants): never two heads"
    assert fm.lines([]) == []


def test_every_surface_says_what_to_test_and_has_a_way_to_match():
    assert len({s.key for s in fm.SURFACES}) == len(fm.SURFACES)
    for s in fm.SURFACES:
        assert s.name and s.test and (s.paths or s.words)


def test_an_edited_test_is_not_a_removed_one():
    """A changed signature or assertion shows as - then +: only a test whose def is gone for good is a removal."""
    assert fm.match([], [], ["-def test_a(x):", "+def test_a(x, y):", "-    assert x == 1", "+    assert x == 2"]) == []
    assert fm.removed_tests(["-def test_a():", "-def test_b():", "+def test_b(y):", "-def test_a():"]) == [
        "-def test_a("]


def test_tests_and_docs_do_not_call_the_surface_of_what_they_name():
    assert fm.match(["packages/brain/tests/test_mcp_x.py", "docs/export-notes.md", "tests/commands/test_a.py",
                     "packages/brain/docs/hooks/guard.md"]) == []
    assert keys(fm.match(["packages/brain/tests/fixtures/formats/ar-v1.json"])) == ["store"]   # a format's fixture
    assert keys(fm.match(["packages/brain/src/brain/mcpserver.py", "src/research_graph/export_gitnexus.py"])) == [
        "external", "escaped"]
