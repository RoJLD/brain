"""The answers' lane (wi-brain-answers-lane): the capture ties each answer to its DDR, --batch is strict and reads a
BOM, an agent's session never records a relayed answer, --captured records a batch in one PR with its merges."""

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import GIT_ENV, git_init, run_git

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
    answers.remember("demo", root, data["batches"], at=AT, session="s-1")
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
    asked = [{"ddr": "ddr-1", "question": "Q?", "header": "H", "labels": ["A", "B"], "at": "1", "session": "s-1"},
             {"ddr": "ddr-2", "question": "Q?", "header": "H", "labels": ["C", "D"], "at": "2", "session": "s-1"}]
    q = {"question": "Q?", "header": "H", "options": [{"label": "C"}, {"label": "D"}]}
    assert answers.match(q, asked)["ddr"] == "ddr-2"  # the same text twice: the labels decide
    assert answers.match({"question": "Q? (ddr-1)", "header": "x"}, asked)["ddr"] == "ddr-1"
    reworded = {"question": "Reworded", "header": "H", "options": [{"label": "A"}, {"label": "B"}]}
    assert answers.match(reworded, asked, "s-1")["ddr"] == "ddr-1"
    # review of #19, finding 28: the header-and-labels fallback is this session's batch only
    assert answers.match(reworded, asked, "s-other") is None and answers.match(reworded, asked) is None
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
    git_init(bare, bare=True)
    git_init(root)
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
    assert ddr["answer"] == {"at": ddr["answer"]["at"], "by": "Ada", "session": "s-1", "choices": [LONG],
                             "via": "ask-tool"}  # and the session that recorded it (scale study gap 19)
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


def test_captured_matches_the_exact_id_and_leaves_a_ddr_main_does_not_hold(origin, monkeypatch, brain_home,
                                                                          tmp_path):
    """A DDR asked on a branch not merged yet (ddr-...-lone, only in this checkout) is left captured and said; main's
    ddr-...-lone-question, whose id merely contains it, is never answered in its place; the batch's other answers are
    recorded (review of #19, finding 1)."""
    root, bare = origin
    new = _ask(root, "Lone", "A new one, asked on a branch?", ["Yes: go", "No: wait"])["id"]
    assert new == "ddr-2026-11-01-lone" and new in "ddr-2026-11-01-lone-question"
    b = next(b for b in _batches(root) if any(q["header"] == "Lone" for q in b["questions"]))
    by_header = {q["header"]: q for q in b["questions"]}
    _hook(b["questions"], {by_header["Lone"]["question"]: "No", by_header["PLAT-5"]["question"]: f"{LONG} (Recommandé)"})
    monkeypatch.setattr(answers, "gh", _fake_gh([], [True]))
    monkeypatch.setattr(answers, "refresh", _refresh)
    caps = answers.unrecorded("s-1")
    assert {c["ddr"] for c in caps} == {new, "ddr-2026-11-01-plat-5-what-is-public"}
    out = answers.record_captured(_project(root), caps, owner="Ada", wait=0, at=AT)
    assert out["recorded"] == ["ddr-2026-11-01-plat-5-what-is-public"] and out["missing"] == [new]
    assert "answer" not in yaml.safe_load(_main(bare, "records/ddr/ddr-2026-11-01-lone-question.yaml"))
    assert yaml.safe_load(_main(bare, "records/ddr/ddr-2026-11-01-plat-5-what-is-public.yaml"))["answer"]["choices"] \
        == [LONG]
    assert [c["ddr"] for c in answers.unrecorded("s-1")] == [new]   # still captured: recorded once its branch merges


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


# --- the question tool's real shapes (wi-brain-capture-multiselect, wi-brain-capture-unanswered) ---

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ask_tool_results.json").read_text(encoding="utf-8"))
PLACEHOLDER = next(iter(FIXTURE["interrupted"]["answers"].values()))


def _tool_result(name):
    r = FIXTURE[name]
    payload = {"session_id": "s-1", "tool_name": "AskUserQuestion", "tool_use_id": "toolu_01REALSHAPE",
               "tool_input": {"questions": r["questions"]}, "tool_response": r}
    return capture.main(["post-tool-use"], stdin=io.StringIO(json.dumps(payload, ensure_ascii=False)))


