"""brain init: a new personal brain from the templates, a plan then an apply that never overwrites (brain.init)."""

import json
import re

import pytest

from brain import __version__, cli, config, init, neutral, paths, projects, render, skew

from conftest import git_init, run_git


@pytest.fixture
def fresh(tmp_path, monkeypatch, brain_home):
    """An empty folder to become Ada's brain; the tests' own config and registry overrides off."""
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.setattr(init, "machine_terms", lambda: {"users": ["ada-l"], "hosts": ["host-a"]})
    # init pins v<version>; the tests run a dev engine, which stands here for that release (brain.skew)
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])
    root = tmp_path / "ada-brain"
    root.mkdir()
    return root


def test_the_plan_writes_nothing(fresh, brain_home, capsys):
    assert cli.main(["init", str(fresh), "--owner", "Ada"]) == 0
    out = capsys.readouterr().out
    assert "create   config.json" in out and "create   notes/graph (research_graph init --owner Ada, layers work, decisions, records, lessons)" in out
    assert "create   source/packs.yaml" in out
    assert "render   .claude-plugin/marketplace.json (and plugins/brain-core/ with the engine's hooks" in out
    assert f"point    {paths.personal_file()}" in out and "(plan only: brain init --apply writes it)" in out
    assert list(fresh.iterdir()) == [] and not paths.personal_file().exists()


def test_apply_writes_a_brain_that_checks_and_points_to_it(fresh, monkeypatch, capsys):
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "next: git init" in out
    assert f"claude plugin marketplace add {fresh.resolve()}, then claude plugin install brain-core@brain" in out
    assert "brain sync renders the plugin again after an engine upgrade" in out
    data = json.loads((fresh / "config.json").read_text(encoding="utf-8"))
    stores = data.pop("classes")["stores"]
    assert list(stores) == ["memory", "ddr", "ledger", "sessions", "resume", "digest", "vault", "transcripts", "repo"]
    assert stores["memory"]["class"] == "confidential" and stores["repo"] == {
        "class": "private", "paths": ["**"], "why": "rules, graph, ADRs, journal, records"}
    assert "the runbook: https://github.com/RoJLD/brain/blob/main/packages/brain/docs/vault.md" in out
    assert data == {"v": 1, "identity": {"owner": "Ada", "kind": "person"}, "registry": "projects.yaml",
                    "rules": ["rules/global.md"], "memory": "memory", "records": "records",
                    "template": {"name": "generic", "version": 1},
                    "engine": {"repo": init.ENGINE_REPO, "pin": f"v{__version__}"}, "tier": {"base": "lite"},
                    "adapters": {"claude": {"marketplace": "brain", "plugin": "brain-core"}},
                    "public": {"repos": [], "deny": {"people": ["Ada"], "users": ["ada-l"], "hosts": ["host-a"]}}}
    assert config.check(fresh) == [] and config.owner_of(fresh) == "Ada"
    assert "owner: \"Ada\"" in (fresh / "notes" / "graph" / "schema.yaml").read_text(encoding="utf-8")
    assert (fresh / "notes" / "decisions.md").is_file() and (fresh / "notes" / "kanban_graph.md").is_file()
    rules = (fresh / "rules" / "global.md").read_text(encoding="utf-8")
    assert rules.startswith("# Ada's rules for every project") and "{owner}" not in rules
    reg = projects.load(fresh)
    assert list(reg) == ["brain"] and reg["brain"].root == fresh.resolve()
    assert paths.pointer_root() == fresh.resolve()
    assert cli.main(["--root", str(fresh), "check"]) == 0
    out = capsys.readouterr().out
    assert "graph-check OK" in out and re.search(r"render claude: \d+ same\n", out)


