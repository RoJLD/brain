"""The new-project wizard, first slice (brain.project_new, wi-brain-project-wizard; spec-brain-client-standards §8,
STD-5; spec-brain-typology-packs: its kinds are the typology catalog's): what the project produces and its stage, a
plan, then --apply through brain init, the answers recorded as the registry entry's lifecycle; a later answer re-runs
the plan and writes nothing there. Fictitious names only."""

import pytest
import yaml
from brain import __version__, cli, init, project_new, projects, skew, typologies, wizards


@pytest.fixture(autouse=True)
def fresh(monkeypatch, brain_home):
    """As brain init's tests: the tests' own config and registry overrides off, a dev engine standing for its
    release."""
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.setattr(init, "machine_terms", lambda: {"users": ["ada-l"], "hosts": ["host-a"]})
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])


@pytest.fixture
def cat():
    return typologies.engine()


def test_the_kinds_offered_are_code_products_and_research_with_a_template(cat):
    assert project_new.offered(cat) == ["cli", "local-client", "service", "data-pipeline", "research", "trading"]
    assert project_new.templates_of(cat)["trading"] == "research"   # a sub-profile takes its entry's template
    assert "strategy" not in project_new.templates_of(cat)


def test_the_answers_are_resolved_against_the_catalog(cat):
    a = project_new.resolve(cat, ["cli", "research"], "mvp")
    assert a.template == "cli" and a.lifecycle_stage == "build" and a.entries == ["software", "research"]
    assert {"code", "research", "data"} <= set(a.layers) and a.missing == ["data", "fleet", "research", "rules"]
    assert a.lifecycle() == {"typologies": ["cli", "research"], "stage": "build"}
    assert project_new.resolve(cat, ["trading"], "prototype").template == "research"
    assert project_new.resolve(cat, ["library"], "v1", template="cli").template == "cli"


@pytest.mark.parametrize("kinds, stage, needle", [
    ([], "mvp", "--kind K"),
    (["video-x"], "mvp", "not in the typology catalog"),
    (["strategy"], "mvp", "not offered yet (STD-5"),
    (["cli"], "build", "--stage build: one of"),
    (["library"], "mvp", "no profile template of its own yet"),
])
def test_an_answer_it_cannot_take_is_named(cat, kinds, stage, needle):
    with pytest.raises(project_new.WizardError, match=needle.replace("(", r"\(").replace("[", r"\[")):
        project_new.resolve(cat, kinds, stage)


def test_a_plan_writes_nothing_and_apply_records_the_answers(tmp_path, capsys, monkeypatch):
    d = tmp_path / "lab"
    words = ["project", "new", str(d), "--kind", "cli", "--kind", "research", "--stage", "mvp", "--owner", "Ada"]
    assert cli.main(words) == 0
    out = capsys.readouterr().out
    assert out.startswith("brain project new: what it produces: cli (Command-line tool, software [J1]), research")
    assert "stage: mvp (the lifecycle's build); template: cli" in out and "template cli v1" in out
    assert not d.exists()
    assert cli.main([*words, "--apply"]) == 0
    capsys.readouterr()
    entry = yaml.safe_load((d / "projects.yaml").read_text(encoding="utf-8"))["brain"]
    assert entry["lifecycle"] == {"typologies": ["cli", "research"], "stage": "build"}
    assert entry["standards"] == {"profiles": ["cli"], "stage": "mvp"}
    monkeypatch.setenv("BRAIN_PROJECTS", str(d / "projects.yaml"))
    assert projects.check(d) == []
    assert projects.load(d)["brain"].lifecycle["typologies"] == ["cli", "research"]


def test_a_later_answer_re_runs_the_plan_and_writes_nothing_there(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--owner", "Ada", "--apply"]) == 0
    before = (d / "projects.yaml").read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--owner", "Ada"]) == 0
    assert "the answers change nothing" in capsys.readouterr().out
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--kind", "research", "--stage", "v1"]) == 0
    out = capsys.readouterr().out
    assert "lifecycle.typologies: ['cli'] -> ['cli', 'research']" in out
    assert "lifecycle.stage: explore -> launch" in out and "standards.stage: prototype -> v1" in out
    assert "by a branch and a PR of that brain, never here" in out
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--stage", "v1", "--apply"]) == 2
    assert (d / "projects.yaml").read_text(encoding="utf-8") == before


def test_a_refused_answer_exits_2_and_writes_nothing(tmp_path, capsys):
    assert cli.main(["project", "new", str(tmp_path / "x"), "--kind", "creation", "--apply"]) == 2
    assert "not offered yet" in capsys.readouterr().out and not (tmp_path / "x").exists()


def test_the_cockpit_wizard_offers_the_kinds_and_plans_before_it_applies():
    w = wizards.by_id()["project-new"]
    assert w.choices == tuple(project_new.offered(typologies.engine())) and w.ask
    assert w.words("plan", "cli", "D:/lab") == ["brain", "project", "new", "D:/lab", "--kind", "cli"]
    assert w.words("apply", "cli", "D:/lab")[-1] == "--apply"


def test_a_lifecycle_line_that_lands_elsewhere_is_refused():
    from types import SimpleNamespace
    tpl = SimpleNamespace(name="mine")
    lc = {"typologies": ["cli"], "stage": "build"}
    good = "brain:\n  root: .\n" + init.lifecycle_line(lc)
    init._lifecycle_landed(tpl, good, "brain", lc)
    for bad in ("brain:\n    root: .\nother:\n    root: x\n" + init.lifecycle_line(lc),   # not YAML
                "brain:\n  root: .\nother:\n  root: x\n" + init.lifecycle_line(lc)):    # under another entry
        with pytest.raises(init.InitError, match="lifecycle line"):
            init._lifecycle_landed(tpl, bad, "brain", lc)


def test_the_cockpit_wizard_plans_with_the_personal_brains_owner(tmp_path, brain_home, capsys):
    """The cockpit's words carry no --owner: the owner of this machine's personal brain stands for it."""
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "config.json").write_text('{"v": 1, "identity": {"owner": "Ada"}}', encoding="utf-8")
    brain_home.mkdir(parents=True, exist_ok=True)
    (brain_home / "personal.json").write_text('{"root": "%s"}' % mine.as_posix(), encoding="utf-8")
    words = wizards.by_id()["project-new"].words("plan", "cli", str(tmp_path / "lab"))
    assert cli.main(words[1:]) == 0
    out = capsys.readouterr().out
    assert " for Ada " in out and f"(plan only: brain project new {tmp_path / 'lab'} --kind cli --stage prototype " \
                                  "--apply writes it)" in out and "brain init --apply" not in out


def test_an_unreadable_or_strange_folder_is_said_and_never_written(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--owner", "Ada", "--apply"]) == 0
    (d / "projects.yaml").write_text("brain: [unclosed\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["project", "new", str(d), "--kind", "cli"]) == 2
    assert "not readable YAML" in capsys.readouterr().out
    odd = tmp_path / "odd"
    odd.mkdir()
    (odd / "projects.yaml").write_text("x: {root: .}\n", encoding="utf-8")
    assert cli.main(["project", "new", str(odd), "--kind", "cli", "--owner", "Ada", "--apply"]) == 2
    assert "no config.json" in capsys.readouterr().out and not (odd / "config.json").exists()


def test_a_changed_template_is_a_change(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--owner", "Ada", "--apply"]) == 0
    capsys.readouterr()
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--template", "service"]) == 0
    assert "template: cli -> service" in capsys.readouterr().out
