"""Generated READMEs (wi-brain-readme-sync, brain.readme, brain docs): README.md from the engine's template, the repo's
readme.yaml and the facts of their sources; the check, opt-in by readme.yaml; the neutral render of a public repo."""

import json
import sys

from brain import cli, features, graph, readme
from conftest import git_init, run_git

from research_graph.cli import main as research_graph

SPEC = """\
v: 1
title: Lab
tagline: A lab that measures tea.
what: The lab's code and its command.
why: To measure tea the same way every time.
start:
  - Clone the repo.
  - {text: "Install it", run: "pip install -e ."}
commands:
  - {cli: brain, args: docs render, say: "Writes this README."}
  - {cli: brain, args: sync}
sections:
  - {title: Notes, text: "Brewed at 95 degrees."}
links:
  - {title: The site, href: "https://example.org"}
"""


def _lab(tmp_path, monkeypatch, spec=SPEC):
    """lab: a repo whose root holds the store (the Feature layer added), a spec, an ADR, a milestone, an open item of
    it, three features, and readme.yaml; registered in a projects.yaml of its own."""
    root = git_init(tmp_path / "lab")
    store = root / "notes" / "graph"
    assert research_graph(["--store", str(store), "--repo-root", str(root), "init"]) == 0
    schema = (store / "schema.yaml").read_text(encoding="utf-8")
    schema = schema.replace("node_types: [WorkItem,", "node_types: [Feature, CodeRef, WorkItem,").replace(
        "edge_types: [", "edge_types: [delivers, implemented_by, ").replace(
        "statuses: [todo,", "statuses: [have, partial, planned, \"no\", todo,")
    (store / "schema.yaml").write_text(schema, encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(
        "- {id: spec-tea, type: Spec, status: active, title: \"Tea, measured\"}\n"
        "- {id: adr-2026-11-01-tea, type: ADR, status: active, title: \"Brew at 95\"}\n"
        "- {id: ms-tea, type: Milestone, status: pending, title: \"First cup\"}\n"
        "- {id: wi-tea, type: WorkItem, status: todo, title: \"Weigh the leaves\", props: {repo: lab}}\n",
        encoding="utf-8")
    (store / "edges" / "work.yaml").write_text("- {from: wi-tea, to: ms-tea, type: part_of}\n", encoding="utf-8")
    features.add(store, "feat-lab-brew", "Brew Ada's way", "brewing", "lab", status="have", value="high",
                 specs=["spec-tea"], adrs=["adr-2026-11-01-tea"])
    features.set_feature(store, "feat-lab-brew", ["public_title=Brew the owner's way"])
    features.add(store, "feat-lab-weigh", "Weigh the leaves", "measures", "lab", status="partial")
    features.add(store, "feat-lab-cold", "Cold brew", "brewing", "lab", status="planned")
    (root / "readme.yaml").write_text(spec, encoding="utf-8")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"lab:\n  root: {root.as_posix()}\n  repos:\n    - {{name: lab, path: {root.as_posix()}}}\n",
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.chdir(root)
    return root, store


def _render(root, store, public=False):
    return readme.render(readme.load(root), readme.store_facts(store, "lab", public), root)


def test_the_render_holds_the_text_and_the_facts_and_is_stable(tmp_path, monkeypatch):
    root, store = _lab(tmp_path, monkeypatch)
    text = _render(root, store)
    assert text.startswith(f"<!-- {readme.MARKER} from readme.yaml")
    assert "# Lab\n\n> A lab that measures tea.\n\nThe lab's code and its command." in text
    assert "## Why\n\nTo measure tea the same way every time." in text
    assert "1. Clone the repo.\n2. Install it\n\n   ```bash\n   pip install -e .\n   ```" in text
    assert "**3 features: 1 have, 1 partial, 1 planned, 0 no.** By domain: brewing 2, measures 1." in text
    assert "- **Brew Ada's way** (have)\n- **Weigh the leaves** (partial)" in text   # high value first, planned left
    assert "The full matrix: [FEATURES.md](FEATURES.md)." in text
    assert "### `brain docs render`\n\nWrites this README.\n\n    usage: brain docs render" in text
    assert "### `brain sync`\n\n    usage: brain sync" in text
    assert "## Notes\n\nBrewed at 95 degrees." in text and "- [The site](https://example.org)" in text
    assert "- `spec-tea`: Tea, measured" in text and "- `adr-2026-11-01-tea`: Brew at 95" in text
    assert "- `ms-tea`: First cup" in text   # the pending milestone an open item of the repo is part of
    assert "\n\n\n" not in text and text.endswith("\n") and _render(root, store) == text


def test_a_public_repo_is_rendered_neutral(tmp_path, monkeypatch):
    root, store = _lab(tmp_path, monkeypatch)
    text = _render(root, store, public=True)
    assert "Brew the owner's way" in text and "Ada" not in text
    for private in ("spec-tea", "adr-2026-11-01-tea", "ms-tea", "wi-tea", "In the brain"):
        assert private not in text


def test_check_refuses_a_missing_field_a_gone_command_and_a_stale_or_hand_edited_readme(tmp_path, monkeypatch):
    root, store = _lab(tmp_path, monkeypatch)
    facts = readme.store_facts(store, "lab", False)
    rep = readme.check(root, facts)
    assert rep.errors == [] and rep.stale == "README.md is missing"
    assert readme.write(root, rep.text) == "written"
    assert readme.check(root, facts).stale == ""
    (root / "README.md").write_text(rep.text.replace("Brewed at 95", "Brewed at 90"), encoding="utf-8")
    assert "a hand edit, or a stale render" in readme.check(root, facts).stale
    (root / "readme.yaml").write_text(SPEC.replace("why: To measure tea the same way every time.\n", ""),
                                      encoding="utf-8")
    assert any("why" in e for e in readme.check(root, facts).errors)
    (root / "readme.yaml").write_text(SPEC.replace("args: sync", "args: no-such-command"), encoding="utf-8")
    assert readme.check(root, facts).errors == [
        "readme.yaml: the quoted command `brain no-such-command` is gone (its --help does not run): change or "
        "remove it"]
    (root / "readme.yaml").write_text("- not a mapping\n", encoding="utf-8")
    assert readme.check(root, facts).errors[0].startswith("readme.yaml: not a mapping")


def test_another_programs_usage_comes_from_running_its_help(tmp_path):
    assert readme.program_usage(sys.executable, [], tmp_path).startswith("usage:")
    assert readme.program_usage("brain-no-such-program-x", [], tmp_path) is None


def test_cli_render_writes_readme_and_features_and_keeps_a_hand_written_readme(tmp_path, monkeypatch, capsys):
    root, store = _lab(tmp_path, monkeypatch)
    (root / "README.md").write_text("# Lab\n\nWritten by hand.\n", encoding="utf-8")
    assert cli.main(["docs", "check"]) == 1
    assert "error: lab: README.md is not the render of readme.yaml (a hand-written README)" in capsys.readouterr().out
    assert cli.main(["docs", "render", "--write"]) == 1
    assert "refused" in capsys.readouterr().out
    assert (root / "README.md").read_text(encoding="utf-8") == "# Lab\n\nWritten by hand.\n"
    assert cli.main(["docs", "render", "--write", "--force"]) == 0
    out = capsys.readouterr().out
    assert "lab: README.md written" in out and (root / features.VIEW).is_file()
    assert cli.main(["docs", "check"]) == 0
    assert "docs check: 1 README(s) up to date" in capsys.readouterr().out
    assert cli.main(["docs", "render"]) == 0 and capsys.readouterr().out == (root / "README.md").read_text(
        encoding="utf-8")
    features.set_feature(store, "feat-lab-cold", ["status=have"])   # a feature changed without the README
    assert cli.main(["docs", "check"]) == 1
    assert "a stale render" in capsys.readouterr().out
    assert cli.main(["docs", "render", "--write"]) == 0   # a generated README is rewritten without --force


def test_brain_check_is_opt_in_by_readme_yaml(tmp_path, monkeypatch, capsys):
    root, store = _lab(tmp_path, monkeypatch)
    (root / "readme.yaml").unlink()
    (root / "README.md").write_text("# Lab\n\nWritten by hand.\n", encoding="utf-8")
    cli.main(["check"])
    out = capsys.readouterr().out
    assert "README" not in out and "readme" not in out   # no readme.yaml: nothing read, nothing said
    assert cli.main(["docs", "check"]) == 0
    assert "not concerned" in capsys.readouterr().out
    (root / "readme.yaml").write_text(SPEC.replace("args: sync", "args: no-such-command"), encoding="utf-8")
    assert cli.main(["check"]) == 1   # opted in: a quoted command gone is an error
    assert "error: lab: readme.yaml: the quoted command `brain no-such-command` is gone" in capsys.readouterr().out


def test_brain_check_names_a_stale_readme_as_a_stale_view_on_the_default_branch(tmp_path, monkeypatch, capsys):
    root, store = _lab(tmp_path, monkeypatch)
    assert cli.main(["docs", "render", "--write"]) == 0
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "lab")   # on main, the default branch
    capsys.readouterr()
    cli.main(["check"])
    assert "README.md" not in capsys.readouterr().out   # up to date: nothing said
    features.set_feature(store, "feat-lab-cold", ["status=have"])   # a feature changed without the README
    cli.main(["check"])
    out = capsys.readouterr().out
    assert "lab:README.md" in out and "brain docs render --write" in out   # a stale view, named with its writer
    assert "error: lab:" not in out
    cfg = tmp_path / "home-strict" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"views": {"strict": True}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    assert cli.main(["check"]) == 1   # under views.strict a stale view fails the default branch


