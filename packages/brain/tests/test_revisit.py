"""wi-brain-adr-revisit-report: the Revisit-if triggers already met or lapsed, read from the ADRs' prose at zero token
(brain.revisit; docs/revisit.md), and their sections in brain resume and brain digest."""

import json
from datetime import date, datetime, timezone

from brain import cli, digest, projects, resume, revisit

from conftest import git_init, run_git

LOG = """# Decisions

## 2026-01-10 — Kettles boil at ninety

**Context.** x.

**Decision.** Kettles stop at 90.

**Why.** Tea.

**Revisit if.** wi-kettle-sensor is done (then measure), or wi-old-thing closes; ms-first-pot is reached.

## 2026-01-10 — Mugs stay white

**Context.** x.

**Decision.** White mugs.

**Revisit if.** the question ddr-2026-01-12-mug-colour is answered; wi-glaze is dropped; wave s2 closes; the 0.3.0
release ships; feat-lab-saucers is have.

## 2026-01-10 — Spoons by the dozen

**Context.** x.

**Decision.** Twelve spoons.

**Revisit if.** 2026-02-01 passes without a lost spoon, or 2026-09-01; après deux semaines; in its first month; after
3 months.

## 2026-01-10 — The pot's timer

**Context.** x.

**Decision.** `pot.timer_s` is 240.

**Revisit if.** `pot.timer_s` or `pot.size` changes, or transcript.py moves.

## 2026-01-10 — Cups are blue

**Context.** x.

**Decision.** Blue.

**Revisit if.** wi-kettle-sensor is done.

## 2026-01-11 — Cups are green

**Context.** x.

**Decision.** Green, reversing the blue.

**Revisit if.** never.

## 2026-01-10 — Nothing to revisit yet

**Context.** x.

**Decision.** x.

**Revisit if.** TODO

## 2026-01-10 — Trays are square

**Context.** x.

**Decision.** Square.

**Revisit if.** wi-tray-maker is done.

## 2026-02-20 — Trays looked at again

**Context.** adr-2026-01-10-trays-are-square met its trigger.

**Decision.** Square still.

**Revisit if.** wi-pending is done.
"""

NODES = """\
- {id: wi-kettle-sensor, type: WorkItem, status: done, title: Sensor, props: {done: "2026-02-03 measured"}}
- {id: wi-old-thing, type: WorkItem, status: done, title: Old, props: {done: "2026-01-05 before the ADR"}}
- {id: ms-first-pot, type: Milestone, status: reached, title: First pot}
- {id: wi-glaze, type: WorkItem, status: dropped, title: Glaze, props: {dropped: "2026-02-05 no kiln"}}
- {id: wave-s2, type: Milestone, status: reached, title: Wave s2, props: {kind: wave, seq: 2, reached: "2026-02-10",
   shipped_as: 0.2.0}}
- {id: wave-s3, type: Milestone, status: reached, title: Wave s3, props: {kind: wave, seq: 3, reached: "2026-02-15",
   shipped_as: 0.3.0}}
- {id: wave-s4, type: Milestone, status: pending, title: Wave s4, props: {kind: wave, seq: 4}}
- {id: feat-lab-saucers, type: Feature, status: have, title: Saucers}
- {id: ddr-2026-01-12-mug-colour, type: DDR, status: archived, title: Mug colour,
   anchor: "records/ddr/ddr-2026-01-12-mug-colour.yaml#ddr-2026-01-12-mug-colour"}
- {id: wi-tray-maker, type: WorkItem, status: done, title: Trays, props: {done: "2026-02-18 made"}}
- {id: wi-pending, type: WorkItem, status: todo, title: Pending}
- {id: adr-2026-01-10-cups-are-blue, type: ADR, status: active, title: Cups are blue}
- {id: adr-2026-01-11-cups-are-green, type: ADR, status: active, title: Cups are green}
"""

TODAY = "2026-03-01"
KETTLE = "adr-2026-01-10-kettles-boil-at-ninety"
MUGS = "adr-2026-01-10-mugs-stay-white"
SPOONS = "adr-2026-01-10-spoons-by-the-dozen"
POT = "adr-2026-01-10-the-pot-s-timer"
TRAYS = "adr-2026-01-10-trays-are-square"


def _commit(root, monkeypatch, day: str, config: dict | None, msg: str) -> None:
    if config is not None:
        (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("GIT_COMMITTER_DATE", f"{day}T12:00:00")
    monkeypatch.setenv("GIT_AUTHOR_DATE", f"{day}T12:00:00")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "--allow-empty", "-m", msg)


