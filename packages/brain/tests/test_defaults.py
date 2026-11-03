"""Decisions by default, then reviewed (wi-brain-decision-default): the low-stakes mark, refused on the topics a
default never decides; final 24 h later without an answer; the review list; reversible with --again."""

import json

import pytest
import yaml

from brain import batch, cli, decisions, defaults, graph, midsession, projects, records

AT = "2026-11-01T09:00:00Z"
BEFORE = "2026-11-02T08:59:59Z"
AFTER = "2026-11-02T09:00:00Z"


def _root(store):
    return store.parents[1]


def _ask(root, title, question="Which one?", options=("Short: fewer words", "Long: more words"), **kw):
    return decisions.ask(root, title=title, question=question, options=list(options), why="clearer", at=AT,
                         project="demo", **kw)[0]


@pytest.fixture
def registry(tmp_path, monkeypatch, store):
    root = _root(store)
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)
    return root


def test_ask_low_stakes_marks_the_recommendation_and_its_deadline(store):
    ddr = _ask(_root(store), "Label wording", low_stakes=True)
    assert ddr["default"] == {"option": "Short", "after": "2026-11-02T09:00:00Z"}
    assert ddr["status"] == "pending" and records.check(_root(store)) == ([], [])


@pytest.mark.parametrize("title, question, topic", [
    ("Pilot price", "Which price for the pilot?", "money"),
    ("Rotate", "Rotate the API key now?", "keys"),
    ("Vault", "Create the recovery key?", "keys"),
    ("Repo", "Make the repo public?", "visibility"),
    ("Release", "Publish the release notes?", "publication"),
    ("Tag", "Push the tag v1.2?", "publication"),
    ("Sign-up", "Create an account for the tester?", "accounts"),
    ("Canary", "Arm the boot of the node?", "arming"),
    ("Lint", "A new rule for the backlog?", "rules"),
    ("Cron", "Add a scheduled task for the alerts?", "scheduled tasks"),
    ("Prix", "Quel tarif pour le pilote ?", "money"),
    ("Clé", "Créer la clé de récupération ?", "keys"),
    ("Dépôt", "Rendre le dépôt public ?", "visibility"),
    ("Tâche", "Créer une tâche planifiée ?", "scheduled tasks"),
])
def test_the_mark_is_refused_on_what_a_default_never_decides(store, title, question, topic):
    root = _root(store)
    with pytest.raises(decisions.QueueError, match=f"--low-stakes refused: a decision on {topic}"):
        _ask(root, title, question, low_stakes=True)
    assert not (root / "records" / "ddr").is_dir() or not list((root / "records" / "ddr").iterdir())
    _ask(root, title, question)  # without the mark: the owner's, as always


def test_brain_check_refuses_a_hand_written_mark(store):
    root = _root(store)
    ddr = _ask(root, "Domain", "Spend twenty euros on a domain?")
    ddr["default"] = {"option": "Short", "after": AFTER}
    records.write(root, "ddr", ddr, replace=True)
    errors, _ = records.check(root)
    assert any("low-stakes mark refused: a decision on money ('euros')" in e for e in errors)
    ddr = _ask(root, "Wording", "Which wording?")
    ddr["default"] = {"option": "Long", "after": AFTER}
    records.write(root, "ddr", ddr, replace=True)
    assert any("default.option 'Long' is not the recommendation" in e for e in records.check(root)[0])


