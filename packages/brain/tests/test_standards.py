"""The standards registry (wi-brain-standards-registry): the catalog format, the opt-in of a project (projects.yaml
standards:), brain standards list|show|check, the brief's invariants, and the engine's own catalogs."""

import json
from pathlib import Path

import pytest
import yaml
from brain import brief, cli, projects, schema, standards

FIXTURES = Path(__file__).parent / "fixtures" / "formats" / "standards" / "v1"
INSTALLER = Path(__file__).resolve().parents[1] / "installer"


def _row(sid, **over):
    row = {"id": sid, "domain": "persistence", "statement": f"{sid} holds.", "profiles": ["cli"], "stage": "mvp",
           "enforcement": "check", "check": "a lint", "languages": ["py"], "status": "proposed"}
    row.update(over)
    return row


def _catalog(folder: Path, name: str, rows: list, **top) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{name}.yaml"
    f.write_text(yaml.safe_dump({"v": 1, "catalog": name, "title": f"The {name} catalog", **top, "rows": rows},
                                sort_keys=False), encoding="utf-8")
    return f


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """The engine's catalogs, in a folder of the test's own."""
    folder = tmp_path / "engine-catalogs"
    _catalog(folder, "software", [
        _row("sw-atomic-writes", title="Atomic writes"),
        _row("sw-utc", domain="time", profiles=["any"], stage="prototype", enforcement="review-lens",
             languages=["any"], coverage={"status": "have", "by": "the timestamps"}, status="validated"),
        _row("sw-sbom", domain="supply-chain", profiles=["service"], stage="v1", enforcement="measure"),
        _row("sw-fuzz", domain="testing", stage="scale", enforcement="test-template", adapter="test"),
    ])
    monkeypatch.setattr(standards, "ENGINE_DIR", folder)
    return folder


@pytest.fixture
def registry(tmp_path, monkeypatch, store):
    """demo (the store's root) and a registry folder ``brain`` beside it, with a local research catalog."""
    root = store.parents[1]
    reg = tmp_path / "brain" / "projects.yaml"
    _catalog(reg.parent / "standards", "research", [
        _row("res-pre-registration", domain="method", profiles=["research"], stage="prototype",
             enforcement="review-lens", languages=["any"]),
    ])

    def write(entry: str) -> Path:
        reg.write_text(f"demo:\n  root: {root.as_posix()}\n{entry}", encoding="utf-8")
        return reg
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    write("")
    return write


# --- the catalog format ---------------------------------------------------------------------------------------

def test_the_format_is_registered_as_a_whole_new_format():
    import sys
    sys.path.insert(0, str(INSTALLER))
    try:
        import release_check
    finally:
        sys.path.remove(str(INSTALLER))
    assert release_check.SCHEMAS["standards"] == ("packages/brain/src/brain/schemas/standards.schema.json",)
    assert "standards" in schema.SCHEMAS and schema.known_v("standards") == 1


def test_a_catalog_reads_into_rows(engine):
    [cat] = standards.engine_catalogs()
    assert cat.name == "software" and cat.engine and cat.errors == [] and cat.notes == []
    by = {r.id: r for r in cat.rows}
    assert by["sw-utc"].coverage == {"status": "have", "by": "the timestamps"} and by["sw-utc"].covers("ts")
    assert by["sw-fuzz"].adapter == "test" and not by["sw-fuzz"].covers("ts")


def test_the_older_fixture_reads_clean_and_the_newer_one_only_in_read_mode(monkeypatch):
    older = standards.load_file(FIXTURES / "older.yaml")
    assert older.errors == [] and older.notes == [] and [r.id for r in older.rows] == ["fx-atomic-writes", "fx-utc"]
    strict = standards.load_file(FIXTURES / "newer.yaml")
    assert any("unexpected field 'owner'" in e for e in strict.errors)       # a newer engine's top-level key
    assert any("unexpected field 'severity'" in e for e in strict.errors)    # and a row's
    assert any("profile 'quantum'" in e for e in strict.errors)              # a newer vocabulary value
    monkeypatch.setenv("BRAIN_STRICT", "0")
    read = standards.load_file(FIXTURES / "newer.yaml")
    assert read.errors == [] and len(read.rows) == 1
    assert any("owner" in n for n in read.notes) and any("quantum" in n for n in read.notes)


def test_a_higher_v_is_refused_and_its_rows_not_read(tmp_path):
    f = _catalog(tmp_path, "x", [_row("a")])
    f.write_text(f.read_text(encoding="utf-8").replace("v: 1", "v: 2"), encoding="utf-8")
    cat = standards.load_file(f)
    assert cat.rows == [] and any("written by brain >" in e for e in cat.errors)


