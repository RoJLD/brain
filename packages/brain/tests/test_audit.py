import dataclasses
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from brain import audit, cli, inventory, projects

from conftest import run_git
from test_inventory import mem

README = ("# lab\n\n## Install\n\npip install .\n\n## Usage\n\nRun lab daily.\n\n## Tests\n\npytest\n\n"
          "One.\nTwo.\nThree.\n")
GUARD = "def run():\n    pass\n\nif __name__ == '__main__':\n    run()\n"
FIND = '[tool.setuptools.packages.find]\nwhere = ["src"]\n'


def _measure(repos: dict, cfg: dict | None = None):
    """audit.measure on trees held in memory: the first repo is the project's root, with its store."""
    root = Path("/m") / next(iter(repos))
    p = projects.Project("demo", root, [root / "notes" / "graph"])
    cfgs = [projects.Repo(n, Path("/m") / n, **(cfg or {}).get(n, {})) for n in repos]
    return audit.measure(p, cfgs, {n: mem(files, n) for n, files in repos.items()})


def _found(res, repo=None, info=False):
    return {(f["check"], f["unit"]): f["severity"] for r in res["repos"] if repo in (None, r["name"])
            for f in r["findings"] if info or f["severity"] != "info"}


def test_cmd_documented_forms_and_specs_do_not_count():
    res = _measure({"lab": {
        "pyproject.toml": '[project.scripts]\nlab-run = "lab.cli:main"\nlab-off = "lab.cli:main"\n' + FIND,
        "README.md": README + "Run lab-run.exe daily. python -m lab.prov check. Weekly: make drift.\n"
                              "The hook hooks/capture.sh records the session.\n",
        "docs/guide.md": "`python -m lab.tool` does it. See src/lab/other.py and `stem`.\n"
                         # a catalog names a module by a function of it; a file name in backticks names no module
                         "- `catalog.fit(y)`: the fit. Its settings: `report.yaml`.\n",
        "docs/specs/s.md": "lab-off and lab.hidden are named in a spec only.\n",
        "src/lab/__init__.py": "", "src/lab/cli.py": "def main():\n    pass\n",
        "src/lab/tool.py": GUARD, "src/lab/other.py": GUARD, "src/lab/stem.py": GUARD, "src/lab/hidden.py": GUARD,
        "src/lab/catalog.py": GUARD, "src/lab/report.py": GUARD,
        # python -m lab.prov runs __main__.py, which runs lab.prov.cli: one command
        "src/lab/prov/__init__.py": "", "src/lab/prov/__main__.py": "from .cli import main\nmain()\n",
        "src/lab/prov/cli.py": GUARD,
        # make drift runs -m lab.drift; make hid runs lab.hiddenmk, which no doc names
        "Makefile": "PY := python\ndrift:\n\t$(PY) -m lab.drift --x\nhid:\n\t$(PY) -m lab.hiddenmk\n",
        "src/lab/drift.py": GUARD, "src/lab/hiddenmk.py": GUARD,
        # a package.json bin documented by its package's README, and one with no doc
        "tools/mcp/package.json": '{"bin": {"lab-mcp": "./server.mjs"}}', "tools/mcp/server.mjs": "x\n",
        "tools/mcp/README.md": "# The MCP server\n\nWhat it exposes.\n",
        "tools/other/package.json": '{"bin": {"lab-other": "./o.mjs"}}', "tools/other/o.mjs": "x\n",
        # a command module run through a hook shim whose script the docs name
        "src/lab/capture.py": GUARD, "hooks/capture.py": "import sys\nfrom lab.capture import run\nsys.exit(run())\n",
        "hooks/capture.sh": "python capture.py\n"}})
    assert {u for c, u in _found(res) if c == "cmd.documented"} == {"lab-off", "lab.hidden", "lab.hiddenmk",
                                                                   "lab-other", "lab.report"}
    assert "lab.prov.cli" not in {u.name for u in res["facts"]["lab"].units if u.kind == "command"}