def test_final_by_default_24_hours_later_then_reviewed_and_reversible(registry, capsys):
    root = registry
    _ask(root, "Label wording", low_stakes=True)
    _ask(root, "Answered early", low_stakes=True)
    decisions.answer(root, "answered-early", ["Long"], at=BEFORE, by="Ada")
    assert defaults.finalize(root, BEFORE) == []
    assert defaults.review(root, BEFORE)["provisional"][0]["hours_left"] == 0
    assert defaults.finalize(root, AFTER) == ["ddr-2026-11-01-label-wording"]
    ddr = decisions.find(root, "label-wording")[1]
    assert ddr["status"] == "answered"
    assert ddr["answer"] == {"at": AFTER, "by": "default", "choices": ["Short"], "via": "default"}
    assert records.check(root) == ([], [])
    assert defaults.finalize(root, "2026-11-09T00:00:00Z") == []  # once
    assert decisions.find(root, "answered-early")[1]["answer"]["choices"] == ["Long"]  # the owner's answer stays

    base = ["--project", "demo", "decision"]
    assert cli.main(base + ["defaulted", "--at", AFTER]) == 0
    out = capsys.readouterr().out
    assert "demo: 1 decision(s) taken by default to review, 0 provisional, 0 reversed; reverse one: brain decision " \
           "answer ID <option> --again" in out
    assert "  ddr-2026-11-01-label-wording: Label wording -> Short (final 2026-11-02T09:00:00Z)" in out
    text = decisions.announce(root)   # the SessionStart hook announces it like any answer not integrated yet
    assert "ddr-2026-11-01-label-wording: Short (by default" in text

    assert cli.main(base + ["defaulted", "--seen", "--at", AFTER]) == 0
    assert "reviewed 1: ddr-2026-11-01-label-wording" in capsys.readouterr().out
    assert decisions.find(root, "label-wording")[1]["default"]["reviewed"] == {"at": AFTER}
    assert cli.main(base + ["defaulted", "--json", "--at", AFTER]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["defaulted"] == [] and data["reviewed"] == 1

    assert cli.main(base + ["answer", "label-wording", "Long", "--again", "--at", "2026-11-03T10:00:00Z"]) == 0
    capsys.readouterr()
    assert cli.main(base + ["defaulted", "--at", "2026-11-03T10:00:00Z"]) == 0
    assert "reversed ddr-2026-11-01-label-wording: Label wording: Short -> Long" in capsys.readouterr().out


def test_apply_and_seen_from_the_cli(registry, monkeypatch, capsys):
    root = registry
    _ask(root, "Label wording", low_stakes=True)
    base = ["--project", "demo", "decision", "defaulted"]
    assert cli.main(base + ["--at", BEFORE]) == 0
    assert "provisional ddr-2026-11-01-label-wording: Label wording -> Short (final in 0 h, unless answered)" in \
        capsys.readouterr().out
    assert cli.main(base + ["--apply", "--at", AFTER]) == 0
    assert "demo: ddr-2026-11-01-label-wording taken by default" in capsys.readouterr().out
    view = (root / "notes" / "decision_queue.md").read_text(encoding="utf-8")
    assert "## Answered, to integrate (1)" in view
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(base + ["--seen", "--at", AFTER]) == 1  # the owner's own note: not from an agent's session
    assert "not an agent's session" in capsys.readouterr().err


def test_the_morning_batch_and_the_hooks_name_the_defaults(registry, tmp_path):
    root = registry
    _ask(root, "Label wording", low_stakes=True)
    _ask(root, "Other wording", low_stakes=True)
    defaults.finalize(root, AFTER)   # both final
    _ask(root, "Third wording", low_stakes=True)
    for d in (root / "records" / "ddr").glob("*third*"):   # still provisional
        assert yaml.safe_load(d.read_text(encoding="utf-8"))["status"] == "pending"
    data = batch.build(projects.Project(name="demo", root=root))
    assert data["defaulted"] == "Taken by default, to review: 2 (1 provisional) — brain decision defaulted"
    zen = "\n".join(batch.zen(data))
    assert "  Taken by default, to review: 2 (1 provisional) — brain decision defaulted" in zen
    queue = root / "records" / "ddr"
    top = midsession._read(queue / "ddr-2026-11-01-label-wording.yaml")
    assert top["via"] == "default"
    assert "(by default: brain decision defaulted)" in midsession.render(queue, [top], [])


def test_topics_are_words_not_parts_of_words():
    assert defaults.topics({"title": "Monkey keyboard arms-length", "question": "Keystroke or tagline?"}) == []
    assert defaults.topics({"title": "x", "question": "y", "options": [{"label": "Rotate the password"}]}) == [
        ("keys", "password")]
