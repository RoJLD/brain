"""Regressions of the review of brain #38 (tests linked and coverage measured): a stale or context-less coverage
summary never strips tests, the def lines are no execution, branch data and odd paths are read, the repo's
fail_under is not the report's, sync and audit read the summary alike, the trend reads today's summary, only real
imports count."""

import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from brain import audit, features, links, projects, testcov

from test_inventory import mem
from test_links_auto import CLI, _data_file, _files, _summary, _tested


# --- 1 and 5: a stale summary narrows only what it measured ---

def test_a_symbol_added_since_the_summary_keeps_the_names_rule():
    cli = CLI + "\n\ndef cmd_new_thing(args):\n    return 2\n"
    files = _files(**{
        "src/p/cli.py": cli,
        "notes/graph/coverage/demo.json": _summary({"tests/test_run.py": ["cmd_run_job", "main"]}),
        "tests/test_new.py": "from p import cli\n\n\ndef test_new():\n    assert cli.main(['new', 'thing'])\n"})
    files["notes/graph/nodes/work.yaml"] += ('- {id: feat-new, type: Feature, status: have, title: "New",'
                                             ' props: {repo: demo, domain: jobs}}\n')
    files["notes/graph/edges/work.yaml"] += ('- {from: feat-new, to: "code:demo:p/cli.py::cmd_new_thing",'
                                             ' type: implemented_by}\n')
    got = _tested(links.derive(mem(files, "demo"), "demo"))
    assert got["feat-new"] == {"test_new.py"}   # the summary never saw cmd_new_thing: not "no test runs it"
    assert got["feat-run"] == {"test_run.py"}


def test_a_test_added_since_the_summary_keeps_the_names_rule():
    files = _files(**{
        "notes/graph/coverage/demo.json": _summary({"tests/test_run.py": ["cmd_run_job", "main"]}),
        "tests/test_run_new.py": "from p import cli\n\n\ndef test_again():\n    assert cli.main(['run', 'job'])\n"})
    got = _tested(links.derive(mem(files, "demo"), "demo"))
    assert got["feat-run"] == {"test_run.py", "test_run_new.py"}


# --- 2 and 4: branch data is read; a summary with no test context is refused, an old one ignored ---

def test_branch_coverage_arcs_give_the_contexts(tmp_path):
    root = tmp_path / "demo"
    (root / "src" / "p").mkdir(parents=True)
    (root / "src" / "p" / "cli.py").write_text(CLI, encoding="utf-8")
    data = tmp_path / ".coverage"
    _data_file(data, root)
    db = sqlite3.connect(data)
    db.execute("delete from line_bits")   # branch = true: coverage writes arcs, not lines
    db.executemany("insert into arc values (?, ?, ?, ?)", [(1, 2, -4, 5), (1, 2, 5, -4), (1, 3, 9, -8)])
    db.commit()
    db.close()
    ctxs, _ = testcov.contexts(data, root, root)
    assert ctxs == {"src/p/cli.py": {5: {"tests/test_run.py"}, 9: {"tests/test_other.py"}}}


def test_a_data_file_without_test_contexts_is_refused(tmp_path):
    root = tmp_path / "demo"
    (root / "src" / "p").mkdir(parents=True)
    (root / "src" / "p" / "cli.py").write_text(CLI, encoding="utf-8")
    rep = {"files": {"src/p/cli.py": {"summary": {"num_statements": 9}, "executed_lines": [1, 4, 5]}}}
    with pytest.raises(testcov.CoverageError, match="--cov-context=test"):
        testcov.summarize([(rep, {}, root)], root, "demo")
    # a version 1 summary (no functions, no test_modules) is not read: the static rule applies
    old = json.loads(_summary({"tests/test_run.py": ["main"]}))
    old["version"] = 1
    got = _tested(links.derive(mem(_files(**{"notes/graph/coverage/demo.json": json.dumps(old)}), "demo"), "demo"))
    assert got["feat-run"] == {"test_run.py"}
    no_ctx = json.loads(_summary({}, seen=[]))
    got = _tested(links.derive(mem(_files(**{"notes/graph/coverage/demo.json": json.dumps(no_ctx)}), "demo"), "demo"))
    assert got["feat-run"] == {"test_run.py"} and got["feat-check"] == {"test_guards.py"}


# --- 3 and 12: what counts as running a function ---

