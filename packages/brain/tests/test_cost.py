"""wi-brain-token-ledger and wi-brain-cost-estimation: the ledger joined to the backlog (brain.cost), brain usage,
brain cost estimate|review|audit, and the cost in brain status, brain digest and the cockpit."""

import json

import pytest

from brain import cli, cockpit, cost, digest, graph, projects, status, usage

ITEMS = """
- {id: wi-a, type: WorkItem, status: done, title: "Ledger A", props: {theme: "3.9", pr: "engine #7",
   done: "2026-11-01 ok"}}
- {id: wi-b, type: WorkItem, status: done, title: "Ledger B", props: {theme: "3.9", done: "2026-11-01 ok"}}
- {id: wi-c, type: WorkItem, status: done, title: "Ledger C", props: {theme: "3.9", done: "2026-11-01 ok"}}
- {id: wi-d, type: WorkItem, status: done, title: "Fix D", props: {theme: "3.9", done: "2026-11-02 ok"}}
- {id: wi-e, type: WorkItem, status: todo, title: "Ledger E", props: {theme: "3.9"}}
"""


@pytest.fixture
def project(store):
    with (store / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write(ITEMS)
    with (store / "edges" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("- {from: wi-a, to: ms-x, type: part_of}\n- {from: wi-e, to: ms-x, type: part_of}\n")
    root = store.parents[1]
    return projects.Project(name="demo", root=root, stores=[store])


def row(sid, day="2026-11-01", usd=10.0, cls="standard", folder=None, **kw):
    """A ledger row as brain.usage writes it, with what a test does not set at its default."""
    r = {"session_id": sid, "folder": folder or "", "start": f"{day}T10:00:00Z", "end": f"{day}T11:00:00Z",
         "title": "", "branch": "b", "kind": "build", "cost": usd, "active_s": 3600,
         "tokens": {"output": int(usd * 10_000)}, "sub_tokens": {}, "days": {day: {"cost": usd, "messages": 10,
                                                                                    "output": 1000}},
         "brief": {"side": True, "key": sid, "class": cls, "budget": 400_000, "items": [], "chars": 2000},
         "spawned": [], "closed": [], "title_items": [], "prs": [], "context": {"peak": 300_000},
         "phases": {"explore": {"cost": usd * 0.5}, "build": {"cost": usd * 0.5}},
         "signals": {"review_rounds": 1, "merges": 1, "conflicts": 0}, "ngrams": {}, "tools": {}, "commands": {},
         "skills": {}, "start_cost": {"cost": 1.0}}
    r.update(kw)
    return r


def ledger(project, rows):
    for r in rows:
        r["folder"] = r["folder"] or str(project.root)
    return cost.Ledger(rows, [project])


def test_sessions_serve_the_items_they_closed_merged_or_name(project):
    led = ledger(project, [
        row("s1", closed=["wi-b"]),
        row("s2", prs=["acme/engine#7"]),                       # wi-a's PR
        row("s3", title_items=["wi-c"], brief={"side": True, "items": ["wi-b"], "class": "standard"}),
        row("s4", brief={"side": True, "items": ["wi-zz", "wi-d", "wi-b"], "class": "standard"}),  # the first known
        row("s5", spawned=["k1", "k2"], closed=["wi-a"]),               # an orchestrator: coordination
        row("s6", closed=["wi-a", "wi-c"]),                             # shared equally
    ])
    served = {r["session_id"]: r["served"] for r in led.rows}
    assert served == {"s1": ["wi-b"], "s2": ["wi-a"], "s3": ["wi-c"], "s4": ["wi-d"], "s5": [], "s6": ["wi-a", "wi-c"]}
    a = cost.actual(led.items["wi-a"])
    assert a["cost"] == pytest.approx(15.0) and a["sessions"] == 2 and a["milestone"] == "ms-x"
    assert a["class"] == "standard" and a["budget"] == 400_000 and a["done_day"] == "2026-11-01"


def test_report_tables_and_distributions(project):
    seqs = {"git add > git commit > git push": [2, 0.5], "grep > head > sed": [9, 3.0]}
    rows = [row(f"s{i}", usd=float(i), closed=["wi-a"] if i % 2 else ["wi-b"], ngrams=seqs) for i in range(1, 5)]
    rows.append(row("p", spawned=["s1", "s2"], usd=20.0))
    for r in rows[:4]:
        r["brief"]["key"] = r["session_id"]
        r["brief"]["side"] = True
    led = ledger(project, rows)
    rep = cost.report(led, "2026-11-01", "2026-11-02", "summary")
    assert rep["sessions"] == 5 and rep["cost"] == pytest.approx(30.0) and rep["plans"] == ["Pro"]
    items = {r["key"]: r for r in rep["tables"]["item"]}
    assert items["wi-a"]["total"] == pytest.approx(4.0) and items["wi-b"]["total"] == pytest.approx(6.0)
    klass = {r["key"]: r for r in rep["tables"]["class"]}
    assert klass["standard"]["n"] == 5 and klass["standard"]["median"] == pytest.approx(3.0)
    phases = {r["key"]: r["total"] for r in rep["tables"]["phase"]}
    assert phases == {"explore": pytest.approx(15.0), "build": pytest.approx(15.0)}
    seq = rep["tables"]["sequences"]
    assert [s["key"] for s in seq] == ["git add > git commit > git push"]  # reading is not a script candidate
    fam = cost.report(led, "", "", "family")["tables"]["family"]
    assert fam[0]["key"] == "p" and fam[0]["total"] == pytest.approx(23.0)  # p with s1 and s2
    days = cost.report(led, "", "", "day")["tables"]["day"]
    assert days == [pytest.approx(days[0])] and days[0]["key"] == "2026-11-01" and days[0]["sessions"] == 5
    text = "\n".join(cost.render_report(rep))
    assert "By item" in text and "Script candidates" in text and "median" in text


def _run(usd, day, agents, labels, phases):
    return {"cost": usd, "agents": agents, "output": 1000, "tokens": 5000, "start": f"{day}T10:00:00Z",
            "end": f"{day}T11:00:00Z", "days": {day: usd}, "phases": phases, "labels": labels}


def _boss():
    return row("boss", usd=100.0, main_cost=20.0, title="Coordinator: wave", agents={
        "subagents": {"Review lens: tests": {"count": 2, "cost": 10.0}},
        "workflows": {"wf_a": _run(60.0, "2026-11-01", 3, {"impl:x": {"count": 1, "cost": 50.0},
                                                            "lens:x": {"count": 2, "cost": 10.0}},
                                   {"Implement": {"count": 1, "cost": 50.0}, "Review": {"count": 2, "cost": 10.0}}),
                      "wf_old": _run(10.0, "2026-10-20", 1, {"impl:x": {"count": 1, "cost": 10.0}},
                                     {"Implement": {"count": 1, "cost": 10.0}})}})


def test_usage_shows_the_workflow_runs_and_the_agents_apart(project):
    """wi-brain-usage-workflow-agents: whose the cost is, each workflow run, each agent's label."""
    old = row("old", usd=12.0, main_cost=7.0, subagents={"Explore": {"count": 1, "cost": 5.0}})  # scanned before agents
    led = ledger(project, [_boss(), old, row("plain", usd=8.0, main_cost=8.0)])
    rep = cost.report(led, "2026-11-01", "2026-11-02", "summary")
    a = rep["agents"]
    assert a["main"] == pytest.approx(35.0) and a["subagents"] == {"cost": pytest.approx(15.0), "count": 3}
    assert a["workflows"] == {"cost": pytest.approx(70.0), "runs": 1, "agents": 3}  # wf_old is not in the window
    assert [r["key"] for r in rep["tables"]["workflow"]] == ["wf_a"]
    wf = rep["tables"]["workflow"][0]
    assert wf["total"] == 60.0 and wf["agents"] == 3 and wf["session"] == "boss"
    assert wf["phases"] == [["Implement", 1, 50.0], ["Review", 2, 10.0]]
    agents = {r["key"]: r for r in cost.report(led, "2026-11-01", "2026-11-02", "agent")["tables"]["agent"]}
    assert agents["impl:x"]["total"] == pytest.approx(50.0) and agents["impl:x"]["runs"] == 1
    assert agents["Review lens: tests"]["kind"] == "subagent" and agents["lens:x"]["kind"] == "workflow"
    text = "\n".join(cost.render_report(rep))
    assert "whose: main threads $35.00 (29%), subagents $15.00 (12%, 3 agent(s)), workflows $70.00 (58%, 1 run(s), " \
           "3 agent(s))" in text
    assert "By workflow run" in text and "wf_a" in text and "Implement 1 $50.00" in text
    assert "By agent label" in "\n".join(cost.render_report(cost.report(led, "", "", "agent")))
    quiet = cost.report(ledger(project, [row("plain", usd=8.0, main_cost=8.0)]), "", "", "summary")
    assert "workflow" not in quiet["tables"] and "whose:" not in "\n".join(cost.render_report(quiet))


def test_cli_usage_by_workflow_and_agent(project, capsys):
    led = ledger(project, [_boss()])
    rows = {f"p/{r['session_id']}.jsonl": r for r in led.rows}
    for r in rows.values():
        r.pop("project"), r.pop("served")
    usage.save(rows)
    for by, want in (("workflow", "wf_a"), ("agent", "impl:x")):
        assert cli.main(["--root", str(project.root), "usage", "--since", "2026-10-01", "--by", by, "--no-scan"]) == 0
        assert want in capsys.readouterr().out


def _history(project):
    return ledger(project, [
        row("s1", "2026-10-30", usd=10.0, closed=["wi-a"]),
        row("s2", "2026-10-31", usd=20.0, closed=["wi-b"]),
        row("s3", "2026-11-01", usd=30.0, closed=["wi-c"]),
        row("s4", "2026-11-02", usd=90.0, closed=["wi-d"], signals={"review_rounds": 6, "merges": 1, "conflicts": 3},
            phases={"explore": {"cost": 20.0}, "merge": {"cost": 70.0}}),
        row("s5", "2026-11-02", usd=5.0, title_items=["wi-e"], start="2026-11-02T12:00:00Z"),
    ])


def test_estimate_from_the_most_alike_items_and_its_record(project):
    led = _history(project)
    target = cost.target_of(led, "wi-e")
    assert target["class"] == "standard" and target["theme"] == "3.9" and target["milestone"] == "ms-x"
    est = cost.estimate(led, target, "2026-11-02")
    assert est["basis"] == "class+theme" and est["n"] == 4
    assert est["calibration"]["n"] == 3  # wi-b, wi-c, wi-d have items before them
    raw = cost.raw_estimate(cost.history(led), target)
    assert est["cost"]["median"] == pytest.approx(raw["cost"]["median"] * est["calibration"]["factor"])
    text = cost.estimate_text(est)
    back = cost.parse_estimate(text)
    assert back["day"] == "2026-11-02" and back["class"] == "standard" and back["usd"] == pytest.approx(
        round(est["cost"]["median"], 2))
    cost.record(target["store"], "wi-e", "cost_estimate", text)
    node = next(n for n in graph._yaml().safe_load((project.stores[0] / "nodes" / "work.yaml").read_text(
        encoding="utf-8")) if n["id"] == "wi-e")
    assert node["props"]["cost_estimate"] == text
    brief = cost.target_of(led, "Fix the wi-a ledger. **Task class:** strategic. Context budget: 800k")
    assert brief["class"] == "strategic" and brief["budget"] == 800_000 and brief["kind"] == "fix"
    assert brief["theme"] == "3.9"  # from the first item it names
    assert "basis" in "\n".join(cost.render_estimate(cost.estimate(led, brief, "2026-11-02")))


def test_review_explains_the_gap(project):
    led = _history(project)
    rv = cost.review(led, "wi-d")
    assert rv["source"] == "backtest" and rv["estimate"] == pytest.approx(20.0)  # wi-a, wi-b, wi-c: median 20
    assert rv["ratio"] == pytest.approx(4.5) and cost.verdict(rv["ratio"]) == "over"
    assert rv["budget_use"] == pytest.approx(0.75)
    why = "\n".join(rv["why"])
    assert "+ merge" in why and "3 merge conflicts" in why and "6 review rounds" in why
    assert "- explore" in why
    cost.record(led.items["wi-d"].store, "wi-d", "cost_estimate", "2026-11-02 class=standard usd=60.00")
    led = _history(project)
    rv = cost.review(led, "wi-d")
    assert rv["source"] == "recorded" and rv["ratio"] == pytest.approx(1.5)
    assert cost.review_text(rv, "2026-11-02").startswith("2026-11-02 usd=90.00 est=60.00 x1.50 (recorded)")
    assert "against the recorded estimate" in "\n".join(cost.render_review(rv))


def test_audit_lists_the_estimates_off_and_the_calibration(project):
    led = _history(project)
    au = cost.audit(led, "2026-11-01", "2026-11-03")
    assert {rv["item"]["id"] for rv in au["reviews"]} == {"wi-a", "wi-b", "wi-c", "wi-d"}
    # each backtest only knows the items finished before it: wi-b (x2), wi-c (x2) and wi-d (x4.5) are off
    assert [rv["item"]["id"] for rv in au["off"]] == ["wi-b", "wi-c", "wi-d"]
    assert au["calibration"]["standard"]["n"] == 3
    text = cost.render_audit(au, "demo", "2026-11-02 12:00 UTC")
    assert "# Cost audit, demo" in text and "**wi-d** (over)" in text and "## Calibration" in text
    assert cost.audit_path("demo", "2026-11-01", "").name == "audit-2026-11-01_now.md"


def test_cli_usage_and_cost(project, capsys):
    rows = {f"p/{r['session_id']}.jsonl": r for r in _history(project).rows}
    for r in rows.values():
        r.pop("project"), r.pop("served")
    usage.save(rows)
    root = str(project.root)
    assert cli.main(["--root", root, "usage", "--since", "2026-10-01", "--json", "--by", "item", "--no-scan"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert {r["key"] for r in rep["tables"]["item"]} == {"wi-a", "wi-b", "wi-c", "wi-d", "wi-e"}
    assert cli.main(["--root", root, "usage", "--since", "2026-10-01", "--report", "daily"]) == 0
    assert "By day" in capsys.readouterr().out
    assert cli.main(["--root", root, "cost", "estimate", "wi-e", "--record"]) == 0
    out = capsys.readouterr().out
    assert "basis class+theme" in out and "recorded on wi-e" in out
    assert cli.main(["--root", root, "cost", "review", "wi-d", "--record"]) == 0
    assert "x4.50, over" in capsys.readouterr().out
    text = (project.stores[0] / "nodes" / "work.yaml").read_text(encoding="utf-8")
    assert "cost_estimate:" in text and "cost_review:" in text
    assert cli.main(["--root", root, "cost", "audit", "--since", "2026-10-01", "--write"]) == 0
    assert "written to" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["--root", root, "cost", "estimate", "a brief", "--record"])


def test_cockpit_prices_a_session_and_sorts_by_cost():
    sr = {"model": "claude-opus-5-5", "tokens_by_model": {"claude-opus-5-5": {"output": 1_000_000}},
          "subagents": {"count": 1, "tokens": {"output": 500_000}}}
    assert cockpit.cost_of(sr) == pytest.approx(30.0) and cockpit.cost_of({}) is None
    rows = [{"state": "idle", "age_s": 5, "cost_usd": 1.0}, {"state": "running", "age_s": 9, "cost_usd": None},
            {"state": "asking", "age_s": 7, "cost_usd": 3.0}]
    panel = {"rows": rows}
    assert [r["age_s"] for r in cockpit.shown("sessions", panel, {"sort": "cost"})] == [7, 5, 9]
    assert cockpit.parse_view(["sessions:cost"])["sessions"]["sort"] == "cost"


def test_status_and_digest_show_the_cost(project):
    rows = {f"p/{r['session_id']}.jsonl": r for r in _history(project).rows}
    for r in rows.values():
        r.pop("project"), r.pop("served")
    usage.save(rows)
    s = cost.summary_of(cost.load([project]), "demo", "2026-11-02", "2026-11-03")
    assert s["sessions"] == 2 and s["cost"] == pytest.approx(95.0) and s["items"][0][0] == "wi-d"
    assert "costliest items wi-d" in cost.summary_line(s)
    data = status.collect(project, quick=True)
    assert "tokens" in data and data["tokens"]["days"] == cost.STATUS_DAYS
    part = digest._cost(s)
    assert part.key == "cost" and "costliest items" in part.levels[0][0]
    assert digest._cost({"sessions": 0}) is None
