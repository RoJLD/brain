"""wi-brain-decision-pins: a decision pinned to the code it governs (brain.pins, docs/pins.md): brain adr pin writes
pins.yaml beside the decision log, brain impact --diff lists the pinned decisions a change touches, brain review
check and brain merge-ready refuse until the PR body keeps or overrides each one, brain check warns on a bad pin.
spec-brain-three-repos §3 no. 3 (TR-2). Fixtures only."""

import subprocess
from pathlib import Path

import pytest
from brain import cli, decisions, pins, projects, review

AT = "2026-11-02T09:00:00Z"
OPTS = ["A: the first", "B: the second"]
LOG = """# Decisions

## 2026-11-01 — Retries stay at four

**Context.** x

**Decision.** four retries.

## 2026-11-02 — The cache is per user

**Context.** y

**Decision.** per user.

## 2026-11-03 — REVERSAL: The cache is per user

**Supersedes.** 2026-11-02 — The cache is per user (`adr-2026-11-02-the-cache-is-per-user`)

**New decision.** per machine.
"""
RETRY = "adr-2026-11-01-retries-stay-at-four"
CACHE = "adr-2026-11-02-the-cache-is-per-user"
REVERSAL = "adr-2026-11-03-reversal-the-cache-is-per-user"


@pytest.fixture
def proj(store):
    root = store.parents[1]
    (root / "notes" / "decisions.md").write_text(LOG, encoding="utf-8", newline="\n")
    pending, _ = decisions.ask(root, title="Pending one", question="?", options=OPTS, why="w", at=AT)
    done, _ = decisions.ask(root, title="Answered one", question="?", options=OPTS, why="w", at=AT)
    decisions.answer(root, done["id"], ["A"], at=AT)
    p = projects.for_root(root)
    p.pending, p.answered = pending["id"], done["id"]
    return p


def test_brain_adr_pin_writes_a_pin_and_never_edits_its_holds(proj, capsys):
    root = str(proj.root)
    assert cli.main(["--root", root, "adr", "pin", RETRY, "--touches", "src/net.py", "--holds", "retries stay at 4",
                     "--date", "2026-11-12"]) == 0
    assert "pin: adr-2026-11-01-retries-stay-at-four pinned (1 touch(es))" in capsys.readouterr().out
    assert cli.main(["--root", root, "adr", "pin", RETRY, "--touches", "code:demo:src/retry.py::backoff"]) == 0
    assert pins.load(proj) == [{"decision": RETRY, "holds": "retries stay at 4",
                                "touches": ["src/net.py", "code:demo:src/retry.py::backoff"], "since": "2026-11-12"}]
    assert cli.main(["--root", root, "adr", "pin", RETRY, "--touches", "x.py", "--holds", "five"]) == 1
    assert "a holds line is never edited" in capsys.readouterr().err
    # a superseded ADR, a pending DDR, an unknown id, a malformed touch: refused
    for ref, touch, why in ((CACHE, "a.py", "superseded by " + REVERSAL), (proj.pending, "a.py", "only an answered"),
                            ("adr-nope", "a.py", "no such ADR"), (REVERSAL, "C:\\x.py", "a path relative")):
        assert cli.main(["--root", root, "adr", "pin", ref, "--touches", touch, "--holds", "h"]) == 1
        assert why in capsys.readouterr().err
    assert cli.main(["--root", root, "adr", "pin", proj.answered, "--touches", "docs/", "--holds", "h"]) == 0
    assert pins.path_of(proj) == proj.root / "notes" / "pins.yaml"


def test_a_change_hits_a_pin_by_file_folder_glob_or_coderef():
    pin = {"touches": ["src/net.py", "docs/", "tests/test_*.py", "code:demo:src/retry.py::backoff",
                       "code:other:src/net.py"]}
    files = {"src/net.py", "docs/a.md", "tests/test_x.py", "src/retry.py"}
    assert pins.hits(pin, files, {"demo"}) == ["src/net.py", "docs/a.md", "tests/test_x.py",
                                              "code:demo:src/retry.py::backoff"]
    ref = "code:demo:src/retry.py::backoff"   # GitNexus said which symbols: only a touched symbol counts
    assert ref not in pins.hits(pin, files, {"demo"}, refs=set(), known={ref})
    assert ref in pins.hits(pin, files, {"demo"}, refs={ref}, known={ref})
    assert ref in pins.hits(pin, files, {"demo"}, refs=set(), known=set())   # a CodeRef the graph lacks: the file
    assert pins.hits(pin, {"README.md"}, {"demo"}) == []


