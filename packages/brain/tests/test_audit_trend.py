"""brain.audit_trend: the trend (the last completed ISO weeks re-measured at their end commit with today's rules) and
the milestone ms-brain-conformance. Moved from test_audit with the module (wi-brain-engine-debt, batch 2)."""

import dataclasses
from datetime import date

from brain import audit_checks, audit_measure, audit_trend, inventory, projects

from test_audit import _weekly


def test_trend_falling_flat_week_and_like_for_like_window(make_repo):
    weeks = ["2026-09-30T12:00:00Z", "2026-10-07T12:00:00Z", "2026-10-14T12:00:00Z", "2026-10-21T12:00:00Z",
             "2026-10-28T12:00:00Z"]
    a = _weekly(make_repo, "a", 5, weeks)
    late = _weekly(make_repo, "late", 2, weeks[2:])
    p = projects.Project("demo", a)
    cfgs = [projects.Repo("a", a), projects.Repo("late", late)]
    refs = {"a": "refs/heads/main", "late": "refs/heads/main"}
    t = audit_trend.trend(p, cfgs, refs, 5, date(2026, 11, 2))
    assert [w["week"] for w in t["weeks"]] == ["2026-W40", "2026-W41", "2026-W42", "2026-W43", "2026-W44"]
    assert [audit_trend._total(w) for w in t["weeks"]] == [5, 4, 3, 2, 1]
    assert t["left"] == ["late"] and t["repos"] == ["a"]               # no commit before W40's end: out
    assert audit_trend.falling([5, 4, 3, 2, 1]) == 4 and "falling 4 of 4" in audit_trend.trend_line(t)
    assert audit_trend.falling([5, 4, 4, 3, 2]) == 2 and audit_trend.falling([3, 2, 0, 0, 0]) == 4   # zero counts as falling
    assert audit_trend.week_ends(1, date(2026, 11, 8)) == [("2026-W44", "2026-11-02T00:00:00Z")]
    assert audit_trend.trend(p, cfgs[1:], refs, 5, date(2026, 11, 2))["weeks"] == []   # nothing over the window
    layer = {"notes/graph/schema.yaml": "node_types: [CodeRef, Repo]\n",
             "notes/graph/nodes/code.yaml": "- {id: repo-a, type: Repo, status: active, title: a}\n"}
    make_repo.commit(a, layer, date="2026-10-29T12:00:00Z")   # a code layer arrives in the last week
    p = projects.Project("demo", a, [a / "notes" / "graph"])
    now = audit_measure.measure(p, cfgs[:1], {"a": inventory.git_tree(a, "HEAD")})
    assert now["layered"] == {"a"}
    t = audit_trend.trend(p, cfgs[:1], refs, 5, date(2026, 11, 2), None, now["layered"])
    assert [audit_trend._total(w) for w in t["weeks"]] == [10, 9, 8, 7, 6]   # coderef.module counted in every week


def test_milestone_needs_every_repo_no_p0_p1_no_pending_and_four_falls(monkeypatch):
    ok = {"counts": {"P0": 0, "P1": 0, "P2": 3}, "repos": [{"name": "a"}]}
    tr = {"weeks": [{}], "falling": 4}
    assert not audit_trend.milestone([ok], tr)["met"]                         # generator checks still pending
    assert "1 P0/P1 checks not measured" in audit_trend.milestone([ok], tr)["reasons"]   # readme.generated: features.md,
    #                                    feature.links, readme.yaml and help.quoted run (wi-brain-readme-sync)
    unopted = {**ok, "repos": [{"name": "a", "not_measured": [{"check": "readme.yaml", "owner": audit_checks.NO_README}]}]}
    assert audit_trend.milestone([unopted], tr)["pending"] == ["readme.generated", "readme.yaml"]   # not opted in: pending
    monkeypatch.setattr(audit_checks, "PENDING", {k: dataclasses.replace(v, run=len) for k, v in audit_checks.PENDING.items()})
    assert audit_trend.milestone([ok], tr)["met"]
    unfeatured = {**ok, "repos": [{"name": "a", "not_measured": [{"check": "features.md", "owner": audit_checks.NO_FEATURES},
                                                                 {"check": "doc.links", "owner": "x"}]}]}
    m = audit_trend.milestone([unfeatured], tr)   # a generator's check that cannot run in that project still blocks
    assert not m["met"] and m["pending"] == ["features.md"]
    assert not audit_trend.milestone([ok], {"weeks": [{}], "falling": 3})["met"]
    assert not audit_trend.milestone([ok], None)["met"]
    assert not audit_trend.milestone([{**ok, "counts": {"P0": 0, "P1": 1, "P2": 0}}], tr)["met"]
    assert not audit_trend.milestone([{**ok, "repos": [{"name": "a", "error": "x not found"}]}], tr)["met"]
    blind = {**ok, "repos": [{"name": "a", "not_measured": [{"check": "test.module",
                                                             "owner": "pyproject.toml needs Python 3.11+ (tomllib)"}]}]}
    m = audit_trend.milestone([blind], tr)   # its modules could not be read: not audited
    assert not m["met"] and m["reasons"][0] == "not audited: a (pyproject.toml needs Python 3.11+ (tomllib))"
