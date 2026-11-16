"""wi-brain-format-lint: three format lints (a path into the brain's home built outside brain.paths, a file of the
home written around brain.stateio, a test reading the real home) read by two backends the owner switches on or off
(config.json audit.format_lints_python / _ast_grep, both off), the python one in the AST, the ast-grep one by its
pinned binary (N/A without it), the scout's info and DEFER lines, and brain lint formats --compare."""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from brain import cli, formatlint, inventory, scout

HOME_PATH = '''\
import os
from pathlib import Path


def a():
    return Path.home() / ".brain" / "x.json"


def b():
    return os.path.expanduser("~/.brain/y")


def c():
    return Path("~/.brain").expanduser()


def fine():
    return Path.home() / ".config", Path("~/.cache").expanduser()
'''
DIRECT_WRITE = '''\
from brain import paths


def a(text):
    f = paths.brain_home() / "notes" / "x.json"
    f.write_text(text, encoding="utf-8")


def b(text):
    with open(paths.brain_home() / "y.log", "a", encoding="utf-8") as fh:
        fh.write(text)


def c(text, other):
    other.write_text(text, encoding="utf-8")                  # not the home's
    with open(paths.brain_home() / "z.json", encoding="utf-8") as fh:   # a read
        return fh.read()
'''
REAL_HOME = '''\
import os
from pathlib import Path


def test_a(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)       # a patch, not a read
    assert Path.home()
    assert os.path.expanduser("~/x")
'''


def _checks(path, text):
    return [(h.check, h.line) for h in formatlint.python_hits(path, text)]


def test_the_python_backend_reads_the_three_rules():
    assert _checks("src/brain/x.py", HOME_PATH) == [("format.home-path", 6), ("format.home-path", 10),
                                                   ("format.home-path", 14)]
    assert _checks("src/brain/x.py", DIRECT_WRITE) == [("format.direct-write", 6), ("format.direct-write", 10)]
    assert _checks("tests/test_x.py", REAL_HOME) == [("format.real-home-test", 7), ("format.real-home-test", 8)]


def test_each_rule_reads_its_files_and_never_its_door():
    assert formatlint.checks_for("src/brain/paths.py") == ["format.direct-write"]
    assert formatlint.checks_for("src/brain/stateio.py") == ["format.home-path"]
    assert formatlint.checks_for("tests/test_x.py") == ["format.real-home-test"]
    assert formatlint.checks_for("tests/conftest.py") == formatlint.checks_for("README.md") == []
    assert _checks("src/brain/paths.py", HOME_PATH) == []
    assert {c for c, _ in _checks("tests/test_x.py", HOME_PATH)} == {"format.real-home-test"}   # a test's own rule
    assert _checks("src/brain/x.py", "def (:\n") == []                     # does not parse: nothing
    assert formatlint.checks_for("tools/paths.py") == ["format.home-path", "format.direct-write"]   # not a door
    imported = "from os.path import expanduser\n\n\ndef f():\n    return expanduser('~/.brain')\n"
    assert _checks("src/brain/x.py", imported) == [("format.home-path", 5)]


def test_both_backends_are_off_by_default_and_switched_by_the_owner(tmp_path, monkeypatch):
    assert formatlint.enabled(None) == []
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"v": 1, "audit": {"format_lints_python": True, "format_lints_ast_grep": False}}),
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    assert formatlint.enabled(None) == ["python"]


# --- the ast-grep backend: its pinned binary, faked ---

FAKE = '''\
import json, os, re, sys
args = sys.argv[1:]
if os.path.exists(os.path.join(os.path.dirname(__file__), "broken")):
    print("error: the rule does not parse", file=sys.stderr)
    sys.exit(2)
if args == ["--version"]:
    print("ast-grep VERSION")
    sys.exit(0)
rule, files = args[args.index("--rule") + 1], [a for a in args[1:] if not a.startswith("-") and a != args[args.index("--rule") + 1]]
word = {"home-path.yml": ".brain", "direct-write.yml": "write_text", "real-home-test.yml": "Path.home()"}[rule.replace("\\\\", "/").rsplit("/", 1)[-1]]
rows = []
for f in files:
    for i, line in enumerate(open(f, encoding="utf-8").read().splitlines()):
        if word in line:
            rows.append({"file": f, "range": {"start": {"line": i, "column": 0}}, "text": line.strip(), "ruleId": rule})
print(json.dumps(rows))
'''


@pytest.fixture
def fake_grep(tmp_path, monkeypatch):
    """An ``ast-grep`` on the PATH answering at the pinned version: a line holding the rule's word is a match."""
    bindir = tmp_path / "bin"
    bindir.mkdir()

    def make(version=formatlint.AST_GREP_PIN):
        (bindir / "fake.py").write_text(FAKE.replace("VERSION", version), encoding="utf-8")
        if os.name == "nt":
            (bindir / "ast-grep.cmd").write_text(f'@"{sys.executable}" "{bindir / "fake.py"}" %*\n', encoding="utf-8")
        else:
            sh = bindir / "ast-grep"
            sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bindir / "fake.py"}" "$@"\n', encoding="utf-8")
            sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return make


def test_without_the_binary_the_ast_grep_backend_is_na(monkeypatch):
    monkeypatch.setattr(formatlint.shutil, "which", lambda name: None)
    assert formatlint.ast_grep()[1].startswith("ast-grep is not on the PATH")
    assert formatlint.hits({"src/brain/x.py": HOME_PATH}, "ast-grep") == (
        [], formatlint.ast_grep()[1])


