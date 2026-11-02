from __future__ import annotations

import networkx as nx

from research_graph.validate import (
    all_experiment_gaps,
    check_consistency,
    check_coverage,
    check_wiring,
    edge_coverage,
    edge_drift,
    edge_predictive_on_contemporaneous,
    empty_decision_bodies,
    experiment_tests_no_hypothesis,
    experiments_missing_from_kanban,
    hypothesis_stub_needs_prose,
    hypothesis_validated_without_support,
    l2_without_parent,
    staged_experiment_gaps,
    staged_experiment_ids,
    staged_module_without_test,
)


def _repo(tmp_path):
    (tmp_path / "experiments" / "exp000_x").mkdir(parents=True)
    (tmp_path / "experiments" / "exp001_y").mkdir(parents=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "scientific_decisions.md").write_text(
        "## 2026-05-15 — a thing\nbody\n## 2026-05-20 — another\n",
        encoding="utf-8",
    )
    return tmp_path


def test_check_coverage_flags_missing_experiment(tmp_path):
    repo = _repo(tmp_path)
    g = nx.DiGraph()
    g.add_node("exp000_x", type="Experiment", status="active", anchor=None)
    # exp001_y has no node, 2026-05-15 / 2026-05-20 have no SDR node.
    problems = check_coverage(g, repo)
    assert any("exp001_y" in p for p in problems)
    assert any("2026-05-15" in p for p in problems)


def test_check_coverage_clean(tmp_path):
    repo = _repo(tmp_path)
    g = nx.DiGraph()
    g.add_node("exp000_x", type="Experiment", status="active", anchor=None)
    g.add_node("exp001_y", type="Experiment", status="active", anchor=None)
    g.add_node(
        "sdr-1",
        type="SDR",
        status="active",
        anchor="notes/scientific_decisions.md#2026-05-15-a-thing",
    )
    g.add_node(
        "sdr-2",
        type="SDR",
        status="active",
        anchor="notes/scientific_decisions.md#2026-05-20-another",
    )
    assert check_coverage(g, repo) == []


def test_anchor_missing_date_flagged(tmp_path):
    repo = _repo(tmp_path)
    g = nx.DiGraph()
    g.add_node("exp000_x", type="Experiment", status="active", anchor=None)
    g.add_node("exp001_y", type="Experiment", status="active", anchor=None)
    g.add_node(
        "sdr-1",
        type="SDR",
        status="active",
        anchor="notes/scientific_decisions.md#2026-05-15-a-thing",
    )
    g.add_node(
        "sdr-2",
        type="SDR",
        status="active",
        anchor="notes/scientific_decisions.md#2026-05-20-another",
    )
    g.add_node(
        "h",
        type="Hypothesis",
        status="open",
        anchor="notes/scientific_decisions.md#2099-01-01-nope",
    )
    problems = check_coverage(g, repo)
    assert any("no heading dated 2099-01-01" in p for p in problems)


def test_same_date_two_headings_one_node_flagged(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "scientific_decisions.md").write_text(
        "## 2026-05-15 — first\nx\n## 2026-05-15 — second\n", encoding="utf-8"
    )
    g = nx.DiGraph()
    g.add_node(
        "sdr-1",
        type="SDR",
        status="active",
        anchor="notes/scientific_decisions.md#2026-05-15-first",
    )
    problems = check_coverage(g, tmp_path)
    assert any("2 heading(s) but 1" in p for p in problems)


def test_malformed_anchor_flagged(tmp_path):
    (tmp_path / "notes").mkdir()
    g = nx.DiGraph()
    g.add_node("x", type="Hypothesis", status="open", anchor="no-hash-here")
    problems = check_coverage(g, tmp_path)
    assert any("malformed anchor" in p for p in problems)


def test_experiments_missing_from_kanban(tmp_path):
    (tmp_path / "experiments" / "exp032_done").mkdir(parents=True)
    (tmp_path / "experiments" / "exp099_orphan").mkdir(parents=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "kanban_experiments.md").write_text(
        "## Done\n- exp032_done shipped\n", encoding="utf-8"
    )
    problems = experiments_missing_from_kanban(tmp_path)
    assert any("exp099_orphan" in p for p in problems)
    assert not any("exp032_done" in p for p in problems)