def test_brain_check_ignores_its_own_repo_option_and_a_bad_readme_encoding(tmp_path, monkeypatch, capsys):
    root, store = _lab(tmp_path, monkeypatch)
    (root / "readme.yaml").unlink()
    before = cli.main(["check"])
    capsys.readouterr()
    assert cli.main(["check", "--repo", "zzz"]) == before   # --repo is --public's: no README check reads it
    assert "generated READMEs" not in capsys.readouterr().out
    (root / "readme.yaml").write_text(SPEC, encoding="utf-8")
    (root / "README.md").write_bytes("# Lab\n\nCaf\xe9 by hand.\n".encode("cp1252"))   # not UTF-8
    assert "a hand-written README" in readme.check(root, readme.store_facts(store, "lab", False)).stale
    assert cli.main(["docs", "check"]) == 1 and "Traceback" not in capsys.readouterr().out


def test_dir_and_repo_name_the_checkout_and_a_target_without_readme_yaml_is_not_concerned(tmp_path, monkeypatch,
                                                                                          capsys):
    root, store = _lab(tmp_path, monkeypatch)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "readme.yaml").write_text(SPEC.replace("title: Lab", "title: Lab worktree"), encoding="utf-8")
    assert cli.main(["docs", "render", "--write", "--repo", "lab", "--dir", str(wt)]) == 0
    assert "# Lab worktree" in (wt / "README.md").read_text(encoding="utf-8") and not (root / "README.md").exists()
    assert (wt / features.VIEW).is_file()   # its FEATURES.md beside it
    assert cli.main(["docs", "check", "--dir", str(wt)]) == 0   # --dir alone: a worktree of the root's repo
    empty = tmp_path / "empty"
    empty.mkdir()
    capsys.readouterr()
    assert cli.main(["docs", "check", "--dir", str(empty)]) == 0
    out = capsys.readouterr().out
    assert "holds no readme.yaml: not concerned" in out and "up to date" not in out


