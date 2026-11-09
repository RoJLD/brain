import json

import pytest
import yaml

from brain import cli, records, transcript

DDR = {"v": 1, "id": "ddr-2026-10-30-command-shape", "title": "Command shape", "question": "Which?",
       "options": [{"label": "brain"}, {"label": "atlas"}], "recommendation": {"option": "brain", "why": "one"},
       "multi_select": False, "status": "pending",
       "asked": {"at": "2026-10-30T10:00:00Z", "by": "aaaabbbb-1111-2222-3333-444455556666", "via": "spec"},
       "links": {"items": ["wi-one"], "adrs": ["adr-2026-10-30-x"], "specs": ["spec-x"]}}


def _root(store):
    return store.parents[1]


def test_write_check_and_graph(store, fixture_transcript):
    root = _root(store)
    stats, _, _ = transcript.session_stats(fixture_transcript)
    sr = stats.record(fixture_transcript, extra_items=["wi-one", "wi-unknown"])
    records.write(root, "sr", sr)
    records.write(root, "ddr", DDR)
    ar = {"v": 1, "id": "ar-2026-10-30-commit-demo-abcdef1234", "kind": "commit", "at": "2026-10-30T10:05:00Z",
          "repo": "RoJLD/demo", "sha": "abcdef1234", "subject": "x", "items": ["wi-two"],
          "session": {"id": "aaaabbbb-1111-2222-3333-444455556666", "tool": "claude-code"}, "source": "hook"}
    assert records.write(root, "ar", ar) is not None
    assert records.write(root, "ar", ar) is None  # append-only, once per id
    assert (root / "records" / "sr" / "2026-10" / "sr-2026-10-30-aaaabbbb.yaml").exists()
    assert records.check(root) == ([], [])
    nodes, edges, left_out = records.graph_view(root, store)
    assert {n["id"]: n["type"] for n in nodes} == {"sr-2026-10-30-aaaabbbb": "Session", DDR["id"]: "DDR",
                                                    ar["id"]: "Action"}
    assert {(e["from"], e["to"], e["type"]) for e in edges} == {
        ("sr-2026-10-30-aaaabbbb", "wi-one", "touches"),
        (DDR["id"], "sr-2026-10-30-aaaabbbb", "raised_by"),
        (DDR["id"], "adr-2026-10-30-x", "answered_in"),
        (DDR["id"], "wi-one", "about"), (DDR["id"], "spec-x", "about"),
        (ar["id"], "sr-2026-10-30-aaaabbbb", "produced_by"), (ar["id"], "wi-two", "touches")}
    assert left_out == 2  # wi-brain-record-formats and wi-unknown are not in this store
    records.write_graph(root, store)
    generated = yaml.safe_load((store / "nodes" / "_generated_records.yaml").read_text(encoding="utf-8"))
    assert len(generated) == 3


def test_check_flags_a_secret_and_a_bad_record(store):
    root = _root(store)
    records.write(root, "ddr", DDR)
    f = root / "records" / "ddr" / f"{DDR['id']}.yaml"
    f.write_text(f.read_text(encoding="utf-8") + "# key: " + "sk-" + "ant-" + "q" * 30 + "\n", encoding="utf-8")
    errors, _ = records.check(root)
    assert any("anthropic-key" in e for e in errors)
    bad = dict(DDR, id="ddr-2026-10-30-bad", options=[{"label": "only"}])
    with pytest.raises(SystemExit, match="fewer than 2"):
        records.write(root, "ddr", bad)


def test_cli_ddr_lifecycle(store, capsys):
    root = _root(store)
    args = ["--root", str(root), "record", "ddr", "--title", "Notify", "--question", "Which channel first?",
            "--option", "ntfy: self-hosted push", "--option", "Telegram: a bot", "--why", "no account needed",
            "--about-item", "wi-one", "--at", "2026-10-31T09:00:00Z"]
    assert cli.main(args) == 0
    ddr_id = "ddr-2026-10-31-notify"
    assert cli.main(["--root", str(root), "record", "ddr", "--id", ddr_id, "--answer", "ntfy",
                     "--at", "2026-10-31T09:10:00Z"]) == 0
    assert cli.main(["--root", str(root), "record", "ddr", "--id", ddr_id, "--applied", "wi-one",
                     "--session", "s-1", "--at", "2026-10-31T09:20:00Z"]) == 0
    d = yaml.safe_load((root / "records" / "ddr" / f"{ddr_id}.yaml").read_text(encoding="utf-8"))
    assert d["status"] == "integrated" and d["answer"]["choices"] == ["ntfy"]
    assert d["options"][0] == {"label": "ntfy", "consequences": "self-hosted push"}
    assert d["read"]["session"] == d["applied"]["session"] == "s-1"
    assert cli.main(["--root", str(root), "record", "check"]) == 0


