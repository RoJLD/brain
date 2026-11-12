"""wi-brain-lessons-registry and wi-brain-lessons-loop: Lesson nodes (brain lesson add|seen|list|--follow), the
dedup, the item proposal of a recurring lesson, the iron-rules index, the linter (brain lint lessons) and the retro
(brain retro ITEM | --wave)."""

import json

import pytest

from brain import cli, cost, graph, lessons, projects

LESSON_SCHEMA = (
    "node_types: [ADR, WorkItem, Milestone, Spec, DDR, Session, Action, Lesson, Hook]\n"
    "edge_types: [decided_by, supersedes, part_of, depends_on, specified_by, raised_by, answered_in, about, "
    "produced_by, touches, learned_from, enforced_by, led_to]\n"
    "statuses: [active, todo, doing, done, dropped, pending, reached, proposed, answered, integrated, archived, "
    "open, closed, recorded, enforced, resolved, regressed]\n"
    "status_by_type:\n  WorkItem: [todo, doing, done, dropped]\n  Milestone: [pending, reached]\n"
    "  Lesson: [open, enforced, resolved, regressed, archived]\n"
    "required_props:\n  Lesson: [trigger, anti_pattern, check]\n")

MERGE = dict(trigger="merging main into a branch while other PRs land",
             anti_pattern="the resolution was made against a stale local main and dropped a merged item",
             check="`git diff origin/main -- notes/journal.md` shows no removed line of another PR")


@pytest.fixture
def lstore(store):
    (store / "schema.yaml").write_text(LESSON_SCHEMA, encoding="utf-8")
    (store / "nodes" / "delivery.yaml").write_text(
        "- {id: hook-guards, type: Hook, status: active, title: \"The guards\"}\n", encoding="utf-8")
    return store


def _lesson(store, lid="les-demo-merge-stale-main", **kw):
    args = dict(MERGE, severity="medium", signal="merges", frm=["wi-one"], prs="acme #185", today="2026-11-03")
    args.update(kw)
    return lessons.add(store, lid, "Merge resolution against a stale main", **args)


def test_add_writes_the_node_and_its_edges(lstore):
    out = _lesson(lstore, led_to="wi-two", rule="Sigma-READ-THE-DIFF")
    assert out["filed"] is None
    nodes = graph.load_yaml_list(lstore / lessons.FILE)
    assert nodes[0]["id"] == "les-demo-merge-stale-main" and nodes[0]["status"] == "open"
    p = nodes[0]["props"]
    assert p["trigger"] == MERGE["trigger"] and p["signal"] == "merges" and p["prs"] == "acme #185"
    assert p["rule"] == "Sigma-READ-THE-DIFF" and p["learned"] == "2026-11-03"
    edges = graph.load_yaml_list(lstore / lessons.EDGES)
    assert {(e["to"], e["type"]) for e in edges} == {("wi-one", "learned_from"), ("wi-two", "led_to")}


def test_add_needs_the_lesson_type_its_props_and_known_nodes(store, lstore):
    with pytest.raises(lessons.LessonError, match="needs its check"):
        _lesson(lstore, check=" ")
    with pytest.raises(lessons.LessonError, match="unknown node"):
        _lesson(lstore, frm=["wi-nope"])
    with pytest.raises(lessons.LessonError, match="severity"):
        _lesson(lstore, severity="huge")


def test_add_refuses_a_lesson_without_the_type_in_the_schema(store):
    with pytest.raises(lessons.LessonError, match="no Lesson node type"):
        _lesson(store)


