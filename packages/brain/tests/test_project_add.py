"""brain project add (brain.project_add, wi-brain-project-add): a project registered in a brain's projects.yaml by a
command, a plan then --apply: read only, an existing instance, or a new one from a template; placed in the scope tree
(--parent), marked by a class floor (--floor); the registry as it would be checked before the write, the entry
appended with the comments kept, the step logged in the setup ledger. Fictitious names only."""

import json

import pytest
import yaml
from brain import __version__, cli, init, paths, project_add, projects, skew

HEADER = "# the registry of a test brain: this comment is kept\nhome:\n  root: .\n  title: the brain itself\n"


@pytest.fixture(autouse=True)
def fresh(monkeypatch, brain_home):
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.delenv("BRAIN_SCOPES", raising=False)
    monkeypatch.setattr(init, "machine_terms", lambda: {"users": ["ada-l"], "hosts": ["host-a"]})
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])


@pytest.fixture
def home(tmp_path):
    """A brain with a registry, a graph store and a scope tree: a folder of apps split by a private floor."""
    d = tmp_path / "home"
    (d / "notes" / "graph").mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}}), encoding="utf-8")
    (d / "projects.yaml").write_text(HEADER, encoding="utf-8")
    (d / "scopes.yaml").write_text(
        "v: 1\nscopes:\n  apps: {type: folder, title: Apps}\n"
        "  closed-apps: {type: folder, title: Closed apps, parent: apps, classes: {floor: private}}\n",
        encoding="utf-8")
    return d


