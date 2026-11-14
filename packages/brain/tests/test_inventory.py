import textwrap
from pathlib import Path

import pytest

from brain import inventory


def mem(files: dict, name: str = "mem") -> inventory.Tree:
    """A tree held in memory (no git): its blobs go to the blob cache."""
    out = {}
    for path, text in files.items():
        data = textwrap.dedent(text).encode()
        sha = inventory._blob_id(data)
        inventory._BLOBS[sha] = data
        out[path] = sha
    return inventory.Tree(Path(name), out, "0" * 40, "2026-11-01", "main")


def test_layouts_src_find_package_dir_flat_and_roots():
    t = mem({"pyproject.toml": '[project.scripts]\na = "a.cli:main"\n[tool.setuptools.packages.find]\n'
                               'where = ["src"]\ninclude = ["a*"]\n',
             "src/a/__init__.py": "", "src/a/cli.py": "def main(): pass\n", "src/b/x.py": "def f(): pass\n"})
    lay = inventory.layout(t)
    assert (lay.roots, lay.tops, lay.scripts) == (["src"], ["a*"], {"a": "a.cli:main"})
    assert set(inventory.module_index(t, lay)[0]) == {"a", "a.cli"}
    lay = inventory.layout(t, ["src"])   # given roots replace the discovered ones and their include filter
    assert lay.tops is None and set(inventory.module_index(t, lay)[0]) == {"a", "a.cli", "b.x"}
    t = mem({"pyproject.toml": '[tool.setuptools]\npackage-dir = {"" = "plugins/core"}\npackages = ["brain"]\n',
             "plugins/core/brain/__init__.py": "", "plugins/core/brain/cli.py": "def main(): pass\n",
             "plugins/core/hooks/x.py": "import sys\n"})
    lay = inventory.layout(t)
    assert lay.roots == ["plugins/core"] and set(inventory.module_index(t, lay)[0]) == {"brain", "brain.cli"}
    t = mem({"pkg/__init__.py": "", "pkg/m.py": "def f(): pass\n", "setup.py": "x = 1\n",
             "loose/n.py": "def g(): pass\n"})
    lay = inventory.layout(t)
    assert lay.roots == [""] and set(inventory.module_index(t, lay)[0]) == {"pkg", "pkg.m"}
    assert inventory.layout(t, ["lib/"]).roots == ["lib"]
    assert inventory.layout(mem({"pyproject.toml": "[project\n"})).roots is None   # unreadable: not measured


def test_units_exclusions_exemptions_waivers_and_commands():
    t = mem({
        "src/p/__init__.py": "from .a import A\n",                  # no def or class: not a unit
        "src/p/sub/__init__.py": "def helper():\n    pass\n",       # a def: a unit
        "src/p/a.py": "class A:\n    pass\n",
        "src/p/__main__.py": "from p.a import A\nA()\n",              # trivial: exempt; the package is a command
        "src/p/job.py": "def run():\n    pass\n\nif __name__ == '__main__':\n    run()\n",   # a command module
        "src/p/tests/test_x.py": "def test(): pass\n", "src/p/conftest.py": "def fx(): pass\n",
        "src/p/_generated_x.py": "def f(): pass\n", "src/p/old.py": "def f(): pass\n",
        "upstream/q/m.py": "def f(): pass\n",
        "scripts/run.ps1": "python -m p\n", "scripts/tool.py": "print(1)\n", "docs/x.sh": "echo\n",
        "tests/test_a.py": "from p.a import A\n", "tests/a.Tests.ps1": "Describe 'a' {}\n",
    })
    rf = inventory.collect(t, "demo", waive={"src/p/old.py": "kept for the 2026 replays"})
    by = {}
    for u in rf.units:
        by.setdefault(u.kind, set()).add(u.path if u.kind != "command" else u.name)
    assert by == {"module": {"src/p/sub/__init__.py", "src/p/a.py", "src/p/job.py"},
                  "script": {"scripts/run.ps1", "scripts/tool.py"}, "command": {"p", "p.job"}}
    assert rf.exempt == ["src/p/__main__.py"] and rf.waived == [("src/p/old.py", "kept for the 2026 replays")]
    assert {"tests/test_a.py", "tests/a.Tests.ps1"} <= set(rf.tests)


