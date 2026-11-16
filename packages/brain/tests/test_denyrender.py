"""The deny list rendered as a gitleaks configuration (brain.denyrender, brain public deny render;
wi-brain-deny-gitleaks-render): every term matches what brain.public matches, in Go's regexp syntax; the file is a
plan then an atomic, idempotent write, mode 600, never inside a repository; the plan never prints a term. Invented
owner Ada and invented terms."""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from brain import boundary, cli, config, denylist, denyrender

DENY = {"people": ["Ada Lovelace"], "users": ["ada"], "hosts": ["box-one", "lab_02"],
        "repos": ["acme_lab", "x.y+z", "odd(name)"], "paths": ["D:\\vault\\acme-notes", "/srv/acme"]}
LINES = [
    "we deploy to BOX_ONE today", "box one or boxone, Lab 02", "boxone2 is another host, so is xbox-one",
    "see acme lab and AcmeLab and acme-lab", "not xacme_lab nor acme_labs", "Ada Lovelace wrote it, adalovelace too",
    "path D:/vault/acme-notes/x and D:\\vault\\acme_notes\\y", "x.y+z here, xxy+z not", "odd(name) and odd_name",
    "/srv/acme/data", "plain text with nothing", "ada@example.invalid", "a line\twith a tab: ada",
]


