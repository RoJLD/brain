"""The deny terms derived from the brain's own registries (wi-brain-public-deny-derived, brain.denylist): a machine,
a person, a project, a spec or a module is refused by the public check the day it is declared, in every spelling."""

import json

import pytest
from brain import boundary, cli, config, denylist, guards, public
from conftest import run_git

MODULES = """\
- {id: D7, name: graph-core, brick: D}
- {id: OPS-RUNNER, name: night-runner, brick: O}
"""


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """Ada's brain: config.json (hosts, identity, public repos), members.yaml, a registry of two projects and a
    read-only one, two specs and a module registry; returns a writer of config.json's public block."""
    root = tmp_path / "ada-brain"
    (root / "notes" / "graph").mkdir(parents=True)
    (root / "notes" / "graph" / "schema.yaml").write_text("owner: Ada\nnode_types: [WorkItem]\n", encoding="utf-8")
    (root / "notes" / "graph" / "modules.yaml").write_text(MODULES, encoding="utf-8")
    (root / "docs" / "specs").mkdir(parents=True)
    (root / "docs" / "specs" / "2026-01-02-orchard-design.md").write_text("# Orchard\n", encoding="utf-8")
    (root / "members.yaml").write_text("v: 1\npeople:\n- {person_id: bertha, name: Bertha Quill}\n", encoding="utf-8")
    (tmp_path / "lab-repo").mkdir()
    (root / "projects.yaml").write_text(
        "ada-brain: {root: .}\nmoonshot: {root: ../lab-repo}\nupstream-tool: {access: read, title: a tool}\n",
        encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))

    def write(**public):
        data = {"v": 1, "identity": {"owner": "Ada", "display_name": "Ada L."},
                "hosts": {"kestrel": {"aliases": ["kestrel-wsl"]}, "x1": {}},
                "public": {"repos": ["acme/engine"], "deny": {"people": ["Ada"]}, **public}}
        (root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
        return config.load(root)
    write.root = root
    return write


def test_each_registry_gives_its_names(brain):
    cfg = brain()
    got = denylist.declared(cfg)
    by = {src: [t for s, t in got if s == src] for src in denylist.SOURCES}
    assert by["hosts"] == ["kestrel", "kestrel-wsl"]   # x1: shorter than 3, never derived
    assert by["people"] == ["Ada", "Ada L.", "Bertha Quill", "bertha"]
    # the brain's own project gives its repo (its folder), not its name; a repo by its folder too
    assert by["projects"] == ["moonshot", "upstream-tool", "ada-brain", "lab-repo"]
    assert by["specs"] == ["2026-01-02-orchard-design"]
    assert by["modules"] == ["graph-core", "night-runner", "OPS-RUNNER"]   # D7: a short code, not derived
    # each joins its category after the hand list, none twice whatever its case (Ada is the hand list's)
    terms = config.deny_terms(cfg)
    assert terms[:3] == [("people", "Ada"), ("people", "Ada L."), ("people", "Bertha Quill")]
    assert ("hosts", "kestrel-wsl") in terms and ("repos", "moonshot") in terms and ("repos", "graph-core") in terms
    assert ("paths", "2026-01-02-orchard-design") in terms
    assert sum(1 for _, t in terms if t.lower() == "ada") == 1


def test_public_names_and_public_repos_are_never_derived(brain):
    cfg = brain(repos=["acme/ada-brain"], public_names={"upstream-tool": "a third-party tool, public upstream"})
    names = {t for _, t in denylist.declared(cfg)}
    assert "ada-brain" not in names and "upstream-tool" not in names   # the public repo's name, a public name
    assert "moonshot" in names and config.describe(cfg)["public_names"] == ["upstream-tool"]


def test_derive_picks_the_sources_and_brain_check_warns_about_the_rest(brain, capsys):
    cfg = brain(derive=["hosts"])
    assert {c for c, _ in denylist.terms(cfg)} == {"hosts"} and config.describe(cfg)["derive"] == ["hosts"]
    lines = denylist.check_lines(brain.root)
    assert any("the projects name 'moonshot' is in no deny list" in x for x in lines)
    assert not any("'kestrel'" in x for x in lines) and not any("'Ada'" in x for x in lines)   # derived, by hand
    assert cli.main(["--root", str(brain.root), "check", "--all"]) in (0, 1)
    assert "warning: public: the specs name '2026-01-02-orchard-design' is in no deny list" in capsys.readouterr().out
    brain(derive=[])
    assert denylist.terms(config.load(brain.root)) == []
    brain()
    assert denylist.check_lines(brain.root) == []   # every source derived: nothing left undenied
    (brain.root / config.FILE).write_text(json.dumps({"v": 1, "public": {"derive": []}}), encoding="utf-8")
    assert denylist.check_lines(brain.root) == []   # a brain that publishes nothing is not concerned


@pytest.mark.parametrize("text", ["acme-lab", "acme_lab", "Acme Lab", "ACMELAB", "see acme-lab.", "import acme_lab",
                                  "acme - lab", "acme--lab"])
def test_a_term_matches_in_every_spelling_of_its_separators(text):
    assert boundary.term_regex("acme-lab").search(text)
    assert boundary.term_regex("acme_lab").search(text)
    assert boundary.term_regex("acme - lab").search(text)   # a run of separators: its own text too


@pytest.mark.parametrize("text", ["acmelabs", "my_acme_lab", "acme-lab2"])
def test_a_term_keeps_its_word_boundaries(text):
    assert not boundary.term_regex("acme-lab").search(text)


def test_a_separator_at_a_terms_end_stays_literal():
    rx = boundary.term_regex("-foo-")
    assert rx.search("x -foo- y") and not rx.search("foo") and not rx.search("x-foo")


def test_the_public_check_refuses_a_derived_name_and_a_new_spec_unstamps(brain, make_repo, capsys):
    cfg = brain()
    repo = make_repo("engine", {"README.md": "# engine\n\nBuilt on moonshot_lab? No: on Moonshot.\n",
                                "src/core.py": "HOST = 'kestrel_wsl'\n"})
    run_git(repo, "remote", "add", "origin", "https://github.com/acme/engine.git")
    data = public.check(repo, cfg)
    assert {(f["path"], f["what"]) for f in data["findings"]} == {
        ("README.md", "repos term 'moonshot'"), ("src/core.py", "hosts term 'kestrel-wsl'")}
    (repo / "README.md").write_text("# engine\n", encoding="utf-8")
    (repo / "src" / "core.py").write_text("HOST = 'localhost'\n", encoding="utf-8")
    run_git(repo, "commit", "-qam", "neutral names")
    assert cli.main(["check", "--public", "--repo", str(repo), "--history"]) == 1   # the history still holds them
    capsys.readouterr()
    head = run_git(repo, "rev-parse", "HEAD").strip()
    public.stamp_path("acme/engine", head).parent.mkdir(parents=True, exist_ok=True)
    public.stamp_path("acme/engine", head).write_text(json.dumps(
        {"v": public.STAMP_V, "key": public.stamp_key(cfg, public.gitleaks_exe() is not None)}), encoding="utf-8")
    assert public.stamp_refusal("acme/engine", head, cfg) == ""
    (brain.root / "docs" / "specs" / "2026-02-03-new-idea.md").write_text("# New\n", encoding="utf-8")
    why = public.stamp_refusal("acme/engine", head, config.load(brain.root))
    assert "under other rules" in why and "a registry public.derive reads" in why


def test_the_engines_own_names_are_never_derived(brain):
    with (brain.root / "projects.yaml").open("a", encoding="utf-8") as fh:
        fh.write("research_graph: {access: read, title: the graph engine}\n")
    (brain.root.parent / "brain").mkdir()
    with (brain.root / "projects.yaml").open("a", encoding="utf-8") as fh:
        fh.write(f"rocket: {{root: {(brain.root.parent / 'brain').as_posix()}}}\n")
    names = {t.lower() for _, t in denylist.declared(brain())}
    assert "rocket" in names and not names & {"brain", "research_graph", "research-graph"}


def test_a_name_held_in_one_spelling_only_is_warned_about(brain):
    brain(derive=[], deny={"people": ["Ada"], "repos": ["moonshot"]})
    with (brain.root / "projects.yaml").open("a", encoding="utf-8") as fh:
        fh.write("moonshot-lab: {access: read, title: its lab}\n")
    lines = denylist.check_lines(brain.root)
    # moonshot refuses moonshot-lab, not moonshot_lab nor moonshotlab: the name is not held
    assert any("'moonshot-lab' is in no deny list" in x for x in lines)
    assert not any("'moonshot' is in no deny list" in x for x in lines)
    assert denylist.spellings("a-b c") == ["a-b-c", "a_b_c", "a b c", "abc"]


@pytest.mark.parametrize("torn", ["projects.yaml", "members.yaml", "notes/graph/modules.yaml"])
def test_a_registry_that_cannot_be_read_fails_closed(brain, make_repo, torn):
    """A conflict marker in a registry: no shorter list. The guards refuse, brain check --public stops."""
    cfg = brain()
    f = brain.root / torn
    f.write_text("<<<<<<< HEAD\n" + f.read_text(encoding="utf-8") + "=======\n>>>>>>> other\n", encoding="utf-8")
    assert "the deny terms could not be derived" in config.unexpected(cfg)
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(brain.root)}
    assert any("cannot trust the configuration" in reason for g, _, reason, _ in guards.refusals(payload)
               if g == "public")
    repo = make_repo("engine", {"README.md": "# engine\n"})
    with pytest.raises(public.PublicError, match="cannot be derived from the registries"):
        public.check(repo, cfg)
    assert cli.main(["check", "--public", "--repo", str(repo)]) == 2
    assert any("could not be built" in x for x in denylist.check_lines(brain.root)) or \
        denylist.check_lines(brain.root) is not None   # check_lines never raises