def test_another_version_is_na_the_pinned_one_scans(fake_grep):
    fake_grep("0.1.0")
    assert formatlint.ast_grep() == ("", f"ast-grep 0.1.0 found, the rules are pinned to {formatlint.AST_GREP_PIN}")
    fake_grep()
    got, why = formatlint.hits({"src/brain/x.py": HOME_PATH, "tests/test_x.py": REAL_HOME}, "ast-grep")
    assert why == ""
    assert [(h.check, h.path, h.line) for h in got] == [
        ("format.home-path", "src/brain/x.py", 6), ("format.home-path", "src/brain/x.py", 10),
        ("format.home-path", "src/brain/x.py", 14), ("format.real-home-test", "tests/test_x.py", 7)]
    (Path(os.environ["PATH"].split(os.pathsep)[0]) / "broken").write_text("", encoding="utf-8")
    got, why = formatlint.grep_hits({"src/brain/x.py": Path(__file__)}, formatlint.shutil.which("ast-grep"))
    assert got == [] and why == "ast-grep scan direct-write.yml: exit 2, error: the rule does not parse"   # never 0 hits


def test_the_files_go_in_batches_under_the_command_line_limit():
    files = [f"C:/some/long/folder/file_{i:04d}.py" for i in range(2000)]
    batches = formatlint._batches(files)
    assert len(batches) > 1 and [f for b in batches for f in b] == files
    assert all(sum(len(f) + 3 for f in b) <= formatlint.ARGV_CHARS for b in batches)


@pytest.mark.skipif(not formatlint.ast_grep()[0], reason="the real ast-grep at its pinned version is not installed")
def test_the_real_rules_find_what_the_python_backend_finds():
    """With the owner's binary installed: the YAML rules on the same samples (the comparison's ground)."""
    texts = {"src/brain/x.py": HOME_PATH, "src/brain/y.py": DIRECT_WRITE, "tests/test_x.py": REAL_HOME}
    got, why = formatlint.hits(texts, "ast-grep")
    assert why == ""
    assert sorted((h.check, h.path, h.line) for h in got) == sorted(
        (h.check, h.path, h.line) for p, t in texts.items() for h in formatlint.python_hits(p, t))


def test_the_rules_ship_with_the_engine():
    assert sorted(p.name for p in formatlint.RULES_DIR.glob("*.yml")) == sorted(formatlint.RULE_FILES.values())
    for check, name in formatlint.RULE_FILES.items():
        assert f"id: {check}\n" in (formatlint.RULES_DIR / name).read_text(encoding="utf-8")


# --- the scout and brain lint formats ---

def _change(make_repo):
    repo = make_repo("lab", {"src/lab/core.py": "from pathlib import Path\n\n\ndef old():\n"
                                                "    return Path.home() / '.brain'\n"})
    base = inventory.git(repo, "rev-parse", "HEAD").strip()
    make_repo.write(repo, {"src/lab/core.py": "from pathlib import Path\n\n\ndef old():\n"
                                              "    return Path.home() / '.brain'\n\n\ndef new():\n"
                                              "    return Path.home() / '.brain' / 'x'\n"})
    return repo, base


def test_the_scout_says_what_a_change_adds_and_defers_what_was_there(make_repo, monkeypatch):
    monkeypatch.setattr(formatlint.shutil, "which", lambda name: None)   # no ast-grep, even an installed one
    repo, base = _change(make_repo)
    rows = scout.changed(repo, base)
    args = ("lab", rows, inventory.git_tree(repo, base), inventory.work_tree(repo))
    assert formatlint.signals(*args, []) == ([], {})                       # switched off: nothing read
    lines, na = formatlint.signals(*args, ["python"])
    assert na == {} and [(x["tag"], x["check"], x["unit"]) for x in lines] == [
        ("info", "format.home-path", "src/lab/core.py::new"), ("DEFER", "format.home-path", "src/lab/core.py")]
    lines, na = formatlint.signals(*args, ["python", "ast-grep"])          # no binary: said, the python lines kept
    assert len(lines) == 2 and list(na) == ["format lints (ast-grep)"]


def test_both_backends_on_say_an_occurrence_once(make_repo, fake_grep):
    fake_grep()
    repo, base = _change(make_repo)
    lines, na = formatlint.signals("lab", scout.changed(repo, base), inventory.git_tree(repo, base),
                                   inventory.work_tree(repo), ["python", "ast-grep"])
    assert na == {} and sorted(x["tag"] for x in lines) == ["DEFER", "info"]


def test_brain_lint_formats_compares_the_backends(make_repo, fake_grep, capsys):
    fake_grep()
    repo = make_repo("lab", {"src/lab/core.py": HOME_PATH + DIRECT_WRITE.replace("from brain import paths\n", ""),
                             "tests/test_x.py": REAL_HOME})
    assert cli.main(["lint", "formats", "--repo-dir", str(repo), "--compare", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert set(d["backends"]) == {"python", "ast-grep"} and all(b["why"] == "" for b in d["backends"].values())
    only_py = {(h["check"], h["line"]) for h in d["diff"]["only python"]}
    only_grep = {(h["check"], h["line"]) for h in d["diff"]["only ast-grep"]}
    assert ("format.real-home-test", 8) in only_py                          # the fake knows no expanduser
    assert only_grep == set() or all(c in formatlint.SEVERITY for c, _ in only_grep)
    assert cli.main(["lint", "formats", "--repo-dir", str(repo), "--compare"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("python: ") and out[1].startswith("ast-grep: ") and " s" in out[0]
    assert any(x.startswith("only python (") for x in out)


def test_brain_lint_formats_outside_a_repo_exits_2(tmp_path, capsys):
    assert cli.main(["lint", "formats", "--repo-dir", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("brain lint formats: ")
