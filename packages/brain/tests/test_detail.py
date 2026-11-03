"""wi-brain-tui-detail and wi-brain-tui-actions: a row's detail (brain.detail), its links and its actions, run as
the owner's (Ada's, the tests' owner) and logged; brain tui --detail."""

import json
import subprocess
import sys

import pytest

from brain import cli, decisions, detail, paths, projects, queue, status

AT = "2026-11-02T10:00:00Z"


@pytest.fixture
def demo(store):
    """The store's project, with a spec section, an ADR, a code file and a DDR asked of Ada."""
    root = store.parents[1]
    (root / "docs").mkdir()
    (root / "docs" / "x.md").write_text("# Spec X\n\n## 2.1 The section\n\ntext\n\n## 3 Ce qui reste à décider\n",
                                        encoding="utf-8")
    (root / "notes" / "decisions.md").write_text("# Decisions\n\n## 2026-10-30 — X\n\nbody\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
    with open(store / "edges" / "work.yaml", "a", encoding="utf-8") as fh:
        fh.write("- {from: wi-one, to: adr-2026-10-30-x, type: decided_by}\n"
                 "- {from: wi-one, to: ms-x, type: part_of}\n- {from: wi-two, to: ms-x, type: part_of}\n"
                 "- {from: wi-two, to: wi-one, type: depends_on}\n"
                 "- {from: wi-one, to: \"code:demo:src/x.py\", type: implemented_by}\n")
    p = projects.Project("demo", root, stores=[store])
    ddr, _ = decisions.ask(root, title="Pick a layout", question="Grid or tabs?", at=AT, why="both views",
                           options=["Grid and tabs: an overview and a tab per panel", "Tabs only", "-x odd"],
                           items=["wi-one"], specs=["spec-x 2.1"], project="demo")
    return p, ddr["id"]


def _entry(p, ref):
    data = queue.build(p, transcripts=False, with_graph=False)
    return next(e for e in data["entries"] if e["id"] == ref)


def test_a_decision_shows_its_options_links_and_answer(demo):
    p, ref = demo
    st = status._store(p)
    d = detail.of("queue", {**_entry(p, ref), "project": "demo"}, project=p, store=st)
    heads = [h for h, _ in d["sections"]]
    assert d["title"] == "Pick a layout" and heads[:2] == [ref, "Question"]
    assert {"Options", "Why the recommendation", "Linked", "Unblocks (3)", "How"} <= set(heads)
    opts = dict(d["sections"])["Options"]
    assert opts[0] == "1. Grid and tabs (recommended): an overview and a tab per panel" and opts[-1].startswith("Other")
    assert dict(d["sections"])["Unblocks (3)"] == ["ms-x [pending]: Milestone X", "wi-one [todo]: First: with a colon, "
                                                   "and a comma", "wi-two [doing]: Second"]
    files = {x["label"]: x for x in d["links"] if x["kind"] == "file"}
    assert files[f"the DDR {ref}.yaml"]["path"].endswith(f"{ref}.yaml")
    assert files["spec spec-x §2.1"]["line"] == 3  # the spec at its section
    assert {x["id"] for x in d["links"] if x["kind"] == "item"} == {"ms-x", "wi-one", "wi-two"}
    (a,) = d["actions"]
    assert (a.kind, a.multi, a.cwd) == ("answer", False, p.root)
    root = str(p.root)
    assert detail.answer_steps(a, ["Grid and tabs"]) == [
        ["brain", "--root", root, "decision", "answer", ref, "Grid and tabs", "--via", "tui", "--by", "Ada"]]
    assert detail.answer_steps(a, ["-x odd"], notes="  my\nnote ")[0][6:] == ["3", "--notes", "my note", "--via", "tui",
                                                                            "--by", "Ada"]  # by number
    assert detail.answer_steps(a, [], other="neither")[0][6:8] == ["--other", "neither"]
    with pytest.raises(ValueError):
        detail.answer_steps(a, [])
    with pytest.raises(ValueError):
        detail.answer_steps(a, ["Grid and tabs", "Tabs only"])  # one choice only
    text = "\n".join(detail.lines(d))
    assert "Actions (in the TUI, after a confirmation)" in text and "decision answer" in text


def test_an_action_offers_done_and_apply_with_its_exact_command(demo):
    p, _ = demo
    ddr, _, _ = queue.add(p.root, kind="action", title="Install the TUI extra",
                          what=r"Run `.\install.ps1 -Apply -Extras tui` on box1, then `git push` nothing", at=AT,
                          project="demo")
    d = detail.of("queue", {**_entry(p, ddr["id"]), "project": "demo"}, project=p, store=status._store(p))
    assert [a.kind for a in d["actions"]] == ["done", "apply"]
    done, apply = d["actions"]
    root = str(p.root)
    assert done.steps == [["brain", "--root", root, "queue", "done", ddr["id"]]] and done.note
    assert detail.done_steps(done, "did it once") == [done.steps[0] + ["--note", "did it once"]]
    assert apply.steps == [[r".\install.ps1", "-Apply", "-Extras", "tui"],
                           ["brain", "--root", root, "queue", "done", ddr["id"], "--note",
                            r"applied in brain tui: .\install.ps1 -Apply -Extras tui"]]
    assert apply.handover and not done.handover  # an install: run by a window once the cockpit closes (INST-2)
    assert "What" in dict(d["sections"])
    answered = detail.ddr(ddr["id"], p)  # once answered, no action is offered
    decisions.answer(p.root, ddr["id"], [], other="done", at=AT)
    assert answered["actions"] and not detail.ddr(ddr["id"], p)["actions"]
    assert "Answer (answered)" in dict(detail.ddr(ddr["id"], p)["sections"])


def test_a_denied_call_is_marked_done_and_its_grant_named():
    e = {"id": "perm-abc1234567", "kind": "permission", "source": "denial", "project": queue.OUTSIDE,
         "title": "Bash: git push", "detail": "permission rule", "count": 2, "last": "2026-11-02",
         "how": "grant a narrow allow rule", "unblocks": 0, "unblocked": []}
    d = detail.of("queue", e)
    (a,) = d["actions"]
    assert a.kind == "done" and a.steps == [["brain", "--root", str(detail.HERE), "queue", "done", e["id"]]]
    assert any("brain permissions grant perm-abc1234567" in x for x in dict(d["sections"])["How"])
    assert "2 time(s), last 2026-11-02" in dict(d["sections"])["The call"]
    prop = {"id": "wi-x:needs", "kind": "action", "source": "prop:needs", "project": "demo", "item": "wi-x",
            "title": "Ada runs `brain permissions render --level user`", "unblocks": 0}
    p = projects.Project("demo", detail.HERE)
    (apply,) = detail.of("queue", prop, project=p)["actions"]  # an item prop: the model clears it, no done
    assert apply.kind == "apply" and apply.steps == [["brain", "permissions", "render", "--level", "user"]]


def test_install_named_without_backquotes_is_an_apply_with_its_plan():
    seed = (r"Once merged and pulled: 1. cd D:\work\brain; git pull --ff-only. 2. .\install.ps1 (the plan: "
            r"allow ...). 3. .\install.ps1 -Apply. 4. brain permissions: the user file. 5. brain queue done <this id>.")
    assert detail.commands(seed) == [[r".\install.ps1", "-Apply"], [r".\install.ps1"]]  # the apply first
    assert detail.commands("needs install.ps1 -Apply -Extras tui, Ada's to run") == [
        ["install.ps1", "-Apply", "-Extras", "tui"]]
    assert detail.commands("reinstall.ps1 -Apply") == []
    assert detail.preview([r".\install.ps1", "-Apply", "-Extras", "tui"]) == [r".\install.ps1", "-Extras", "tui"]
    assert detail.preview(["brain", "permissions", "render", "--write"]) is None


def test_commands_split_and_shown():
    assert detail.commands("Run `brain permissions render --write` then `git push` and `brain x`") == [
        ["brain", "permissions", "render", "--write"], ["brain", "x"]]
    assert detail.commands(r".\install.ps1 -Apply -Extras tui; then check") == [
        [r".\install.ps1", "-Apply", "-Extras", "tui"]]
    assert detail.commands("Rotate the key", "", None) == []
    assert detail.split('brain decision answer x "Grid and tabs" \'a b\'') == [
        "brain", "decision", "answer", "x", "Grid and tabs", "a b"]
    assert detail.shown(["brain", "decision", "answer", "Grid and tabs", "--other", "it's", ""]) == (
        'brain decision answer "Grid and tabs" --other "it\'s" ""')


def test_an_item_shows_its_spec_adrs_pr_code_and_neighbours(demo, monkeypatch):
    p, _ = demo
    st = status._store(p)
    st.nodes["wi-one"]["props"]["pr"] = "demo #7"
    monkeypatch.setitem(detail._OWNERS, str(p.root), detail._REPO_RE.search("git@github.com:RoJLD/demo.git"))
    d = detail.item("wi-one", p, st, row={"unblocks": 2, "since": "2026-10-30"})
    s = dict(d["sections"])
    assert d["sections"][0] == ("wi-one", ["WorkItem todo, priority P0, milestone ms-x", "unblocks 2, idea 2026-10-30"])
    assert s["Spec"] == ["spec-x [active]: Spec X"] and s["ADRs (decided_by)"] == ["adr-2026-10-30-x [active]: X"]
    assert s["PR"] == ["demo #7"] and s["Code and tests"] == ["code:demo:src/x.py"]
    assert s["Waiting on it"] == ["wi-two [doing]: Second"] and "theme: 3.1" in s["Props"]
    links = {x["label"]: x for x in d["links"]}
    assert links["ADR adr-2026-10-30-x"]["line"] == 3 and links["spec spec-x"]["line"] == 1
    assert links["PR demo #7"]["url"] == "https://github.com/RoJLD/demo/pull/7"
    assert links["code src/x.py"]["path"].endswith("x.py")
    assert detail.pr_url("https://github.com/o/r/pull/3 merged", p) == "https://github.com/o/r/pull/3"
    assert detail.pr_url("not a pr", p) == ""


def test_milestone_session_and_alert(demo, brain_home):
    p, _ = demo
    st = status._store(p)
    d = detail.milestone("ms-x", p, st, row={"done": 0, "items": 2, "project": "demo"})
    assert dict(d["sections"])["Trigger"] == ["x: y, z"]
    assert dict(d["sections"])["todo (1)"] == ["wi-one [todo]: First: with a colon, and a comma"]
    assert dict(d["sections"])["doing (1)"] == ["wi-two [doing]: Second"] and len(d["links"]) == 2
    (paths.sessions_dir()).mkdir(parents=True)
    (paths.sessions_dir() / "s1.plan.json").write_text(json.dumps({"session_id": "s1", "steps": [
        {"content": "Read", "status": "completed"}, {"content": "Write", "status": "in_progress"}]}), encoding="utf-8")
    row = {"session_id": "s1", "state": "running", "project": "demo", "age_s": 30, "folder": str(p.root),
           "branch": "b", "model": "claude-opus-5-5", "effort": "high", "context": 1000, "budget": 4000,
           "output_tokens": 10, "cost_usd": 1.5, "title": "T", "last_write": AT}
    s = dict(detail.session(row)["sections"])
    assert s["Plan (2/2 Write; from the hook)"] == ["[x] 1. Read", "[>] 2. Write"]
    assert s["Where"] == [f"folder: {p.root}", "branch: b"] and "$1.50 at API prices" in s["Model"][0]
    a = detail.alert({"level": "warn", "project": "demo", "key": "stack:x", "message": "x is down " * 30,
                      "source": "stacks", "since": AT})
    assert dict(a["sections"])["Message"][0].startswith("x is down x is down") and a["actions"] == []
    assert detail.find({"alerts": {"projects": [{"project": "demo", "alerts": [{"key": "stack:x"}]}]}},
                       "stack:x")[0] == "alerts"


def test_anchor_line(tmp_path):
    f = tmp_path / "s.md"
    f.write_text("# Title\n\n### 4.6 Le détail (drill-down) — P1\n\n## 10. Les réponses d'Ada\n\n"
                 "## 2026-11-02 — Le cockpit : un sélecteur de projet, des filtres\n", encoding="utf-8")
    assert detail.anchor_line(f, "4.6") == 3 and detail.anchor_line(f, "10") == 5
    assert detail.anchor_line(f, "46-le-détail-drill-down--p1") == 3  # GitHub's anchor
    assert detail.anchor_line(f, "2026-11-02-le-cockpit-un-s-lecteur-de") == 7  # the engine's, cut
    assert detail.anchor_line(f, "top") == 1 and detail.anchor_line(f, "nowhere") is None
    assert detail.anchor_line(tmp_path / "gone.md", "x") is None


def test_opener_picks_the_editor(monkeypatch):
    x = {"kind": "file", "path": "f.md", "line": 3}
    assert detail.opener(x, {"EDITOR": "code --wait"}) == (["code", "--wait", "-g", "f.md:3"], False)
    assert detail.opener(x, {"EDITOR": "vim"}) == (["vim", "+3", "f.md"], True)
    assert detail.opener({**x, "line": None}, {"EDITOR": "notepad"}) == (["notepad", "f.md"], True)
    monkeypatch.setattr(detail.shutil, "which", lambda name: None)
    assert detail.opener(x, {}) == (None, False)
    monkeypatch.setattr(detail.shutil, "which", lambda name: "/bin/code")
    assert detail.opener(x, {}) == (["/bin/code", "-g", "f.md:3"], False)


def _done(code=0, out="ok"):
    return subprocess.CompletedProcess([], code, out, "")


def test_run_logs_each_step_as_robins_and_stops_at_a_failure(tmp_path, brain_home):
    a = detail.Action("apply", "Apply", "demo", "ddr-x", tmp_path, steps=[["brain", "x"], ["brain", "y"]])
    calls = []

    def runner(argv, **kw):
        calls.append((argv, kw["cwd"]))
        return _done(1 if argv[-1] == "x" else 0, "token=ghp_" + "a" * 36 + "\nfailed")
    res = detail.run(a, a.steps, runner=runner, env={})
    assert [r["exit"] for r in res] == [1] and calls == [([sys.executable, "-m", "brain", "x"], str(tmp_path))]
    (log,) = paths.ledger_dir().glob("cockpit-*.jsonl")
    (line,) = log.read_text(encoding="utf-8").splitlines()
    row = json.loads(line)
    assert {k: row[k] for k in ("event", "action", "by", "via", "project", "id", "command", "exit")} == {
        "event": "tui-action", "action": "apply", "by": "Ada", "via": "tui", "project": "demo", "id": "ddr-x",
        "command": "brain x", "exit": 1}
    assert "ghp_" not in row["output"] and "failed" in row["output"]  # secrets dropped
    assert "failed (exit 1): brain x" in detail.summary(res)
    with pytest.raises(PermissionError):
        detail.run(a, a.steps, runner=runner, env={"CLAUDECODE": "1"})  # a session's shell: refused
    assert detail.refused({"CLAUDECODE": "1"}) and not detail.refused({})
    with pytest.raises(ValueError):
        detail.argv(["git", "push"], tmp_path)
    (tmp_path / "install.ps1").write_text("", encoding="utf-8")
    assert detail.argv([r".\install.ps1", "-Apply"], tmp_path)[-2:] == [str(tmp_path / "install.ps1"), "-Apply"]


def test_argv_runs_the_installer_the_brain_declares(tmp_path, monkeypatch):
    """wi-brain-tui-apply-reload (INST-1): the brain's config.json engine.installer, whatever its name, runs from the
    brain's root; another script of that folder does not."""
    cfg = {"v": 1, "identity": {"owner": "Ada", "kind": "person"},
           "engine": {"repo": "ada/engine", "pin": "v0.2.3", "installer": "setup/bootstrap.ps1"}}
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "setup").mkdir()
    (tmp_path / "setup" / "bootstrap.ps1").write_text("", encoding="utf-8")
    (tmp_path / "setup" / "other.ps1").write_text("", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "config.json"))
    words = detail.argv(["setup/bootstrap.ps1", "-Apply"], tmp_path)
    assert words[1:] == ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp_path / "setup" / "bootstrap.ps1"),
                         "-Apply"]
    with pytest.raises(ValueError):
        detail.argv(["setup/other.ps1"], tmp_path)


