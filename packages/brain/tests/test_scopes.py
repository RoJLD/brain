"""The scope tree as data (brain.scopes, wi-brain-scope-tree; spec-brain-scope-tree 3.1, 3.2, 3.13): parent: in the
registry, the containers of scopes.yaml, the type catalogue, brain check's rules, brain scopes, --scope on status, the
generated view; a brain without a tree stays flat under Global. Fictitious names only."""

import json
import shutil

import pytest

from brain import cli, config, projects, scopes, status
from brain.commands import _stores

TREE = """\
v: 1
scopes:
  pro: {type: sphere, title: Professional}
  home: {type: sphere, title: Personal}
  acme: {type: company, title: ACME SA, parent: pro, classes: {floor: confidential}}
  finance: {type: unit, title: Finance, parent: acme, also_under: [home]}
"""


@pytest.fixture
def brain(tmp_path, monkeypatch, store):
    """A brain at tmp_path/root (the store fixture's root) with config.json and a registry of three projects: alpha
    (the brain's own root), beta and gamma beside it; no scopes.yaml until a test writes one."""
    root = store.parent.parent
    for name in ("beta", "gamma"):
        shutil.copytree(store, tmp_path / name / "notes" / "graph")
    (root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.delenv("BRAIN_SCOPES", raising=False)

    def registry(text: str) -> None:
        (root / "projects.yaml").write_text(text, encoding="utf-8")

    registry("alpha: {root: .}\nbeta: {root: ../beta}\ngamma: {root: ../gamma}\n")
    registry.root = root
    return registry


def _tree(root, text=TREE):
    (root / scopes.FILE).write_text(text, encoding="utf-8")


def test_without_a_tree_every_project_sits_flat_under_global(brain):
    tree = scopes.load(brain.root)
    assert not tree.present and tree.file is None
    assert tree.children(scopes.GLOBAL) == ["alpha", "beta", "gamma"]
    assert scopes.check(brain.root) == ([], [])
    assert not scopes.view_applies(brain.root)
    lines = scopes.render(tree)
    assert lines[0] == "Global (3 projects)" and "no scope tree" in lines[-1]
    assert scopes.select("global", brain.root) == ("global", ["alpha", "beta", "gamma"])


def test_parent_places_projects_under_containers_and_projects(brain):
    brain("alpha: {root: ., parent: finance}\nbeta: {root: ../beta, parent: alpha}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    tree = scopes.load(brain.root)
    assert tree.present
    assert tree.chain("beta") == ["alpha", "finance", "acme", "pro"]
    assert tree.path("beta") == "pro/acme/finance/alpha/beta" and tree.depth("beta") == 5
    assert tree.children(scopes.GLOBAL) == ["pro", "home", "gamma"]   # containers first
    assert tree.projects_under("acme") == ["alpha", "beta"] and tree.projects_under("home") == []
    assert scopes.check(brain.root) == ([], [])
    assert scopes.resolve(tree, "pro/acme") == "acme" and scopes.resolve(tree, "global/pro") == "pro"
    assert scopes.resolve(tree, ".", here="alpha") == "alpha" and scopes.resolve(tree, "..", here="alpha") == "finance"
    with pytest.raises(scopes.ScopeError, match="not a child of pro"):
        scopes.resolve(tree, "pro/finance")
    with pytest.raises(scopes.ScopeError, match="no node of that id"):
        scopes.resolve(tree, "nowhere")
    assert scopes.select("acme", brain.root) == ("acme", ["alpha", "beta"])
    text = "\n".join(scopes.render(tree))
    assert "acme « ACME SA » (Company) 2 projects" in text
    assert "↪ finance (shortcut; its place is pro/acme/finance)" in text   # SCOPE-5: shown, never counted twice
    assert "├─ home « Personal » (Sphere)\n" in text   # an empty container: no count


def test_the_check_refuses_what_the_spec_refuses(brain):
    brain("alpha: {root: ., parent: nowhere}\nbeta: {root: ../beta, parent: loop-a}\ngamma: {root: ../gamma}\n")
    _tree(brain.root, """\
v: 1
scopes:
  pro: {type: sphere}
  gamma: {type: folder}
  loop-a: {type: folder, parent: loop-b}
  loop-b: {type: folder, parent: loop-a}
  odd: {type: planet}
  Bad_Id: {type: folder}
  host: {type: tenant}
  low: {type: unit, parent: high, classes: {floor: private}}
  high: {type: company, parent: pro, classes: {floor: confidential}}
  weird: {type: folder, classes: {floor: top}}
  global: {type: folder}
""")
    errors, _ = scopes.check(brain.root)
    assert "project alpha: its parent 'nowhere' is no node (a container of scopes.yaml, a project, or global)" in errors
    assert any(e.startswith("scope loop-a: its parents loop back to it") for e in errors)
    assert any(e.startswith("scope gamma: gamma is a project of the registry too") for e in errors)
    assert any(e.startswith("scope odd: unknown type 'planet'") for e in errors)
    assert "scope Bad_Id: an id is lowercase letters, digits and '-' (kebab-case)" in errors
    assert any(e.startswith("scope host: a tenant is another brain") for e in errors)
    assert any(e.startswith("scope low: its class floor private is under confidential, the floor high sets") for e in
               errors)
    assert "scope weird: classes.floor is one of public, private, confidential, sealed, resident, secret, not 'top'" \
        in errors
    assert any(e.startswith("scope global: global is the root") for e in errors)


def test_depth_past_six_levels_is_a_warning_and_the_catalogue_constrains_children(brain, monkeypatch):
    chain = "".join(f"  n{i}: {{type: folder{', parent: n' + str(i - 1) if i else ''}}}\n" for i in range(7))
    _tree(brain.root, "v: 1\nscopes:\n" + chain + "  club: {type: association, parent: n0}\n")
    errors, warnings = scopes.check(brain.root)
    assert errors == []
    assert warnings == ["scope n6 is 7 levels under global (more than 6): each level that carries rules costs every "
                        "session of its subtree"]
    data = {"v": 1, "identity": {"owner": "Ada"},
            "scope_types": {"folder": {"fr": "Classeur", "children": ["folder", "project"]},
                            "programme": {"en": "Programme", "fr": "Programme"}}}
    (brain.root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
    tree = scopes.load(brain.root)
    assert tree.label("folder", "fr") == "Classeur" and tree.label("folder") == "Folder"   # renamed, id kept
    assert tree.label("programme") == "Programme"
    errors, _ = scopes.check(brain.root)
    assert errors == ["scope club: a association under n0, whose type folder accepts folder, project (config.json "
                      "scope_types children)"]
    assert config.check(brain.root) == []   # the key is the schema's


def test_registry_accepts_parent_on_every_kind_of_entry(brain):
    brain("alpha: {root: ., parent: pro}\nup: {title: upstream, access: read, parent: pro}\n"
          "team: {title: hosted, tenant: {}, parent: pro}\n")
    _tree(brain.root)
    assert projects.check(brain.root) == []
    tree = scopes.load(brain.root)
    assert [(n, tree.nodes[n].kind) for n in tree.children("pro")] == [("acme", "container"), ("alpha", "project"),
                                                                     ("up", "read"), ("team", "mount")]
    assert scopes.select("pro", brain.root) == ("pro", ["alpha"])   # no command reads into the other two
    assert "parent" in projects.KEYS


def test_brain_scopes_and_status_scope(brain, monkeypatch, capsys):
    brain("alpha: {root: ., parent: finance}\nbeta: {root: ../beta, parent: home}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    root = str(brain.root)
    assert cli.main(["--root", root, "scopes"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Global (3 projects)\n") and "finance « Finance » (Unit) 1 project" in out
    assert cli.main(["--root", root, "scopes", "--scope", "pro", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["scope"] == "pro" and [n["id"] for n in data["nodes"]] == ["pro", "acme", "finance", "alpha"]
    assert cli.main(["--root", root, "scopes", "--types", "--lang", "fr"]) == 0
    assert "sphere" in capsys.readouterr().out
    assert cli.main(["--root", root, "status", "--scope", "pro", "--quick", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["scope"] == "pro" and [p["project"] for p in data["projects"]] == ["alpha"] and "total" not in data
    assert cli.main(["--root", root, "status", "--scope", "global", "--quick", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [p["project"] for p in data["projects"]] == ["alpha", "beta", "gamma"] and "total" in data   # = --all
    assert cli.main(["--root", root, "status", "--scope", "..", "--quick"]) == 0   # alpha's parent: finance
    assert capsys.readouterr().out.startswith("scope: pro/acme/finance (1 project(s))\n")
    with pytest.raises(SystemExit, match="one of them"):
        cli.main(["--root", root, "status", "--scope", "pro", "--all"])
    with pytest.raises(SystemExit, match="no registered project the brain loads under acme"):
        brain("alpha: {root: .}\nbeta: {root: ../beta}\ngamma: {root: ../gamma}\n")
        cli.main(["--root", root, "status", "--scope", "acme"])


def test_resume_and_digest_take_scope(brain, monkeypatch, capsys):
    from brain import digest, resume
    brain("alpha: {root: ., parent: pro}\nbeta: {root: ../beta, parent: acme}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    monkeypatch.setattr(resume, "build", lambda p, **k: f"pack {p.name}\n")
    assert cli.main(["--root", str(brain.root), "resume", "--scope", "pro"]) == 0
    assert capsys.readouterr().out == "pack beta\n\npack alpha\n"   # depth first, the containers' subtrees first
    monkeypatch.setattr(digest, "gather", lambda p, since, until, offline=False: {"project": p.name})
    monkeypatch.setattr(digest, "render", lambda p, d, budget=0: "")
    assert cli.main(["--root", str(brain.root), "digest", "--scope", "acme", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"project": "beta"}]   # a list, as with --all


def test_status_scope_on_a_multi_project_node_adds_the_totals(brain):
    brain("alpha: {root: ., parent: pro}\nbeta: {root: ../beta, parent: pro}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    names = scopes.select("pro", brain.root)[1]
    data = status.run([projects.load(brain.root)[n] for n in names], every=True, quick=True)
    assert [p["project"] for p in data["projects"]] == ["alpha", "beta"] and "total" in data


def test_sync_writes_the_view_and_the_registry_check_reads_the_tree(brain, monkeypatch, capsys):
    brain("alpha: {root: ., parent: finance}\nbeta: {root: ../beta}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    assert scopes.view_applies(brain.root) and scopes.view_stale(brain.root)
    assert scopes.write_view(brain.root) and not scopes.write_view(brain.root)
    text = (brain.root / scopes.VIEW).read_text(encoding="utf-8")
    assert text.startswith("# Scope tree\n") and "| `sphere` | Sphere | Sphère | 2 |" in text
    assert not scopes.view_stale(brain.root)
    _tree(brain.root, TREE + "  ops: {type: team, parent: nowhere}\n")
    assert _stores._scopes_check(brain.root) == [
        "scopes: scope ops: its parent 'nowhere' is no node (a container of scopes.yaml, a project, or global)"]
    _tree(brain.root, TREE + "  ops: {type: team, parent: home}\n")
    assert _stores._scopes_check(brain.root) == []
    assert "warning: scopes: notes/scopes_graph.md is stale (brain sync writes it)" in capsys.readouterr().out


def test_classes_reads_the_tree_through_brain_scopes(brain, monkeypatch, tmp_path):
    from brain import classes
    _tree(brain.root)
    cfg = config.load(brain.root)
    assert classes.scopes_file(cfg) == brain.root / scopes.FILE
    assert set(classes.scope_nodes(cfg)) == {"pro", "home", "acme", "finance"}
    other = tmp_path / "elsewhere.yaml"
    other.write_text("v: 1\nscopes:\n  solo: {type: folder}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_SCOPES", str(other))
    assert set(scopes.load(brain.root).nodes) == {"alpha", "beta", "gamma", "solo"}
    (brain.root / scopes.FILE).write_text("v: [", encoding="utf-8")
    monkeypatch.delenv("BRAIN_SCOPES")
    errors, _ = scopes.check(brain.root)
    assert errors and errors[0].startswith("scopes.yaml: not readable YAML")
    assert classes.scope_nodes(config.load(brain.root)) == {}