def test_a_near_duplicate_is_refused_unless_new(lstore):
    _lesson(lstore)
    again = dict(MERGE, trigger="merging main into the branch while other PRs land")
    with pytest.raises(lessons.LessonError, match="close to les-demo-merge-stale-main"):
        lessons.add(lstore, "les-demo-merge-stale-main-2", "Merge resolution against a stale main", **again)
    out = lessons.add(lstore, "les-demo-merge-stale-main-2", "Merge resolution against a stale main", new=True,
                      **again)
    assert out["node"]["id"] == "les-demo-merge-stale-main-2"
    other = lessons.add(lstore, "les-demo-bom", "A BOM in an answers file", trigger="writing a JSON from PS 5.1",
                        anti_pattern="Set-Content adds a byte order mark the reader skipped", check="`brain check`")
    assert other["node"]["status"] == "open"


def test_a_severe_lesson_with_no_fix_files_its_proposal(lstore):
    out = _lesson(lstore, severity="high")
    assert out["filed"] == "wi-demo-merge-stale-main"
    item = graph.node_index(lstore)["wi-demo-merge-stale-main"][1]
    assert item["type"] == "WorkItem" and item["status"] == "todo"
    assert item["props"]["priority_proposed"] == "P1" and item["props"]["lesson"] == "les-demo-merge-stale-main"
    assert "script first" in item["props"]["fix_ladder"]
    led = [e for e in graph.load_yaml_list(lstore / lessons.EDGES) if e["type"] == "led_to"]
    assert led == [{"from": "les-demo-merge-stale-main", "to": "wi-demo-merge-stale-main", "type": "led_to"}]


def test_seen_twice_files_the_proposal_once(lstore):
    _lesson(lstore)
    out = lessons.seen(lstore, "les-demo-merge-stale-main", frm=["wi-two"], pr="acme #194", today="2026-11-04")
    assert out["filed"] == "wi-demo-merge-stale-main" and not out["regressed"]
    node = out["node"]
    assert lessons.seen_of(node) == 2 and node["props"]["prs"] == "acme #185, acme #194"
    assert node["props"]["last_seen"] == "2026-11-04"
    again = lessons.seen(lstore, "les-demo-merge-stale-main", pr="acme #200", today="2026-11-05")
    assert again["filed"] is None and lessons.seen_of(again["node"]) == 3  # its proposal is open: not twice
    learned = [e["to"] for e in graph.load_yaml_list(lstore / lessons.EDGES) if e["type"] == "learned_from"]
    assert learned == ["wi-one", "wi-two"]
    with pytest.raises(lessons.LessonError, match="say where"):
        lessons.seen(lstore, "les-demo-merge-stale-main")
    with pytest.raises(lessons.LessonError, match="no such lesson"):
        lessons.seen(lstore, "wi-one", pr="x #1")


def test_an_enforced_lesson_that_recurs_regresses_and_files_a_proposal(lstore):
    out = _lesson(lstore, enforced_by=["hook-guards"])
    assert out["node"]["status"] == "enforced" and out["filed"] is None
    back = lessons.seen(lstore, "les-demo-merge-stale-main", pr="acme #210", today="2026-11-06")
    assert back["regressed"] and back["node"]["status"] == "regressed"
    assert back["node"]["props"]["regressed"] == "2026-11-06" and back["filed"] == "wi-demo-merge-stale-main"


def test_rows_follow_and_the_friction_kpi(lstore):
    _lesson(lstore, led_to="wi-two")
    graph.close_item(lstore, "wi-two", "acme #186", today="2026-11-03")
    graph.set_item(lstore, "wi-one", ["retro=2026-11-03 friction=6 merges=4 conflicts=2"])
    graph.set_item(lstore, "wi-two", ["retro=2026-11-04 friction=2 merges=1"])
    back = lessons.seen(lstore, "les-demo-merge-stale-main", pr="acme #199", today="2026-11-05")
    assert back["regressed"] and back["filed"] == "wi-demo-merge-stale-main"  # its fix is done, yet it recurred
    rs = lessons.rows(lstore)
    assert rs[0]["led_to"] == [{"id": "wi-two", "status": "done", "pr": "acme #186", "done": "2026-11-03"},
                               {"id": "wi-demo-merge-stale-main", "status": "todo", "pr": "", "done": ""}]
    assert rs[0]["recurred_since_fix"] and rs[0]["seen"] == 2 and rs[0]["status"] == "regressed"
    kpi = lessons.friction(lstore)
    assert kpi == [{"week": "2026-W45", "items": 2, "points": 8, "mean": 4.0}]
    text = "\n".join(lessons.render_follow(rs, kpi))
    assert "led to wi-two [done] acme #186, done 2026-11-03" in text and "recurred since its fix: yes" in text
    assert "2026-W45 4.0 (2 item(s))" in text
    assert lessons.select(rs, status="enforced") == []
    assert "1 lesson(s): 1 regressed" in lessons.render_list(rs)[0]


