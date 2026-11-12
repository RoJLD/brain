"""Tolerant readers, strict writers (wi-brain-tolerant-reader) and the validator's keywords (wi-brain-schema-keywords):
spec-brain-data-compat N3, N4 and gap 8. Each format has an older and a newer fixture under tests/fixtures/formats/
<format>/v1/: the older one as brain 0.2.4 wrote it, the newer one with a newer brain's additive keys under the same v.
Both are read (the newer one in read mode, its unknown keys noted), and written back without loss where the engine
writes the format; strict mode (CI at the pin, every write) refuses the unknown keys; a higher v is refused in both."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from brain import __version__, config, init, neutral, permissions, projects, records, schema

FORMATS = Path(__file__).parent / "fixtures" / "formats"


def fixture(fmt: str, which: str) -> Path:
    return next((FORMATS / fmt / "v1").glob(f"{which}.*"))


def refusal(where: str, v: int = 2, known: int = 1) -> str:
    return f"{where}: v{v} is written by brain > {__version__}, which reads v{known}: brain update"


@pytest.fixture
def read_mode(monkeypatch):
    monkeypatch.setenv("BRAIN_STRICT", "0")


# --- the validator's keywords ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", schema.SCHEMAS)
def test_every_keyword_of_the_schemas_is_implemented(kind):
    """A keyword the validator skipped would be a rule nobody enforces (gap 8: maximum, until this PR)."""
    assert schema.unsupported(schema.load(kind)) == []


def test_an_unimplemented_keyword_is_found_and_its_schema_refused(tmp_path, monkeypatch):
    assert schema.unsupported({"properties": {"exclusiveMaximum": {"type": "number", "multipleOf": 5}},
                               "$defs": {"x": {"items": {"uniqueItems": True}}},
                               "allOf": [{"if": {"not": {}}, "then": {}}]}) == ["multipleOf", "not", "uniqueItems"]
    (tmp_path / "config.schema.json").write_text(json.dumps({"properties": {"v": {"const": 1}}, "anyOf": []}),
                                                 encoding="utf-8")
    monkeypatch.setattr(schema, "SCHEMA_DIR", tmp_path)
    schema.load.cache_clear()
    try:
        with pytest.raises(ValueError, match="config.schema.json uses anyOf, which brain.schema does not implement"):
            schema.load("config")
    finally:
        schema.load.cache_clear()


def test_maximum_is_enforced():
    s = {"type": "object", "properties": {"n": {"type": "number", "minimum": 0, "maximum": 100}}}
    for n, want in ((100, []), (0, []), (100.5, ["x.n: above 100"]), (-1, ["x.n: below 0"])):
        errors: list[str] = []
        schema._validate({"n": n}, s, s, "x", errors)
        assert errors == want, n


def test_the_mode_is_strict_in_ci_and_read_elsewhere(monkeypatch):
    monkeypatch.delenv("BRAIN_STRICT")
    monkeypatch.delenv("CI", raising=False)
    assert schema.mode() == schema.READ
    monkeypatch.setenv("CI", "true")
    assert schema.mode() == schema.STRICT
    monkeypatch.setenv("BRAIN_STRICT", "0")      # an older engine reading a newer one's data, in CI: the rollback job
    assert schema.mode() == schema.READ
    monkeypatch.setenv("BRAIN_STRICT", "1")
    monkeypatch.delenv("CI")
    assert schema.mode() == schema.STRICT


def test_newer_refuses_only_a_higher_integer_v():
    assert schema.newer("f", 2) == refusal("f")
    assert schema.newer("f", 1) == schema.newer("f", 0) == schema.newer("f", None) == schema.newer("f", True) == ""
    assert schema.newer("f", "2") == ""      # not an integer: the schema's const reports it


# --- the five schemas: DDR, SR, AR, event, config.json --------------------------------------------------------------

@pytest.mark.parametrize("kind", ["ddr", "sr"])
def test_a_record_round_trips_without_loss(kind, tmp_path, read_mode):
    """Read, then rewritten by the engine (records.write replace=True, strict): a newer brain's fields stay."""
    root = tmp_path / "brain"
    for which in ("older", "newer"):
        rec = yaml.safe_load(fixture(kind, which).read_text(encoding="utf-8"))
        path = records.record_path(root, kind, rec)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture(kind, which), path)
        (loaded,) = [r for _, r in records.load(root)[kind]]
        assert loaded == rec
        errors, warnings = records.check(root)
        assert errors == []
        assert bool(warnings) == (which == "newer")
        assert records.write(root, kind, loaded, replace=True) == path
        assert yaml.safe_load(path.read_text(encoding="utf-8")) == rec, which
        errors, _ = records.check(root, schema.STRICT)
        assert bool(errors) == (which == "newer") and all("unexpected field" in e for e in errors)