def test_doc_dead_refs_modules_paths_placeholders_and_sibling_repos():
    res = _measure({"lab": {
        "README.md": README + "Run `python -m lab.gone` or -m lab.tool, then scripts/run.ps1 and scripts/gone.ps1.\n"
                     "Not checked: scripts/<name>.ps1, $ROOT/scripts/x.ps1, other/x.py, ../sib/src/x.py, "
                     "-m pip, https://x.org/scripts/y.py.\nIn the sibling repo: src/sib/y.py.\n"
                     "Run python -m lab (a package with no __main__.py) and python -m sib.\n"
                     "| [hb](https://github.com/hummingbot/hummingbot) | Its `scripts/arb.py` opens two legs |\n"
                     "Ours (https://github.com/RoJLD/lab): scripts/gone2.ps1.\n"
                     "Moved to the sibling, then dropped: src/sib/gone.py; ours: src/lab/gone.py.\n",
        "docs/x/b.md": "Next to this doc: scripts/local.ps1.\n", "docs/x/scripts/local.ps1": "x\n",
        "scripts/run.ps1": "x\n", "src/lab/__init__.py": "", "src/lab/tool.py": GUARD},
        "sib": {"src/sib/__init__.py": "", "src/sib/__main__.py": "print(1)\n",
                "src/sib/y.py": "def f():\n    pass\n"}})
    assert _found(res, "lab") == {
        **{(c, u): s for (c, u), s in _found(res, "lab").items() if c != "doc.dead-ref"},
        ("doc.dead-ref", "README.md#-m lab.gone"): "P0", ("doc.dead-ref", "README.md#scripts/gone.ps1"): "P0",
        ("doc.dead-ref", "README.md#-m lab"): "P0", ("doc.dead-ref", "README.md#scripts/gone2.ps1"): "P0",
        ("doc.dead-ref", "README.md#src/lab/gone.py"): "P0",
        ("doc.dead-ref", "README.md#src/sib/gone.py"): "P2"}   # a stale reference into another repo
    why = {f["unit"]: f["why"] for f in res["repos"][0]["findings"]}
    assert why["README.md#-m lab"].endswith("a package with no __main__.py")


CODE = """\
- {id: repo-lab, type: Repo, status: active, title: lab}
- {id: "code:lab:lab/core.py::go", type: CodeRef, status: active, title: ok}
- {id: "code:lab:scripts/s.py", type: CodeRef, status: active, title: "ok, from the root"}
- {id: "code:lab:lab/core.py::nope", type: CodeRef, status: active, title: gone symbol}
- {id: "code:lab:lab/gone.py", type: CodeRef, status: active, title: gone file}
- {id: "code:lab:lab/old.py", type: CodeRef, status: retired, title: retired}
- {id: "code:lab:../x.py", type: CodeRef, status: active, title: malformed}
- {id: "code:other:x.py", type: CodeRef, status: active, title: unregistered repo}
- {id: "code:sib:sib/m.py::f", type: CodeRef, status: active, title: ok in a sibling}
"""