def test_the_pr_body_keeps_or_overrides_each_pinned_decision(proj):
    pins.add(proj, RETRY, ["src/net.py"], "retries stay at 4", "2026-11-12")
    pins.add(proj, REVERSAL, ["src/cache.py"], "the cache is per machine", "2026-11-12")
    touched = pins.touched(proj, {"src/net.py", "src/cache.py"}, {"demo"})
    assert [(t["id"], t["day"], t["hits"]) for t in touched] == [(RETRY, "2026-11-01", ["src/net.py"]),
                                                                 (REVERSAL, "2026-11-03", ["src/cache.py"])]
    assert pins.verdict(proj, touched, None)[0].startswith("2 pinned decision(s) touched")
    blocks = pins.verdict(proj, touched, "A change.\n")
    assert len(blocks) == 2 and f"says neither Keeps {RETRY}" in blocks[0]
    body = f"Done.\n\n- Keeps `{RETRY}`\n- Overrides {REVERSAL}\n"
    assert pins.verdict(proj, touched, body) == [f"Overrides {REVERSAL}: the reason is missing"]
    body = f"Keeps {RETRY}\nOverrides {REVERSAL}: the cache moves to the server\n"
    assert pins.verdict(proj, touched, body) == [f"Overrides {REVERSAL}: no REVERSAL ADR supersedes it (brain adr "
                                                 f"new --reverses {REVERSAL})"]
    with (proj.root / "notes" / "decisions.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## 2026-11-12 — REVERSAL: Server cache\n\n**Supersedes.** 2026-11-03 — x (`{REVERSAL}`)\n")
    assert pins.verdict(proj, touched, body) == []
    assert pins.answers("keeps adr-x\n* Overrides `adr-y`: because\n") == {"adr-x": ("keeps", ""),
                                                                         "adr-y": ("overrides", "because")}


def test_brain_check_warns_on_a_pin_it_cannot_hold(proj):
    (proj.root / "notes" / "pins.yaml").write_text(
        f"- {{decision: {CACHE}, holds: per user, touches: [a.py]}}\n"
        f"- {{decision: {RETRY}, holds: four, touches: []}}\n"
        f"- {{decision: {RETRY}, holds: four, touches: [b.py]}}\n", encoding="utf-8")
    lines = pins.check_lines(proj)
    assert len(lines) == 2
    assert f"{CACHE} (superseded by {REVERSAL}: pin the REVERSAL instead)" in lines[0]
    assert f"{RETRY} (touches is a list of paths or CodeRefs)" in lines[0]
    assert lines[1] == f"warning: notes/pins.yaml pins one decision twice: {RETRY}"
    (proj.root / "notes" / "pins.yaml").write_text("{decision: x}\n", encoding="utf-8")
    assert "a list of pins expected" in pins.check_lines(proj)[0]
    (proj.root / "notes" / "pins.yaml").unlink()
    assert pins.check_lines(proj) == []


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def test_review_check_refuses_until_the_body_keeps_the_pin(proj, monkeypatch, tmp_path, capsys):
    pins.add(proj, RETRY, ["src/net.py"], "retries stay at 4", "2026-11-12")
    repo = tmp_path / "code"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "ada@example.org")
    _git(repo, "config", "user.name", "Ada")
    (repo / "src").mkdir()
    (repo / "src" / "net.py").write_text("RETRIES = 4\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "src" / "net.py").write_text("RETRIES = 5\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "five")
    head = _git(repo, "rev-parse", "HEAD").strip()
    from brain import scout
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
    assert review.pins_gate(repo, base, base, None) == ([], [])


def test_impact_lists_the_pinned_decisions_in_its_checklist():
    from brain import impact
    rep = impact.Report("demo", "demo", "a" * 40, "origin/main", "worktree", mode="files", files=[{"status": "M"}],
                        pins=[{"id": RETRY, "day": "2026-11-01", "holds": "retries stay at 4", "hits": ["src/net.py"],
                               "since": "", "title": "Retries stay at four"}])
    text = "\n".join(impact.render(rep))
    assert "[ ] pinned decisions this change touches (1): the PR body says Keeps <id> or Overrides <id>: why" in text
    assert f"    {RETRY} (2026-11-01): holds retries stay at 4 (src/net.py)" in text
