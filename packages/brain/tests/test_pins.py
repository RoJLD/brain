"""wi-brain-decision-pins: a decision pinned to the code it governs (brain.pins, docs/pins.md): brain adr pin writes
pins.yaml beside the decision log, brain impact --diff lists the pinned decisions a change touches, brain review
check and brain merge-ready refuse until the PR body keeps or overrides each one, brain check warns on a bad pin.
spec-brain-three-repos §3 no. 3 (TR-2). Fixtures only."""

import subprocess
from pathlib import Path

import pytest
from brain import cli, decisions, mergeready, notes, pins, projects, review, scout

AT = "2026-11-02T09:00:00Z"
OPTS = ["A: the first", "B: the second"]
LOG = """# Decisions

## 2026-11-01 — Retries stay at four

**Context.** x

**Decision.** four retries.

## 2026-11-02 — The cache is per user for every outbound call the engine's network layer makes

**Context.** y

**Decision.** per user.

## 2026-11-02 — Batches run at night

**Context.** z

**Decision.** at night.
"""
RETRY = "adr-2026-11-01-retries-stay-at-four"
REVERSAL_FIELDS = {"context": "c", "decision": "d", "why": "w", "migration": "m", "trigger": "t", "revisit": "r"}


@pytest.fixture
def proj(store):
    """RETRY in force; CACHE superseded by a REVERSAL whose Supersedes field wraps (a long title); NIGHT superseded by
    a reversal given its own title; an answered DDR superseded by an ADR; a pending DDR."""
    root = store.parents[1]
    log = root / "notes" / "decisions.md"
    log.write_text(LOG, encoding="utf-8", newline="\n")
    pending, _ = decisions.ask(root, title="Pending one", question="?", options=OPTS, why="w", at=AT)
    done, _ = decisions.ask(root, title="Answered one", question="?", options=OPTS, why="w", at=AT)
    decisions.answer(root, done["id"], ["A"], at=AT)
    other, _ = decisions.ask(root, title="Answered two", question="?", options=OPTS, why="w", at=AT)
    decisions.answer(root, other["id"], ["B"], at=AT)
    ids = {e["title"][:9]: e["id"] for e in notes.adr_entries(log.read_text(encoding="utf-8"))}
    rev = notes.adr_new(log, "", REVERSAL_FIELDS, day="2026-11-03", reverses=ids["The cache"])
    own = notes.adr_new(log, "Daytime batches", REVERSAL_FIELDS, day="2026-11-04", reverses=ids["Batches r"])
    over = notes.adr_new(log, "The second answer replaced", REVERSAL_FIELDS, day="2026-11-05", reverses=other["id"])
    p = projects.for_root(root)
    p.ids = {"cache": ids["The cache"], "reversal": rev["id"], "night": ids["Batches r"], "day": own["id"],
             "pending": pending["id"], "answered": done["id"], "other": other["id"], "over": over["id"]}
    return p


def test_a_reversal_is_found_however_its_supersedes_field_wraps_and_whatever_its_title(proj):
    i = proj.ids
    text = (proj.root / "notes" / "decisions.md").read_text(encoding="utf-8")
    field = text.split("**Supersedes.**", 1)[1].split("\n\n", 1)[0]
    assert "\n" in field   # the id is on the field's second line (finding 1)
    known = pins.decisions_of(proj)
    assert known[i["cache"]].superseded_by == i["reversal"] and known[i["cache"]].status == "superseded"
    assert known[i["night"]].superseded_by == i["day"]   # a reversal titled freely
    assert known[i["other"]].superseded_by == i["over"]   # an answered DDR overridden by an ADR (finding 6)
    assert not known[RETRY].superseded_by and not known[i["reversal"]].superseded_by
    with pytest.raises(notes.NotesError, match="give the title"):
        notes.adr_new(proj.root / "notes" / "decisions.md", "", REVERSAL_FIELDS, reverses=i["answered"])