def test_coderefs_dangling_measured_module_layer_and_pending_code_layer():
    res = _measure({"lab": {
        "notes/graph/schema.yaml": "node_types: [WorkItem, CodeRef, Repo]\n", "notes/graph/nodes/code.yaml": CODE,
        "README.md": README, "src/lab/__init__.py": "", "src/lab/core.py": "def go():\n    pass\n",
        "src/lab/extra.py": "def x():\n    pass\n", "scripts/s.py": "print(1)\n",
        "tests/test_core.py": "x\n", "tests/test_extra.py": "x\n", "tests/test_s.py": "x\n"},
        "sib": {"README.md": README, "src/sib/__init__.py": "", "src/sib/m.py": "def f():\n    pass\n",
                "tests/test_m.py": "x\n"}}, {"lab": {"folder": "Lab"}})
    found = _found(res)
    assert {u for c, u in found if c == "coderef.dangling"} == {"code:lab:lab/core.py::nope", "code:lab:lab/gone.py",
                                                                "code:lab:../x.py"}
    assert all(found[("coderef.dangling", u)] == "P0" for c, u in found if c == "coderef.dangling")
    assert {u for c, u in found if c == "coderef.module"} == {"src/lab/extra.py"}   # sib has no repo-sib node
    lab, sib = res["repos"]
    fix = next(f["fix"] for f in lab["findings"] if f["check"] == "coderef.module")
    assert fix.startswith("add code:Lab:lab/extra.py ")   # the folder's case: the engine's code-check needs it
    assert {"check": "coderef.dangling", "owner": "CodeRefs of unregistered repos: other"} in lab["not_measured"]
    assert "code.layer" in [x["check"] for x in sib["not_measured"]]
    assert "code.layer" not in [x["check"] for x in lab["not_measured"]]


def test_readme_exists_and_sections():
    res = _measure({"a": {"src/a/__init__.py": "", "src/a/m.py": "def f():\n    pass\n", "tests/test_m.py": "x\n"},
                    "b": {"README.md": "# b\nshort\n", "src/b/__init__.py": "def f():\n    pass\n"},
                    "sample-backtest": {"README.md": "# sample-backtest\n" + "text\n" * 9 + "## Install\n## Example\n"
                                        "```\n## Tests\n```\n", "src/h/__init__.py": "def f():\n    pass\n"},
                    "conf": {"README.md": "# conf\n" + "text\n" * 12}})
    found = _found(res)
    assert found[("readme.exists", "README.md")] == "P0"
    assert [r["findings"][0]["why"] for r in res["repos"][:2]] == [
        "no README.md at the root", "README.md has 2 non-blank line(s) (10 at least)"]
    assert {u for c, u in _found(res, "sample-backtest") if c == "readme.sections"} == {"README.md#tests"}
    assert _found(res, "conf") == {}                                    # no code: no sections asked


@pytest.mark.parametrize("check, cls, sev", [
    ("test.module", "entry", "P1"), ("test.module", "prod", "P1"), ("test.module", "other", "P2"),
    ("test.script", "prod", "P1"), ("test.script", "other", "P2"), ("cmd.documented", "entry", "P1"),
    ("cmd.documented", "other", "P2"), ("coderef.module", "entry", "P2"), ("readme.sections", "entry", "P2"),
    ("readme.exists", "", "P0"), ("doc.dead-ref", "other", "P0"), ("coderef.dangling", "", "P0")])
def test_severity_by_check_and_class(check, cls, sev):
    assert audit.severity(check, cls) == sev


def test_classes_from_entries_defaults_and_the_no_entry_fallback():
    files = {"README.md": README, "src/{n}/__init__.py": "", "src/{n}/cli.py": "from {n} import core\n\ndef main():\n"
             "    core.go()\n", "src/{n}/core.py": "def go():\n    pass\n", "src/{n}/idle.py": "def f():\n    pass\n"}

    def mk(n, extra=""):
        return {**{k.format(n=n): v.format(n=n) for k, v in files.items()}, "pyproject.toml": extra + FIND}

    res = _measure({"seeded": mk("seeded"), "default": mk("default", '[project.scripts]\nd = "default.cli:main"\n'),
                    "noseed": mk("noseed"), "lib": mk("lib"), "moved": mk("moved")},
                   {"seeded": {"production": True, "entry": ["seeded.cli"]}, "default": {"production": True},
                    "noseed": {"production": True}, "lib": {}, "moved": {"entry": ["script:gone", "hooks/moved.json"]}})
    cls = {r["name"]: (r["classes"], r["no_entry"]) for r in res["repos"]}
    assert cls["seeded"] == ({"entry": 2, "prod": 0, "other": 1}, False)
    assert cls["default"] == ({"entry": 3, "prod": 0, "other": 1}, False)   # the console script d is a unit too
    assert cls["noseed"] == ({"entry": 0, "prod": 3, "other": 0}, True)     # conservative: everything production
    assert cls["lib"] == ({"entry": 0, "prod": 0, "other": 3}, False)
    assert cls["moved"] == ({"entry": 0, "prod": 3, "other": 0}, True)      # production through its entries (Q4)
    found = _found(res, "noseed")
    assert found[("test.module", "src/noseed/idle.py")] == "P1"
    assert _found(res, "moved")[("test.module", "src/moved/idle.py")] == "P1"


