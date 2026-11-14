"""wi-brain-rule-usage: the usage counters by tool id (brain.toolids, the token ledger's scan, brain.tooling,
brain usage --kind): every kind of tooling, one id whatever the form a source names it in, the OpenTelemetry export
and the guards ledger joined without counting a call twice, the scope per project, the unused marked."""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from brain import cli, cost, projects, queue, toolids, tooling, usage

FIX = Path(__file__).parent / "fixtures"
TOOLING = FIX / "claude" / "tooling"
OTEL = FIX / "otel"
LAB_SID = "11111111-1111-4111-8111-111111111111"
OTHER_SID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 1, 10, tzinfo=timezone.utc)
RULES = ("- {id: rule-git-prs, type: Rule, status: active, title: \"Worktrees and PRs\"}\n"
         "- {id: rule-never-cited, type: Rule, status: active, title: \"A rule no session cites\"}\n"
         "- {id: rule-retired, type: Rule, status: retired, title: \"Gone\"}\n")


# --- the ids: one tool, whatever the form ---

@pytest.mark.parametrize("path, want", [
    ("/opt/cc/.claude/plugins/cache/market/kit/1.2.0/skills/close-item/SKILL.md", "kit:close-item"),
    (r"D:\cc\.claude\plugins\cache\market\kit\1.2.0\skills\close-item\SKILL.md", "kit:close-item"),
    ("/work/lab/plugins/kit/skills/close-item/SKILL.md", "kit:close-item"),
    (r"D:\work\brain\plugins\kit\skills\close-item\SKILL.md", "kit:close-item"),
    ("/opt/cc/.claude/plugins/marketplaces/market/plugins/kit/skills/close-item/SKILL.md", "kit:close-item"),
    ("/opt/cc/.claude/skills/notes/SKILL.md", "notes"),
    (".claude/skills/notes/SKILL.md", "notes"),
    ("/work/lab/README.md", ""),
])
def test_a_skill_md_path_reads_as_the_skill_call_names_it(path, want):
    assert toolids.skill_of_path(path) == want
    if want:
        assert toolids.skills_in(f"Read {path} and follow it; then {path} again.") == [want]


def test_slash_commands_rule_ids_hooks_and_mcp_ids():
    assert toolids.slash_skill("/kit:review") == "kit:review" and toolids.slash_skill("clear") == ""
    assert toolids.slash_skill("loop") == "loop"
    assert toolids.rule_ids("rule-git-prs, wi-lab-rule-usage and (rule-scout).") == ["rule-git-prs", "rule-scout"]
    assert toolids.hook_id("PreToolUse:mcp__docs__search") == toolids.hook_id("PreToolUse:mcp_tool") \
        == "PreToolUse:mcp_tool"
    assert toolids.hook_id("Stop") == "Stop" and toolids.hook_id("PreToolUse:Bash") == "PreToolUse:Bash"
    assert toolids.mcp_id("docs", "search") == "mcp__docs__search" and toolids.mcp_id("", "x") == ""
    assert toolids.plugin_of_tool("skill", "kit:close-item") == "kit"
    assert toolids.plugin_of_tool("mcp", "mcp__plugin_kit_brain__status") == "kit"
    assert toolids.plugin_of_tool("mcp", "mcp__docs__search") == ""


@pytest.mark.parametrize("line, want", [
    ("brain --project lab item show wi-a && git status", ["brain item show"]),
    ("python -m brain journal add 'done; brain status said ok'", ["brain journal add"]),
    ("BRAIN_HOME=/tmp/h brain.exe --root . check --public", ["brain check"]),
    ("git commit -m \"brain item add x\"", []),
    ("cat <<EOF > f\nbrain status\nEOF", []),
    ("brain alerts --all --notify", ["brain alerts"]),
])
def test_brain_commands_are_program_and_subcommand_never_arguments(line, want):
    assert toolids.brain_command(line) == want


