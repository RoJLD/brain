"""brain rules diff (brain.rulesdiff): the cutter, the subject classifier in French and English, the classes, the
command, and the restricted reader's canary: a restricted note's text reaches no log, alert, record or output."""

import json
from pathlib import Path

import pytest
from brain import cli, config, rulesdiff

SUBJECTS = Path(__file__).parent / "fixtures" / "rules-diff" / "subjects.yaml"

GLOBAL = """# Ada's rules

## Git

- Never commit without being asked.
- Use a git worktree for every change and merge through a pull request, then pull
  where a service runs.
- Ask who merges a pull request when in doubt.

## Language

- Write commits in English.
"""

MACHINE = """# This machine

- Use a git worktree for every change and merge through a pull request, then pull where a service runs.
- Write commits in English.
- Prefer bash for the scripts of this machine, always.
"""

PROJECT = """# lab

## Git

- Crée et merge tes PR toi-même.
- Use a git worktree for each change and merge through a pull request, and then pull where any service runs.
"""


def _note(folder: Path, name: str, body: str, kind: str = "feedback", meta: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{name}.md"
    head = meta or f"name: {name}\ndescription: a note\ntype: {kind}\n"
    f.write_text(f"---\n{head}---\n\n{body}\n", encoding="utf-8")
    return f


@pytest.fixture
def ada(tmp_path, monkeypatch):
    """Ada's brain in a temporary folder (its config.json names no subject list), her machine's Claude folder, a
    project lab and the three rule files."""
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"}}),
                                       encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / "config.json"))
    claude = tmp_path / "claude-config"
    claude.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    lab = tmp_path / "lab"
    lab.mkdir()
    (tmp_path / "notes").mkdir()
    files = {"machine": tmp_path / "machine.md", "global": tmp_path / "global.md", "project": lab / "CLAUDE.md"}
    files["machine"].write_text(MACHINE, encoding="utf-8")
    files["global"].write_text(GLOBAL, encoding="utf-8")
    files["project"].write_text(PROJECT, encoding="utf-8")
    return {"brain": brain, "claude": claude, "lab": lab, "tmp": tmp_path, **files}


def _flags(ada, *more):
    return ["rules", "diff", "--machine-rules", str(ada["machine"]), "--global", str(ada["global"]),
            "--project-rules", str(ada["project"]), "--notes", str(ada["tmp"] / "notes"), *more]


def _units_of(data: dict) -> list[dict]:
    """Every unit of a --json report, whatever its class."""
    return ([u for c in ("identical", "near", "contradictory") for p in data[c] for u in (p["a"], p["b"])]
            + data["one_side"] + data["to_check"])


def _run(capsys, argv):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


# --- the cutter ---

def test_units_are_bullets_with_their_wrapped_lines_and_paragraphs():
    us = rulesdiff.markdown_units(GLOBAL, "global", "global.md")
    assert [u.line for u in us] == [5, 6, 8, 12]
    assert us[1].text.endswith("where a service runs.") and "pull request, then pull" in us[1].text
    assert us[1].excerpt(200) == ("Use a git worktree for every change and merge through a pull request, then pull "
                                  "where a service runs.")


def test_one_feedback_note_is_one_unit(tmp_path):
    mem = tmp_path / "proj" / "memory"
    _note(mem, "feedback_ask", "Never commit without being asked.\n\n**Why:** a past mistake.")
    _note(mem, "user_role", "Ada is a data scientist.", kind="user")
    _note(mem, "nested", "Write commits in English.", meta="name: nested\nmetadata:\n  type: feedback\n")
    _note(mem, "broken", "Text.", meta="name: [unclosed\n")
    (mem / "MEMORY.md").write_text("- [x](feedback_ask.md)\n", encoding="utf-8")
    us = rulesdiff.notes_units([mem])
    assert [u.file for u in us] == ["proj/feedback_ask.md", "proj/nested.md"]
    assert us[0].source == "notes" and us[0].line == 7 and us[0].text.startswith("Never commit")


# --- the classifier ---