def test_a_derivation_that_fails_makes_the_guards_fail_closed(brain, monkeypatch):
    cfg = brain()

    def boom(_cfg):
        raise denylist.DeriveError("registry torn")
    monkeypatch.setattr(denylist, "terms", boom)
    why = config.unexpected(cfg)
    assert "the deny terms could not be derived" in why and "registry torn" in why
    assert config.deny_terms(cfg) == [("people", "Ada")]   # the hand list still reads; the guards refuse on why
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": str(brain.root)}
    assert any("cannot trust the configuration" in reason for g, _, reason, _ in guards.refusals(payload)
               if g == "public")


def test_a_render_for_a_public_repo_does_not_deny_its_own_name(brain):
    cfg = brain()
    assert ("repos", "moonshot") in config.deny_terms(cfg)
    published = denylist.publishing(cfg, ["moonshot"])
    assert ("repos", "moonshot") not in config.deny_terms(published) and ("repos", "lab-repo") in \
        config.deny_terms(published)
    assert "moonshot" not in denylist.public_names(cfg)   # the brain's own config is left as it was


def test_many_terms_are_one_regex_first(brain):
    r = public.rules(brain())
    assert r.any_term is not None and r.any_term.search("night_runner") and not r.any_term.search("nothing here")
    assert public.scan_lines("a.md", [(1, "nothing private")], r) == []