def test_experiments_kanban_matches_by_number(tmp_path):
    # mentioning the bare id (exp032) covers the full dir name (exp032_growth_value)
    (tmp_path / "experiments" / "exp032_growth_value").mkdir(parents=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "kanban_experiments.md").write_text("- exp032 — growth vs value\n", encoding="utf-8")
    assert experiments_missing_from_kanban(tmp_path) == []


def test_empty_decision_bodies_flagged(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "scientific_decisions.md").write_text(
        "## 2026-06-10 — has body\nsome content\n\n## 2026-06-11 — empty\n\n",
        encoding="utf-8",
    )
    problems = empty_decision_bodies(tmp_path)
    assert any("2026-06-11" in p for p in problems)
    assert not any("2026-06-10" in p for p in problems)


def test_empty_decision_bodies_clean(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "decisions.md").write_text(
        "## 2026-06-10 — a\nbody a\n## 2026-06-11 — b\nbody b\n", encoding="utf-8"
    )
    assert empty_decision_bodies(tmp_path) == []


def test_staged_experiment_ids_extracts():
    staged = [
        "experiments/exp033_identification_maturity/run.py",
        "experiments\\exp033_identification_maturity\\config.yaml",
        "src/research_lab/data/coinmetrics.py",
        "experiments/exp040_other/README.md",
    ]
    assert staged_experiment_ids(staged) == {"exp033_identification_maturity", "exp040_other"}


def test_staged_experiment_gaps_missing_kanban_and_sdr(tmp_path):
    (tmp_path / "experiments" / "exp050_z").mkdir(parents=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "kanban_experiments.md").write_text("## Done\n", encoding="utf-8")
    (notes / "scientific_decisions.md").write_text("## 2026-01-01 — x\nbody\n", encoding="utf-8")
    (notes / "cahier_laboratoire.md").write_text("", encoding="utf-8")
    gaps = staged_experiment_gaps(tmp_path, {"exp050_z"})
    assert any("kanban_experiments.md" in g for g in gaps)
    assert any("scientific_decisions.md" in g for g in gaps)


def test_staged_experiment_gaps_clean_when_present_and_not_run(tmp_path):
    (tmp_path / "experiments" / "exp050_z").mkdir(parents=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "kanban_experiments.md").write_text("- exp050 shipped\n", encoding="utf-8")
    (notes / "scientific_decisions.md").write_text(
        "## 2026-01-01 — exp050 z\nbody\n", encoding="utf-8"
    )
    (notes / "cahier_laboratoire.md").write_text("", encoding="utf-8")
    assert staged_experiment_gaps(tmp_path, {"exp050_z"}) == []


def test_staged_experiment_gaps_ran_but_no_cahier(tmp_path):
    exp = tmp_path / "experiments" / "exp050_z"
    (exp / "results").mkdir(parents=True)
    (exp / "results" / "manifest.json").write_text("{}", encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "kanban_experiments.md").write_text("- exp050\n", encoding="utf-8")
    (notes / "scientific_decisions.md").write_text(
        "## 2026-01-01 — exp050\nbody\n", encoding="utf-8"
    )
    (notes / "cahier_laboratoire.md").write_text("", encoding="utf-8")
    gaps = staged_experiment_gaps(tmp_path, {"exp050_z"})
    assert any("cahier_laboratoire.md" in g for g in gaps)


def test_staged_experiment_gaps_noop_without_notes(tmp_path):
    assert staged_experiment_gaps(tmp_path, {"exp050_z"}) == []


def test_staged_module_without_test_flagged(tmp_path):
    (tmp_path / "tests").mkdir()
    staged = ["src/research_lab/data/newloader.py"]
    gaps = staged_module_without_test(staged, tmp_path)
    assert any("newloader" in g for g in gaps)