@pytest.mark.parametrize("text, want", [
    ("PreToolUse:Bash hook error: kit guard: git push refused: acme/lab is a public repo (config.json ...", "public"),
    ("PreToolUse:Bash hook error: kit guard: git commit message refused: it holds an AI attribution line", "attribution"),
    ("PreToolUse:Bash hook error: kit guard: git commit refused: a.py:3 (bearer) looks like a secret", "secrets"),
    ("PreToolUse:Bash hook error: kit guard: git commit refused: a.py adds a conflict marker (<<<<<<<)", "markers"),
    ("PreToolUse:Edit hook error: kit guard: Edit refused: a.py is in the production checkout /work/lab", "production"),
    ("PreToolUse:Bash hook error: kit guard: gh repo edit refused: visibility is Ada's alone (a decision)", "owner"),
    ("mcp__x__start_session hook error: kit usage guard: a new session refused until the quota is read", "usage"),
    ("PreToolUse:Bash hook error: kit guard: something new refused", "guard"),
    ("Exit code 1\nrefused: not a hook", ""),
    ("", ""),
])
def test_a_refusal_names_its_guard(text, want):
    assert toolids.refusal_guard(text) == want


def test_rule_files_are_relative_to_the_project_root(tmp_path, monkeypatch):
    """A session started in a subfolder, or that cd's into one, names the root's CLAUDE.md as the inventory does;
    another project's CLAUDE.md is never this one's (never its bare name)."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cc"))
    lab = tmp_path / "lab"
    (lab / ".git").mkdir(parents=True)
    (lab / "sub").mkdir()
    toolids.project_root.cache_clear()
    assert toolids.project_root(str(lab / "sub")) == str(lab) and toolids.project_root("") == ""
    assert toolids.rule_file(str(lab / "CLAUDE.md"), toolids.project_root(str(lab / "sub"))) == "CLAUDE.md"
    assert toolids.rule_file(str(lab / ".claude" / "rules" / "x.md"), str(lab)) == ".claude/rules/x.md"
    other = toolids.rule_file(str(tmp_path / "other" / "CLAUDE.md"), str(lab))
    assert other != "CLAUDE.md" and other.endswith("other/CLAUDE.md") and "\\" not in other
    assert toolids.rule_file(str(tmp_path / "cc" / "CLAUDE.md"), str(lab)) == "~/.claude/CLAUDE.md"
    assert toolids.rule_file(r"D:\cc\.claude\projects\-work-lab\memory\MEMORY.md") == "memory/MEMORY.md"
    assert toolids.is_rule_file("/w/AGENTS.md") and toolids.is_rule_file("/w/.claude/rules/a.md")
    assert not toolids.is_rule_file("/w/README.md")


# --- the scan: real transcript shapes, scrubbed ---

def _transcript(src: Path, dst: Path, **subs: Path) -> Path:
    text = src.read_text(encoding="utf-8")
    for key, path in subs.items():
        text = text.replace(f"__{key}__", json.dumps(str(path))[1:-1])
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return dst


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two projects, lab and other, each with a graph store and one session in the projects folder."""
    cc = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cc))
    projs = []
    for name in ("lab", "other"):
        root = tmp_path / name
        store = root / "notes" / "graph"
        (store / "nodes").mkdir(parents=True)
        (store / "edges").mkdir()
        (store / "edges.yaml").write_text("", encoding="utf-8")
        (store / "nodes" / "rules.yaml").write_text(RULES if name == "lab" else "", encoding="utf-8")
        projs.append(projects.Project(name=name, root=root, stores=[store]))
    lab, other = projs
    pdir = cc / "projects"
    _transcript(TOOLING / "lab.jsonl", pdir / "-work-lab" / f"{LAB_SID}.jsonl", LAB=lab.root, HOME=cc)
    _transcript(TOOLING / "other.jsonl", pdir / "-work-other" / f"{OTHER_SID}.jsonl", OTHER=other.root, HOME=cc)
    return lab, other, pdir


def _row(pdir, sid):
    return usage.scan(next(pdir.glob(f"*/{sid}.jsonl")))


