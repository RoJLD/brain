"""The scope tree as data (brain.scopes, wi-brain-scope-tree; spec-brain-scope-tree 3.1, 3.2, 3.13): parent: in the
registry, the containers of scopes.yaml, the type catalogue, brain check's rules, brain scopes, --scope on status, the
generated view; a brain without a tree stays flat under Global. Fictitious names only."""

import json
import shutil

import pytest

from brain import cli, config, projects, scopes
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


def test_status_scope_on_a_multi_project_node_adds_the_totals(brain, capsys):
    brain("alpha: {root: ., parent: pro}\nbeta: {root: ../beta, parent: pro}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    assert cli.main(["--root", str(brain.root), "status", "--scope", "pro", "--quick", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
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
    cfg = config.load(brain.root)
    with pytest.raises(classes.ClassError, match="cannot be read"):   # fail closed: no floor or recipient dropped
        classes.scope_nodes(cfg)
    from brain import vault
    store = classes.Store("repo", "private", project="alpha")
    with pytest.raises(vault.VaultError, match="not readable YAML"):
        vault.for_store(cfg, store)   # never sealed to the root's recipients alone


def test_a_sub_project_inherits_the_floor_above_its_parent(brain):
    from brain import classes
    brain("alpha: {root: ., parent: acme}\nbeta: {root: ../beta, parent: alpha}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    cfg = config.load(brain.root)
    assert classes.scope_chain(cfg, "beta") == ["alpha", "acme", "pro"]
    assert classes.floor(cfg, "beta") == ("confidential", "acme") == scopes.floor(scopes.load(brain.root), "beta")


def test_a_project_named_global_is_refused_and_never_loops(brain, capsys):
    brain("global: {root: .}\nbeta: {root: ../beta}\n")
    tree = scopes.load(brain.root)
    assert "global" not in tree.nodes and scopes.render(tree)[0] == "Global (1 project)"
    errors, _ = scopes.check(brain.root)
    assert errors == ["project global: global is the root of the scope tree, the brain itself: rename the project"]


def test_dotdot_under_an_unknown_parent_is_a_clean_refusal(brain):
    brain("alpha: {root: ., parent: typo}\nbeta: {root: ../beta}\n")
    with pytest.raises(SystemExit, match="the parent of alpha, 'typo', is no node"):
        cli.main(["--root", str(brain.root), "status", "--scope", "..", "--quick"])


def test_archived_subtrees_are_left_out_of_the_counts_unless_asked(brain, capsys):
    brain("alpha: {root: ., parent: old}\nbeta: {root: ../beta}\n")
    _tree(brain.root, TREE + "  old: {type: folder, status: archived}\n")
    tree = scopes.load(brain.root)
    assert scopes.render(tree)[0] == "Global (1 project)"
    assert scopes.render(tree, archived=True)[0] == "Global (2 projects)"
    assert cli.main(["--root", str(brain.root), "scopes", "--scope", "old", "--json"]) == 0
    assert [n["id"] for n in json.loads(capsys.readouterr().out)["nodes"]] == ["old", "alpha"]   # named: shown


def _config(root, **public):
    data = {"v": 1, "identity": {"owner": "Ada"}, "public": {"deny": {"people": ["Ada"], "repos": ["handmade"],
                                                                     "paths": ["E:/Work"]}, **public}}
    (root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
    return config.load(root)


def test_deny_from_tree_is_off_by_default(brain):
    brain("alpha: {root: ., parent: acme}\nbeta: {root: ../beta}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    cfg = _config(brain.root)
    assert config.deny_terms(cfg) == [("people", "Ada"), ("repos", "handmade"), ("paths", "E:/Work")]
    assert config.unexpected(cfg) == "" and config.describe(cfg)["deny_from_tree"] is False


def test_deny_from_tree_adds_the_private_subtree_and_its_repos(brain):
    brain("alpha: {root: ., parent: finance}\nbeta: {root: ../beta, parent: alpha}\n"
          "gamma: {root: ../gamma, parent: pro}\nupstream: {title: an upstream, access: read, parent: acme}\n"
          "handmade: {root: ../beta, parent: acme}\n")
    _tree(brain.root, TREE + "  open: {type: folder, classes: {floor: public}}\n")
    cfg = _config(brain.root, deny_from_tree=True, repos=["someone/root"])
    assert scopes.private_nodes(scopes.load(brain.root)) == ["alpha", "beta", "upstream", "handmade"]
    # alpha's repo is its root's folder, root: a public repo of public.repos, left out; beta's folder is beta
    assert scopes.private_terms(cfg) == ["alpha", "beta", "handmade", "upstream"]
    assert config.deny_terms(cfg) == [("people", "Ada"), ("repos", "handmade"), ("repos", "alpha"), ("repos", "beta"),
                                      ("repos", "upstream"), ("paths", "E:/Work")]   # gamma (pro: no floor) is not
    assert config.check(brain.root) == [] and config.describe(cfg)["deny"]["repos"] == 4
    from brain import public
    assert public.rules_hash(cfg) != public.rules_hash(_config(brain.root, repos=["someone/root"]))


def test_a_newly_placed_private_project_is_denied_without_a_hand_edit(brain):
    brain("alpha: {root: .}\nbeta: {root: ../beta}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    cfg = _config(brain.root, deny_from_tree=True)
    assert scopes.private_terms(cfg) == []
    brain("alpha: {root: .}\nbeta: {root: ../beta}\ngamma: {root: ../gamma, parent: acme}\n")
    assert scopes.private_terms(cfg) == ["gamma"]


def test_an_unreadable_tree_makes_the_guards_refuse_when_generation_is_on(brain):
    (brain.root / scopes.FILE).write_text("v: [", encoding="utf-8")
    assert config.unexpected(_config(brain.root)) == ""   # off: the hand list alone, as before
    why = config.unexpected(_config(brain.root, deny_from_tree=True))
    assert why.startswith("scopes.yaml: not readable YAML") and "cannot generate the deny list" in why
    assert "true or false" in config.unexpected(_config(brain.root, deny_from_tree="yes"))


def test_brain_scopes_deny_lists_the_generated_terms(brain, capsys):
    brain("alpha: {root: .}\nbeta: {root: ../beta, parent: acme}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    _config(brain.root)
    assert cli.main(["--root", str(brain.root), "scopes", "--deny"]) == 0
    assert capsys.readouterr().out == ("deny from the tree: off (config.json public.deny_from_tree); 1 term(s) for "
                                       "public.deny.repos: beta\n")
    _config(brain.root, deny_from_tree=True)
    assert cli.main(["--root", str(brain.root), "scopes", "--deny", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"deny_from_tree": True, "repos": ["beta"]}


def test_a_repo_that_cannot_be_resolved_keeps_the_name_and_case_counts_once(brain, monkeypatch):
    brain("alpha: {root: .}\nbeta: {root: ../beta, parent: acme}\ngamma: {root: ../gamma, parent: acme}\n")
    _tree(brain.root)
    cfg = _config(brain.root, deny_from_tree=True)

    def repos_of(p):
        if p.name == "beta":   # a production checkout on another drive: os.path.relpath raises
            raise ValueError("path is on mount 'E:', start on mount 'C:'")
        return [projects.Repo("gamma", p.root, folder="Gamma"), projects.Repo("svc", p.root, folder="SVC")]
    monkeypatch.setattr(projects, "repos_of", repos_of)
    assert scopes.private_terms(cfg) == ["beta", "gamma", "svc"]   # never raised into the guard; once each
    assert config.unexpected(cfg) == ""


@pytest.mark.parametrize("case, want", [
    ("floor", "the scope tree has 1 error(s), the first: scope acme: classes.floor is one of"),
    ("parent", "the scope tree has 1 error(s), the first: project beta: its parent 'acmee' is no node"),
    ("named", "does not exist: public.deny_from_tree cannot generate the deny list"),
    ("none", "no scope tree (scopes.yaml or a parent: in projects.yaml)"),
    ("list", "projects.yaml is a list, not a mapping"),
    ("raises", "the deny list could not be generated (RuntimeError: boom)"),
])
def test_generation_on_refuses_whatever_would_make_the_list_miss_terms(brain, monkeypatch, case, want):
    brain("alpha: {root: .}\nbeta: {root: ../beta, parent: acme}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    cfg = _config(brain.root, deny_from_tree=True)
    assert config.unexpected(cfg) == ""
    if case == "floor":
        _tree(brain.root, TREE.replace("floor: confidential", "floor: Private"))
    elif case == "parent":
        brain("alpha: {root: .}\nbeta: {root: ../beta, parent: acmee}\ngamma: {root: ../gamma}\n")
    elif case == "named":
        monkeypatch.setenv("BRAIN_SCOPES", str(brain.root / "moved.yaml"))
    elif case == "none":
        (brain.root / scopes.FILE).unlink()
        brain("alpha: {root: .}\nbeta: {root: ../beta}\ngamma: {root: ../gamma}\n")
    elif case == "list":
        (brain.root / "projects.yaml").write_text("- alpha\n", encoding="utf-8")
    else:
        monkeypatch.setattr(scopes, "private_terms", lambda cfg: (_ for _ in ()).throw(RuntimeError("boom")))
    assert want in config.unexpected(config.load(brain.root))
    assert config.unexpected(_config(brain.root)) == ""   # off: the hand list alone, nothing refused


def test_a_project_marked_private_on_its_own_entry_is_denied(brain):
    """DENY-1, the owner's answer: a class floor on the project entry, read-only entries and mounts too."""
    brain("alpha: {root: .}\nbeta: {root: ../beta, classes: {floor: private}}\ngamma: {root: ../gamma}\n"
          "upstream: {title: an upstream, access: read, classes: {floor: confidential}}\n"
          "team: {title: hosted, tenant: {}, classes: {floor: public}}\n")
    assert projects.check(brain.root) == []
    assert scopes.check(brain.root) == ([], [])   # parent: is not needed: the floor is the node's own
    cfg = _config(brain.root, deny_from_tree=True)
    assert scopes.private_terms(cfg) == ["beta", "upstream"]
    assert config.unexpected(cfg) == ""


def test_a_project_floor_binds_its_stores_and_never_loosens_its_container(brain):
    from brain import classes
    brain("alpha: {root: .}\nbeta: {root: ../beta, parent: acme, classes: {floor: private}}\n"
          "gamma: {root: ../gamma, classes: {floor: sealed}}\n")
    _tree(brain.root)
    errors, _ = scopes.check(brain.root)
    assert errors == ["project beta: its class floor private is under confidential, the floor acme sets above it: "
                      "a guard only tightens going down (remove it, or raise it)"]
    cfg = config.load(brain.root)
    assert classes.floor(cfg, "gamma") == ("sealed", "gamma") and classes.floor(cfg, "beta") == ("confidential", "acme")
    brain("alpha: {root: .}\nbeta: {root: ../beta, classes: {floor: Private}}\ngamma: {root: ../gamma}\n")
    assert scopes.check(brain.root)[0] == ["project beta: classes.floor is one of public, private, confidential, "
                                           "sealed, resident, secret, not 'Private'"]