def test_staged_module_with_existing_test_clean(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_newloader.py").write_text("", encoding="utf-8")
    staged = ["src/research_lab/data/newloader.py"]
    assert staged_module_without_test(staged, tmp_path) == []


def test_staged_module_ignores_init(tmp_path):
    staged = ["src/research_lab/data/__init__.py"]
    assert staged_module_without_test(staged, tmp_path) == []


def test_staged_module_accepts_parent_named_test(tmp_path):
    # repo convention: research_graph/validate.py -> tests/test_research_graph_validate.py
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_research_graph_validate.py").write_text("", encoding="utf-8")
    staged = ["src/research_lab/research_graph/validate.py"]
    assert staged_module_without_test(staged, tmp_path) == []


def test_staged_module_rule_covers_any_package_under_src(tmp_path):
    (tmp_path / "tests").mkdir()
    staged = ["src/other_pkg/tool.py", "src/top_level.py", "scripts/run.py", "src\\win_pkg\\mod.py"]
    assert [g.split(":")[0] for g in staged_module_without_test(staged, tmp_path)] == [
        "src/other_pkg/tool.py", "src/win_pkg/mod.py"]


def test_validated_hypothesis_with_refutes_flagged():
    g = nx.DiGraph()
    g.add_node("H", type="Hypothesis", status="validated")
    g.add_node("v", type="Verdict", status="validated")
    g.add_node("vr", type="Verdict", status="rejected")
    g.add_edge("v", "H", type="validates")
    g.add_edge("vr", "H", type="refutes")
    assert any("refutes" in p for p in hypothesis_validated_without_support(g))


def test_validated_hypothesis_without_support_flagged():
    g = nx.DiGraph()
    g.add_node("H", type="Hypothesis", status="validated")
    assert any("no validated" in p for p in hypothesis_validated_without_support(g))


def test_validated_hypothesis_with_support_clean():
    g = nx.DiGraph()
    g.add_node("H", type="Hypothesis", status="validated")
    g.add_node("v", type="Verdict", status="validated")
    g.add_edge("v", "H", type="validates")
    assert hypothesis_validated_without_support(g) == []


def test_experiment_without_tests_edge_flagged():
    g = nx.DiGraph()
    g.add_node("exp007_x", type="Experiment", status="active")
    assert any("tests no Hypothesis" in p for p in experiment_tests_no_hypothesis(g))


def test_experiment_with_tests_edge_clean():
    g = nx.DiGraph()
    g.add_node("exp007_x", type="Experiment", status="active")
    g.add_node("M1", type="Hypothesis", status="open")
    g.add_edge("exp007_x", "M1", type="tests")
    assert experiment_tests_no_hypothesis(g) == []


def test_l2_without_instantiates_flagged():
    g = nx.DiGraph()
    g.add_node("h2-x", type="Hypothesis", status="proposed", level="L2")
    assert any("L2 without" in p for p in l2_without_parent(g))


def test_l2_with_instantiates_clean():
    g = nx.DiGraph()
    g.add_node("h2-x", type="Hypothesis", status="proposed", level="L2")
    g.add_node("M1", type="Hypothesis", status="open", level="L1")
    g.add_edge("h2-x", "M1", type="instantiates")
    assert l2_without_parent(g) == []


def test_check_consistency_aggregates_advisories_not_wiring():
    g = nx.DiGraph()
    g.add_node(
        "exp007_x", type="Experiment", status="active"
    )  # tests no hypothesis -> now BLOCKING
    g.add_node("h2-y", type="Hypothesis", status="proposed", level="L2")  # no parent (advisory)
    g.add_node(
        "M-z", type="Hypothesis", status="planned", level="L1"
    )  # stub needs prose (advisory)
    out = check_consistency(g)
    assert any("L2 without" in p for p in out)
    assert any("needs curated prose" in p for p in out)
    # experiment_tests_no_hypothesis graduated to the blocking surface (check_wiring), NOT here
    assert not any("tests no Hypothesis" in p for p in out)


def _exp_cfg(repo, name, body):
    d = repo / "experiments" / name
    d.mkdir(parents=True)
    (d / "config.yaml").write_text(body, encoding="utf-8")
    return d


def test_methodological_experiment_exempted(tmp_path):
    _exp_cfg(tmp_path, "exp022_x", "experiment:\n  name: x\nmethodological: true\n")
    g = nx.DiGraph()
    g.add_node("exp022_x", type="Experiment", status="active")
    # without repo_root the exemption can't be read -> still flagged
    assert any("tests no Hypothesis" in p for p in experiment_tests_no_hypothesis(g))
    # with repo_root the methodological marker exempts it
    assert experiment_tests_no_hypothesis(g, tmp_path) == []


def test_non_methodological_experiment_still_flagged(tmp_path):
    _exp_cfg(tmp_path, "exp007_x", "experiment:\n  name: x\n")  # no marker, no tests edge
    g = nx.DiGraph()
    g.add_node("exp007_x", type="Experiment", status="active")
    assert any("tests no Hypothesis" in p for p in experiment_tests_no_hypothesis(g, tmp_path))


def test_edges_experiment_exempted(tmp_path):
    # a TRADING experiment declares a non-empty `edges:` list -> validates an Edge, not a Hypothesis
    _exp_cfg(tmp_path, "exp048_carry_v2", "experiment:\n  name: x\nedges: [E-funding-carry]\n")
    g = nx.DiGraph()
    g.add_node("exp048_carry_v2", type="Experiment", status="active")
    # without repo_root the exemption can't be read -> still flagged
    assert any("tests no Hypothesis" in p for p in experiment_tests_no_hypothesis(g))
    # with repo_root the `edges:` marker exempts it (its claim is an Edge, not a mechanism)
    assert experiment_tests_no_hypothesis(g, tmp_path) == []


def test_empty_edges_list_not_exempted(tmp_path):
    # an empty `edges: []` is NOT a trading experiment -> still requires a tested Hypothesis
    _exp_cfg(tmp_path, "exp009_x", "experiment:\n  name: x\nedges: []\n")
    g = nx.DiGraph()
    g.add_node("exp009_x", type="Experiment", status="active")
    assert any("tests no Hypothesis" in p for p in experiment_tests_no_hypothesis(g, tmp_path))


def test_check_wiring_blocks_untested(tmp_path):
    _exp_cfg(tmp_path, "exp007_x", "experiment:\n  name: x\n")
    g = nx.DiGraph()
    g.add_node("exp007_x", type="Experiment", status="active")
    assert any("tests no Hypothesis" in p for p in check_wiring(g, tmp_path))


def test_check_wiring_clean_when_tested(tmp_path):
    g = nx.DiGraph()
    g.add_node("exp007_x", type="Experiment", status="active")
    g.add_node("M1", type="Hypothesis", status="open")
    g.add_edge("exp007_x", "M1", type="tests")
    assert check_wiring(g, tmp_path) == []


def test_stub_needs_prose_flagged():
    g = nx.DiGraph()
    g.add_node("M-new", type="Hypothesis", level="L1", status="planned")
    assert any("needs curated prose" in p for p in hypothesis_stub_needs_prose(g))


def test_curated_l1_not_flagged():
    g = nx.DiGraph()
    g.add_node("M-growth", type="Hypothesis", level="L1", status="active")
    assert hypothesis_stub_needs_prose(g) == []


def test_check_wiring_includes_landmine_guard():
    # A validated Hypothesis with no validates-support is now BLOCKING (graduated to check_wiring).
    g = nx.DiGraph()
    g.add_node("H", type="Hypothesis", status="validated")
    assert any("no validated" in p for p in check_wiring(g))


def test_check_consistency_excludes_landmine_guard():
    # The anti-landmine guard moved to check_wiring (blocking); it is no longer an advisory.
    g = nx.DiGraph()
    g.add_node("H", type="Hypothesis", status="validated")  # validated, unsupported
    assert not any("no validated" in p for p in check_consistency(g))


# ---- all_experiment_gaps: repo-wide (NOT staged-scoped) rigor-debt audit ----


def _audit_repo(tmp_path):
    """Two experiments; exp070 ran (manifest) and is fully documented, exp071 is orphan."""
    (tmp_path / "experiments" / "exp070_done" / "results").mkdir(parents=True)
    (tmp_path / "experiments" / "exp070_done" / "results" / "manifest.json").write_text(
        "{}", encoding="utf-8"
    )
    (tmp_path / "experiments" / "exp071_orphan").mkdir(parents=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "kanban_experiments.md").write_text("- exp070_done done\n", encoding="utf-8")
    (notes / "scientific_decisions.md").write_text("## 2026-01-01 — exp070_done\nbody\n", "utf-8")
    (notes / "cahier_laboratoire.md").write_text("## run exp070_done\nbody\n", encoding="utf-8")
    return tmp_path


def test_all_experiment_gaps_flags_orphan_not_documented():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path

        repo = _audit_repo(Path(d))
        gaps = all_experiment_gaps(repo)
        # exp071_orphan absent from kanban + SDR (it never ran, so no cahier flag)
        assert any("exp071_orphan" in g and "kanban" in g for g in gaps)
        assert any("exp071_orphan" in g and "scientific_decisions" in g for g in gaps)
        # exp070_done is fully documented → never flagged
        assert not any("exp070_done" in g for g in gaps)


def test_all_experiment_gaps_flags_ran_but_no_cahier(tmp_path):
    (tmp_path / "experiments" / "exp072_ran" / "results").mkdir(parents=True)
    (tmp_path / "experiments" / "exp072_ran" / "results" / "manifest.json").write_text(
        "{}", encoding="utf-8"
    )
    notes = tmp_path / "notes"
    notes.mkdir()
    # present in kanban + SDR, but missing from cahier despite having run
    (notes / "kanban_experiments.md").write_text("exp072_ran\n", encoding="utf-8")
    (notes / "scientific_decisions.md").write_text("## d — exp072_ran\nb\n", encoding="utf-8")
    (notes / "cahier_laboratoire.md").write_text("", encoding="utf-8")
    gaps = all_experiment_gaps(tmp_path)
    assert any("exp072_ran" in g and "cahier" in g for g in gaps)
    assert not any("kanban" in g for g in gaps)


def test_all_experiment_gaps_noop_without_notes(tmp_path):
    (tmp_path / "experiments" / "exp073_x").mkdir(parents=True)
    assert all_experiment_gaps(tmp_path) == []


def test_all_experiment_gaps_matches_by_number(tmp_path):
    (tmp_path / "experiments" / "exp074_slug").mkdir(parents=True)
    notes = tmp_path / "notes"
    notes.mkdir()
    # referenced by bare number "exp074" everywhere → no gap
    for f in ("kanban_experiments.md", "scientific_decisions.md", "cahier_laboratoire.md"):
        (notes / f).write_text("see exp074 here\n", encoding="utf-8")
    assert all_experiment_gaps(tmp_path) == []


# ---- Edge Graph gates (2026-06-15) ------------------------------------------


def _mech(g, mid, status, nature):
    g.add_node(mid, type="Hypothesis", level="L1", status=status, props={"nature": nature})


def test_edge_coverage_flags_supported_mechanism_without_edge():
    g = nx.DiGraph()
    _mech(g, "M-x", "active", "contemporaneous")  # no exploits edge -> flagged
    _mech(g, "M-y", "active", "contemporaneous")
    g.add_node("E-y", type="Edge", status="proposed", props={"edge_type": "hedge"})
    g.add_edge("E-y", "M-y", type="exploits")
    out = edge_coverage(g)
    assert any("M-x" in p for p in out)
    assert not any("M-y" in p for p in out)


def test_edge_drift_flags_live_edge_on_rejected_mechanism():
    g = nx.DiGraph()
    _mech(g, "M-dead", "rejected", "contemporaneous")
    g.add_node("E-bad", type="Edge", status="live", props={"edge_type": "hedge"})
    g.add_edge("E-bad", "M-dead", type="exploits")
    assert any("E-bad" in p for p in edge_drift(g))


def test_edge_drift_exempts_constraint_and_proposed():
    g = nx.DiGraph()
    _mech(g, "M-dead", "rejected", "contemporaneous")
    g.add_node("C-ok", type="Edge", status="live", props={"edge_type": "constraint"})
    g.add_edge("C-ok", "M-dead", type="exploits")
    g.add_node("E-prop", type="Edge", status="proposed", props={"edge_type": "hedge"})
    g.add_edge("E-prop", "M-dead", type="exploits")
    assert edge_drift(g) == []


def test_honesty_guard_flags_live_predictive_on_contemporaneous():
    g = nx.DiGraph()
    _mech(g, "M-contemp", "active", "contemporaneous")
    g.add_node("E-pred", type="Edge", status="live", props={"edge_type": "carry-alpha", "signal_nature": "predictive"})
    g.add_edge("E-pred", "M-contemp", type="exploits")
    assert any("E-pred" in p for p in edge_predictive_on_contemporaneous(g))


def test_honesty_guard_allows_predictive_on_predictive_and_exempts_proposed():
    g = nx.DiGraph()
    _mech(g, "M-pred", "active", "predictive")
    g.add_node("E-ok", type="Edge", status="live", props={"edge_type": "carry-alpha", "signal_nature": "predictive"})
    g.add_edge("E-ok", "M-pred", type="exploits")
    _mech(g, "M-c", "active", "contemporaneous")
    g.add_node("E-cand", type="Edge", status="proposed", props={"edge_type": "carry-alpha", "signal_nature": "predictive"})
    g.add_edge("E-cand", "M-c", type="exploits")
    assert edge_predictive_on_contemporaneous(g) == []


# ---- era-aware pre-registration rule (2026-07-15 consolidation) --------------


def _mk_exp(tmp_path, exp_id, *, config: str | None = None, ran: bool = False):
    exp = tmp_path / "experiments" / exp_id
    exp.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (exp / "config.yaml").write_text(config, encoding="utf-8")
    if ran:
        (exp / "results").mkdir(parents=True, exist_ok=True)
        (exp / "results" / "manifest.json").write_text("{}", encoding="utf-8")
    return exp


def _mk_notes(tmp_path, *, kanban="", sdr="", cahier=""):
    notes = tmp_path / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "kanban_experiments.md").write_text(kanban, encoding="utf-8")
    (notes / "scientific_decisions.md").write_text(sdr, encoding="utf-8")
    (notes / "cahier_laboratoire.md").write_text(cahier, encoding="utf-8")