def test_the_writer_stays_strict(tmp_path, read_mode):
    """Only a rewrite carries unknown fields, and only those of the file it replaces; a newer record is not replaced."""
    root = tmp_path / "brain"
    newer = yaml.safe_load(fixture("ddr", "newer").read_text(encoding="utf-8"))
    with pytest.raises(SystemExit, match="unexpected field 'confidence'"):
        records.write(root, "ddr", newer)                    # a new record: strict
    older = yaml.safe_load(fixture("ddr", "older").read_text(encoding="utf-8"))
    records.write(root, "ddr", older)
    with pytest.raises(SystemExit, match="unexpected field 'confidence'"):
        records.write(root, "ddr", newer, replace=True)      # the file it replaces did not have it
    path = records.record_path(root, "ddr", older)
    path.write_text(yaml.safe_dump({**older, "v": 2}), encoding="utf-8")
    with pytest.raises(SystemExit, match="v2 is written by brain > .*: brain update"):
        records.write(root, "ddr", older, replace=True)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["v"] == 2   # never overwritten
    errors, _ = records.check(root)
    assert errors == [f"records/ddr/{older['id']}.yaml: " + refusal("ddr")]


def test_ar_lines_are_read_one_by_one(tmp_path, monkeypatch, read_mode):
    """A newer brain's line (a higher v, a new kind) is skipped and counted; an additive field is kept as written;
    a broken line is an error, never a crash."""
    root = tmp_path / "brain"
    f = root / "records" / "ar" / "2026-10.jsonl"
    f.parent.mkdir(parents=True)
    lines = fixture("ar", "newer").read_text(encoding="utf-8").splitlines()
    f.write_text("\n".join(lines + ["<<<<<<< HEAD", "[1, 2]"]) + "\n", encoding="utf-8")
    bad: list[records.Bad] = []
    loaded = records.load(root, bad)["ar"]
    assert [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for _, r in loaded] == [lines[0]]  # byte-exact
    assert [(b.where.name, b.newer) for b in bad] == [("2026-10.jsonl:2", True), ("2026-10.jsonl:3", True),
                                                      ("2026-10.jsonl:4", False), ("2026-10.jsonl:5", False)]
    assert "'release' is a newer brain's kind" in bad[0].reason and refusal("ar") in bad[1].reason
    errors, warnings = records.check(root)
    assert errors == ["records/ar/2026-10.jsonl:4: " + bad[2].reason,
                      "records/ar/2026-10.jsonl:5: ar: a record is a mapping, got list"]
    assert len([w for w in warnings if "line skipped" in w]) == 2
    assert any("unknown field 'signed'" in w for w in warnings)
    assert any("ar.session: unknown field 'host_id'" in w for w in warnings)
    assert records.ar_ids(root) == {"ar-2026-10-30-commit-demo-abcdef1234", "ar-2026-10-30-release-demo-1",
                                    "ar-2026-10-30-commit-demo-fedcba9876"}
    errors, _ = records.check(root, schema.STRICT)
    assert len([e for e in errors if "line skipped" in e]) == 2
    store = root / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    monkeypatch.setattr(records.graph, "node_index", lambda s: {})
    nodes, _, _ = records.graph_view(root, store)                       # the graph still builds
    assert [n["id"] for n in nodes] == ["ar-2026-10-30-commit-demo-abcdef1234"]


