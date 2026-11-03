import json
from datetime import date, datetime, timezone

import pytest

from brain import cli, decisions, digest, projects, resume

from conftest import run_git

TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)


def _registry(tmp_path, monkeypatch, root, extra=""):
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n{extra}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))


def _project(tmp_path, monkeypatch, store):
    """The store fixture made a project with a past: items closed in and out of the window, milestones, an ADR log,
    DDRs, a session record and a journal."""
    root = store.parents[1]
    with open(store / "nodes" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("- {id: wi-shipped, type: WorkItem, status: done, title: \"Shipped\",\n"
                 "   props: {priority: P1, pr: \"root #7\", done: \"2026-11-01 shipped the thing; tests green\"}}\n"
                 "- {id: wi-old, type: WorkItem, status: done, title: \"Old\", props: {done: \"2026-10-01 old\"}}\n"
                 "- {id: wi-gone, type: WorkItem, status: dropped, title: \"Gone\",\n"
                 "   props: {dropped: \"2026-10-31 superseded by wi-shipped\"}}\n"
                 "- {id: wi-undated, type: WorkItem, status: done, title: \"Undated\"}\n"
                 "- {id: ms-y, type: Milestone, status: reached, title: \"Milestone Y\",\n"
                 "   props: {reached: \"2026-10-31: evidence here\"}}\n"
                 "- {id: ms-z, type: Milestone, status: reached, title: \"Milestone Z\"}\n")
    (root / "notes" / "decisions.md").write_text(
        "# Decisions\n\n## 2026-10-20 — Old one (ADR)\n\n**Context.** c\n\n**Decision.** old.\n\n"
        "## 2026-10-31 — Pick the store (ADR)\n\n**Context.** Some context.\n\n**Décision.** Files first. Then\n"
        "SQLite when it hurts.\n\n**Why.** w\n\n"
        "## 2026-11-01 — REVERSAL: Pick the store\n\n**Supersedes.** 2026-10-31\n\n"
        "**New decision.** SQLite now.\n\n"
        "## 2026-11-02 — A note\n\nPlain first paragraph. Second sentence.\n", encoding="utf-8")
    (root / "notes" / "journal.md").write_text(
        "# Journal\n\n## 2026-10-20 — Old\n\n- old\n\n## 2026-10-31 — Middle\n\n"
        "- First sentence of a bullet. Second sentence\n  continued.\n  - a sub bullet\n- Another bullet\n\n"
        "## 2026-11-02 — Today\n\n- today line\n", encoding="utf-8")
    decisions.ask(root, title="Pick a store", question="Which?", options=["A: first", "B: second"], why="simplest",
                  at="2026-10-30T08:00:00Z", items=["wi-shipped"])
    decisions.answer(root, "pick-a-store", ["A"], at="2026-11-01T09:00:00Z")
    decisions.ask(root, title="Ancient", question="Which?", options=["X", "Y"], why="short",
                  at="2026-10-01T08:00:00Z")
    sr = root / "records" / "sr" / "2026-11"
    sr.mkdir(parents=True)
    (sr / "sr-2026-11-01-abc.yaml").write_text(
        "v: 1\nid: sr-2026-11-01-abc\nstatus: closed\nsummary: Shipped it\nmodel: m\neffort: high\n"
        "start: '2026-11-01T10:00:00Z'\nactive_s: 5400\ntokens: {output: 12345}\nprs: [{repo: o/root, number: 7}]\n",
        encoding="utf-8")
    monkeypatch.setattr(digest.actions, "repo_name", lambda d: "o/root")
    _registry(tmp_path, monkeypatch, root)
    return projects.get("demo")


def test_window_forms():
    st = resume.Store({"ms-y": {"id": "ms-y", "type": "Milestone", "status": "reached",
                                "props": {"reached": "2026-10-31: evidence"}},
                       "ms-p": {"id": "ms-p", "type": "Milestone", "status": "pending"},
                       "wi-a": {"id": "wi-a", "type": "WorkItem", "status": "done"}}, [])
    assert digest.resolve("today", TODAY) == "2026-11-02"
    assert digest.resolve("yesterday", TODAY) == "2026-11-01"
    assert digest.resolve("last-week", TODAY) == "2026-10-26"
    assert digest.resolve("Last-Month", TODAY) == "2026-10-02"
    assert digest.resolve("last-month", date(2026, 3, 31)) == "2026-02-28"  # clamped to the month's last day
    assert digest.resolve("last-month", date(2026, 1, 15)) == "2025-12-15"
    assert digest.resolve("2026-10-29", TODAY) == "2026-10-29"
    assert digest.resolve("ms-y", TODAY, st=st) == "2026-10-31"
    for when, why in (("2026-02-30", "not a day"), ("ms-p", "pending, not reached"), ("wi-a", "not a milestone"),
                      ("next-week", "expected YYYY-MM-DD"), ("ms-nope", "no such node")):
        with pytest.raises(digest.DigestError, match=why):
            digest.resolve(when, TODAY, st=st)
    w = digest.Window("2026-10-26", "2026-11-02")
    assert w.has("2026-10-26T00:00:00Z") and w.has("2026-11-02") and not w.has("2026-11-03") and not w.has("")


def test_gather_reads_every_source_newest_first(tmp_path, monkeypatch, store):
    p = _project(tmp_path, monkeypatch, store)
    d = digest.gather(p, offline=True, today=TODAY)
    assert (d["since"], d["until"]) == ("2026-10-26", "2026-11-02")
    assert [(m["id"], m["day"]) for m in d["milestones"]] == [("ms-y", "2026-10-31")]  # ms-z has no date
    assert [(i["id"], i["status"], i["day"]) for i in d["items"]] == [
        ("wi-shipped", "done", "2026-11-01"), ("wi-gone", "dropped", "2026-10-31")]
    assert d["items"][0]["outcome"] == "shipped the thing; tests green" and d["items"][0]["pr"] == "root #7"
    assert [(a["day"], a["title"]) for a in d["adrs"]] == [
        ("2026-11-02", "A note"), ("2026-11-01", "REVERSAL: Pick the store"), ("2026-10-31", "Pick the store (ADR)")]
    assert d["adrs"][2]["id"] == "adr-2026-10-31-pick-the-store-adr"
    assert d["adrs"][2]["decision"] == "Files first. Then SQLite when it hurts."
    assert d["adrs"][1]["decision"] == "SQLite now."
    assert d["adrs"][0]["lead"] == "Plain first paragraph. Second sentence." and not d["adrs"][0]["decision"]
    assert [x["id"] for x in d["ddrs"]] == ["ddr-2026-10-30-pick-a-store"]  # the ancient one has no event in it
    assert d["ddrs"][0]["events"] == {"asked": "2026-10-30", "answered": "2026-11-01"}
    assert d["ddrs"][0]["answer"] == "A" and d["ddrs"][0]["status"] == "answered"
    assert [s["id"] for s in d["sessions"]] == ["sr-2026-11-01-abc"] and d["sessions"][0]["prs"] == ["o/root#7"]
    assert [(e["day"], e["title"]) for e in d["journal"]] == [("2026-11-02", "Today"), ("2026-10-31", "Middle")]
    assert d["journal"][1]["bullets"][0] == \
        "- First sentence of a bullet. Second sentence\n  continued.\n  - a sub bullet"
    assert d["prs"] is None and d["prs_why"] == "--offline" and d["summary"] is None
    json.dumps(d)  # --json prints it as is


def test_text_sections_and_determinism(tmp_path, monkeypatch, store):
    p = _project(tmp_path, monkeypatch, store)
    text = digest.build(p, offline=True, today=TODAY, now=NOW, budget=0)
    assert text == digest.build(p, offline=True, today=TODAY, now=NOW, budget=0)
    heads = [ln.split(" (")[0] for ln in text.splitlines() if ln.startswith("## ")]
    assert heads == ["## Milestones reached", "## Items closed", "## ADRs", "## DDRs", "## Merged PRs",
                     "## Session records", "## Journal", "## Generated"]
    assert text.startswith("# Digest — demo (root), 2026-10-26 to 2026-11-02\n")
    assert "In it: 1 milestone reached, 2 items closed, 3 ADRs, 1 DDR with an event, PRs not read, " \
           "1 session record, 2 journal entries." in text
    assert "- ms-y reached 2026-10-31: Milestone Y\n  evidence here\n" in text
    assert "- wi-shipped 2026-11-01 [P1] (root #7): Shipped\n  shipped the thing; tests green\n" in text
    assert "- wi-gone dropped 2026-10-31: Gone\n" in text
    assert "- 2026-10-31: Pick the store\n  Decision: Files first.\n" in text  # (ADR) suffix off, first sentence
    assert "- 2026-11-02: A note\n  Plain first paragraph.\n" in text
    assert "asked 2026-10-30; answered 2026-11-01: A" in text
    assert "Merged PRs\nNot read (--offline)." in text
    assert "- 2026-11-01 sr-2026-11-01-abc [m high]: Shipped it\n" \
           "  1.5 h active, 12,345 output tokens; PRs o/root#7\n" in text
    journal = text.split("## Journal")[1]
    assert journal.index("### 2026-11-02 — Today") < journal.index("### 2026-10-31 — Middle")
    assert "  - a sub bullet" in journal and "Old" not in journal
    assert text.endswith("## Generated\nGenerated 2026-11-02 09:30 UTC.\n")  # not a git checkout, nothing condensed


def test_budget_lowers_the_journal_first_then_cuts(tmp_path, monkeypatch, store):
    p = _project(tmp_path, monkeypatch, store)
    with open(p.journal, "a", encoding="utf-8") as fh:  # a busy day: lowering the journal pays
        fh.write("- " + "\n- ".join(f"Bullet {i} is short. Its tail {'goes on ' * 12}" for i in range(20)) + "\n")
    data = digest.gather(p, offline=True, today=TODAY)
    full = digest.render(p, data, budget=0, now=NOW)
    text = digest.render(p, data, budget=resume.tokens(full) - 1, now=NOW)
    journal = text.split("## Journal")[1]
    assert "- Bullet 3 is short.\n" in journal and "goes on" not in journal and "sub bullet" not in journal
    assert "- First sentence of a bullet.\n- Another bullet\n" in journal
    assert "shipped the thing" in text and "Decision: Files first." in text and "1.5 h active" in text
    assert "Condensed for --budget" in text and "journal first sentences." in text
    levels = [resume.tokens("\n".join(lv)) for lv in digest._journal(data["journal"], "notes/journal.md").levels]
    budget = resume.tokens(full) - levels[0] + levels[2] + 40
    heads = digest.render(p, data, budget=budget, now=NOW)  # then its headings, before anything else
    assert resume.tokens(heads) <= budget
    assert "- 2026-11-02: Today (21 bullets)\n" in heads and "Bullet 3" not in heads
    assert "shipped the thing" in heads and "Decision: Files first." in heads and "journal headings." in heads
    low = digest.render(p, data, budget=resume.tokens(full) // 3, now=NOW)  # every section lowered
    assert resume.tokens(low) <= resume.tokens(full) // 3 and "journal a count" in low
    assert "2 entries from 2026-10-31 to 2026-11-02: notes/journal.md." in low
    tiny = digest.render(p, data, budget=1, now=NOW)  # only the header, the cut note and the last section are left
    assert [ln for ln in tiny.splitlines() if ln.startswith("#")] == [
        "# Digest — demo (root), 2026-10-26 to 2026-11-02", "## Cut", "## Generated"]
    assert "dropped from the end (the oldest journal entries first)" in tiny and "`brain digest --budget 0`" in tiny


def test_condense_follows_the_steps():
    parts = [digest.Part(k, k, [["x"] * 9, ["x"] * 3, ["x"], ["x"]][:n], ["a", "b", "c", "d"][:n])
             for k, n in (("items", 3), ("journal", 4), ("adrs", 3))]
    seen = []
    digest.condense(parts, lambda: seen.append(tuple(p.level for p in parts)) and False)
    # journal down to its headings first, then the ADRs, then the items; then the last levels
    assert seen[:4] == [(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 2, 1)]
    assert tuple(p.level for p in parts) == (2, 3, 2)


def test_git_dates_a_closed_node_without_a_dated_prop(tmp_path, monkeypatch, git_repo):
    (git_repo / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem, Milestone]\n", encoding="utf-8")
    work = git_repo / "notes" / "graph" / "nodes" / "work.yaml"
    for day, text in (("2026-10-28", work.read_text(encoding="utf-8").replace(
            "{id: wi-b, type: WorkItem, status: todo", "{id: wi-b, type: WorkItem, status: done")),
                      ("2026-10-30", work.read_text(encoding="utf-8").replace(
                          "{id: wi-b, type: WorkItem, status: todo", "{id: wi-b, type: WorkItem, status: done")
                       + "- {id: ms-m, type: Milestone, status: reached, title: \"M\"}\n")):
        work.write_text(text, encoding="utf-8")
        monkeypatch.setenv("GIT_COMMITTER_DATE", f"{day}T12:00:00Z")
        monkeypatch.setenv("GIT_AUTHOR_DATE", f"{day}T12:00:00Z")
        run_git(git_repo, "commit", "-qam", f"close on {day}")
    store = git_repo / "notes" / "graph"
    assert digest.git_closures(git_repo, store) == {"wi-b": ("2026-10-28", "done"), "ms-m": ("2026-10-30", "reached")}
    assert digest.git_closures(git_repo, store, "2026-10-29", "2026-11-02") == {"ms-m": ("2026-10-30", "reached")}
    assert digest.git_closures(git_repo, store, "2026-10-28", "2026-10-29") == {"wi-b": ("2026-10-28", "done")}
    assert digest.git_closures(git_repo, tmp_path / "elsewhere") == {}
    _registry(tmp_path, monkeypatch, git_repo)
    p = projects.get("demo")
    st = resume.Store.load(store)
    miles, items = digest.closures(p, st, digest.Window("2026-10-26", "2026-11-02"))
    assert [(i["id"], i["day"], i["day_from"]) for i in items] == [("wi-b", "2026-10-28", "git")]
    assert [(m["id"], m["day"]) for m in miles] == [("ms-m", "2026-10-30")]
    assert digest.resolve("ms-m", TODAY, p, st) == "2026-10-30"  # a milestone without props.reached, dated by git


def test_merged_prs_less_those_on_the_items(tmp_path, monkeypatch, store):
    p = _project(tmp_path, monkeypatch, store)
    calls = []

    def gh(root, args, timeout=15.0):
        calls.append(args)
        return [{"number": 7, "title": "Ship it", "mergedAt": "2026-11-01T10:00:00Z", "headRefName": "a"},
                {"number": 8, "title": "Docs", "mergedAt": "2026-10-31T10:00:00Z", "headRefName": "b"},
                {"number": 2, "title": "Before", "mergedAt": "2026-10-20T10:00:00Z", "headRefName": "c"}], ""
    monkeypatch.setattr(digest.resume, "gh_json", gh)
    d = digest.gather(p, today=TODAY)
    assert "merged:2026-10-26..2026-11-02" in calls[0] and [x["number"] for x in d["prs"]] == [7, 8]
    text = digest.render(p, d, budget=0, now=NOW)
    assert "## Merged PRs (2; the 1 a closed item cites are on its line)\n- #8 2026-10-31: Docs\n\n" in text
    monkeypatch.setattr(digest.resume, "gh_json", lambda root, args, timeout=15.0: (None, "gh not found"))
    assert digest.merged_prs(p.root, digest.Window("2026-10-26", "2026-11-02"), False) == (None, "gh not found")
    assert digest.cited_prs([{"pr": "root #7, other #9"}, {"pr": "#3 and PR #4"}, {"pr": "Root #5"}], "o/root") == \
        {7, 3, 4, 5}


def test_summary_written_beside_the_digest_comes_first(tmp_path, monkeypatch, store):
    p = _project(tmp_path, monkeypatch, store)
    d = digest.gather(p, offline=True, today=TODAY)
    f = digest.summary_path("demo", digest.Window(d["since"], d["until"]))
    f.parent.mkdir(parents=True)
    f.write_text("# Week 44\n\nThe store was picked.\nThen shipped.\n\nMore detail.\n", encoding="utf-8")
    d = digest.gather(p, offline=True, today=TODAY)
    assert d["summary"]["text"].startswith("# Week 44") and d["summary"]["path"] == str(f)
    text = digest.render(p, d, budget=0, now=NOW)
    assert text.split("\n## ")[1].startswith("Narrative summary (") and "The store was picked.\nThen shipped." in text
    assert "# Week 44" not in text
    assert digest.latest("demo") is None  # a summary is not a digest


def test_write_latest_and_the_resume_pack_points_to_it(tmp_path, monkeypatch, store):
    p = _project(tmp_path, monkeypatch, store)
    assert "History: the latest digest" not in resume.build(p, offline=True, now=NOW)
    for since in ("2026-10-26", "2026-10-30"):
        d = digest.gather(p, since, "2026-11-01", offline=True, today=TODAY)
        digest.write("demo", d, digest.render(p, d, now=NOW))
    d = digest.gather(p, "2026-10-01", "2026-10-31", offline=True, today=TODAY)
    out = digest.write("demo", d, digest.render(p, d, now=NOW))
    assert out == resume.paths.brain_home() / "digest" / "demo" / "2026-10-01_2026-10-31.md"
    assert digest.latest("demo").name == "2026-10-30_2026-11-01.md"  # the window that ends last, then starts last
    pack = resume.build(p, offline=True, now=NOW)
    assert "History: the latest digest is " in pack and "2026-10-30_2026-11-01.md" in pack.split("## Journal")[1]


def test_journal_entries_and_first_sentences(tmp_path):
    j = tmp_path / "j.md"
    j.write_text("# J\n\nintro\n\n## 2026-11-01 — A\n\nA paragraph\nwrapped.\n- b1 e.g. this. Next one\n  - sub\n"
                 "## 2026-11-02 — B\n", encoding="utf-8")
    assert resume.journal_entries(j) == [
        ("2026-11-01 — A", [["A paragraph"], ["wrapped."], ["- b1 e.g. this. Next one", "  - sub"]]),
        ("2026-11-02 — B", [])]
    assert resume.last_entry(j) == ("2026-11-02 — B", [], 0)
    assert digest._first_bullet_sentence("- b1 e.g. this. Next one\n  - sub") == "- b1 e.g. this."
    assert digest.first_sentence("No full stop here") == "No full stop here"
    assert digest.first_sentence("Version v0.3.0 shipped. Then more.") == "Version v0.3.0 shipped."


def test_cli_digest(tmp_path, monkeypatch, store, capsys):
    _project(tmp_path, monkeypatch, store)
    other = tmp_path / "other"
    (other / "notes" / "graph").mkdir(parents=True)
    _registry(tmp_path, monkeypatch, store.parents[1], f"other: {{root: {other.as_posix()}}}\n")
    args = ["--since", "2026-10-26", "--until", "2026-11-02", "--offline"]
    assert cli.main(["--project", "demo", "digest", *args, "--write"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("# Digest — demo") and "digest: demo -> " in out.err
    assert (resume.paths.brain_home() / "digest" / "demo" / "2026-10-26_2026-11-02.md").read_text(
        encoding="utf-8") == out.out
    assert cli.main(["digest", "--project", "demo", *args, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["project"] == "demo" and [i["id"] for i in data["items"]] == ["wi-shipped", "wi-gone"]
    assert cli.main(["digest", "--all", *args]) == 0
    text = capsys.readouterr().out
    assert "# Digest — demo" in text and "# Digest — other" in text
    assert cli.main(["digest", "--all", "--since", "ms-y", "--offline"]) == 1  # other has no ms-y: that one fails
    out = capsys.readouterr()
    assert "# Digest — demo" in out.out and "brain digest: other: 'ms-y': expected" in out.err
    monkeypatch.chdir(store.parents[1] / "notes")
    assert cli.main(["digest", *args, "--budget", "1"]) == 0
    assert "## Cut" in capsys.readouterr().out
