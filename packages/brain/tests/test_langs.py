"""The language adapters (wi-brain-lang-adapters): a repo's tools: in projects.yaml names the reports its own tools
write; the engine reads them (it runs nothing): brain audit's lang.report, and the standards' language gaps."""

import json
from pathlib import Path

import pytest
from brain import audit, langs, projects, standards

JUNIT = """<?xml version="1.0"?>
<testsuites>
  <testsuite name="a" tests="3" failures="1" errors="0">
    <testcase name="one"/><testcase name="two"><failure message="no"/></testcase><testcase name="three"/>
  </testsuite>
  <testsuite name="b" tests="2" failures="0" errors="1">
    <testcase name="four"><error message="boom"/></testcase><testcase name="five"><skipped/></testcase>
  </testsuite>
</testsuites>
"""
SARIF = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "eslint"}}, "results": [
    {"ruleId": "no-unused-vars", "level": "error"}, {"ruleId": "eqeqeq", "level": "warning"},
    {"ruleId": "info", "level": "note"}]}, {"tool": {"driver": {"name": "x"}}, "results": [{"ruleId": "r"}]}]}


def _write(folder: Path, name: str, text: str) -> Path:
    f = folder / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return f


# --- the readers ------------------------------------------------------------------------------------------------

def test_junit_counts_failures_and_errors_over_the_cases(tmp_path):
    assert langs.read_junit(_write(tmp_path, "j.xml", JUNIT)) == (2, 5)
    one = _write(tmp_path, "one.xml", '<testsuite tests="4" failures="1" errors="1"></testsuite>')
    assert langs.read_junit(one) == (2, 4)   # no testcase: the suite's own counts
    with pytest.raises(langs.ReportError, match="not JUnit"):
        langs.read_junit(_write(tmp_path, "x.xml", "<coverage/>"))
    with pytest.raises(langs.ReportError, match="not XML"):
        langs.read_junit(_write(tmp_path, "bad.xml", "<testsuite"))


def test_sarif_counts_the_results_a_note_aside(tmp_path):
    assert langs.read_sarif(_write(tmp_path, "l.sarif", json.dumps(SARIF))) == 3
    with pytest.raises(langs.ReportError, match="no runs"):
        langs.read_sarif(_write(tmp_path, "n.sarif", "{}"))
    with pytest.raises(langs.ReportError, match="not JSON"):
        langs.read_sarif(_write(tmp_path, "b.sarif", "{"))


@pytest.mark.parametrize("fmt, text, want", [
    ("cobertura", '<coverage line-rate="0.8125" branch-rate="0.5"></coverage>', 81.25),
    ("lcov", "SF:a.ts\nLF:10\nLH:7\nend_of_record\nSF:b.ts\nLF:10\nLH:10\nend_of_record\n", 85.0),
    ("coverage-json", json.dumps({"totals": {"percent_covered": 64.333}}), 64.33),
    ("istanbul-summary", json.dumps({"total": {"lines": {"pct": 92.5}}}), 92.5),
])
def test_coverage_reports(tmp_path, fmt, text, want):
    assert langs.read_coverage(_write(tmp_path, "c", text), fmt) == want


@pytest.mark.parametrize("fmt, text", [("cobertura", "<report/>"), ("lcov", "SF:a\n"),
                                       ("coverage-json", "{}"), ("istanbul-summary", '{"total": {}}')])
def test_a_coverage_report_of_another_shape_is_said(tmp_path, fmt, text):
    with pytest.raises(langs.ReportError):
        langs.read_coverage(_write(tmp_path, "c", text), fmt)


def test_read_says_why_a_report_cannot_be_read(tmp_path):
    r = langs.read(tmp_path, "test", {"report": "junit.xml", "format": "junit"})
    assert not r.read and r.error == "no report at junit.xml"
    _write(tmp_path, "junit.xml", JUNIT)
    r = langs.read(tmp_path, "test", {"report": "junit.xml", "format": "junit", "tool": "vitest"})
    assert r.read and (r.count, r.total, r.tool) == (2, 5, "vitest")
    _write(tmp_path, "cov.json", "[]")
    r = langs.read(tmp_path, "coverage", {"report": "cov.json", "format": "coverage-json"})
    assert "not coverage-json" in r.error and r.percent is None


# --- the contract in projects.yaml ------------------------------------------------------------------------------

@pytest.mark.parametrize("value, needle", [
    ([], "tools is a mapping"),
    ({"lint": "eslint.sarif"}, "a mapping {report, format}"),
    ({"lint": {"format": "sarif"}}, "report is the path"),
    ({"lint": {"report": "/abs/eslint.sarif", "format": "sarif"}}, "inside the repo's checkout"),
    ({"lint": {"report": "../eslint.sarif", "format": "sarif"}}, "inside the repo's checkout"),
    ({"test": {"report": "j.xml", "format": "sarif"}}, "format is one of junit"),
    ({"lint": {"report": "x", "format": "sarif", "command": "eslint ."}}, "unknown key(s) command"),
    ({"bench": {"report": "b.json", "format": "json"}}, "unknown slot 'bench'"),
    ({"lint": {"report": "x", "format": "pylint-json"}}, "format 'pylint-json'"),
])
def test_a_bad_tools_entry_is_named(value, needle):
    errors = langs.tools_errors("repos[0]", value)
    assert any(needle in e for e in errors), errors