def test_docs_set_leaves_out_specs_plans_changelogs_and_journals():
    keep = ["README.md", "sub/README.md", "docs/guide.md", "docs/runbooks/x.md", "notes/runbook.md"]
    drop = ["docs/specs/a.md", "docs/plans/b.md", "docs/superpowers/specs/c.md", "CHANGELOG.md", "notes/journal.md",
            "notes/other.md", "upstream/README.md"]
    assert [p for p in keep + drop if inventory.is_doc(p)] == keep


def test_a_frozen_store_is_no_doc():
    """A brain an older engine wrote, frozen under tests/fixtures/stores (wi-brain-old-store-fixture), is data a test
    reads: its READMEs document nothing of this repo. Any other fixture's README still counts."""
    data = ["tests/fixtures/stores/v0.3.1/brain/README.md", "packages/x/tests/fixtures/stores/v1/README.md",
            "tests/unit/fixtures/stores/a/README.md"]
    kept = ["tests/fixtures/README.md", "tests/fixtures/a/README.md", "fixtures/stores/README.md",
            "docs/fixtures/stores/README.md", "src/fixtures/stores/tests/README.md", "tests/stores/fixtures/README.md"]
    assert [p for p in data + kept if inventory.frozen_store(p)] == data
    assert [p for p in data + kept if inventory.is_doc(p)] == kept


def test_a_frozen_store_s_hook_is_no_test():
    """A frozen store's hooks (guard.sh, capture.sh under tests/fixtures/stores/<tag>/) are data an upgrade test
    reads, not tests: no feature is tested by them, no test.links finding is about them."""
    frozen = ["packages/brain/tests/fixtures/stores/v0.4.0/brain/plugins/brain-core/hooks/guard.sh",
              "tests/fixtures/stores/v1/hooks/x.ps1"]
    tests = ["tests/hooks/guard.sh", "tests/fixtures/fake.sh", "packages/brain/tests/test_x.py"]
    assert [p for p in frozen + tests if inventory.is_test(p)] == tests


def _modules(files, tops=("p",)):
    t = mem(files)
    rf = inventory.collect(t, "demo")
    ev = inventory.evidence(t, rf.tests, set(tops))
    reach = inventory.tests_reach(rf, ev, inventory.Index.build({"demo": rf}))
    mods = [u for u in rf.units if u.kind == "module"]
    stems = {}
    for u in mods:
        stems[inventory.stem(u)] = stems.get(inventory.stem(u), 0) + 1
    rex = inventory.reexports(rf)
    return {u.path[4:]: inventory.module_evidence(u, rf, ev, stems, rex, reach)[0] for u in mods}


def test_module_evidence_each_via_strongest_first():
    vias = _modules({
        "src/p/__init__.py": "from .re import thing\n",
        "src/p/named.py": "def f(): pass\n", "src/p/imported.py": "def f(): pass\n",
        "src/p/re.py": "def thing(): pass\n", "src/p/invoked.py": "def f(): pass\n",
        "src/p/tract.py": "def f(): pass\n", "src/p/bare.py": "def f(): pass\n",
        "src/p/one/cli.py": "def f(): pass\n", "src/p/two/cli.py": "def f(): pass\n",
        "src/p/two/runner.py": "from p.two import cli\n\ndef go(): pass\n",
        "src/p/funding_diff.py": "def f(): pass\n",
        "tests/test_named.py": "def test(): pass\n",
        "tests/test_misc.py": "import p.imported\nfrom p import thing\n\ndef test():\n    run('-m', 'p.invoked')\n",
        "tests/test_extract.py": "def test(): pass\n",           # extract is not tract
        "tests/test_cli.py": "from p.two.runner import go\n",   # an ambiguous stem, confirmed by its imports
        "tests/test_scan_funding_diff.py": "def test(): pass\n",  # test_*_<stem>.py (a project's gate rule)
    })
    assert vias == {"p/named.py": "name", "p/imported.py": "import", "p/re.py": "re-export",
                    "p/invoked.py": "invocation", "p/tract.py": "", "p/bare.py": "",
                    "p/one/cli.py": "", "p/two/cli.py": "name (ambiguous stem)", "p/two/runner.py": "import",
                    "p/funding_diff.py": "name"}