def test_the_scan_counts_every_kind_by_tool_id(world):
    lab, other, pdir = world
    t = _row(pdir, LAB_SID)["tooling"]
    skill = t["skill"]["kit:close-item"]
    # a Skill call, a Read of its SKILL.md and an Agent's prompt naming it: one skill, three uses
    assert (skill["calls"], skill["call"], skill["read"], skill["agent"]) == (3, 1, 1, 1)
    assert skill["cost"] > 0 and skill["chars"] > 800   # the turn it drove, the SKILL.md it read
    assert t["skill"]["kit:review"]["slash"] == 1 and "clear" not in t["skill"]
    assert t["rule"]["rule-git-prs"]["cited"] == 1 and "rule-usage" not in t["rule"]
    assert t["rule"]["CLAUDE.md"]["loaded"] == 1 and t["rule"]["memory/MEMORY.md"]["loaded"] == 1
    assert t["rule"]["CLAUDE.md"]["chars"] == len("# lab\n\nRun the tests before a PR.\n")
    assert set(t["command"]) == {"brain item show", "brain journal add", "brain status"}
    assert t["command"]["brain status"]["fails"] == 1
    hooks = t["hook"]
    assert hooks["PreToolUse:Bash"]["calls"] == 2 and hooks["PreToolUse:Bash"]["timeouts"] == 1
    assert hooks["PreToolUse:Bash"]["fails"] == 1 and hooks["PreToolUse:Bash"]["ms"] == 450 + 5436
    injected = next(json.loads(x)["attachment"]["content"][0] for x in (TOOLING / "lab.jsonl").open(encoding="utf-8")
                    if "hook_additional_context" in x)
    assert hooks["SessionStart:startup"]["chars"] == len(injected)   # the context it injected, its own name filled in
    assert hooks["PreToolUse:mcp_tool"]["calls"] == 1 and hooks["Stop"]["calls"] == 1
    assert t["guard"] == {"public": {"calls": 1}}
    assert _row(pdir, LAB_SID)["refused"] == {"toolu_fixture0004": "public"}


# --- the report ---

_UNITS: list = []


@pytest.fixture
def units():
    """The CLI registry's units, built once (inside a test: it reads the tests' BRAIN_HOME)."""
    if not _UNITS:
        _UNITS.append(tooling.registry_units())
    return _UNITS[0]


def _ledger(world, rows=None):
    lab, other, pdir = world
    rows = rows if rows is not None else [_row(pdir, LAB_SID), _row(pdir, OTHER_SID)]
    return cost.Ledger(rows, [lab, other], queue.Placer([lab, other]))


def _report(world, units, projs=None, kind="all", led=None, **kw):
    lab, other, _ = world
    projs = projs or [lab, other]
    led = cost.scoped(led or _ledger(world), projs, False)
    kw.setdefault("inv", {})
    kw.setdefault("runs", [])
    kw.setdefault("otel_dir", OTEL)
    return tooling.report(led, projs, "2026-01-01", "", kind, now=NOW, units=units, **kw)


def _by(rep, kind):
    return {r["id"]: r for r in rep["rows"] if r["kind"] == kind}


def test_one_projects_counts_never_reach_the_other(world, units):
    lab, other, _ = world
    both = _report(world, units)
    assert _by(both, "skill")["kit:close-item"]["sessions"] == 2
    assert _by(both, "skill")["kit:close-item"]["projects"] == ["lab", "other"]
    only = _report(world, units, projs=[lab])
    sk = _by(only, "skill")["kit:close-item"]
    assert (sk["calls"], sk["sessions"], sk["projects"]) == (3, 1, ["lab"])
    assert only["sessions"] == 1 and "attribution" not in _by(only, "guard")   # the other's refusal stays there
    assert _by(_report(world, units, projs=[other]), "skill")["kit:close-item"]["calls"] == 1


def test_the_export_adds_durations_and_rejections_and_never_counts_a_call_twice(world, units):
    rep = _report(world, units)
    hooks = _by(rep, "hook")
    # PreToolUse:Bash: the transcript holds 2 runs of session 1111, the export 1: the larger count, not the sum;
    # the other session's 1 run (transcript) is added as its own
    assert hooks["PreToolUse:Bash"]["calls"] == 3
    assert hooks["UserPromptSubmit"]["calls"] == 2   # only the export holds it: one run per session
    assert hooks["PreToolUse:Bash"]["ms"]["n"] == 1 and hooks["PreToolUse:Bash"]["ms"]["p50"] == 469
    mcp = _by(rep, "mcp")["mcp__docs__search"]   # the transcript's name and the export's mcp_tool read alike
    assert mcp["calls"] == 1 and mcp["rejects"] == {"hook": 1} and mcp["ms"]["n"] == 2
    assert rep["sources"]["otel"]["read"] and rep["sources"]["otel"]["sessions"] == 2
    assert rep["misses"]["hook_runs_otel_only"] > 0


