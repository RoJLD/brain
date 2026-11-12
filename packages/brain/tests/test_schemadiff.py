"""brain schema diff and the scout's schema.narrowed (brain.schemadiff, wi-brain-schema-diff; spec-brain-data-compat
N6): what a schema change narrows, and how the PR's Compat: line resolves it. Off by default (an info line), NEW under
config.json audit.schema_diff_strict: a patch never newly refuses."""

import json
from pathlib import Path

import pytest

from brain import cli, init, schema, schemadiff

from conftest import BRAIN, run_git

OBJ = {"type": "object", "additionalProperties": True, "required": ["id"],
       "properties": {"v": {"const": 1}, "id": {"type": "string", "pattern": "^x-"},
                      "kind": {"enum": ["a", "b"]}, "n": {"type": ["integer", "null"], "minimum": 0, "maximum": 10},
                      "tags": {"type": "array", "items": {"type": "string", "maxLength": 20}}}}


def edit(**changes):
    """OBJ with ``changes`` applied: ``prop__key=value`` sets a property's keyword (None removes it), ``key=value``
    the root's."""
    out = json.loads(json.dumps(OBJ))
    for path, value in changes.items():
        target, key = (out["properties"][path.split("__")[0]], path.split("__")[1]) if "__" in path else (out, path)
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value
    return out


@pytest.mark.parametrize("new,expected", [
    ({"properties": {k: v for k, v in OBJ["properties"].items() if k != "kind"}}, "/kind: removed"),
    ({"required": ["id", "kind"]}, "/kind: newly required"),
    ({"kind__enum": ["a"]}, '/kind: enum narrowed (no longer "b")'),
    ({"n__type": "integer"}, "/n: type narrowed (integer|null -> integer)"),
    ({"tags__type": "array", "id__type": "integer"}, "/id: type narrowed (string -> integer)"),
    ({"v__const": 2}, "/v: const 1 -> 2"),
    ({"additionalProperties": False}, "/*: closed"),
    ({"n__minimum": 1}, "/n: minimum 0 -> 1"),
    ({"n__maximum": 9}, "/n: maximum 10 -> 9"),
    ({"id__pattern": "^y-"}, "/id: pattern changed"),
    ({"id__minLength": 3}, "/id: minLength added -> 3"),
    ({"allOf": [{"if": {"properties": {"kind": {"const": "a"}}}, "then": {"required": ["n"]}}]},
     "/: an allOf entry added"),
    ({"tags__items": {"type": "string", "maxLength": 10}}, "/tags[]: maxLength 20 -> 10"),
])
def test_each_narrowing_is_found(new, expected):
    found = schemadiff.json_narrowed(OBJ, edit(**new) if "properties" not in new else {**OBJ, **new})
    assert any(expected in line for line in found), found


@pytest.mark.parametrize("new", [
    {"properties": {**OBJ["properties"], "extra": {"type": "string"}}},          # an optional property
    {"kind__enum": ["a", "b", "c"]},                                             # an enum widened
    {"n__type": ["integer", "null", "string"]},                                  # a type widened
    {"n__minimum": None, "n__maximum": 11},                                      # bounds loosened
    {"description": "now with prose", "kind__description": "the kind"},          # prose
    {"required": []},                                                            # a field no longer required
])
def test_what_only_widens_is_no_narrowing(new):
    assert schemadiff.json_narrowed(OBJ, edit(**new) if "properties" not in new else {**OBJ, **new}) == []


def test_a_bumped_v_is_the_format_moving():
    """A v bumped is a narrowing of its own (the old files no longer validate), said once, never as a const."""
    d = schemadiff.compare("x/ddr.schema.json", json.dumps(OBJ), json.dumps(edit(v__const=2, kind__enum=["a"])))
    assert d.v == (1, 2) and d.narrowed == [
        '/kind: enum narrowed (no longer "b")', "/v: v1 -> v2: the files of v1 no longer validate (the format moves)"]
    alone = schemadiff.compare("x/ddr.schema.json", json.dumps(OBJ), json.dumps(edit(v__const=2)))
    assert alone.narrowed == ["/v: v1 -> v2: the files of v1 no longer validate (the format moves)"]
    assert schemadiff.compare("x/ddr.schema.json", None, json.dumps(OBJ)).narrowed == []      # a new schema
    assert schemadiff.compare("x/ddr.schema.json", json.dumps(OBJ), None).narrowed == ["the schema removed"]
    broken = schemadiff.compare("x/ddr.schema.json", json.dumps(OBJ), "{not json")
    assert broken.error and broken.narrowed == [broken.error]