def test_module_evidence_name_of_another_package_fixtures_and_indirect_reach():
    vias = _modules({
        "src/p/__init__.py": "", "src/p/stats/fdr.py": "def bh(): pass\n",
        "src/p/sweep/family_fdr.py": "def f(): pass\n",
        "tests/test_family_fdr.py": "from p.sweep.family_fdr import f\n",   # names fdr.py, tests another package
        "src/p/config.py": "def load(): pass\n",
        "tests/test_graph.py": "FAKE = '''from p.config import load\nrun -m p.config'''\n",   # a fixture
        "src/p/venues/__init__.py": "from p.venues.bitget import B\nfrom p.venues.okx import O\n",
        "src/p/venues/bitget.py": "class B: pass\n", "src/p/venues/okx.py": "class O: pass\n",
        "src/p/venues/deep.py": "class D: pass\n",
        "src/p/venues/base.py": "from p.venues import deep\n\nclass V: pass\n",
        "src/p/cli.py": "from p.venues import base\n\ndef main(): pass\n",
        "tests/test_venues.py": "from p.venues import get_venue\nfrom p.cli import main\n\n"
                                "def test_bitget_funding():\n    get_venue('bitget')\n",
    })
    assert vias["p/stats/fdr.py"] == "" and vias["p/sweep/family_fdr.py"] == "name"
    assert vias["p/config.py"] == ""
    assert vias["p/venues/bitget.py"] == "indirect"              # its package imports it, the test names it
    assert vias["p/venues/okx.py"] == "indirect (unnamed)"       # reached, never named: P2 at most
    assert vias["p/venues/deep.py"] == "indirect (unnamed)"      # two hops away


RUNS = """\
import subprocess

HOOK = ROOT / "scripts" / "e.sh"
CYCLE = "scripts/f.ps1"   # the cycle host (scripts/g.ps1 in a comment)
REF = parse_code_ref("code:lab:scripts/h.ps1")


def _run(name):
    return subprocess.run(["bash", str(ROOT / name)])


def test_runs():
    subprocess.run(["bash", "scripts/c.sh"])
    script = ROOT / "scripts" / "i.ps1"
    cmd = ["pwsh", "-File",
           str(script)]
    out = subprocess.run(
        cmd,
        capture_output=True)
    _run("scripts/j.sh")
    out = subprocess.run(
        [str(HOOK), "x"], text=True)
    assert "scripts/k.ps1 -Register" in out.stdout
"""


def test_script_evidence_name_pester_runs_and_mentioned_only():
    t = mem({**{f"scripts/{n}": "x\n" for n in ("a.ps1", "b.ps1", "c.sh", "d.ps1", "e.sh", "f.ps1", "g.ps1",
                                                  "h.ps1", "i.ps1", "j.sh", "k.ps1")},
             "tests/a.Tests.ps1": "Describe 'a' {}\n", "tests/test_d.py": "def test(): pass\n",
             "tests/test_misc.py": RUNS})
    rf = inventory.collect(t, "demo")
    ev = inventory.evidence(t, rf.tests)
    got = {u.name: inventory.script_evidence(u, ev) for u in rf.units}
    assert {k: v[0] for k, v in got.items()} == {
        "a.ps1": "name", "b.ps1": "", "c.sh": "runs", "d.ps1": "name", "e.sh": "runs", "f.ps1": "", "g.ps1": "",
        "h.ps1": "", "i.ps1": "runs", "j.sh": "runs", "k.ps1": ""}
    assert got["f.ps1"] == ("", ["tests/test_misc.py"]) and got["b.ps1"] == ("", [])   # named, never run