def test_lint_proposes_a_guard_for_a_command_check_and_flags_prose(lstore):
    _lesson(lstore)
    lessons.add(lstore, "les-demo-prose", "Ask before a costly brainstorm", trigger="a wide brainstorm",
                anti_pattern="started without the owner's go", check="the owner says so", signal="owner")
    lessons.add(lstore, "les-demo-judged", "Keep briefs short", trigger="writing a brief",
                anti_pattern="a brief of four pages", check="a reader finds it long", why_not_script="judgement")
    found = {f["lesson"]: f for f in lessons.lint_lessons(lstore)}
    assert set(found) == {"les-demo-merge-stale-main", "les-demo-prose"}
    assert found["les-demo-merge-stale-main"]["kind"] == "guard"
    assert found["les-demo-merge-stale-main"]["command"].startswith("git diff origin/main")
    assert found["les-demo-prose"]["kind"] == "prose"
    assert lessons.propose_guards(lstore, list(found.values()), today="2026-11-03") == {
        "filed": ["wi-demo-merge-stale-main"], "linked": []}
    assert lessons.lint_lessons(lstore)[0]["fix"] == ["wi-demo-merge-stale-main"]
    props = graph.node_index(lstore)["wi-demo-merge-stale-main"][1]["props"]
    assert "is a guard candidate of brain lint lessons" in props["priority_reason"]
    assert "regressed" not in props["idea"] and props["priority_proposed"] == "P2"   # a medium lesson


def test_a_low_lesson_proposes_p3(lstore):
    _lesson(lstore, severity="low")
    assert lessons.seen(lstore, "les-demo-merge-stale-main", pr="acme #2")["filed"] == "wi-demo-merge-stale-main"
    assert graph.node_index(lstore)["wi-demo-merge-stale-main"][1]["props"]["priority_proposed"] == "P3"
    assert "guard candidate" in lessons.render_lint(lessons.lint_lessons(lstore))[0]


def test_iron_rules_index_reads_tracked_markdown_only(make_repo, lstore, tmp_path):
    repo = make_repo("fork", {"ROADMAP.md": "Iron **Σ-THE-STACK-CAN-LAG** : check the live stack.\n"
                                            "See Sigma-TAG-DRIVEN-CI and Σ-THE-STACK-CAN-LAG again.\n",
                              "docs/spec.md": "# Spec\nΣ-TAG-DRIVEN-CI.\n", "code.py": "# Σ-NOT-IN-MARKDOWN\n"})
    (repo / "untracked.md").write_text("Σ-UNTRACKED\n", encoding="utf-8")
    _lesson(lstore, rule="Σ-THE-STACK-CAN-LAG")
    index = lessons.iron_rules([projects.Repo("fork", repo), projects.Repo("gone", tmp_path / "nowhere")],
                               lessons.rule_links(lstore))
    fork, gone = index
    assert gone["missing"] == "no checkout"
    ids = {r["id"]: r for r in fork["rules"]}
    assert set(ids) == {"Σ-THE-STACK-CAN-LAG", "Σ-TAG-DRIVEN-CI"}
    assert ids["Σ-THE-STACK-CAN-LAG"]["mentions"] == 2 and ids["Σ-THE-STACK-CAN-LAG"]["cited"] == ["ROADMAP.md:1",
                                                                                                   "ROADMAP.md:2"]
    assert ids["Σ-THE-STACK-CAN-LAG"]["lessons"] == ["les-demo-merge-stale-main"]
    assert ids["Σ-THE-STACK-CAN-LAG"]["text"].startswith("Iron Σ-THE-STACK-CAN-LAG")
    assert ids["Σ-TAG-DRIVEN-CI"]["cited"] == ["ROADMAP.md:2", "docs/spec.md:2"]
    text = "\n".join(lessons.render_rules(index))
    assert "fork: 2 iron rule(s), 4 mention(s)" in text and "gone: missing" in text
    assert "[lesson les-demo-merge-stale-main]" in text


