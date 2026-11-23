"""Typology packs (wi-brain-typology-packs, spec-brain-typology-packs E3, TYPO-1, TYPO-4, TYPO-6): a pack of
source/packs.yaml names its typologies and bundles a kind's parts; the engine ships software, research and
hardware-cad; a brain takes one with ``from: engine``; a project's typologies propose its packs by a plan the owner
applies, never silently.
Fictitious names only."""

import json

import pytest
from brain import cli, neutral, render, schema, typologies, typology_packs

PACKS = """\
# the owner's comment, kept
marketplace:
  name: demo-market
  owner:
    name: Ada

packs:
  core:              # every session's
    core: true
    hooks: true
  writing:
    projects: [other]   # a brain pack for one project
    typologies: [creation]
# a trailing comment of the file
"""


@pytest.fixture
def brain(store, monkeypatch):
    """The store fixture's root: a brain with a neutral source and a registry of demo (a cli) and other (creation)."""
    root = store.parents[1]
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    (root / "projects.yaml").write_text(
        "demo:\n  root: .\n  lifecycle: {typologies: [cli]}\n"
        "other:\n  root: ../other\n  lifecycle: {typologies: [creation]}\n", encoding="utf-8")
    (root.parent / "other").mkdir(exist_ok=True)
    (root / "source").mkdir()
    (root / "source" / "packs.yaml").write_text(PACKS, encoding="utf-8")
    return root


def _run(root, *args) -> int:
    return cli.main(["--root", str(root), "typologies", *args])


def test_the_engines_packs_are_software_and_research_and_carry_the_clauses_of_done():
    assert typology_packs.self_check() == []
    packs = typology_packs.engine()
    assert set(packs) == {"software", "research", "hardware-cad"}
    assert packs["software"]["typologies"] == ["software"] and packs["research"]["typologies"] == ["research"]
    assert packs["hardware-cad"]["typologies"] == ["hardware-cad"]
    cat = typologies.engine()
    # the hardware pack's clauses reach an item of the entry and of its sub-profiles
    hw = ["physical-evidence", "failsafe-tested", "design-checked"]
    assert [c.id for c in cat.clauses["hardware-cad"]] == hw
    assert [c.id for c in cat.done_clauses(["hardware"])][-3:] == hw
    # the clauses moved from the catalog into the packs: an item's definition of done is unchanged
    assert [c.id for c in cat.clauses["software"]] == ["pr", "test", "same-pr-docs", "scout", "worktree"]
    assert [c.id for c in cat.done_clauses(["cli"])][-5:] == ["pr", "test", "same-pr-docs", "scout", "worktree"]
    assert "done" not in (typologies._read()["entries"]["software"])


def test_from_engine_lays_the_brains_keys_over_the_engines_pack():
    given = {"from": "engine", "projects": ["demo"], "layers": ["code"]}
    applied = typology_packs.overlay("software", given)
    assert applied["layers"] == ["code"]                       # the nearest wins: the brain's list replaces
    assert applied["typologies"] == ["software"] and applied["projects"] == ["demo"]
    assert applied["done"] == typology_packs.engine()["software"]["done"]
    assert typology_packs.overlay("writing", {"projects": ["x"]}) == {"projects": ["x"]}   # not from the engine
    assert typology_packs.overlay("nothing", given) is given   # an id the engine does not ship: check says why


def test_a_packs_parts_are_checked_their_shape_an_error_an_unknown_id_a_note_in_read_mode():
    bad = {"typologies": "software", "standards": {"profiles": "cli"}, "stages": {"build": "x"},
           "done": [{"id": "x"}], "doors": [{"id": "d"}], "roles": [{"id": "r", "text": "a"}, {"id": "r", "text": "b"}]}
    errors = typology_packs.part_errors("p", bad, strict=False)
    assert any("typologies is a list of ids" in e for e in errors)
    assert any("standards is {catalogs" in e for e in errors)
    assert any("stages is {stage" in e for e in errors)
    assert any("done: clause" in e for e in errors)
    assert any("doors is a list of {id, text}" in e for e in errors)
    assert any("roles: 'r' twice" in e for e in errors)
    later = {"typologies": ["podcast-x"], "layers": ["moodboard"], "guards": ["rights"], "registry": ["media"],
             "stages": {"shoot": ["a gate"]}, "standards": {"profiles": ["video-x"], "catalogs": ["video"]}}
    notes: list[str] = []
    assert typology_packs.part_errors("p", later, strict=False, notes=notes) == []
    assert len(notes) == 7                                     # each unknown id kept, noted once
    strict = typology_packs.part_errors("p", later, strict=True)
    assert len(strict) == 7 and all("not" in e for e in strict)