def test_the_older_ar_file_reads_clean(tmp_path):
    root = tmp_path / "brain"
    f = root / "records" / "ar" / "2026-10.jsonl"
    f.parent.mkdir(parents=True)
    shutil.copyfile(fixture("ar", "older"), f)
    assert records.check(root, schema.STRICT) == ([], [])


@pytest.mark.parametrize("which", ["older", "newer"])
def test_events_round_trip(which):
    for line in fixture("event", which).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        assert json.loads(json.dumps(event)) == event
        errors, unknown = schema.validate("event", event, schema.READ)
        assert errors == [] and unknown == ([] if which == "older" else ["event: unknown field 'cpu_s'"])
        assert bool(schema.check("event", event)[0]) == (which == "newer")
        assert schema.check("event", {**event, "v": 2})[0] == [refusal("event")]


@pytest.mark.parametrize("which", ["older", "newer"])
def test_config_round_trips(which, tmp_path, monkeypatch, read_mode, capsys):
    root = tmp_path / "brain"
    root.mkdir()
    (root / "projects.yaml").write_text("mine: {root: .}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    shutil.copyfile(fixture("config", which), root / config.FILE)
    data = json.loads(fixture("config", which).read_text(encoding="utf-8"))
    cfg = config.load(root)
    assert cfg.data == data and json.loads(json.dumps(cfg.data)) == data
    assert config.check(root) == []
    assert ("unknown field" in capsys.readouterr().err) == (which == "newer")
    monkeypatch.setenv("BRAIN_STRICT", "1")
    assert bool(config.check(root)) == (which == "newer")
    (root / config.FILE).write_text(json.dumps({**data, "v": 2}), encoding="utf-8")
    assert config.check(root) == [refusal(config.FILE)]


# --- the YAML formats the owner edits -------------------------------------------------------------------------------

@pytest.mark.parametrize("which", ["older", "newer"])
def test_permissions_yaml(which, tmp_path, monkeypatch, read_mode):
    root = tmp_path / "brain"
    root.mkdir()
    (root / "projects.yaml").write_text("mine: {root: .}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    f = root / permissions.FILE
    shutil.copyfile(fixture("permissions", which), f)
    monkeypatch.setenv(permissions.ENV, str(f))
    assert permissions.check() == []
    assert permissions.load().data == yaml.safe_load(f.read_text(encoding="utf-8"))   # kept as written
    assert any(r.text == "Bash(gh secret set *)" and r.verdict == "deny" for r in permissions.load().rules)
    monkeypatch.setenv("BRAIN_STRICT", "1")
    assert len(permissions.check()) == (3 if which == "newer" else 0)
    f.write_text(f.read_text(encoding="utf-8").replace("v: 1", "v: 2"), encoding="utf-8")
    assert permissions.check()[0] == refusal(permissions.FILE)


def test_the_permissions_schema_says_what_brain_permissions_reads():
    """wi-brain-permissions-schema: permissions.schema.json describes brain.permissions' keys (its constants), so a
    change of either without the other fails here, and brain schema diff sees the format move."""
    s = schema.load("permissions")
    assert set(s["properties"]) == set(permissions.SECTIONS)
    assert set(s["$defs"]["rule"]["properties"]) == permissions.RULE_KEYS
    assert set(s["properties"]["never"]["additionalProperties"]["properties"]) == permissions.NEVER_KEYS
    assert s["properties"]["v"] == {"const": 1, "description": "The format's version."}
    for name, extra in (("machines", {"profile"}), ("tenants", {"projects"}), ("sessions", {"project", "parent"})):
        assert set(s["properties"][name]["additionalProperties"]["properties"]) == {"title"} | extra, name


@pytest.mark.parametrize("which", ["older", "newer"])
def test_the_permissions_fixtures_match_the_schema(which):
    """The older file validates strict; the newer one's additive keys are noted in read mode, never errors."""
    data = yaml.safe_load(fixture("permissions", which).read_text(encoding="utf-8"))
    errors, unknown = schema.validate("permissions", data, schema.READ)
    assert errors == [] and bool(unknown) == (which == "newer")
    assert (schema.check("permissions", data)[0] == []) == (which == "older")
    assert schema.check("permissions", {**data, "v": 2})[0] == [refusal("permissions")]


def _packs(root: Path, which: str) -> neutral.Source:
    (root / neutral.FOLDER).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture("packs", which), root / neutral.FOLDER / neutral.PACKS)
    return neutral.load(root)


def test_packs_yaml(tmp_path, monkeypatch, read_mode):
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "none.json"))
    older = neutral.check(_packs(tmp_path / "a", "older"), nodes=[])
    src = _packs(tmp_path / "b", "newer")
    assert src.data == yaml.safe_load(fixture("packs", "newer").read_text(encoding="utf-8"))
    assert neutral.check(src, nodes=[]) == older
    monkeypatch.setenv("BRAIN_STRICT", "1")
    assert neutral.check(src, nodes=[]) == older + ["packs.yaml: unknown key 'targets'"]
    (tmp_path / "b" / neutral.FOLDER / neutral.PACKS).write_text("v: 2\npacks: {}\n", encoding="utf-8")
    assert neutral.check(neutral.load(tmp_path / "b"), nodes=[])[-1] == refusal(neutral.PACKS)