# --- the retro ---

def _row(sid, item, **kw):
    r = {"session_id": sid, "folder": "", "start": "2026-11-03T10:00:00Z", "end": "2026-11-03T11:00:00Z",
         "title": "", "branch": "b", "kind": "build", "cost": 12.0, "active_s": 3600, "tokens": {"output": 1000},
         "sub_tokens": {}, "days": {}, "brief": {"side": True, "key": sid, "class": "standard", "budget": 600_000,
                                                 "items": [item], "chars": 2000},
         "spawned": [], "closed": [item], "title_items": [], "prs": [], "context": {"peak": 300_000},
         "phases": {}, "ngrams": {}, "tools": {}, "skills": {}, "start_cost": {},
         "signals": {"merges": 3, "conflicts": 2, "thrash": 1, "asks": 2, "ask_wait_s": 600, "wait_s": 900,
                     "compactions": 0, "review_rounds": 1},
         "commands": {"python -m pytest": {"calls": 5, "fails": 2}, "git merge": {"calls": 3, "fails": 1}}}
    r.update(kw)
    return r


def _ledgers(home):
    d = home / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    guards = [{"at": "2026-11-03T10:10:00Z", "event": "guard", "guard": "public", "check": "public",
               "decision": "denied", "session_id": "s1"},
              {"at": "2026-11-03T10:11:00Z", "event": "guard", "guard": "owner", "check": "installer",
               "decision": "override", "session_id": "s1"},
              {"at": "2026-11-03T10:12:00Z", "event": "guard", "guard": "public", "check": "public",
               "decision": "denied", "session_id": "elsewhere"}]
    sess = {"id": "s1"}
    ars = [{"kind": "push", "at": "2026-11-03T10:20:00Z", "repo": "acme/engine", "branch": "f", "session": sess},
           {"kind": "pr", "at": "2026-11-03T10:21:00Z", "repo": "acme/engine",
            "pr": {"number": 7, "action": "created"}, "session": sess},
           {"kind": "push", "at": "2026-11-03T10:40:00Z", "repo": "acme/engine", "branch": "f", "session": sess},
           {"kind": "push", "at": "2026-11-03T10:50:00Z", "repo": "acme/engine", "branch": "f", "session": sess},
           {"kind": "push", "at": "2026-11-03T10:55:00Z", "repo": "acme/engine", "branch": "other", "session": sess},
           {"kind": "pr", "at": "2026-11-03T11:00:00Z", "repo": "acme/engine",
            "pr": {"number": 7, "action": "merged"}, "session": sess},
           {"kind": "push", "at": "2026-11-03T11:30:00Z", "repo": "acme/engine", "branch": "f", "session": sess}]
    (d / "guards-2026-11.jsonl").write_text("".join(json.dumps(g) + "\n" for g in guards), encoding="utf-8")
    (d / "ar-2026-11.jsonl").write_text("".join(json.dumps(a) + "\n" for a in ars), encoding="utf-8")


@pytest.fixture
def demo(lstore, brain_home):
    graph.set_item(lstore, "wi-one", ["pr=engine #7", "wave=F (Ada, 2026-11-03)", "status=done"])
    graph.set_item(lstore, "wi-two", ["wave=F"])
    _ledgers(brain_home)
    p = projects.Project(name="demo", root=lstore.parents[1], stores=[lstore])
    return p, lstore