def test_recent_decisions_are_the_newest_by_their_date(tmp_path, monkeypatch):
    root, store = _lab(tmp_path, monkeypatch)
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        for d in range(2, 9):
            f.write(f"- {{id: adr-2026-11-0{d}-call-{d}, type: ADR, status: active, title: \"Call {d}\"}}\n")
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        for d in range(2, 9):
            f.write(f"- {{from: wi-tea, to: adr-2026-11-0{d}-call-{d}, type: decided_by}}\n")
    text = _render(root, store)
    shown = [x for x in text.split("\n") if x.startswith("- `adr-")]
    assert [x.split("`")[1] for x in shown] == [f"adr-2026-11-0{d}-call-{d}" for d in range(8, 3, -1)]


def test_the_schema_is_registered_and_holds_the_required_fields():
    data = json.loads((readme.TEMPLATE.parents[2] / "schemas" / "readme.schema.json").read_text(encoding="utf-8"))
    assert data["required"] == ["v", "title", "what", "why", "start"]
    from brain import schema
    assert "readme" in schema.SCHEMAS and schema.unsupported(data) == []
    assert schema.schema_errors("readme", graph.load_yaml(SPEC)) == []


def test_public_render_through_a_public_clone(tmp_path, monkeypatch):
    root, store = _lab(tmp_path, monkeypatch)
    cfg = tmp_path / "home" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"public": {"repos": ["acme/lab"]}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    run_git(root, "remote", "add", "origin", "https://github.com/acme/lab.git")
    assert features.public_checkout(root)
    assert cli.main(["docs", "render", "--write", "--force"]) == 0
    text = (root / "README.md").read_text(encoding="utf-8")
    assert "Brew the owner's way" in text and "spec-tea" not in text and "Ada" not in text


