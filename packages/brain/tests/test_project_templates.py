"""brain init by profile (wi-brain-project-templates): the templates cli, local-client, service, data-pipeline and
research extend the generic brain (through the bases _project and _software) with the profile's standards selection at
its stage, the CI jobs, the test harness, the format registry's skeleton, the issue and ADR templates and the graph's
layers; the generic template's files are unchanged."""

import hashlib
import json
import re
import subprocess
import sys

import pytest
import yaml
from brain import __version__, cli, init, skew, standards

PROFILES = {"cli": [], "local-client": [], "service": ["operations", "fleet"], "data-pipeline": ["data", "operations"],
            "research": ["ideas", "research", "data"]}
SOFTWARE = (".github/workflows/ci.yml", ".github/ISSUE_TEMPLATE/task.md", "docs/templates/adr.md", "docs/formats.md",
            "tests/conftest.py", "tests/test_harness.py", "fixtures/formats/README.md")


@pytest.fixture
def fresh(tmp_path, monkeypatch, brain_home):
    """An empty folder to become Ada's brain (as test_init's)."""
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.setattr(init, "machine_terms", lambda: {"users": ["ada-l"], "hosts": ["host-a"]})
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])
    root = tmp_path / "ada-brain"
    root.mkdir()
    return root


def test_the_profiles_are_the_engines_templates_and_the_bases_are_not():
    assert set(PROFILES) | {"generic"} == set(init.known_templates())
    with pytest.raises(init.InitError, match="a base the engine's templates extend"):
        init.load_template("_software")
    tpl = init.load_template("service")
    assert tpl.extends == ("_software", "_project", "generic")
    assert set(SOFTWARE) <= set(tpl.files) and set(init.load_template("generic").files) <= set(tpl.files)


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_a_profile_s_brain_checks_and_selects_its_standards(fresh, capsys, name):
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", name, "--stage", "mvp", "--apply"]) == 0
    capsys.readouterr()
    for rel in SOFTWARE:
        assert (fresh / rel).is_file(), rel
    registry = yaml.safe_load((fresh / "projects.yaml").read_text(encoding="utf-8"))
    assert registry["brain"]["standards"] == {"profiles": [name], "stage": "mvp"}
    assert standards.selection_errors("brain", registry["brain"]["standards"]) == []
    schema = yaml.safe_load((fresh / "notes" / "graph" / "schema.yaml").read_text(encoding="utf-8"))
    assert set(PROFILES[name]) <= set(schema["layers"]) and {"work", "decisions", "records", "code"} <= set(
        schema["layers"])
    rules = yaml.safe_load((fresh / "boundary.yaml").read_text(encoding="utf-8"))["rules"]
    assert {"glob": ".github/**", "side": "engine", "target": ".github/",
            "why": "the CI jobs and the issue template"} in rules
    config = yaml.safe_load((fresh / "config.json").read_text(encoding="utf-8"))
    assert config["template"] == {"name": name, "version": 1}
    assert cli.main(["--root", str(fresh), "check"]) == 0, capsys.readouterr().out


def test_the_stage_defaults_to_prototype_and_is_checked(fresh, capsys):
    steps = init.plan(fresh, "Ada", template_spec="cli")
    text = next(s.text for s in steps if s.path.name == "projects.yaml")
    assert yaml.safe_load(text)["brain"]["standards"]["stage"] == "prototype"
    with pytest.raises(init.InitError, match="--stage 'beta': one of prototype, mvp, v1, scale"):
        init.plan(fresh, "Ada", template_spec="cli", stage="beta")
    assert init.STAGES == standards.STAGES


def test_the_generic_template_writes_what_it_wrote(fresh):
    """generic is the base of the others, and its own output does not move: no file appended, no stage."""
    tpl = init.load_template("generic")
    assert tpl.extends == () and tpl.appends == {}
    out = init.files_for("Ada", "person", None, "lite", "brain", tpl)
    for rel, source in tpl.files.items():
        raw = init.template(source) if source else ""
        assert "{stage}" not in raw
        assert out[rel] == raw.replace("{owner}", "Ada").replace("{name}", "brain").replace(
            "{owner_q}", '"Ada"').replace("{title_q}", '"Ada\'s brain: rules, decisions, backlog and journal"'), rel