def test_subjects_classify_french_and_english():
    subs = rulesdiff.load_subjects(SUBJECTS)
    assert [s.id for s in subs.subjects] == ["git-authority", "commit-language", "shell"]
    cases = {
        "Never commit without being asked.": ("git-authority", "ask"),
        "Ne fais jamais de commit sans qu'on te le demande.": ("git-authority", "ask"),
        "Create and merge your PRs yourself.": ("git-authority", "automerge"),
        "Crée et merge tes PR toi-même.": ("git-authority", "automerge"),
        "Open a pull request; the owner merges it.": ("git-authority", "pr"),
        "Write commits in English.": ("commit-language", "english"),
        "Les commits et les PR sont écrits en français.": ("commit-language", "french"),
        "Utilise toujours PowerShell pour les scripts.": ("shell", "powershell"),
    }
    for text, (subject, value) in cases.items():
        claims, touched = rulesdiff.classify(text, subs)
        assert [(c["subject"], c["value"]) for c in claims] == [(subject, value)], text
        assert claims[0]["scope"] == "any" and touched == {}, text


def test_scopes_split_a_rule_and_a_subject_with_no_value_is_to_check():
    subs = rulesdiff.load_subjects(SUBJECTS)
    claims, _ = rulesdiff.classify("In this repo, merge your PRs yourself. In any other repo, never commit.", subs)
    assert claims == [{"subject": "git-authority", "value": "automerge", "scope": "this-repo"},
                      {"subject": "git-authority", "value": "ask", "scope": "other-repos"}]
    assert rulesdiff.classify("Ask who merges the pull requests.", subs) == ([], {"git-authority": "no value"})
    assert rulesdiff.classify("Commits are signed.", subs) == ([], {})
    assert rulesdiff.classify("Commit only when asked, merge yourself", subs) == (
        [], {"git-authority": "several values: ask, automerge"})
    assert rulesdiff.classify("The shell of the CI.", subs) == ([], {"shell": "no value"})


def test_a_malformed_subject_list_is_refused(tmp_path):
    for data, why in [({"subjects": [{"id": "x", "kind": "law", "values": {"a": ["x"]}}]}, "kind is"),
                      ({"subjects": [{"id": "x", "values": {}}]}, "values is a mapping"),
                      ({"subjects": [{"id": "x", "values": {"a": ["("]}}]}, "pattern"),
                      ({"subjects": [{"id": "x", "values": {"a": ["x"]}}, {"id": "x", "values": {"a": ["y"]}}]},
                       "twice"),
                      ({"subjects": [{"id": "x", "values": {"a": ["a{99999999999}"]}}]}, "pattern"),
                      ({"nothing": 1}, "a list under 'subjects'")]:
        with pytest.raises(rulesdiff.RulesDiffError, match=why):
            rulesdiff.parse_subjects(data, "s.yaml")


