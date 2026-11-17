"""brain decision apply (brain.answerapply): the answered DDRs applied at zero token but the prose: the ADR's skeleton
(Context and Decision from the DDRs, Why and Revisit if left TODO), decided_by edges and props.decided_<date> on the
items they name, the answers table in their spec's section, then the acks. Fixtures only: the tests' Ada."""

import json

import pytest
import yaml

from brain import answerapply, cli, decisions

AT = "2026-11-02T09:00:00Z"
SPEC = """# Spec X

## 1. Context

Some text.

## 2. Questions

- **ZEN-1, the first question.** Options: a, b.

```
ZEN-2 inside a fence does not count
```

### 2.1 Details

- ZEN-2 here.

## 3. Build path

The end.
"""
LOG = "# Decisions\n\n## 2026-10-30 — X\n\n**Context.** c\n"


@pytest.fixture
def root(store):
    r = store.parents[1]
    (r / "docs").mkdir()
    (r / "docs" / "x.md").write_text(SPEC, encoding="utf-8", newline="\n")
    (r / "notes" / "decisions.md").write_text(LOG, encoding="utf-8", newline="\n")
    one, _ = decisions.ask(r, title="ZEN-1: the first question", question="Which first?",
                           options=["Alpha: fast, one step", "Beta: slow"], why="fast", at=AT,
                           items=["wi-one", "wi-gone"], specs=["spec-x"])
    two, _ = decisions.ask(r, title="ZEN-2: the second question", question="Which second?",
                           options=["Gamma: kept", "Delta: dropped", "Epsilon: both"], why="kept", at=AT,
                           items=["wi-one", "wi-two"], specs=["spec-x"], multi=True)
    decisions.answer(r, one["id"], ["Alpha"], by="Ada", via="ask-tool", at="2026-11-02T10:00:00Z")
    decisions.answer(r, two["id"], ["Gamma", "Epsilon"], other="and a note", by="Ada", via="ask-tool",
                     at="2026-11-03T10:00:00Z")
    return r


ADR = "adr-2026-11-04-ada-s-answers-of-2026-11-03-to-zen-1-to-zen-2"


def _apply(root, *more):
    return cli.main(["--root", str(root), "decision", "apply", "--date", "2026-11-04", *more])


def test_the_plan_names_each_write_and_writes_nothing(root, capsys):
    assert _apply(root) == 0
    out = capsys.readouterr().out
    assert f"adr: {ADR}" in out and "## Ada's answers of 2026-11-03 to ZEN-1 to ZEN-2" in out
    assert "- ZEN-1: « Alpha »: fast, one step. Items: wi-one." in out
    assert "- ZEN-2: « Gamma », « Epsilon », own text: « and a note »: kept; both. Items: wi-one, wi-two." in out
    assert "item: wi-one decided_by" in out and "props.decided_2026_11_03_zen=" in out
    assert "spec: spec-x: the answers table (x.md line 19, the end of « 2. Questions »)" in out
    assert f"ack: ddr-2026-11-02-zen-1-the-first-question --applied {ADR}, wi-one, spec-x 2. Questions" in out
    assert "not in the store: wi-gone (left out)" in out and "not written: --write" in out
    assert (root / "notes" / "decisions.md").read_text("utf-8") == LOG
    assert (root / "docs" / "x.md").read_text("utf-8") == SPEC
    assert all(d["status"] == "answered" for _, d in decisions.load(root))


def test_write_applies_everything_but_the_prose(root, capsys):
    assert _apply(root, "--write", "--session", "s-1") == 0
    out = capsys.readouterr().out
    assert f"fill {ADR}'s Why and Revisit if" in out
    log = (root / "notes" / "decisions.md").read_text("utf-8")
    assert log.startswith(LOG) and "## 2026-11-04 — Ada's answers of 2026-11-03 to ZEN-1 to ZEN-2" in log
    assert "**Context.** Ada answered 2 question(s) (ask-tool), asked in spec-x:" in log
    assert "- ZEN-1 (ddr-2026-11-02-zen-1-the-first-question): Which first?" in log
    assert "**Why.** TODO" in log and "**Revisit if.** TODO" in log
    edges = yaml.safe_load((root / "notes" / "graph" / "edges" / "work.yaml").read_text("utf-8"))
    assert {(e["from"], e["to"]) for e in edges if e["type"] == "decided_by"} == {("wi-one", ADR), ("wi-two", ADR)}
    nodes = {n["id"]: n for n in yaml.safe_load((root / "notes" / "graph" / "nodes" / "work.yaml").read_text("utf-8"))}
    one = nodes["wi-one"]["props"]["decided_2026_11_03_zen"]
    assert one.startswith(f"Ada, 2026-11-02 ({ADR}, ZEN-1): « Alpha »; Ada, 2026-11-03 ({ADR}, ZEN-2)")
    spec = (root / "docs" / "x.md").read_text("utf-8")
    table = ("**Ada's answers (2026-11-03, ask-tool):**\n\n| Question | Answer | Applied |\n|---|---|---|\n"
             f"| ZEN-1 | « Alpha » | `{ADR}`, `wi-one` |\n")
    assert f"- ZEN-2 here.\n\n{table}" in spec and spec.endswith("## 3. Build path\n\nThe end.\n")
    assert spec.index(table) < spec.index("## 3. Build path")
    for _, d in decisions.load(root):
        assert d["status"] == "archived" and d["applied"]["in"][0] == ADR and d["applied"]["session"] == "s-1"
    assert _apply(root) == 1   # applied: nothing left
    assert "no answered decision to apply" in capsys.readouterr().err


