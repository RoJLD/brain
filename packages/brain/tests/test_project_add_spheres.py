"""The default spheres and the qualification (wi-brain-project-add-spheres): brain init --examples writes a person's
default spheres in scopes.yaml (SCOPE-1, none for a team); brain project add asks the five questions of the
qualification (spec-brain-product-lifecycle 3.10) by its plan, by options or in the terminal (--interactive), and
writes their answers to the entry's lifecycle; brain check reads lifecycle's stage, shape and profile against their
catalogs (an unknown value a note in read mode, an error in strict mode). Fictitious names only."""

import json

import pytest
import yaml
from brain import __version__, cli, firstrun, init, paths, project_add, projects, schema, scopes, skew

HEADER = "home:\n  root: .\n  title: the brain itself\n"


@pytest.fixture(autouse=True)
def fresh_env(monkeypatch, brain_home):
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.delenv("BRAIN_SCOPES", raising=False)
    monkeypatch.setattr(init, "machine_terms", lambda: {"users": ["ada-l"], "hosts": ["host-a"]})
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])


@pytest.fixture
def home(tmp_path):
    """A brain with a registry, a graph store and the default spheres."""
    d = tmp_path / "home"
    (d / "notes" / "graph").mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}}), encoding="utf-8")
    (d / "projects.yaml").write_text(HEADER, encoding="utf-8")
    (d / "scopes.yaml").write_text(scopes.default_spheres_text(), encoding="utf-8")
    return d


@pytest.fixture
def bench(tmp_path):
    """An existing instance whose own config.json says a team works on it."""
    d = tmp_path / "bench"
    (d / "notes" / "graph").mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Lab", "kind": "team"}}),
                                   encoding="utf-8")
    return d


def registry(d):
    return yaml.safe_load((d / "projects.yaml").read_text(encoding="utf-8"))


# --- brain init --examples ----------------------------------------------------------------------------------------

def test_the_default_spheres_are_the_three_of_scope_1_and_read_as_a_tree(tmp_path):
    data = yaml.safe_load(scopes.default_spheres_text())
    assert data["v"] == 1
    assert data["scopes"] == {sid: {"type": "sphere", "title": title} for sid, title in scopes.DEFAULT_SPHERES.items()}
    assert list(data["scopes"]) == ["pro", "personal", "academic"]


def test_init_examples_plans_the_spheres_then_writes_them_with_a_current_view(tmp_path, capsys):
    root = tmp_path / "ada-brain"
    assert cli.main(["init", str(root), "--owner", "Ada", "--examples"]) == 0
    out = capsys.readouterr().out
    assert "create   scopes.yaml" in out and "--examples: scopes.yaml holds the default spheres" in out
    assert not root.exists()   # a plan writes nothing
    assert cli.main(["init", str(root), "--owner", "Ada", "--examples", "--apply"]) == 0
    capsys.readouterr()
    assert (root / "scopes.yaml").read_text(encoding="utf-8") == scopes.default_spheres_text()
    errors, warnings = scopes.check(root)
    assert errors == [] and warnings == []
    tree = scopes.load(root)
    assert [n for n in tree.nodes if tree.nodes[n].kind == "container"] == list(scopes.DEFAULT_SPHERES)
    # the view is written with the tree, so the first brain check finds it current
    assert (root / scopes.VIEW).read_text(encoding="utf-8") == scopes.view_text(tree)