def test_a_pattern_past_the_engines_limits_exits_2(ada, capsys, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("subjects:\n  - id: x\n    values: {a: ['a{99999999999}']}\n", encoding="utf-8")
    code, out, err = _run(capsys, _flags(ada, "--subjects", str(bad)))
    assert code == 2 and out == "" and "pattern" in err and "Traceback" not in err


def test_a_values_not_patterns_are_its_negations():
    subs = rulesdiff.load_subjects(SUBJECTS)
    assert rulesdiff.classify("Never merge your PRs yourself.", subs) == ([], {})
    assert rulesdiff.classify("Ne merge jamais tes PR toi-même.", subs) == ([], {})
    claims, _ = rulesdiff.classify("Don't ever commit unless asked.", subs)
    assert [(c["subject"], c["value"]) for c in claims] == [("git-authority", "ask")]
    us = (rulesdiff.markdown_units("- Never commit without being asked.\n", "global", "g.md")
          + rulesdiff.markdown_units("- Never merge your PRs yourself.\n", "project", "CLAUDE.md"))
    assert rulesdiff.diff(us, subs)["contradictory"] == []


def test_a_scope_carries_to_the_next_sentences_and_from_the_heading():
    subs = rulesdiff.load_subjects(SUBJECTS)
    claims, _ = rulesdiff.classify("In this repo, the rules differ. Merge your PRs yourself.", subs)
    assert claims == [{"subject": "git-authority", "value": "automerge", "scope": "this-repo"}]
    claims, _ = rulesdiff.classify("Never commit, e.g. in this repo.", subs)
    assert claims == [{"subject": "git-authority", "value": "ask", "scope": "this-repo"}]
    assert rulesdiff.sentences("Never commit, e.g. in this repo. Then push, i.e. publish.") == [
        "never commit, e.g. in this repo.", "then push, i.e. publish."]
    us = rulesdiff.markdown_units("## In any other repo\n\n- Merge your PRs yourself.\n", "global", "g.md")
    rulesdiff.diff(us, subs)
    assert us[0].claims == [{"subject": "git-authority", "value": "automerge", "scope": "other-repos"}]


def test_a_front_matter_and_a_bom_are_not_rules(tmp_path):
    f = tmp_path / "rules.md"
    f.write_text("---\ntitle: Ada's rules\nscope: global\n---\n\n# Rules\n\n- Use bash.\n", encoding="utf-8-sig")
    us = rulesdiff.markdown_units(rulesdiff._read(f), "global", "rules.md")
    assert [(u.line, u.text) for u in us] == [(8, "- Use bash.")]
    _note(tmp_path / "mem", "feedback_bom", "Write commits in English.")
    note = tmp_path / "mem" / "feedback_bom.md"
    note.write_text(note.read_text(encoding="utf-8"), encoding="utf-8-sig")   # a BOM before its front matter
    assert [u.file for u in rulesdiff.notes_units([tmp_path / "mem"])] == ["mem/feedback_bom.md"]


def test_the_same_short_text_is_identical_not_near():
    us = (rulesdiff.markdown_units("- Use bash.\n", "global", "g.md")
          + rulesdiff.markdown_units("- Use bash.\n", "machine", "m.md"))
    rep = rulesdiff.diff(us, None)
    assert len(rep["identical"]) == 1 and rep["near"] == []


def test_a_config_rules_file_outside_the_brains_root_is_shown_whole(tmp_path, monkeypatch):
    outside = tmp_path / "elsewhere" / "global.md"
    outside.parent.mkdir()
    outside.write_text(GLOBAL, encoding="utf-8")
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / "config.json").write_text(json.dumps({"v": 1, "rules": [outside.as_posix()]}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / "config.json"))
    srcs = rulesdiff.global_sources(config.load())
    assert [(s.file, s.path) for s in srcs] == [(outside.as_posix(), outside)]


# --- the classes ---

def _units():
    return (rulesdiff.markdown_units(GLOBAL, "global", "global.md")
            + rulesdiff.markdown_units(MACHINE, "machine", "~/.claude/CLAUDE.md")
            + rulesdiff.markdown_units(PROJECT, "project", "CLAUDE.md"))


def test_the_classes_identical_near_one_side_contradictory_to_check():
    rep = rulesdiff.diff(_units(), rulesdiff.load_subjects(SUBJECTS))
    ident = {(p["a"].ref, p["b"].ref) for p in rep["identical"]}
    assert ident == {("global:global.md:6", "machine:~/.claude/CLAUDE.md:3"),
                     ("global:global.md:12", "machine:~/.claude/CLAUDE.md:4")}
    near = {(p["a"].ref, p["b"].ref) for p in rep["near"]}
    assert ("global:global.md:6", "project:CLAUDE.md:6") in near
    assert [(p["subject"], p["a_value"], p["b_value"], p["scope"], p["a"].ref, p["b"].ref)
            for p in rep["contradictory"]] == [
        ("git-authority", "ask", "automerge", "any", "global:global.md:5", "project:CLAUDE.md:5")]
    assert rep["contradictory"][0]["kind"] == "guardrail"
    assert {u.ref for u in rep["one_side"]} == {"global:global.md:5", "global:global.md:8",
                                                "machine:~/.claude/CLAUDE.md:5", "project:CLAUDE.md:5"}
    assert [(u.ref, s) for u, s, _ in rep["to_check"]] == [("global:global.md:8", "git-authority")]


def test_without_a_subject_list_no_contradiction_is_computed():
    rep = rulesdiff.diff(_units(), None)
    assert rep["contradictory"] == [] and rep["to_check"] == [] and len(rep["identical"]) == 2