@pytest.mark.parametrize("old,new", [
    ({"type": "object", "properties": {"a": {"type": 5}}}, {"type": "object", "properties": {"a": {"type": 6}}}),
    ({"properties": {"a": {"required": True}}}, {"properties": {"a": {"required": False}}}),     # draft 03
    ({"enum": None}, {"enum": ["x"]}),
    ({"properties": []}, {"properties": {"a": {}}}),
    ({"allOf": {"x": 1}}, {"allOf": [{"required": ["a"]}]}),
])
def test_an_odd_schema_never_crashes(old, new):
    """The scout runs on every registered repo: a schema of an unexpected shape is a narrowing it cannot weigh, or
    none, never a traceback."""
    d = schemadiff.compare("x/a.schema.json", json.dumps(old), json.dumps(new))
    assert isinstance(d.narrowed, list)


def test_what_the_engines_schemas_hide_in_conditions_and_refs_is_found():
    """The ar, ddr and event schemas carry their conditional fields in allOf[].then.required; sr points at $defs."""
    ddr = json.loads((schema.SCHEMA_DIR / "ddr.schema.json").read_text(encoding="utf-8"))
    i, entry = next((i, e) for i, e in enumerate(ddr["allOf"]) if "then" in e and "required" in e["then"])
    tighter = json.loads(json.dumps(ddr))
    tighter["allOf"][i]["then"]["required"] = [*entry["then"]["required"], "zz_new"]
    assert f"/allOf[{i}]/then/zz_new: newly required" in schemadiff.json_narrowed(ddr, tighter)
    assert schemadiff.json_narrowed({"$ref": "#/$defs/a"}, {"$ref": "#/$defs/b"}) == ["/: $ref #/$defs/a -> #/$defs/b"]
    assert schemadiff.json_narrowed({}, {"additionalProperties": {"type": "string"}}) == [
        "/*: type narrowed (any -> string)"]
    assert schemadiff.json_narrowed({"anyOf": [{}, {}]}, {"anyOf": [{}]}) == ["/: anyOf changed"]
    assert schemadiff.json_narrowed({}, {"uniqueItems": True}) == ["/: uniqueItems added"]
    assert schemadiff.json_narrowed({"items": [{}, {}]}, {"items": [{}, {"type": "string"}]}) == [
        "[][1]: type narrowed (any -> string)"]


@pytest.mark.parametrize("old,new", [
    ({"type": "integer"}, {"type": "number"}),
    (False, {}), ({"type": "string"}, True), ({}, {"items": True}),
])
def test_a_widening_of_types_and_booleans_is_no_narrowing(old, new):
    assert schemadiff.json_narrowed(old, new) == []


STORE = ("node_types: [WorkItem, Lesson]\nedge_types: [depends_on, led_to]\nstatuses: [todo, done, open]\n"
         "status_by_type:\n  WorkItem: [todo, done]\nrequired_props:\n  Lesson: [trigger]\n")


@pytest.mark.parametrize("new,expected", [
    (STORE.replace(", Lesson]", "]"), "node_types: Lesson removed"),
    (STORE.replace(", led_to]", "]"), "edge_types: led_to removed"),
    (STORE.replace("WorkItem: [todo, done]", "WorkItem: [todo]"), "status_by_type.WorkItem: done removed"),
    (STORE.replace("status_by_type:\n", "status_by_type:\n  Lesson: [open]\n"),
     "status_by_type.Lesson: its statuses restricted to open"),
    (STORE.replace("Lesson: [trigger]", "Lesson: [trigger, check]"), "required_props.Lesson: check newly required"),

])
def test_a_store_schema_narrowed(new, expected):
    assert expected in schemadiff.compare("notes/graph/schema.yaml", STORE, new).narrowed


def test_a_type_whose_statuses_were_open_given_a_list_narrows():
    """status_by_type.T null (any status) then a list: the other statuses are refused."""
    old = STORE.replace("status_by_type:\n", "status_by_type:\n  Lesson:\n")
    new = STORE.replace("status_by_type:\n", "status_by_type:\n  Lesson: [open]\n")
    assert "status_by_type.Lesson: its statuses restricted to open" in schemadiff.compare("s/schema.yaml", old,
                                                                                          new).narrowed


def test_a_store_schema_that_only_grows_narrows_nothing():
    grown = STORE.replace("[WorkItem, Lesson]", "[WorkItem, Lesson, Note]").replace("open]", "open, closed]")
    assert schemadiff.compare("notes/graph/schema.yaml", STORE, grown).narrowed == []


