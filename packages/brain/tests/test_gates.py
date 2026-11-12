"""wi-brain-forecast-gates: gates as data (brain.gates, docs/gates.md): the format and its check, each kind as the
forecast draws it, a milestone's own gate, the owner's action DDRs as gates, the due alert, and what brain queue says
each gate holds. spec-brain-psychohistory §3.4, spec-brain-sizing-prioritization §5.4."""

import random
from datetime import date

import test_forecast
from brain import forecast, gates, queue
from test_forecast import NOW, ledger, model

project = test_forecast.project   # the forecast's store and ledger fixture

TODAY = NOW.date()


def prep(g, nodes=None, ddrs=(), work=(), flow=None, here=None):
    return gates.prepare(g, today=TODAY, resolver=gates.Resolver(None, here=here), nodes=nodes or {},
                         ddrs=list(ddrs), work=list(work), flow=flow or {})


# --- the format ---

def test_each_kind_is_checked_and_labelled():
    assert gates.problems({"kind": "calendar", "days": 28}) == []
    assert gates.problems({"kind": "calendar"}) == ["a calendar gate needs days: N (N > 0)"]
    assert gates.problems({"kind": "calendar", "days": 7, "reset_daily": 1.5})
    assert gates.problems({"kind": "count", "of": "ddr.answered", "at_least": 100}) == []
    assert "give current and per_day" in gates.problems({"kind": "count", "of": "passes", "at_least": 60})[0]
    assert gates.problems({"kind": "external", "ref": "quant wi-z"}) == ["an external gate needs ref: <project>:<id>"]
    assert gates.problems({"kind": "hardware", "machine": "gpu", "ready": "soon"})
    assert gates.problems({"kind": "eventually"})[0].startswith("kind 'eventually' is not one of")
    assert gates.of({"gate": {"kind": "go_nogo"}}) == [{"kind": "go_nogo"}]
    assert gates.of({"gate": [{"kind": "go_nogo"}, "prose"]}) == [{"kind": "go_nogo"}]
    assert gates.label({"kind": "hardware", "machine": "gpu"}) == "hardware gpu"
    assert gates.label({"kind": "count", "of": "ddr.answered", "at_least": 100}) == "count ddr.answered >= 100"
    assert gates.ready_range("2026-12..2027-01") == (date(2026, 12, 1), date(2027, 1, 31))
    assert gates.ready_range("2026-12-15") == (date(2026, 12, 15), date(2026, 12, 15))
    assert gates.ready_range("2027-01..2026-12") is None
    assert gates.parse_ref("quant:wi-z (the schema)") == ("quant", "wi-z")
    assert gates.parse_ref("Other-lab wi-z") is None


def test_each_kind_is_prepared_for_the_futures():
    # a calendar counted from a date: what is left of it; from an open item: a lag after it; elapsed: passed
    assert prep({"kind": "calendar", "days": 28, "from": "2026-10-26"})["days"] == 21
    assert prep({"kind": "calendar", "days": 7, "from": "2026-10-01"})["passed"]
    nodes = {"wi-cap": {"id": "wi-cap", "status": "todo"}}
    assert prep({"kind": "calendar", "days": 30, "from": "wi-cap"}, nodes)["after"] == "wi-cap"
    assert "unknown item" in prep({"kind": "calendar", "days": 30, "from": "wi-nope"})["undated"]
    # a measured count at its pace: 90 answered, 10 of them in the last 28 days: 10 more take 28 days
    ddrs = [{"answer": {"at": "2026-11-01T10:00:00Z" if k < 10 else "2026-01-01T10:00:00Z"}} for k in range(90)]
    c = prep({"kind": "count", "of": "ddr.answered", "at_least": 100}, ddrs=ddrs)
    assert round(c["lo"]) == 28 and c["lo"] == c["hi"]
    assert prep({"kind": "count", "of": "ddr.answered", "at_least": 50}, ddrs=ddrs)["passed"]
    assert prep({"kind": "count", "of": "passes", "at_least": 60, "current": 0, "per_day": 0})["undated"].startswith(
        "a count without a pace")
    # hardware: a range of days from now, or not dated without one
    h = prep({"kind": "hardware", "machine": "gpu", "ready": "2026-12..2027-01"})
    assert (h["lo"], h["hi"]) == ((date(2026, 12, 1) - TODAY).days, (date(2027, 1, 31) - TODAY).days + 1)
    assert prep({"kind": "hardware", "machine": "gpu"})["undated"] == "hardware not dated: gpu"
    # external: passed once the other project's item is done (here: this store), else not dated
    here = ("demo", {"wi-a": {"id": "wi-a", "status": "done"}, "wi-b": {"id": "wi-b", "status": "todo"}})
    assert prep({"kind": "external", "ref": "demo:wi-a"}, here=here)["passed"]
    assert prep({"kind": "external", "ref": "demo:wi-b"}, here=here)["undated"] == \
        "after another project: demo:wi-b (todo)"
    # go/no-go: a decision lag, passed once its DDR is answered
    assert prep({"kind": "go_nogo"})["decision"]
    answered = [{"id": "ddr-go", "status": "answered", "answer": {"at": "2026-11-01T10:00:00Z"}}]
    assert prep({"kind": "go_nogo", "ddr": "ddr-go"}, ddrs=answered)["passed"]
    # a malformed gate holds its node, never silently drawn as nothing
    assert prep({"kind": "hardware"})["undated"].startswith("a malformed gate")