def test_brain_check_reads_a_typology_pack_and_refuses_a_wrong_from_or_a_typology_core(brain, monkeypatch):
    monkeypatch.setattr(schema, "mode", lambda: schema.STRICT)
    src = neutral.load(brain)
    assert neutral.check(src) == []
    f = brain / "source" / "packs.yaml"
    f.write_text(PACKS + "  lab:\n    from: engine\n  soft:\n    from: elsewhere\n", encoding="utf-8")
    errors = neutral.check(neutral.load(brain))
    assert any("pack lab: from: engine, but the engine ships no typology pack 'lab'" in e for e in errors)
    assert any("pack soft: from is 'engine'" in e for e in errors)
    f.write_text(PACKS.replace("    hooks: true\n", "    hooks: true\n    typologies: [software]\n"),
                 encoding="utf-8")
    assert any("a typology pack is never the core pack" in e for e in neutral.check(neutral.load(brain)))


def test_a_project_s_typologies_propose_the_engines_pack_and_nothing_is_written_without_apply(brain, capsys):
    before = (brain / "source" / "packs.yaml").read_text(encoding="utf-8")
    assert _run(brain, "propose", "demo") == 0
    out = capsys.readouterr().out
    assert "demo: typologies cli" in out
    assert "software (engine; for software): to take: packs.yaml gains it, from: engine, projects: [demo]" in out
    assert "research (engine" not in out and "writing" not in out    # a cli meets software only
    assert "layers its store lacks" in out and "research_graph --store \"" in out and "layers add code" in out
    assert "standards profiles it does not opt in to: software" in out
    assert "(plan only: brain typologies propose demo --apply writes it)" in out
    assert (brain / "source" / "packs.yaml").read_text(encoding="utf-8") == before


def test_apply_appends_the_pack_with_comments_kept_then_a_rerun_proposes_nothing(brain, capsys):
    assert _run(brain, "propose", "demo", "--apply") == 0
    text = (brain / "source" / "packs.yaml").read_text(encoding="utf-8")
    assert "# the owner's comment, kept" in text and "# a trailing comment of the file" in text
    assert "  software:" in text and "    from: engine\n    projects: [demo]\n" in text
    src = neutral.load(brain)
    soft = next(p for p in src.packs if p.id == "software")
    assert soft.projects == ["demo"] and soft.spec["layers"] == ["code", "docs_tests", "features"]
    assert neutral.check(src) == []
    # the render gives it to demo only (node-local, TYPO-6), never to every project
    assert soft in render._packs_for(src, "demo") and soft not in render._packs_for(src, "other")
    capsys.readouterr()
    assert _run(brain, "--json", "propose", "demo") == 0
    data = json.loads(capsys.readouterr().out)
    assert [(p["pack"], p["active"], p["step"]) for p in data["packs"]] == [("software", True, "")]


def test_apply_adds_the_project_to_a_brain_pack_s_projects_flow_or_block(brain, capsys):
    f = brain / "projects.yaml"
    f.write_text(f.read_text(encoding="utf-8") + "third:\n  root: ../third\n  lifecycle: {typologies: [creation]}\n",
                 encoding="utf-8")
    (brain.parent / "third").mkdir(exist_ok=True)
    assert _run(brain, "propose", "third", "--apply") == 0
    text = (brain / "source" / "packs.yaml").read_text(encoding="utf-8")
    assert "    projects: [other, third]   # a brain pack for one project" in text
    block = PACKS.replace("    projects: [other]   # a brain pack for one project\n",
                          "    projects:\n      - other\n")
    (brain / "source" / "packs.yaml").write_text(block, encoding="utf-8")
    assert _run(brain, "propose", "third", "--apply") == 0
    assert "    projects:\n      - other\n      - third\n" in (brain / "source" / "packs.yaml").read_text(
        encoding="utf-8")