def test_a_templates_variables_are_read():
    text = "{owner_line}node_types: [A, B]\n"
    assert schemadiff.compare("t/templates/schemas/default.yaml", text, text.replace(", B", "")).narrowed == [
        "node_types: B removed"]


@pytest.mark.parametrize("kind", sorted(schema.SCHEMAS))
def test_the_engines_schemas_read_and_compare_clean_with_themselves(kind):
    text = (schema.SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8")
    assert schemadiff.compare(f"{kind}.schema.json", text, text).narrowed == []


def test_the_default_store_schema_template_reads():
    path = init.TEMPLATES / "schemas" / "default.yaml"
    text = path.read_text(encoding="utf-8")
    assert schemadiff.is_schema("packages/brain/src/brain/templates/schemas/default.yaml")
    assert schemadiff.compare("templates/schemas/default.yaml", text, text.replace("Lesson]", "]")).narrowed


def test_which_files_are_schemas():
    yes = ["src/x/schemas/ddr.schema.json", "notes/graph/schema.yaml", "src/research_graph/templates/schema.yaml",
           "pkg/templates/schemas/default.yaml"]
    no = ["tests/fixtures/stores/v1/brain/notes/graph/schema.yaml", "docs/schema.md", "config.json",
          "src/x/schemas/README.md"]
    assert [p for p in yes + no if schemadiff.is_schema(p)] == yes


def test_the_compat_lines_are_read():
    body = ("Fixes the reader.\n\nCompat: migration mig-ddr-v2\n- **Compat:** breaking (adr-2026-11-12-drop-x)\n"
            "compat: additive\nNot a Compat: line in prose\n")
    assert schemadiff.compat(body) == [("migration", "mig-ddr-v2"), ("breaking", "adr-2026-11-12-drop-x"),
                                       ("additive", "")]
    # a word is no id: such a line resolves nothing
    assert schemadiff.compat("Compat: breaking changes to ddr\nCompat: migration TBD\n") == [
        ("breaking", ""), ("migration", "")]


def test_only_an_adr_or_a_migration_with_its_fixture_resolves(tmp_path):
    from brain import inventory
    tree = inventory.Tree(tmp_path, {"tests/fixtures/formats/ddr/v2/older.yaml": ""})
    d = schemadiff.compare("s/ddr.schema.json", json.dumps(OBJ), json.dumps(edit(v__const=2)))
    for body in ("Compat: additive", "Compat: breaking changes", "Compat: migration TBD"):
        assert not schemadiff.resolve(schemadiff.Diff(d.path, list(d.narrowed), d.v), schemadiff.compat(body),
                                      tree).resolved, body
    assert schemadiff.resolve(d, schemadiff.compat("Compat: migration mig-ddr-v2"), tree).resolved


def test_a_renamed_schema_narrows_for_its_readers(tmp_path):
    from brain import inventory
    text = json.dumps(OBJ)
    base = inventory.Tree(tmp_path, {"s/ddr.schema.json": ""})
    new = inventory.Tree(tmp_path, {"s/ddr2.schema.json": ""})
    base.text = lambda p: text      # the same content under another name
    new.text = lambda p: text
    (d,) = schemadiff.diffs([("R100", "s/ddr.schema.json", "s/ddr2.schema.json")], base, new, "")
    assert d.narrowed == ["renamed from s/ddr.schema.json"]


# --- the command and the scout, on a repo ---------------------------------------------------------------------------

SCHEMA = "src/lab/schemas/ddr.schema.json"
README = "# lab\n\nThe lab.\n"


@pytest.fixture
def lab(make_repo, tmp_path, monkeypatch):
    repo = make_repo("lab", {"README.md": README, "pyproject.toml": '[project]\nname = "lab"\n',
                             "src/lab/__init__.py": "", SCHEMA: json.dumps(OBJ, indent=1) + "\n"})
    run_git(repo, "tag", "v1")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {repo.as_posix()}, production: [.]}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    run_git(repo, "checkout", "-q", "-b", "feature")
    return repo


def write(repo: Path, rel: str, data) -> None:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(data if isinstance(data, str) else json.dumps(data, indent=1) + "\n", encoding="utf-8",
                 newline="\n")


@pytest.fixture
def strict_config(tmp_path, monkeypatch):
    data = json.loads(BRAIN.read_text(encoding="utf-8"))
    data["audit"] = {"schema_diff_strict": True}
    cfg = tmp_path / "strict" / "config.json"
    cfg.parent.mkdir()
    (cfg.parent / "rules.md").write_text((BRAIN.parent / "rules.md").read_text(encoding="utf-8"), encoding="utf-8")
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    return cfg