def _mk_spec(tmp_path, rel="docs/specs/2026-07-15-x-design.md"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# design\n", encoding="utf-8")
    return rel


def test_spec_pointer_satisfies_preregistration(tmp_path):
    # In the kanban + a live spec pointer + never ran => nothing to flag at all.
    # (Asserting == [] rather than a substring's absence: a substring that does not exist yet
    # would make this pass before the implementation.)
    rel = _mk_spec(tmp_path)
    _mk_exp(tmp_path, "exp080_x", config=f"spec: {rel}\n")
    _mk_notes(tmp_path, kanban="exp080_x\n")
    assert all_experiment_gaps(tmp_path) == []


def test_dead_spec_pointer_is_a_gap(tmp_path):
    _mk_exp(tmp_path, "exp081_x", config="spec: docs/specs/does-not-exist.md\n")
    _mk_notes(tmp_path, kanban="exp081_x\n")
    gaps = all_experiment_gaps(tmp_path)
    assert any("exp081_x" in g and "missing file" in g for g in gaps)


def test_legacy_sdr_still_satisfies_preregistration(tmp_path):
    """Non-regression: replacing SDR *by* spec would redden every legacy experiment."""
    _mk_exp(tmp_path, "exp082_legacy")  # no config.yaml at all
    _mk_notes(tmp_path, kanban="exp082_legacy\n", sdr="## 2026-01-01 - exp082_legacy\nbody\n")
    assert all_experiment_gaps(tmp_path) == []


def test_no_sdr_and_no_spec_is_a_gap(tmp_path):
    _mk_exp(tmp_path, "exp083_x")
    _mk_notes(tmp_path, kanban="exp083_x\n")
    gaps = all_experiment_gaps(tmp_path)
    assert any("exp083_x" in g and "no pre-registration" in g for g in gaps)


def test_trading_experiment_exempt_from_cahier(tmp_path):
    rel = _mk_spec(tmp_path)
    _mk_exp(tmp_path, "exp084_trade", config=f"edges: [E-funding-carry]\nspec: {rel}\n", ran=True)
    _mk_notes(tmp_path, kanban="exp084_trade\n")
    assert not any("cahier" in g for g in all_experiment_gaps(tmp_path))


def test_science_experiment_still_needs_cahier(tmp_path):
    """The trading exemption must not leak to non-trading experiments."""
    rel = _mk_spec(tmp_path)
    _mk_exp(tmp_path, "exp085_sci", config=f"spec: {rel}\n", ran=True)
    _mk_notes(tmp_path, kanban="exp085_sci\n")
    gaps = all_experiment_gaps(tmp_path)
    assert any("exp085_sci" in g and "cahier" in g for g in gaps)


def test_both_gates_share_the_rule(tmp_path):
    """Anti-divergence: the blocking and advisory gates must agree."""
    rel = _mk_spec(tmp_path)
    _mk_exp(tmp_path, "exp086_x", config=f"spec: {rel}\n")
    _mk_notes(tmp_path, kanban="exp086_x\n")
    assert all_experiment_gaps(tmp_path) == []
    assert staged_experiment_gaps(tmp_path, {"exp086_x"}) == []