def ledger_rows():
    files = sorted(paths.ledger_dir().glob("setup-*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def registry(d):
    return yaml.safe_load((d / "projects.yaml").read_text(encoding="utf-8"))


def test_a_plan_writes_nothing_and_apply_appends_a_read_entry_with_the_comments_kept(home, capsys):
    words = ["--root", str(home), "project", "add", "orchard", "--read", "--title", "a lab read only", "--parent",
             "closed-apps"]
    assert cli.main(words) == 0
    out = capsys.readouterr().out
    assert "brain project add orchard: its entry in" in out and "(plan: --apply writes it)" in out
    assert "    access: read\n    parent: closed-apps" in out and "under closed-apps" in out
    assert (home / "projects.yaml").read_text(encoding="utf-8") == HEADER and ledger_rows() == []
    assert cli.main([*words, "--apply"]) == 0
    text = (home / "projects.yaml").read_text(encoding="utf-8")
    assert text.startswith(HEADER)   # appended: the comment and the order of the entries kept
    assert registry(home)["orchard"] == {"title": "a lab read only", "access": "read", "parent": "closed-apps"}
    row = ledger_rows()[-1]
    assert row["via"] == "project-add" and row["exit"] == 0 and row["by"] == "Ada"
    assert row["command"].startswith("brain project add orchard --parent closed-apps") and "--apply" in row["command"]
    assert "orchard:" in row["output"]


def test_an_existing_instance_gets_a_relative_root_and_a_floor(home, tmp_path, capsys):
    other = tmp_path / "workshop"
    (other / "notes" / "graph").mkdir(parents=True)
    assert cli.main(["--root", str(home), "project", "add", "workshop", "--existing", str(other), "--parent", "apps",
                     "--floor",
                     "private", "--apply"]) == 0
    capsys.readouterr()
    assert registry(home)["workshop"] == {"root": "../workshop", "parent": "apps", "classes": {"floor": "private"}}


def test_an_existing_instance_with_another_store_declares_it(home, tmp_path, capsys):
    other = tmp_path / "bench"
    (other / "graph").mkdir(parents=True)
    assert cli.main(["--root", str(home), "project", "add", "bench", "--existing", str(other), "--store", "graph",
                     "--apply"]) == 0
    capsys.readouterr()
    assert registry(home)["bench"] == {"root": "../bench", "stores": ["graph"]}


def test_the_deny_terms_it_adds_are_shown_when_the_tree_generates_them(home, capsys):
    cfg = json.loads((home / "config.json").read_text(encoding="utf-8"))
    cfg["public"] = {"deny_from_tree": True}
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert cli.main(["--root", str(home), "project", "add", "orchard", "--read", "--parent", "closed-apps"]) == 0
    assert "public.deny.repos gains (public.deny_from_tree): orchard" in capsys.readouterr().out
    assert cli.main(["--root", str(home), "project", "add", "meadow", "--read", "--parent", "apps"]) == 0
    assert "public.deny.repos gains" not in capsys.readouterr().out   # no floor along its chain


@pytest.mark.parametrize("extra, needle", [
    (["Bad_Name", "--read"], "kebab-case"),
    (["home", "--read"], "home is registered already"),
    (["apps", "--read"], "apps is a container of the scope tree already"),
    (["global", "--read"], "the tree's root"),
    (["orchard", "--read", "--parent", "nowhere"], "its parent 'nowhere' is no node"),
    (["orchard", "--read", "--floor", "secretish"], "--floor secretish: one of"),
    (["orchard", "--read", "--store", "graph"], "a read-only project has no store"),
    (["orchard", "--template", "x"], "--dir DIR names its folder"),
])
def test_an_answer_it_cannot_take_writes_nothing(home, capsys, extra, needle):
    assert cli.main(["--root", str(home), "project", "add", *extra, "--apply"]) == 2
    assert needle in capsys.readouterr().out
    assert (home / "projects.yaml").read_text(encoding="utf-8") == HEADER and ledger_rows() == []


def test_one_way_in_is_required(home, capsys):
    with pytest.raises(SystemExit):
        cli.main(["--root", str(home), "project", "add", "orchard"])
    with pytest.raises(SystemExit):
        cli.main(["--root", str(home), "project", "add", "orchard", "--read", "--existing", str(home)])


def test_an_existing_folder_without_a_store_or_already_a_root_is_refused(home, tmp_path, capsys):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert cli.main(["--root", str(home), "project", "add", "bare", "--existing", str(bare)]) == 2
    assert "no graph store at notes/graph" in capsys.readouterr().out
    assert cli.main(["--root", str(home), "project", "add", "again", "--existing", str(home)]) == 2
    assert "the root of home already" in capsys.readouterr().out
    assert cli.main(["--root", str(home), "project", "add", "ghost", "--existing", str(tmp_path / "none")]) == 2
    assert "no such folder" in capsys.readouterr().out


def test_no_registry_here_is_refused_and_the_pointer_s_brain_is_never_written(tmp_path, capsys, home, monkeypatch):
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    monkeypatch.setenv("BRAIN_PERSONAL", str(home))   # a pointer to another brain: not the registry acted on
    assert cli.main(["--root", str(empty), "project", "add", "orchard", "--read", "--apply"]) == 2
    assert "no projects.yaml at" in capsys.readouterr().out
    assert (home / "projects.yaml").read_text(encoding="utf-8") == HEADER


def test_an_error_already_in_the_registry_is_left_to_brain_check(home, capsys):
    (home / "projects.yaml").write_text(HEADER + "stray:\n  access: maybe\n", encoding="utf-8")
    assert cli.main(["--root", str(home), "project", "add", "orchard", "--read", "--apply"]) == 0
    capsys.readouterr()
    assert registry(home)["orchard"] == {"access": "read"}


def test_a_template_writes_the_project_s_brain_then_registers_it(home, tmp_path, capsys, monkeypatch):
    new = tmp_path / "sprout"
    words = ["--root", str(home), "project", "add", "sprout", "--template", init.DEFAULT_TEMPLATE, "--dir", str(new),
             "--parent", "apps"]
    assert cli.main(words) == 0
    out = capsys.readouterr().out
    assert "first: brain init" in out and not new.exists()
    assert cli.main([*words, "--apply"]) == 0
    capsys.readouterr()
    assert (new / "notes" / "graph").is_dir()
    assert registry(home)["sprout"] == {"root": "../sprout", "parent": "apps"}
    assert registry(new)["sprout"]["root"] == "."   # its own registry names it as this one does
    vias = [r["via"] for r in ledger_rows()]
    assert "init" in vias and vias[-1] == "project-add"
    monkeypatch.setenv("BRAIN_PROJECTS", str(home / "projects.yaml"))
    assert "sprout" in projects.load(home)


def test_a_template_into_a_folder_that_holds_files_is_refused(home, tmp_path, capsys):
    full = tmp_path / "full"
    full.mkdir()
    (full / "a.txt").write_text("x", encoding="utf-8")
    assert cli.main(["--root", str(home), "project", "add", "full", "--template", init.DEFAULT_TEMPLATE, "--dir",
                     str(full)]) == 2
    assert "not empty" in capsys.readouterr().out


def test_the_entry_block_is_a_block_mapping_in_the_given_order():
    assert project_add.block("orchard", {"title": "é", "access": "read"}) == "orchard:\n  title: é\n  access: read\n"