def test_brain_adr_pin_writes_a_pin_and_never_edits_its_holds(proj, capsys):
    root, i = str(proj.root), proj.ids
    assert cli.main(["--root", root, "adr", "pin", RETRY, "--touches", "src/net.py", "--holds", "retries stay at 4",
                     "--date", "2026-11-12"]) == 0
    assert "pin: adr-2026-11-01-retries-stay-at-four pinned (1 touch(es))" in capsys.readouterr().out
    assert cli.main(["--root", root, "adr", "pin", RETRY, "--touches", "code:demo:src/retry.py::backoff"]) == 0
    assert pins.load(proj) == [{"decision": RETRY, "holds": "retries stay at 4",
                                "touches": ["src/net.py", "code:demo:src/retry.py::backoff"], "since": "2026-11-12"}]
    assert cli.main(["--root", root, "adr", "pin", RETRY, "--touches", "x.py", "--holds", "five"]) == 1
    assert "a holds line is never edited" in capsys.readouterr().err
    for ref, touch, why in ((i["cache"], "a.py", "superseded by " + i["reversal"]),
                            (i["pending"], "a.py", "only an answered"), ("adr-nope", "a.py", "no such ADR"),
                            (i["reversal"], "C:\\x.py", "a path relative"), (i["reversal"], "./a.py", "without ./")):
        assert cli.main(["--root", root, "adr", "pin", ref, "--touches", touch, "--holds", "h"]) == 1
        assert why in capsys.readouterr().err
    assert cli.main(["--root", root, "adr", "pin", i["answered"], "--touches", "docs/", "--holds", "h"]) == 0
    assert pins.path_of(proj) == proj.root / "notes" / "pins.yaml"


def test_add_merges_every_row_of_a_decision_and_refuses_a_file_it_would_lose(proj):
    f = pins.path_of(proj)
    f.write_text(f"- {{decision: {RETRY}, holds: four, touches: a.py}}\n"
                 f"- {{decision: {RETRY}, holds: four, touches: [b.py]}}\n", encoding="utf-8")
    pin, verb = pins.add(proj, RETRY, ["c.py"])
    assert verb == "extended" and pin["touches"] == ["a.py", "b.py", "c.py"] and len(pins.load(proj)) == 1
    f.write_text(f"- {{decision: {RETRY}, holds: four, touches: [a.py]}}\n- just a line\n", encoding="utf-8")
    with pytest.raises(pins.PinError, match="1 entry"):
        pins.add(proj, RETRY, ["c.py"])
    assert "1 entry(ies) that are not pins" in pins.check_lines(proj)[0]


def test_a_change_hits_a_pin_by_file_folder_glob_or_coderef(proj):
    pin = {"touches": ["src/net.py", "docs/", "tests/test_*.py", "code:demo:src/retry.py::backoff",
                       "code:other:src/net.py", "lib/**/*.py"]}
    files = {"src/net.py", "docs/a.md", "tests/test_x.py", "src/retry.py", "tests/sub/test_y.py", "lib/a/b/c.py"}
    assert pins.hits(pin, files, {"demo"}) == ["src/net.py", "docs/a.md", "tests/test_x.py",
                                              "code:demo:src/retry.py::backoff", "lib/a/b/c.py"]
    ref = "code:demo:src/retry.py::backoff"   # GitNexus said which symbols: only a touched symbol counts
    assert ref not in pins.hits(pin, files, {"demo"}, refs=set(), known={ref})
    assert ref in pins.hits(pin, files, {"demo"}, refs={ref}, known={ref})
    assert ref in pins.hits(pin, files, {"demo"}, refs=set(), known=set())   # a CodeRef the graph lacks: the file
    assert pins.hits(pin, {"README.md"}, {"demo"}) == []
    # through touched: the CodeRefs the graph knows are not mistaken for decision ids (finding 3)
    pins.add(proj, RETRY, [ref], "retries stay at 4", "2026-11-12")
    assert pins.touched(proj, {"src/retry.py"}, {"demo"}, refs=set(), known={ref}) == []
    assert [t["id"] for t in pins.touched(proj, {"src/retry.py"}, {"demo"}, refs={ref}, known={ref})] == [RETRY]


def _pinned(proj):
    """RETRY (in force) and CACHE (pinned before its REVERSAL) on two files."""
    pins.path_of(proj).write_text(
        f"- {{decision: {RETRY}, holds: retries stay at 4, touches: [src/net.py]}}\n"
        f"- {{decision: {proj.ids['cache']}, holds: per user, touches: [src/cache.py]}}\n", encoding="utf-8")
    return pins.touched(proj, {"src/net.py", "src/cache.py"}, {"demo"})