@pytest.fixture
def ada(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada Lovelace", "kind": "person"},
                               "public": {"derive": [], "deny": DENY}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    return config.load()


def _rules(text: str) -> dict[str, str]:
    """{rule id: regex} from the rendered TOML (read with tomllib where the Python has it, else by line)."""
    try:
        import tomllib
    except ImportError:   # Python 3.10
        ids = re.findall(r'^id = "(.*)"$', text, re.M)
        regs = [json.loads(r) for r in re.findall(r"^regex = (\".*\")$", text, re.M)]
        return dict(zip(ids, regs))
    data = tomllib.loads(text)
    return {r["id"]: r["regex"] for r in data["rules"]}


def _python(regex: str) -> re.Pattern:
    """Go's (?i) flag and syntax, which this subset shares with Python's re."""
    return re.compile(regex)


def test_every_term_matches_as_brain_public_matches(ada):
    """The rendered rules find, on each line, the terms brain.boundary.term_regex finds there (with the text's
    backslashes read as slashes, as brain.public reads it), and nothing else."""
    rules = _rules(denyrender.gitleaks(denyrender.by_category(ada)))
    assert set(rules) == {f"brain-private-{c}" for c in DENY}
    for line in LINES:
        want = {t for cat, ts in DENY.items() for t in ts if boundary.term_regex(t).search(line.replace("\\", "/"))}
        got = set()
        for cat, regex in rules.items():
            for t in DENY[cat.removeprefix("brain-private-")]:
                one = denyrender.term_re2(t)
                if re.search(rf"(?i)(?:^|[^A-Za-z0-9_])({one})(?:[^A-Za-z0-9_]|$)", line) and _python(regex).search(line):
                    got.add(t)
        assert got == want, line


def test_the_regexes_are_go_regexp(ada):
    """RE2 has no lookaround and refuses an escaped letter or space: the rendered regexes use neither."""
    for regex in _rules(denyrender.gitleaks(denyrender.by_category(ada))).values():
        assert not re.search(r"\(\?<?[=!]", regex)
        assert not re.search(r"\\[A-Za-z0-9 ]", regex.replace("\\\\", ""))
    assert denyrender.re2_escape("a.b+c (d) [e] {f} ^$|*?\\") == "a\\.b\\+c \\(d\\) \\[e\\] \\{f\\} \\^\\$\\|\\*\\?\\\\"
    assert denyrender.re2_escape("plain-name_1 %$#") == "plain-name_1 %\\$#"


def test_toml_strings_escape_quotes_newlines_and_controls():
    for text in ['say "hi"', "back\\slash", "a\nb", "tab\there", "100 % $HOME", "&amp; <x/>", "\x01\x7f", "é"]:
        out = denyrender.toml_str(text)
        try:
            import tomllib
        except ImportError:
            assert "\n" not in out and out.startswith('"') and out.endswith('"')
            continue
        assert tomllib.loads(f"k = {out}")["k"] == text


def test_keywords_and_the_extended_config(ada):
    text = denyrender.gitleaks(denyrender.by_category(ada), extend="../repo/.gitleaks.toml")
    assert '[extend]\npath = "../repo/.gitleaks.toml"' in text and "useDefault" not in text
    assert "[extend]\nuseDefault = true" in denyrender.gitleaks(denyrender.by_category(ada))
    assert denyrender.keyword("Ada Lovelace") == "lovelace" and denyrender.keyword("D:\\vault\\acme-notes") == "vault"
    # every rule's keywords are in each spelling its regex matches (gitleaks' prefilter would skip a fragment else)
    for spelled in ("acme lab", "AcmeLab", "acme-lab"):
        assert denyrender.keyword("acme_lab") in spelled.lower()


def test_the_plan_then_an_atomic_idempotent_apply(ada, tmp_path):
    out = tmp_path / "home" / ".config" / "brain" / denyrender.FILE_NAME
    p = denyrender.plan(ada, out)
    assert p["state"] == "new" and p["refused"] == "" and p["terms"] == sum(len(v) for v in DENY.values())
    shown = "\n".join(denyrender.render_plan(p))
    assert not any(t.lower() in shown.lower() for ts in DENY.values() for t in ts)   # never a term on screen
    assert denyrender.apply(p) == "written" and out.read_text(encoding="utf-8") == p["text"]
    if os.name != "nt":
        assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert not [f for f in out.parent.iterdir() if f.name.startswith(".brain-deny-")]   # no temporary file left
    again = denyrender.plan(ada, out)
    assert again["state"] == "unchanged" and denyrender.apply(again) == "unchanged"
    out.write_text("edited by hand\n", encoding="utf-8")
    assert denyrender.plan(ada, out)["state"] == "changed"


def test_a_write_cut_midway_leaves_the_old_file(ada, tmp_path, monkeypatch):
    out = tmp_path / "cfg" / denyrender.FILE_NAME
    out.parent.mkdir()
    out.write_text("the previous render\n", encoding="utf-8")

    def cut(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(denyrender.os, "replace", cut)
    with pytest.raises(OSError):
        denyrender.apply(denyrender.plan(ada, out))
    assert out.read_text(encoding="utf-8") == "the previous render\n"
    assert [f.name for f in out.parent.iterdir()] == [denyrender.FILE_NAME]


def test_never_inside_a_repository(ada, tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    p = denyrender.plan(ada, repo / "sub" / denyrender.FILE_NAME)
    assert "inside the git repository" in p["refused"]
    with pytest.raises(denyrender.RenderError):
        denyrender.apply(p)
    assert not (repo / "sub").exists()


def test_the_default_place(monkeypatch, tmp_path):
    assert denyrender.default_out({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "brain" / denyrender.FILE_NAME
    assert denyrender.default_out({}).parts[-3:] == (".config", "brain", denyrender.FILE_NAME)


def test_a_derivation_that_fails_renders_nothing(ada, monkeypatch):
    def broken(cfg):
        raise denylist.DeriveError("projects.yaml: a conflict marker")
    monkeypatch.setattr(denylist, "terms", broken)
    with pytest.raises(denyrender.RenderError, match="cannot be derived"):
        denyrender.plan(ada, Path("x.toml"))


def test_the_command_line(ada, tmp_path, capsys):
    out = tmp_path / "o" / denyrender.FILE_NAME
    argv = ["public", "deny", "render", "--format", "gitleaks", "--out", str(out)]
    assert cli.main([*argv, "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["state"] == "new" and plan["applied"] is None and "text" not in plan and not out.exists()
    assert cli.main([*argv, "--apply"]) == 0 and out.is_file()
    assert "applied   written" in capsys.readouterr().out
    assert cli.main([*argv, "--apply"]) == 0 and "applied   unchanged" in capsys.readouterr().out
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    assert cli.main(["public", "deny", "render", "--format", "gitleaks", "--out", str(repo / "x.toml")]) == 2
    with pytest.raises(SystemExit):
        cli.main(["public", "deny", "render", "--format", "trufflehog"])
    capsys.readouterr()


@pytest.mark.skipif(not shutil.which("gitleaks"), reason="gitleaks is not on the PATH")
def test_gitleaks_reads_the_file_and_finds_the_terms(ada, tmp_path):
    out = tmp_path / "cfg" / denyrender.FILE_NAME
    denyrender.apply(denyrender.plan(ada, out))
    scan = tmp_path / "scan"
    scan.mkdir()
    (scan / "notes.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    report = tmp_path / "report.json"
    subprocess.run(["gitleaks", "dir", str(scan), "--config", str(out), "--no-banner", "--exit-code", "0",
                    "--report-format", "json", "--report-path", str(report)], capture_output=True, timeout=120)
    found = {f["StartLine"] for f in json.loads(report.read_text(encoding="utf-8"))
             if f["RuleID"].startswith("brain-private-")}
    want = {i for i, line in enumerate(LINES, 1)
            if any(boundary.term_regex(t).search(line.replace("\\", "/")) for ts in DENY.values() for t in ts)}
    assert found == want