def test_the_harness_runs_green_in_a_new_brain(fresh, capsys):
    """The test harness a code product starts with passes as written: the CI is green from the first commit."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", "cli", "--apply"]) == 0
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=fresh,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "3 passed" in done.stdout


def _own(tmp_path, manifest: str, files: dict[str, str]):
    tpl = tmp_path / "mine"
    tpl.mkdir()
    (tpl / "template.yaml").write_text(manifest, encoding="utf-8")
    for name, text in files.items():
        (tpl / name).write_text(text, encoding="utf-8")
    return tpl


def test_a_template_of_ones_own_extends_a_profile(fresh, tmp_path, capsys):
    tpl = _own(tmp_path, "name: mine\nversion: 1\nextends: cli\nfiles: {CLAUDE.md: claude.md, docs/runbook.md: rb.md}\n"
                         "append: {README.md: more.md}\n",
               {"claude.md": "# {owner}'s own rules\n", "rb.md": "# Runbook\n", "more.md": "\n## More\n"})
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl), "--apply"]) == 0
    assert (fresh / "CLAUDE.md").read_text(encoding="utf-8") == "# Ada's own rules\n"   # its own file wins
    assert (fresh / "docs" / "runbook.md").is_file() and (fresh / "tests" / "conftest.py").is_file()
    assert (fresh / "README.md").read_text(encoding="utf-8").endswith("\n## More\n")
    registry = yaml.safe_load((fresh / "projects.yaml").read_text(encoding="utf-8"))
    assert registry["brain"]["standards"]["profiles"] == ["cli"]


@pytest.mark.parametrize("manifest, says", [
    ("name: mine\nversion: 1\nextends: astrology\n", "extends 'astrology': one of the engine's templates"),
    ("name: mine\nversion: 1\nextends: cli\nappend: {nowhere.md: more.md}\n", "append nowhere.md: not a file"),
    ("name: mine\nversion: 1\nextends: cli\nappend: {projects.yaml: more.md}\n", "projects.yaml with what it appends "
                                                                                 "is not YAML"),
    ("name: mine\nversion: 1\n", "files maps the brain's path"),
    ("name: mine\nversion: 1\nextends: cli\nclasses: [memory]\n", "classes: {store: {class, paths}}"),
    ("name: mine\nversion: 1\nextends: cli\nfiles: {projects.yaml: two.yaml}\n",
     "what it appends goes under the brain's own entry (brain), which must be the registry's last"),
])
def test_a_bad_extension_plans_nothing(fresh, tmp_path, capsys, manifest, says):
    tpl = _own(tmp_path, manifest, {"more.md": "  - [unclosed\n",
                                    "two.yaml": "{name}:\n  root: .\nlib:\n  root: ../lib\n"})
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl)]) == 2
    assert says in capsys.readouterr().out and list(fresh.iterdir()) == []


def test_a_profile_over_an_existing_brain_says_what_it_does_not_append(fresh, capsys):
    """brain init never writes over a file: on a brain that exists, the plan names the fragments a kept file misses,
    so the owner adds the boundary's rule and the standards selection by hand."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    capsys.readouterr()
    assert cli.main(["init", str(fresh), "--template", "cli"]) == 0
    out = capsys.readouterr().out
    assert "keep     boundary.yaml (exists; the template appends boundary-github.yaml to it: add that by hand" in out
    assert "keep     projects.yaml (exists; the template appends standards.yaml to it" in out
    assert "keep     CLAUDE.md (exists)" in out


# What each engine template writes (its files rendered at --stage mvp, its graphs and their schemas, its classes),
# hashed. spec-brain-typology-packs E1 bis moved the issue template from _project to _software and made research take
# parts of _software instead of extending it, every output unchanged. A deliberate change of a template's output bumps
# its version and updates its digest here, in the same PR.
DIGESTS = {"cli": "4a317f0a9ebddd02", "data-pipeline": "56ef5812c2b459cb", "generic": "769d3e1b34d00278",
           "local-client": "1fca86a520d976cb", "research": "a25779d06d892300", "service": "b403064d7769f8dd"}