def _lab(tmp_path, monkeypatch):
    root = git_init(tmp_path / "lab")
    store = root / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text("node_types: [WorkItem, Milestone, Feature, ADR, DDR]\n"
                                       "edge_types: [part_of, supersedes, decided_by]\n", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(NODES, encoding="utf-8")
    (store / "edges" / "work.yaml").write_text(
        "- {from: adr-2026-01-11-cups-are-green, to: adr-2026-01-10-cups-are-blue, type: supersedes}\n",
        encoding="utf-8")
    (root / "records" / "ddr").mkdir(parents=True)
    (root / "records" / "ddr" / "ddr-2026-01-12-mug-colour.yaml").write_text(
        "id: ddr-2026-01-12-mug-colour\nstatus: archived\nanswer: {at: '2026-01-20T10:00:00Z', choices: [white]}\n",
        encoding="utf-8")
    (root / "notes" / "decisions.md").write_text(LOG, encoding="utf-8")
    _commit(root, monkeypatch, "2026-01-05", {"pot": {"timer_s": 240}}, "start")
    _commit(root, monkeypatch, "2026-01-10", {"pot": {"timer_s": 240, "size": 1}}, "same day as the ADR")
    _commit(root, monkeypatch, "2026-01-25", {"pot": {"timer_s": 300, "size": 1}}, "a longer timer")
    _commit(root, monkeypatch, "2026-01-28", {"pot": {"timer_s": 200, "size": 1}}, "shorter again")
    return root, store


def _report(tmp_path, monkeypatch, **kw):
    root, store = _lab(tmp_path, monkeypatch)
    return revisit.report(store, [root / "notes" / "decisions.md"], root, TODAY, **kw)


def _flagged(rep):
    return {f["id"]: {(t["kind"], t["ref"]): t for t in f["triggers"]} for f in rep["flagged"]}


def test_a_named_node_closed_after_the_adr_is_met_and_one_closed_before_is_not(tmp_path, monkeypatch):
    got = _flagged(_report(tmp_path, monkeypatch))[KETTLE]
    sensor = got[("node", "wi-kettle-sensor")]
    assert sensor["state"] == "met" and sensor["day"] == "2026-02-03"
    assert sensor["evidence"] == "wi-kettle-sensor (WorkItem) done 2026-02-03"
    assert ("node", "wi-old-thing") not in got   # done before the ADR was written: it knew
    assert ("node", "ms-first-pot") not in got   # no dated prop: the commit that made it reached, before the ADR


def test_a_dropped_node_lapses_and_waves_ddrs_and_features_are_read(tmp_path, monkeypatch):
    got = _flagged(_report(tmp_path, monkeypatch))[MUGS]
    assert got[("node", "wi-glaze")]["state"] == "lapsed"
    assert got[("node", "ddr-2026-01-12-mug-colour")]["day"] == "2026-01-20"   # its record's answer
    saucers = got[("node", "feat-lab-saucers")]   # a feature has no closing day: kept, and said
    assert saucers["state"] == "met" and saucers["day"] == "" and "its day unknown" in saucers["evidence"]
    s2 = got[("wave", "wave-s2")]
    assert s2["day"] == "2026-02-10" and "shipped as 0.2.0" in s2["evidence"] and "« wave s2 »" in s2["evidence"]
    assert got[("wave", "wave-s3")]["evidence"].endswith("(named « 0.3.0 »)")   # a release resolves its wave


def test_days_past_and_spans_elapsed_lapse_and_a_future_day_does_not(tmp_path, monkeypatch):
    got = _flagged(_report(tmp_path, monkeypatch))[SPOONS]
    assert set(got) == {("date", "2026-02-01"), ("date", "après deux semaines"), ("date", "in its first month")}
    assert got[("date", "après deux semaines")]["day"] == "2026-01-24"
    assert got[("date", "in its first month")]["day"] == "2026-02-10"
    later = revisit.report(*_lab_again(tmp_path), "2026-05-01")
    assert ("date", "after 3 months") in _flagged(later)[SPOONS]   # due 2026-04-10


def _lab_again(tmp_path):
    root = tmp_path / "lab"
    return root / "notes" / "graph", [root / "notes" / "decisions.md"], root


def test_a_config_key_changed_after_the_adr_day_is_met_with_its_commit(tmp_path, monkeypatch):
    got = _flagged(_report(tmp_path, monkeypatch))[POT]
    assert set(got) == {("config", "pot.timer_s")}   # pot.size was set on the ADR's day; transcript.py is no key
    t = got[("config", "pot.timer_s")]
    assert t["day"] == "2026-01-25" and t["evidence"].startswith("pot.timer_s: 240 -> 300 in ")


def test_superseded_todo_and_reviewed_adrs_are_left_out(tmp_path, monkeypatch):
    rep = _report(tmp_path, monkeypatch)
    ids = set(_flagged(rep))
    assert ids == {KETTLE, MUGS, SPOONS, POT}
    assert rep["adrs"] == 8 and rep["with_revisit"] == 7 and rep["reviewed"] == 1   # blue superseded, TODO skipped
    shown = {f["id"]: f for f in revisit.report(*_lab_again(tmp_path), TODAY, show_all=True)["flagged"]}
    assert shown[TRAYS]["reviewed_by"] == ["adr-2026-02-20-trays-looked-at-again"]


def test_the_newest_triggers_come_first_and_counts_add_up(tmp_path, monkeypatch):
    rep = _report(tmp_path, monkeypatch)
    assert [f["id"] for f in rep["flagged"]] == [MUGS, SPOONS, KETTLE, POT]   # by their newest trigger
    assert rep["counts"] == {"node": 4, "wave": 2, "date": 3, "config": 1}


def test_the_cli_json_keys_and_text(tmp_path, monkeypatch, capsys):
    root, _ = _lab(tmp_path, monkeypatch)
    (tmp_path / "projects.yaml").write_text(f"lab: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    monkeypatch.chdir(root)
    assert cli.main(["adr", "revisit", "--today", TODAY, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert list(out) == ["v", "today", "logs", "adrs", "with_revisit", "flagged", "reviewed", "counts"]
    assert out["v"] == 1 and out["logs"] == ["notes/decisions.md"]
    assert list(out["flagged"][0]) == ["id", "day", "title", "file", "line", "revisit", "triggers", "reviewed_by"]
    assert list(out["flagged"][0]["triggers"][0]) == ["kind", "ref", "state", "day", "evidence"]
    assert cli.main(["adr", "revisit", "--today", TODAY]) == 0
    text = capsys.readouterr().out
    assert text.startswith("revisit: 8 ADR(s) in force, 7 with a Revisit if; 4 with a trigger met or lapsed")
    assert "(--all shows them)" in text and f"- {POT} (notes/decisions.md:" in text
    assert "    met config: pot.timer_s: 240 -> 300 in " in text
    assert cli.main(["adr", "revisit", "--today", "March"]) == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_resume_and_digest_carry_the_section(tmp_path, monkeypatch):
    root, _ = _lab(tmp_path, monkeypatch)
    (tmp_path / "projects.yaml").write_text(f"lab: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    p = projects.get("lab")
    text = resume.build(p, offline=True, budget=0, now=datetime(2026, 3, 1, 9, tzinfo=timezone.utc))
    sec = text.split("## Revisit if met or lapsed")[1].split("\n## ")[0]
    assert "4 ADR(s) in force with a trigger met or lapsed:" in sec
    assert f"- {MUGS}: met node ddr-2026-01-12-mug-colour (+4): Mugs stay white" in sec
    week = digest.gather(p, since="2026-02-09", until="2026-02-16", offline=True, today=date(2026, 3, 1))
    assert {f["id"]: [t["ref"] for t in f["triggers"]] for f in week["revisit"]} == {
        MUGS: ["wave-s2", "wave-s3"], SPOONS: ["in its first month"]}
    page = digest.build(p, since="2026-02-09", until="2026-02-16", offline=True, budget=0,
                        today=date(2026, 3, 1), now=datetime(2026, 3, 1, tzinfo=timezone.utc))
    assert "## Revisit if met or lapsed (2 ADRs; `brain adr revisit`)" in page
    assert "  met wave: wave-s2 (Milestone) reached 2026-02-10" in page


def test_a_project_without_a_log_or_store_reads_nothing(tmp_path):
    rep = revisit.report(None, [tmp_path / "none.md"], tmp_path, TODAY)
    assert rep["adrs"] == 0 and rep["flagged"] == [] and rep["logs"] == []


def test_related_is_the_spec_context_source(tmp_path, monkeypatch):
    rep = _report(tmp_path, monkeypatch)
    assert [f["id"] for f in revisit.related(rep, refs={"pot.timer_s"})] == [POT]
    assert [f["id"] for f in revisit.related(rep, words=["MUGS", "white"])] == [MUGS]
    assert revisit.related(rep) == []


def test_spans_count_calendar_months():
    assert revisit.add_span(date(2026, 1, 31), 1, "month") == date(2026, 2, 28)
    assert revisit.add_span(date(2026, 1, 10), 2, "semaines") == date(2026, 1, 24)
    assert revisit.add_span(date(2026, 1, 10), 1, "an") == date(2027, 1, 10)
    assert revisit.add_span(date(2026, 1, 10), 3, "jours") == date(2026, 1, 13)