def test_text_imports_by_pattern():
    text = "import a.b as c, d\nfrom .x import (y,\n    z)  # two\nfrom e.f import g as h\n    import i\n"
    assert inventory.text_imports(text) == [("a.b", 0, ()), ("d", 0, ()), ("x", 1, ("y", "z")),
                                            ("e.f", 0, ("g",)), ("i", 0, ())]
    for text in ("from p.alloc import (  # noqa: E402\n    gates,\n    report,\n)\n",
                 "from p.alloc import (\n    gates,  # the rules\n    report,\n)\n"):
        assert inventory.text_imports(text) == [("p.alloc", 0, ("gates", "report"))]


LAB = {
    "pyproject.toml": '[tool.setuptools.packages.find]\nwhere = ["src"]\n',
    "scripts/host.ps1": "# the lab platform\n& $py scripts\\cycle.ps1\n& \"$bin\\qmd-snap.exe\" --x\n",
    "scripts/cycle.ps1": "python -m lab.cli.run --x\n",
    "scripts/unused.ps1": "echo\n",
    "src/lab/__init__.py": "", "src/lab/cli/__init__.py": "",
    "src/lab/cli/run.py": "from lab.core import go\n\ndef main():\n    from ..fam import REG\n    go()\n",
    "src/lab/core.py": "from md.store import save\n\ndef go():\n    pass\n",
    "src/lab/fam/__init__.py": 'REG = {"a": "lab.fam.alpha"}\n',          # a registry of dotted names
    "src/lab/fam/alpha.py": "from lab.fam import beta\n\ndef run():\n    pass\n",
    "src/lab/fam/beta.py": "from lab.fam import alpha\n\ndef run():\n    pass\n",   # a cycle
    "src/lab/idle.py": "def f():\n    pass\n",
}
MD = {"pyproject.toml": '[project.scripts]\nqmd-snap = "md.snap:main"\nlab = "md.other:main"\n'
                        '[tool.setuptools.packages.find]\nwhere = ["src"]\n',
      "src/md/__init__.py": "", "src/md/store.py": "def save():\n    pass\n",
      "src/md/snap.py": "def main():\n    pass\n", "src/md/other.py": "def main():\n    pass\n"}


def _repos():
    repos = {"lab": inventory.collect(mem(LAB), "lab"), "md": inventory.collect(mem(MD), "md")}
    return repos, inventory.Index.build(repos)


def test_closure_from_a_script_seed_into_a_sibling_repo():
    repos, idx = _repos()
    reached, missing = inventory.closure(repos, {"lab": ["scripts/host.ps1", "nope.ps1"]}, idx)
    depth = {f"{r}:{p}": d for (r, p), (d, _) in reached.items()}
    assert depth["lab:scripts/host.ps1"] == 0
    assert depth["lab:scripts/cycle.ps1"] == 1 and depth["md:src/md/snap.py"] == 1   # named by the seed: entry
    assert depth["lab:src/lab/cli/run.py"] == 2 and depth["lab:src/lab/core.py"] == 3
    assert depth["md:src/md/store.py"] == 4                           # the import chain crosses into md
    assert {"lab:src/lab/fam/alpha.py", "lab:src/lab/fam/beta.py"} <= set(depth)   # registry string, cycle
    assert not {"lab:src/lab/idle.py", "lab:scripts/unused.ps1", "md:src/md/other.py"} & set(depth)  # prose 'lab'
    assert missing == {"lab": ["nope.ps1"]}
    assert reached[("lab", "src/lab/fam/alpha.py")][1][:3] == ("host.ps1", "cycle.ps1", "cli.run")