def test_projects_yaml_keys(tmp_path, monkeypatch, read_mode):
    root = tmp_path / "brain"
    root.mkdir()
    f = root / "projects.yaml"
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    shutil.copyfile(fixture("projects", "older"), f)
    older = projects.check(root)
    shutil.copyfile(fixture("projects", "newer"), f)
    assert projects.check(root) == older
    assert projects.raw(root)["mine"]["formats"] == {"alloc": {"glob": "*.json"}}
    p = projects.load(root)["mine"]
    assert [r.lang for r in projects.repos_of(p)] == ["py"]
    # access: read and a second project at a shared root (0.3.0): additive, read by this engine as their own
    assert list(projects.load(root)) == ["mine", "prog"] and projects.load(root)["prog"].shares_root_with == "mine"
    assert list(projects.readonly(root)) == ["upstream"]
    monkeypatch.setenv("BRAIN_STRICT", "1")
    assert projects.check(root) == older + [
        "project mine: unknown key(s) formats (brain projects --keys lists them)",
        f"project mine: repos[0]: unknown key(s) ci (known: {', '.join(sorted(projects.REPO_KEYS))})"]
    with pytest.raises(projects.RepoError, match=r"repos\[0\]: unknown key\(s\) ci"):
        projects.repos_of(p)


def _template(tmp_path: Path, which: str, engine: str = "") -> str:
    folder = tmp_path / which
    shutil.copytree(init.TEMPLATES / init.DEFAULT_TEMPLATE, folder)
    text = fixture("template", which).read_text(encoding="utf-8")
    if engine:
        text = text.replace('engine: ">=0.2.2"', f'engine: "{engine}"')
    (folder / init.MANIFEST).write_text(text, encoding="utf-8")
    return str(folder)


def test_the_template_manifest(tmp_path, monkeypatch, read_mode):
    assert init.load_template(_template(tmp_path, "older")).name == "generic"
    assert init.load_template(_template(tmp_path, "newer")).name == "generic"     # its new key noted, not refused
    monkeypatch.setenv("BRAIN_STRICT", "1")
    with pytest.raises(init.InitError, match=r"unknown key\(s\) upgrades"):
        init.load_template(str(tmp_path / "newer"))
    # the engine range first: a template for a newer engine says so, not "unknown key(s)"
    with pytest.raises(init.InitError, match=r"it needs brain >=9\.0, this is .*brain update"):
        init.load_template(_template(tmp_path / "x", "newer", engine=">=9.0"))


# --- the review's findings (RETRO-1/2/9) ----------------------------------------------------------------------------