def _errors(home):
    f = home / "ledger" / "errors.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def test_a_multiple_choice_returned_as_a_list_is_captured(brain_home):
    """The tool returns a multiple choice as a list: the capture of the whole call was lost to a TypeError."""
    assert _tool_result("multiselect") == 0
    assert _errors(brain_home) == ""
    (ddr,) = _ledger(brain_home, "ddr")
    assert ddr["answer"]["choices"] == ["merge-check", "Two existing guards", "Public check at commit",
                                        "Sort the 7 candidates"] and "other" not in ddr["answer"]
    assert ddr["recommendation"]["option"] == "merge-check" and ddr["status"] == "answered"


def test_ddr_from_question_takes_a_list_or_a_joined_string_and_keeps_free_text():
    q = FIXTURE["multiselect"]["questions"][0]
    for answer in (["Two existing guards", "merge-check (Recommandé)", "my own idea"],
                   "merge-check (Recommandé), Two existing guards, my own idea"):
        ans = capture.ddr_from_question(q, answer, AT, {"session_id": "s-1"})["answer"]
        assert ans["choices"] == ["merge-check", "Two existing guards"]
        if isinstance(answer, list):
            assert ans["other"] == "my own idea"   # an item that names no option is the owner's text
    one = capture.ddr_from_question({**q, "multiSelect": False}, ["Two existing guards"], AT, {})["answer"]
    assert one["choices"] == ["Two existing guards"]


def test_a_batch_multiple_choice_as_a_list_is_tied_to_its_ddr(store, brain_home):
    root = _demo(store)
    (b,) = _batches(root)
    hosts = next(q for q in b["questions"] if q["header"] == "Hosts")
    _hook(b["questions"], {hosts["question"]: ["Alpha (Recommandé)", "Beta, gamma", "my own idea"]})
    (cap,) = _ledger(brain_home, "answer")
    assert cap["choices"] == ["Alpha", "Beta, gamma"] and cap["other"] == "my own idea"
    assert cap["answer"] == "Alpha (Recommandé), Beta, gamma, my own idea"


def test_an_interrupted_question_is_no_answer(store, brain_home):
    """The owner sent a message instead of answering: the tool's placeholder is never an answer."""
    assert _tool_result("interrupted") == 0 and _errors(brain_home) == ""
    ddrs = _ledger(brain_home, "ddr")
    assert len(ddrs) == 2 and all(d["status"] == "pending" and "answer" not in d for d in ddrs)
    root = _demo(store)
    (b,) = _batches(root)
    lone = next(q for q in b["questions"] if q["header"] == "Lone")
    _hook(b["questions"], {lone["question"]: PLACEHOLDER})
    assert not _ledger(brain_home, "answer")   # a printed question: nothing captured, as for an empty answer
    assert answers.unanswered(PLACEHOLDER) and answers.unanswered([PLACEHOLDER]) and not answers.unanswered("No")


def _cap(ddr, at, sid="s-1", n=0, **kw):
    """A capture row as the hook writes it (an older engine's rows included)."""
    rec = {"v": 1, "id": f"ans-{at[:10]}-{ddr[-6:]}-{at[11:13]}{at[14:16]}-{n}", "at": at, "ddr": ddr,
           "project": "demo", "root": "x", "session": sid, "tool_use_id": "t", "question": "q", "header": "H",
           "answer": kw.get("answer", ", ".join(kw.get("choices") or []) or kw.get("other", "")), "multi": False}
    rec.update({k: v for k, v in kw.items() if k != "answer"})
    answers._append(answers.CAPTURED, [rec])
    return rec


LONE = "ddr-2026-11-01-lone-question"


