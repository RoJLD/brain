"""The new-project wizard, second slice (brain.project_new, wi-brain-project-wizard-tools; spec-brain-client-standards
§8, questions 3 and 4): the languages and tools (each check's slot and the report its tool writes), the data (the
class floor, a residency clause, personal data), written under the brain's own registry entry by --apply, the
standards rows they select shown in the plan, and a re-run that shows what they change. Fictitious names only."""

import argparse
import json

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


def its_own_checks_pass(d, capsys):
    """The new brain passes its own brain classes --check and brain check."""
    capsys.readouterr()
    assert cli.main(["--root", str(d), "classes", "--check"]) == 0, capsys.readouterr().out
    assert cli.main(["--root", str(d), "check"]) == 0, capsys.readouterr().out


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


def test_the_printed_commands_run_once_as_printed():
    """A command the plan prints runs as is, once: vitest's run (not its watch), c8 wrapping the command it measures,
    eslint and prettier given the tree; each writes the report it is declared with (c8 its coverage/ default)."""
    cmd = {(t.lang, t.slot, t.name): t.command for t in langs.TOOLS.values()}
    assert cmd["ts", "test", "vitest"].startswith("vitest run ")
    c8 = cmd["ts", "coverage", "c8"].split()
    assert c8[0] == "c8" and [w for w in c8[1:] if not w.startswith("-")]   # the command it measures
    assert cmd["ts", "lint", "eslint"].startswith("eslint . ") and cmd["ts", "format", "prettier"].endswith(" .")
    for t in langs.TOOLS.values():
        if t.report and t.name != "c8":
            assert t.report in t.command or t.report.rsplit("/", 1)[0] in t.command, t