def test_apply_renders_a_local_claude_marketplace(fresh, capsys):
    """The Claude files after the store: the marketplace brain, its core plugin brain-core with the engine's hooks,
    loaded in place by ``claude plugin marketplace add DIR`` (a relative source) and current for brain check."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    market = json.loads((fresh / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert market == {"name": "brain", "owner": {"name": "Ada"},
                      "plugins": [{"name": "brain-core", "source": "./plugins/brain-core"}]}
    plugin = fresh / "plugins" / "brain-core"
    assert json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")) == {"name": "brain-core"}
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert "SessionStart" in hooks["hooks"] and "PreToolUse" in hooks["hooks"]
    engine = render.claude_hooks()
    shipped = {f.relative_to(engine).as_posix() for f in engine.rglob("*") if f.is_file() and "__pycache__" not in f.parts}
    assert {f.relative_to(plugin / "hooks").as_posix() for f in (plugin / "hooks").rglob("*") if f.is_file()} == shipped
    assert (plugin / "hooks" / "inject-rules.sh").read_bytes() == \
        (engine / "inject-rules.sh").read_bytes().replace(b"\r\n", b"\n")
    packs = (fresh / "source" / "packs.yaml").read_text(encoding="utf-8")
    assert neutral.load_yaml(packs) == {"marketplace": {"owner": {"name": "Ada"}},
                                        "packs": {"core": {"core": True, "hooks": True}}}
    capsys.readouterr()
    assert render.main(fresh, "claude", check=True) == 0
    assert "not current" not in capsys.readouterr().out


def test_an_owner_with_quotes_is_quoted_in_packs_yaml(fresh, capsys):
    assert cli.main(["init", str(fresh), "--owner", 'Ada "the first" O\'Neil: #1', "--apply"]) == 0
    packs = neutral.load_yaml((fresh / "source" / "packs.yaml").read_text(encoding="utf-8"))
    assert packs["marketplace"]["owner"]["name"] == 'Ada "the first" O\'Neil: #1'
    market = json.loads((fresh / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert market["owner"] == {"name": 'Ada "the first" O\'Neil: #1'}


def test_a_rendered_file_that_differs_is_kept(fresh, capsys):
    """brain init never overwrites: a Claude file that exists and differs keeps the whole render back and is named;
    brain render --target claude --write replaces it."""
    (fresh / ".claude-plugin").mkdir()
    mine = '{"name": "mine", "owner": {"name": "Ada"}, "plugins": []}\n'
    (fresh / ".claude-plugin" / "marketplace.json").write_text(mine, encoding="utf-8")
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "keep     .claude-plugin/marketplace.json (differs: brain render --target claude --write replaces it)" \
        in out
    assert (fresh / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8") == mine
    assert not (fresh / "plugins").exists()
    assert render.main(fresh, "claude", do_write=True) == 0
    assert json.loads((fresh / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))["name"] == "brain"


def test_the_first_items_go_into_the_empty_layers(fresh, capsys):
    """research_graph init writes an empty layer as a flow list (``[]``): the first item and its first edge go after
    its comments, and the store still checks."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    assert cli.main(["--root", str(fresh), "item", "add", "wi-first", "--title", "First: the pilot", "--priority",
                     "P1", "--reason", "the pilot"]) == 0
    assert cli.main(["--root", str(fresh), "item", "add", "wi-second", "--title", "Second", "--after",
                     "wi-first"]) == 0
    work = (fresh / "notes" / "graph" / "nodes" / "work.yaml").read_text(encoding="utf-8")
    assert "[]" not in work and work.startswith("# Work layer") and "- {id: wi-first," in work
    assert "{from: wi-second, to: wi-first, type: depends_on}" in \
        (fresh / "notes" / "graph" / "edges" / "work.yaml").read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "sync"]) == 0 and cli.main(["--root", str(fresh), "check"]) == 0
    assert "graph-check OK" in capsys.readouterr().out


def test_a_second_apply_changes_nothing_and_a_file_is_never_overwritten(fresh, capsys):
    (fresh / "rules").mkdir()
    (fresh / "rules" / "global.md").write_text("my own rules\n", encoding="utf-8")
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    assert "keep     rules/global.md (exists)" in capsys.readouterr().out
    assert (fresh / "rules" / "global.md").read_text(encoding="utf-8") == "my own rules\n"
    before = {p: p.read_bytes() for p in fresh.rglob("*") if p.is_file()}
    assert (fresh / ".claude-plugin" / "marketplace.json") in before
    assert (fresh / "plugins" / "brain-core" / "hooks" / "hooks.json") in before
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "create" not in out and "point" not in out and "keep     notes/graph (a graph store already)" in out
    assert "render   " not in out and "keep     .claude-plugin/marketplace.json (and plugins/brain-core/: current)" in out
    assert {p: p.read_bytes() for p in fresh.rglob("*") if p.is_file()} == before