def test_retro_gathers_the_friction_signals(demo):
    p, store = demo
    _lesson(store)
    led = cost.Ledger([_row("s1", "wi-one", folder=str(p.root))], [p])
    r = lessons.retro(led, "wi-one", store)
    s = r["signals"]
    assert s["guards"] == 1 and s["guard_checks"] == {"public:public": 1}
    assert s["tests"] == 2 and s["conflicts"] == 2 and s["owner_s"] == 600 and s["asks"] == 2
    assert s["rework"] == {"engine#7": 2}
    assert r["friction"] == 2 + 1 + 2 + 1 + 2  # conflicts, guards, tests, thrash, rework
    assert r["fired"] == ["guards", "merges", "owner", "rework", "tests", "waits"]
    assert [k["id"] for k in r["known"]] == ["les-demo-merge-stale-main"]
    text = "\n".join(lessons.render_retro(r, owner="Ada"))
    assert "1 refusal(s) (public:public x1)" in text and "engine#7 2 push(es) after opening" in text
    assert "Ada       2 question(s), 10 min until the answers" in text
    assert "5. what to change in the next brief" in text
    line = lessons.retro_text(r, "2026-11-03")
    assert line.startswith("2026-11-03 friction=8 merges=3 conflicts=2 guards=1 tests=2")


def test_cli_retro_records_and_the_wave_retro(demo, capsys, monkeypatch):
    p, store = demo
    rows = [_row("s1", "wi-one", folder=str(p.root))]
    monkeypatch.setattr(cost, "load", lambda projs, root=None, refresh=True: cost.Ledger(list(rows), [p]))
    root = str(p.root)
    assert cli.main(["--root", root, "retro", "wi-one", "--record", "--note", "the merges cost the most",
                     "--note", "a  merge driver"]) == 0
    out = capsys.readouterr().out
    assert "retro wi-one" in out and "recorded on wi-one" in out
    node = graph.node_index(store)["wi-one"][1]
    assert node["props"]["retro"].startswith(f"{node['props']['retro'][:10]} friction=8")
    assert node["props"]["retro_notes"] == "the merges cost the most | a merge driver"
    assert cli.main(["--root", root, "retro", "--wave", "F", "--json"]) == 0
    w = json.loads(capsys.readouterr().out)
    assert [r["item"] for r in w["items"]] == ["wi-one"] and w["open"] == ["wi-two"]
    assert w["totals"]["guards"] == 1 and w["totals"]["rework"] == 2
    with pytest.raises(SystemExit):
        cli.main(["--root", root, "retro"])
    with pytest.raises(SystemExit):
        cli.main(["--root", root, "retro", "wi-nope"])


def test_the_wave_retro_reads_the_numbered_waves(demo, brain_home):
    """wi-brain-retro-numbered-waves: the 0.3.1 deep retro found 0 items, its items being part_of wave-0.3.1 with no
    props.wave. A numbered wave's items are its part_of and carried_to ones, those carried out of it left out."""
    p, store = demo
    for rel in ("0.3.1", "0.3.2", "0.3.3"):
        graph.add_item(store, f"wave-{rel}", f"Wave {rel}", node_type="Milestone", status="pending",
                       props={"kind": "wave", "release": rel})
    graph.add_item(store, "wi-three", "In the wave", milestone="wave-0.3.2",
                   props={"retro_notes": "the merges cost the most"})
    graph.add_item(store, "wi-four", "Carried in", milestone="wave-0.3.1", props={"carried_to": "0.3.2"})
    graph.add_item(store, "wi-five", "Carried out", milestone="wave-0.3.2", props={"carried_to": "wave-0.3.3"})
    graph.add_item(store, "wi-six", "Free text", props={"wave": "0.3.2, week of 2026-11-16"})
    _lesson(store, frm=["wi-three"])
    led = cost.Ledger([_row("s1", "wi-three", folder=str(p.root))], [p])
    for name in ("0.3.2", "wave-0.3.2"):
        assert lessons.wave_items(led, name) == ["wi-four", "wi-six", "wi-three"], name
    w = lessons.wave_retro(led, "0.3.2", store)
    assert [r["item"] for r in w["items"]] == ["wi-three"] and w["open"] == ["wi-four", "wi-six"]
    assert w["notes"] == {"wi-three": "the merges cost the most"}
    assert [x["id"] for x in w["learned"]] == ["les-demo-merge-stale-main"]
    text = "\n".join(lessons.render_wave(w))
    assert "retro notes recorded on the wave's items: 1" in text and "wi-three: the merges cost the most" in text
    assert lessons.wave_items(led, "0.3.3") == ["wi-five"]
    assert lessons.wave_items(led, "0.3") == []   # a prefix of a release names no wave
    assert lessons.wave_items(led, "F") == ["wi-one", "wi-two"]   # the letter waves, as before
    assert lessons.wave_items(led, "wave-") == [] and lessons.wave_items(led, " ") == []   # no name: no item


