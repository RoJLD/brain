"""The personal graph's ids and ADR titles a public repo refuses (wi-brain-public-private-ids, brain.privateids): the
``graph`` check of brain check --public and of the public commit guard."""

import json

import pytest
from brain import cli, config, guards, privateids, public
from conftest import run_git

MINE = """\
- {id: wi-mine-task, type: WorkItem, status: todo, title: "A task of the engine"}
- {id: feat-mine-thing, type: Feature, status: have, title: "A feature of the engine"}
- {id: adr-2026-03-04-sovereign-choice, type: ADR, status: active, title: "Les choix souverains du moteur public"}
- {id: adr-2026-03-05-ok, type: ADR, status: active, title: "Too short"}
- {id: ddr-2026-03-05-which-host, type: DDR, status: answered, title: "Which host"}
"""
LAB = """\
- {id: wi-lab-secret-plan, type: WorkItem, status: todo, title: "The lab's plan"}
- {id: ms-lab-launch, type: Milestone, status: pending, title: "Launch"}
"""


def _store(root, nodes):
    (root / "notes" / "graph" / "nodes").mkdir(parents=True)
    (root / "notes" / "graph" / "schema.yaml").write_text("owner: Ada\nnode_types: [WorkItem]\n", encoding="utf-8")
    (root / "notes" / "graph" / "nodes" / "work.yaml").write_text(nodes, encoding="utf-8")


@pytest.fixture
def pub(tmp_path, monkeypatch, make_repo):
    """Ada's brain (its project mine, whose repos are the brain and the public engine, and a project lab) and a clean
    checkout of the public repo acme/engine."""
    brain, lab = tmp_path / "ada-brain", tmp_path / "lab"
    _store(brain, MINE)
    _store(lab, LAB)
    (brain / "projects.yaml").write_text(
        f"mine: {{root: ., repos: [., ../engine]}}\nlab: {{root: {lab.as_posix()}}}\n", encoding="utf-8")
    (brain / config.FILE).write_text(json.dumps(
        {"v": 1, "identity": {"owner": "Ada"},
         "public": {"repos": ["acme/engine"], "allow": {"docs/history.md": "the history quotes the decisions on purpose"}}}),
        encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / config.FILE))
    monkeypatch.setenv("BRAIN_PROJECTS", str(brain / "projects.yaml"))
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setattr(guards, "gitleaks", lambda repo: None)
    repo = make_repo("engine", {"README.md": "# engine\n\nIts items: wi-mine-task, feat-mine-thing.\n"})
    run_git(repo, "remote", "add", "origin", "https://github.com/acme/engine.git")
    return repo




def test_the_index_holds_decisions_everywhere_and_other_projects_ids(pub):
    idx = privateids.index((pub.parent / "ada-brain"), "acme/engine")
    assert idx.own == ["mine"]   # its repo ../engine is named as the public repo
    assert set(idx.ids) == {"adr-2026-03-04-sovereign-choice", "adr-2026-03-05-ok", "ddr-2026-03-05-which-host",
                            "wi-lab-secret-plan"}   # ms-lab-launch: not a shape of the list
    assert idx.titles == {6: {("les", "choix", "souverains", "du", "moteur", "public"): "adr-2026-03-04-sovereign-choice"}}
    # another public repo has no own project: every id of the shapes is refused
    assert "wi-mine-task" in privateids.index((pub.parent / "ada-brain"), "acme/other").ids


@pytest.mark.parametrize("line, what", [
    ("See wi-lab-secret-plan.", "the private id wi-lab-secret-plan (lab:notes/graph, not this repo's project)"),
    ("(adr-2026-03-04-sovereign-choice)", "the private ADR adr-2026-03-04-sovereign-choice (mine:notes/graph)"),
    ("ddr-2026-03-05-which-host answered", "the private DDR ddr-2026-03-05-which-host (mine:notes/graph)"),
    ('ADR "LES CHOIX — souverains du moteur public":', "the title of the private ADR adr-2026-03-04-sovereign-choice"),
])
def test_a_line_with_a_private_id_or_title_is_refused(pub, line, what):
    idx = privateids.index((pub.parent / "ada-brain"), "acme/engine")
    assert privateids.find(line, idx) == [what]


def test_an_id_with_a_files_extension_is_the_id(pub):
    idx = privateids.index((pub.parent / "ada-brain"), "acme/engine")
    assert privateids.find("see ../decisions/adr-2026-03-04-sovereign-choice.md", idx) == [
        "the private ADR adr-2026-03-04-sovereign-choice (mine:notes/graph)"]
    assert privateids.find("changes/wi-lab-secret-plan.v2.md", idx)