ALLOC = {
    "pyproject.toml": '[tool.setuptools.packages.find]\nwhere = ["src"]\n',
    "scripts/cycle.ps1": "& $py -m lab.alloc shadow --config x\n",
    "scripts/manual.ps1": "python -m lab.tool\n",
    "src/lab/__init__.py": "",
    "src/lab/alloc.py": "import argparse\n\ndef cmd_shadow(a):\n    from lab import report\n\n"
                        "def cmd_publish(a):\n    from lab import gates\n\ndef _load():\n    from lab import cfg\n\n"
                        "def main():\n    sub = argparse.ArgumentParser().add_subparsers()\n"
                        "    sub.add_parser('shadow')\n    sub.add_parser('publish')\n",
    "src/lab/tool.py": "def run():\n    from lab import alloc\n",
    "src/lab/report.py": "def r(): pass\n", "src/lab/gates.py": "def g(): pass\n", "src/lab/cfg.py": "X = 1\n",
}


def test_closure_follows_only_the_subcommand_a_script_runs():
    rf = inventory.collect(mem(ALLOC), "lab")
    idx = inventory.Index.build({"lab": rf})
    got = {p for _, p in inventory.closure({"lab": rf}, {"lab": ["scripts/cycle.ps1"]}, idx)[0]}
    assert {"src/lab/alloc.py", "src/lab/report.py", "src/lab/cfg.py"} <= got   # shadow's import, a helper's
    assert "src/lab/gates.py" not in got                                         # alloc publish stays manual
    assert inventory.subcommand_of("cmd_publish", frozenset({"publish"})) == "publish"
    assert inventory.subcommand_of("_load", frozenset({"publish"})) == ""
    got = {p for _, p in inventory.closure({"lab": rf}, {"lab": ["scripts/cycle.ps1", "scripts/manual.ps1"]},
                                           idx)[0]}
    assert "src/lab/gates.py" in got   # imported by another module: every subcommand may run


def test_module_file_needs_a_main_to_run_a_package():
    rf = inventory.collect(mem({"src/a/__init__.py": "", "src/a/m.py": "def f(): pass\n",
                                "src/b/__init__.py": "", "src/b/__main__.py": "print(1)\n"}), "x")
    idx = inventory.Index.build({"x": rf})
    assert idx.module_file("a", main=True) is None and idx.module_file("a") == ("x", "src/a/__init__.py")
    assert idx.module_file("b", main=True) == ("x", "src/b/__main__.py")
    assert idx.module_file("a.m", main=True) == ("x", "src/a/m.py")


def test_closure_seeds_console_scripts_and_dotted_modules():
    repos, idx = _repos()
    reached, missing = inventory.closure(repos, {"md": ["script:qmd-snap", "md.store", "script:nope"]}, idx)
    assert {k for k, (d, _) in reached.items() if d == 0} == {("md", "src/md/snap.py"), ("md", "src/md/store.py")}
    assert missing == {"md": ["script:nope"]}
    assert inventory.command_at("x\n  lab run\n", "lab") and not inventory.command_at("the lab platform", "lab")


REGISTRY = {   # a command registry (brain.commands): its package lists its modules instead of importing them
    "pyproject.toml": '[project.scripts]\na = "a.cli:main"\n',
    "src/a/__init__.py": "",
    "src/a/cli.py": "from a import commands\n\ndef main():\n    commands.load()\n",
    "src/a/commands/__init__.py": "import importlib\nimport pkgutil\n\n\ndef load():\n    return [importlib.import_module"
                                  "(f'{__name__}.{m.name}') for m in pkgutil.iter_modules(__path__)]\n",
    "src/a/commands/hello.py": "from a import core\n\ndef register(sub, ctx):\n    sub.add_parser('hello')\n",
    "src/a/core.py": "def go(): pass\n",
    "tests/test_cli.py": "from a.cli import main\n\ndef test_main():\n    main()\n",
}