def test_apply_is_refused_and_nothing_written_when_the_source_would_fail_its_check(brain, monkeypatch, capsys):
    before = (brain / "source" / "packs.yaml").read_text(encoding="utf-8")
    real = neutral.check
    calls = {"n": 0}

    def worse(src, nodes=None):
        calls["n"] += 1
        return real(src, nodes) + (["a new error"] if calls["n"] > 1 else [])
    monkeypatch.setattr(neutral, "check", worse)
    assert _run(brain, "propose", "demo", "--apply") == 1
    assert "a new error; nothing written" in capsys.readouterr().out
    assert (brain / "source" / "packs.yaml").read_text(encoding="utf-8") == before


def test_a_project_without_typologies_or_not_registered(brain, capsys):
    (brain / "projects.yaml").write_text("demo:\n  root: .\n", encoding="utf-8")
    assert _run(brain, "propose", "demo") == 0
    assert "no lifecycle.typologies" in capsys.readouterr().out
    assert _run(brain, "propose", "ghost") == 2
    assert "not a project of this brain's registry" in capsys.readouterr().out


def test_brain_typologies_packs_lists_the_engines_and_the_brains(brain, capsys):
    assert _run(brain, "packs") == 0
    out = capsys.readouterr().out
    assert "software (engine): for software; not taken" in out
    assert "writing (packs.yaml): for creation; taken for other" in out
    assert "  done: pr, test, same-pr-docs, scout, worktree" in out
    assert _run(brain, "--json", "packs") == 0
    rows = {r["id"]: r for r in json.loads(capsys.readouterr().out)["packs"]}
    assert rows["research"]["layers"] == ["research"] and rows["writing"]["projects"] == ["other"]


def test_an_unreadable_engine_pack_file_is_one_error(monkeypatch, tmp_path):
    bad = tmp_path / "typology_packs.yaml"
    bad.write_text("v: 2\n", encoding="utf-8")
    monkeypatch.setattr(typology_packs, "FILE", bad)
    typology_packs._read.cache_clear()
    try:
        with pytest.raises(typology_packs.PackError):
            typology_packs.engine()
        assert typology_packs.overlay("software", {"from": "engine"}) == {"from": "engine"}
    finally:
        typology_packs._read.cache_clear()


# --- the review's cases ----------------------------------------------------------------------------------------------

def test_a_layers_own_stage_is_known():
    assert typology_packs.part_errors("p", {"stages": {"preregistration-backtest": ["a gate"]}}, strict=True) == []


def test_check_knows_the_brains_own_typology_ids(brain, monkeypatch):
    (brain / "config.json").write_text('{"v": 1, "typologies": {"podcast": {"parent": "creation"}}}', encoding="utf-8")
    (brain / "source" / "packs.yaml").write_text(PACKS.replace("typologies: [creation]", "typologies: [podcast]"),
                                                encoding="utf-8")
    monkeypatch.setattr(schema, "mode", lambda: schema.STRICT)
    assert not any("podcast" in e for e in neutral.check(neutral.load(brain)))


def test_apply_writes_the_packs_own_projects_never_a_nested_mappings(brain):
    nested = PACKS.replace("  writing:\n", "  writing:\n    claude:\n      projects: [zzz]\n")
    (brain / "source" / "packs.yaml").write_text(nested, encoding="utf-8")
    f = brain / "projects.yaml"
    f.write_text(f.read_text(encoding="utf-8") + "third:\n  root: ../third\n  lifecycle: {typologies: [creation]}\n",
                 encoding="utf-8")
    (brain.parent / "third").mkdir(exist_ok=True)
    assert _run(brain, "propose", "third", "--apply") == 0
    text = (brain / "source" / "packs.yaml").read_text(encoding="utf-8")
    assert "      projects: [zzz]\n" in text and "projects: [other, third]" in text