def test_a_numbered_wave_counts_only_its_own_stores_items(demo, tmp_path):
    """With several projects (--all), each project's wave of that release counts its own items, with the props.wave
    match."""
    p, store = demo
    graph.add_item(store, "wave-0.3.2", "Wave 0.3.2", node_type="Milestone", status="pending",
                   props={"kind": "wave", "release": "0.3.2"})
    graph.add_item(store, "wi-mine", "Mine", milestone="wave-0.3.2")
    other = tmp_path / "other" / "notes" / "graph"
    (other / "nodes").mkdir(parents=True)
    (other / "edges").mkdir()
    (other / "schema.yaml").write_text(LESSON_SCHEMA, encoding="utf-8")
    graph.add_item(other, "wave-0.3.2", "Its own 0.3.2", node_type="Milestone", status="pending",
                   props={"kind": "wave", "release": "0.3.2"})
    graph.add_item(other, "wi-theirs", "Theirs", milestone="wave-0.3.2")
    q = projects.Project(name="other", root=other.parents[1], stores=[other])
    led = cost.Ledger([], [p, q])
    assert lessons.wave_items(led, "0.3.2") == ["wi-mine", "wi-theirs"]
    led.items["wi-theirs"].store = store   # an id the ledger places in another store: not this wave's
    assert lessons.wave_items(led, "0.3.2") == ["wi-mine"]
    graph.set_item(store, "wi-two", ["wave=0.3.2, week of 2026-11-16"])
    led = cost.Ledger([], [p, q])
    assert lessons.wave_items(led, "0.3.2") == ["wi-mine", "wi-theirs", "wi-two"]