def test_a_rewrite_built_afresh_keeps_the_fields_of_the_file_it_replaces(tmp_path, read_mode):
    """A rewrite from a record rebuilt from scratch (brain record sr --replace, ddr --file --replace) puts a newer
    brain's fields back, at their exact place: a list item's field is carried for that item only."""
    root = tmp_path / "brain"
    newer = yaml.safe_load(fixture("ddr", "newer").read_text(encoding="utf-8"))
    older = yaml.safe_load(fixture("ddr", "older").read_text(encoding="utf-8"))
    path = records.record_path(root, "ddr", newer)
    path.parent.mkdir(parents=True)
    shutil.copyfile(fixture("ddr", "newer"), path)
    records.write(root, "ddr", json.loads(json.dumps(older)), replace=True)
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == newer
    other = json.loads(json.dumps(older))
    other["options"][1]["weight"] = 3          # the old file had weight on options[0] only
    with pytest.raises(SystemExit, match=r"ddr.options\[1\]: unexpected field 'weight'"):
        records.write(root, "ddr", other, replace=True)


def test_a_newer_ddr_is_named_as_such(tmp_path, read_mode):
    from brain import decisions
    root = tmp_path / "brain"
    older = yaml.safe_load(fixture("ddr", "older").read_text(encoding="utf-8"))
    path = records.record_path(root, "ddr", older)
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({**older, "v": 2}), encoding="utf-8")
    with pytest.raises(decisions.QueueError, match="v2 is written by brain > .*: brain update"):
        decisions.find(root, older["id"])
    with pytest.raises(decisions.QueueError, match="v2 is written by brain"):
        decisions.find(root, "command-shape")


def test_an_ar_line_never_crashes_the_reader(tmp_path, read_mode):
    root = tmp_path / "brain"
    f = root / "records" / "ar" / "2026-10.jsonl"
    f.parent.mkdir(parents=True)
    good = fixture("ar", "older").read_text(encoding="utf-8").strip()
    f.write_bytes(("[" * 100000 + "\n" + good + "\n").encode() + b'{"v":1,"id":"\xff"}\n'
                  + b'{"v":1,"kind":["x"]}\n{"v":true}\n{"id":"x"}\n')
    bad: list[records.Bad] = []
    assert len(records.load(root, bad)["ar"]) == 1
    assert len(bad) == 5 and not any(b.newer for b in bad)      # corrupt, not a newer brain's: errors in read mode
    assert len(records.check(root)[0]) == 5
    assert records.ar_ids(root) == {json.loads(good)["id"], "�", "x"}


def test_the_keyword_guard_refuses_what_the_validator_half_enforces():
    assert schema.unsupported({"properties": {"a": {"if": {"const": 1}, "then": {"const": 2}}}}) == [
        "if/then outside an allOf entry of their own"]
    assert schema.unsupported({"allOf": [{"if": {}, "then": {}, "required": ["m"]}]}) == [
        "if/then outside an allOf entry of their own"]
    assert schema.unsupported({"items": [{"type": "string"}]}) == ["items as a list"]
    assert schema.unsupported({"allOf": [{"if": {}, "then": {}}, {"required": ["m"]}]}) == []


@pytest.mark.parametrize("value, want", [("off", schema.READ), ("n", schema.READ), ("FALSE", schema.READ),
                                         ("on", schema.STRICT), ("yes", schema.STRICT), ("1", schema.STRICT)])
def test_brain_strict_values(value, want, monkeypatch):
    monkeypatch.setenv("BRAIN_STRICT", value)
    assert schema.mode() == want


@pytest.mark.parametrize("value, want", [("true", schema.STRICT), ("1", schema.STRICT), ("no", schema.READ),
                                         ("off", schema.READ), ("", schema.READ)])
def test_ci_values(value, want, monkeypatch):
    monkeypatch.delenv("BRAIN_STRICT")
    monkeypatch.setenv("CI", value)
    assert schema.mode() == want


def test_a_note_is_printed_once(read_mode, capsys):
    assert schema.tolerate("packs.yaml: unknown key 'x'") == schema.tolerate("packs.yaml: unknown key 'x'") == []
    assert capsys.readouterr().err.count("unknown key 'x'") == 1