def test_a_package_that_lists_its_modules_imports_each_one():
    """wi-brain-cli-registry: brain's commands are found by pkgutil.iter_modules(__path__); the production closure
    and the tests' reach go through the registry as through an import, or the audit would see none of them."""
    rf = inventory.collect(mem(REGISTRY), "a")
    idx = inventory.Index.build({"a": rf})
    assert inventory.facts(rf.tree, "src/a/commands/__init__.py").discovers
    assert not inventory.facts(rf.tree, "src/a/cli.py").discovers
    reached = inventory.closure({"a": rf}, {"a": ["script:a"]}, idx)[0]
    assert {("a", "src/a/commands/hello.py"), ("a", "src/a/core.py")} <= set(reached)
    vias = _modules(REGISTRY, tops=("a",))
    assert vias["a/commands/hello.py"] == vias["a/core.py"] == "indirect (unnamed)"   # reached by test_cli's import
    alone = dict(REGISTRY, **{"src/a/commands/__init__.py": "def load():\n    return []\n"})
    assert _modules(alone, tops=("a",))["a/commands/hello.py"] == ""   # no listing: nothing reaches it


def test_parse_code_ref_pinned_to_the_engines_grammar():
    p = inventory.parse_code_ref
    assert p("code:demo-data:demo_data/venues/lighter.py::LighterVenue") == (
        "demo-data", "demo_data/venues/lighter.py", "LighterVenue")
    assert p("code:trade-desk:trade_desk/deploy/cross_venue/testnet.py") == (
        "trade-desk", "trade_desk/deploy/cross_venue/testnet.py", "")
    assert p("code:Demo-lab:scripts/alloc_param_sobol.py::evaluate")[0] == "Demo-lab"
    assert p("code:x:a.py::LighterVenue.funding")[2] == "LighterVenue.funding"
    for bad in ("code:x", "code:x:../a.py", "code:x:a.yaml::S", "code:x:a.py::1bad", "codex:x:a.py",
                "code:x:a\\b.py"):
        with pytest.raises(ValueError):
            p(bad)


def test_has_symbol_looks_into_classes_if_and_try():
    t = mem({"m.py": "class A:\n    def b(self): pass\nif X:\n    def c(): pass\n"
                     "try:\n    D = 1\nexcept E:\n    pass\n",
             "bad.py": "def (:\n"})
    assert [inventory.has_symbol(t, "m.py", s) for s in ("A", "A.b", "c", "D", "A.z", "z", "c.x")] == \
        [True, True, True, True, False, False, False]
    assert inventory.has_symbol(t, "bad.py", "A") is None


def test_a_git_failure_raises_and_never_reads_as_an_empty_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "_run_git", lambda repo, args, data=None, timeout=300: (128, b"", b"fatal: bad"))
    with pytest.raises(inventory.AuditError, match="fatal: bad"):
        inventory.git_tree(tmp_path, "main")
    (tmp_path / ".git").mkdir()
    with pytest.raises(inventory.AuditError):
        inventory.reading_ref(tmp_path)


def test_git_tree_week_commits_and_reading_ref(make_repo):
    repo = make_repo("r", {"a.py": "x = 1\n"}, date="2026-10-01T12:00:00Z")
    second = make_repo.commit(repo, {"b.py": "y = 2\n"}, date="2026-10-08T12:00:00Z")
    t = inventory.git_tree(repo, "refs/heads/main", "main")
    assert set(t.files) == {"a.py", "b.py"} and t.rev == second and t.date == "2026-10-08"
    assert t.text("b.py") == "y = 2\n" and t.label == f"main@{second[:7]}"
    assert inventory.reading_ref(repo) == ("refs/heads/main", "main")
    first, none = inventory.week_commits(repo, "HEAD", ["2026-10-05T00:00:00Z", "2026-09-28T00:00:00Z"])
    assert first and first != second and none == ""