def test_a_decision_not_answered_is_refused(root, capsys):
    pending, _ = decisions.ask(root, title="ZEN-3: later", question="?", options=["A: a", "B: b"], why="a", at=AT)
    assert _apply(root, pending["id"]) == 1
    assert f"{pending['id']} is pending: only an answered decision is applied" in capsys.readouterr().err


def test_spec_narrows_and_json_gives_the_plan(root, capsys):
    other, _ = decisions.ask(root, title="Unrelated", question="?", options=["A: a", "B: b"], why="a", at=AT)
    decisions.answer(root, other["id"], ["A"], by="Ada", at=AT)
    assert _apply(root, "--spec", "spec-x", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert [d["code"] for d in data["ddrs"]] == ["ZEN-1", "ZEN-2"] and data["props_key"] == "decided_2026_11_03_zen"
    assert data["specs"][0]["section"] == "2. Questions" and data["unknown"] == ["wi-gone"]
    assert _apply(root, other["id"], "--title", "A choice of Ada's") == 0
    assert "## A choice of Ada's" in capsys.readouterr().out


def test_codes_and_the_place_of_the_table():
    a = [answerapply.Answer(i, c, "", "", "", [], [], "", "", "Ada", "2026-11-02", "", [], [])
         for i, c in (("d1", "ZEN-1"), ("d2", "ZEN-3"))]
    assert answerapply._codes(a) == "ZEN-1 to ZEN-3" and answerapply._prefix(a) == "zen"
    a[1].code = "TOK-2"
    assert answerapply._codes(a) == "ZEN-1 and TOK-2" and answerapply._prefix(a) == ""
    lines = SPEC.split("\n")
    assert answerapply._place(lines, "ZEN-9") == (lines.index("## 3. Build path"), "2. Questions")   # the heading
    assert answerapply._place(["# T", "", "text"], "ZEN-9") == (3, "")                             # the end
    assert answerapply._place(lines, "ZEN-2")[1] == "2.1 Details"   # the fenced mention is passed over


def test_another_projects_answers_are_left_out_and_a_stopped_run_is_refused(root, capsys):
    other, _ = decisions.ask(root, title="ZEN-9: theirs", question="?", options=["A: a", "B: b"], why="a", at=AT,
                             project="elsewhere")
    decisions.answer(root, other["id"], ["A"], by="Ada", at=AT)
    assert other["id"] not in [d["id"] for d in answerapply.select(root, [], "", "demo")]
    assert other["id"] in [d["id"] for d in answerapply.select(root, [], "", "elsewhere")]
    log = root / "notes" / "decisions.md"
    log.write_text(LOG + "\n## 2026-11-04 — Ada's answers of 2026-11-03 to ZEN-1 to ZEN-2\n", encoding="utf-8")
    assert _apply(root, "--spec", "spec-x", "--write") == 2
    assert "refused: the decision log already holds" in capsys.readouterr().out
    assert all(d["status"] == "answered" for _, d in decisions.load(root))


def test_a_spec_without_a_file_is_not_named_in_the_acks(root, capsys):
    (root / "docs" / "x.md").unlink()
    assert _apply(root, "--write") == 0
    out = capsys.readouterr().out
    assert "spec: spec-x has no file in the root: its table is not written" in out
    assert all("spec-x" not in " ".join(d["applied"]["in"]) for _, d in decisions.load(root))
    assert "not in the store: wi-gone (left out)" in out
