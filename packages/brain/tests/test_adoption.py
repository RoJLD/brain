"""Command adoption (wi-brain-command-adoption): brain perf --usage crosses the CLI registry with the engine's exec
ledger and a mini scan of the transcripts (the brain commands a session ran itself, its hand reads and edits of a
brain's files), and with the features: each gap comes with what to propose, nothing refused."""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from brain import adoption, cli, features

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def known():
    return adoption.units(cli.build_parser())


def test_the_registry_units_are_named_as_the_exec_ledger_names_runs(known):
    units, alias = known
    assert units["brain status"] == "status" and units["brain item show"] == "item"
    assert "brain item" not in units and "brain perf" in units and "brain journal last" in units
    families = {" ".join(u.split()[:2]) for u in units}
    assert all(a.startswith("brain ") and (t in units or t in families) for a, t in alias.items())


def test_every_run_the_ledger_names_lands_on_a_unit(known):
    """Each command and subcommand parsed as typed (aliases too), named by selftime.command_task as its exec event
    is, counts for its unit: none drifts into 'never ran' (a family run through its alias counts for its family)."""
    from brain import selftime
    units, alias = known
    parser = cli.build_parser()
    top = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    checked = 0
    for name, sp in top.choices.items():
        subs = next((a for a in sp._actions if a.__class__.__name__ == "_SubParsersAction"), None)
        for words in [[name, s] for s in subs.choices] if subs is not None else [[name]]:
            try:
                args, _ = parser.parse_known_args(words)
            except SystemExit:   # a required argument: its task name is the same, so its sibling's check stands
                continue
            task = selftime.command_task(args)
            want = alias.get(" ".join(["brain", *words]), " ".join(["brain", *words]))
            assert adoption.ran_count(want, Counter({alias.get(task, task): 1})) == 1, (words, task)
            checked += 1
    assert checked > 50


@pytest.mark.parametrize("line, want", [
    ("cd x && brain --project demo item show wi-1 | head -5", ["brain item show"]),
    ('"E:/venv/Scripts/brain.exe" --root=. status --all', ["brain status"]),
    ('& "C:/v/Scripts/brain.exe" items --text x', ["brain items"]),
    ("brain --proj demo journal last 3; brain perf --usage", ["brain journal last", "brain perf"]),
    ("BRAIN_HOME=/tmp/h python -m brain status", ["brain status"]),
    ("python -m pytest -q", []),
    ("cat <<EOF > f\nbrain status\nEOF", []),
    ("cd a\ncat <<EOF\nbrain items\nEOF", []),
    ("git -C D:/work/brain status", []),
    ('git commit -m "brain item add x; brain status"', []),
    ('echo "run brain items now"', []),
    ("brain nope", []),
])
def test_typed_reads_the_brain_commands_of_a_shell_line(known, line, want):
    assert adoption.typed(line, *known) == want


def _record(when, tool, inp, cwd, session="s1"):
    return {"type": "assistant", "timestamp": when.isoformat().replace("+00:00", "Z"), "cwd": str(cwd),
            "sessionId": session, "message": {"content": [{"type": "tool_use", "name": tool, "input": inp}]}}


@pytest.fixture
def brain(tmp_path, monkeypatch, store):
    root = store.parents[1]
    (root / "notes" / "journal.md").write_text("# Journal\n", encoding="utf-8")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    adoption._owned.cache_clear()
    yield root
    adoption._owned.cache_clear()


def _transcript(tmp_path, root):
    day = NOW - timedelta(days=1)
    recs = [
        _record(day, "Bash", {"command": "brain status --quick"}, root),
        _record(day, "Bash", {"command": "brain --project demo item show wi-one"}, root),
        _record(day, "Read", {"file_path": str(root / "notes" / "journal.md")}, root),
        _record(day, "Grep", {"pattern": "wi-one", "path": "notes/graph/nodes/work.yaml"}, root),
        _record(day, "Bash", {"command": "grep -n x notes/decisions.md"}, root, "s2"),
        _record(day, "Edit", {"file_path": str(root / "notes" / "decisions.md")}, root),
        _record(day, "Read", {"file_path": str(root.parent / "elsewhere" / "journal.md")}, root),   # not a brain's
        _record(NOW - timedelta(days=40), "Bash", {"command": "brain brief wi-one"}, root),   # before the period
        {"type": "user", "message": {"content": "brain status"}},
        {**_record(day, "Bash", {"command": "brain items"}, root), "timestamp": 12},   # a time that cannot be read
        {**_record(day, "Bash", {"command": "brain items"}, root), "timestamp": "2026-11-10T10:00:00"},   # naive: UTC
    ]
    f = tmp_path / "t.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return f


def test_scan_counts_the_typed_commands_the_hand_reads_and_edits(tmp_path, brain, known):
    seen = adoption.scan([_transcript(tmp_path, brain)], NOW - timedelta(days=28), NOW, *known)
    assert seen == {"typed": {"brain status": 1, "brain item show": 1, "brain items": 1}, "reads": {"journal": 1, "graph": 1, "adr": 1},
                    "edits": {"adr": 1}, "sessions": 2}