def test_the_brains_own_root_gives_no_name_from_a_worktree_either(brain, tmp_path, monkeypatch):
    """The registry read from the main checkout and config.json from a worktree (or the other way round) are one
    brain: a project rooted in its repo is not derived by name (a brain named as its engine)."""
    from conftest import git_init
    git_init(brain.root)
    run_git(brain.root, "add", "-A")
    run_git(brain.root, "commit", "-qm", "init")
    wt = tmp_path / "ada-wt"
    run_git(brain.root, "worktree", "add", "-q", "-b", "side", str(wt))
    (brain.root / "inner").mkdir()
    with (brain.root / "projects.yaml").open("a", encoding="utf-8") as fh:
        fh.write(f"inner-proj: {{root: {(brain.root / 'inner').as_posix()}}}\n"
                 f"main-twin: {{root: {brain.root.as_posix()}}}\n")
    brain()
    import shutil
    shutil.copy(brain.root / config.FILE, wt / config.FILE)
    monkeypatch.setenv("BRAIN_CONFIG", str(wt / config.FILE))   # the registry stays the main checkout's
    cfg = config.load()
    assert cfg.root == wt.resolve()
    names = {t for s, t in denylist.declared(cfg) if s == "projects"}
    assert "main-twin" not in names and "moonshot" in names
    assert "inner-proj" in names   # a subfolder of the brain's repo is another project: its name is derived
