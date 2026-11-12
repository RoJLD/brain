"""--scope REF on queue, tui, usage, cost, audit and permissions (wi-brain-scope-tree): each view gets the projects of
a node's subtree, as --all gets every one. Fictitious names only."""

import argparse
import json

import pytest

from brain import audit, cli, cockpit, cost, permissions, queue

from test_scopes import _tree, brain  # noqa: F401 - the fixture, shared


class Picked(Exception):
    """Raised by a stand-in once it has seen the projects a view was given."""


def _layout(brain):  # noqa: F811 - the fixture's name
    brain("alpha: {root: ., parent: pro}\nbeta: {root: ../beta, parent: acme}\ngamma: {root: ../gamma}\n")
    _tree(brain.root)
    return str(brain.root)


def test_queue_scope_shows_the_subtree_groups_and_their_totals(brain, monkeypatch, capsys):  # noqa: F811
    root = _layout(brain)
    seen = {}

    def collect(projs, only=None, **k):
        seen["only"] = only
        group = {"entries": [], "counts": {kind: 0 for kind in queue.KINDS}, "bands": {}}
        return [{"project": p.name, **group} for p in projs] + [{"project": queue.OUTSIDE, **group}]
    monkeypatch.setattr(queue, "collect", collect)
    assert cli.main(["--root", root, "queue", "--scope", "pro", "--json"]) == 0
    groups = [d["project"] for d in json.loads(capsys.readouterr().out)]
    assert groups == ["alpha", "beta"] and seen["only"] is None   # the registry's order, as --all; no outside group
    monkeypatch.setattr(queue, "render", lambda d, **k: [f"group {d['project']}"])
    assert cli.main(["--root", root, "queue", "--scope", "acme"]) == 0
    out = capsys.readouterr().out
    assert "group beta" in out and "group gamma" not in out and "scope acme: 0 waiting on" in out


def test_tui_scope_hands_the_cockpit_the_subtree(brain, monkeypatch):  # noqa: F811
    root = _layout(brain)

    def cockpit_(projs, every=False, **k):
        raise Picked([p.name for p in projs], every)
    monkeypatch.setattr(cockpit, "Cockpit", cockpit_)
    with pytest.raises(Picked) as got:
        cli.main(["--root", root, "tui", "--scope", "pro", "--once"])
    assert got.value.args == (["beta", "alpha"], True)   # several projects: the cockpit's every view


def test_usage_and_cost_scope_read_the_subtree_sessions(brain, monkeypatch):  # noqa: F811
    root = _layout(brain)

    def load(projs, root, **k):
        raise Picked([p.name for p in projs])
    monkeypatch.setattr(cost, "load", load)
    with pytest.raises(Picked) as got:
        cli.main(["--root", root, "usage", "--scope", "acme", "--no-scan"])
    assert got.value.args == (["beta"],)
    for sub in (["estimate", "x"], ["review"], ["audit"]):
        with pytest.raises(Picked) as got:
            cli.main(["--root", root, "cost", *sub, "--scope", "pro"])
        assert got.value.args == (["beta", "alpha"],)


def test_audit_scope_selects_the_subtree(brain):  # noqa: F811
    root = _layout(brain)
    args = argparse.Namespace(scope="pro", all=False, project=None)
    assert [p.name for p in audit.scope(args, brain.root)] == ["beta", "alpha"]
    with pytest.raises(audit.AuditError, match="one of them"):
        audit.scope(argparse.Namespace(scope="pro", all=True, project=None), brain.root)
    with pytest.raises(audit.AuditError, match="no node of that id"):
        audit.scope(argparse.Namespace(scope="nowhere", all=False, project=None), brain.root)
    assert root


def test_permissions_scope_lists_each_project_and_keeps_its_requests_meaning(brain, monkeypatch, capsys):  # noqa: F811
    root = _layout(brain)
    named = []
    monkeypatch.setattr(permissions, "show", lambda model, ctx: {"project": ctx.project, "files": []})
    real = permissions.context
    monkeypatch.setattr(permissions, "context", lambda model, name, *a: named.append(name) or real(model, name, *a))
    assert cli.main(["--root", root, "permissions", "--scope", "pro", "--json"]) in (0, 1)
    assert named == ["beta", "alpha"] and [d["project"] for d in json.loads(capsys.readouterr().out)] == ["beta",
                                                                                                         "alpha"]
    picked = {}
    monkeypatch.setattr(permissions, "requests", lambda model, only=None, days=7: [])
    monkeypatch.setattr(permissions, "select", lambda reqs, **k: picked.update(k) or [])
    cli.main(["--root", root, "permissions", "--requests", "--scope", "project", "--json"])
    assert picked["scope"] == "project"   # with --requests: a level's start, as before