def test_a_refusal_in_the_guards_ledger_and_the_transcript_counts_once(world, units, tmp_path):
    led = tmp_path / "ledger"
    led.mkdir()
    lines = [
        {"at": "2026-01-05T09:00:31Z", "event": "guard", "guard": "public", "check": "public", "decision": "denied",
         "tool": "Bash", "session_id": LAB_SID, "tool_use_id": "toolu_fixture0004"},
        {"at": "2026-01-05T09:00:50Z", "event": "guard", "guard": "secrets", "check": "secrets", "decision": "denied",
         "tool": "Bash", "session_id": LAB_SID},                                      # no tool use id: the ledger's
        {"at": "2026-01-05T09:00:51Z", "event": "guard", "guard": "heredoc", "check": "backslash",
         "decision": "warned", "session_id": LAB_SID, "tool_use_id": "t9"},          # a warning, no refusal
        {"at": "2026-01-05T09:00:52Z", "event": "guard", "guard": "owner", "decision": "denied",
         "session_id": "not-in-scope", "tool_use_id": "t8"},
    ]
    (led / "guards-2026-01.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json {\n",
                                              encoding="utf-8")
    rep = _report(world, units, kind="guard", guards_dir=led)
    g = _by(rep, "guard")
    assert g["public"]["calls"] == 1 and g["secrets"]["calls"] == 1 and g["attribution"]["calls"] == 1
    assert "owner" not in g and "heredoc" not in g
    assert rep["misses"] == {"matched": 1, "transcript_only": 1, "ledger_only": 1}
    assert all(not r["mark"] for r in rep["rows"])   # a guard that refuses nothing still guards: never marked


def test_unused_for_30_days_is_marked_retire_or_merge(world, units):
    lab, other, pdir = world
    old = _row(pdir, LAB_SID)
    old["session_id"] = "old"
    old["start"], old["end"] = "2025-11-01T10:00:00Z", "2025-11-01T11:00:00Z"
    old["days"] = {"2025-11-01": {"cost": 1.0}}
    old["tooling"]["skill"]["kit:ancient"] = {"calls": 2}
    led = _ledger(world, [old, _row(pdir, LAB_SID)])
    inv = {"skill": {"kit:close-item": {"lab"}, "kit:shelved": {"lab"}},
           "rule": {"rule-git-prs": {"lab"}, "rule-never-cited": {"lab"}}}
    known, alias, via = units
    known = {**known, "brain zz-never": "x", "brain zz-wired": "x", "brain zz-ran": "x"}
    rep = _report(world, units=(known, alias, {**via, "brain zz-wired": "wired: a hook"}), projs=[lab], led=led,
                  inv=inv, runs=[("brain zz-ran", "2026-01-08")])
    sk, rl, cm = _by(rep, "skill"), _by(rep, "rule"), _by(rep, "command")
    assert sk["kit:close-item"]["mark"] == "" and sk["kit:close-item"]["last_used"] == "2026-01-05"
    assert sk["kit:shelved"]["mark"] == tooling.MARK and sk["kit:shelved"]["last_used"] == ""   # never
    assert sk["kit:ancient"]["mark"] == tooling.MARK and sk["kit:ancient"]["last_used"] == "2025-11-01"
    assert sk["kit:ancient"]["calls"] == 0   # out of the window: no calls counted, only its last use
    assert rl["rule-never-cited"]["mark"] == tooling.MARK and rl["rule-git-prs"]["mark"] == ""
    assert cm["brain zz-never"]["mark"] == tooling.MARK
    assert cm["brain zz-wired"]["mark"] == "" and cm["brain zz-wired"]["reached"] == "wired: a hook"
    assert cm["brain zz-ran"]["mark"] == "" and cm["brain item show"]["mark"] == ""
    assert "script" not in {r["kind"] for r in rep["rows"] if r["mark"]}   # programs are never marked
    text = "\n".join(tooling.render(rep, top=3))
    assert "« retire or merge », unused since 2025-12-11" in text and "kit:shelved" in text