def test_apply_takes_the_files_indent_and_line_ends(brain):
    four = PACKS.replace("\n  core:", "\n    core:").replace("\n    core: true", "\n        core: true") \
        .replace("\n    hooks: true", "\n        hooks: true").replace("\n  writing:", "\n    writing:") \
        .replace("\n    projects: [other]", "\n        projects: [other]") \
        .replace("\n    typologies: [creation]", "\n        typologies: [creation]")
    f = brain / "source" / "packs.yaml"
    f.write_bytes(four.replace("\n", "\r\n").encode("utf-8"))
    assert _run(brain, "propose", "demo", "--apply") == 0
    raw = f.read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"")                           # every line end kept CRLF
    assert b"    software:" in raw and b"        from: engine\r\n        projects: [demo]\r\n" in raw
    assert next(p for p in neutral.load(brain).packs if p.id == "software").projects == ["demo"]


def test_a_refused_or_failed_apply_puts_the_file_back_byte_for_byte(brain, monkeypatch):
    f = brain / "source" / "packs.yaml"
    f.write_bytes(PACKS.replace("\n", "\r\n").encode("utf-8"))
    original = f.read_bytes()
    real = neutral.check
    calls = {"n": 0}

    def boom(src, nodes=None):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("the check broke")
        return real(src, nodes)
    monkeypatch.setattr(neutral, "check", boom)
    with pytest.raises(RuntimeError):
        typology_packs.apply(brain, "demo", typology_packs.propose(brain, "demo")[1])
    assert f.read_bytes() == original


def test_apply_without_a_packs_yaml_is_refused_not_a_traceback(brain, capsys):
    (brain / "source" / "packs.yaml").unlink()
    assert _run(brain, "propose", "demo", "--apply") in (1, 2)
    assert "Traceback" not in capsys.readouterr().err


def test_a_brain_pack_bearing_an_engine_packs_id_is_said_to_hide_it(brain, capsys):
    (brain / "source" / "packs.yaml").write_text(PACKS + "  software:\n    procedures: []\n", encoding="utf-8")
    assert _run(brain, "propose", "demo", "--apply") == 0
    out = capsys.readouterr().out
    assert "software (packs.yaml; for software): hidden by packs.yaml's own pack software" in out
    assert "nothing for --apply to write" in out


def test_a_brains_own_done_is_a_note_and_malformed_parts_list_safely(brain, monkeypatch, capsys):
    f = brain / "source" / "packs.yaml"
    f.write_text(PACKS.replace("    typologies: [creation]\n", "    typologies: [creation]\n    layers: research\n"
                               "    done: [{id: shipped, text: shipped}]\n"), encoding="utf-8")
    monkeypatch.setattr(schema, "mode", lambda: schema.STRICT)
    errors = neutral.check(neutral.load(brain))
    assert any("a brain's clauses of done are not read" in e for e in errors)
    assert any("layers is a list of ids" in e for e in errors)
    assert _run(brain, "packs") == 0
    assert "layers: r, e" not in capsys.readouterr().out


def test_a_yaml_special_project_name_is_quoted(brain):
    f = brain / "projects.yaml"
    f.write_text(f.read_text(encoding="utf-8") + "'on':\n  root: ../on\n  lifecycle: {typologies: [software]}\n",
                 encoding="utf-8")
    (brain.parent / "on").mkdir(exist_ok=True)
    assert _run(brain, "propose", "on", "--apply") == 0
    assert next(p for p in neutral.load(brain).packs if p.id == "software").projects == ["on"]


def test_self_check_finds_a_clause_id_given_twice(monkeypatch):
    packs = typology_packs.engine()
    packs["software"]["done"].append({"id": "verified", "text": "again"})
    packs["other"] = {"typologies": ["software"], "done": [{"id": "pr", "text": "again"}]}
    monkeypatch.setattr(typology_packs, "engine", lambda: packs)
    errors = typology_packs._clause_collisions()
    assert any("'verified' is the generic sentence's" in e for e in errors)
    assert any("'pr' also given to software" in e for e in errors)