def test_init_examples_for_a_team_writes_no_sphere(tmp_path, capsys):
    root = tmp_path / "team-brain"
    assert cli.main(["init", str(root), "--owner", "Team Z", "--kind", "team", "--examples", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "a team has no default spheres" in out and not (root / "scopes.yaml").exists()


def test_init_without_examples_writes_no_scope_tree(tmp_path, capsys):
    root = tmp_path / "plain"
    assert cli.main(["init", str(root), "--owner", "Ada", "--apply"]) == 0
    assert "--examples" not in capsys.readouterr().out and not (root / "scopes.yaml").exists()


def test_init_examples_keeps_a_scopes_yaml_already_there(tmp_path, capsys):
    root = tmp_path / "kept"
    root.mkdir()
    (root / "scopes.yaml").write_text("v: 1\nscopes: {}\n", encoding="utf-8")
    assert cli.main(["init", str(root), "--owner", "Ada", "--examples", "--apply"]) == 0
    assert "keep     scopes.yaml (exists)" in capsys.readouterr().out
    assert (root / "scopes.yaml").read_text(encoding="utf-8") == "v: 1\nscopes: {}\n"


def test_the_one_command_of_the_screens_keeps_examples(tmp_path):
    import argparse
    args = argparse.Namespace(kind="person", tenant=None, template=None, name="brain", stage=None, catalogue=None,
                              tier=None, examples=True)
    assert "--examples" in init.command_line(tmp_path, args, "Ada", "lite", "lite", [], [])


# --- brain project add: the qualification ------------------------------------------------------------------------

def test_the_answers_go_to_the_entry_s_lifecycle_under_a_sphere(home, bench, capsys):
    words = ["--root", str(home), "project", "add", "bench", "--existing", str(bench), "--parent", "pro",
             "--profile", "internal", "--kind", "cli", "--kind", "research", "--stage", "mvp", "--floor", "private"]
    assert cli.main(words) == 0
    out = capsys.readouterr().out
    assert "1 purpose and audience: internal (lifecycle.profile)" in out
    assert "2 what it produces: cli, research (lifecycle.typologies)" in out
    assert "3 stage: build (since " in out and "4 criticity: private (classes.floor)" in out
    assert "5 who works on it: team, the identity.kind of its own config.json" in out
    assert registry(home) == {"home": {"root": ".", "title": "the brain itself"}}   # the plan writes nothing
    assert cli.main([*words, "--apply"]) == 0
    capsys.readouterr()
    entry = registry(home)["bench"]
    since = entry["lifecycle"].pop("since")
    assert len(since) == 10 and since[4] == "-"   # the day it is written, YYYY-MM-DD, kept a string
    assert entry == {"root": "../bench", "parent": "pro", "classes": {"floor": "private"},
                     "lifecycle": {"typologies": ["cli", "research"], "stage": "build", "profile": "internal"}}
    assert projects.check(home) == []


def test_the_plan_names_each_unanswered_question_with_its_option(home, bench, capsys):
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench)]) == 0
    out = capsys.readouterr().out
    assert "1 purpose and audience: not answered (--profile maker|client|startup|internal|open-source|research)" in out
    assert "2 what it produces: not answered (--kind K" in out and "3 stage: not answered (--stage S" in out
    assert "4 criticity: not answered (--floor CLASS)" in out


def test_a_read_only_project_takes_no_qualification(home, capsys):
    assert cli.main(["--root", str(home), "project", "add", "orchard", "--read", "--parent", "personal"]) == 0
    assert "qualification: a read-only project answers 4 only, its criticity: not answered (--floor CLASS)" in \
        capsys.readouterr().out
    assert cli.main(["--root", str(home), "project", "add", "orchard", "--read", "--kind", "cli"]) == 2
    assert "--kind: a read-only project's entry holds title, access, parent and classes only" in \
        capsys.readouterr().out


@pytest.mark.parametrize("extra, why", [
    (["--kind", "video-x"], "--kind video-x: not in the typology catalog"),
    (["--stage", "someday"], "--stage someday: one of the lifecycle's stages"),
    (["--team"], "--team goes with --template"),
])
def test_an_answer_it_does_not_take_plans_nothing(home, bench, capsys, extra, why):
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench), *extra,
                     "--apply"]) == 2
    assert why in capsys.readouterr().out and "bench" not in registry(home)


def test_a_bad_profile_is_refused_by_the_parser(home, bench, capsys):
    with pytest.raises(SystemExit):
        cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench), "--profile", "hobby"])
    assert "invalid choice: 'hobby'" in capsys.readouterr().err


def test_a_template_s_team_and_standards_stage_reach_brain_init(home, tmp_path, capsys):
    paths.personal_file().parent.mkdir(parents=True, exist_ok=True)
    paths.personal_file().write_text(json.dumps({"root": str(home)}), encoding="utf-8")
    words = ["--root", str(home), "project", "add", "sprout", "--template", init.DEFAULT_TEMPLATE, "--dir",
             str(tmp_path / "sprout"), "--team", "--stage", "mvp", "--kind", "service"]
    assert cli.main(words) == 0
    out = capsys.readouterr().out
    assert "--stage mvp --kind team --apply" in out and "5 who works on it: a team (brain init --kind team)" in out
    assert cli.main([*words, "--apply"]) == 0
    capsys.readouterr()
    assert json.loads((tmp_path / "sprout" / "config.json").read_text(encoding="utf-8"))["identity"]["kind"] == "team"
    lc = registry(home)["sprout"]["lifecycle"]
    assert lc["typologies"] == ["service"] and lc["stage"] == "build"


