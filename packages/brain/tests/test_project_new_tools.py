"""The new-project wizard, second slice (brain.project_new, wi-brain-project-wizard-tools; spec-brain-client-standards
§8, questions 3 and 4): the languages and tools (each check's slot and the report its tool writes), the data (the
class floor, a residency clause, personal data), written under the brain's own registry entry by --apply, the
standards rows they select shown in the plan, and a re-run that shows what they change. Fictitious names only."""

import pytest
import yaml
from brain import __version__, cli, init, langs, project_new, projects, skew, standards, typologies


@pytest.fixture(autouse=True)
def fresh(monkeypatch, brain_home):
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.setattr(init, "machine_terms", lambda: {"users": ["ada-l"], "hosts": ["host-a"]})
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])


def answers(kind="cli", stage="mvp"):
    return project_new.resolve(typologies.engine(), [kind], stage)


def entry_of(d):
    return yaml.safe_load((d / "projects.yaml").read_text(encoding="utf-8"))["brain"]


def test_the_tool_table_writes_only_what_the_engine_reads():
    """Every tool with a report passes the registry's own check of tools:, the defaults name known tools, and the
    privacy rows are rows of the engine's catalogs (a renamed row would silently drop out of --personal-data)."""
    for t in langs.TOOLS.values():
        assert t.lang in langs.LANGS and t.slot in langs.SLOTS and t.command
        if t.report:
            assert langs.tools_errors("x", {t.slot: t.entry()}, strict=True) == []
            assert t.report.startswith(("reports/", "coverage/"))
        else:
            assert not t.format
    for lang, slots in langs.DEFAULT_TOOLS.items():
        assert all(langs.tool(lang, s, n) for s, n in slots.items())
    held = {r.id for r in standards.rows_of(standards.engine_catalogs())}
    assert set(project_new.PERSONAL_DATA) <= held


def test_a_language_takes_its_usual_tools_unless_named():
    a = project_new.answer_tools(answers(), "py", [])
    assert {s: t.name for s, t in a.tools.items()} == {"lint": "ruff", "test": "pytest", "coverage": "pytest-cov"}
    assert [(t.slot, t.name) for t in a.unreported] == [("format", "ruff")]   # an exit code only: named, not declared
    a = project_new.answer_tools(answers(), "py", ["typecheck=mypy", "coverage=none"])
    assert list(a.tools) == ["lint", "typecheck", "test"]
    assert a.repo_tools()["typecheck"] == {"report": "reports/mypy.xml", "format": "junit", "tool": "mypy"}
    a = project_new.answer_tools(answers(), "ts", ["test=jest"])
    assert {s: t.name for s, t in a.tools.items()} == {"lint": "eslint", "test": "jest", "coverage": "c8"}
    assert project_new.answer_tools(answers(), None, None).lang == ""   # nothing asked: nothing written


@pytest.mark.parametrize("lang, specs, needle", [
    (None, ["lint=ruff"], "with --lang py|ts"),
    ("go", [], "--lang go: one of py, ts"),
    ("py", ["lint"], "SLOT=TOOL"),
    ("py", ["=ruff"], "SLOT=TOOL"),
    ("py", ["style=ruff"], "the slot is one of"),
    ("py", ["lint=eslint"], "not a lint tool of py the wizard knows (ruff"),
    ("py", ["lint=ruff", "lint=none"], "named twice"),
])
def test_a_tool_it_cannot_take_is_named(lang, specs, needle):
    with pytest.raises(project_new.WizardError, match=needle.replace("(", r"\(").replace("|", r"\|")):
        project_new.answer_tools(answers(), lang, specs)


def test_the_data_answers():
    assert project_new.answer_data(answers(), "confidential").floor == "confidential"
    assert project_new.answer_data(answers(), None, residency=True).floor == "resident"
    assert project_new.answer_data(answers(), "resident", residency=True).floor == "resident"
    a = project_new.answer_data(answers(), None, personal=True)
    assert a.floor == "" and a.include == list(project_new.PERSONAL_DATA)
    for floor, residency, needle in (("private", True, "--residency is the floor resident"),
                                     ("top", False, "--floor top: one of"), ("secret", False, "never in the brain")):
        with pytest.raises(project_new.WizardError, match=needle):
            project_new.answer_data(answers(), floor, residency)