def test_a_team_a_tenant_and_another_pointer(fresh, brain_home, tmp_path, capsys):
    brain_home.mkdir(parents=True, exist_ok=True)
    (brain_home / paths.PERSONAL).write_text(json.dumps({"root": str(tmp_path / "other")}), encoding="utf-8")
    assert cli.main(["init", str(fresh), "--owner", "Team  Z", "--kind", "team", "--tenant", "team-z", "--tier",
                     "default", "--name", "team-z", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "keep     " in out and "install.ps1 -Personal moves it" in out
    data = json.loads((fresh / "config.json").read_text(encoding="utf-8"))
    assert data["identity"] == {"owner": "Team Z", "kind": "team", "tenant": "team-z"}
    assert data["tier"] == {"base": "default"}
    assert "team-z:\n  root: .\n" in (fresh / "projects.yaml").read_text(encoding="utf-8")
    assert paths.pointer_root() == tmp_path / "other"   # never moved by brain init


@pytest.mark.parametrize("args, why", [([], "--owner NAME"), (["--owner", " "], "--owner NAME"),
                                       (["--owner", "Ada", "--name", "Bad Name"], "--name 'Bad Name'")])
def test_bad_arguments_plan_nothing(fresh, capsys, args, why):
    assert cli.main(["init", str(fresh), *args]) == 2
    assert why in capsys.readouterr().out and list(fresh.iterdir()) == []


def test_the_templates_name_no_one():
    """The starter files carry the owner's name only where brain init puts it: placeholders, no name."""
    tpl = init.load_template()
    for name in filter(None, set(tpl.files.values())):
        text = init.template(name)
        assert set(re.findall(r"\{(\w+)\}", text)) <= {"owner", "owner_q", "name", "title_q"}, name
        assert "Ada" not in text, name
    assert "{owner_q}" in init.template("packs.yaml")


# --- the template, the owner, publishable by construction (wi-brain-domain-templates, wi-brain-setup-wizard,
# wi-brain-public-ready-init) ---

def committed(root):
    """git init and a first commit of the new brain, as its owner would."""
    git_init(root)
    run_git(root, "config", "commit.gpgsign", "false")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "my brain")
    return root


def test_the_generic_template_writes_a_publishable_brain(fresh, capsys):
    """The default template: README, boundary.yaml at readiness_max 0, the fixtures folder, LF endings; brain check
    runs the boundary and the engine side's public scan from the first commit, and passes."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    assert "template generic v1" in capsys.readouterr().out
    for rel in ("README.md", "boundary.yaml", "fixtures/README.md", ".gitattributes"):
        assert (fresh / rel).is_file(), rel
    assert (fresh / "README.md").read_text(encoding="utf-8").startswith("# Ada's brain")
    assert "readiness_max: 0" in (fresh / "boundary.yaml").read_text(encoding="utf-8")
    assert "eol=lf" in (fresh / ".gitattributes").read_text(encoding="utf-8")
    assert cli.main(["--root", str(fresh), "check"]) == 0          # before git init: a note, never a failure
    assert "boundary: not a git checkout yet" in capsys.readouterr().out
    committed(fresh)
    assert cli.main(["--root", str(fresh), "check"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"boundary: \d+ tracked file\(s\) classified; engine side 1 file\(s\), readiness 0 \(max 0\), "
                     r"public scan green", out), out
    assert cli.main(["--root", str(fresh), "boundary", "--check"]) == 0


@pytest.mark.parametrize("rel, text, why", [
    ("src/tool.py", "AUTHOR = 'Ada'\n", "denied: people term 'Ada'"),
    ("tests/test_tool.py", "HOST = 'host-a'\n", "denied: hosts term 'host-a'"),
    ("fixtures/people.yaml", "- mail: ada" + "@" + "realmail.org\n", "pattern: an e-mail address"),   # built here:
    # the address itself would fail this repo's own public check
    ("misc.txt", "anything\n", "misc.txt: no rule of boundary.yaml classifies it"),
])
def test_brain_check_refuses_a_private_term_where_publishable(fresh, capsys, rel, text, why):
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    committed(fresh)
    (fresh / rel).parent.mkdir(parents=True, exist_ok=True)
    (fresh / rel).write_text(text, encoding="utf-8")
    run_git(fresh, "add", "-A")
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "check"]) == 1
    out = capsys.readouterr().out
    assert why in out and "error: boundary:" in out, out


def test_a_fresh_brain_carries_no_audit_debt_of_the_engine(fresh, capsys):
    """The README is there and the rendered plugin is waived: brain audit finds no P0 on a fresh brain, and none of
    the engine's hook scripts."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    committed(fresh)
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "audit", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    found = [f for p in data["projects"] for r in p["repos"] for f in r["findings"]]
    assert not [f for f in found if f["severity"] in ("P0", "P1")], [(f["unit"], f["why"]) for f in found]
    assert not [f for f in found if f["unit"].startswith("plugins/")], found


def test_the_owner_comes_from_the_folders_config(fresh, capsys):
    assert cli.main(["init", str(fresh), "--owner", "Ada Lovelace", "--apply"]) == 0
    capsys.readouterr()
    assert cli.main(["init", str(fresh), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "for Ada Lovelace (person, lite)" in out and "create" not in out


def test_a_template_of_ones_own(fresh, tmp_path, capsys):
    """A folder holding a template.yaml: its files rendered with the variables, config.json naming it."""
    tpl = tmp_path / "lab"
    tpl.mkdir()
    (tpl / "template.yaml").write_text(
        'name: lab\nversion: 3\nengine: ">=0.2.1, <1"\ntitle: "A lab"\n'
        'files: {projects.yaml: projects.yaml, source/packs.yaml: packs.yaml, rules/global.md: rules.md, '
        'NOTES.md: notes.md, memory/.gitkeep: "", records/.gitkeep: ""}\n', encoding="utf-8")
    for name in ("projects.yaml", "packs.yaml", "rules.md"):
        (tpl / name).write_text(init.template(name), encoding="utf-8")
    (tpl / "notes.md").write_text("# {owner}'s lab notes ({name})\n", encoding="utf-8")
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl), "--name", "lab", "--apply"]) == 0
    assert "template lab v3" in capsys.readouterr().out
    assert (fresh / "NOTES.md").read_text(encoding="utf-8") == "# Ada's lab notes (lab)\n"
    assert not (fresh / "boundary.yaml").exists()
    assert json.loads((fresh / "config.json").read_text(encoding="utf-8"))["template"] == {"name": "lab", "version": 3}
    assert config.check(fresh) == []