def _ledger(home, tasks):
    d = home / "ledger" / "engine"
    d.mkdir(parents=True, exist_ok=True)
    at = (NOW - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    lines = [json.dumps({"v": 1, "kind": "exec", "at": at, "end": at, "host": "h", "project": "brain", "task": t,
                         "version": "0", "duration_s": 0.1, "exit": 0}) for t in tasks]
    (d / f"exec-{NOW:%Y-%m}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_perf_usage_splits_each_commands_runs_and_proposes_for_each_gap(tmp_path, brain, brain_home, capsys,
                                                                       monkeypatch):
    _ledger(brain_home, ["brain status"] * 3 + ["brain item show", "hook guard shell"])
    monkeypatch.setattr(adoption, "_subsessions", lambda since, until: 2)
    assert adoption.main(as_json=True, files=[_transcript(tmp_path, brain)], now=NOW, root=brain) == 0
    rep = json.loads(capsys.readouterr().out)
    rows = {r["command"]: r for r in rep["commands"]}
    assert rows["brain status"] == {"command": "brain status", "module": "status", "runs": 3, "by_session": 1,
                                    "otherwise": 2}
    assert rows["brain item show"]["otherwise"] == 0 and "brain brief" in rep["never_run"]
    reached = {r["command"]: r["via"] for r in rep["reached_otherwise"]}   # main passes the modules' RUNS_VIA
    assert reached["brain capture"].startswith("wired: ") and "brain capture" not in rep["never_run"]
    assert "brain status" not in rep["never_run"] and rep["sessions"] == 2
    kinds = [(p["kind"], p["what"]) for p in rep["proposals"]]
    assert ("hint", "1 hand read(s) of the journal: brain journal last [N] answers") in kinds
    assert ("procedure", "1 hand edit(s) of the decision log: brain adr new writes it") in kinds
    assert ("procedure", "2 sub-session(s) started, brain brief ran 0 time(s)") in kinds
    assert any(k == "wire" and "never ran in the period" in w for k, w in kinds)
    assert adoption.main(files=[], now=NOW, root=brain, top=1) == 0   # the text report
    out = capsys.readouterr().out
    assert out.startswith("adoption: ") and "brain status" in out and "gaps and what to propose" in out
    assert cli.main(["perf", "--usage", "--since", "28d", "--json"]) == 0   # the flag on brain perf
    assert "never_run" in json.loads(capsys.readouterr().out)
    assert cli.main(["perf", "--usage", "--engine"]) == 2


def test_a_have_feature_whose_commands_never_ran(tmp_path, monkeypatch, known):
    units, _ = known
    m = features.Model(features={"feat-a": {"id": "feat-a", "status": "have"}, "feat-b": {"id": "feat-b",
                                                                                          "status": "have"},
                                 "feat-c": {"id": "feat-c", "status": "planned"}},
                       nodes={}, out={"feat-a": [("implemented_by", "code:brain:packages/brain/src/brain/commands/"
                                                                    "brief.py")],
                                      "feat-b": [("implemented_by", "code:brain:packages/brain/src/brain/commands/"
                                                                    "status.py::cmd_status")],
                                      "feat-c": [("implemented_by", "code:brain:packages/brain/src/brain/commands/"
                                                                    "impact.py")]})
    monkeypatch.setattr(features, "load_store", lambda store: m)
    got = adoption.unused_features(tmp_path, units, Counter({"brain status": 4}))
    assert got == [{"feature": "feat-a", "commands": ["brain brief"]}]
    assert adoption.unused_features(None, units, Counter()) == []


def test_runs_via_names_real_units_and_says_how(known):
    """wi-brain-adoption-gaps: each RUNS_VIA entry is a unit of the registry, wired or on demand, so a command a hook
    or another command runs without the CLI, or one the owner runs when its occasion comes, is no gap."""
    units, _ = known
    via = adoption.runs_via()
    assert "brain capture" in via and "brain memory sync" in via and "brain vault seal" in via
    assert all(u in units for u in via), sorted(set(via) - set(units))
    from brain.commands import _registry as registry
    for m in registry.load():   # a module accounts for its own commands only
        name = m.__name__.rsplit(".", 1)[-1]
        assert all(units[f"brain {k}"] == name for k in getattr(m, "RUNS_VIA", None) or {}), name
    assert all(v.startswith(("wired: ", "on demand: ")) for v in via.values())
    assert "brain cost review" not in via   # wired by close-item's step 2b: it must show when it never runs


def test_a_command_reached_another_way_is_listed_apart_not_a_gap(tmp_path, monkeypatch, known):
    units, _ = known
    via = {"brain brief": "wired: a test's hook"}
    rep = adoption.report(units, Counter({"brain status": 1}), {}, NOW - timedelta(days=28), NOW, via=via)
    assert "brain brief" not in rep["never_run"] and "brain impact" in rep["never_run"]
    assert {"command": "brain brief", "via": "wired: a test's hook"} in rep["reached_otherwise"]
    assert any(p["kind"] == "wire" and p["count"] == len(rep["never_run"]) for p in rep["proposals"])
    text = "\n".join(adoption.render(rep))
    assert "reached another way (RUNS_VIA, not a gap):\n  brain brief: wired: a test's hook" in text
    m = features.Model(features={"feat-a": {"id": "feat-a", "status": "have"}}, nodes={},
                       out={"feat-a": [("implemented_by", "code:brain:packages/brain/src/brain/commands/brief.py")]})
    monkeypatch.setattr(features, "load_store", lambda store: m)
    assert adoption.unused_features(tmp_path, units, Counter(), via) == []
    assert adoption.unused_features(tmp_path, units, Counter()) == [{"feature": "feat-a", "commands": ["brain brief"]}]
