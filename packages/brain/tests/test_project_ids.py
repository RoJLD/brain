"""Project ids, the doctrine (brain.projectids; spec-brain-project-ids ID-1 to ID-3): a registry key is the project's
id, frozen at birth; aliases resolve to it with a notice; a project that ended is a tombstone no command loads; ids
and aliases are one namespace across projects and containers, never reused; a private project's other names are as
private as its id; no code reads a project from a node id. Fictitious names only."""

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from brain import cli, config, denylist, guards, project_add, projectids, projects, schema, scopes
from brain.commands import _stores

TREE = "v: 1\nscopes:\n  pro: {type: sphere, title: Professional, aliases: [work]}\n" \
       "  acme: {type: company, title: ACME SA, parent: pro, classes: {floor: private}}\n"


@pytest.fixture
def brain(tmp_path, monkeypatch, store):
    """A brain at tmp_path/root: alpha (its own root), orchard beside it; config.json; no scopes.yaml until a test
    writes one. Returns a writer of the registry."""
    root = store.parent.parent
    shutil.copytree(store, tmp_path / "orchard" / "notes" / "graph")
    (root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.delenv("BRAIN_SCOPES", raising=False)
    monkeypatch.delenv("BRAIN_STRICT", raising=False)
    monkeypatch.delenv("CI", raising=False)

    def registry(text: str) -> None:
        (root / "projects.yaml").write_text(text, encoding="utf-8")

    registry("alpha: {root: .}\norchard: {root: ../orchard, title: The orchard, aliases: [old-orchard, grove], "
             "label: Orchard}\n")
    registry.root = root
    return registry


def _errors(root):
    return projects.check(root) + scopes.check(root)[0]


# --- the keys, documented ---

def test_the_identity_keys_are_documented_by_brain_projects_keys(brain, capsys):
    assert {"aliases", "label", "status"} <= set(projects.KEYS)
    assert cli.main(["projects", "--keys"]) == 0
    out = capsys.readouterr().out
    for key in ("aliases", "label", "status"):
        assert re.search(rf"^\s*{key}\b", out, re.M), key
    assert "became-process" in out and "never reused" in out


def test_a_registry_without_the_new_keys_reads_as_before(brain, capsys):
    """The registry as the previous release wrote it: no identity key, every check silent, every project loaded."""
    brain("alpha: {root: .}\norchard: {root: ../orchard, title: The orchard}\nupstream: {access: read}\n")
    assert _errors(brain.root) == [] and scopes.check(brain.root)[1] == []
    assert list(projects.load()) == ["alpha", "orchard"] and projects.tombstones() == {}
    assert cli.main(["projects", "--json"]) == 0
    data = {d["name"]: d for d in json.loads(capsys.readouterr().out)["projects"]}
    assert data["orchard"]["aliases"] == [] and data["orchard"]["label"] == "" and data["orchard"]["status"] == "active"


# --- --project and scope references resolve an alias, with a notice ---

def test_project_by_alias_runs_as_its_id_with_a_notice(brain, capsys):
    assert cli.main(["projects", "--project", "old-orchard", "--json"]) == 0
    got = capsys.readouterr()
    assert [d["name"] for d in json.loads(got.out)["projects"]] == ["orchard"]
    assert "'old-orchard' is an alias of 'orchard'" in got.err and "running as orchard" in got.err
    assert cli.main(["--project", "grove", "projects"]) == 0   # before the subcommand too
    got = capsys.readouterr()
    assert got.out.startswith("orchard (") and "label" in got.out and "old-orchard, grove" in got.out
    assert "'grove' is an alias of 'orchard'" in got.err
    assert projects.get("grove").name == "orchard"   # a caller of get() too
    with pytest.raises(SystemExit, match="unknown project 'nowhere'"):
        cli.main(["projects", "--project", "nowhere"])


def test_a_scope_reference_resolves_an_alias_of_a_project_or_a_container(brain, capsys):
    brain("alpha: {root: .}\norchard: {root: ../orchard, parent: acme, aliases: [grove]}\n")
    (brain.root / scopes.FILE).write_text(TREE, encoding="utf-8")
    tree = scopes.load(brain.root)
    assert tree.aliases == {"work": "pro", "grove": "orchard"}
    assert scopes.resolve(tree, "grove") == "orchard"
    assert scopes.resolve(tree, "work") == "pro"
    assert scopes.resolve(tree, "work/acme/grove") == "orchard"   # a path of ids, each part an alias or an id
    err = capsys.readouterr().err
    assert "--scope grove: 'grove' is an alias of 'orchard'" in err and "'work' is an alias of 'pro'" in err
    assert scopes.select("work", brain.root) == ("pro", ["orchard"])
    with pytest.raises(scopes.ScopeError):
        scopes.resolve(tree, "nowhere")


def test_parent_names_an_id_never_an_alias(brain):
    brain("alpha: {root: .}\norchard: {root: ../orchard, parent: work}\n")
    (brain.root / scopes.FILE).write_text(TREE, encoding="utf-8")
    assert any("its parent 'work' is no node" in e and "an alias of pro, and parent: names an id" in e
               for e in scopes.check(brain.root)[0])


# --- one namespace: an id or an alias is never reused ---

@pytest.mark.parametrize("text,needle", [
    ("alpha: {root: .}\norchard: {root: ../orchard, aliases: [alpha]}\n",
     "project orchard: alias 'alpha' is project alpha already: an id or an alias is never reused"),
    ("alpha: {root: ., aliases: [grove]}\norchard: {root: ../orchard, aliases: [grove]}\n",
     "project orchard: alias 'grove' is an alias of project alpha already"),
    ("alpha: {root: .}\norchard: {root: ../orchard, aliases: [orchard]}\n", "alias 'orchard' is its own id"),
    ("alpha: {root: .}\norchard: {root: ../orchard, aliases: [grove, grove]}\n", "alias 'grove' is listed twice"),
    ("alpha: {root: .}\norchard: {root: ../orchard, aliases: grove}\n", "aliases is a list of names"),
    ("alpha: {root: .}\norchard: {root: ../orchard, aliases: [Grove]}\n", "alias 'Grove' is not kebab-case"),
    ("alpha: {root: .}\norchard: {root: ../orchard, aliases: [global]}\n", "alias 'global' is the tree's root"),
    ("alpha: {root: .}\norchard: {root: ../orchard, aliases: [pro]}\n", "alias 'pro' is scope pro already"),
    ("alpha: {root: ., aliases: [work]}\norchard: {root: ../orchard}\n", "scope pro: alias 'work' is an alias of project alpha already"),   # either side: one namespace
    ("alpha: {root: .}\norchard: {root: ../orchard, label: [x]}\n", "label is one line of text"),
    ("alpha: {root: .}\nold: {status: merged, aliases: [grove]}\norchard: {root: ../orchard, aliases: [old]}\n",
     "alias 'old' is project old already"),   # a tombstone's id is reserved for ever
])
def test_check_refuses_a_reused_id_or_alias(brain, text, needle):
    brain(text)
    (brain.root / scopes.FILE).write_text(TREE, encoding="utf-8")
    errors = _errors(brain.root)
    assert any(needle in e for e in errors), errors
    assert any(needle in e for e in _stores._scopes_check(brain.root)), "brain check --all prints scopes: errors"


def test_two_aliases_of_one_name_resolve_to_none(brain, capsys):
    """Never a guess between two projects: an alias two nodes declare names neither."""
    brain("alpha: {root: ., aliases: [grove]}\norchard: {root: ../orchard, aliases: [grove]}\n")
    assert projectids.alias_map(projects.raw()) == {}
    with pytest.raises(SystemExit, match="unknown project 'grove'"):
        cli.main(["projects", "--project", "grove"])


def test_an_id_that_is_not_kebab_case_is_a_warning_never_an_error(brain):
    brain("alpha: {root: .}\nOrchard_1: {root: ../orchard}\n")
    errors, warnings = scopes.check(brain.root)
    assert not any("Orchard_1" in e for e in errors)
    assert any("project Orchard_1: its id is not kebab-case" in w and "frozen" in w for w in warnings)


def _ids_strict(root, on):
    """config.json projects.ids_strict: absent (None), false or true."""
    data = {"v": 1, "identity": {"owner": "Ada"}}
    if on is not None:
        data["projects"] = {"ids_strict": on}
    (root / config.FILE).write_text(json.dumps(data), encoding="utf-8")


def test_brain_project_add_never_mints_a_name_in_use(brain, tmp_path):
    """Under config.json projects.ids_strict."""
    (brain.root / scopes.FILE).write_text(TREE, encoding="utf-8")
    _ids_strict(brain.root, True)
    cfg = config.load(brain.root)
    registry = brain.root / "projects.yaml"
    for name, why in (("grove", "is an alias of project orchard already"), ("work", "is an alias of scope pro"),
                      ("x", "kebab-case from a letter"), ("a" * 41, "2 to 40 characters")):
        with pytest.raises(project_add.AddError, match=why):
            project_add._check_name(name, registry, cfg)
    project_add._check_name("fresh-one", registry, cfg)   # a name no node holds passes


@pytest.mark.parametrize("on", [None, False])
def test_brain_project_add_takes_0_5_1_s_names_without_the_key(brain, tmp_path, on):
    """config.json projects.ids_strict absent or false: the name rule takes a kebab-case name from a letter of any
    length, as 0.5.1; a registered name, a container's id, the tree's root and a name that is not kebab-case are still
    refused. A name another node holds as an alias passes this rule but not the command: the entry would add an error
    to brain check --all, which refuses the write (test_project_add)."""
    (brain.root / scopes.FILE).write_text(TREE, encoding="utf-8")
    _ids_strict(brain.root, on)
    cfg = config.load(brain.root)
    registry = brain.root / "projects.yaml"
    for name in ("x", "a" * 41, "grove", "work"):
        project_add._check_name(name, registry, cfg)
    for name, why in (("alpha", "registered already"), ("acme", "a container of the scope tree"),
                      ("global", "the tree's root"), ("Orchard_1", "kebab-case from a letter"),
                      ("1abc", "kebab-case from a letter")):
        with pytest.raises(project_add.AddError, match=why):
            project_add._check_name(name, registry, cfg)


def test_an_unreadable_config_leaves_the_ids_rule_off(brain, tmp_path):
    (brain.root / config.FILE).write_text("{not json", encoding="utf-8")
    project_add._check_name("a" * 41, brain.root / "projects.yaml", config.load(brain.root))


# --- a tombstone: a project that ended ---

def test_a_tombstone_is_never_loaded_and_says_why(brain, capsys):
    brain("alpha: {root: .}\norchard: {root: ../orchard}\nold-lab: {title: a lab merged into orchard, status: merged, "
          "aliases: [lab], label: Lab, parent: orchard}\n")
    assert list(projects.load()) == ["alpha", "orchard"]
    assert projects.tombstones() == {"old-lab": "merged"} and list(projects.readonly()) == []
    assert _errors(brain.root) == []
    with pytest.raises(SystemExit, match=r"'old-lab' is a tombstone \(status merged\)"):
        projects.get("old-lab")
    with pytest.raises(SystemExit, match="is a tombstone"):
        cli.main(["status", "--project", "lab", "--quick"])   # an alias of a tombstone resolves, and is refused
    assert "'lab' is an alias of 'old-lab'" in capsys.readouterr().err
    tree = scopes.load(brain.root)
    assert tree.nodes["old-lab"].kind == "tombstone" and tree.nodes["old-lab"].status == "archived"
    assert "old-lab (Project, ended: merged)" in "\n".join(scopes.render(tree, archived=True))
    assert cli.main(["projects", "--json"]) == 0
    data = {d["name"]: d for d in json.loads(capsys.readouterr().out)["projects"]}
    assert data["old-lab"] == {"name": "old-lab", "title": "a lab merged into orchard", "access": "none",
                               "status": "merged", "aliases": ["lab"], "label": "Lab"}
    assert cli.main(["projects"]) == 0
    assert "old-lab (tombstone, merged: the project ended, no command loads it)" in capsys.readouterr().out


def test_check_refuses_a_tombstone_with_live_keys_and_keeps_its_guards(brain, tmp_path):
    lab = tmp_path / "lab"
    lab.mkdir()
    brain("alpha: {root: .}\nold-lab: {root: ../lab, stores: [notes/graph], production: [.], status: archived}\n")
    errors = projects.check()
    assert any("project old-lab: a tombstone (status archived) holds" in e and "not production, root, stores" in e
               for e in errors), errors
    assert "old-lab" not in projects.load()
    # fail closed: a project that ended but still names a production checkout keeps it refused to edits
    assert any(p.name == "old-lab" for p in projects.guarded())
    roots = {os.path.normcase(os.path.abspath(r)) for r in guards.production_roots()}
    assert os.path.normcase(str(lab.resolve())) in roots


def test_an_unknown_status_is_a_note_never_a_live_project(brain, capsys, monkeypatch):
    brain("alpha: {root: .}\nlater: {status: frozen-solid, title: a newer brain's status}\n")
    assert projects.check() == []   # read mode: a newer brain's value, noted
    assert "status 'frozen-solid' is not one of" in capsys.readouterr().err
    assert "later" not in projects.load()   # the key narrows: never read as a live project
    with pytest.raises(SystemExit, match="its status 'frozen-solid' is not one this engine knows"):
        projects.get("later")
    monkeypatch.setenv("BRAIN_STRICT", "1")
    assert schema.mode() == schema.STRICT
    assert any("status 'frozen-solid' is not one of" in e for e in projects.check())
    brain("alpha: {root: .}\nodd: {status: 3}\nfine: {root: ../orchard, status: active}\n")
    errors = projects.check()
    assert any("project odd: status is one of active" in e for e in errors)
    assert "fine" in projects.load()   # status: active, said, is a live project


# --- private stays private ---

def test_a_private_projects_aliases_and_label_join_the_deny_terms(brain):
    brain("alpha: {root: .}\norchard: {root: ../orchard, parent: acme, aliases: [old-orchard], label: Green Grove}\n"
          "old-lab: {status: merged, parent: acme, aliases: [lab-one]}\n")
    (brain.root / scopes.FILE).write_text(TREE, encoding="utf-8")
    data = {"v": 1, "identity": {"owner": "Ada"},
            "public": {"deny": {"people": ["Ada"]}, "derive": [], "deny_from_tree": True}}
    (brain.root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
    cfg = config.load(brain.root)
    terms = scopes.private_terms(cfg)
    for t in ("orchard", "old-orchard", "Green Grove", "old-lab", "lab-one"):
        assert t in terms, (t, terms)
    assert scopes.deny_unexpected(cfg) == ""


def test_the_derived_deny_feed_names_aliases_labels_and_tombstones(brain):
    brain("alpha: {root: ., aliases: [own-old]}\norchard: {root: ../orchard, aliases: [old-orchard], label: Grove}\n"
          "upstream: {access: read, aliases: [up-old]}\nold-lab: {status: archived, aliases: [lab-one]}\n")
    data = {"v": 1, "identity": {"owner": "Ada"}, "public": {"repos": ["someone/engine"], "derive": ["projects"]}}
    (brain.root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
    got = [t for _, t in denylist.declared(config.load(brain.root), ("projects",))]
    for t in ("orchard", "old-orchard", "Grove", "upstream", "up-old", "old-lab", "lab-one"):
        assert t in got, (t, got)
    assert "alpha" not in got and "own-old" not in got   # the brain's own root gives its repos, not its names


# --- a repo's name: is its frozen id ---

def test_a_repo_named_after_its_folder_while_its_ids_name_another_is_warned(brain, capsys):
    nodes = brain.root / "notes" / "graph" / "nodes"
    (nodes / "_generated_docs.yaml").write_text(
        '- {id: "doc:first-home:docs/a.md::top", type: Doc, status: active}\n'
        '- {id: "code:first-home:src/a.py", type: CodeRef, status: active}\n', encoding="utf-8")
    brain("alpha: {root: .}\n")
    warns = projectids.repo_name_warnings(list(projects.load().values()))
    assert warns == [f"project alpha: its repo . has no name: and is named after its folder (root), while its graph's "
                     "ids name first-home: a clone in another folder? give the repo name: <the name its ids use> (a "
                     "repo's name is its frozen id)"]
    _stores.check_registry(None, list(projects.load().values()))
    assert "warning: project alpha: its repo . has no name:" in capsys.readouterr().out
    brain("alpha: {root: ., repos: [{path: ., name: first-home}]}\n")   # pinned: the ids resolve, nothing to say
    assert projectids.repo_name_warnings(list(projects.load().values())) == []
    brain("alpha: {root: ., repos: [{path: ., name: elsewhere}]}\n")   # named, wrongly: not this warning's case
    assert projectids.repo_name_warnings(list(projects.load().values())) == []


# --- ID-3: a node id is a birth mark, never read back ---

SRC = Path(projects.__file__).resolve().parent
RG = SRC.parents[3] / "src" / "research_graph"   # the repo's other package (src/research_graph)
# what reading a project out of a node id looks like: the second dash-separated part of an id, or a regex that captures
# the segment after a node type's prefix
READS_PROJECT = [
    re.compile(r"""\.split\(\s*['"]-['"]\s*(?:,\s*\d+\s*)?\)\s*\[\s*1\s*\]"""),
    re.compile(r"""\.partition\(\s*['"]-['"]\s*\)\s*\[\s*2\s*\]\s*\.partition"""),
    re.compile(r"""(?:wi|spec|feat|ms|les|era)-\((?:\?P<\w+>)?\[?[a-z]"""),
]


def _reads_project(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if any(p.search(line) for p in READS_PROJECT)]


def test_no_engine_code_reads_a_project_from_a_node_id():
    assert _reads_project('project = node["id"].split("-")[1]') != []   # the scan sees what it looks for
    assert _reads_project('m = re.match(r"wi-(?P<project>[a-z0-9]+)-", nid)') != []
    assert _reads_project('short = nid.removeprefix("wi-").removeprefix(p.name + "-")') == []   # a display strip
    hits = {}
    assert SRC.is_dir() and RG.is_dir(), "both packages are scanned, never skipped silently"
    for base in (SRC, RG):
        for f in base.rglob("*.py") if base.is_dir() else []:
            found = _reads_project(f.read_text(encoding="utf-8", errors="replace"))
            if found:
                hits[f.name] = found
    assert hits == {}, "a node id is a birth mark (ID-3): read the project from the store, never from the id"


def test_an_item_whose_slug_names_another_project_is_read_by_its_store(brain, capsys):
    """A project whose store holds items born elsewhere (wi-elsewhere-...) reads them as its own."""
    store = brain.root.parent / "orchard" / "notes" / "graph"
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as fh:
        fh.write('- {id: wi-elsewhere-thing, type: WorkItem, status: todo, title: "Born elsewhere"}\n')
    assert cli.main(["item", "show", "wi-elsewhere-thing", "--project", "orchard"]) == 0
    assert "Born elsewhere" in capsys.readouterr().out


# --- the review's cases: a typo never shrinks the deny list, an old name keeps its floor ---

@pytest.mark.parametrize("fault", ["status: actve", "status: archived", "access: raed"])
def test_a_typo_or_a_tombstone_with_live_keys_never_shrinks_the_deny_terms(brain, tmp_path, fault):
    """A private project whose entry is skipped (an unknown status, a tombstone that still names its repos, an access
    typo) keeps its repos' names denied, in the tree's feed and the derived one: fail closed."""
    (tmp_path / "secret-repo").mkdir()
    entry = "{root: ../secret-repo, parent: acme, repos: [{path: ., name: hidden-name}]"
    brain("alpha: {root: .}\norchard: " + entry + "}\n")
    (brain.root / scopes.FILE).write_text(TREE, encoding="utf-8")
    data = {"v": 1, "identity": {"owner": "Ada"}, "public": {"deny": {"people": ["Ada"]}, "derive": ["projects"],
                                                             "deny_from_tree": True}}
    (brain.root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
    cfg = config.load(brain.root)
    before_tree = scopes.private_terms(cfg)
    before_derived = [t for _, t in denylist.declared(cfg, ("projects",))]
    assert {"hidden-name", "secret-repo", "orchard"} <= set(before_tree)
    brain("alpha: {root: .}\norchard: " + entry + ", " + fault + "}\n")
    assert "orchard" not in projects.load()
    assert set(before_tree) <= set(scopes.private_terms(cfg))
    assert set(before_derived) <= {t for _, t in denylist.declared(cfg, ("projects",))}


def test_a_stores_old_project_name_keeps_its_class_floor(brain):
    from brain import classes
    brain("alpha: {root: .}\norchard: {root: ../orchard, parent: acme, aliases: [grove]}\n")
    (brain.root / scopes.FILE).write_text(TREE, encoding="utf-8")
    cfg = config.load(brain.root)
    assert classes.floor(cfg, "grove") == classes.floor(cfg, "orchard") == ("private", "acme")
    assert classes.scope_chain(cfg, "grove") == ["acme", "pro"]


def test_project_never_resolves_a_containers_id_or_alias(brain, capsys):
    brain("alpha: {root: .}\norchard: {root: ../orchard, aliases: [grove, pro-old]}\n")
    (brain.root / scopes.FILE).write_text(TREE.replace("aliases: [work]", "aliases: [grove]"), encoding="utf-8")
    assert projectids.canonical("grove") == "grove"   # two nodes declare it: none
    assert projectids.canonical("pro") == "pro"   # a container's id
    assert projectids.canonical("pro-old") == "orchard" and "is an alias of 'orchard'" in capsys.readouterr().err


def test_a_notes_home_with_a_status_is_no_tombstone(brain):
    brain("alpha: {root: .}\nnotes: {kind: knowledge, root: ../notes, status: archived}\n")
    assert projects.tombstones() == {} and "notes" in projects.knowledge()
    assert any("project notes: a notes home holds" in e and "status" in e for e in projects.check())


def test_the_reference_registry_leaves_a_tombstone_out(brain):
    from brain import arc42
    got = arc42.registry({"alpha": {"root": "."}, "old-lab": {"status": "merged", "access": "read"},
                          "up": {"access": "read"}})
    assert list(got) == ["alpha", "up"] and got["up"]["access"] == "read"
