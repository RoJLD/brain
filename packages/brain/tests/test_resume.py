import io
import json
import os
import subprocess
from datetime import datetime, timezone

from brain import cli, decisions, projects, resume

from conftest import run_git

NOW = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)


def _registry(tmp_path, monkeypatch, root, extra=""):
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n{extra}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return reg


def _project(tmp_path, monkeypatch, store):
    """The store fixture made a project: a milestone, a frontier, a waiting item, an open question, a journal, DDRs
    and a hand-over notes folder."""
    root = store.parents[1]
    with open(store / "nodes" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("- {id: wi-three, type: WorkItem, status: todo, title: \"Third\", props: {priority: P1}}\n"
                 "- {id: wi-four, type: WorkItem, status: done, title: \"Fourth\", props: {priority: P1}}\n"
                 "- {id: wi-five, type: WorkItem, status: todo, title: \"Fifth\", props: {priority: P2}}\n"
                 "- {id: wi-six, type: WorkItem, status: todo, title: \"Sixth\",\n"
                 "   props: {priority: P1, open: \"Ada picks the store\"}}\n"
                 "- {id: ms-y, type: Milestone, status: reached, title: \"Milestone Y\"}\n")
    with open(store / "edges" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("- {from: wi-three, to: wi-two, type: depends_on}\n"
                 "- {from: wi-six, to: wi-four, type: depends_on}\n"
                 "- {from: wi-one, to: ms-x, type: part_of}\n"
                 "- {from: wi-four, to: ms-x, type: part_of}\n")
    (root / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
    (root / "notes" / "journal.md").write_text(
        "# Journal\n\n## 2026-11-01 — Old\n\n- old\n\n## 2026-11-02 — Today\n\n"
        + "".join(f"- line {i}\n" for i in range(1, 6)) + "- line 6 wraps\n  over two lines\n", encoding="utf-8")
    decisions.ask(root, title="Pick a store", question="Which?", options=["A: first", "B: second"], why="simplest",
                  at="2026-11-01T08:00:00Z", blocking=True)
    decisions.ask(root, title="Pick a name", question="Which?", options=["X", "Y"], why="short",
                  at="2026-11-01T08:00:00Z")
    decisions.answer(root, "pick-a-name", ["Y"], at="2026-11-01T09:00:00Z")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("# Third, half done\n\nLeft: wi-three (tests).\n", encoding="utf-8")
    (notes / "b.md").write_text("# Fourth, done\n\nwi-four merged.\n", encoding="utf-8")
    (notes / "c.txt").write_text("wi-three\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_NOTES", str(notes))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    _registry(tmp_path, monkeypatch, root)
    return projects.get("demo")


def test_pack_is_ordered_stable_to_volatile_and_deterministic(tmp_path, monkeypatch, store):
    p = _project(tmp_path, monkeypatch, store)
    text = resume.build(p, offline=True, now=NOW)
    assert text == resume.build(p, offline=True, now=NOW)  # same inputs, same bytes
    heads = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert [h.split(" (")[0].split(":")[0] for h in heads] == [
        "# Resume pack — demo", "## Milestones", "## Work", "## Decisions", "## Git", "## Journal",
        "## Hand-over notes that name an open item", "## Now"]
    assert "this project: CLAUDE.md" in text
    assert "- ms-x 1/2 done: Milestone X" in text and "Reached: ms-y" in text
    work = text.split("## Work")[1].split("## Decisions")[0]
    # wi-one P0 then wi-six P1 (its prerequisite is done); wi-five is P2; wi-three waits on wi-two (doing)
    assert work.index("- wi-one [P0]") < work.index("- wi-six [P1]") and "wi-five" not in work
    assert "Startable P0/P1 (2 of the 3 on the frontier):" in work
    assert "- wi-two [-]: Second" in work and "- wi-three [P1] after wi-two: Third" in work
    dec = text.split("## Decisions")[1].split("## Git")[0]
    assert dec.index("pick-a-store [blocking] asked 2026-11-01") < dec.index("Answered, to integrate")
    assert "recommended: A" in dec and "pick-a-name: Y (Pick a name)" in dec
    assert "- wi-six: Ada picks the store" in dec
    assert "Open PRs: not read (--offline)." in text
    assert "Last entry: 2026-11-02 — Today (its last 4 of 6 bullets)" in text
    assert "- line 1\n" not in text and "- line 3\n" in text and "  over two lines\n" in text
    notes = text.split("## Hand-over notes")[1].split("## Now")[0]
    assert "a.md" in notes and "[wi-three]" in notes and "b.md" not in notes and "c.txt" not in notes
    assert text.endswith("## Now\nGenerated 2026-11-02 09:30 UTC (not a git checkout).\nStacks: none declared.\n")
    # nothing that moves with the clock before the last section
    assert "2026-11-02 09:30" not in text.split("## Now")[0]


def test_budget_cuts_from_the_volatile_end(tmp_path, monkeypatch, store):
    p = _project(tmp_path, monkeypatch, store)
    full = resume.build(p, offline=True, now=NOW, budget=0)
    budget = resume.tokens(full) - 60
    cut = resume.build(p, offline=True, now=NOW, budget=budget)
    assert resume.tokens(cut) <= budget
    assert "## Hand-over notes" not in cut and "## Milestones" in cut and "## Decisions" in cut
    assert cut.startswith("# Resume pack — demo") and cut.endswith("Stacks: none declared.\n")
    assert "line(s) dropped from the volatile end to fit --budget" in cut.split("## Now")[0].split("## Cut")[1]
    tiny = resume.build(p, offline=True, now=NOW, budget=1)  # only the header and the last section are left
    assert [ln for ln in tiny.splitlines() if ln.startswith("#")] == [
        "# Resume pack — demo (root)", "## Cut", "## Now"]
    assert not any(block.endswith(":") for block in cut.split("\n\n"))  # no sub-heading left without its rows


def test_open_prs_and_worktree_branches(tmp_path, monkeypatch, git_repo):
    monkeypatch.setattr(resume.shutil, "which", lambda name: None)
    assert resume.open_prs(git_repo) == (None, "gh not found")
    monkeypatch.setattr(resume.shutil, "which", lambda name: "gh")
    rows = [{"number": 9, "title": "Later", "headRefName": "b", "isDraft": True},
            {"number": 3, "title": "First", "headRefName": "a", "isDraft": False}]
    real = subprocess.run

    def fake(argv, **kw):
        if argv[0] == "gh":
            return subprocess.CompletedProcess(argv, 0, json.dumps(rows), "")
        return real(argv, **kw)
    monkeypatch.setattr(resume.subprocess, "run", fake)
    prs, why = resume.open_prs(git_repo)
    assert [p["number"] for p in prs] == [3, 9] and why == ""
    monkeypatch.setattr(resume.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 1, "", "warn\nerror connecting to api.github.com\n"))
    assert resume.open_prs(git_repo) == (None, "gh: error connecting to api.github.com")
    monkeypatch.setattr(resume.subprocess, "run", real)
    run_git(git_repo, "worktree", "add", "-q", "-b", "feat/x", str(git_repo.parent / "wt"))
    assert resume.worktree_branches(git_repo) == ["feat/x"]


def test_git_section_with_prs_and_head(tmp_path, monkeypatch, git_repo):
    (git_repo / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    _registry(tmp_path, monkeypatch, git_repo)
    monkeypatch.setenv("BRAIN_NOTES", "")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    monkeypatch.setattr(resume, "open_prs", lambda root: ([{"number": 4, "title": "Add X", "headRefName": "feat/x",
                                                            "isDraft": True}], ""))
    text = resume.build(projects.get("demo"), now=NOW)
    head = run_git(git_repo, "rev-parse", "--short", "HEAD").strip()
    assert "Open PRs (1):\n- #4 feat/x [draft]: Add X\n" in text
    assert f"Generated 2026-11-02 09:30 UTC at {head} on main.\n" in text and text.endswith(
        "Session: transcript s-1 (the ledger, the records, brain sessions).\n")
    assert "Hand-over notes that name an open item (newest first)\nNone: no notes folder found." in text


def test_a_nested_claude_does_not_print_its_outer_sessions_app_id(tmp_path, monkeypatch, store):
    """Review of #34, finding 50: a ``claude`` started from a desktop session's shell inherits its
    CLAUDE_CODE_HOST_SESSION_ID; the pack's Session line names that app id only when the app's file of it names this
    session's transcript, so SendMessage is not pointed at the outer session."""
    from brain import sessions
    p = _project(tmp_path, monkeypatch, store)
    host = "local_22222222-2222-4222-8222-222222222222"
    d = tmp_path / "appdata" / "Claude-Data" / "claude_t" / "claude-code-sessions" / "acct" / "org"
    d.mkdir(parents=True)
    (d / f"{host}.json").write_text(json.dumps({"sessionId": host, "cliSessionId": "s-outer"}), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv(sessions.HOST_ENV, host)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-nested")
    text = resume.build(p, offline=True, now=NOW)
    assert host not in text and text.endswith(
        "Session: transcript s-nested (the ledger, the records, brain sessions).\n")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-outer")  # the outer session itself keeps its app id
    assert f"Session: app {host} (SendMessage" in resume.build(p, offline=True, now=NOW)


def test_worktree_of_a_registered_checkout_keeps_the_project_name(tmp_path, monkeypatch, git_repo):
    (git_repo / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    _registry(tmp_path, monkeypatch, git_repo)
    wt = tmp_path / "wt"
    run_git(git_repo, "worktree", "add", "-q", "-b", "feat/y", str(wt))
    p = resume.project_for(wt)
    assert p.name == "demo" and p.root == wt and p.journal == wt / "notes" / "journal.md"
    assert resume.project_for(tmp_path).name == tmp_path.name


def test_session_start_line(tmp_path, monkeypatch, store, capsys):
    p = _project(tmp_path, monkeypatch, store)
    root = store.parents[1]
    assert resume.announce(tmp_path) == ""  # not in a project
    line = resume.announce(root / "notes")
    assert line.startswith("Resume pack of demo: none written. `brain resume` prints") and "\n" not in line
    f = resume.write("demo", resume.build(p, offline=True, now=NOW))
    assert f == resume.pack_path("demo") and f.parent.parent == resume.paths.brain_home()
    line = resume.announce(root, now=f.stat().st_mtime + 2 * 3600 + 5)
    assert line.startswith("Resume pack of demo: written 2 h ago (") and "tokens)" in line
    assert "## Milestones" not in line  # never the pack itself
    assert resume.age(30) == "less than a minute" and resume.age(3 * 86400) == "3 days"
    resume.hook_main(["SessionStart"], stdin=io.StringIO(json.dumps({"cwd": str(root)})))
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert out["hookSpecificOutput"]["additionalContext"].startswith("Resume pack of demo: written")
    resume.hook_main(["SessionStart"], stdin=io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    resume.hook_main(["SessionStart"], stdin=io.StringIO("not json"))  # never fails, logs instead
    assert capsys.readouterr().out == ""
    assert "resume-announce" in (resume.paths.ledger_dir() / "errors.log").read_text(encoding="utf-8")


def test_cli_resume(tmp_path, monkeypatch, store, capsys):
    _project(tmp_path, monkeypatch, store)
    other = tmp_path / "other"
    (other / "notes" / "graph").mkdir(parents=True)
    _registry(tmp_path, monkeypatch, store.parents[1], f"other: {{root: {other.as_posix()}}}\n")
    assert cli.main(["--project", "demo", "resume", "--offline", "--write"]) == 0
    out = capsys.readouterr()
    assert out.out.startswith("# Resume pack — demo") and "resume: demo -> " in out.err
    assert resume.pack_path("demo").read_text(encoding="utf-8") == out.out
    assert cli.main(["resume", "--project", "demo", "--offline", "--budget", "1"]) == 0
    assert "## Milestones" not in capsys.readouterr().out
    assert cli.main(["resume", "--all", "--offline"]) == 0
    text = capsys.readouterr().out
    assert "# Resume pack — demo" in text and "# Resume pack — other" in text
    assert "## Milestones" in text.split("# Resume pack — other")[0]
    monkeypatch.chdir(store.parents[1] / "notes")
    assert cli.main(["resume", "--offline"]) == 0
    assert capsys.readouterr().out.startswith("# Resume pack — demo")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": os.getcwd()})))
    assert cli.main(["resume", "--hook"]) == 0
    assert "Resume pack of demo: written" in capsys.readouterr().out