def test_an_import_runs_no_function_and_a_function_under_if_counts():
    src = ("import os\n\n\ndef f():\n    return 1\n\n\nif os.name == 'nt':\n    def g():\n        return 2\n"
           "else:\n    def g():\n        return 3\n\ntry:\n    import x\nexcept ImportError:\n    def h():\n"
           "        return 4\n")
    fn = testcov.functions(src)
    assert 4 not in fn and fn[5] == "f"   # the def line runs at import
    assert fn[10] == "g" and fn[13] == "g" and fn[19] == "h"
    assert 8 not in fn and 9 not in fn


# --- 6: the repo's fail_under is not the report's ---

def test_fail_under_is_turned_off_for_the_run_and_the_report(tmp_path, monkeypatch):
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        if "json" in cmd:
            Path(cmd[cmd.index("-o") + 1]).write_text('{"files": {}}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(testcov.subprocess, "run", fake)
    monkeypatch.setattr(testcov, "contexts", lambda data, root, cwd: ({"src/p/cli.py": {5: {"tests/test_a.py"}}}, "7"))
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    with pytest.raises(testcov.CoverageError, match="no test context"):   # no file in the stub's report
        testcov.run(tmp_path, "demo", ["tests/test_a.py"], ["src"], python="py")
    pytest_cmd = next(c for c in calls if "pytest" in c)
    json_cmd = next(c for c in calls if "json" in c)
    assert "--cov-fail-under=0" in pytest_cmd and "--fail-under=0" in json_cmd


# --- 7: brain sync reads the summary as brain audit does ---

def test_sync_and_audit_read_the_same_summary(make_repo):
    summary = _summary({})
    root = make_repo("demo", {**_files(), ".gitignore": "ignored/\n"})
    store = root / "notes" / "graph"
    (store / "coverage").mkdir()
    (store / "coverage" / "demo.json").write_bytes(b"\xef\xbb\xbf" + summary.encode("utf-8"))   # a BOM
    m = features.load_store(store, "demo")
    assert features.coverage_of(m, "feat-core") == 100.0   # read through the tree, as the audit reads it
    (root / ".gitignore").write_text("notes/graph/coverage/\n", encoding="utf-8")
    assert features.load_store(store, "demo").coverage == {}   # an ignored summary is nobody's


# --- 8: the trend reads today's summary ---

def test_the_trend_measures_test_coverage_with_todays_summary():
    root = Path("/m/demo")
    p = projects.Project("demo", root, [root / "notes" / "graph"])
    today = audit.measure(p, [projects.Repo("demo", root)],
                          {"demo": mem(_files(**{"notes/graph/coverage/demo.json": _summary({})}), "demo")})
    week = audit.measure(p, [projects.Repo("demo", root)], {"demo": mem(_files(), "demo")},
                         layered=today["layered"], linked=today["linked"], featured=today["featured"],
                         coverage=today["coverage"])
    assert [f["unit"] for f in week["repos"][0]["findings"] if f["check"] == "test.coverage"] == ["src/p/lonely.py"]
    assert "coverage" not in audit._public(today)


# --- 9: only real imports and -m count ---

def test_a_dotted_name_in_a_string_is_no_import():
    files = _files(**{
        "tests/test_strings.py": "from p import core\n\n\ndef test_names():\n"
                                 "    assert {'p', 'p.cli'} and core.go()  # the run job, said p.cli\n",
        "tests/test_dash_m.py": "import subprocess\n\n\ndef test_m():\n"
                                "    subprocess.run(['python', '-m', 'p.cli', 'run', 'job'])\n"})
    got = _tested(links.derive(mem(files, "demo"), "demo"))
    assert "test_strings.py" not in got["feat-run"]   # p.cli only in a string: not an import
    assert "test_dash_m.py" in got["feat-run"]   # "-m", "p.cli" runs it


# --- 10: a data file under a path with '#' or '%' ---

def test_a_data_file_path_with_a_hash_or_a_percent(tmp_path):
    root = tmp_path / "demo"
    (root / "src" / "p").mkdir(parents=True)
    (root / "src" / "p" / "cli.py").write_text(CLI, encoding="utf-8")
    for odd in ("c#x", "a%41b"):
        (tmp_path / odd).mkdir()
        data = tmp_path / odd / ".coverage"
        _data_file(data, root)
        ctxs, _ = testcov.contexts(data, root, root)
        assert ctxs["src/p/cli.py"][5] == {"tests/test_run.py"}
    assert not (tmp_path / "c").exists()   # no stray file where the URI was cut


# --- the CI measures the coverage (wi-brain-test-coverage) ---

def test_the_ci_keeps_a_coverage_data_file_brain_coverage_reads():
    import yaml
    root = Path(__file__).resolve().parents[3]
    ci = yaml.safe_load((root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = {s.get("name"): s for s in ci["jobs"]["brain"]["steps"]}
    run = steps["Tests"]
    assert run["working-directory"] == "packages/brain" and run["env"]["COVERAGE_FILE"] == "coverage.data"
    assert "--cov-context=test" in run["run"] and "--cov-fail-under=0" in run["run"]
    assert steps["Coverage data"]["with"]["path"] == "packages/brain/coverage.data"
    assert "relative_files = true" in (root / "packages" / "brain" / "pyproject.toml").read_text(encoding="utf-8")


# --- wi-brain-coverage-map-refresh: the map read in a worktree, and from the CI after a merge ---

def test_a_data_file_is_read_against_the_checkout_that_holds_its_cwd(make_repo, tmp_path):
    repo = make_repo("lab", {"src/p/__init__.py": "", "tests/test_a.py": "def test_a():\n    pass\n"})
    wt = tmp_path / "wt-lab"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(wt)], check=True,
                   capture_output=True)
    assert testcov.checkout_of(wt / "src", repo).resolve() == wt.resolve()       # a worktree of the repo: its own
    assert testcov.checkout_of(repo / "src", repo).resolve() == repo.resolve()
    other = make_repo("other", {"x.py": ""})
    assert testcov.checkout_of(other, repo) == repo                               # another repo: the registered one
    assert testcov.checkout_of(tmp_path / "nowhere", repo) == repo


class _Gh:
    """A fake gh: each call's answer in turn (a CompletedProcess, or an exception to raise); the calls kept."""

    def __init__(self, *answers, files=None):
        self.answers, self.calls, self.files = list(answers), [], files or {}

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        if argv[1:3] == ["run", "download"]:
            for rel, text in self.files.items():
                f = Path(argv[argv.index("-D") + 1]) / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text, encoding="utf-8")
        return a