def test_two_values_in_different_scopes_do_not_contradict():
    subs = rulesdiff.load_subjects(SUBJECTS)
    us = (rulesdiff.markdown_units("- In this repo, merge your PRs yourself.\n", "global", "g.md")
          + rulesdiff.markdown_units("- In any other repo, never commit.\n", "project", "CLAUDE.md"))
    assert rulesdiff.diff(us, subs)["contradictory"] == []


# --- the command ---

def test_the_command_prints_json_by_class(ada, capsys):
    _note(ada["tmp"] / "notes", "feedback_lang", "Write commits in English.")
    code, out, _ = _run(capsys, _flags(ada, "--subjects", str(SUBJECTS), "--json"))
    assert code == 0
    data = json.loads(out)
    assert data["counts"] == {"identical": 4, "near": 2, "contradictory": 1, "one_side": 4, "to_check": 1}
    assert data["contradictions"] == "computed" and data["subjects"]["count"] == 3
    c = data["contradictory"][0]
    assert (c["class"], c["subject"], c["a"]["value"], c["b"]["value"]) == ("contradictory", "git-authority", "ask",
                                                                              "automerge")
    assert {k: c["a"][k] for k in ("source", "line", "subject")} == {"source": "global", "line": 5,
                                                                     "subject": "git-authority"}
    notes = [p for p in data["identical"] if p["b"]["source"] == "notes"]
    assert notes and notes[0]["b"]["file"] == "notes/feedback_lang.md" and notes[0]["b"]["value"] == "english"
    assert {u["class"] for u in data["one_side"]} == {"one_side"}
    assert data["to_check"][0]["subject"] == "git-authority" and data["to_check"][0]["value"] is None


def test_the_command_text_report_and_no_subject_list(ada, capsys):
    code, out, _ = _run(capsys, _flags(ada))
    assert code == 0
    assert "contradictory: not computed" in out and "no subject list" in out
    assert "identical (2)" in out and "one side (" in out
    assert "global:" in out and "Never commit without being asked." in out


def test_the_subject_list_comes_from_config_json(ada, capsys, tmp_path):
    (ada["brain"] / "rules").mkdir()
    (ada["brain"] / "rules" / "subjects.yaml").write_text(SUBJECTS.read_text(encoding="utf-8"), encoding="utf-8")
    (ada["brain"] / "config.json").write_text(json.dumps({
        "v": 1, "identity": {"owner": "Ada", "kind": "person"},
        "rules_diff": {"subjects": "rules/subjects.yaml", "restricted": ["some-key"]}}), encoding="utf-8")
    assert config.check(ada["brain"]) == []   # the key is in the schema
    code, out, _ = _run(capsys, _flags(ada, "--json"))
    assert code == 0 and json.loads(out)["counts"]["contradictory"] == 1
    (ada["brain"] / "rules" / "subjects.yaml").unlink()   # named by config.json, not found: an error
    code, _, err = _run(capsys, _flags(ada))
    assert code == 2 and "rules_diff.subjects" in err