def test_a_reset_rule_draws_longer_counts_than_its_days():
    p = {"days": 10.0, "reset": 0.05}
    draws = [gates.draw(p, random.Random(k), [])[0] for k in range(400)]
    assert min(draws) >= 10.0 and sum(draws) / len(draws) > 12.0
    assert gates.draw({"days": 10.0, "reset": 0.0}, random.Random(1), []) == (10.0, 0.0)
    assert gates.draw({"after": "wi-x", "days": 5.0, "reset": 0.0}, random.Random(1), []) == (0.0, 5.0)
    assert gates.draw({"decision": True}, random.Random(1), [48.0]) == (0.0, 2.0)


# --- the futures ---

def test_a_gated_item_waits_for_its_release_and_a_lag_follows_its_dependency():
    # one lane: an item released at 5 h starts then; one with a 1-day lag after item 0 starts 1 day (4 h) after it
    cal = forecast._Calendar(random.Random(1), [4.0], 1)
    done = forecast._schedule([2.0, 2.0], [True, True], [0.0, 0.0], [[], [0]], [[1], []], 1, [0.0, 1.0], cal)
    assert done == [2.0, 8.0]   # 2 h of work, then a lag of a day (4 h a day), then 2 h
    m = model(n=2)
    m["items"][1]["gates"] = [{"label": "hardware gpu", "kind": "hardware", "lo": 20, "hi": 30}]
    res = forecast.run(m, 200)
    days = {i["id"]: i["days"] for i in res["items"]}
    assert days["wi-1"]["p10"] >= 20 and days["wi-0"]["p90"] < 5
    item = next(i for i in res["items"] if i["id"] == "wi-1")
    assert item["gates"] == ["hardware gpu"]
    assert res["gates"]["declared"] == [{"gate": "hardware gpu", "kind": "hardware", "state": "drawn",
                                         "items": ["wi-1"], "milestones": []}]
    text = "\n".join(forecast.render(res, show_items=True))
    assert "gate           hardware gpu (drawn) holds 1 item(s)" in text and "after hardware gpu" in text


def test_a_milestone_waits_for_its_own_gate_and_an_undated_one_holds_it():
    m = model(n=2)
    m["milestones"][0]["gates"] = [{"label": "calendar 30 days", "kind": "calendar", "days": 30.0, "reset": 0.0}]
    res = forecast.run(m, 100)
    ms = res["milestones"][0]
    assert ms["days"]["p10"] >= 30 and ms["gates"] == ["calendar 30 days"]
    m["milestones"][0]["gates"] = [{"label": "hardware gpu", "kind": "hardware", "undated": "hardware not dated: gpu"}]
    res = forecast.run(m, 100)
    ms = res["milestones"][0]
    assert ms["shown"] == "undated" and ms["dates"] is None and ms["part"]["dates"]
    assert "not dated: hardware not dated" in "\n".join(forecast.render(res))
    m["items"][0]["gates"] = [{"label": "count passes >= 60", "kind": "count",
                               "undated": "a count without a pace: passes 0 of 60"}]
    m["items"][0]["why"] = "a count without a pace: passes 0 of 60"
    plan = forecast._plan(m)
    assert plan["undated"] == {"wi-0": "a count without a pace: passes 0 of 60"}


def test_an_action_only_the_owner_may_do_gates_its_item_and_a_due_date_alerts():
    m = model(n=2, delays_h=[1.0], action_delays_h=[240.0])
    m["items"][1]["action"] = ["ddr-arm"]
    m["items"][0]["due"] = "2026-11-01"   # yesterday: any p80 passes it
    res = forecast.run(m, 200)
    days = {i["id"]: i["days"] for i in res["items"]}
    assert days["wi-1"]["p10"] >= 9.0   # 240 h of the owner's action delay
    assert res["gates"]["action"] == ["ddr-arm"] and res["gates"]["action_items"] == ["wi-1"]
    assert res["gates"]["late"] == [{"id": "wi-0", "due": "2026-11-01",
                                     "p80": next(i["dates"]["p80"] for i in res["items"] if i["id"] == "wi-0")}]
    text = "\n".join(forecast.render(res))
    assert "ALERT          wi-0: its p80" in text and "1 pending action(s) only" in text