def test_keeps_for_a_decision_in_force_overrides_with_its_reason_for_a_superseded_one(proj):
    cache, rev = proj.ids["cache"], proj.ids["reversal"]
    touched = _pinned(proj)
    assert [(t["id"], t["superseded_by"]) for t in touched] == [(RETRY, ""), (cache, rev)]   # finding 2: it stays
    assert pins.verdict(proj, touched, None)[0].startswith("2 pinned decision(s) touched")
    blocks = pins.verdict(proj, touched, "A change.\n")
    assert len(blocks) == 2 and f"says neither Keeps {RETRY}" in blocks[0] and f"superseded by {rev}" in blocks[1]
    assert pins.verdict(proj, touched, f"Keeps {RETRY}\nKeeps {cache}\n") == [
        f"{cache} is superseded by {rev}: the PR body says Overrides {cache}: <why>"]
    assert pins.verdict(proj, touched, f"Keeps {RETRY}\nOverrides {cache}\n") == [
        f"Overrides {cache}: the reason is missing"]
    assert pins.verdict(proj, touched, f"Overrides {RETRY}: five now\nOverrides {cache}: per machine\n") == [
        f"Overrides {RETRY}: no later ADR supersedes it yet (brain adr new --reverses {RETRY})"]
    assert pins.verdict(proj, touched, f"1. Keeps **{RETRY.upper()}**.\n- Overrides `{cache}` — per machine\n") == []
    assert pins.verdict(proj, touched, f"Keeps {RETRY}\nOverrides {cache}: x\nKeeps {cache}\n") == [
        f"{cache}: the PR body both keeps and overrides it"]


def test_lines_the_rendered_pr_does_not_show_do_not_count():
    body = "```\nKeeps adr-a\n```\n<!-- Keeps adr-b -->\nKeeps adr-c, adr-d\n> Keeps adr-e\n"
    assert pins.answers(body) == {"adr-c": {"keeps": ""}, "adr-d": {"keeps": ""}}


def test_brain_check_warns_on_a_pin_it_cannot_hold(proj):
    cache, rev = proj.ids["cache"], proj.ids["reversal"]
    pins.path_of(proj).write_text(
        f"- {{decision: {cache}, holds: per user, touches: [a.py]}}\n"
        f"- {{decision: {RETRY}, holds: four, touches: []}}\n"
        f"- {{decision: {RETRY}, holds: four, touches: [b.py]}}\n", encoding="utf-8")
    lines = pins.check_lines(proj)
    assert len(lines) == 2
    assert f"{cache} (superseded by {rev}: pin the decision in force instead)" in lines[0]
    assert f"{RETRY} (touches is a list of paths or CodeRefs)" in lines[0]
    assert lines[1] == f"warning: notes/pins.yaml pins one decision twice: {RETRY}"
    pins.path_of(proj).write_text("{decision: x}\n", encoding="utf-8")
    assert "a list of pins expected" in pins.check_lines(proj)[0]
    pins.path_of(proj).unlink()
    assert pins.check_lines(proj) == []


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def _repo(path: Path) -> Path:
    path.mkdir(exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "ada@example.org")
    _git(path, "config", "user.name", "Ada")
    _git(path, "config", "core.quotepath", "true")
    return path