def test_project_after_the_subcommand_reads_that_projects_claude_md(ada, capsys, monkeypatch):
    """Run from another repo with a CLAUDE.md of its own: --project lab reads lab's, not the current folder's."""
    reg = ada["brain"] / "projects.yaml"
    reg.write_text(f"lab: {{root: {ada['lab'].as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    here = ada["tmp"] / "elsewhere"
    (here / ".git").mkdir(parents=True)
    (here / "CLAUDE.md").write_text("- A rule only the current folder's repo has.\n", encoding="utf-8")
    monkeypatch.chdir(here)
    argv = ["rules", "diff", "--machine-rules", str(ada["machine"]), "--global", str(ada["global"]),
            "--notes", str(ada["tmp"] / "notes"), "--json"]
    for tail, want, not_want in ((["--project", "lab"], "toi-même", "only the current folder"),
                                 ([], "only the current folder", "toi-même")):
        code, out, _ = _run(capsys, argv + tail)
        assert code == 0
        texts = " ".join(u["excerpt"] for u in _units_of(json.loads(out)))
        assert want in texts and not_want not in texts, tail


def test_a_missing_explicit_file_exits_non_zero(ada, capsys):
    for flag in ("--machine-rules", "--global", "--project-rules", "--subjects"):
        argv = _flags(ada) + [flag, str(ada["tmp"] / "missing.md")]   # a repeatable flag: both files, one missing
        code, out, err = _run(capsys, argv)
        assert code == 2 and "not found" in err and out == "", flag
    code, _, err = _run(capsys, _flags(ada) + ["--notes", str(ada["tmp"] / "no-such-folder")])
    assert code == 2 and "not a folder" in err


def test_the_default_sources_skip_what_is_missing_and_read_every_memory_folder(ada, capsys, monkeypatch):
    (ada["claude"] / "CLAUDE.md").write_text(MACHINE, encoding="utf-8")
    _note(ada["claude"] / "projects" / "k1" / "memory", "feedback_a", "Write commits in English.")
    _note(ada["claude"] / "projects" / "k2" / "memory", "feedback_b", "Prefer bash, always.")
    monkeypatch.chdir(ada["lab"])
    code, out, _ = _run(capsys, ["rules", "diff", "--json"])
    assert code == 0
    data = json.loads(out)
    assert {s["source"] for s in data["sources"]} >= {"machine", "project", "notes"}
    files = {u["file"] for u in data["one_side"]} | {p[s]["file"] for c in ("identical", "near") for p in data[c]
                                                      for s in "ab"}
    assert {"k1/feedback_a.md", "k2/feedback_b.md"} <= files


# --- the restricted reader ---

CANARY = "zq7-canary-restricted-4417"


def _restricted(root: Path) -> Path:
    mem = root / "projects" / "secret-key" / "memory"
    _note(mem, "feedback_one", f"Never commit without being asked. {CANARY}")
    _note(mem, "feedback_two", "Crée et merge tes PR toi-même.")
    _note(mem, "feedback_broken", "Text.", meta=f"name: [{CANARY}\ntype: feedback\n")
    _note(mem, "user_note", f"{CANARY} is a user note.", kind="user")
    return mem


def test_the_restricted_reader_gives_names_and_subjects_only(ada):
    mem = _restricted(ada["claude"])
    got = rulesdiff.restricted_feedback_subjects([mem], rulesdiff.load_subjects(SUBJECTS))
    assert got == [{"name": "feedback_one", "subjects": ["git-authority"]},
                   {"name": "feedback_two", "subjects": ["git-authority"]}]


def test_the_restricted_reader_refuses_an_agent_session(ada, monkeypatch, capsys):
    mem = _restricted(ada["claude"])
    for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "BRAIN_AGENT_SESSION"):
        with monkeypatch.context() as m:
            m.setenv(var, "1")
            with pytest.raises(rulesdiff.Refused, match=var):
                rulesdiff.restricted_feedback_subjects([mem], None)
            code, out, _ = _run(capsys, _flags(ada, "--restricted-notes", str(mem), "--json"))
            data = json.loads(out)
            assert code == 0 and data["restricted"] == {"folders": 1, "refused": var, "notes": [], "unmatched": []}
            assert CANARY not in out and not any(u["file"].startswith("secret-key/") for u in _units_of(data))


def test_restricted_notes_stay_out_of_the_ordinary_notes_while_the_reader_is_refused(ada, monkeypatch, capsys):
    """In an agent session the reader is refused, and the restricted folder still stays out of the machine's notes
    (config.json's entry), and out of --notes when a flag names it (finding: a --notes folder was read as notes)."""
    mem = _restricted(ada["claude"])
    open_mem = ada["claude"] / "projects" / "open-key" / "memory"
    _note(open_mem, "feedback_open", "Write commits in English.")
    (ada["brain"] / "config.json").write_text(json.dumps({
        "v": 1, "identity": {"owner": "Ada", "kind": "person"},
        "rules_diff": {"restricted": ["secret-key"]}}), encoding="utf-8")
    monkeypatch.setenv("CLAUDECODE", "1")
    base = ["rules", "diff", "--machine-rules", str(ada["machine"]), "--global", str(ada["global"]),
            "--project-rules", str(ada["project"]), "--json"]
    for extra in ([], ["--notes", str(mem), "--notes", str(open_mem)]):
        code, out, _ = _run(capsys, base + extra)
        data = json.loads(out)
        assert code == 0 and data["restricted"]["refused"] == "CLAUDECODE" and CANARY not in out, extra
        files = {u["file"] for u in _units_of(data)}
        assert "open-key/feedback_open.md" in files and not any(f.startswith("secret-key/") for f in files), extra
    assert {"source": "notes", "file": mem.as_posix(), "why": "restricted"} in data["skipped"]