def test_the_python_defaults_are_the_reports_the_code_templates_ci_writes():
    """pytest's and pytest-cov's reports are those templates/_software/ci.yml writes (brain audit reads them)."""
    ci = init.files_for("Ada", "person", None, "lite", "brain", init.load_template("cli"))[project_new.CI]
    for slot in ("test", "coverage"):
        t = langs.tool("py", slot, langs.DEFAULT_TOOLS["py"][slot])
        assert t.report in ci, t


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
    # the template's CI writes the tests' and the coverage's reports, not the lint's nor mypy's: the plan says so
    assert "not written by the template's CI (.github/workflows/ci.yml): reports/ruff.sarif, reports/mypy.xml" in out
    assert not d.exists()
    assert cli.main([*words, "--apply"]) == 0
    capsys.readouterr()
    e = entry_of(d)
    repo = next(r for r in e["repos"] if r["path"] == ".")
    assert repo["lang"] == "py" and list(repo["tools"]) == ["lint", "typecheck", "test", "coverage"]
    assert repo["tools"]["coverage"] == {"report": "reports/coverage.xml", "format": "cobertura", "tool": "pytest-cov"}
    ci = (d / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert all(repo["tools"][s]["report"] in ci for s in ("test", "coverage"))
    assert e["classes"] == {"floor": "private"} and e["lifecycle"]["typologies"] == ["cli"]
    assert e["standards"] == {"profiles": ["cli"], "stage": "mvp", "include": list(project_new.PERSONAL_DATA)}
    assert "# brain project new: its language" in (d / "projects.yaml").read_text(encoding="utf-8")
    its_own_checks_pass(d, capsys)
    monkeypatch.setenv("BRAIN_PROJECTS", str(d / "projects.yaml"))
    assert projects.check(d) == []   # the registry's own checks take what the wizard wrote
    p = projects.load(d)["brain"]
    chosen = dict((r.id, why) for r, why in standards.applicable(standards.rows_of(standards.engine_catalogs()),
                                                                standards.selection(p.standards)))
    assert chosen["sw-erasure"] == "included"   # required from mvp although its own stage is v1


def test_a_template_without_standards_gets_its_include_alone(tmp_path, capsys, monkeypatch):
    """The generic template writes no standards: the include comes as a standards: of its own, and the new brain
    passes its own checks (the floor public: its stores are all at or above it)."""
    d = tmp_path / "lab"
    assert "standards:" not in init.files_for("Ada", "person", None, "lite", "brain",
                                              init.load_template("generic"))["projects.yaml"]
    assert cli.main(["project", "new", str(d), "--kind", "research", "--template", "generic", "--personal-data",
                     "--floor", "public", "--owner", "Ada", "--apply"]) == 0
    e = entry_of(d)
    assert e["standards"] == {"include": list(project_new.PERSONAL_DATA)} and e["classes"] == {"floor": "public"}
    its_own_checks_pass(d, capsys)
    monkeypatch.setenv("BRAIN_PROJECTS", str(d / "projects.yaml"))
    assert projects.check(d) == []


@pytest.mark.parametrize("words, asked", [(["--floor", "confidential"], "--floor confidential"),
                                          (["--floor", "sealed"], "--floor sealed"),
                                          (["--residency"], "--residency (the floor resident)")])
def test_a_floor_its_own_stores_are_under_is_refused_at_plan_time(tmp_path, capsys, words, asked):
    """brain check refuses a store under its project's floor, and a new brain's stores (repo private, memory and the
    decisions confidential, the machine's sealed) belong to its own entry: a stricter floor is refused by the plan,
    naming the stores and the floors they hold, and nothing is written."""
    d = tmp_path / "lab"
    for apply in ([], ["--apply"]):
        assert cli.main(["project", "new", str(d), "--kind", "cli", *words, "--owner", "Ada", *apply]) == 2
        out = capsys.readouterr().out
        assert f"{asked}: the brain's own stores " in out and "repo (private)" in out
        assert "which brain check refuses" in out
        assert "they hold the floor public or private" in out and not d.exists()


def test_the_refused_floor_is_the_one_brain_check_refuses(tmp_path, capsys):
    """The refusal is the classes check's own: the same brain written with the floor confidential forced (by brain
    init, past the wizard) fails brain classes --check, and with private, the floor the wizard takes, passes. Once
    its stores are declared at the floor, a re-run takes it."""
    for floor, code in (("confidential", 1), ("private", 0)):
        d = tmp_path / floor
        a = answers()
        a.floor = floor
        ns = project_new._init_args(argparse.Namespace(dir=str(d), owner="Ada", template=None, name="brain",
                                                       apply=True), a)
        assert init.main(ns) == 0
        capsys.readouterr()
        assert cli.main(["--root", str(d), "classes", "--check"]) == code
        assert ("under the floor confidential" in capsys.readouterr().out) == (code == 1)
    d = tmp_path / "private"
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    for store in cfg["classes"]["stores"].values():
        store["class"] = "confidential" if store["class"] in ("public", "private") else store["class"]
    (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--floor", "confidential"]) == 0
    assert "classes.floor: private -> confidential" in capsys.readouterr().out


def test_a_language_its_tools_leave_uncovered_is_a_gap_in_the_plan(tmp_path, capsys):
    """sw-utf8 is a lint row written for Python: a TypeScript repo covers it only through a lint tool of its own.
    The code templates' CI runs Python: the plan says none of a TypeScript project's reports is written yet."""
    d = tmp_path / "web"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "ts", "--owner", "Ada"]) == 0
    out = capsys.readouterr().out
    assert "not covered on ts" not in out
    assert "the template's CI (.github/workflows/ci.yml) runs py only, not ts: none of these reports is written" in out
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "ts", "--tool", "lint=none",
                     "--owner", "Ada"]) == 0
    out = capsys.readouterr().out
    assert "not covered on ts: sw-utf8: its check covers py, not brain (ts)" in out
    assert "no tool: lint, typecheck" in out
    assert cli.main(["project", "new", str(d), "--kind", "research", "--template", "generic", "--lang", "py",
                     "--owner", "Ada"]) == 0
    assert "the template writes no CI (.github/workflows/ci.yml)" in capsys.readouterr().out


def test_a_re_run_shows_what_the_answers_change(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py", "--owner", "Ada", "--apply"]) == 0
    before = (d / "projects.yaml").read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py"]) == 0
    assert "the answers change nothing" in capsys.readouterr().out
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py", "--tool", "test=none", "--tool",
                     "typecheck=mypy", "--floor", "private", "--personal-data"]) == 0
    out = capsys.readouterr().out
    assert "repos[path: .].tools.typecheck: (none) -> mypy (reports/mypy.xml, junit)" in out
    assert "repos[path: .].tools.test: pytest (reports/junit.xml, junit) -> (none)" in out
    assert "classes.floor: (none) -> private" in out
    assert "standards.include: (none) -> ['sw-privacy-by-design'," in out
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "ts", "--apply"]) == 2
    assert "repos[path: .].lang: py -> ts" in capsys.readouterr().out
    assert (d / "projects.yaml").read_text(encoding="utf-8") == before