def test_interactive_asks_what_the_options_leave(home, bench, monkeypatch, capsys):
    answers = iter(["startup", "service, research", "launch", "confidential"])
    monkeypatch.setattr(firstrun, "tty", lambda: True)
    monkeypatch.setattr(firstrun, "ASK", lambda prompt: next(answers))
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench), "--interactive",
                     "--apply"]) == 0
    capsys.readouterr()
    entry = registry(home)["bench"]
    assert entry["classes"] == {"floor": "confidential"}
    assert {k: v for k, v in entry["lifecycle"].items() if k != "since"} == {
        "typologies": ["service", "research"], "stage": "launch", "profile": "startup"}


def test_interactive_leaves_an_empty_answer_unanswered_and_skips_what_options_gave(home, bench, monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(firstrun, "tty", lambda: True)
    monkeypatch.setattr(firstrun, "ASK", lambda prompt: asked.append(prompt) or "")
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench), "--profile", "maker",
                     "-i", "--apply"]) == 0
    capsys.readouterr()
    assert [p.split(" ")[0] for p in asked] == ["2", "3", "4"]   # 1 answered by --profile; 5: an instance's own
    assert registry(home)["bench"]["lifecycle"] == {"profile": "maker"}


def test_interactive_without_a_terminal_writes_nothing(home, bench, monkeypatch, capsys):
    monkeypatch.setattr(firstrun, "tty", lambda: False)
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench), "-i", "--apply"]) == 2
    assert "--interactive needs a terminal" in capsys.readouterr().out and "bench" not in registry(home)