def test_restricted_notes_flag_adds_to_the_config_and_a_key_covers_its_worktrees(ada, capsys):
    """--restricted-notes adds to config.json's rules_diff.restricted (both stay out of the ordinary notes, both are
    read for names and subjects); a key's worktree folders (key-...) are restricted too; an entry that matches no
    folder is reported."""
    _restricted(ada["claude"])
    wt = ada["claude"] / "projects" / "secret-key--claude-worktrees-x" / "memory"
    _note(wt, "feedback_wt", f"Write commits in English. {CANARY}")
    other = ada["tmp"] / "other-restricted"
    _note(other, "feedback_other", f"Prefer bash, always. {CANARY}")
    (ada["brain"] / "config.json").write_text(json.dumps({
        "v": 1, "identity": {"owner": "Ada", "kind": "person"},
        "rules_diff": {"restricted": ["secret-key", "no-such-key"]}}), encoding="utf-8")
    flags = ["rules", "diff", "--machine-rules", str(ada["machine"]), "--global", str(ada["global"]),
             "--project-rules", str(ada["project"])]
    code, out, _ = _run(capsys, flags + ["--subjects", str(SUBJECTS), "--restricted-notes", str(other), "--json"])
    assert code == 0 and CANARY not in out
    data = json.loads(out)
    assert not any(u["source"] == "notes" for u in _units_of(data))
    assert {n["name"] for n in data["restricted"]["notes"]} == {"feedback_one", "feedback_two", "feedback_wt",
                                                                "feedback_other"}
    assert data["restricted"]["unmatched"] == ["no-such-key"]
    code, out, _ = _run(capsys, flags)
    assert code == 0 and "restricted entry no-such-key: no memory folder" in out and CANARY not in out
    assert rulesdiff.is_restricted(wt, {"secret-key"}, [])
    assert not rulesdiff.is_restricted(ada["claude"] / "projects" / "secret-keyring" / "memory", {"secret-key"}, [])


def test_canary_a_restricted_note_reaches_no_log_alert_record_or_output(ada, capsys, tmp_path):
    """The canary: a unique string in restricted notes (one read, one whose front matter breaks) is found nowhere
    after both outputs: not in the text or JSON output, not in ledger/errors.log, alert.txt or records/, not in any
    other file under the test's folders, and the restricted folder is left out of the machine's notes."""
    mem = _restricted(ada["claude"])
    (ada["brain"] / "config.json").write_text(json.dumps({
        "v": 1, "identity": {"owner": "Ada", "kind": "person"},
        "rules_diff": {"restricted": ["secret-key"]}}), encoding="utf-8")
    outputs = []
    for extra in ([], ["--json"]):
        code, out, err = _run(capsys, ["rules", "diff", "--machine-rules", str(ada["machine"]), "--global",
                                       str(ada["global"]), "--project-rules", str(ada["project"]),
                                       "--subjects", str(SUBJECTS), *extra])
        assert code == 0
        outputs.append(out + err)
    assert all(CANARY not in o for o in outputs)
    assert "feedback_one: git-authority" in outputs[0]
    data = json.loads(outputs[1].strip())
    assert data["restricted"]["notes"] == [{"name": "feedback_one", "subjects": ["git-authority"]},
                                           {"name": "feedback_two", "subjects": ["git-authority"]}]
    assert not any(u["source"] == "notes" for u in _units_of(data))   # in no class: not read as an ordinary note
    log = Path(str(ada["tmp"] / "brain-home")) / "ledger" / "errors.log"
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "restricted note feedback_broken:" in text and "Error" in text and CANARY not in text
    for f in tmp_path.rglob("*"):   # BRAIN_HOME (ledger, memory-sync/alert.txt) and the brain (records/) included
        if f.is_file() and mem not in f.parents:
            assert CANARY.encode() not in f.read_bytes(), f