def test_cli_lesson_add_seen_list_follow_and_lint(lstore, capsys):
    root = str(lstore.parents[1])
    base = ["--root", root, "lesson", "add", "les-demo-bom", "--title", "A BOM in the answers file",
            "--trigger", "writing the answers JSON from PowerShell 5.1", "--anti-pattern",
            "Set-Content -Encoding utf8 adds a BOM and the batch wrote nothing", "--check",
            "`brain decision answer --batch` reads a BOM", "--signal", "owner", "--from", "wi-one",
            "--pr", "acme #146"]
    assert cli.main(base) == 0
    assert "add: les-demo-bom [open] seen 1" in capsys.readouterr().out
    assert cli.main(base[:4] + ["les-demo-bom-2"] + base[5:]) == 1
    assert "close to les-demo-bom" in capsys.readouterr().err
    assert cli.main(["--root", root, "lesson", "seen", "les-demo-bom", "--pr", "acme #147"]) == 0
    assert "filed wi-demo-bom" in capsys.readouterr().out
    assert cli.main(["--root", root, "lessons", "--follow"]) == 0
    out = capsys.readouterr().out
    assert "les-demo-bom [open]" in out and "led to wi-demo-bom [todo]" in out
    assert cli.main(["--root", root, "lesson", "--json", "list"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["lessons"][0]["seen"] == 2 and data["friction"] == []
    assert cli.main(["--root", root, "lint", "lessons"]) == 0
    assert "les-demo-bom: its check is a command" in capsys.readouterr().out


def _procedure() -> str:
    from pathlib import Path
    return (Path(lessons.__file__).parent / "procedures" / "close-item" / "SKILL.md").read_text(encoding="utf-8")


def test_the_close_item_procedure_has_the_retro_step():
    text = _procedure()
    step = text.split("## 2b. Retro", 1)[1].split("## 3.", 1)[0]
    assert "brain [--project P] retro <id>" in step and "--record --note" in step
    assert "brain lesson add les-<project>-<slug>" in step and "brain lesson seen <les-id>" in step
    assert "--signal <signal>" in step   # a lesson without its signal never shows in a later retro
    assert "brain retro --wave <W>" in step and "Retro: friction N" in text


def test_the_retro_never_stops_the_close_and_runs_before_the_tick():
    """The review of #33's blocking finding: a store with no Lesson type made step 3b fail, and the skill's stop rule
    then left the item half closed."""
    text = _procedure()
    assert text.index("## 2b. Retro") < text.index("## 3. Ticked")
    head = " ".join(text.split("## 0.", 1)[0].split())
    assert "the retro (step 2b) never stops the close" in head
    step = " ".join(text.split("## 2b. Retro", 1)[1].split("## 3.", 1)[0].split())
    assert "The retro never stops the close" in step and "`Retro: skipped (<why>)`" in step
    assert "Retro: skipped (<why>)" in text.split("## Report", 1)[1]


def test_a_store_without_the_lesson_type_says_how_to_add_it(store, capsys):
    with pytest.raises(lessons.LessonError, match="docs/lessons.md shows.*a retro goes on without it"):
        _lesson(store)
    assert cli.main(["--root", str(store.parents[1]), "lesson"]) == 0   # listing an old store: nothing, no error


def test_a_severe_lesson_whose_fix_is_done_files_nothing(lstore):
    graph.close_item(lstore, "wi-two", "acme #5", today="2026-10-20")
    out = _lesson(lstore, severity="high", led_to="wi-two")
    assert out["filed"] is None and out["linked"] is None
    assert [n for n in graph.node_index(lstore) if n.startswith("wi-demo")] == []


def test_seen_in_its_own_fix_item_is_no_regression(lstore):
    out = _lesson(lstore, severity="high")                  # files wi-demo-merge-stale-main
    fix = out["filed"]
    graph.close_item(lstore, fix, "acme #6", today="2026-11-04")
    again = lessons.seen(lstore, "les-demo-merge-stale-main", frm=[fix], today="2026-11-04")
    assert not again["regressed"] and again["filed"] is None and again["node"]["status"] == "open"
    later = lessons.seen(lstore, "les-demo-merge-stale-main", frm=["wi-two"], today="2026-11-10")
    assert later["regressed"] and later["filed"] == f"{fix}-2"   # seen elsewhere after the fix: a regression


def test_lint_propose_reports_a_linked_item_apart(lstore):
    graph.add_item(lstore, "wi-demo-stale-guard", "Warn on a merge resolution made against a stale main that drops "
                   "a merged PR's lines", props={"priority_proposed": "P2"})
    _lesson(lstore, propose=False)
    got = lessons.propose_guards(lstore, lessons.lint_lessons(lstore), today="2026-11-03")
    assert got == {"filed": [], "linked": ["wi-demo-stale-guard"]}


def test_the_retro_hint_names_the_signal_and_the_project_prefix(demo):
    p, store = demo
    led = cost.Ledger([_row("s1", "wi-one", folder=str(p.root))], [p])
    hint = lessons.render_retro(lessons.retro(led, "wi-one", store), owner="Ada")[-1]
    assert "brain lesson add les-<project>-<slug>" in hint and "--signal guards|merges|owner|rework|tests|waits" in hint


def test_lows_of_the_review(lstore, capsys):
    # the shell's test builtin and Test-Path are not test runs
    assert lessons.failed_tests([{"commands": {"test": {"fails": 1}, "test-path": {"fails": 2},
                                               "python -m pytest": {"fails": 1}, "npm test": {"fails": 1}}}]) == 2
    # a lesson recorded after its fix closed has not recurred
    graph.close_item(lstore, "wi-two", "acme #5", today="2026-10-20")
    _lesson(lstore, led_to="wi-two")
    assert lessons.rows(lstore)[0]["recurred_since_fix"] is False
    # like_item never links a node the lesson already learned from
    graph.add_item(lstore, "wi-src", "Merge resolution against a stale main", status="doing")
    lessons.add(lstore, "les-demo-src", "Merge resolution against a stale main", trigger="t1 x y", anti_pattern="a1 x y",
                check="c", frm=["wi-src"], new=True, propose=False)
    reg = lessons.Registry.load(lstore)
    assert lessons.like_item(reg, reg.nodes["les-demo-src"]) != "wi-src"
    # the list's flags after the list subcommand
    assert cli.main(["--root", str(lstore.parents[1]), "lesson", "list", "--json", "--status", "open"]) == 0
    assert {r["id"] for r in json.loads(capsys.readouterr().out)["lessons"]} == {"les-demo-merge-stale-main",
                                                                                 "les-demo-src"}


def test_one_edge_per_pair_the_fix_wins(lstore):
    _lesson(lstore, frm=["wi-one", "wi-two"], led_to="wi-two")
    edges = {(e["to"], e["type"]) for e in graph.load_yaml_list(lstore / lessons.EDGES)}
    assert edges == {("wi-one", "learned_from"), ("wi-two", "led_to")}
    lessons.seen(lstore, "les-demo-merge-stale-main", frm=["wi-two"], today="2026-11-04")
    assert len(graph.load_yaml_list(lstore / lessons.EDGES)) == 2  # wi-two is linked already


def test_a_command_is_any_shell_tool_after_its_environment():
    assert lessons.is_command("BRAIN_CONFIG=x/config.json brain check --public")
    assert lessons.is_command("grep -rl 'x' records/") and lessons.is_command("od -c f")
    assert lessons.is_command("git diff --cached --check")
    assert not lessons.is_command("props.retro") and not lessons.is_command("the owner says so")


def test_an_open_item_close_to_the_lesson_is_linked_not_duplicated(lstore):
    graph.add_item(lstore, "wi-demo-stale-guard", "Warn on a merge resolution made against a stale main that drops "
                   "a merged PR's lines", props={"priority_proposed": "P2"})
    out = _lesson(lstore, severity="high")
    assert out["filed"] is None and out["linked"] == "wi-demo-stale-guard"
    assert "wi-demo-merge-stale-main" not in graph.node_index(lstore)
    led = [e["to"] for e in graph.load_yaml_list(lstore / lessons.EDGES) if e["type"] == "led_to"]
    assert led == ["wi-demo-stale-guard"]


def test_the_wave_retro_carries_the_review_error_score(demo, brain_home):
    """wi-brain-review-error-score: the wave's score and the trend, from the stamps placed in it."""
    from brain import review
    p, store = demo
    review.stamp("a" * 40, 3, 3, note="- high correctness A.c fixed: one path only", wave="0.3.2", pr="5")
    w = lessons.wave_retro(cost.Ledger([], [p]), "wave-0.3.2", store)
    text = "\n".join(lessons.render_wave(w))
    assert "review error score, wave 0.3.2: 1 PR(s) reviewed, 3 confirmed finding(s), 3.0 per PR" in text
    assert "the reviews stay complete: 1 wave(s) scored, 3 needed" in text