def test_the_ledger_keeps_the_answers(home, bench, capsys):
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench), "--kind", "cli",
                     "--stage", "build", "--profile", "client", "--apply"]) == 0
    capsys.readouterr()
    rows = [json.loads(line) for f in sorted(paths.ledger_dir().glob("setup-*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    cmd = rows[-1]["command"]
    assert "--profile client" in cmd and "--stage build" in cmd and "--kind cli" in cmd


def test_lifecycle_of_maps_a_standards_stage_and_dates_it(monkeypatch):
    import argparse
    args = argparse.Namespace(kinds=["cli", "cli"], profile=None, stage="v1")
    assert project_add.lifecycle_of(args, today="2030-01-02") == {"typologies": ["cli"], "stage": "launch",
                                                                   "since": "2030-01-02"}
    assert project_add.lifecycle_of(argparse.Namespace(kinds=None, profile=None, stage=None)) == {}


# --- brain check: lifecycle's stage, shape and profile ----------------------------------------------------------

UNKNOWN_LIFECYCLE = [
    ("stage: someday", "stage 'someday' is not one of explore"),
    ("shape: round", "shape 'round' is not one of living, finite"),
    ("profile: hobby", "profile 'hobby' is not one of maker"),
]


def _lifecycle_strict(home, on):
    """config.json projects.lifecycle_strict: absent (None), false or true."""
    data = {"v": 1, "identity": {"owner": "Ada"}}
    if on is not None:
        data["projects"] = {"lifecycle_strict": on}
    (home / "config.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("line, what", UNKNOWN_LIFECYCLE)
def test_an_unknown_lifecycle_value_is_an_error_in_strict_mode_a_note_in_read_mode(home, monkeypatch, capsys, line,
                                                                                    what):
    """Under config.json projects.lifecycle_strict."""
    _lifecycle_strict(home, True)
    (home / "projects.yaml").write_text(HEADER + f"  lifecycle: {{{line}}}\n", encoding="utf-8")
    errors = projects.check(home)
    assert any(what in e for e in errors), errors
    monkeypatch.setenv("BRAIN_STRICT", "0")
    monkeypatch.setattr(schema, "_NOTED", set())   # a note is printed once per process: this test's own
    capsys.readouterr()
    assert not any(what in e for e in projects.check(home))
    notes = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("brain: note: ")]
    assert any(what in ln and "(kept: a newer brain's key? strict in CI)" in ln for ln in notes), notes


def test_known_lifecycle_values_pass(home):
    (home / "projects.yaml").write_text(
        HEADER + "  lifecycle: {typologies: [software], stage: deliver, shape: finite, profile: open-source, "
                 "since: '2030-01-02'}\n", encoding="utf-8")
    assert projects.check(home) == []


@pytest.mark.parametrize("on", [None, False])
@pytest.mark.parametrize("line, what", UNKNOWN_LIFECYCLE)
def test_an_unknown_lifecycle_value_is_a_note_only_without_the_key(home, monkeypatch, capsys, line, what, on):
    """config.json projects.lifecycle_strict absent or false: no error even in strict mode (CI), as 0.5.1, which
    never refused one; the note says it."""
    _lifecycle_strict(home, on)
    (home / "projects.yaml").write_text(HEADER + f"  lifecycle: {{{line}}}\n", encoding="utf-8")
    monkeypatch.setattr(schema, "_NOTED", set())
    capsys.readouterr()
    assert projects.check(home) == []
    assert any(what in ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("brain: note: "))


def test_an_unreadable_catalog_leaves_the_stage_unread_without_the_key(home, monkeypatch):
    from brain import typologies

    def broken(*a, **k):
        raise typologies.CatalogError("x")
    (home / "projects.yaml").write_text(HEADER + "  lifecycle: {stage: someday}\n", encoding="utf-8")
    monkeypatch.setattr(typologies, "load", broken)
    assert projects.check(home) == []
    _lifecycle_strict(home, True)
    with pytest.raises(typologies.CatalogError):
        projects.check(home)


def test_an_unreadable_config_leaves_the_lifecycle_check_a_note(home):
    (home / "config.json").write_text("{not json", encoding="utf-8")
    (home / "projects.yaml").write_text(HEADER + "  lifecycle: {profile: hobby}\n", encoding="utf-8")
    assert not any("profile 'hobby'" in e for e in projects.check(home))


def test_a_standards_stage_written_as_the_lifecycle_s_names_the_stage_it_reads_as(home):
    _lifecycle_strict(home, True)
    (home / "projects.yaml").write_text(HEADER + "  lifecycle: {stage: mvp}\n", encoding="utf-8")
    errors = projects.check(home)
    assert any("stage 'mvp' is not one of" in e and "a standards stage: write build" in e for e in errors), errors


# --- the review's findings ------------------------------------------------------------------------------------------

def test_init_examples_view_reads_the_new_brain_never_another_s_environment(tmp_path, monkeypatch, capsys):
    other = tmp_path / "other"
    other.mkdir()
    (other / "projects.yaml").write_text("zeta-lab:\n  root: .\n", encoding="utf-8")
    (other / "scopes.yaml").write_text("v: 1\nscopes:\n  far-sphere: {type: sphere, title: Far}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", (other / "projects.yaml").as_posix())
    monkeypatch.setenv("BRAIN_SCOPES", (other / "scopes.yaml").as_posix())
    root = tmp_path / "ada-brain"
    assert cli.main(["init", str(root), "--owner", "Ada", "--examples", "--apply"]) == 0
    capsys.readouterr()
    view = (root / scopes.VIEW).read_text(encoding="utf-8")
    assert "zeta-lab" not in view and "far-sphere" not in view
    assert all(s in view for s in scopes.DEFAULT_SPHERES)
    monkeypatch.delenv("BRAIN_PROJECTS")
    monkeypatch.delenv("BRAIN_SCOPES")
    assert view == scopes.view_text(scopes.load(root))   # current for the new brain's own brain check


def test_project_add_reads_the_tree_of_the_brain_it_edits_whatever_brain_scopes_names(home, bench, tmp_path,
                                                                                      monkeypatch, capsys):
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("v: 1\nscopes:\n  far-sphere: {type: sphere, title: Far}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_SCOPES", elsewhere.as_posix())
    words = ["--root", str(home), "project", "add", "bench", "--existing", str(bench)]
    assert cli.main([*words, "--parent", "far-sphere"]) == 2   # not a node of this brain's tree
    capsys.readouterr()
    assert cli.main([*words, "--parent", "academic", "--apply"]) == 0
    assert registry(home)["bench"]["parent"] == "academic"


def test_init_examples_leaves_out_a_sphere_the_brain_s_own_name_holds(tmp_path, capsys):
    root = tmp_path / "pro-brain"
    assert cli.main(["init", str(root), "--owner", "Ada", "--name", "pro", "--examples"]) == 0
    out = capsys.readouterr().out
    assert "--examples: scopes.yaml holds the default spheres of a person (personal, academic;" in out
    assert "left out: pro (a project of the registry has that id" in out
    assert cli.main(["init", str(root), "--owner", "Ada", "--name", "pro", "--examples", "--apply"]) == 0
    capsys.readouterr()
    data = yaml.safe_load((root / "scopes.yaml").read_text(encoding="utf-8"))
    assert list(data["scopes"]) == ["personal", "academic"]
    assert scopes.check(root) == ([], [])


def test_init_examples_leaves_out_a_sphere_a_kept_registry_holds(tmp_path):
    root = tmp_path / "kept"
    root.mkdir()
    (root / "projects.yaml").write_text("brain:\n  root: .\nacademic:\n  root: ../thesis\n", encoding="utf-8")
    assert init.examples_for(root, "person", "brain") == ("person", ("pro", "personal"), ("academic",))
    assert init.examples_for(root, "team", "brain") == ("team", (), ())


def test_init_examples_on_a_team_brain_keeps_its_kind_without_kind_team(tmp_path, capsys):
    root = tmp_path / "lab"
    assert cli.main(["init", str(root), "--owner", "Lab Z", "--kind", "team", "--apply"]) == 0
    capsys.readouterr()
    assert cli.main(["init", str(root), "--examples", "--apply"]) == 0   # a re-run: --kind left at its default
    out = capsys.readouterr().out
    assert "--examples: a team has no default spheres" in out and not (root / "scopes.yaml").exists()
    assert init.kind_in(root) == "team"


def test_since_is_the_local_day(monkeypatch):
    import argparse
    import datetime as dt

    class Local(dt.date):
        @classmethod
        def today(cls):
            return cls(2030, 5, 6)

    monkeypatch.setattr(project_add, "date", Local)
    lc = project_add.lifecycle_of(argparse.Namespace(kinds=None, profile=None, stage="build"))
    assert lc == {"stage": "build", "since": "2030-05-06"}


@pytest.mark.parametrize("stage, std", [("launch", "v1"), ("build", "mvp"), ("grow", "scale"), ("explore", "prototype"),
                                        ("mature", None), (None, None)])
def test_a_lifecycle_stage_reads_back_as_its_standards_stage(stage, std):
    assert project_add.standards_stage(stage, project_add.typologies.load()) == std


def test_a_template_s_lifecycle_stage_selects_the_same_standards(home, tmp_path, capsys):
    paths.personal_file().parent.mkdir(parents=True, exist_ok=True)
    paths.personal_file().write_text(json.dumps({"root": str(home)}), encoding="utf-8")
    words = ["--root", str(home), "project", "add", "sprout", "--template", "cli", "--dir", str(tmp_path / "sprout"),
             "--stage", "launch"]
    assert cli.main(words) == 0
    assert "--stage v1 --apply" in capsys.readouterr().out
    assert cli.main([*words, "--apply"]) == 0
    capsys.readouterr()
    assert registry(home)["sprout"]["lifecycle"]["stage"] == "launch"
    std = yaml.safe_load((tmp_path / "sprout" / "projects.yaml").read_text(encoding="utf-8"))["sprout"]["standards"]
    assert std["stage"] == "v1"   # the standards brain init selected, at the stage the entry records


def test_a_stage_with_no_standards_stage_keeps_brain_init_s_default_and_says_so(home, tmp_path, capsys):
    paths.personal_file().parent.mkdir(parents=True, exist_ok=True)
    paths.personal_file().write_text(json.dumps({"root": str(home)}), encoding="utf-8")
    assert cli.main(["--root", str(home), "project", "add", "sprout", "--template", init.DEFAULT_TEMPLATE, "--dir",
                     str(tmp_path / "sprout"), "--stage", "mature"]) == 0
    out = capsys.readouterr().out
    first = next(ln for ln in out.splitlines() if ln.strip().startswith("first: brain init"))
    assert "--stage" not in first
    assert "brain init's standards: its default stage (mature reads as no standards stage" in out


def test_a_read_only_project_s_plan_shows_its_floor(home, capsys):
    assert cli.main(["--root", str(home), "project", "add", "orchard", "--read", "--floor", "private"]) == 0
    assert "qualification: a read-only project answers 4 only, its criticity: private (classes.floor)" in \
        capsys.readouterr().out


def test_interactive_checks_the_options_before_asking(home, bench, monkeypatch, capsys):
    def never(prompt):
        raise AssertionError(f"asked {prompt!r} before the options were checked")
    monkeypatch.setattr(firstrun, "tty", lambda: True)
    monkeypatch.setattr(firstrun, "ASK", never)
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench), "--kind", "video-x",
                     "-i", "--apply"]) == 2
    assert "--kind video-x: not in the typology catalog" in capsys.readouterr().out
    assert cli.main(["--root", str(home), "project", "add", "Bad_Name", "--existing", str(bench), "-i"]) == 2
    assert "bench" not in registry(home)


def test_interactive_reads_an_input_that_ends_as_no_terminal(home, bench, monkeypatch, capsys):
    def ended(prompt):
        raise EOFError
    monkeypatch.setattr(firstrun, "tty", lambda: True)   # stdin from NUL: isatty says True on Windows
    monkeypatch.setattr(firstrun, "ASK", ended)
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(bench), "-i", "--apply"]) == 2
    out = capsys.readouterr().out
    assert "--interactive needs a terminal" in out and "(its input ended)" in out and "cancelled" not in out
    assert "bench" not in registry(home)