def test_9_record_ddr_answers_only_what_the_session_captured(store, monkeypatch, tmp_path):
    """Review of #19, finding 9: an agent's session whose relayed answer brain decision answer refuses could record it
    with brain record ddr --id X --answer (or --file --replace) as the owner's."""
    from brain import answers
    root = _root(store)
    records.write(root, "ddr", DDR)
    f = root / "records" / "ddr" / f"{DDR['id']}.yaml"
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-receiver")
    base = ["--root", str(root), "record", "ddr"]
    for extra in (["--answer", "brain", "--by", "Ada"], ["--other", "medium please"]):
        with pytest.raises(SystemExit, match="never recorded"):
            cli.main(base + ["--id", DDR["id"], *extra])
    answered = dict(DDR, status="answered", answer={"at": "2026-10-30T11:00:00Z", "by": "Ada", "via": "chat",
                                                    "choices": ["brain"]})
    other = tmp_path / "answered.yaml"
    other.write_text(yaml.safe_dump(answered), encoding="utf-8")
    with pytest.raises(SystemExit, match="never recorded"):
        cli.main(base + ["--file", str(other), "--replace"])
    assert yaml.safe_load(f.read_text(encoding="utf-8"))["status"] == "pending"
    assert cli.main(base + ["--id", DDR["id"], "--read", "--session", "s-1"]) == 0   # a stamp with no answer
    answers._append(answers.CAPTURED, [{"v": 1, "id": "ans-1", "at": "2026-10-30T11:00:00Z", "ddr": DDR["id"],
                                        "project": "demo", "session": "sess-receiver", "answer": "brain",
                                        "choices": ["brain"]}])
    assert cli.main(base + ["--id", DDR["id"], "--answer", "brain"]) == 0   # this session's question tool's
    assert cli.main(base + ["--file", str(f), "--replace"]) == 0   # the answer it already holds, unchanged
    monkeypatch.delenv("CLAUDECODE")
    assert cli.main(base + ["--id", DDR["id"], "--other", "medium please"]) == 0   # the owner's own terminal
    assert yaml.safe_load(f.read_text(encoding="utf-8"))["answer"]["other"] == "medium please"


def test_cli_imports_the_ledger(store, brain_home):
    root = _root(store)
    (brain_home / "ledger").mkdir(parents=True)
    ar = {"v": 1, "id": "ar-2026-10-31-pr-demo-3-created", "kind": "pr", "at": "2026-10-31T10:00:00Z",
          "repo": "RoJLD/demo", "pr": {"number": 3, "action": "created"},
          "session": {"id": "s-1", "tool": "claude-code"}, "source": "hook"}
    (brain_home / "ledger" / "ar-2026-10.jsonl").write_text(json.dumps(ar) + "\n", encoding="utf-8")
    assert cli.main(["--root", str(root), "record", "ar", "--import"]) == 0
    assert cli.main(["--root", str(root), "record", "ar", "--import"]) == 0
    lines = (root / "records" / "ar" / "2026-10.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["id"] for x in lines] == [ar["id"]]


def test_cli_item_commands(store):
    root = _root(store)
    assert cli.main(["--root", str(root), "item", "add", "wi-new", "--title", "New", "--priority", "P1",
                     "--spec", "spec-x", "--milestone", "ms-x"]) == 0
    assert cli.main(["--root", str(root), "item", "set", "wi-new", "status=doing"]) == 0
    assert cli.main(["--root", str(root), "item", "close", "wi-new", "--pr", "demo #1", "--outcome", "ok"]) == 0
    assert cli.main(["--root", str(root), "item", "set", "wi-new", "status=bogus"]) == 1