def test_a_rule_id_no_rule_node_has_is_not_counted_and_the_inventory_reads_the_graph(world, units):
    lab, other, _ = world
    rep = _report(world, units, projs=[lab], kind="rule", inv=None)
    rl = _by(rep, "rule")
    assert "rule-git-prs" in rl and "rule-retired" not in rl
    assert rl["rule-never-cited"]["mark"] == tooling.MARK
    assert rl["CLAUDE.md"]["loaded"] == 1


def test_an_older_row_without_the_counters_still_gives_its_skills_and_commands(world, units):
    lab, other, pdir = world
    r = _row(pdir, LAB_SID)
    for k in ("tooling", "refused"):
        r.pop(k)
    r["skills"] = {"kit:close-item": {"calls": 1, "cost": 0.5}, "clear": {"calls": 1}}
    r["commands"] = {"brain item show": {"calls": 2, "cost": 0.2}, "git push": {"calls": 1}}
    rep = _report(world, units, projs=[lab], led=_ledger(world, [r]))
    assert _by(rep, "skill")["kit:close-item"]["calls"] == 1 and "clear" not in _by(rep, "skill")
    assert _by(rep, "command")["brain item show"]["calls"] == 2
    assert _by(rep, "script")["git push"]["calls"] == 1


def test_no_export_and_a_garbage_export_are_said_not_fatal(world, units, tmp_path):
    rep = _report(world, units, kind="hook", otel_dir=tmp_path / "none")
    assert rep["sources"]["otel"]["read"] is False and _by(rep, "hook")["PreToolUse:Bash"]["calls"] == 3
    bad = tmp_path / "otel"
    bad.mkdir()
    (bad / "logs.jsonl").write_text("garbage\n{\"resourceLogs\": 3}\n", encoding="utf-8")
    rep = _report(world, units, kind="hook", otel_dir=bad)
    assert rep["sources"]["otel"]["bad_lines"] == 1 and rep["sources"]["otel"]["sessions"] == 0


def test_the_scheduled_tasks_read_the_engines_runs(world, units, monkeypatch, brain_home):
    lab, other, _ = world
    eng = brain_home / "ledger" / "engine"
    eng.mkdir(parents=True)
    ev = [{"v": 1, "kind": "exec", "at": f"2026-01-0{d}T03:00:00Z", "end": f"2026-01-0{d}T03:00:00Z",
           "project": "brain", "task": "brain alerts", "duration_s": 0.4, "exit": 0} for d in (2, 8)]
    ev.append({"v": 1, "kind": "exec", "end": "2026-01-08T03:00:00Z", "task": "hook guard shell", "duration_s": 0.1})
    (eng / "exec-2026-01.jsonl").write_text("\n".join(json.dumps(e) for e in ev) + "\n{cut", encoding="utf-8")
    runs = tooling.engine_runs(datetime(2025, 12, 1, tzinfo=timezone.utc), NOW)
    assert runs == [("brain alerts", "2026-01-02"), ("brain alerts", "2026-01-08")]
    monkeypatch.setattr(tooling, "schedule_units", lambda projs, registry: {"alerts-pass": "brain alerts",
                                                                           "dead": "brain vault canary"})
    rep = _report(world, units, projs=[lab], kind="scheduled", runs=runs,
                  inv={"scheduled": {"alerts-pass": {"lab"}, "dead": {"lab"}}})
    s = _by(rep, "scheduled")
    assert s["alerts-pass"]["calls"] == 2 and s["alerts-pass"]["last_used"] == "2026-01-08"
    assert s["alerts-pass"]["mark"] == "" and s["dead"]["mark"] == tooling.MARK