@pytest.mark.parametrize("manifest, why", [
    ("name: lab\nversion: 1\nengine: \">=99\"\nfiles: {}\n", "it needs brain >=99"),
    ("name: lab\nversion: 1\nfiles: {config.json: x}\n", "a path inside the brain, not config.json"),
    ("name: lab\nversion: 1\nfiles: {../out.md: x}\n", "a path inside the brain"),
    ("name: lab\nversion: 1\nfiles: {a.md: missing.md}\n", "no file 'missing.md' in the template"),
    ("name: Lab\nversion: 1\nfiles: {}\n", "name is lower case"),
    ("name: lab\nversion: 0\nfiles: {}\n", "version is a whole number"),
    ("name: lab\nversion: 1\nfiles: {}\nhooks: x\n", "unknown key(s) hooks"),
    ("name: lab\nversion: 1\nfiles: {NOTES.md: \"\"}\n", "files misses what config.json names: projects.yaml"),
])
def test_a_bad_template_plans_nothing(fresh, tmp_path, capsys, manifest, why):
    tpl = tmp_path / "lab"
    tpl.mkdir()
    (tpl / "template.yaml").write_text(manifest, encoding="utf-8")
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl)]) == 2
    assert why in capsys.readouterr().out and list(fresh.iterdir()) == []


def test_an_unknown_template_names_the_engines(fresh, capsys):
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", "quant"]) == 2
    assert "not one of the engine's (generic)" in capsys.readouterr().out


