"""wi-brain-owner-waits-check: brain check warns of an open item whose text says it waits on the owner while no field
the owner's queue reads (props.open, props.external_blocker, a pending DDR) carries it; a warning, never an error.
The tests run as Ada (tests/fixtures/brain); the phrasings are those found in a real backlog, renamed."""

import json

import pytest
import yaml

from brain import cli, decisions, graph, ownerwaits, waves


def _write(store, items: list[dict]):
    """The store's work items are ``items`` alone (the fixture's edges go with its items)."""
    (store / "nodes" / "work.yaml").write_text(yaml.safe_dump(items, allow_unicode=True), encoding="utf-8")
    (store / "edges" / "work.yaml").write_text("", encoding="utf-8")


def _item(nid, title="An item", status="todo", **props):
    return {"id": nid, "type": "WorkItem", "status": status, "title": title, "props": props}


def _found(store, root=None, names=("Ada",)):
    return {nid: phrase for nid, _, phrase in ownerwaits.findings(waves.load(store, root), list(names))}


WAITS = [
    ("progress", "the trial waits on Ada's install of the pinned binary; nothing else left"),
    ("waiting", "STEP-1 to STEP-5 wait on Ada"),
    ("left", "blocked on the owner: the lock is applied elevated"),
    ("left", "pending Ada's answer on the contract"),
    ("progress", "the data waits on Ada's install"),                    # a subject ending in « a »
    ("progress", "the schema waits for the owner"),
    ("left", "pending Ada’s answer on the contract"),                  # a typographic apostrophe
    ("left", "the release ships until Ada signs the tag"),
    ("engine", "installable from the public repo once Ada pushes v0.2.0"),
    ("brief", "the session prompt (Ada runs it on the laptop after the tag)"),
    ("left", "left: Ada's move of the folder with no session running"),
    ("left", "Ada still has to confirm the allow"),
    ("note", "attend le geste d'Ada sur le portable"),
    ("note", "en attente de la réponse du propriétaire"),
    ("note", "bloqué par Ada tant que la clé manque"),
    ("note", "dès que Ada aura signé, la PR part"),
    ("note", "jusqu’à ce que Ada signe le contrat"),
    ("note", "Ada doit signer le contrat"),
]


@pytest.mark.parametrize("key,text", WAITS)
def test_a_wait_said_in_prose_is_found(store, key, text):
    _write(store, [_item("wi-w", **{key: text})])
    assert list(_found(store)) == ["wi-w"]


def test_the_title_counts_and_the_excerpt_is_cut_at_words(store):
    _write(store, [_item("wi-w", title="Check the brain on a second machine, the laptop, in a session Ada runs there: "
                                       "the tester's path from the public tag")])
    where, phrase = ownerwaits.findings(waves.load(store), ["Ada"])[0][1:]
    assert where == "title"
    assert phrase == "…machine, the laptop, in a session Ada runs there: the tester's path from…"


NOT_WAITS = [
    ("idea", "Ada, 2026-11-14: waits on Ada's go"),                    # the source of an idea
    ("priority_reason", "Ada, 2026-11-14: blocked on the owner"),         # a past call
    ("decided_2026_11_02", "STEP-1 waits on Ada"),                        # a decision recorded
    ("validated", "2026-10-30 by Ada, once Ada signs"),
    ("scope", "each « waits on the owner » line names an item"),          # quoted: named, not said
    ("scope", 'the hand-over\'s "waiting on Ada" lines'),
    ("scope", "a wait on the owner said only in prose"),                  # a noun
    ("scope", "The wait on Ada is the longest one"),                      # a noun, capitalised
    ("scope", "the waiting-on-Ada time per item"),                        # a compound
    ("scope", "publishes the signed entries with Ada's go"),              # who decides, in general
    ("scope", "Ada decides the model, the budget and the trigger"),
    ("scope", "worth it only once Ada uses the view"),                    # a condition to come, no gesture
    ("scope", "waits on Bob's review"),                                   # someone else
]


@pytest.mark.parametrize("key,text", NOT_WAITS)
def test_history_quotes_and_design_phrasings_are_left_alone(store, key, text):
    _write(store, [_item("wi-n", **{key: text})])
    assert _found(store) == {}


@pytest.mark.parametrize("status", ["done", "dropped"])
def test_a_closed_item_is_left_alone(store, status):
    _write(store, [_item("wi-c", status=status, progress="waits on Ada's install")])
    assert _found(store) == {}


@pytest.mark.parametrize("field", ["open", "external_blocker", "owner_wait_checked"])
def test_a_wait_already_carried_or_checked_is_left_alone(store, field):
    _write(store, [_item("wi-f", progress="waits on Ada's install", **{field: "the install of the binary"})])
    assert _found(store) == {}


def test_a_pending_ddr_carries_the_wait(store):
    root = store.parents[1]
    _write(store, [_item("wi-d", progress="waits on Ada's choice of the provider")])
    assert list(_found(store, root)) == ["wi-d"]
    (root / "notes" / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    decisions.ask(root, title="Which provider", question="Which provider for wi-d?", options=["A: cheaper", "B: EU"],
                  why="cheaper", at="2030-01-06T09:00:00Z", items=["wi-d"], project="demo")
    assert _found(store, root) == {}


def test_the_owner_comes_from_config_and_the_owner_always_counts(store, tmp_path, monkeypatch):
    _write(store, [_item("wi-a", progress="waits on Ada's install"), _item("wi-o", progress="waits on the owner")])
    assert ownerwaits.names() == ["Ada"]
    assert set(_found(store, names=ownerwaits.names())) == {"wi-a", "wi-o"}
    cfg = tmp_path / "nobody" / "config.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    assert ownerwaits.names() == []
    assert set(_found(store, names=ownerwaits.names())) == {"wi-o"}   # no name in the engine: « the owner » only


def test_brain_check_warns_with_the_command_and_never_fails(store, monkeypatch, capsys):
    root = store.parents[1]
    monkeypatch.setattr(graph, "research_graph", lambda *a: 0)
    _write(store, [_item("wi-w", progress="waits on Ada's install of the binary"),
                   _item("wi-ok", progress="waits on Ada's install", external_blocker="Ada installs the binary")])
    lines = ownerwaits.check_lines(store, root)
    assert lines == [
        "warning: owner wait in prose only: wi-w: its props.progress says « waits on Ada's install of the binary », "
        "which brain next and brain queue do not read: brain item set wi-w external_blocker=\"...\" (a gesture of "
        "Ada's) or open=\"...\" (a question), or brain decision ask (a choice); history or a condition to come: "
        "brain item set wi-w owner_wait_checked=\"DATE: why\""]
    assert cli.main(["--root", str(root), "check"]) == 0   # a warning, never an error
    assert lines[0] in capsys.readouterr().out