def test_a_newer_engines_slot_key_or_format_is_a_note_in_read_mode(monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_STRICT", "0")
    value = {"bench": {"report": "b.json", "format": "json"},
             "lint": {"report": "x.sarif", "format": "sarif", "command": "eslint ."},
             "coverage": {"report": "c.xml", "format": "jacoco"}}
    assert langs.tools_errors("repos[0]", value) == []
    assert langs.declared(value) == {"lint": {"report": "x.sarif", "format": "sarif", "command": "eslint ."}}
    assert "unknown slot 'bench'" in capsys.readouterr().err


def _registry(tmp_path, monkeypatch, repo: str) -> Path:
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "web").mkdir(exist_ok=True)
    reg.write_text(f"demo:\n  root: .\n  repos:\n    - {repo}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return reg


def test_repos_of_reads_tools(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, "{path: ../web, lang: ts, tools: {lint: {report: eslint.sarif, format: sarif}, "
                                     "test: {report: junit.xml, format: junit, tool: vitest}}}")
    [r] = projects.repos_of(projects.get("demo"))
    assert r.lang == "ts" and set(r.tools) == {"lint", "test"} and r.tools["test"]["tool"] == "vitest"
    assert projects.check() == []
    assert "tools" in projects.KEYS["repos"]


def test_a_repo_without_tools_is_unchanged(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, "{path: ../web, lang: ts}")
    [r] = projects.repos_of(projects.get("demo"))
    assert r.tools == {} and r.lang == "ts"


def test_a_bad_tools_entry_fails_the_registry_check(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, "{path: ../web, tools: {test: {report: junit.xml, format: sarif}}}")
    with pytest.raises(projects.RepoError, match="format is one of junit"):
        projects.repos_of(projects.get("demo"))
    assert any("format is one of junit" in e for e in projects.check())


# --- brain audit's lang.report ----------------------------------------------------------------------------------

def _repo(path: Path, tools: dict, lang: str = "ts") -> projects.Repo:
    return projects.Repo("web", path, lang=lang, tools=langs.declared(tools))


def test_lang_report_says_what_the_reports_say(tmp_path):
    _write(tmp_path, "reports/junit.xml", JUNIT)
    _write(tmp_path, "reports/eslint.sarif", json.dumps(SARIF))
    _write(tmp_path, "coverage/coverage-summary.json", json.dumps({"total": {"lines": {"pct": 42.0}}}))
    _write(tmp_path, "tsc.sarif", json.dumps({"runs": [{"results": []}]}))
    tools = {"lint": {"report": "reports/eslint.sarif", "format": "sarif", "tool": "eslint"},
             "typecheck": {"report": "tsc.sarif", "format": "sarif"},
             "test": {"report": "reports/junit.xml", "format": "junit"},
             "coverage": {"report": "coverage/coverage-summary.json", "format": "istanbul-summary"},
             "format": {"report": "prettier.xml", "format": "junit"}}
    got = {f["unit"]: f for f in audit.lang_report({"cfg": _repo(tmp_path, tools)})}
    assert set(got) == {"lint:reports/eslint.sarif", "test:reports/junit.xml",
                        "coverage:coverage/coverage-summary.json", "format:prettier.xml"}   # typecheck: clean
    assert got["lint:reports/eslint.sarif"]["why"] == "3 lint finding(s) (eslint)"
    assert got["test:reports/junit.xml"]["why"] == "2 of 5 test(s) failed"
    assert got["coverage:coverage/coverage-summary.json"]["why"].startswith("coverage 42 % (under")
    assert "no report at prettier.xml" in got["format:prettier.xml"]["why"]
    assert "prettier --check" in got["format:prettier.xml"]["fix"]   # the usual tool of ts, named
    assert all(f["check"] == "lang.report" and f["severity"] == "P2" for f in got.values())


def test_lang_report_is_measured_only_where_tools_are_declared(tmp_path):
    assert audit.lang_report({"cfg": _repo(tmp_path, {})}) == audit.NO_TOOLS
    assert audit.PENDING["lang.report"].applies == "tools" and not audit.PENDING["lang.report"].blocks
    assert audit.CHECKS["lang.report"].scout == "never" and audit.RULESET >= 8


# --- the standards' side ----------------------------------------------------------------------------------------

def test_a_declared_slot_covers_a_standard_on_its_repos_language():
    row = standards.Row("sw-lint", "software", "code-quality", "Lint in CI.", ["cli"], "mvp", "check", "a linter",
                        ["py"], "proposed", adapter="lint")
    plain = standards.Row("sw-x", "software", "x", "X.", ["cli"], "mvp", "check", "x", ["py"], "proposed")
    chosen = [(row, ""), (plain, "")]
    langs_ = {"app": "py", "web": "ts"}
    assert standards.gaps(chosen, langs_) == ["sw-lint: its check covers py, not web (ts)",
                                              "sw-x: its check covers py, not web (ts)"]
    assert standards.gaps(chosen, langs_, {"web": {"lint"}}) == ["sw-x: its check covers py, not web (ts)"]
