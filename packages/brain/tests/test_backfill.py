import json
import os
import shutil
from datetime import datetime, timezone

import pytest
import yaml

from brain import backfill, cli, records

SID = "aaaabbbb-1111-2222-3333-444455556666"
LIVE = "ccccdddd-1111-2222-3333-444455556666"
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _root(store):
    return store.parents[1]


def _call(session, tuid, command, cwd, t_use, t_result, stdout="", agent=""):
    use = {"type": "assistant", "sessionId": session, "timestamp": t_use, "cwd": cwd, "gitBranch": "main",
           "version": "2.1.320", "entrypoint": "cli", "isSidechain": bool(agent),
           "message": {"id": f"msg_{tuid}", "model": "claude-opus-5-5", "role": "assistant",
                       "content": [{"type": "tool_use", "id": tuid, "name": "Bash", "input": {"command": command}}],
                       "usage": {"input_tokens": 1, "output_tokens": 10}}}
    result = {"type": "user", "sessionId": session, "timestamp": t_result, "cwd": cwd, "gitBranch": "main",
              "isSidechain": bool(agent),
              "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tuid, "content": "ok"}]},
              "toolUseResult": {"stdout": stdout, "stderr": ""}}
    return "".join(json.dumps(r) + "\n" for r in (use, result))


def _old(path, when="2026-10-30T11:00:00"):
    t = datetime.fromisoformat(when).replace(tzinfo=timezone.utc).timestamp()
    os.utime(path, (t, t))