def test_the_inventory_holds_the_projects_skills_rules_and_schedules(world, monkeypatch):
    lab, other, _ = world
    skill = lab.root / ".claude" / "skills" / "notes" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: notes\ndescription: Take notes.\n---\n", encoding="utf-8")
    (lab.root / "CLAUDE.md").write_text("# lab\n", encoding="utf-8")
    monkeypatch.setattr(tooling, "_schedules", lambda projs, registry: [("nightly", "lab", ["alerts", "--all"])])
    inv = tooling.inventory([lab])
    assert inv["skill"]["notes"] == {"lab"} and inv["rule"]["CLAUDE.md"] == {"lab"}
    assert set(inv["rule"]) >= {"rule-git-prs", "rule-never-cited"} and "rule-retired" not in inv["rule"]
    assert inv["scheduled"]["nightly"] == {"lab"}
    assert tooling.schedule_units([lab], None) == {"nightly": "brain alerts"}
    assert "notes" not in tooling.inventory([other])["skill"]   # the other project's inventory is its own


def test_cli_usage_kind_json_and_text(world, units, capsys, monkeypatch):
    lab, other, pdir = world
    rows = {f"p/{sid}.jsonl": _row(pdir, sid) for sid in (LAB_SID, OTHER_SID)}
    usage.save(rows)
    monkeypatch.setattr(tooling, "registry_units", lambda: units)
    monkeypatch.setattr(tooling, "engine_runs", lambda since, until: [])
    root = str(lab.root)
    assert cli.main(["--root", root, "usage", "--kind", "skill", "--since", "2026-01-01", "--no-scan", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["kind"] == "skill" and {r["kind"] for r in rep["rows"]} == {"skill"}
    assert cli.main(["--root", root, "usage", "--kind", "all", "--since", "2026-01-01", "--no-scan"]) == 0
    out = capsys.readouterr().out
    assert "brain usage --kind all" in out and "Brain commands" in out
    with pytest.raises(SystemExit) as exc:
        cli.main(["--root", root, "usage", "--kind", "nope"])
    assert exc.value.code == 2


def test_counted_kinds_and_their_titles_agree():
    assert set(tooling.TITLES) == set(toolids.KINDS) and set(tooling.MARKED) <= set(toolids.KINDS)
    assert Counter(toolids.KINDS).most_common(1)[0][1] == 1


# --- the review of #236 ---

def test_an_older_row_that_ran_python_m_brain_alone_reads(world, units):
    """« python -m brain » with no command (--version, an option first) is a key of an older row's commands: no
    command, and no crash."""
    lab, other, pdir = world
    r = _row(pdir, LAB_SID)
    for k in ("tooling", "refused"):
        r.pop(k)
    r["commands"] = {"python -m brain": {"calls": 1}, "brain item show": {"calls": 2}}
    rep = _report(world, units, projs=[lab], led=_ledger(world, [r]))
    assert _by(rep, "command")["brain item show"]["calls"] == 2


def test_a_ledger_refusal_without_a_tool_use_id_counts_once():
    misses = Counter()
    got = tooling.guard_counts({"refused": {"toolu_1": "public"}, "tooling": {}},
                               [{"guard": "public", "session_id": "s", "decision": "denied"}], misses)
    assert got == Counter({"public": 1}) and misses == Counter({"matched_by_guard": 1})


def test_a_tool_the_export_alone_saw_is_used_not_marked():
    from collections import defaultdict
    accs = defaultdict(tooling.Acc)
    row = {"session_id": "s", "project": "lab", "start": "2026-01-05T09:00:00Z", "tools": {}}
    got = {"s": {"hooks": {}, "tools": {("mcp", "mcp__srv__q"): [12.0]}, "rejects": {}, "results": {}}}
    tooling._add_otel(accs, got, {"s": row}, ("mcp",), Counter())
    assert accs[("mcp", "mcp__srv__q")].last == "2026-01-05"


def test_a_brain_command_keeps_its_registry_unit_never_an_argument():
    assert usage._brain_units("brain capture acme-merger && brain item show wi-x") == ["brain capture",
                                                                                       "brain item show"]


def test_a_rule_id_is_not_counted_without_the_scope_s_rule_nodes():
    r = {"tooling": {"rule": {"rule-usage": {"calls": 1}, "CLAUDE.md": {"loaded": 1}}}}
    got = {tid for kind, tid, _ in tooling.row_tools(r, rules=None) if kind == "rule"}
    assert got == {"CLAUDE.md"}   # a branch name such as feat/rule-usage cites no rule