def diff(capsys, repo, *args) -> tuple[int, dict]:
    rc = cli.main(["schema", "diff", "--against", "v1", "--repo-dir", str(repo), "--json", *args])
    return rc, json.loads(capsys.readouterr().out)


def test_the_command_reports_and_refuses_only_when_strict(lab, capsys, tmp_path):
    write(lab, SCHEMA, edit(kind__enum=["a"]))
    rc, data = diff(capsys, lab)
    assert rc == 0 and not data["strict"]
    assert data["schemas"] == [{"path": SCHEMA, "narrowed": ['/kind: enum narrowed (no longer "b")'], "v": [1, 1],
                                "resolved": ""}]
    assert diff(capsys, lab, "--strict")[0] == 1
    body = tmp_path / "body.md"
    body.write_text("Compat: breaking adr-2026-11-12-drop-b\n", encoding="utf-8")
    rc, data = diff(capsys, lab, "--strict", "--pr-body", str(body))
    assert rc == 0 and data["schemas"][0]["resolved"] == "Compat: breaking adr-2026-11-12-drop-b"


def test_a_migration_resolves_only_with_v_bumped_and_its_fixture(lab, capsys):
    write(lab, SCHEMA, edit(kind__enum=["a"], v__const=2))
    run_git(lab, "add", "-A")
    run_git(lab, "commit", "-q", "-m", "ddr v2\n\nCompat: migration mig-ddr-v2")
    rc, data = diff(capsys, lab, "--strict")
    assert rc == 1 and data["compat"] == ["migration mig-ddr-v2"]          # no fixture of v2 yet
    capsys.readouterr()
    assert cli.main(["schema", "diff", "--against", "v1", "--repo-dir", str(lab)]) == 0
    assert "a fixture fixtures/formats/ddr/v2/" in capsys.readouterr().out
    write(lab, "tests/fixtures/formats/ddr/v2/older.yaml", "v: 2\nid: x-1\n")
    rc, data = diff(capsys, lab, "--strict")
    assert rc == 0 and data["schemas"][0]["resolved"].startswith("Compat: migration mig-ddr-v2, v1 -> v2")


def test_the_owners_opt_in_makes_it_strict(lab, capsys, strict_config):
    write(lab, SCHEMA, edit(required=["id", "kind"]))
    rc, data = diff(capsys, lab)
    assert rc == 1 and data["strict"]


def test_it_runs_in_a_repo_with_no_brain(lab, capsys, monkeypatch):
    """CI's checkout of the engine holds no graph store and no personal brain: the diff never asks for one."""
    from brain import paths

    def no_brain(*a, **k):
        raise SystemExit("brain: no notes/graph/schema.yaml above the current folder")
    monkeypatch.setattr(paths, "find_root", no_brain)
    write(lab, SCHEMA, edit(kind__enum=["a"]))
    rc, data = diff(capsys, lab)
    assert rc == 0 and data["schemas"][0]["path"] == SCHEMA


def test_a_tag_that_does_not_exist_is_a_usage_error(lab, capsys):
    assert cli.main(["schema", "diff", "--against", "v9", "--repo-dir", str(lab)]) == 2


def scout(capsys, repo) -> dict:
    rc = cli.main(["audit", "--diff", "--repo-dir", str(repo), "--json"])
    data = json.loads(capsys.readouterr().out)
    return {"rc": rc, **{f["unit"]: f["tag"] for f in data["findings"] if f["check"] == "schema.narrowed"}}


def test_the_scout_shows_a_narrowing_as_info_by_default(lab, capsys):
    write(lab, SCHEMA, edit(additionalProperties=False))
    got = scout(capsys, lab)
    assert got[SCHEMA] == "info"
    write(lab, SCHEMA, json.dumps(OBJ, indent=1) + "\n")      # the same change set but the narrowing: same exit
    assert scout(capsys, lab)["rc"] == got["rc"]            # never blocking: info changes no exit code


def test_the_scout_makes_it_new_under_the_opt_in_unless_resolved(lab, capsys, strict_config):
    write(lab, SCHEMA, edit(additionalProperties=False))
    got = scout(capsys, lab)
    assert got[SCHEMA] == "NEW" and got["rc"] == 1
    run_git(lab, "add", "-A")
    run_git(lab, "commit", "-q", "-m", "close ddr\n\nCompat: breaking adr-2026-11-12-close-ddr")
    assert scout(capsys, lab)[SCHEMA] == "justified"


def test_a_widening_is_no_finding(lab, capsys, strict_config):
    write(lab, SCHEMA, edit(kind__enum=["a", "b", "c"]))
    assert SCHEMA not in scout(capsys, lab)