def test_a_hook_shim_takes_its_module_evidence():
    res = _measure({"lab": {"README.md": README, "src/lab/__init__.py": "",
                            "src/lab/cap.py": "def main():\n    pass\n",
                            "hooks/cap_hook.py": "import sys\nfrom lab.cap import main\nsys.exit(main())\n",
                            "hooks/bare.py": "import sys\nfrom lab.cap import main\nprint(1)\n" + "x = 1\n" * 20,
                            "tests/test_cap.py": "from lab.cap import main\n"}})
    found = _found(res, info=True)
    assert found[("test.script", "hooks/cap_hook.py")] == "info" and found[("test.script", "hooks/bare.py")] == "P2"


# --- the command, on git repos ---

SCHEMA = ("node_types: [WorkItem, Milestone, Spec]\nedge_types: [specified_by, depends_on, part_of, decided_by]\n"
          "statuses: [active, todo, doing, done, dropped, pending, reached]\n"
          "status_by_type:\n  WorkItem: [todo, doing, done, dropped]\n")
LAB = {"README.md": README, "pyproject.toml": '[project.scripts]\nlab = "lab.cli:main"\n' + FIND,
       "src/lab/__init__.py": "", "src/lab/cli.py": "from lab import core\n\ndef main():\n    core.go()\n",
       "src/lab/core.py": "def go():\n    pass\n", "src/lab/extra.py": "def x():\n    pass\n",
       "tests/test_cli.py": "from lab.cli import main\n", "tests/test_core.py": "from lab.core import go\n",
       "notes/graph/schema.yaml": SCHEMA, "notes/graph/edges/work.yaml": "# edges\n",
       "notes/graph/nodes/work.yaml": '- {id: spec-x, type: Spec, status: active, title: "Spec X"}\n'
                                      '- {id: ms-x, type: Milestone, status: pending, title: "M"}\n'}