@pytest.mark.parametrize("spec, version, fits", [(">=0.2.1", "0.2.1", True), (">=0.2.1", "0.2.0", False),
                                                 (">=0.2, <0.3", "0.2.9", True), ("<0.3", "0.3.0", False),
                                                 ("==0.2.1", "0.2.1", True), ("", "0.0.1", True)])
def test_engine_fits(spec, version, fits):
    assert init.engine_fits(spec, version) is fits


def test_machine_terms_leave_out_common_names(monkeypatch):
    monkeypatch.setattr(init.getpass, "getuser", lambda: "Admin")
    monkeypatch.setattr(init.socket, "gethostname", lambda: "host-a.example.invalid")
    assert init.machine_terms() == {"hosts": ["host-a"]}


def test_a_template_starts_each_graph_it_declares(fresh, tmp_path, capsys):
    """The manifest's graphs: one store each, by research_graph init with the owner; the first is the brain's main."""
    tpl = tmp_path / "lab"
    tpl.mkdir()
    for name in ("projects.yaml", "packs.yaml", "rules.md"):
        (tpl / name).write_text(init.template(name), encoding="utf-8")
    (tpl / "template.yaml").write_text(
        'name: lab\nversion: 1\ngraphs: [{name: work, store: notes/graph}, {name: research, store: research/graph}]\n'
        'files: {projects.yaml: projects.yaml, source/packs.yaml: packs.yaml, rules/global.md: rules.md, '
        'memory/.gitkeep: "", records/.gitkeep: ""}\n', encoding="utf-8")
    assert init.load_template(str(tpl)).graphs == [{"name": "work", "store": "notes/graph", "schema": "default"},
                                                   {"name": "research", "store": "research/graph",
                                                    "schema": "default"}]
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "create   notes/graph (research_graph init --owner Ada, layers work, decisions, records, lessons)" in out
    assert "create   research/graph (research_graph init --owner Ada, layers work, decisions, records, lessons)" in out
    for store in ("notes/graph", "research/graph"):
        assert 'owner: "Ada"' in (fresh / store / "schema.yaml").read_text(encoding="utf-8"), store


@pytest.mark.parametrize("graphs, why", [
    ("[]", "graphs is a list of {name, store, schema}, one at least"),
    ("[{name: work, store: notes/graph, layers: [work]}]", "graphs[0]: a mapping of name, schema, store"),
    ("[{name: a, store: g}, {name: a, store: h}]", "graphs[1]: name is lower case"),
    ("[{name: a, store: ../g}]", "graphs[0] (a): store is a folder inside the brain"),
    ("[{name: a, store: g, schema: quant}]", "schema 'quant': only default for now"),
])
def test_a_bad_graph_plans_nothing(fresh, tmp_path, capsys, graphs, why):
    tpl = tmp_path / "lab"
    tpl.mkdir()
    for name in ("projects.yaml", "packs.yaml", "rules.md"):
        (tpl / name).write_text(init.template(name), encoding="utf-8")
    (tpl / "template.yaml").write_text(
        f'name: lab\nversion: 1\ngraphs: {graphs}\n'
        'files: {projects.yaml: projects.yaml, source/packs.yaml: packs.yaml, rules/global.md: rules.md, '
        'memory/.gitkeep: "", records/.gitkeep: ""}\n', encoding="utf-8")
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--template", str(tpl)]) == 2
    assert why in capsys.readouterr().out and list(fresh.iterdir()) == []


def test_the_generic_store_holds_the_records_after_sync(fresh, fixture_transcript, capsys):
    """GT-2 (the owner's answer, 2026-11-03): the generic template's store is the brain's base, work, decisions and records; a
    question asked and a session recorded are DDR and Session nodes after brain sync, and the store still checks."""
    from brain import records, transcript

    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    schema = (fresh / "notes" / "graph" / "schema.yaml").read_text(encoding="utf-8")
    assert schema.startswith("# The vocabulary of this graph store, the brain's base") and 'owner: "Ada"' in schema
    assert "records: [DDR, Session, Action]" in schema
    assert cli.main(["--root", str(fresh), "decision", "ask", "--title", "Pick a name", "--question", "Which?",
                     "--option", "Orion: short", "--option", "Atlas: taken", "--why", "short", "--no-notify"]) == 0
    stats, _, _ = transcript.session_stats(fixture_transcript)
    records.write(fresh, "sr", stats.record(fixture_transcript))
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "sync"]) == 0
    generated = (fresh / "notes" / "graph" / "nodes" / "_generated_records.yaml").read_text(encoding="utf-8")
    assert "type: DDR" in generated and "type: Session" in generated
    assert cli.main(["--root", str(fresh), "check"]) == 0
    assert "graph-check OK" in capsys.readouterr().out