def test_captured_refuses_and_retires_a_placeholder_row(origin, monkeypatch, brain_home):
    """Rows an older engine wrote for an interrupted question (SIGMA-1 to 4): listed, refused, retired; --again never
    writes them."""
    root, bare = origin
    _cap(LONE, "2026-11-04T03:16:21Z", answer=PLACEHOLDER, other=PLACEHOLDER)
    monkeypatch.setattr(answers, "gh", _fake_gh([], [True]))
    monkeypatch.setattr(answers, "refresh", _refresh)
    (c,) = answers.unrecorded("s-1")
    with pytest.raises(answers.AnswersError, match="nothing to record: .*not answered: the owner sent a message"):
        answers.record_captured(_project(root), [c], owner="Ada", wait=0, at=AT, again=True)
    assert "answer" not in yaml.safe_load(_main(bare, f"records/ddr/{LONE}.yaml"))
    assert answers.read(answers.RECORDED)[0]["retired"].startswith("not answered") and not answers.unrecorded("s-1")


def test_a_real_answer_wins_over_a_later_placeholder(brain_home):
    _cap(LONE, "2026-11-04T03:00:00Z", choices=["No"])
    _cap(LONE, "2026-11-04T03:16:21Z", answer=PLACEHOLDER, other=PLACEHOLDER)
    assert [c["choices"] for c in answers.unrecorded("s-1")] == [["No"]]


# --- review of #19: the medium and low findings of the answers' lane ---

def test_5_an_older_capture_of_a_recorded_ddr_does_not_come_back(brain_home):
    a = _cap(LONE, "2026-11-04T09:00:00Z", choices=["Yes"])
    b = _cap(LONE, "2026-11-04T10:00:00Z", choices=["No"])
    assert [c["id"] for c in answers.unrecorded("s-1")] == [b["id"]]
    answers._append(answers.RECORDED, [{"v": 1, "id": b["id"], "at": "2026-11-04T10:05:00Z", "ddr": LONE,
                                        "pr": "u"}])   # an older engine's row: no captured_at
    assert answers.unrecorded("s-1") == [] and a["id"] not in {r["id"] for r in answers.read(answers.RECORDED)}


def test_5_a_capture_older_than_the_ddr_answer_is_stale_even_with_again(origin, monkeypatch, brain_home, tmp_path):
    root, bare = origin
    _cap(LONE, "2026-11-03T09:00:00Z", choices=["Yes"])
    other = tmp_path / "other"   # answered by hand on main after the capture (decision answer, --batch)
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
    decisions.answer(other, "lone", ["No"], at="2026-11-03T10:00:00Z", by="Ada")
    run_git(other, "add", "-A")
    run_git(other, "commit", "-qm", "answered by hand")
    run_git(other, "push", "-q", "origin", "main")
    monkeypatch.setattr(answers, "gh", _fake_gh([], [True]))
    monkeypatch.setattr(answers, "refresh", _refresh)
    with pytest.raises(answers.AnswersError, match="stale, retired"):
        answers.record_captured(_project(root), answers.unrecorded("s-1"), owner="Ada", wait=0, at=AT, again=True)
    assert yaml.safe_load(_main(bare, f"records/ddr/{LONE}.yaml"))["answer"]["choices"] == ["No"]
    assert answers.unrecorded("s-1") == []   # retired: it never comes back


def test_6_an_answer_captured_before_the_deadline_beats_the_default(origin, monkeypatch, brain_home, tmp_path):
    from brain import defaults
    root, bare = origin
    ddr = _ask(root, "Wording", "Which wording?", ["Short: fewer", "Long: more"], low_stakes=True)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "a low-stakes decision")
    run_git(root, "push", "-q", "origin", "main")
    after = ddr["default"]["after"]
    _cap(ddr["id"], "2026-11-02T08:30:00Z", choices=["Long"])   # the owner answered in time
    assert defaults.finalize(root, "2026-11-02T09:05:00Z") == []   # this machine's refresh leaves it pending
    other = tmp_path / "other"   # another machine's refresh took the default meanwhile
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
    with monkeypatch.context() as m:
        m.setenv("BRAIN_HOME", str(tmp_path / "elsewhere"))
        assert defaults.finalize(other, "2026-11-02T09:05:00Z") == [ddr["id"]]
    run_git(other, "add", "-A")
    run_git(other, "commit", "-qm", "taken by default")
    run_git(other, "push", "-q", "origin", "main")
    monkeypatch.setattr(answers, "gh", _fake_gh([], [True]))
    monkeypatch.setattr(answers, "refresh", _refresh)
    out = answers.record_captured(_project(root), answers.unrecorded("s-1"), owner="Ada", wait=0, at=AT)
    assert out["recorded"] == [ddr["id"]]
    got = yaml.safe_load(_main(bare, f"records/ddr/{ddr['id']}.yaml"))["answer"]
    assert got["choices"] == ["Long"] and got["by"] == "Ada" and got["at"] < after


