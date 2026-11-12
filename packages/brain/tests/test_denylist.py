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
    assert by["projects"] == ["ada-brain", "moonshot", "upstream-tool", "lab-repo"]   # a repo by its folder too
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


@pytest.mark.parametrize("text", ["acme-lab", "acme_lab", "Acme Lab", "ACMELAB", "see acme-lab.", "import acme_lab"])
def test_a_term_matches_in_every_spelling_of_its_separators(text):
    assert boundary.term_regex("acme-lab").search(text)
    assert boundary.term_regex("acme_lab").search(text)


@pytest.mark.parametrize("text", ["acmelabs", "acme--lab", "my_acme_lab", "acme-lab2"])
def test_a_term_keeps_its_word_boundaries(text):
    assert not boundary.term_regex("acme-lab").search(text)


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


def test_a_derivation_that_fails_makes_the_guards_fail_closed(brain, monkeypatch):
    cfg = brain()

    def boom(_cfg):
        raise RuntimeError("registry torn")
    monkeypatch.setattr(denylist, "terms", boom)
    why = config.unexpected(cfg)
    assert "the deny terms could not be derived" in why and "registry torn" in why
    assert config.deny_terms(cfg) == [("people", "Ada")]   # the hand list still reads; the guards refuse on why
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": str(brain.root)}
    assert any("cannot trust the configuration" in reason for g, _, reason, _ in guards.refusals(payload)
               if g == "public")


def test_many_terms_are_one_regex_first(brain):
    r = public.rules(brain())
    assert r.any_term is not None and r.any_term.search("night_runner") and not r.any_term.search("nothing here")
    assert public.scan_lines("a.md", [(1, "nothing private")], r) == []