def test_a_fresh_brain_passes_check_all_with_a_private_remote(fresh, capsys):
    """brain init writes a classes block: a brain fresh from it, committed and pushed to a private remote, passes
    brain check --all (its empty memory/ and records/ hold no data; the waivers print, they do not fail)."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    committed(fresh)
    run_git(fresh, "remote", "add", "origin", "git@example.invalid:ada/ada-brain.git")
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "classes", "--check"]) == 0
    assert "classes: 9 store(s), OK" in capsys.readouterr().out
    assert cli.main(["--root", str(fresh), "check", "--all"]) == 0, capsys.readouterr().out


def test_refresh_and_check_in_a_brain_check_its_own_data(fresh, capsys):
    """brain refresh and brain check in a brain's own root run the registry check too (config.json, the classes, the
    permissions, the stacks and bundles, the ids), as check --all does: what a brain's own tests used to check
    (wi-brain-test-split)."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    committed(fresh)
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "refresh"]) == 0
    out = capsys.readouterr().out
    assert "== registry" in out and "registry: 1 project(s)" in out
    cfg = json.loads((fresh / "config.json").read_text(encoding="utf-8"))
    cfg["identity"]["owner"] = "Bob"   # no longer its stores' owner
    (fresh / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    for command in ("refresh", "check"):
        assert cli.main(["--root", str(fresh), command]) == 1, command
        assert "identity.owner 'Bob'" in capsys.readouterr().out


def _register(brain, line):
    with (brain / "projects.yaml").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def test_a_brains_refresh_reads_the_ids_of_every_registered_project(fresh, tmp_path, capsys):
    """The ids are unique across every registered project's stores, as check --all reads them: a collision with
    another project fails, and a shared_ids waiver for it is no stale waiver."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    assert cli.main(["--root", str(fresh), "item", "add", "wi-first", "--title", "First"]) == 0
    committed(fresh)
    lab = tmp_path / "lab" / "notes" / "graph"
    (lab / "nodes").mkdir(parents=True)
    (lab / "schema.yaml").write_text("owner: Ada\nnode_types: [WorkItem]\n", encoding="utf-8")
    (lab / "nodes" / "work.yaml").write_text('- {id: wi-first, type: WorkItem, status: todo, title: "Lab"}\n',
                                            encoding="utf-8")
    _register(fresh, f"lab: {{root: {(tmp_path / 'lab').as_posix()}}}")
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "refresh"]) == 1
    assert "error: id wi-first is in" in capsys.readouterr().out
    reg = fresh / "projects.yaml"
    lab_root = (tmp_path / "lab").as_posix()
    reg.write_text(reg.read_text(encoding="utf-8").replace(
        f"lab: {{root: {lab_root}}}",
        f"lab: {{root: {lab_root}, shared_ids: {{wi-first: 'the pilot item, mirrored in the lab'}}}}"), encoding="utf-8")
    assert cli.main(["--root", str(fresh), "refresh"]) == 0
    out = capsys.readouterr().out
    assert "waived: id wi-first is in" in out and "remove it" not in out


def test_a_project_cloned_elsewhere_leaves_its_stacks_unchecked_here(fresh, tmp_path, capsys):
    """A registered project whose stacks file sits in a root this machine does not hold is skipped with a warning:
    the verdict does not depend on which repos are cloned here."""
    assert cli.main(["init", str(fresh), "--owner", "Ada", "--apply"]) == 0
    committed(fresh)
    _register(fresh, f"far: {{root: {(tmp_path / 'far').as_posix()}, stacks: stacks.yaml}}")
    capsys.readouterr()
    assert cli.main(["--root", str(fresh), "refresh"]) == 0
    assert "warning: stacks of project far: its root is not on this machine" in capsys.readouterr().out
