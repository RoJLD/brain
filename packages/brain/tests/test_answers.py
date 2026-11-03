"""The answers' lane (wi-brain-answers-lane): the capture ties each answer to its DDR, --batch is strict and reads a
BOM, an agent's session never records a relayed answer, --captured records a batch in one PR with its merges."""

import io
import json
import shutil
import subprocess

import pytest
import yaml
from conftest import GIT_ENV, run_git

from brain import answers, batch, capture, cli, decisions, graph, projects, records

AT = "2026-11-01T09:00:00Z"
LONG = "Le mécanisme dans le moteur public, les règles de plateforme lisibles par chaque locataire"
SHORT = "Le mécanisme dans le moteur public"


def _root(store):
    return store.parents[1]


def _ask(root, title, question, options, **kw):
    return decisions.ask(root, title=title, question=question, options=list(options), why="simplest", at=AT,
                         project="demo", **kw)[0]


def _demo(store):
    root = _root(store)
    _ask(root, "PLAT-5 — What is public?", "Qu'est-ce qui est public de la plateforme ?",
         [f"{LONG}:: the mechanism open", "Everything private: closed"])
    _ask(root, "Hosts", "Which hosts?", ["Alpha: a", "Beta, gamma: b", "Delta"], multi=True)
    _ask(root, "Lone question", "Alone?", ["Yes: go", "No: wait"])
    return root


def _status(root, ref):
    return decisions.find(root, ref)[1]


def _project(root):
    return projects.Project(name="demo", root=root, stores=[root / "notes" / "graph"])


def _batches(root):
    """What brain decision batch prints for the question tool, remembered as the command does."""
    data = batch.build(_project(root))
    answers.remember("demo", root, data["batches"], at=AT)
    return data["batches"]


def _hook(questions, replies, notes=None, sid="s-1", tuid="toolu_01ABCDEFGH"):
    payload = {"session_id": sid, "tool_name": "AskUserQuestion", "tool_use_id": tuid,
               "tool_input": {"questions": questions},
               "tool_response": {"questions": questions, "answers": replies,
                                 "annotations": {q: {"notes": n} for q, n in (notes or {}).items()}}}
    return capture.main(["post-tool-use"], stdin=io.StringIO(json.dumps(payload)))


