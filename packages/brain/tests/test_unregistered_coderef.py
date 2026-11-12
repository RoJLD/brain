"""wi-brain-audit-unregistered-coderef: an active CodeRef of a repo no project registers is an error of brain check
--all (a warning in a brain's own root without --all) and a coderef.dangling P0 of brain audit (tests/test_audit.py),
not a line of « not measured » nobody reads. A CodeRef of a registered repo, a retired one and one of another
project's repo pass."""

from __future__ import annotations

from research_graph.cli import main as research_graph

from brain import audit, projects
from brain.commands._stores import check_registry

CODE = ('- {id: "code:home:x.py", type: CodeRef, status: active, title: its own repo}\n'
        '- {id: "code:other:y.py", type: CodeRef, status: active, title: "another project\'s repo"}\n'
        '- {id: "code:nowhere:z.py", type: CodeRef, status: active, title: no project registers it}\n'
        '- {id: "code:nowhere:old.py", type: CodeRef, status: retired, title: retired}\n')


def _registry(tmp_path, monkeypatch):
    stores = {}
    for name in ("home", "other"):
        root = tmp_path / name
        store = root / "notes" / "graph"
        assert research_graph(["--store", str(store), "--repo-root", str(root), "init", "--owner", "Ada"]) == 0
        stores[name] = store
    (stores["home"] / "nodes" / "code.yaml").write_text(CODE, encoding="utf-8")
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text("".join(f"{n}:\n  root: {(tmp_path / n).as_posix()}\n" for n in stores), encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return list(projects.load().values())


def test_the_registrys_repo_tokens_and_a_stores_coderefs(tmp_path, monkeypatch):
    projs = _registry(tmp_path, monkeypatch)
    assert projects.repo_tokens() == {"home", "other"}
    assert ("code:nowhere:old.py", "retired") in projects.code_refs(projs[0].stores[0])


def test_check_all_refuses_an_active_coderef_of_an_unregistered_repo(tmp_path, monkeypatch, capsys):
    projs = _registry(tmp_path, monkeypatch)
    assert check_registry(None, projs, every=True) == 1
    errors = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("error:")]
    assert errors == ["error: CodeRef code:nowhere:z.py (home): its repo nowhere is in no project's repos: (register "
                      "it, point the CodeRef at a registered repo, or retire it)"]


def test_without_all_it_is_a_warning(tmp_path, monkeypatch, capsys):
    projs = _registry(tmp_path, monkeypatch)
    assert check_registry(None, projs) == 0
    assert "warning: CodeRef code:nowhere:z.py (home): its repo nowhere" in capsys.readouterr().out


def test_the_audit_reads_the_registry_the_project_came_from_found_by_its_root(tmp_path):
    """Review of the PR, finding 1: no BRAIN_PROJECTS, no pointer: the registry is the brain root's, found through the
    project's registry_dir, not by walking from the project's own root."""
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "projects.yaml").write_text(f"home:\n  root: {(tmp_path / 'home').as_posix()}\n"
                                         f"lab:\n  root: {(tmp_path / 'lab').as_posix()}\n", encoding="utf-8")
    home = projects.load(brain)["home"]
    assert home.registry_dir == brain and {"home", "lab"} <= audit._repo_tokens(home, [])


def test_a_project_whose_repos_do_not_read_and_a_read_only_one_still_count(tmp_path):
    """Review of the PR, findings 2 and 3: a RepoError keeps the project's name and declared folders; a read-only
    project's name is a repo the brain never audits, not an unregistered one."""
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "projects.yaml").write_text(
        f"lab:\n  root: {(tmp_path / 'lab').as_posix()}\n  repos: [., ../lab-data]\n  audit: {{max_lines: 0}}\n"
        "foyr:\n  title: a product read only\n  access: read\n", encoding="utf-8")
    assert {"lab", "lab-data", "foyr"} <= projects.repo_tokens(brain)


def test_an_unknown_registry_never_makes_a_p0():
    """A project with no registry (an audit of a bare repo): its CodeRefs of other repos stay not measured."""
    p = projects.Project("demo", tmp := projects.Path("/m/lab"), [tmp / "notes" / "graph"])
    assert p.registry_dir is None and audit._repo_tokens(p, []) is None