def _digest(name: str) -> str:
    tpl = init.load_template(name)
    out = init.files_for("Ada", "person", None, "lite", "brain", tpl, stage="mvp")
    out.pop("config.json")
    blob = json.dumps({"files": out, "graphs": tpl.graphs, "classes": tpl.classes,
                       "schemas": [init.graph_schema(g, "Ada", tpl) for g in tpl.graphs]}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def test_every_template_writes_what_it_wrote_before_the_typology_doors():
    assert {name: _digest(name) for name in init.known_templates()} == DIGESTS


def test_the_project_base_writes_nothing_of_a_code_host():
    """_project, the generic project base, writes no .github/ file and no boundary rule for it: a project that is not
    code, or not on GitHub, extends it alone; the issue template and the .github/ rule are _software's."""
    base = init.load_template("_project", ("test",))
    assert not [rel for rel in base.files if rel.startswith(".github/")] and base.appends == {}
    assert "docs/templates/adr.md" in base.files
    software = init.load_template("_software", ("test",))
    assert ".github/ISSUE_TEMPLATE/task.md" in software.files and "boundary.yaml" in software.appends


def test_research_takes_parts_of_the_software_base_instead_of_extending_it():
    """research extends _project and names what it takes from _software: a path _software adds later reaches it only
    when it says so; it never takes _software's graphs (its own layers, no features layer)."""
    tpl = init.load_template("research")
    assert tpl.extends == ("_project", "generic")
    assert set(tpl.takes["_software"]) == set(SOFTWARE) - {"docs/templates/adr.md"} | {"boundary.yaml"}
    assert "features" not in tpl.graphs[0]["layers"]
    assert [extra for _, extra in tpl.appends["boundary.yaml"]] == ["boundary-github.yaml"]


@pytest.mark.parametrize("takes, says", [
    ("{_software: [docs/nowhere.md]}", "takes _software: 'docs/nowhere.md': not a path _software itself writes"),
    ("{astrology: [x.md]}", "takes 'astrology': one of the engine's templates"),
    ("{_project: [docs/templates/adr.md]}", "takes '_project': the template itself or one it extends"),
    ("[_software]", "takes maps one of the engine's templates to the brain's paths"),
    ("{_software: []}", "takes maps one of the engine's templates to the brain's paths"),
    ("{_software: [boundary.yaml, boundary.yaml]}", "the brain's paths taken from it, each once"),
    ("{_software: [boundary.yaml]}\nextends: research", "takes _software: 'boundary.yaml': its base takes it already"),
])
def test_a_bad_take_plans_nothing(fresh, tmp_path, capsys, takes, says):
    manifest = f"name: mine\nversion: 1\ntakes: {takes}\n"
    tpl = _own(tmp_path, manifest if "extends" in manifest else manifest + "extends: _project\n", {})
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl)]) == 2
    assert says in capsys.readouterr().out and list(fresh.iterdir()) == []


def test_a_taken_append_needs_the_file_it_goes_to(fresh, tmp_path, capsys):
    """A template of no base that writes no boundary.yaml cannot take _software's boundary fragment: the error names
    the take, not an append the owner never wrote."""
    files = {r: "x.md" for r in init.REQUIRED}
    tpl = _own(tmp_path, "name: mine\nversion: 1\ntakes: {_software: [boundary.yaml]}\nfiles: "
               + json.dumps(files) + "\n", {"x.md": "x\n"})
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl)]) == 2
    assert ("takes _software: boundary.yaml: what _software appends there needs a file the template does not write"
            in capsys.readouterr().out)


def test_a_template_of_ones_own_takes_the_ci_alone(fresh, tmp_path, capsys):
    tpl = _own(tmp_path, "name: mine\nversion: 1\nextends: _project\ntakes: {_software: [.github/workflows/ci.yml]}\n",
               {})
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl), "--apply"]) == 0
    assert (fresh / ".github" / "workflows" / "ci.yml").is_file()
    assert not (fresh / ".github" / "ISSUE_TEMPLATE").exists() and not (fresh / "tests").exists()


def test_an_unknown_typology_or_stage_id_in_a_template_s_selection_is_tolerated(fresh, tmp_path, capsys):
    """spec-brain-typology-packs E1: the profiles' names and the stages a template selects follow one typology
    catalog still to come (wi-brain-typology-catalog); an id this engine does not know, written by a template of a
    later catalog, is a note in read mode (an error only in strict mode, CI), never a refusal to start the brain."""
    tpl = _own(tmp_path, "name: mine\nversion: 1\nextends: _project\nappend: {projects.yaml: standards.yaml}\n",
               {"standards.yaml": "  standards:\n    profiles: [film]\n    stage: pre-production\n"})
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl), "--apply"]) == 0
    selection = yaml.safe_load((fresh / "projects.yaml").read_text(encoding="utf-8"))["brain"]["standards"]
    notes: list[str] = []
    assert standards.selection_errors("brain", selection, strict=False, notes=notes) == []
    assert any("profile 'film'" in n for n in notes) and any("stage 'pre-production'" in n for n in notes)
    assert standards.selection_errors("brain", selection, strict=True)


def test_the_templates_name_no_one_and_code_takes_no_variable():
    """Every template's files carry no name, only the variables brain init renders; code and CI files none at all
    (an f-string's {name} would be rendered away, as the harness's once was)."""
    allowed = {"owner", "owner_q", "name", "title_q", "stage"}
    for spec in init.known_templates() + ["_project", "_software"]:
        tpl = init.load_template(spec, ("test",))
        for rel, source in tpl.files.items():
            text = tpl.text(rel)
            found = set(re.findall(r"\{(owner|owner_q|name|title_q|stage)\}", text))
            assert "Ada" not in text and found <= allowed, (spec, rel)
            if rel.endswith((".py", ".yml")) or source.endswith(".tmpl"):
                assert not found, (spec, rel, found)


def test_the_engine_s_own_tests_never_collect_a_template():
    """A template's Python files end in .tmpl: pytest packages/brain (the engine's CI) must not load them as tests or
    as a conftest."""
    folder = init.TEMPLATES
    assert not [p.name for d in folder.iterdir() if d.is_dir() for p in d.iterdir() if p.name.endswith(".py")]
