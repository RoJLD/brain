"""wi-brain-audit-feature-coverage: brain audit's feature.coverage. A command or module of a command registry that no
feature names (an implemented_by of its file, or a title that says it) is an info of the full audit, listed in a
section of its own; in the scout, NEW on a unit the change adds, DEFER on a touched one, LEFT there only under
config.json audit.feature_coverage_strict (the owner's opt-in)."""

import json
import shutil

from brain import audit, cli, config, feature_coverage
from conftest import BRAIN
from test_audit import FIND, README, _found, _measure

SCHEMA = ("node_types: [WorkItem, Feature, CodeRef, Repo]\n"
          "edge_types: [implemented_by, part_of]\n"
          "statuses: [active, retired, todo, done, have, partial, planned, \"no\"]\n"
          "status_by_type:\n  Feature: [have, partial, planned, \"no\"]\n  CodeRef: [active, retired]\n"
          "  WorkItem: [todo, done]\n")
REG = "def register(sub, ctx):\n    p = sub.add_parser({name!r})\n    p.add_subparsers().add_parser('leaf')\n"
LAB = {
    "README.md": README, "pyproject.toml": '[project.scripts]\nlab = "lab.cli:main"\n' + FIND,
    "src/lab/__init__.py": "",
    "src/lab/cli.py": "from lab.commands import _registry\n\ndef main():\n    _registry.load()\n",
    "src/lab/commands/__init__.py": "import pkgutil\n\n\ndef _names():\n    return [m.name for m in "
                                    "pkgutil.iter_modules(__path__)]\n",
    "src/lab/commands/_registry.py": "def load():\n    pass\n",              # a helper: not a command
    "src/lab/commands/run.py": REG.format(name="run"),                      # named by a title: lab run
    "src/lab/commands/stray.py": REG.format(name="stray"),                  # named by nothing
    "src/lab/commands/two_words.py": "def register(sub, ctx):\n    sub.add_parser(NAME)\n",   # not literal: its stem
    "src/lab/store.py": "def save():\n    pass\n",                          # named by a title: lab.store
    "src/lab/linked.py": "def f():\n    pass\n",                            # an implemented_by of a symbol
    "src/lab/old.py": "def f():\n    pass\n",                               # named by nothing
    "src/lab/storex.py": "def f():\n    pass\n",                            # lab.store is not lab.storex
    "src/lab/tools/deep.py": "def f():\n    pass\n",                        # not beside cli.py: out of scope
    "tests/test_store.py": "from lab.store import save\n",
    "notes/graph/schema.yaml": SCHEMA,
    "notes/graph/nodes/features.yaml":
        "- {id: feat-lab-run, type: Feature, status: have, title: \"Runs: lab run --fast, and lab two-words\"}\n"
        "- {id: feat-lab-store, type: Feature, status: planned, title: \"Saving (lab.store), later\"}\n"
        "- {id: feat-lab-cli, type: Feature, status: have, title: \"The CLI\"}\n",
    "notes/graph/edges/features.yaml":
        "- {from: feat-lab-cli, to: \"code:lab:lab/cli.py\", type: implemented_by}\n"
        "- {from: feat-lab-cli, to: \"code:lab:lab/linked.py::f\", type: implemented_by}\n",
}


def test_top_commands_reads_the_parsers_register_adds_on_its_first_parameter():
    assert feature_coverage.top_commands(REG.format(name="run")) == ["run"]          # not its subcommand leaf
    two = "def register(s, ctx):\n    s.add_parser('b')\n    s.add_parser('a')\n    s.add_parser(X)\n"
    assert feature_coverage.top_commands(two) == ["b", "a"]                          # source order, literals only
    assert feature_coverage.top_commands("def run():\n    pass\n") == []
    assert feature_coverage.top_commands("def register(:\n") == []


