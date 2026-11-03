import json
from datetime import date

import pytest
import yaml

from brain import batch, cli, decisions, graph, projects, queue, records

AT = "2026-11-01T09:00:00Z"
TODAY = date(2026, 11, 3)


def _root(store):
    return store.parents[1]


def _graph(store):
    """wi-a <- wi-b <- wi-c -> ms-x: a DDR on wi-a unblocks 4, on wi-b 3, on wi-c 2, on wi-q 1."""
    with open(store / "nodes" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("- {id: wi-a, type: WorkItem, status: todo, title: \"A\"}\n"
                 "- {id: wi-b, type: WorkItem, status: todo, title: \"B\"}\n"
                 "- {id: wi-c, type: WorkItem, status: doing, title: \"C\"}\n"
                 "- {id: wi-q, type: WorkItem, status: todo, title: \"Q\"}\n")
    with open(store / "edges" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("- {from: wi-b, to: wi-a, type: depends_on}\n- {from: wi-c, to: wi-b, type: depends_on}\n"
                 "- {from: wi-c, to: ms-x, type: part_of}\n")


def _ask(root, title, question, items=None, specs=None, options=("Yes: go", "No: wait"), **kw):
    return decisions.ask(root, title=title, question=question, options=list(options), why="simplest", at=AT,
                         items=items, specs=specs, project="demo", **kw)[0]


def _queue(store):
    """Eight pending decisions: a blocking one, a brainstorm's Q1-Q3 (spec-x), two of one item, a lone one, another
    brainstorm's Q1 (spec-y); and an action, which no batch takes."""
    root = _root(store)
    _graph(store)
    _ask(root, "Q2 — Which host?", "Quel hôte ?", items=["wi-a"], specs=["spec-x"],
         options=["Alpha: a", "Beta, gamma: b, with a comma", "Delta"], multi=True)
    _ask(root, "Q1 — Which venue?", "Quel lieu ?", items=["wi-q"], specs=["spec-x"],
         options=["Venue A: the first", "Venue B"])
    _ask(root, "Q3 — Which name?", "Quel nom ?", specs=["spec-x"])
    _ask(root, "Rules lint: one", "Guard rule one?", items=["wi-c"], options=["Guard it: a hook", "Keep it soft"])
    _ask(root, "Rules lint: two", "Guard rule two?", items=["wi-c"], options=["Guard it: a hook", "Keep it soft"])
    _ask(root, "Lone question", "Alone?")
    _ask(root, "Urgent", "Urgent question?", items=["wi-b"], blocking=True)
    _ask(root, "Q1 — Other brainstorm", "Autre ?", specs=["spec-y"])
    queue.add(root, kind="action", title="Enter the key", what="in the vault", at=AT, items=["wi-q"])
    return root


# --- headers and groups ---

@pytest.mark.parametrize("title, chip", [
    ("Q6 — New milestone ms-brain-trust?", "Q6 milestone"),
    ("Q1 — What does 'floorplane' mean?", "Q1"),
    ("BRIQUE-10 — Where do trust and identity live in the module tree?", "BRIQUE-10"),
    ("ACME-3 — Workstation box1 is also ACME's GPU node", "ACME-3"),
    ("Q4 — Identity: Brain credentials standalone", "Q4 Identity"),
    ("Q2 — Que faut-il chiffrer d'abord ?", "Q2 chiffrer"),
    ("Rules lint: a guard for rule-backlog-current?", "Rules lint"),
    ("Notifications — ntfy.sh public ou serveur ntfy à soi ?", "Notification"),
    ("Allow brain resume without a permission prompt", "Allow brain"),
    ("", "?"),
])
def test_header_fits_the_tools_chip(title, chip):
    assert batch.header(title) == chip and len(chip) <= batch.HEADER


def test_repeated_chips_are_numbered_within_a_call():
    assert batch._unique(["Rules lint", "Q1", "Rules lint", "Rules lint"]) == ["Rules lint", "Q1", "Rules lint 2",
                                                                                "Rules lint 3"]
    assert batch._unique(["Abcdefghijkl", "Abcdefghijkl"]) == ["Abcdefghijkl", "Abcdefghij 2"]


def test_groups_a_brainstorm_then_an_item_then_a_spec():
    one = {"id": "ddr-x-1", "title": "BRIQUE-3 — Order?", "links": {"specs": ["spec-b"], "items": ["wi-z"]}}
    assert batch.group_of(one) == ("series:BRIQUE:spec-b", "BRIQUE* (spec-b)")
    assert batch._series(one) == ("BRIQUE", 3)
    nospec = {"id": "ddr-x-2", "title": "Q4 — x", "asked": {"at": AT}}
    assert batch.group_of(nospec)[0] == "series:Q:2026-11-01"  # one brainstorm: the same day
    assert batch.group_of({"id": "d", "title": "t", "links": {"items": ["wi-z"], "specs": ["s"]}}) == ("item:wi-z",
                                                                                                    "wi-z")
    assert batch.group_of({"id": "d", "title": "t", "links": {"specs": ["s"]}}) == ("spec:s", "s")
    assert batch.group_of({"id": "d", "title": "t"}) == ("ddr:d", "d")


# --- batches ---

def test_build_puts_blocking_first_then_groups_by_what_they_unblock(store):
    root = _queue(store)
    data = batch.build(projects.for_root(root), today=TODAY)
    assert data["decisions"] == 8 and data["blocking"] == 1
    assert data["rest"] == {"decision": 0, "action": 1, "permission": 0}
    got = [[i.split("ddr-2026-11-01-")[1] for i in b["ids"]] for b in data["batches"]]
    assert got == [["urgent"],  # blocking: first, alone
                   ["q1-which-venue", "q2-which-host", "q3-which-name"],  # unblocks 4 (Q2), in numbered order
                   ["rules-lint-one", "rules-lint-two", "lone-question", "q1-other-brainstorm"]]  # 2, 0, 0
    first, second, third = data["batches"]
    assert first["blocking"] and first["unblocked"] == ["ms-x", "wi-b", "wi-c"]
    assert second["title"] == "Q* (spec-x)" and second["unblocks"] == 6  # wi-a, wi-b, wi-c, ms-x, wi-q, wi-one
    assert third["title"] == "wi-c + ddr-2026-11-01-lone-question + Q* (spec-y)"
    assert [q["header"] for q in third["questions"]] == ["Rules lint", "Rules lint 2", "Lone", "Q1 Other"]
    assert "--project" not in third["answer"]
    assert batch.build(projects.for_root(root), today=TODAY, named=True)["batches"][0]["answer"].endswith(
        "--project " + projects.for_root(root).name)
    small = batch.build(projects.for_root(root), size=2, today=TODAY)
    assert [len(b["ids"]) for b in small["batches"]] == [1, 2, 1, 2, 2]  # Q3 left alone: wi-c's pair does not fit
    with pytest.raises(batch.BatchError, match="1 to 4"):
        batch.build(projects.for_root(root), size=5)


def test_questions_are_the_ask_tools_input_as_is(store):
    root = _queue(store)
    data = batch.build(projects.for_root(root), today=TODAY)
    for b in data["batches"]:
        assert batch.check_questions(b["questions"]) == []
        assert len(b["questions"]) == len(b["ids"]) == len(b["entries"])
    urgent = data["batches"][0]["questions"][0]
    assert urgent["question"] == "[BLOQUANT] Urgent question?" and urgent["header"] == "Urgent"
    assert urgent["options"][0] == {"label": "Yes (Recommandé)", "description": "go Pourquoi : simplest"}
    assert urgent["options"][1] == {"label": "No", "description": "wait"}
    host = data["batches"][1]["questions"][1]
    assert host["multiSelect"] is True and host["options"][2] == {"label": "Delta", "description": "-"}
    bad = [dict(urgent, header="A header too long"), dict(urgent, extra=1), dict(urgent, options=urgent["options"][:1])]
    errs = batch.check_questions(bad + [urgent])
    assert any("header" in e for e in errs) and any("keys" in e for e in errs) and any("1 options" in e for e in errs)
    assert any("same text" in e for e in errs) and batch.check_questions([]) == ["0 questions (1 to 4 per call)"]


def test_repeated_question_texts_carry_their_id(store):
    root = _root(store)
    _ask(root, "Rules lint: one", "Guard it?", items=["wi-one"])
    _ask(root, "Rules lint: two", "Guard it?", items=["wi-one"])
    qs = batch.build(projects.for_root(root), today=TODAY)["batches"][0]["questions"]
    assert [q["question"] for q in qs] == ["Guard it? (ddr-2026-11-01-rules-lint-one)",
                                           "Guard it? (ddr-2026-11-01-rules-lint-two)"]
    assert batch.check_questions(qs) == []


def test_zen_shows_one_session_then_the_rest(store):
    root = _queue(store)
    data = batch.build(projects.for_root(root), today=TODAY)
    # the blocking batch and the band now (Q3's spec holds up a P0), always; the rest when they fit
    assert batch.session(data, 0) == 3 and batch.session(data, 1) == 2
    assert [b["band"] for b in data["batches"]] == ["now", "now", "later"]
    text = "\n".join(batch.zen(data, minutes=1))
    assert text.startswith("Morning decisions — ") and "8 decision(s) in 3 batch(es) of up to 4, 1 blocking" in text
    assert "Batch 1/3 [BLOQUANT] · now · blocking · unblocks 3" in text
    assert "Batch 2/3 · now · Q* (spec-x) · unblocks 6" in text
    assert "  1. [Urgent] [BLOQUANT] Urgent question?" in text and "     a) Yes (Recommandé): go" in text
    assert "     Pourquoi : simplest" in text and "Later (1 batch(es), 4 question(s)" in text
    assert "  3/3 · when you can · wi-c + ddr-2026-11-01-lone-question + Q* (spec-y) · unblocks 2: " in text
    assert "1 action(s)" in text
    full = "\n".join(batch.zen(data, minutes=0))
    assert "Later" not in full and "several choices" in full and "  then: brain decision answer --batch" in full
    lines = batch.render(data)
    assert lines[0].endswith("(brain decision batch --zen: the morning digest; --json: the question tool's input)")
    assert any(x.startswith("    Q2 host        4  ddr-2026-11-01-q2-which-host: Q2 — Which host? -> recommended: "
                            "Alpha") for x in lines)
    empty = batch.build(projects.for_root(store.parents[2] / "nothing"), today=TODAY)
    assert batch.zen(empty)[0].endswith("no decision waiting on Ada.") and empty["batches"] == []


# --- answers ---

def _status(root, ref):
    return decisions.find(root, ref)[1]


def test_answer_batch_takes_the_ask_tools_answers(store):
    root = _queue(store)
    answers = {
        "Quel lieu ?": "Venue A (Recommandé)",  # the question's text, as the tool keys it
        "ddr-2026-11-01-q2-which-host": {"choices": ["Alpha (Recommandé)", "Beta, gamma"], "other": "my own idea"},
        "q3-which-name": 2,  # a part of the id, an option's number
        "ddr-2026-11-01-rules-lint-one": {"choices": ["guard it"], "notes": "only on main"},
        "ddr-2026-11-01-rules-lint-two": "",  # no answer: stays pending
        "[BLOQUANT] Urgent question?": {"other": "Not now, ask me Friday"},  # the owner's own text, marked so
        "Autre ?": ["Yes"],
    }
    done = batch.answer_batch(root, json.dumps({"answers": answers}), at=AT)
    assert [d["id"].split("ddr-2026-11-01-")[1] for d in done["answered"]] == [
        "q1-which-venue", "q2-which-host", "q3-which-name", "rules-lint-one", "urgent", "q1-other-brainstorm"]
    assert done["skipped"] == ["ddr-2026-11-01-rules-lint-two"]
    assert _status(root, "q1-which-venue")["answer"] == {"at": AT, "by": "Ada", "choices": ["Venue A"],
                                                         "via": "ask-tool"}
    host = _status(root, "q2-which-host")["answer"]
    assert host["choices"] == ["Alpha", "Beta, gamma"] and host["other"] == "my own idea"
    assert _status(root, "q3-which-name")["answer"]["choices"] == ["No"]
    assert _status(root, "rules-lint-one")["answer"]["notes"] == "only on main"
    urgent = _status(root, "urgent")
    assert urgent["status"] == "answered" and urgent["answer"]["other"] == "Not now, ask me Friday"
    assert "choices" not in urgent["answer"]
    assert _status(root, "rules-lint-two")["status"] == "pending"
    assert records.check(root) == ([], [])
    with pytest.raises(batch.BatchError, match="not pending"):
        batch.answer_batch(root, '{"q1-which-venue": "Venue B"}', at=AT)
    again = batch.answer_batch(root, '{"q1-which-venue": "Venue B"}', at=AT, again=True, via="cli")
    assert again["answered"][0]["answer"]["choices"] == ["Venue B"]


def test_answer_batch_checks_every_key_before_writing(store):
    root = _queue(store)
    cases = [({"lone-question": "Yes", "no such thing": "x"}, "no DDR has this id or this question"),
             ({"lone-question": "Yes", "Alone?": "No"}, "answered twice"),
             ({"lone-question": ["Yes", "No"]}, "takes one choice"),
             ({"lone-question": 9}, "option 9 does not exist"),
             ({"lone-question": {"choices": ["Maybe"]}}, "not one of the options"),
             ({"enter-the-key": "done"}, "is of kind action: brain queue done"),
             ({"rules-lint": "Guard it"}, "several DDRs match"),
             # strict (wi-brain-answers-lane): an unmarked text that is no option's exact label writes nothing
             ({"lone-question": "Ye"}, r"not an option's exact label \(it shortens or extends 'Yes'\)"),
             ({"lone-question": "Not now"}, "the owner's own text goes in"),
             ({"lone-question": ["Yes", "and more"]}, "not an option's exact label"),
             ({"q2-which-host": "Alpha (Recommandé), Beta, gamma, my own idea"}, "'my own idea' is not an option")]
    for answers, message in cases:
        with pytest.raises(batch.BatchError, match=message) as exc:
            batch.answer_batch(root, json.dumps(answers), at=AT)
        assert str(exc.value).startswith("nothing written")
    assert _status(root, "lone-question")["status"] == "pending"
    assert batch.answer_batch(root, '{"lone-question": [""]}', at=AT) == {
        "answered": [], "skipped": ["ddr-2026-11-01-lone-question"]}
    for bad, message in (("not json", "not JSON"), ("[1, 2]", "a list of"), ("{}", "no answer given")):
        with pytest.raises(batch.BatchError, match=message):
            batch.answer_batch(root, bad, at=AT)
    listed = batch.parse('[{"id": "ddr-1", "choice": "A"}, {"question": "Q?", "other": "x"}]')
    assert listed == [("ddr-1", {"choice": "A"}), ("Q?", {"other": "x"})]
    assert batch._value({"id": "d", "options": [{"label": "A"}]}, {"notes": "n"}) is None


# --- the command ---

def test_cli_batch_and_answer(tmp_path, monkeypatch, store, capsys):
    root = _queue(store)
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)
    base = ["--project", "demo", "decision"]
    assert cli.main(base + ["batch", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "demo" and len(data["batches"]) == 3
    assert all(batch.check_questions(b["questions"]) == [] for b in data["batches"])
    assert cli.main(base + ["batch", "--zen", "--minutes", "1"]) == 0
    out = capsys.readouterr().out
    assert "Morning decisions — demo" in out and "Later (1 batch(es)" in out
    assert cli.main(base + ["batch"]) == 0 and "demo: 8 decision(s) in 3 batch(es)" in capsys.readouterr().out
    assert cli.main(base + ["batch", "--size", "5"]) == 1
    assert "1 to 4" in capsys.readouterr().err
    assert cli.main(["decision", "batch", "--all", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["batches"][0]["answer"].endswith("--project demo")
    assert cli.main(["decision", "batch", "--all"]) == 0
    assert "all: 8 decision(s) in 3 batch(es) across 1 of 1 project(s)" in capsys.readouterr().out

    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({data["batches"][1]["questions"][0]["question"]: "Venue B",
                                   data["batches"][0]["ids"][0]: "Yes (Recommandé)"}), encoding="utf-8")
    assert cli.main(base + ["answer", "--batch", f"@{answers}", "--via", "ask-tool", "--by", "Bob", "--at",
                            AT]) == 0
    out = capsys.readouterr().out
    assert "answered 2 decision(s) via ask-tool by Bob:" in out  # --by names someone else than the owner
    assert "  ddr-2026-11-01-q1-which-venue: Venue B" in out and "  ddr-2026-11-01-urgent: Yes" in out
    view = (root / "notes" / "decision_queue.md").read_text(encoding="utf-8")
    assert "## Answered, to integrate (2)" in view
    assert yaml.safe_load((root / "records" / "ddr" / "ddr-2026-11-01-urgent.yaml").read_text(
        encoding="utf-8"))["answer"]["via"] == "ask-tool"
    assert cli.main(base + ["answer", "--batch", str(answers), "--at", AT]) == 1  # a path; already answered
    assert "nothing written" in capsys.readouterr().err
    assert cli.main(base + ["answer", "--batch", '{"lone-question": "No"}', "--at", AT]) == 0  # the JSON itself
    assert _status(root, "lone-question")["answer"]["via"] == "cli"
    assert cli.main(base + ["answer"]) == 1 and "or --batch" in capsys.readouterr().err
    assert cli.main(base + ["answer", "alone", "--batch", "{}"]) == 1 and "no ID" in capsys.readouterr().err
    assert cli.main(base + ["answer", "--batch", "@missing.json"]) == 1
    assert "no such file" in capsys.readouterr().err