def test_run_answers_a_decision_for_real(demo, monkeypatch):
    p, ref = demo
    monkeypatch.delenv("CLAUDECODE", raising=False)
    (a,) = detail.of("queue", {**_entry(p, ref), "project": "demo"}, project=p, store=status._store(p))["actions"]
    res = detail.run(a, detail.answer_steps(a, ["Tabs only"], notes="from the test"))
    assert res[0]["exit"] == 0, res[0]["output"]
    got = decisions.find(p.root, ref)[1]
    assert got["status"] == "answered" and got["answer"]["choices"] == ["Tabs only"]
    assert (got["answer"]["via"], got["answer"]["by"], got["answer"]["notes"]) == ("tui", "Ada", "from the test")


def test_brain_tui_detail_prints_a_row_or_a_node(demo, capsys):
    p, ref = demo
    assert cli.main(["--root", str(p.root), "tui", "--detail", ref, "--quick"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Pick a layout") and "1. Grid and tabs (recommended)" in out
    assert cli.main(["--root", str(p.root), "tui", "--detail", "wi-two", "--quick", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == "wi-two" and data["actions"] == []
    assert cli.main(["--root", str(p.root), "tui", "--detail", "ms-x", "--quick"]) == 0
    assert capsys.readouterr().out.startswith("Milestone X")
    assert cli.main(["--root", str(p.root), "tui", "--detail", "nothing-here", "--quick"]) == 1
    assert "no row, DDR, item or milestone" in capsys.readouterr().err


def test_an_actions_own_command_and_brain_queue_apply(demo, monkeypatch, capsys):
    p, _ = demo
    with pytest.raises(queue.QueueError):
        queue.add(p.root, kind="action", title="T", what="w", at=AT, command="git push --force")
    ddr, _, _ = queue.add(p.root, kind="action", title="Render the user rules", what="see the plan first", at=AT,
                          command="brain  permissions render --level user", cwd="sub", project="demo")
    assert (ddr["command"], ddr["cwd"]) == ("brain permissions render --level user", "sub")
    e = {**_entry(p, ddr["id"]), "project": "demo"}
    assert e["command"] == ddr["command"] and e["how"].startswith(f"brain queue apply {ddr['id']}")
    d = detail.of("queue", e, project=p)
    apply = next(a for a in d["actions"] if a.kind == "apply")
    assert apply.steps[0] == ["brain", "permissions", "render", "--level", "user"] and apply.cwd == p.root / "sub"
    assert dict(d["sections"])["Command"] == ["brain permissions render --level user (in sub)"]
    ran = []
    monkeypatch.setattr(detail, "run", lambda a, steps: ran.append(steps) or [
        {"command": detail.shown(s), "exit": 0, "seconds": 0.1, "output": "fine"} for s in steps])
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert cli.main(["--root", str(p.root), "queue", "apply", ddr["id"]]) == 1  # the owner said no: nothing run
    assert not ran and "nothing run" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert cli.main(["--root", str(p.root), "queue", "apply", ddr["id"]]) == 0
    assert ran[0][0] == apply.steps[0] and ran[0][1][-1] == (
        "applied in brain queue apply: brain permissions render --level user")
    assert apply.steps[1][-1] == "applied in brain tui: brain permissions render --level user"
    out = capsys.readouterr().out
    assert "$ brain permissions render --level user" in out and "ok in 0.1 s" in out
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["--root", str(p.root), "queue", "apply", ddr["id"]]) == 1  # a session's shell: refused
    assert "the actions are Ada's" in capsys.readouterr().err
    other, _, _ = queue.add(p.root, kind="action", title="Rotate the key", what="by hand", at=AT, project="demo")
    assert cli.main(["--root", str(p.root), "queue", "apply", other["id"]]) == 1
    assert "names no command to apply" in capsys.readouterr().err