def test_a_row_breaking_its_schema_is_an_error(tmp_path):
    cat = standards.load_file(_catalog(tmp_path, "x", [_row("a", profiles=[]), {"id": "b"},
                                                       _row("Bad Id")]))
    text = "\n".join(cat.errors)
    assert "profiles" in text and "statement" in text and "pattern" in text or "Bad Id" in text
    assert [r.id for r in cat.rows] == ["a", "Bad Id"]   # b has no statement: left out


def test_unreadable_catalogs(tmp_path):
    with pytest.raises(standards.StandardsError):
        standards.load_file(tmp_path / "none.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("rows: [\n", encoding="utf-8")
    with pytest.raises(standards.StandardsError, match="not YAML"):
        standards.load_file(bad)
    bad.write_text("- a list\n", encoding="utf-8")
    with pytest.raises(standards.StandardsError, match="mapping"):
        standards.load_file(bad)


def test_an_id_twice_is_an_error(tmp_path):
    a = standards.load_file(_catalog(tmp_path, "a", [_row("x"), _row("x")]))
    b = standards.load_file(_catalog(tmp_path, "b", [_row("y"), _row("x")]))
    dups = standards.duplicates([a, b])
    assert len(dups) == 2 and all("standard x" in d for d in dups)
    assert [r.catalog for r in standards.rows_of([a, b]) if r.id == "x"] == ["a"]


# --- the opt-in ---------------------------------------------------------------------------------------------

def test_the_selection_picks_by_profile_and_stage(engine):
    rows = standards.rows_of(standards.engine_catalogs())
    pick = lambda **v: {r.id: why for r, why in standards.applicable(rows, standards.selection(v))}  # noqa: E731
    assert pick(profiles=["cli"], stage="prototype") == {"sw-utc": "profile any, from prototype"}
    assert set(pick(profiles=["cli"], stage="mvp")) == {"sw-utc", "sw-atomic-writes"}
    assert set(pick(profiles=["cli"], stage="scale")) == {"sw-utc", "sw-atomic-writes", "sw-fuzz"}   # not sw-sbom
    assert set(pick(profiles=["service"], stage="v1")) == {"sw-utc", "sw-sbom"}
    got = pick(profiles=["cli"], stage="mvp", include=["sw-sbom"], exclude={"sw-utc": "the project keeps no time"})
    assert got == {"sw-atomic-writes": "profile cli, from mvp", "sw-sbom": "included"}
    assert pick(include=["sw-fuzz"]) == {"sw-fuzz": "included"}
    assert standards.applicable(rows, standards.selection(None)) == []    # no standards: key: nothing


@pytest.mark.parametrize("value, needle", [
    ([], "is a mapping"),
    ({"profiles": ["cli"], "stage": "beta"}, "stage 'beta'"),
    ({"profiles": ["robot"], "stage": "mvp"}, "profile 'robot'"),
    ({"profiles": "cli", "stage": "mvp"}, "profiles is a list"),
    ({"profiles": ["cli"]}, "go together"),
    ({"exclude": {"sw-utc": "short"}}, "a reason of 15"),
    ({"exclude": ["sw-utc"]}, "exclude is a mapping"),
    ({"include": ["sw-nope"]}, "'sw-nope' is no standard"),
    ({"pack": "client"}, "unknown key(s) pack"),
])
def test_a_bad_selection_is_named(value, needle):
    errors = standards.selection_errors("project demo", value, {"sw-utc"})
    assert any(needle in e for e in errors), errors


def test_an_unknown_selection_key_is_a_note_in_read_mode(monkeypatch):
    monkeypatch.setenv("BRAIN_STRICT", "0")
    notes = []
    assert standards.selection_errors("project demo", {"pack": "x"}, set(), notes=notes) == []
    assert notes and "pack" in notes[0]


def test_a_language_gap_is_reported_not_refused(engine):
    rows = standards.rows_of(standards.engine_catalogs())
    chosen = standards.applicable(rows, standards.selection({"profiles": ["cli"], "stage": "mvp"}))
    assert standards.gaps(chosen, {"app": "py", "web": "ts"}) == [
        "sw-atomic-writes: its check covers py, not web (ts)"]


def test_a_project_without_standards_is_not_concerned(engine, registry):
    assert projects.check() == []
    p = projects.get("demo")
    assert p.standards is None and standards.invariants(p) == []


def test_the_registry_check_refuses_a_bad_opt_in_only(engine, registry):
    registry("  standards: {profiles: [cli], stage: mvp, include: [res-pre-registration], "
             "catalogs: [standards/research.yaml]}\n")
    assert projects.check() == []
    p = projects.get("demo")
    assert p.registry_dir == registry("  standards: {profiles: [cli], stage: mvp, include: [res-pre-registration], "
                                      "catalogs: [standards/research.yaml]}\n").parent
    registry("  standards: {profiles: [cli], stage: mvp, include: [res-pre-registration]}\n")
    assert any("'res-pre-registration' is no standard" in e for e in projects.check())   # its catalog not named
    registry("  standards: {catalogs: [standards/none.yaml]}\n")
    assert any("no such catalog" in e for e in projects.check())


def test_the_keys_name_standards():
    assert "standards" in projects.KEYS


# --- the command ----------------------------------------------------------------------------------------------

def test_cli_list_show_check(engine, registry, capsys):
    registry("  standards: {profiles: [research], stage: v1, catalogs: [standards/research.yaml], "
             "include: [sw-atomic-writes]}\n  repos: [{path: ., lang: ts}]\n")
    assert cli.main(["--project", "demo", "standards", "list"]) == 0
    out = capsys.readouterr().out
    assert "== research / method" in out and "== software / persistence" in out and "5 standard(s)" in out
    assert cli.main(["--project", "demo", "standards", "list", "--applicable", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {s["id"]: s["selected_by"] for s in data["standards"]} == {
        "res-pre-registration": "profile research, from prototype", "sw-utc": "profile any, from prototype",
        "sw-atomic-writes": "included"}
    assert cli.main(["--project", "demo", "standards", "list", "--enforcement", "measure"]) == 0
    assert "sw-sbom" in capsys.readouterr().out
    assert cli.main(["--project", "demo", "standards", "show", "sw-utc"]) == 0
    out = capsys.readouterr().out
    assert "the Brain: have: the timestamps" in out and "status: validated" in out
    assert cli.main(["--project", "demo", "standards", "show", "sw-none"]) == 1
    assert cli.main(["--project", "demo", "standards", "check"]) == 0
    out = capsys.readouterr().out
    assert "3 of 5 standard(s) apply to demo" in out
    assert "gap: sw-atomic-writes: its check covers py, not" in out


def test_cli_check_fails_on_a_broken_catalog_or_opt_in(engine, registry, capsys):
    _catalog(engine, "other", [_row("sw-utc")])   # an id twice
    assert cli.main(["--project", "demo", "standards", "check"]) == 1
    out = capsys.readouterr().out
    assert "standard sw-utc: in other.yaml and software.yaml" in out and "not concerned" in out
    (engine / "other.yaml").unlink()
    registry("  standards: {profiles: [cli], stage: alpha}\n")
    assert cli.main(["--project", "demo", "standards", "check", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["concerned"] and any("stage 'alpha'" in e for e in data["errors"])


def test_cli_list_applicable_without_opt_in(engine, registry, capsys):
    assert cli.main(["--project", "demo", "standards", "list", "--applicable"]) == 0
    captured = capsys.readouterr()
    assert "declares no standards:" in captured.err and "no standard applies" in captured.out


def test_cli_a_local_catalog_that_cannot_be_read_exits_1(engine, registry, capsys):
    registry("  standards: {catalogs: [standards/none.yaml]}\n")
    assert cli.main(["--project", "demo", "standards", "check"]) == 1
    assert "no such catalog" in capsys.readouterr().out


# --- the brief ----------------------------------------------------------------------------------------------

def test_the_brief_lists_the_invariants_only_for_a_project_that_opts_in(engine, registry, store):
    (store / "nodes" / "items.yaml").write_text(yaml.safe_dump([
        {"id": "wi-a", "type": "WorkItem", "title": "A", "status": "todo"}]), encoding="utf-8")
    text = brief.render(brief.build(projects.get("demo"), "wi-a", coordinator="local_c", collisions_report=_NoReport()))
    assert "## Invariants" not in text
    registry("  standards: {profiles: [cli], stage: mvp}\n")
    b = brief.build(projects.get("demo"), "wi-a", coordinator="local_c", collisions_report=_NoReport())
    assert b.invariants == ["- `sw-atomic-writes` (persistence, check, proposed): sw-atomic-writes holds.",
                            "- `sw-utc` (time, review-lens): sw-utc holds."]
    assert "## Invariants: the project's standards" in brief.render(b)


class _NoReport:
    items: list = []
    branches: list = []


# --- the engine's own catalogs --------------------------------------------------------------------------------

def test_the_engine_catalogs_are_valid_neutral_and_unique():
    """Every catalog the engine ships reads clean in strict mode, its ids unique across them (a public engine:
    brain check --public reads the same files)."""
    cats = standards.engine_catalogs(strict=True)
    for cat in cats:
        assert cat.errors == [], cat.errors
        assert cat.name == cat.path.stem
    assert standards.duplicates(cats) == []
