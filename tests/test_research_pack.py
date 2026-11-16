"""The research pack's gates moved out of validate's core (wi-brain-research-pack, spec-brain-typology-packs E5):
every name a research project's own checks import from research_graph.validate is the same object as before, and
GATES names only functions of the pack."""

from research_graph import research_pack, validate

MOVED = ["missing_experiment_nodes", "experiments_missing_from_kanban",
         "staged_experiment_ids", "staged_experiment_gaps", "all_experiment_gaps",
         "hypothesis_validated_without_support", "experiment_tests_no_hypothesis", "l2_without_parent",
         "hypothesis_stub_needs_prose", "check_wiring", "check_consistency", "edge_coverage", "edge_drift",
         "edge_predictive_on_contemporaneous"]
PRIVATE = ["_EDGE_ASSERTED", "_EXP_PATH_RE", "_edge_nodes", "_experiment_gaps", "_experiment_is_methodological",
           "_experiment_spec", "_experiment_targets_edges", "_exploited", "_preregistration_gap"]


def test_every_moved_gate_is_importable_from_validate_as_the_same_object():
    for name in MOVED:
        assert getattr(validate, name) is getattr(research_pack, name), name
        assert getattr(research_pack, name).__module__ == "research_graph.research_pack"
    for name in PRIVATE:   # the private helpers too: a research project's checks may reach them
        assert getattr(validate, name) is getattr(research_pack, name), name
    assert validate.yaml and validate.yamlio   # the module names validate held before the move


def test_the_core_keeps_its_generic_checks():
    for name in ("check_coverage", "missing_decision_nodes", "anchor_errors", "endpoint_errors", "empty_decision_bodies",
                 "staged_module_without_test", "DEFAULT_DECISIONS"):
        assert hasattr(validate, name) and not hasattr(research_pack, name), name
    assert validate.check_coverage.__module__ == "research_graph.validate"


def test_gates_name_the_packs_functions_once_each():
    named = [n for kind in research_pack.GATES.values() for n in kind]
    assert len(named) == len(set(named))
    assert all(callable(getattr(research_pack, n)) for n in named)
    assert set(named) <= set(MOVED)


def test_a_research_gate_is_silent_on_a_store_without_research_nodes(tmp_path):
    import networkx as nx
    g = nx.DiGraph()
    g.add_node("wi-x", type="WorkItem", status="todo")
    assert validate.check_wiring(g, tmp_path) == [] and validate.check_consistency(g) == []
    assert validate.missing_experiment_nodes(g, tmp_path) == []