def test_8_a_shortened_label_is_kept_unmapped_and_refused(origin, monkeypatch, brain_home):
    root, bare = origin
    (b,) = _batches(root)
    plat = next(q for q in b["questions"] if q["header"] == "PLAT-5")
    short = {**plat, "options": [{"label": f"{SHORT} (Recommandé)"}, *plat["options"][1:]]}
    _hook([short], {short["question"]: f"{SHORT} (Recommandé)"})
    (cap,) = _ledger(brain_home, "answer")
    assert cap["unmapped"] == [f"{SHORT} (Recommandé)"] and "other" not in cap and "choices" not in cap
    monkeypatch.setattr(answers, "gh", _fake_gh([], [True]))
    monkeypatch.setattr(answers, "refresh", _refresh)
    with pytest.raises(answers.AnswersError, match="names no option of the DDR"):
        answers.record_captured(_project(root), answers.unrecorded("s-1"), owner="Ada", wait=0, at=AT)
    assert "answer" not in yaml.safe_load(_main(bare, "records/ddr/ddr-2026-11-01-plat-5-what-is-public.yaml"))


def test_34_both_ledgers_are_read_over_the_same_months(brain_home):
    sep = _cap("ddr-a", "2026-09-10T09:00:00Z", choices=["A"])
    octo = _cap("ddr-b", "2026-10-31T23:50:00Z", choices=["B"])
    answers._append(answers.RECORDED, [{"v": 1, "id": sep["id"], "at": "2026-09-10T10:00:00Z", "ddr": "ddr-a"},
                                       {"v": 1, "id": octo["id"], "at": "2026-11-01T00:05:00Z", "ddr": "ddr-b"},
                                       {"v": 1, "id": "x", "at": "2026-10-02T00:00:00Z", "ddr": "ddr-x"}])
    assert answers.unrecorded() == []


# --- the PR's own review (2 lenses, 2 skeptics each) ---

def test_review_a_typed_single_choice_keeps_the_owners_reason():
    q = {"question": "Ship it?", "header": "Ship", "multiSelect": False,
         "options": [{"label": "Yes (Recommended)"}, {"label": "No"}]}
    ans = capture.ddr_from_question(q, "No, because it is slow", AT, {})["answer"]
    assert ans == {"at": AT, "by": "user", "via": "ask-tool", "other": "No, because it is slow"}
    assert capture.ddr_from_question(q, "No", AT, {})["answer"]["choices"] == ["No"]


def test_review_a_joined_multiple_choice_takes_the_longest_label():
    q = {"question": "Which?", "header": "Which", "multiSelect": True,
         "options": [{"label": "A, b"}, {"label": "C"}, {"label": "A"}]}
    ans = capture.ddr_from_question(q, "A, b, my idea", AT, {})["answer"]
    assert ans["choices"] == ["A, b"] and ans["other"] == "my idea"


def test_review_answers_of_another_shape_lose_nothing_else(brain_home):
    q = FIXTURE["multiselect"]["questions"][0]
    payload = {"session_id": "s-1", "tool_name": "AskUserQuestion", "tool_use_id": "toolu_01OTHERSHAPE",
               "tool_input": {"questions": [q]}, "tool_response": {"questions": [q], "answers": ["x"]}}
    assert capture.main(["post-tool-use"], stdin=io.StringIO(json.dumps(payload))) == 0
    assert _errors(brain_home) == "" and _ledger(brain_home, "ddr")[0]["status"] == "pending"