def test_the_index_is_read_once_until_a_nodes_file_changes(pub):
    brain = pub.parent / "ada-brain"
    first = privateids.index(brain, "acme/engine")
    assert privateids.index(brain, "acme/engine") is first
    f = brain / "notes" / "graph" / "nodes" / "work.yaml"
    f.write_text(f.read_text(encoding="utf-8") + "- {id: wi-mine-new, type: WorkItem, status: todo, title: N}\n",
                 encoding="utf-8")
    assert privateids.index(brain, "acme/engine") is not first


def test_a_caller_without_the_public_repo_checks_no_graph_id(pub):
    """A render (brain features, brain reference, the README check) or a PR body (the merge gate) is checked
    without its repo: no graph id, since which ids are its own depends on the repo."""
    from brain import features
    cfg = config.load()
    assert public.rules(cfg).graph is None and public.rules(cfg, "acme/other").graph is None
    assert public.rules(cfg, "acme/engine").graph is not None
    assert features.denied_lines("- **Thing** `feat-mine-thing` see wi-lab-secret-plan\n", cfg) == []


def test_the_engine_side_takes_the_engines_repo(pub):
    cfg = config.load()
    cfg.data["public"]["repos"] = ["acme/docs", "acme/engine"]
    cfg.data["engine"] = {"repo": "acme/engine"}
    assert public.engine_repo(cfg) == "acme/engine"
    cfg.data["engine"] = {}
    assert public.engine_repo(cfg) == "acme/docs"


@pytest.mark.parametrize("line", ["wi-mine-task and feat-mine-thing", "adr-2026-01-01-x, an invented id",
                                  "wi-lab-secret-planner", "Les choix souverains du moteur", "Too short"])
def test_the_own_projects_ids_and_invented_ids_pass(pub, line):
    assert privateids.find(line, privateids.index((pub.parent / "ada-brain"), "acme/engine")) == []


def test_brain_check_public_refuses_them_with_its_history(pub, make_repo, capsys):
    assert cli.main(["check", "--public", "--repo", str(pub)]) == 0
    assert "domain 0, graph 0" in capsys.readouterr().out
    (pub / "docs").mkdir()
    (pub / "docs" / "history.md").write_text("adr-2026-03-04-sovereign-choice\n", encoding="utf-8")
    make_repo.commit(pub, {"src/x.py": "# wi-lab-secret-plan\n"}, msg="Fix ddr-2026-03-05-which-host")
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 1
    out = capsys.readouterr().out
    assert "src/x.py:1: graph: the private id wi-lab-secret-plan" in out
    assert "<message>:1: graph: the private DDR ddr-2026-03-05-which-host" in out
    assert "history.md" not in out   # public.allow excepts it


def test_the_commit_guard_refuses_them(pub):
    (pub / "notes.md").write_text("As decided in adr-2026-03-04-sovereign-choice.\n", encoding="utf-8")
    p = {"tool_name": "Bash", "tool_input": {"command": 'git add notes.md && git commit -m "notes"'}, "cwd": str(pub)}
    (reason,) = [r for g, _, r, _ in guards.refusals(p) if g == "public"]
    assert "notes.md:1: graph: the private ADR adr-2026-03-04-sovereign-choice" in reason
    (pub / "notes.md").write_text("As decided in wi-mine-task.\n", encoding="utf-8")
    assert not [r for g, _, r, _ in guards.refusals(p) if g == "public"]


def test_a_store_or_registry_that_cannot_be_read_is_said(pub):
    (pub.parent / "lab" / "notes" / "graph" / "nodes" / "work.yaml").write_text("- {id: [\n", encoding="utf-8")
    idx = privateids.index((pub.parent / "ada-brain"), "acme/engine")
    assert idx.errors == ["the ids of lab:notes/graph are not checked: " + idx.errors[0].rsplit(": ", 1)[1]]
    assert "wi-lab-secret-plan" not in idx.ids and "adr-2026-03-04-sovereign-choice" in idx.ids
    data = public.check(pub, config.load())
    assert any("lab:notes/graph are not checked" in n for n in data["notes"])


def test_a_brain_without_a_public_repo_reads_no_graph(pub):
    cfg = config.load()
    cfg.data["public"]["repos"] = []
    assert public.rules(cfg, "acme/engine").graph is None