def test_apply_writes_the_answers_under_the_brains_own_entry(tmp_path, capsys, monkeypatch):
    d = tmp_path / "lab"
    words = ["project", "new", str(d), "--kind", "cli", "--stage", "mvp", "--lang", "py", "--tool", "typecheck=mypy",
             "--floor", "private", "--personal-data", "--owner", "Ada"]
    assert cli.main(words) == 0
    out = capsys.readouterr().out
    assert "lint: ruff -> reports/ruff.sarif (sarif): ruff check --output-format sarif -o reports/ruff.sarif" in out
    assert "format: ruff, an exit code only (ruff format --check): named, not declared" in out
    assert "data: class floor private" in out and "personal data: its standards include sw-privacy-by-design" in out
    assert "run by its tools: " in out and "(lint: ruff)" in out
    assert "--lang py --tool typecheck=mypy --floor private --personal-data --apply writes it)" in out
    assert not d.exists()
    assert cli.main([*words, "--apply"]) == 0
    capsys.readouterr()
    e = entry_of(d)
    repo = next(r for r in e["repos"] if r["path"] == ".")
    assert repo["lang"] == "py" and list(repo["tools"]) == ["lint", "typecheck", "test", "coverage"]
    assert repo["tools"]["coverage"] == {"report": "reports/coverage.json", "format": "coverage-json",
                                         "tool": "pytest-cov"}
    assert e["classes"] == {"floor": "private"} and e["lifecycle"]["typologies"] == ["cli"]
    assert e["standards"] == {"profiles": ["cli"], "stage": "mvp", "include": list(project_new.PERSONAL_DATA)}
    assert "# brain project new: its language" in (d / "projects.yaml").read_text(encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(d / "projects.yaml"))
    assert projects.check(d) == []   # the registry's own checks take what the wizard wrote
    p = projects.load(d)["brain"]
    chosen = dict((r.id, why) for r, why in standards.applicable(standards.rows_of(standards.engine_catalogs()),
                                                                standards.selection(p.standards)))
    assert chosen["sw-erasure"] == "included"   # required from mvp although its own stage is v1


def test_a_template_without_standards_gets_its_include_alone(tmp_path, capsys, monkeypatch):
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "research", "--personal-data", "--residency", "--owner",
                     "Ada", "--apply"]) == 0
    e = entry_of(d)
    assert e["standards"]["include"] == list(project_new.PERSONAL_DATA) and e["classes"] == {"floor": "resident"}
    monkeypatch.setenv("BRAIN_PROJECTS", str(d / "projects.yaml"))
    assert projects.check(d) == []


def test_a_language_its_tools_leave_uncovered_is_a_gap_in_the_plan(tmp_path, capsys):
    """sw-utf8 is a lint row written for Python: a TypeScript repo covers it only through a lint tool of its own."""
    d = tmp_path / "web"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "ts", "--owner", "Ada"]) == 0
    assert "not covered on ts" not in capsys.readouterr().out
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "ts", "--tool", "lint=none",
                     "--owner", "Ada"]) == 0
    out = capsys.readouterr().out
    assert "not covered on ts: sw-utf8: its check covers py, not brain (ts)" in out
    assert "no tool: lint, typecheck" in out


def test_a_re_run_shows_what_the_answers_change(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py", "--owner", "Ada", "--apply"]) == 0
    before = (d / "projects.yaml").read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py"]) == 0
    assert "the answers change nothing" in capsys.readouterr().out
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py", "--tool", "test=none", "--tool",
                     "typecheck=mypy", "--floor", "confidential", "--personal-data"]) == 0
    out = capsys.readouterr().out
    assert "repos[path: .].tools.typecheck: (none) -> mypy" in out and "repos[path: .].tools.test: pytest -> (none)" \
        in out
    assert "classes.floor: (none) -> confidential" in out
    assert "standards.include: (none) -> ['sw-privacy-by-design'," in out
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "ts", "--apply"]) == 2
    assert "repos[path: .].lang: py -> ts" in capsys.readouterr().out
    assert (d / "projects.yaml").read_text(encoding="utf-8") == before


def test_a_refused_answer_writes_nothing(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--tool", "lint=ruff", "--apply"]) == 2
    assert "with --lang py|ts" in capsys.readouterr().out and not d.exists()
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--floor", "secret", "--apply"]) == 2
    assert not d.exists()


def test_lines_that_cannot_land_are_refused():
    a = project_new.answer_tools(answers(), "py", [])
    edit = project_new.registry_edit(a, "brain")
    good = "brain:\n  root: .\n  repos:\n    - path: .   # its own\n      name: brain\n"
    assert yaml.safe_load(edit(good))["brain"]["repos"][0]["tools"]["lint"]["tool"] == "ruff"
    for bad in ("brain:\n  root: .\n  repos: [{path: .}]\n",            # a flow-style repo: no '- path: .' line
                "brain:\n  root: .\nother:\n  repos:\n    - path: .\n"):  # under another entry
        with pytest.raises(init.InitError, match="by hand|brain.s own entry|twice"):
            edit(bad)
    inc = project_new.answer_data(answers(), None, personal=True)
    with pytest.raises(init.InitError, match="twice"):   # a flow-style standards: cannot take a line
        project_new.registry_edit(inc, "brain")("brain:\n  root: .\n  standards: {profiles: [cli]}\n")