@pytest.fixture
def machine(tmp_path, monkeypatch, brain_home, fixture_transcript):
    """Transcripts and a ledger: one finished session with a subagent, one live session."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-registry.yaml"))
    proj = tmp_path / "claude" / "projects" / "E--work"
    proj.mkdir(parents=True)
    main = proj / f"{SID}.jsonl"
    shutil.copy(fixture_transcript, main)
    _old(main)
    sub = proj / SID / "subagents" / "agent-a1.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text(_call(SID, "toolu_sub1", "gh pr create --fill", "/work/brain", "2026-10-30T10:05:00Z",
                         "2026-10-30T10:05:09Z", "https://github.com/RoJLD/brain-test/pull/8\n", agent="a1"),
                   encoding="utf-8")
    (sub.parent / "agent-a1.meta.json").write_text('{"agentType": "general-purpose"}', encoding="utf-8")
    (sub.parent / "workflows" / "wf_1").mkdir(parents=True)
    (sub.parent / "workflows" / "wf_1" / "journal.jsonl").write_text('{"x": 1}\n', encoding="utf-8")
    live = proj / f"{LIVE}.jsonl"
    live.write_text(_call(LIVE, "toolu_live1", "gh pr merge 9 --repo RoJLD/brain-test --merge", "/work/brain",
                          "2026-11-01T11:30:00Z", "2026-11-01T11:30:05Z"), encoding="utf-8")
    _old(live, "2026-11-01T11:30:05")
    ledger = brain_home / "ledger"
    ledger.mkdir(parents=True)
    hook_push = {"v": 1, "id": "ar-2026-10-30-push-brain-test-feat-0123456789", "kind": "push",
                 "at": "2026-10-30T10:01:00Z", "repo": "RoJLD/brain-test", "branch": "feat", "sha": "0123456789",
                 "session": {"id": SID, "tool": "claude-code"}, "source": "hook", "tool_use_id": "toolu_push1"}
    scratch = {"v": 1, "id": "ar-2026-10-30-commit-scratch-abcdef0123", "kind": "commit", "at": "2026-10-30T10:02:00Z",
               "repo": "scratch", "sha": "abcdef0123", "subject": "test only",
               "session": {"id": SID, "tool": "claude-code"}, "source": "hook", "tool_use_id": "toolu_scratch"}
    (ledger / "ar-2026-10.jsonl").write_text(json.dumps(hook_push) + "\n" + json.dumps(scratch) + "\n",
                                             encoding="utf-8")
    (ledger / "ddr-2026-10.jsonl").write_text(json.dumps({"id": "ddr-2026-10-30-which", "asked": {"by": SID}}) + "\n",
                                              encoding="utf-8")
    (ledger / "events-2026-10.jsonl").write_text(
        json.dumps({"at": "2026-10-30T10:30:00Z", "event": "session_end", "session_id": SID, "reason": "clear"})
        + "\n", encoding="utf-8")
    return proj


def test_backfill_writes_once(store, machine):
    root = _root(store)
    report = backfill.run(root, now=NOW)
    assert report["2026-10"]["sr"] == 1 and report["2026-11"]["sr-live"] == 1
    # the hook's push (keyed by its SHA) stands for the transcript's push of the same tool call
    assert report["2026-10"]["ar-push"] == 1 and report["2026-10"]["ar-known"] == 1
    assert report["2026-10"]["ar-pr"] == 2 and report["2026-11"]["ar-pr"] == 1
    assert report["2026-10"]["ar-unpublished"] == 1  # a commit in a scratch repo (no PR, not registered)
    ars = {a["id"]: a for _, a in records.load(root)["ar"]}
    assert not [a for a in ars.values() if a.get("repo") == "scratch"]
    assert "ar-2026-10-30-push-brain-test-feat-0123456789" in ars
    (sub_pr,) = [a for a in ars.values() if a.get("pr", {}).get("number") == 8]
    assert sub_pr["session"]["agent"] == "general-purpose" and sub_pr["session"]["id"] == SID
    sr = yaml.safe_load((root / "records" / "sr" / "2026-10" / "sr-2026-10-30-aaaabbbb.yaml").read_text("utf-8"))
    assert sr["status"] == "closed" and sr["end_reason"] == "clear" and sr["ddrs"] == ["ddr-2026-10-30-which"]
    assert sr["subagents"]["count"] == 1  # the workflow's journal.jsonl is not a transcript
    assert sorted(sr["actions"]) == sorted(a["id"] for a in ars.values() if a["session"]["id"] == SID)
    assert not list((root / "records" / "sr").glob("2026-11/*"))  # the live session waits
    before = {p: p.read_bytes() for p in (root / "records").rglob("*") if p.is_file()}
    again = backfill.run(root, now=NOW)
    assert {p: p.read_bytes() for p in (root / "records").rglob("*") if p.is_file()} == before
    assert sum(sum(backfill._written(c).values()) for c in again.values()) == 0
    assert again["2026-10"]["sr-kept"] == 1 and "sr" not in again["2026-10"]
    assert records.check(root) == ([], [])


def test_backfill_update_keeps_what_was_written_by_hand(store, machine, capsys):
    root = _root(store)
    backfill.run(root, now=NOW, ledger=False)
    f = root / "records" / "sr" / "2026-10" / "sr-2026-10-30-aaaabbbb.yaml"
    sr = yaml.safe_load(f.read_text("utf-8"))
    sr.update(summary="Built the thing, by hand", end="2026-10-30T10:10:00.000Z", actions=["ar-2026-10-29-pr-x-1-created"])
    records.write(root, "sr", sr, replace=True)
    assert backfill.run(root, now=NOW, ledger=False)["2026-10"]["sr-stale"] == 1
    assert cli.main(["--root", str(root), "record", "backfill", "--update", "--no-ledger", "--quiet-hours", "0"]) == 0
    assert "1 updated" in capsys.readouterr().out
    new = yaml.safe_load(f.read_text("utf-8"))
    assert new["summary"] == "Built the thing, by hand" and new["end"] == "2026-10-30T10:22:00.000Z"
    assert "ar-2026-10-29-pr-x-1-created" in new["actions"] and len(new["actions"]) > 1


def test_backfill_dry_run_and_window(store, machine, capsys):
    root = _root(store)
    assert cli.main(["--root", str(root), "record", "backfill", "--dry-run", "--until", "2026-11-01"]) == 0
    out = capsys.readouterr().out
    assert "2026-10: 1 SR written" in out and "dry run: would write 1 SR" in out
    assert not (root / "records").exists() or not list((root / "records").rglob("*.*"))
    report = backfill.run(root, since="2026-11-01", now=NOW)
    assert "2026-10" not in report and report["2026-11"]["sr-live"] == 1


def test_backfill_keeps_a_newer_brains_data(store, machine):
    """wi-brain-tolerant-reader: an update keeps a newer brain's SR fields; a newer SR is never replaced, and an AR id
    a newer brain wrote is not appended again (its line is skipped by the reader, not by the dedup)."""
    root = _root(store)
    backfill.run(root, now=NOW, ledger=False)
    f = root / "records" / "sr" / "2026-10" / "sr-2026-10-30-aaaabbbb.yaml"
    sr = yaml.safe_load(f.read_text("utf-8"))
    f.write_text(yaml.safe_dump({**sr, "end": "2026-10-30T10:10:00.000Z", "energy_wh": 1.5}), encoding="utf-8")
    assert backfill.run(root, now=NOW, ledger=False, update=True)["2026-10"]["sr-updated"] == 1
    new = yaml.safe_load(f.read_text("utf-8"))
    assert new["energy_wh"] == 1.5 and new["end"] == "2026-10-30T10:22:00.000Z"
    f.write_text(yaml.safe_dump({**new, "v": 2}), encoding="utf-8")
    before = f.read_bytes()
    assert backfill.run(root, now=NOW, ledger=False, update=True)["2026-10"]["sr-refused"] == 1
    assert f.read_bytes() == before
    ar_file = sorted((root / "records" / "ar").glob("*.jsonl"))[0]
    lines = ar_file.read_text("utf-8").splitlines()
    ar_file.write_text("\n".join([lines[0].replace('"v":1', '"v":2', 1)] + lines[1:]) + "\n", encoding="utf-8")
    backfill.run(root, now=NOW, ledger=False)
    assert len(ar_file.read_text("utf-8").splitlines()) == len(lines)
