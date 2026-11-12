"""wi-brain-token-ledger and wi-brain-cost-estimation: the ledger joined to the backlog (brain.cost), brain usage,
brain cost estimate|review|audit, and the cost in brain status, brain digest and the cockpit."""

import json

import pytest

from brain import cli, cockpit, cost, digest, graph, projects, sizing, status, usage

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
    assert cli.main(["--root", root, "cost", "review", "wi-one", "--record"]) == 0   # in the backlog, no session
    assert "0 review(s) recorded" in (out := capsys.readouterr().out) and "not recorded: wi-one (no session" in out
    assert text == (project.stores[0] / "nodes" / "work.yaml").read_text(encoding="utf-8")   # nothing written
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


# --- wi-brain-size-calibration: sizes checked against actuals ---

def test_the_scale_and_a_judged_size_against_the_active_time():
    assert [sizing.size_of(h) for h in (0.1, 0.3, 0.31, 0.8, 2.0, 2.01)] == ["S", "S", "M", "M", "L", "XL"]
    one_hour = {"size": "M", "active_s": 3600}
    assert sizing.size_check(one_hour) == {"judged": "M", "actual": "L", "hours": 1.0, "verdict": "under"}
    assert sizing.size_check(dict(one_hour, size="L"))["verdict"] == "hit"
    assert sizing.size_check(dict(one_hour, size="XL"))["verdict"] == "over"
    assert sizing.size_check({"active_s": 3600}) is None and sizing.size_check(dict(one_hour, size="")) is None


def test_review_and_audit_say_the_size_against_the_actual(project):
    led = _history(project)   # every session is 1 h active: L on the scale
    for i, s in (("wi-a", "S"), ("wi-b", "L"), ("wi-c", "M"), ("wi-d", "big")):   # "big": off the scale, no size
        led.items[i].props["size"] = s
    rv = cost.review(led, "wi-a")
    assert rv["size"] == {"judged": "S", "actual": "L", "hours": 1.0, "verdict": "under"}
    assert "  size S judged; 1.00 h active is L: under-sized" in cost.render_review(rv)
    assert " sessions=1 size=S/L" in cost.review_text(rv, "2026-11-02")
    assert cost.review(led, "wi-d")["size"] is None
    au = cost.audit(led, "2026-10-01", "2026-11-03")
    sz = au["sizes"]
    assert sz["misses"] == 2 and [r["id"] for r in sz["items"]] == ["wi-a", "wi-b", "wi-c"]
    assert [(r["size"], r["n"], r["hit"], r["under"]) for r in sz["table"]] == [("S", 1, 0, 1), ("M", 1, 0, 1),
                                                                                ("L", 1, 1, 0)]
    assert [t["proposed"] for t in sz["thresholds"]] == [None, None, None]   # one item per size: none proposed
    # three sized items: the key is measured; no size tier reaches three items before an item, so it changes nothing
    assert au["size_key"]["n"] == 3 and not au["size_key"]["kept"]
    assert au["size_key"]["with"] == au["size_key"]["without"] == au["backtests"]["median_factor"]
    text = cost.render_audit(au, "demo", "2026-11-02 12:00 UTC")
    assert "## Sizes against actuals" in text and "3 sized item(s), 2 miss(es)" in text
    assert "  - wi-a: S judged, 1.0 h is L" in text and "- S: now 0.3 h, proposed - (1 item(s), 3 needed)" in text


def _sized(project, n=8):
    """n finished items in turn S (10 dollars, 0.2 h) and L (100 dollars, 1.5 h), one a day: the size tells the
    cost apart, the class and theme do not."""
    nodes, rows = [], []
    for k in range(n):
        size, usd, active = ("S", 10.0, 720) if k % 2 == 0 else ("L", 100.0, 5400)
        nodes.append(f'- {{id: wi-s{k}, type: WorkItem, status: done, title: "Sized {k}", props: {{theme: "4.1", '
                     f'size: {size}, done: "2026-10-{10 + k} ok"}}}}\n')
        rows.append(row(f"z{k}", f"2026-10-{10 + k}", usd=usd, active_s=active, closed=[f"wi-s{k}"]))
    nodes.append('- {id: wi-new, type: WorkItem, status: todo, title: "New", props: {theme: "4.1", size: S}}\n')
    with (project.stores[0] / "nodes" / "work.yaml").open("a", encoding="utf-8") as f:
        f.write("".join(nodes))
    return ledger(project, rows)


def test_the_size_is_the_first_key_only_while_it_lowers_the_backtests_error(project, monkeypatch):
    led = _sized(project)
    key = cost.size_key(led)
    assert key["kept"] and key["with"] < key["without"] and key["n"] == 8
    est = cost.estimate(led, cost.target_of(led, "wi-new"), "2026-10-30")
    assert est["basis"] == "size+class" and {i for i, _ in est["similar"]} == {"wi-s0", "wi-s2", "wi-s4", "wi-s6"}
    assert est["size_key"]["kept"] and "size key kept: backtests' error x" in "\n".join(cost.render_estimate(est))
    # a brief's text carries its size as « - size: L »
    assert cost.target_of(led, "Brief.\n- size: L\n**Task class:** standard")["size"] == "L"
    for text in ("a font-size: m rule", "Batch size: S.", "- size: Large", "- size: m"):   # not a size line
        assert cost.target_of(led, text)["size"] == ""
    # the two backtests cover the same items; the errors compared are the sized items'
    assert {t["id"] for t in cost.backtests(led)} == {t["id"] for t in cost.backtests(led, size_key=True)}
    # the estimate records the size judged at the start, and the backtests read it, not a size judged again later
    assert " size=S usd=" in cost.estimate_text(est)
    led.items["wi-s0"].props.update(size="L", cost_estimate="2026-10-09 class=standard size=S usd=10.00")
    assert cost.actual(led.items["wi-s0"])["size"] == "S"
    au = cost.audit(led, "2026-10-01", "2026-11-01")
    assert [(t["size"], t["proposed"]) for t in au["sizes"]["thresholds"]] == [("S", 0.2), ("M", None), ("L", 1.5)]
    # the key that does not lower the error is left out: the estimator falls back to class and theme
    monkeypatch.setattr(cost, "backtest_error", lambda tests: 2.0)
    key = cost.size_key(led)
    assert not key["kept"] and key["with"] == key["without"] == 2.0
    assert cost.estimate(led, cost.target_of(led, "wi-new"), "2026-10-30")["basis"] == "class+theme"