def _ledger(home, name):
    return [json.loads(line) for f in sorted((home / "ledger").glob(f"{name}-*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def registry(tmp_path, monkeypatch, store):
    root = _demo(store)
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)
    return root


# --- the two failures: #139 (a shortened label stored as free text), #146 (a BOM wrote nothing) ---

def test_139_a_shortened_label_is_refused_not_stored_as_free_text(store):
    root = _demo(store)
    with pytest.raises(batch.BatchError, match=r"nothing written[\s\S]*it shortens or extends") as exc:
        batch.answer_batch(root, json.dumps({"plat-5": SHORT}), at=AT)
    assert "the owner's own text goes in" in str(exc.value)
    assert _status(root, "plat-5")["status"] == "pending"
    done = batch.answer_batch(root, json.dumps({"plat-5": f"{LONG} (Recommandé)"}), at=AT)  # the tool's label
    assert done["answered"][0]["answer"]["choices"] == [LONG] and "other" not in done["answered"][0]["answer"]
    done = batch.answer_batch(root, json.dumps({"lone": {"other": SHORT}}), at=AT)  # free text, marked so
    assert done["answered"][0]["answer"]["other"] == SHORT


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_146_a_file_with_a_bom_is_read(registry, tmp_path, capsys, encoding):
    f = tmp_path / "answers.json"
    f.write_text(json.dumps({"Alone?": "Yes (Recommandé)"}, ensure_ascii=False), encoding=encoding)
    assert f.read_bytes()[:2] in (b"\xef\xbb", b"\xff\xfe")
    assert cli.main(["--project", "demo", "decision", "answer", "--batch", f"@{f}", "--at", AT]) == 0
    assert "answered 1 decision(s)" in capsys.readouterr().out
    assert _status(registry, "lone")["answer"]["choices"] == ["Yes"]
    assert batch.parse("﻿" + '{"a": "b"}') == [("a", "b")]


# --- the capture hook ---

def test_the_hook_ties_each_answer_to_the_ddr_its_question_came_from(store, brain_home):
    root = _demo(store)
    (b,) = _batches(root)
    qs = b["questions"]
    by_header = {q["header"]: q for q in qs}
    plat, hosts, lone = by_header["PLAT-5"], by_header["Hosts"], by_header["Lone"]
    assert plat["options"][0]["label"] == f"{LONG} (Recommandé)"
    replies = {plat["question"]: f"{LONG} (Recommandé)",          # the label as the tool returns it, ", " inside
               hosts["question"]: "Alpha (Recommandé), Beta, gamma, my own idea",   # multiple choice and Other
               lone["question"]: "Not before Friday"}                # the owner's own text
    assert _hook(qs, replies, notes={plat["question"]: "only the engine"}) == 0
    caps = {c["ddr"]: c for c in _ledger(brain_home, "answer")}
    p = caps["ddr-2026-11-01-plat-5-what-is-public"]
    assert p["answer"] == f"{LONG} (Recommandé)" and p["choices"] == [LONG] and p["notes"] == "only the engine"
    assert p["session"] == "s-1" and p["project"] == "demo" and p["header"] == "PLAT-5"
    h = caps["ddr-2026-11-01-hosts"]
    assert h["choices"] == ["Alpha", "Beta, gamma"] and h["other"] == "my own idea"
    assert caps["ddr-2026-11-01-lone-question"]["other"] == "Not before Friday"
    assert "choices" not in caps["ddr-2026-11-01-lone-question"]
    assert not (brain_home / "ledger" / f"ddr-{AT[:7]}.jsonl").exists() or not _ledger(brain_home, "ddr")
    assert {a["ddr"] for a in _ledger(brain_home, "ar")} == set(caps)
    _hook(qs, replies)  # the same call twice: captured once
    assert len(_ledger(brain_home, "answer")) == 3
    assert _status(root, "plat-5")["status"] == "pending"  # the capture never writes the repo


def test_a_question_asked_by_hand_stays_an_ad_hoc_ddr(store, brain_home):
    root = _demo(store)
    _batches(root)
    q = {"question": "Lunch?", "header": "Lunch", "multiSelect": False,
         "options": [{"label": "Now (Recommandé)", "description": "-"}, {"label": "Later", "description": "-"}]}
    _hook([q], {"Lunch?": "Now (Recommandé)"})
    assert not _ledger(brain_home, "answer")
    (ddr,) = _ledger(brain_home, "ddr")
    assert ddr["recommendation"]["option"] == "Now" and ddr["answer"]["choices"] == ["Now"]  # the French mark too


def test_match_by_id_suffix_then_text_then_header_and_labels():
    asked = [{"ddr": "ddr-1", "question": "Q?", "header": "H", "labels": ["A", "B"], "at": "1"},
             {"ddr": "ddr-2", "question": "Q?", "header": "H", "labels": ["C", "D"], "at": "2"}]
    q = {"question": "Q?", "header": "H", "options": [{"label": "C"}, {"label": "D"}]}
    assert answers.match(q, asked)["ddr"] == "ddr-2"  # the same text twice: the labels decide
    assert answers.match({"question": "Q? (ddr-1)", "header": "x"}, asked)["ddr"] == "ddr-1"
    assert answers.match({"question": "Reworded", "header": "H", "options": [{"label": "A"}, {"label": "B"}]},
                         asked)["ddr"] == "ddr-1"
    assert answers.match({"question": "Q?", "header": "H", "options": []}, asked) is None  # ambiguous
    assert answers.match({"question": "Other?", "header": "Z"}, asked) is None


# --- one writer per batch: an agent's session never records a relayed answer ---

def test_an_agent_session_records_only_what_its_question_tool_captured(registry, monkeypatch, capsys, brain_home):
    root = registry
    (b,) = _batches(root)
    lone = next(q for q in b["questions"] if q["header"] == "Lone")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-2")
    base = ["--project", "demo", "decision", "answer"]
    assert cli.main(base + ["lone", "Yes", "--at", AT]) == 1  # relayed by a message: refused
    err = capsys.readouterr().err
    assert "never recorded" in err and "brain decision ack" in err
    assert cli.main(base + ["--batch", '{"lone": "Yes"}', "--at", AT]) == 1
    assert "nothing written" in capsys.readouterr().err
    _hook(b["questions"], {lone["question"]: "Yes (Recommandé)"}, sid="s-1")   # another session asked it
    assert cli.main(base + ["lone", "Yes", "--at", AT]) == 1
    _hook(b["questions"], {lone["question"]: "Yes (Recommandé)"}, sid="s-2", tuid="toolu_02")  # this one did
    assert cli.main(base + ["lone", "No", "--at", AT]) == 1  # not what it captured
    assert cli.main(base + ["--batch", '{"Alone?": "Yes (Recommandé)"}', "--at", AT]) == 0
    assert _status(root, "lone")["answer"]["choices"] == ["Yes"]
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert cli.main(base + ["hosts", "Delta", "--at", AT]) == 0  # the owner's own terminal records anything


# --- brain decision answer --captured: a worktree, one PR, merged with its retries ---

@pytest.fixture
def origin(registry, tmp_path, monkeypatch):
    """The project's checkout under git, with an origin (a bare repo) on main."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    root = registry
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    run_git(root, "init", "-q", "-b", "main")
    run_git(root, "config", "commit.gpgsign", "false")
    (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    decisions.write_view(root, "demo")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "init")
    run_git(root, "remote", "add", "origin", str(bare))
    run_git(root, "push", "-q", "-u", "origin", "main")
    run_git(root, "remote", "set-head", "origin", "main")
    return root, bare


def _fake_gh(calls, merges):
    """gh: create answers a URL; merge refuses or merges (the branch pushed onto origin's main, as GitHub would)."""
    def gh(args, cwd):
        calls.append(args)
        if args[:2] == ["pr", "create"]:
            return subprocess.CompletedProcess(args, 0, "https://github.com/acme/demo/pull/7\n", "")
        ok = merges.pop(0) if merges else True
        if ok:
            run_git(cwd, "push", "-q", "origin", "HEAD:main")
        return subprocess.CompletedProcess(args, 0 if ok else 1, "", "" if ok else "not mergeable")
    return gh


def _main(bare, path):
    return subprocess.run(["git", "--git-dir", str(bare), "show", f"main:{path}"], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def _refresh(worktree):
    decisions.write_view(worktree, "demo")
    return 0


def test_captured_records_the_batch_in_one_pr(origin, monkeypatch, capsys, brain_home, tmp_path):
    root, bare = origin
    (b,) = _batches(root)
    by_header = {q["header"]: q for q in b["questions"]}
    _hook(b["questions"], {by_header["PLAT-5"]["question"]: f"{LONG} (Recommandé)",
                           by_header["Lone"]["question"]: "No"}, notes={by_header["Lone"]["question"]: "not yet"})
    calls = []
    monkeypatch.setattr(answers, "gh", _fake_gh(calls, [True]))
    monkeypatch.setattr(answers, "refresh", _refresh)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    base = ["--project", "demo", "decision", "answer", "--captured"]
    assert cli.main(base + ["--dry-run"]) == 0
    assert "dry run: 2 answer(s)" in capsys.readouterr().out
    assert cli.main(base + ["--session", "s-9"]) == 1  # another session's capture: refused
    assert "its own captured answers" in capsys.readouterr().err
    assert cli.main(base) == 0
    out = capsys.readouterr().out
    assert "recorded 2 answer(s) on claude/answers-" in out and "merged" in out
    assert [c[:2] for c in calls] == [["pr", "create"], ["pr", "merge"]]
    body = calls[0][calls[0].index("--body") + 1]
    assert f"{LONG} (Recommandé)" in body and "not yet" in body and "s-1" in body
    branch = next(line.split()[-2] for line in out.splitlines() if "recorded 2" in line).rstrip(":")
    log = subprocess.run(["git", "--git-dir", str(bare), "log", "main", "--format=%s"], capture_output=True,
                         text=True, check=True).stdout
    assert "Ada's answers: Lone, PLAT-5 (question tool, captured)" in log  # the order of the tool call
    ddr = yaml.safe_load(_main(bare, "records/ddr/ddr-2026-11-01-plat-5-what-is-public.yaml"))
    assert ddr["answer"] == {"at": ddr["answer"]["at"], "by": "Ada", "choices": [LONG], "via": "ask-tool"}
    lone = yaml.safe_load(_main(bare, "records/ddr/ddr-2026-11-01-lone-question.yaml"))
    assert lone["answer"]["choices"] == ["No"] and lone["answer"]["notes"] == "not yet"
    assert "Answered, to integrate (2)" in _main(bare, "notes/decision_queue.md")
    assert branch.startswith("claude/answers-") and branch not in subprocess.run(
        ["git", "--git-dir", str(bare), "branch"], capture_output=True, text=True).stdout  # deleted once merged
    assert not (root / ".claude" / "worktrees").exists() or not any((root / ".claude" / "worktrees").iterdir())
    assert branch not in run_git(root, "branch", "--list")
    assert _status(root, "plat-5")["status"] == "pending"  # the main checkout is untouched
    assert cli.main(base) == 0 and "no captured answer to record" in capsys.readouterr().out  # recorded once
    assert records.check(root)[0] == []


def test_captured_merges_main_and_retries_when_it_moved(origin, monkeypatch, brain_home, tmp_path):
    root, bare = origin
    (b,) = _batches(root)
    lone = next(q for q in b["questions"] if q["header"] == "Lone")
    _hook(b["questions"], {lone["question"]: "Yes (Recommandé)"})

    def main_moved():   # another PR lands on main once ours is open: the generated view conflicts
        other = tmp_path / "other"
        subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
        _ask(other, "Late", "Late question?", ["Yes: go", "No: wait"])
        decisions.write_view(other, "demo")
        run_git(other, "add", "-A")
        run_git(other, "commit", "-qm", "another decision")
        run_git(other, "push", "-q", "origin", "main")

    calls = []
    gh = _fake_gh(calls, [False, True])
    monkeypatch.setattr(answers, "gh", lambda args, cwd: (main_moved() if args[:2] == ["pr", "merge"] and
                                                          len(calls) == 1 else None) or gh(args, cwd))
    monkeypatch.setattr(answers, "refresh", _refresh)
    caps = answers.unrecorded("s-1", "demo")
    out = answers.record_captured(_project(root), caps, owner="Ada", session="s-1", wait=0, at=AT)
    assert out["merged"] and out["log"][0].startswith("merge refused") and "merged after 1 retry(ies)" in out["log"]
    assert any(line.startswith("merged main into claude/answers-") for line in out["log"])
    view = _main(bare, "notes/decision_queue.md")
    assert "ddr-2026-11-01-late" in view and "Answered, to integrate (1)" in view  # both sides, regenerated
    assert yaml.safe_load(_main(bare, "records/ddr/ddr-2026-11-01-lone-question.yaml"))["status"] == "answered"
    assert [c[:2] for c in calls] == [["pr", "create"], ["pr", "merge"], ["pr", "merge"]]


def test_captured_leaves_a_decision_answered_meanwhile(origin, monkeypatch, brain_home, tmp_path):
    root, bare = origin
    (b,) = _batches(root)
    lone = next(q for q in b["questions"] if q["header"] == "Lone")
    _hook(b["questions"], {lone["question"]: "Yes (Recommandé)"})
    other = tmp_path / "other"   # someone else answered the same decision on main
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
    decisions.answer(other, "lone", ["No"], at=AT, by="Ada")
    run_git(other, "add", "-A")
    run_git(other, "commit", "-qm", "answered by hand")
    run_git(other, "push", "-q", "origin", "main")
    monkeypatch.setattr(answers, "gh", _fake_gh([], [False]))
    monkeypatch.setattr(answers, "refresh", _refresh)
    with pytest.raises(answers.AnswersError, match="nothing to record") as exc:  # fetched first: not pending
        answers.record_captured(_project(root), answers.unrecorded("s-1"), owner="Ada", wait=0, at=AT)
    assert "lone-question (answered)" in str(exc.value)
    assert not answers.read(answers.RECORDED)