def test_review_check_refuses_until_the_body_keeps_the_pin(proj, monkeypatch, tmp_path, capsys):
    pins.add(proj, RETRY, ["src/net.py", "src/café.py"], "retries stay at 4", "2026-11-12")
    repo = _repo(tmp_path / "code")
    (repo / "src").mkdir()
    (repo / "src" / "net.py").write_text("RETRIES = 4\n", encoding="utf-8")
    (repo / "src" / "café.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "src" / "net.py").write_text("RETRIES = 5\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "five")
    head = _git(repo, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(scout, "resolve", lambda args, root: (proj, [], projects.Repo("demo", repo), repo, True))
    touched, blocks = review.pins_gate(repo, base, head, "nothing said")
    assert [t["id"] for t in touched] == [RETRY] and len(blocks) == 1
    review.stamp(head, 1, 1)
    body = tmp_path / "body.md"
    body.write_text("A change.\n", encoding="utf-8")
    args = ["review", "check", head, "--repo", str(repo), "--base", base]
    assert cli.main([*args, "--body", str(body)]) == 1
    out = capsys.readouterr().out
    assert f"pinned: {RETRY} (2026-11-01) holds retries stay at 4 (src/net.py)" in out and "BLOCK" in out
    body.write_text(f"Keeps {RETRY}: the count is a setting now\n", encoding="utf-8")
    assert cli.main([*args, "--body", str(body)]) == 0
    assert cli.main(args) == 0   # without a body: the pins listed, the stamp alone decides
    assert "pinned: " in capsys.readouterr().out
    # no origin/main in this repo: without a body, a note, the stamp still decides (finding 4)
    assert cli.main(["review", "check", head, "--repo", str(repo)]) == 0
    assert "note: the pins could not be read" in capsys.readouterr().out
    (repo / "src" / "café.py").write_text("x = 2\n", encoding="utf-8")   # a quoted path, read with -z (finding 8)
    _git(repo, "commit", "-qam", "accent")
    touched, _ = review.pins_gate(repo, head, "HEAD", None)
    assert touched[0]["hits"] == ["src/café.py"]


def test_a_pr_cannot_drop_its_own_pin_nor_hide_its_reversal(proj, monkeypatch):
    """Finding 5: the pins live in the changed repo: read at the base, the logs at the head."""
    root = _repo(proj.root)
    pins.add(proj, RETRY, ["src/net.py"], "retries stay at 4", "2026-11-12")
    (root / "src").mkdir()
    (root / "src" / "net.py").write_text("RETRIES = 4\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD").strip()
    pins.path_of(proj).write_text("[]\n", encoding="utf-8")   # the PR removes the pin and edits the code
    (root / "src" / "net.py").write_text("RETRIES = 5\n", encoding="utf-8")
    _git(root, "commit", "-qam", "five, unpinned")
    monkeypatch.setattr(scout, "resolve", lambda args, r: (proj, [], projects.Repo("demo", root), root, True))
    touched, blocks = review.pins_gate(root, base, "HEAD", "")
    assert touched[0]["id"] == RETRY and touched[0]["hits"] == ["src/net.py", "pins.yaml"] and blocks
    notes.adr_new(root / "notes" / "decisions.md", "", REVERSAL_FIELDS, day="2026-11-12", reverses=RETRY)
    _git(root, "commit", "-qam", "the reversal")
    touched, blocks = review.pins_gate(root, base, "HEAD", f"Overrides {RETRY}: five retries now")
    assert touched[0]["superseded_by"] and blocks == []


def test_merge_ready_blocks_on_a_pin_and_survives_an_unreadable_one(monkeypatch, tmp_path):
    g = mergeready.Gate(1, "o/r", "a" * 40, "main")
    monkeypatch.setattr(review, "pins_gate", lambda *a: ([{"id": RETRY}], ["it blocks"]))
    mergeready._pins(g, tmp_path, {"body": ""})
    assert g.checks[-1] == {"check": "pins", "ok": False, "detail": "it blocks"}

    def broken(*a):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
    monkeypatch.setattr(review, "pins_gate", broken)
    mergeready._pins(g, tmp_path, {"body": ""})
    assert not g.checks[-1]["ok"] and "could not be read" in g.checks[-1]["detail"]


def test_impact_lists_the_pinned_decisions_in_its_checklist():
    from brain import impact
    rep = impact.Report("demo", "demo", "a" * 40, "origin/main", "worktree", mode="files", files=[{"status": "M"}],
                        pins=[{"id": RETRY, "day": "2026-11-01", "holds": "retries stay at 4", "hits": ["src/net.py"],
                               "since": "", "title": "Retries stay at four"}])
    text = "\n".join(impact.render(rep))
    assert "[ ] pinned decisions this change touches (1): the PR body says Keeps <id> or Overrides <id>: why" in text
    assert f"    {RETRY} (2026-11-01): holds retries stay at 4 (src/net.py)" in text