def _ok(out=""):
    return subprocess.CompletedProcess(["gh"], 0, out, "")


def test_from_ci_reads_the_data_file_of_heads_green_run_and_says_why_it_cannot(make_repo, monkeypatch):
    repo = make_repo("lab", {"src/p/__init__.py": ""})
    head = testcov._git(repo, "rev-parse", "HEAD")
    runs = json.dumps([{"databaseId": 7, "headSha": "0" * 40, "workflowName": "ci"},
                       {"databaseId": 42, "headSha": head, "workflowName": "ci"}])
    seen = {}
    monkeypatch.setattr(testcov, "from_data", lambda data, cwd, root, name, python="": seen.update(
        data=data.name, cwd=cwd, root=root, text=data.read_text(encoding="utf-8")) or {"repo": name})
    gh = _Gh(_ok(runs), _ok(), files={"coverage.data": "sqlite"})
    assert testcov.from_ci(repo, repo / "src", "lab", runner=gh) == {"repo": "lab"}
    assert gh.calls[0][:5] == ["gh", "run", "list", "--commit", head]
    assert gh.calls[1][:6] == ["gh", "run", "download", "42", "-n", "coverage-data"]   # HEAD's run, not another's
    assert seen["data"] == "coverage.data" and seen["text"] == "sqlite" and seen["root"] == repo
    for answers, said in (
            ([FileNotFoundError("gh")], "gh: FileNotFoundError (the GitHub CLI, installed and signed in?)"),
            ([subprocess.TimeoutExpired(["gh"], 300)], "gh run list: no answer within 300 s"),
            ([subprocess.CompletedProcess(["gh"], 1, "", "HTTP 401: Bad credentials")], "HTTP 401"),
            ([_ok("<html>")], "gh run list: not JSON"),
            ([_ok("[]")], f"no successful CI run of {head[:12]} yet"),
            ([_ok(runs), _ok()], "artifact coverage-data holds no coverage data file")):
        with pytest.raises(testcov.CoverageError, match=re.escape(said)):
            testcov.from_ci(repo, repo, "lab", runner=_Gh(*answers))
    (repo / "src" / "p" / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(testcov.CoverageError, match="tracked files are modified"):
        testcov.from_ci(repo, repo, "lab", runner=_Gh())


def test_brain_coverage_from_ci_parses(monkeypatch):
    from brain import cli as brain_cli
    args = brain_cli.build_parser().parse_args(["coverage", "--repo", "brain", "--from-ci", "--cwd",
                                                "packages/brain", "--write"])
    assert args.from_ci and args.cwd == "packages/brain" and args.write
