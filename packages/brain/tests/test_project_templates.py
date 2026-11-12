"""brain init by profile (wi-brain-project-templates): the templates cli, local-client, service, data-pipeline and
research extend the generic brain (through the bases _project and _software) with the profile's standards selection at
its stage, the CI jobs, the test harness, the format registry's skeleton, the issue and ADR templates and the graph's
layers; the generic template's files are unchanged."""

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
])
def test_a_bad_extension_plans_nothing(fresh, tmp_path, capsys, manifest, says):
    tpl = _own(tmp_path, manifest, {"more.md": "  - [unclosed\n"})
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl)]) == 2
    assert says in capsys.readouterr().out and list(fresh.iterdir()) == []