def test_the_full_audit_lists_what_no_feature_names_as_info_in_a_section():
    res = _measure({"lab": LAB})
    lab = res["repos"][0]
    got = {f["unit"]: f for f in lab["findings"] if f["check"] == "feature.coverage"}
    assert set(got) == {"src/lab/commands/stray.py", "src/lab/old.py", "src/lab/storex.py"}
    assert {f["severity"] for f in got.values()} == {"info"}                          # never counted
    assert "no feature names this command (lab stray)" in got["src/lab/commands/stray.py"]["why"]
    assert got["src/lab/old.py"]["fix"].startswith("brain features link <feature> --code src/lab/old.py")
    assert not any(c == "feature.coverage" for c, _ in _found(res))                  # not in the debt counts
    cov = lab["feature_coverage"]
    assert (cov["units"], cov["named"]) == (8, 5)   # cli, linked, old, store, storex; run, stray, two-words
    assert {x["name"] for x in cov["unnamed"]} == {"lab stray", "lab.old", "lab.storex"}
    text = "\n".join(audit.render_text({"ruleset": audit.RULESET, "projects": [audit._public(res)]}))
    assert "  feature coverage: 5 of 8 commands and modules named by a feature; no feature names: lab stray " \
           "(src/lab/commands/stray.py)" in text
    view = audit.render_view(audit._public(res))
    assert "### Feature coverage" in view and "- command `lab stray` (`src/lab/commands/stray.py`)" in view
    assert audit.CHECKS["feature.coverage"].scout == "new+defer" and audit.RULESET >= 6


def test_no_registry_no_section_and_no_feature_type_not_measured():
    plain = {k: v for k, v in LAB.items() if not k.startswith("src/lab/commands/")}
    lab = _measure({"lab": plain})["repos"][0]
    assert "feature_coverage" not in lab and not any(f["check"] == "feature.coverage" for f in lab["findings"])
    bare = {k: v for k, v in LAB.items() if not k.startswith("notes/")}
    lab = _measure({"lab": bare})["repos"][0]
    assert {"check": "feature.coverage", "owner": audit.NO_FEATURES} in lab["not_measured"]


def _setup(make_repo, tmp_path, monkeypatch):
    from conftest import run_git
    lab = make_repo("lab", LAB)
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {lab.as_posix()}, production: [.]}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    run_git(lab, "checkout", "-q", "-b", "feature")
    (lab / "src" / "lab" / "commands" / "fresh.py").write_text(REG.format(name="fresh"), encoding="utf-8")
    old = lab / "src" / "lab" / "old.py"
    old.write_text(old.read_text(encoding="utf-8") + "\n\ndef g():\n    return 1\n", encoding="utf-8")
    return lab


def _coverage_tags(capsys, lab):
    rc = cli.main(["audit", "--diff", "--repo-dir", str(lab), "--json"])
    data = json.loads(capsys.readouterr().out)
    return rc, {f["unit"]: f["tag"] for f in data["findings"] if f["check"] == "feature.coverage"}, data


def test_the_scout_news_an_added_command_and_defers_a_touched_module(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    rc, tags, data = _coverage_tags(capsys, lab)
    assert rc == 1 and tags == {"src/lab/commands/fresh.py": "NEW", "src/lab/old.py": "DEFER"}
    assert data["deferred"] >= 1
    cli.main(["audit", "--diff", "--repo-dir", str(lab)])
    out = capsys.readouterr().out
    assert "NEW    feature.coverage src/lab/commands/fresh.py" in out and "-> brain features link" in out
    assert "DEFER  feature.coverage src/lab/old.py" in out and "-> wi-debt-lab" in out
    feats = lab / "notes" / "graph" / "nodes" / "features.yaml"   # a title that says it names the added command
    feats.write_text(feats.read_text(encoding="utf-8").replace("lab two-words", "lab two-words, lab fresh"),
                     encoding="utf-8")
    assert _coverage_tags(capsys, lab)[1] == {"src/lab/old.py": "DEFER"}


def test_the_owners_opt_in_makes_a_touched_module_left(make_repo, tmp_path, monkeypatch, capsys):
    folder = tmp_path / "strict-brain"
    folder.mkdir()
    shutil.copy(BRAIN.parent / "rules.md", folder / "rules.md")
    data = json.loads(BRAIN.read_text(encoding="utf-8"))
    data["audit"] = {"feature_coverage_strict": True}
    cfg = folder / "config.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    assert config.check() == [] and feature_coverage.strict(None)   # an optional key the schema declares
    lab = _setup(make_repo, tmp_path, monkeypatch)
    rc, tags, _ = _coverage_tags(capsys, lab)
    assert rc == 1 and tags == {"src/lab/commands/fresh.py": "NEW", "src/lab/old.py": "LEFT"}


def test_the_opt_in_is_off_by_default():
    assert not feature_coverage.strict(None)   # the tests' brain (Ada's) has no audit key