def _registry(tmp_path, monkeypatch, root, extra=""):
    f = tmp_path / "projects.yaml"
    f.write_text(f"demo: {{root: {root.as_posix()}, production: [.], audit: {{spec: spec-x}}{extra}}}\n",
                 encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    return f


def test_cli_text_json_repo_filter_fail_on_and_help(make_repo, tmp_path, monkeypatch, capsys):
    lab = make_repo("lab", LAB)
    _registry(tmp_path, monkeypatch, lab)
    assert cli.main(["--project", "demo", "audit"]) == 0
    out = capsys.readouterr().out
    assert "lab  " in out and "P0 0  P1 0  P2 1" in out and "not measured: readme.yaml" in out
    assert cli.main(["--project", "demo", "audit", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"audit", "ruleset", "projects"} and data["ruleset"] == audit.RULESET
    r = data["projects"][0]["repos"][0]
    assert set(r) == {"name", "path", "production", "commit", "date", "counts", "classes", "no_entry",
                      "missing_entries", "findings", "not_measured", "waived", "exempt"}
    assert set(r["findings"][0]) == {"key", "check", "severity", "unit", "class", "chain", "via", "why", "fix"}
    assert r["findings"][0]["key"] == "lab:test.module:src/lab/extra.py"
    assert cli.main(["--project", "demo", "audit", "--fail-on", "P1"]) == 0   # P2 debt and pending checks only
    assert cli.main(["--project", "demo", "audit", "--fail-on", "P2"]) == 1
    assert cli.main(["--project", "demo", "audit", "--repo", "nope"]) == 2
    assert "unknown repo(s) nope" in capsys.readouterr().err
    assert "brain audit" in cli.build_parser().format_help()
    with pytest.raises(SystemExit, match="not --repo"):   # the view is the whole project's
        cli.main(["--project", "demo", "audit", "--write", "--repo", "lab"])
    cli.main(["--project", "demo", "audit"])
    assert f"(calibrated {audit.CALIBRATED[:10]})" in capsys.readouterr().out
    monkeypatch.setattr(audit, "CALIBRATED", "")
    cli.main(["--project", "demo", "audit"])
    assert "(uncalibrated: wi-brain-scout-rule" in capsys.readouterr().out


def test_git_failure_and_registry_errors_exit_2(make_repo, tmp_path, monkeypatch, capsys):
    lab = make_repo("lab", LAB)
    _registry(tmp_path, monkeypatch, lab, ", repos: [{path: ., waive: {'src/*': short}}]")
    assert cli.main(["--project", "demo", "audit"]) == 2
    assert "15 characters" in capsys.readouterr().err
    _registry(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(inventory, "_run_git", lambda repo, args, data=None, timeout=300: (128, b"", b"fatal: x"))
    assert cli.main(["--project", "demo", "audit"]) == 2
    assert "fatal: x" in capsys.readouterr().err
    assert cli.main(["--project", "nope", "audit"]) == 2


@pytest.mark.parametrize("bad, message", [
    ("[{path: ., lang: go}]", "lang is py or ts"), ("[{path: ., color: red}]", "unknown key(s) color"),
    ("[., .]", "listed twice"), ("[{path: ., name: Bad Name}]", "a name is lowercase"),
    ("[{path: ., scout_limit: -1}]", "scout_limit"), ("x", "a list of paths")])
def test_repos_entries_are_validated(tmp_path, bad, message):
    p = projects.Project("demo", tmp_path, repos=yaml.safe_load(bad))
    with pytest.raises(projects.RepoError, match=message.replace("(", r"\(").replace(")", r"\)")):
        projects.repos_of(p)


def test_repos_default_the_root_and_the_production_checkouts(tmp_path):
    (tmp_path / "lab").mkdir()
    (tmp_path / "md").mkdir()
    p = projects._project("demo", {"production": [".", "../md"]}, tmp_path / "lab")
    got = projects.repos_of(p)
    assert [(r.name, r.production, r.entry, r.item, r.scout_limit) for r in got] == [
        ("lab", True, None, "", 3), ("md", True, None, "", 3)]


def _weekly(make_repo, name, start_untested, dates, root_files=None):
    """A repo whose untested modules go from start_untested down by one at each date."""
    files = dict(root_files or {"README.md": README, "pyproject.toml": FIND, "src/w/__init__.py": ""})
    files.update({f"src/w/m{i}.py": "def f():\n    pass\n" for i in range(start_untested)})
    repo = make_repo(name, files, date=dates[0])
    for k, d in enumerate(dates[1:], 1):
        make_repo.commit(repo, {f"tests/test_m{k - 1}.py": "x\n"} if k <= start_untested else {}, date=d)
    return repo


def test_trend_falling_flat_week_and_like_for_like_window(make_repo):
    weeks = ["2026-09-30T12:00:00Z", "2026-10-07T12:00:00Z", "2026-10-14T12:00:00Z", "2026-10-21T12:00:00Z",
             "2026-10-28T12:00:00Z"]
    a = _weekly(make_repo, "a", 5, weeks)
    late = _weekly(make_repo, "late", 2, weeks[2:])
    p = projects.Project("demo", a)
    cfgs = [projects.Repo("a", a), projects.Repo("late", late)]
    refs = {"a": "refs/heads/main", "late": "refs/heads/main"}
    t = audit.trend(p, cfgs, refs, 5, date(2026, 11, 2))
    assert [w["week"] for w in t["weeks"]] == ["2026-W40", "2026-W41", "2026-W42", "2026-W43", "2026-W44"]
    assert [audit._total(w) for w in t["weeks"]] == [5, 4, 3, 2, 1]
    assert t["left"] == ["late"] and t["repos"] == ["a"]               # no commit before W40's end: out
    assert audit.falling([5, 4, 3, 2, 1]) == 4 and "falling 4 of 4" in audit.trend_line(t)
    assert audit.falling([5, 4, 4, 3, 2]) == 2 and audit.falling([3, 2, 0, 0, 0]) == 4   # zero counts as falling
    assert audit.week_ends(1, date(2026, 11, 8)) == [("2026-W44", "2026-11-02T00:00:00Z")]
    assert audit.trend(p, cfgs[1:], refs, 5, date(2026, 11, 2))["weeks"] == []   # nothing over the window
    layer = {"notes/graph/schema.yaml": "node_types: [CodeRef, Repo]\n",
             "notes/graph/nodes/code.yaml": "- {id: repo-a, type: Repo, status: active, title: a}\n"}
    make_repo.commit(a, layer, date="2026-10-29T12:00:00Z")   # a code layer arrives in the last week
    p = projects.Project("demo", a, [a / "notes" / "graph"])
    now = audit.measure(p, cfgs[:1], {"a": inventory.git_tree(a, "HEAD")})
    assert now["layered"] == {"a"}
    t = audit.trend(p, cfgs[:1], refs, 5, date(2026, 11, 2), None, now["layered"])
    assert [audit._total(w) for w in t["weeks"]] == [10, 9, 8, 7, 6]   # coderef.module counted in every week


def test_milestone_needs_every_repo_no_p0_p1_no_pending_and_four_falls(monkeypatch):
    ok = {"counts": {"P0": 0, "P1": 0, "P2": 3}, "repos": [{"name": "a"}]}
    tr = {"weeks": [{}], "falling": 4}
    assert not audit.milestone([ok], tr)["met"]                         # generator checks still pending
    assert "1 P0/P1 checks not measured" in audit.milestone([ok], tr)["reasons"]   # readme.generated: features.md,
    #                                    feature.links, readme.yaml and help.quoted run (wi-brain-readme-sync)
    unopted = {**ok, "repos": [{"name": "a", "not_measured": [{"check": "readme.yaml", "owner": audit.NO_README}]}]}
    assert audit.milestone([unopted], tr)["pending"] == ["readme.generated", "readme.yaml"]   # not opted in: pending
    monkeypatch.setattr(audit, "PENDING", {k: dataclasses.replace(v, run=len) for k, v in audit.PENDING.items()})
    assert audit.milestone([ok], tr)["met"]
    unfeatured = {**ok, "repos": [{"name": "a", "not_measured": [{"check": "features.md", "owner": audit.NO_FEATURES},
                                                                 {"check": "doc.links", "owner": "x"}]}]}
    m = audit.milestone([unfeatured], tr)   # a generator's check that cannot run in that project still blocks
    assert not m["met"] and m["pending"] == ["features.md"]
    assert not audit.milestone([ok], {"weeks": [{}], "falling": 3})["met"]
    assert not audit.milestone([ok], None)["met"]
    assert not audit.milestone([{**ok, "counts": {"P0": 0, "P1": 1, "P2": 0}}], tr)["met"]
    assert not audit.milestone([{**ok, "repos": [{"name": "a", "error": "x not found"}]}], tr)["met"]
    blind = {**ok, "repos": [{"name": "a", "not_measured": [{"check": "test.module",
                                                             "owner": "pyproject.toml needs Python 3.11+ (tomllib)"}]}]}
    m = audit.milestone([blind], tr)   # its modules could not be read: not audited
    assert not m["met"] and m["reasons"][0] == "not audited: a (pyproject.toml needs Python 3.11+ (tomllib))"


class _Today(date):
    @classmethod
    def today(cls):
        return date(2026, 11, 2)


def test_all_projects_trend_json_milestone_and_a_repo_filter(make_repo, tmp_path, monkeypatch, capsys):
    weeks = ["2026-09-30T12:00:00Z", "2026-10-07T12:00:00Z", "2026-10-14T12:00:00Z", "2026-10-21T12:00:00Z",
             "2026-10-28T12:00:00Z"]
    a, b = _weekly(make_repo, "a", 5, weeks), _weekly(make_repo, "b", 2, weeks)
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"one: {{root: {a.as_posix()}}}\ntwo: {{root: {b.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(audit, "date", _Today)
    assert cli.main(["audit", "--all", "--trend", "5", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"audit", "ruleset", "projects", "trend", "milestone"}
    assert [w["week"] for w in data["trend"]["weeks"]] == ["2026-W40", "2026-W41", "2026-W42", "2026-W43",
                                                           "2026-W44"]
    assert [w["by_project"] for w in data["trend"]["weeks"]][0] == {"one": 5, "two": 2}
    assert [sum(w["debt"].values()) for w in data["trend"]["weeks"]] == [7, 5, 3, 2, 1]   # summed across projects
    assert data["trend"]["falling"] == 4 and data["trend"]["projects"] == ["one", "two"]
    assert data["milestone"]["id"] == "ms-brain-conformance" and not data["milestone"]["met"]
    assert cli.main(["audit", "--all", "--trend", "5"]) == 0
    lines = capsys.readouterr().out.rstrip().splitlines()
    assert lines[-1].startswith("ms-brain-conformance: not met (P0 0, P1 0; 5 P0/P1 checks not measured; falling 4")
    assert cli.main(["audit", "--all", "--repo", "b", "--json"]) == 0   # one repo: no milestone evidence
    data = json.loads(capsys.readouterr().out)
    assert [p["name"] for p in data["projects"]] == ["two"]
    assert data["milestone"]["reasons"] == ["not evaluated: --repo narrows the scope"]


def test_view_refused_on_main_written_from_a_branch_and_left_unchanged(make_repo, tmp_path, monkeypatch, capsys):
    lab = make_repo("lab", LAB)
    _registry(tmp_path, monkeypatch, lab)
    with pytest.raises(SystemExit, match="main checkout on main"):
        cli.main(["--project", "demo", "audit", "--write"])
    run_git(lab, "checkout", "-q", "-b", "feature")
    assert cli.main(["--project", "demo", "audit", "--write"]) == 0
    view = (lab / audit.VIEW).read_text(encoding="utf-8")
    assert view.startswith("# Conformance audit — demo\n\nGENERATED by `brain audit --write`. Do not edit")
    assert "## lab\n" in view and "`src/lab/extra.py` (other)" in view and "## Trend" in view
    assert "view: notes/audit.md written" in capsys.readouterr().out
    assert cli.main(["--project", "demo", "audit", "--write"]) == 0
    assert "view: notes/audit.md unchanged" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="one project"):
        cli.main(["audit", "--all", "--write"])


def test_items_created_once_then_priority_proposed_only_never_linked(make_repo, tmp_path, monkeypatch, capsys):
    lab = make_repo("lab", LAB)
    _registry(tmp_path, monkeypatch, lab)
    run_git(lab, "checkout", "-q", "-b", "feature")
    store = lab / "notes" / "graph"
    assert cli.main(["--project", "demo", "audit", "--items"]) == 0
    nodes = {n["id"]: n for n in yaml.safe_load((store / "nodes" / "work.yaml").read_text(encoding="utf-8"))}
    assert nodes["wi-debt-lab"]["props"] == {"priority_proposed": "P2", "theme": "3.18", "audit_repo": "lab",
                                            "report": "notes/audit.md#lab"}
    edges = yaml.safe_load((store / "edges" / "work.yaml").read_text(encoding="utf-8"))
    assert edges == [{"from": "wi-debt-lab", "to": "spec-x", "type": "specified_by"}]   # no milestone edge
    before = {f: f.read_bytes() for f in store.rglob("*.yaml")}
    assert cli.main(["--project", "demo", "audit", "--items"]) == 0
    assert {f: f.read_bytes() for f in store.rglob("*.yaml")} == before   # a rerun changes nothing
    run_git(lab, "checkout", "-q", "main")
    run_git(lab, "add", "-A")
    run_git(lab, "commit", "-q", "-m", "item")
    (lab / "pyproject.toml").write_text(LAB["pyproject.toml"].replace('lab = "lab.cli:main"\n', 'lab = "lab.cli:main"\n'
                                        'lab-hidden = "lab.cli:main"\n'), encoding="utf-8")   # undocumented entry: P1
    run_git(lab, "add", "-A")
    run_git(lab, "commit", "-q", "-m", "fresh")
    run_git(lab, "checkout", "-q", "-b", "feature2")
    graph_set = []
    real = audit.graph.set_item
    monkeypatch.setattr(audit.graph, "set_item", lambda s, n, a: graph_set.append((n, a)) or real(s, n, a))
    capsys.readouterr()
    assert cli.main(["--project", "demo", "audit", "--items"]) == 0
    assert graph_set == [("wi-debt-lab", ["priority_proposed=P1"])]
    assert "item: wi-debt-lab set priority_proposed=P1" in capsys.readouterr().out


def test_items_map_to_a_named_item_note_a_validated_priority_and_warn_without_workitem(make_repo, tmp_path,
                                                                                       monkeypatch, capsys):
    retro = '- {id: wi-retro, type: WorkItem, status: todo, title: "R",\n   props: {priority: P1}}\n'
    lab = make_repo("lab", {**LAB, "notes/graph/nodes/work.yaml": LAB["notes/graph/nodes/work.yaml"] + retro})
    _registry(tmp_path, monkeypatch, lab, ", repos: [{path: ., item: wi-retro}]")
    run_git(lab, "checkout", "-q", "-b", "feature")
    assert cli.main(["--project", "demo", "audit", "--items"]) == 0
    out = capsys.readouterr().out
    assert "note: wi-retro has the validated priority P1; the measure suggests P2" in out
    node = graph_node(lab, "wi-retro")
    assert node["props"] == {"priority": "P1", "audit_repo": "lab", "report": "notes/audit.md#lab",
                             "priority_proposed": "P2"}
    (lab / "notes" / "graph" / "schema.yaml").write_text("node_types: [Spec]\n", encoding="utf-8")
    assert cli.main(["--project", "demo", "audit", "--items"]) == 0
    assert "has no WorkItem type" in capsys.readouterr().out


def graph_node(root, nid):
    return {n["id"]: n for n in yaml.safe_load((root / "notes" / "graph" / "nodes" / "work.yaml").read_text(
        encoding="utf-8"))}[nid]


def test_dogfood_the_audit_modules_pass_their_own_test_module_check():
    repo = Path(__file__).resolve().parents[1]
    if not (repo / ".git").exists():
        pytest.skip("not a git checkout")
    rf = inventory.collect(inventory.work_tree(repo), "brain")
    ev = inventory.evidence(rf.tree, rf.tests, {"brain"})
    reach = inventory.tests_reach(rf, ev, inventory.Index.build({"brain": rf}))
    mods = {u.name: u for u in rf.units if u.kind == "module"}
    for name in ("brain.inventory", "brain.audit", "brain.scout"):
        assert inventory.module_evidence(mods[name], rf, ev, {}, {}, reach)[0] == "name", name