def test_the_audit_measures_an_opted_in_repo_only(tmp_path):
    from types import SimpleNamespace

    from brain import audit

    class Tree:
        def __init__(self, files):
            self.files = files

        def has(self, path):
            return path in self.files

        def text(self, path):
            return self.files[path]

    def ctx(files):
        return {"rf": SimpleNamespace(tree=Tree(files), name="lab"),
                "cfg": SimpleNamespace(name="lab", path=str(tmp_path))}

    assert audit.readme_yaml(ctx({})) == audit.NO_README == audit.help_quoted(ctx({}))   # not opted in
    assert audit.readme_yaml(ctx({"readme.yaml": SPEC})) == [] and audit.help_quoted(ctx({"readme.yaml": SPEC})) == []
    bad = SPEC.replace("why: To measure tea the same way every time.\n", "").replace("args: sync", "args: nope")
    found = audit.readme_yaml(ctx({"readme.yaml": bad}))
    assert len(found) == 1 and found[0]["check"] == "readme.yaml" and "why" in found[0]["why"]
    gone = audit.help_quoted(ctx({"readme.yaml": SPEC.replace("args: sync", "args: nope")}))
    assert [f["why"] for f in gone] == ["the quoted command `brain nope` is gone (its --help does not run): change "
                                        "or remove it"] and gone[0]["severity"] == "P1"


def test_the_format_fixtures_read_tolerant_and_strict(monkeypatch):
    from brain import schema
    formats = readme.TEMPLATE.parents[4] / "tests" / "fixtures" / "formats" / "readme" / "v1"
    older = graph.load_yaml((formats / "older.yaml").read_text(encoding="utf-8"))
    newer = graph.load_yaml((formats / "newer.yaml").read_text(encoding="utf-8"))
    assert schema.schema_errors("readme", older, schema.STRICT) == []
    errors, unknown = schema.validate("readme", newer, schema.READ)
    assert errors == [] and len(unknown) == 3   # read mode: noted, kept
    assert len(schema.schema_errors("readme", newer, schema.STRICT)) == 3   # strict (CI at the pin): refused
    assert schema.schema_errors("readme", {**older, "v": 2})[0].startswith("readme: v2 is written by brain >")
    monkeypatch.setenv("BRAIN_STRICT", "0")
    assert readme.spec_errors(newer) == []   # an owner's file read by an older engine: nothing refused