def test_a_re_run_compares_each_slots_report_and_format(tmp_path, capsys):
    """The same tool with another report is a change; a slot declared by hand without a tool shows its report; a
    tool with an exit code only is named as such, never as no tool."""
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py", "--owner", "Ada", "--apply"]) == 0
    reg = d / "projects.yaml"
    text = reg.read_text(encoding="utf-8").replace("reports/coverage.xml, format: cobertura",
                                                   "reports/coverage.json, format: coverage-json")
    head = "      tools:   # brain project new: each check's tool and the report it writes (brain audit reads them)\n"
    assert head in text
    text = text.replace(head, head + "        format: {report: reports/fmt.sarif, format: sarif}\n")
    reg.write_text(text, encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py"]) == 0
    out = capsys.readouterr().out
    assert ("repos[path: .].tools.coverage: pytest-cov (reports/coverage.json, coverage-json) -> pytest-cov "
            "(reports/coverage.xml, cobertura)") in out
    assert "repos[path: .].tools.format: reports/fmt.sarif, sarif -> ruff, an exit code only (not declared)" in out
    assert "tools.lint" not in out and "tools.test" not in out


def test_the_apply_line_repeats_the_answers_as_they_run(tmp_path, capsys):
    """A --tool given with spaces comes back as SLOT=TOOL: the printed line runs as is."""
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--lang", "py", "--tool", " typecheck = mypy ",
                     "--owner", "Ada"]) == 0
    assert "--lang py --tool typecheck=mypy --apply writes it)" in capsys.readouterr().out


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
    inc = project_new.registry_edit(project_new.answer_data(answers(), None, personal=True), "brain")
    for bad, needle in (("brain:\n  root: .\n  standards: {profiles: [cli],\n    stage: mvp}\n", "spans lines"),
                        ("brain:\n  root: .\n  standards:\n    include: sw-x\n", "not a list of ids"),
                        ("brain:\n  root: .\n  standards:\n    profiles: [cli]\n  standards:\n    stage: mvp\n",
                         "twice")):
        with pytest.raises(init.InitError, match=needle):
            inc(bad)


@pytest.mark.parametrize("text", [
    "brain:\n  root: .\n  standards: {profiles: [cli], stage: mvp}   # its own\n",
    "brain:\n  root: .\n  standards:\n    profiles: [cli]\n    include: [sw-x, sw-erasure]   # its own\n",
    "brain:\n  root: .\n  standards:\n    include:\n      - sw-x   # its own\n      # a comment\n      - sw-erasure\n"
    "    stage: mvp\n",
    "brain:\n  root: .\n  standards:\n    include:\n    - sw-x\n    stage: mvp\n",
    "brain:\r\n  root: .\r\n  standards:\r\n    include:\r\n      - sw-x\r\n",
])
def test_an_include_the_template_writes_takes_the_rows(text):
    """A template whose selection includes rows already: the privacy rows merge into its include (flow or block, a
    one-line standards: {..} too), its own rows and comments kept, each row once."""
    inc = project_new.answer_data(answers(), None, personal=True)
    out = project_new.registry_edit(inc, "brain")(text)
    got = yaml.safe_load(out)["brain"]["standards"]
    held = [i for i in ("sw-x", "sw-erasure") if i in text]
    assert got["include"] == held + [i for i in project_new.PERSONAL_DATA if i not in held]
    assert ("# its own" in out) == ("# its own" in text) and ("stage" in got) == ("stage" in text)
    assert out.count("standards:") == 1


def test_a_template_registry_that_cannot_take_them_is_refused_at_apply_only(tmp_path, capsys):
    """The plan says what --apply would refuse and shows the template's registry without the answers' lines;
    --apply refuses it and writes nothing."""
    tpl = tmp_path / "odd"
    tpl.mkdir()
    (tpl / "template.yaml").write_text("name: odd\nversion: 1\nextends: generic\nappend: {projects.yaml: std.yaml}\n",
                                       encoding="utf-8")
    (tpl / "std.yaml").write_text("  standards: {profiles: [cli],\n    stage: mvp}\n", encoding="utf-8")
    d = tmp_path / "lab"
    words = ["project", "new", str(d), "--kind", "cli", "--template", str(tpl), "--personal-data", "--owner", "Ada"]
    assert cli.main(words) == 0
    out = capsys.readouterr().out
    assert "  --apply refuses: projects.yaml: its 'standards: {profiles: [cli],' spans lines" in out
    assert "--apply refuses it, as said above" in out
    assert cli.main([*words, "--apply"]) == 2
    assert "spans lines" in capsys.readouterr().out and not d.exists()


def test_the_include_goes_under_the_brains_own_entry_only():
    inc = project_new.answer_data(answers(), None, personal=True)
    text = "other:\n  root: x\n  standards:\n    profiles: [cli]\nbrain:\n  root: .\n"
    data = yaml.safe_load(project_new.registry_edit(inc, "brain")(text))
    assert "include" not in data["other"]["standards"]
    assert data["brain"]["standards"]["include"] == list(project_new.PERSONAL_DATA)