GATED = """
- {id: ms-g, type: Milestone, status: pending, title: "Gated", props: {trigger: "a month of capture",
   gate: {kind: hardware, machine: gpu, ready: "2026-12..2027-01"}}}
- {id: wi-g, type: WorkItem, status: todo, title: "Build gated", props: {priority: P1, theme: "3.9",
   gate: [{kind: calendar, days: 10, from: wi-p1}], due: "2027-01-15", due_source: "the pilot's start"}}
"""


def test_gather_reads_the_gates_of_the_store(project):
    with (project.stores[0] / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(GATED)
    m = forecast.gather(project, ledger(project), NOW)
    row = next(i for i in m["items"] if i["id"] == "wi-g")
    assert "wi-p1" in row["deps"] and row["gates"][0]["after"] == "wi-p1" and row["due"] == "2027-01-15"
    ms = next(x for x in m["milestones"] if x["id"] == "ms-g")
    assert ms["gates"][0]["label"] == "hardware gpu" and ms["durations"] == []
    res = forecast.run(m, 100)
    g = {i["id"]: i["days"] for i in res["items"]}
    assert g["wi-g"]["p10"] >= g["wi-p1"]["p10"] + 10
    ms = next(x for x in res["milestones"] if x["id"] == "ms-g")
    assert ms["days"]["p10"] >= (date(2026, 12, 1) - TODAY).days


# --- brain check and brain queue ---

CHECKED = """
- {id: ms-t, type: Milestone, status: pending, title: "Timed", props: {trigger: "y for 4 weeks in a row"}}
- {id: wi-ext, type: WorkItem, status: todo, title: "External", props: {after_external: "Other-lab wi-z (the schema)"}}
- {id: wi-ok, type: WorkItem, status: todo, title: "Resolved", props: {after_external: "demo:wi-one"}}
- {id: wi-bad, type: WorkItem, status: todo, title: "Bad gate", props: {gate: {kind: hardware}}}
- {id: wi-due, type: WorkItem, status: todo, title: "Due", props: {due: "2026-12-01"}}
- {id: wi-far, type: WorkItem, status: todo, title: "Far", props: {gate: {kind: external, ref: "demo:wi-nope"}}}
"""


def test_brain_check_warns_on_prose_gates_unresolved_refs_and_sourceless_dues(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(CHECKED)
    nodes = {"wi-one": {"id": "wi-one", "status": "todo"}}
    lines = gates.check_lines(store, resolver=gates.Resolver(None, here=("demo", nodes)))
    text = "\n".join(lines)
    assert len(lines) == 5 and all(x.startswith("warning: ") for x in lines)
    assert "1 malformed gate(s) (docs/gates.md): wi-bad (a hardware gate needs machine: <name>)" in text
    assert "1 trigger(s) name a duration with no gate" in text and "ms-t (4 weeks, in a row)" in text
    assert "wi-far (demo:wi-nope: no wi-nope in demo's store)" in text
    assert "1 after_external that do not resolve" in text and "wi-ext (not <project>:<id>)" in text
    assert "wi-ok" not in text
    assert "1 due date(s) without their source" in text and "wi-due" in text


def test_brain_queue_counts_what_each_gate_holds(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {id: wi-hw, type: WorkItem, status: todo, title: \"On the gpu\", props: {gate: {kind: hardware, "
                "machine: gpu}}}\n"
                "- {id: ms-hw, type: Milestone, status: pending, title: \"Gpu work\"}\n")
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {from: wi-hw, to: ms-hw, type: part_of}\n- {from: wi-one, to: wi-hw, type: depends_on}\n")
    rows = queue.held_by_gates(queue.load_graph(store))
    assert rows == [{"gate": "hardware gpu", "kind": "hardware", "on": ["wi-hw"], "items": ["wi-hw", "wi-one"],
                     "milestones": ["ms-hw"]}]
    assert queue.gates_line(rows) == "  gates: hardware gpu holds 1 milestone(s), 2 item(s)"
    data = {"project": "demo", "counts": {"decision": 0, "action": 0, "permission": 0}, "entries": [],
            "gates": rows, "days": 7}
    assert queue.gates_line(rows) in queue.render(data)
