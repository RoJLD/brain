"""wi-brain-resources-view: the sampler (brain.resources) with psutil absent and present (a fake module), docker stats
down, slow and answering garbage, its real payload as a fixture, the CLI's --json keys, the thresholds; the cockpit's
band and its detail in test_tui_resources below (Textual only)."""

import collections
import contextlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain import classes, cli, quota, resources, resources_view, stacks, usage

FIXTURES = Path(__file__).parent / "fixtures" / "docker"
STATS = (FIXTURES / "stats.jsonl").read_text(encoding="utf-8")   # a real docker stats payload, names invented
DOWN = (FIXTURES / "down.txt").read_text(encoding="utf-8")       # what the client says when the engine is not there
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
CLI_A = "11111111-2222-4333-8444-555555555555"
CLI_B = "66666666-7777-4888-9999-aaaaaaaaaaaa"
FORKED = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"


# --- the thresholds and the small parsers ---------------------------------------------------------------------------

def test_the_levels_are_warn_at_85_and_critical_at_95():
    assert [resources.level(p) for p in (0, 84.9, 85, 94.9, 95, 100, None, "x")] == [
        "ok", "ok", "warn", "warn", "critical", "critical", "unknown", "unknown"]
    b = {"cpu_pct": 96.0, "mem_pct": 86.0, "disk_pct": 50.0, "disk": "C:\\", "quota_level": "warn", "quota_pct": 70,
         "pace_x": 1.3}
    lv = resources.levels(b)
    assert [x["what"] for x in lv][0] == "cpu" and {x["what"] for x in lv} == {"cpu", "memory", "quota"}
    assert resources.worst({"levels": lv}) == "critical" and resources.worst({"levels": []}) == "ok"


def test_docker_sizes_and_percents_parse_and_garbage_gives_none():
    assert resources.parse_size("75.66MiB") == int(75.66 * 2 ** 20)
    assert resources.parse_size("1.06MB") == 1_060_000 and resources.parse_size("0B") == 0
    assert resources.parse_size("--") is None and resources.parse_size("12 parsecs") is None
    assert resources._pair("383kB / 784kB") == (383_000, 784_000)
    assert resources._pct("1.31%") == 1.31 and resources._pct("--") is None


# --- docker stats: the real payload, the stacks that declare each container, and the failures ----------------------

def _stacks(tmp_path):
    bundle = tmp_path / "home" / "stacks" / "sovereign"
    bundle.mkdir(parents=True)
    (bundle / "compose.yaml").write_text("# a bundle\nname: brain-sovereign\nservices: {}\n", encoding="utf-8")
    graph = tmp_path / "CodeGraph"
    graph.mkdir()
    out = [stacks.Stack(name, "lab", ["docker", "compose", "up", "-d", name], cwd=bundle, bundle="sovereign")
           for name in ("qdrant", "grafana", "prometheus", "loki")]
    out.append(stacks.Stack("codegraph", "acme", ["docker", "compose", "up", "-d"], cwd=graph,
                            index={"container": "codegraph"}))
    return out


def test_the_real_payload_parses_and_each_container_finds_its_stack(tmp_path):
    rows, bad = resources.parse_stats(STATS, _stacks(tmp_path))
    assert bad == 0 and len(rows) == 8
    by = {r["name"]: r for r in rows}
    q = by["brain-sovereign-qdrant-1"]
    assert q["mem_bytes"] == int(75.66 * 2 ** 20) and q["mem_limit_bytes"] == int(31.3 * 2 ** 30)
    assert q["cpu_pct"] == 0.32 and q["pids"] == 58 and q["net_rx_bytes"] == 383_000 and len(q["id"]) == 12
    assert (q["stack"], q["project"]) == ("qdrant", "lab")
    # the bundle's otel-collector is declared by no stack here: said, not guessed
    assert by["brain-sovereign-otel-collector-1"]["stack"] == ""
    # a Compose stack: its index.container, then its project's prefix
    assert {by[n]["stack"] for n in ("codegraph", "codegraph-graphs", "codegraph-web")} == {"codegraph"}
    assert by["codegraph-web"]["project"] == "acme"


def test_the_compose_project_is_the_p_flag_the_file_name_or_the_folder(tmp_path):
    s = stacks.Stack("x", "lab", ["docker", "compose", "-p", "Mine", "up"], cwd=tmp_path)
    assert resources._compose_project(s) == "mine"
    d = tmp_path / "My Stack"
    d.mkdir()
    assert resources._compose_project(stacks.Stack("x", "lab", ["docker", "compose", "up"], cwd=d)) == "mystack"


def _docker(monkeypatch, state, code=0, out=""):
    monkeypatch.setattr(resources, "_which", lambda name: "docker")
    calls = []

    def run(argv, timeout):
        calls.append((argv, timeout))
        return state, code, out
    monkeypatch.setattr(resources, "_run", run)
    return calls


def test_docker_ok_reads_stats_once_without_streaming(monkeypatch, tmp_path):
    calls = _docker(monkeypatch, "ok", 0, STATS)
    c = resources.containers(_stacks(tmp_path))
    assert c["state"] == "ok" and len(c["rows"]) == 8 and c["why"] == ""
    assert calls == [(["docker", "stats", "--no-stream", "--format", "{{json .}}"], resources.DOCKER_TIMEOUT)]


def test_docker_absent_down_slow_and_garbage_are_states_never_errors(monkeypatch):
    monkeypatch.setattr(resources, "_which", lambda name: None)
    assert resources.containers()["state"] == "absent"
    _docker(monkeypatch, "ok", 1, DOWN)
    c = resources.containers()
    assert c["state"] == "down" and "failed to connect to the docker API" in c["why"] and c["rows"] == []
    _docker(monkeypatch, "slow")
    assert resources.containers(timeout=0.5) == {"state": "slow", "why": "docker stats gave no answer in 0.5 s",
                                                 "rows": []}
    _docker(monkeypatch, "absent")
    assert resources.containers()["state"] == "absent"
    _docker(monkeypatch, "ok", 0, "<html>502 Bad Gateway</html>\n{\"no\": \"name\"}\n[1, 2]\n")
    c = resources.containers()
    assert c["state"] == "garbage" and "3 line(s)" in c["why"]
    _docker(monkeypatch, "ok", 0, "WARNING: something\n" + STATS)   # a stray line among real ones: skipped, said
    c = resources.containers()
    assert c["state"] == "ok" and len(c["rows"]) == 8 and c["why"] == "1 line(s) skipped"


def test_a_slow_program_is_killed_at_its_timeout_and_said_slow():
    state, code, _ = resources._run([sys.executable, "-c", "import time; time.sleep(30)"], 0.5)
    assert (state, code) == ("slow", None)
    assert resources._run(["brain-no-such-program-xyz"], 2.0)[0] == "absent"


# --- the machine without psutil (the standard library's readers, faked) ---------------------------------------------

def _feed(monkeypatch, cpu, net):
    cpu, net = iter(cpu), iter(net)
    monkeypatch.setattr(resources, "_cpu_times", lambda ps=None: next(cpu))
    monkeypatch.setattr(resources, "_net_counters", lambda ps=None: next(net))
    monkeypatch.setattr(resources, "_memory", lambda: {"committed_pct": 88.0, "commit_total": 88, "commit_limit": 100,
                                                       "total": 64 * 2 ** 30, "available": 20 * 2 ** 30,
                                                       "nonpaged": 2 ** 30})
    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(resources, "_disk_usage", lambda p: Usage(1000, 960, 40))


def test_without_psutil_the_band_reads_the_stdlib_counters_and_says_its_levels(monkeypatch):
    clock = iter([100.0, 102.0, 104.0])
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(clock))
    # idle and total CPU seconds; a 32-bit counter that wraps between the second and third readings
    _feed(monkeypatch, [(100.0, 200.0), (110.0, 220.0), (111.0, 240.0)],
          [({"aa": (1000, 500)}, 2 ** 32), ({"aa": (3000, 900)}, 2 ** 32), ({"aa": (100, 1300)}, 2 ** 32)])
    s = resources.Sampler(ps=None)
    first = s.band()
    assert first["cpu_pct"] is None and first["up_bps"] is None and first["source"] == "stdlib"
    b = s.band()
    assert b["cpu_pct"] == 50.0 and b["mem_pct"] == 88.0 and b["disk_pct"] == 96.0
    assert (b["down_bps"], b["up_bps"]) == (1000, 200)
    assert {x["what"]: x["level"] for x in b["levels"]} == {"memory": "warn", "disk": "critical"}
    third = s.band()
    assert third["cpu_pct"] == 95.0 and third["down_bps"] == (2 ** 32 - 3000 + 100) // 2   # the wrap counted
    assert len(s.history) == 3 and set(s.history[-1]) == {"at", "cpu_pct", "mem_pct", "up_bps", "down_bps"}
    assert isinstance(b["cost_ms"], float)
    p = s.processes()
    assert p["available"] is False and "psutil" in p["why"] and p["rows"] == []


def test_the_band_words_and_the_narrow_band():
    b = {"cpu_pct": 23.4, "mem_pct": 96.0, "disk_pct": 64.0, "disk": "C:\\", "up_bps": 12_000, "down_bps": 1_500_000,
         "tokens": 1_234_567, "quota_pct": 42.0, "pace_x": 0.8, "quota_level": "ok"}
    parts = resources_view.band_parts(b)
    assert [t for t, _ in parts] == ["CPU 23 %", "RAM 96 %", "C: 64 %", "\u219112K \u21931.4M", "1.2M tok",
                                     "quota 42 % 0.8x"]
    assert [lv for _, lv in parts][:2] == ["ok", "critical"]
    assert [t for t, _ in resources_view.band_parts(b, narrow=True)] == ["CPU 23 %", "RAM 96 %", "quota 42 % 0.8x"]
    assert resources_view.band_parts({"error": "boom"}) == [("resources: boom", "unknown")]
    empty = resources_view.band_text({"quota_level": "unknown"})
    assert empty.startswith("CPU - \u00b7 RAM -") and empty.endswith("quota -")


def test_the_stdlib_net_dev_reader_leaves_loopback_out():
    text = ("Inter-|   Receive\n face |bytes packets errs drop fifo frame compressed multicast|bytes\n"
            "    lo: 500 5 0 0 0 0 0 0 500 5 0 0 0 0 0 0\n"
            "  eth0: 1000 10 0 0 0 0 0 0 2000 20 0 0 0 0 0 0\n")
    assert resources.parse_net_dev(text) == {"eth0": (1000, 2000)}


def test_the_real_stdlib_readers_answer_or_say_none():
    """On the machine that runs the suite: each reader gives its shape or None, never raises."""
    t = resources._cpu_times(None)
    assert t is None or (len(t) == 2 and t[1] >= t[0] >= 0)
    n = resources._net_counters(None)
    assert n is None or isinstance(n[0], dict)
    m = resources._memory()
    assert set(m) == {"committed_pct", "commit_total", "commit_limit", "total", "available", "nonpaged"}


# --- the ledger and the quota: read from files, never computed ------------------------------------------------------

def _ledger(rows):
    usage.ledger_file().parent.mkdir(parents=True, exist_ok=True)
    usage.save(rows)


def _row(sid, folder, tokens_today, usd_today, yesterday=0):
    days = {TODAY: {"cost": usd_today, "messages": 3, "output": 10, "tokens": tokens_today}}
    if yesterday:
        days["2000-01-01"] = {"cost": 9.0, "messages": 1, "output": 1, "tokens": yesterday}
    return {"session_id": sid, "folder": folder, "title": f"Task {sid[:4]}", "days": days}


def test_tokens_today_sums_the_utc_day_only_and_reparses_only_a_changed_ledger(monkeypatch):
    s = resources.Sampler(ps=None)
    assert s.tokens_today()["tokens"] is None and "no token ledger" in s.tokens_today()["why"]
    _ledger({"a.jsonl": _row(CLI_A, "/w/a", 1000, 0.5, yesterday=99_999), "b.jsonl": _row(CLI_B, "/w/b", 250, 0.25)})
    t = s.tokens_today()
    assert (t["tokens"], t["usd"], t["sessions"]) == (1250, 0.75, 2) and t["ledger_at"]
    assert t["by_session"][CLI_A] == {"tokens": 1000, "usd": 0.5, "folder": "/w/a", "title": "Task 1111"}

    def boom():
        raise AssertionError("parsed again")
    monkeypatch.setattr(usage, "load", boom)
    assert s.tokens_today()["tokens"] == 1250   # the same file: the cache


def test_a_ledger_that_cannot_be_read_is_said(monkeypatch):
    _ledger({})
    monkeypatch.setattr(usage, "load", lambda: (_ for _ in ()).throw(ValueError("a newer engine wrote it")))
    t = resources.Sampler(ps=None).tokens_today()
    assert t["tokens"] is None and "a newer engine wrote it" in t["why"]


def test_the_quota_is_the_last_forecast_with_its_pace_and_the_capacity_line():
    s = resources.Sampler(ps=None)
    assert s.quota() == {"level": "unknown", "why": "no quota forecast yet (brain usage quota)"}
    quota.save_status({"window": "week", "pct_now": 40.0, "pace": {"pct_h": 0.5, "at_reset": 88.0}, "level": "p0p1",
                       "now": "2026-11-13T10:00:00Z", "conversion": {"usd_per_pct": 20.0},
                       "session_hour": {"usd": 10.0}})
    q = s.quota()
    assert q["pace_x"] == 0.8 and q["level"] == "warn" and q["pct_now"] == 40.0
    assert q["capacity"] == {"session_hours": 120.0, "for_20": 6.0, "session_hour_usd": 10.0}


def test_the_overhead_is_pending_until_a_source_is_plugged(monkeypatch):
    assert resources.overhead()["state"] == "pending" and "rule usage" in resources.overhead()["why"]

    def broken():
        raise RuntimeError("x")
    monkeypatch.setattr(resources, "OVERHEAD_SOURCES", [broken, lambda: {"tokens": 1200, "share_pct": 3.5,
                                                                         "source": "rules"}])
    assert resources.overhead() == {"state": "ok", "tokens": 1200, "share_pct": 3.5, "sources": ["rules"]}


# --- the processes with psutil present (a fake module) ---------------------------------------------------------------

class FakeError(Exception):
    pass


class FakeProc:
    def __init__(self, pid, ppid, name, cmd=(), exe="", rss=100, private=0, cwd="", cpu=1.0, denied=False):
        self.pid, self.info = pid, {"pid": pid, "ppid": ppid, "name": name}
        self.cmd, self._exe, self.rss, self.private, self._cwd, self.cpu, self.denied = (
            list(cmd), exe, rss, private, cwd, cpu, denied)

    def oneshot(self):
        return contextlib.nullcontext()

    def cmdline(self):
        if self.denied:
            raise FakeError("access denied")
        return self.cmd

    def exe(self):
        return self._exe

    def memory_info(self):
        return SimpleNamespace(rss=self.rss, private=self.private)

    def cpu_times(self):
        return SimpleNamespace(user=self.cpu, system=0.0)

    def create_time(self):
        return 1.0

    def cwd(self):
        if not self._cwd:
            raise FakeError("no cwd")
        return self._cwd


CPU = collections.namedtuple("scputimes", "user system idle guest")
NET = collections.namedtuple("snetio", "bytes_sent bytes_recv")


class FakePsutil:
    Error = FakeError

    def __init__(self, procs):
        self.procs = procs
        self.cpu = iter([CPU(50.0, 50.0, 100.0, 7.0), CPU(60.0, 60.0, 120.0, 9.0)] + [CPU(60.0, 60.0, 120.0, 9.0)] * 9)
        self.net = iter([{"eth0": NET(100, 1000), "lo": NET(5, 5)}] + [{"eth0": NET(300, 1400), "lo": NET(9, 9)}] * 9)

    def process_iter(self, attrs):
        assert attrs == ["pid", "ppid", "name"]
        return iter(self.procs)

    def cpu_count(self):
        return 4

    def cpu_times(self):
        return next(self.cpu)

    def net_io_counters(self, pernic):
        assert pernic is True
        return next(self.net)


def _app_session(tmp_path, host, cli_id, cwd, title, archived=False):
    d = tmp_path / "appdata" / "Claude-Data" / "x" / "claude-code-sessions" / "a" / "b"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{host}.json").write_text(json.dumps({
        "sessionId": host, "cliSessionId": cli_id, "cwd": str(cwd), "title": title, "isArchived": archived,
        "lastActivityAt": 1, "lastTurnReport": "never read"}), encoding="utf-8")


def _machine(tmp_path):
    wa, wb = tmp_path / "wt-a", tmp_path / "wt-b"
    wa.mkdir()
    wb.mkdir()
    cli_bin = str(tmp_path / "claude-code" / "2.1" / "claude.exe")
    procs = [
        FakeProc(1, 0, "Claude.exe", [r"C:\Program Files\WindowsApps\Claude_5\app\Claude.exe"],
                 exe=r"C:\Program Files\WindowsApps\Claude_5\app\Claude.exe", rss=900),            # the desktop app
        FakeProc(2, 1, "Claude.exe", ["Claude.exe", "--type=renderer"], exe="x", rss=800),        # its renderer
        FakeProc(10, 1, "claude.exe", [cli_bin, "--output-format", "stream-json", f"--resume={CLI_A}"],
                 exe=cli_bin, rss=300, private=350, cwd=str(wa), cpu=4.0),                       # tied by its flags
        FakeProc(11, 10, "node.exe", ["node", "mcp-server.js"], rss=50),                          # its MCP server
        FakeProc(12, 10, "python.exe", ["python", "-m", "pytest", "-n", "2"], rss=70),            # its suite...
        FakeProc(13, 12, "python.exe", ["python", "-m", "pytest", "--worker"], rss=40),           # ...and a worker
        FakeProc(20, 1, "claude.exe", [cli_bin, f"--resume={FORKED}", "--fork-session"], exe=cli_bin, rss=200,
                 cwd=str(wb)),                                                                    # tied by its folder
        FakeProc(30, 0, "brain.exe", [r"C:\x\brain.exe", "tui", "--plain"], rss=60),              # a brain command
        FakeProc(31, 0, "python.exe", denied=True),                                               # unreadable
        FakeProc(40, 0, "explorer.exe", ["explorer.exe"], rss=5000),                              # not the Brain's
    ]
    _app_session(tmp_path, "local_aaaaaaaa-0000-4000-8000-000000000001", CLI_A, wa, "Session A")
    _app_session(tmp_path, "local_bbbbbbbb-0000-4000-8000-000000000002", CLI_B, wb, "Session B")
    _ledger({"a.jsonl": _row(CLI_A, str(wa), 5000, 1.5), "c.jsonl": _row("cccccccc-0000-4000-8000-000000000003",
                                                                       str(tmp_path / "gone"), 700, 0.2)})
    return procs


def _sampled(monkeypatch, tmp_path):
    procs = _machine(tmp_path)
    ps = FakePsutil(procs)
    monkeypatch.setattr(resources, "_disk_usage",
                        lambda p: collections.namedtuple("U", "total used free")(1000, 500, 500))
    monkeypatch.setattr(resources.time, "sleep", lambda s: procs[2].__setattr__("cpu", 6.0))
    ticks = iter(range(1000))
    monkeypatch.setattr(resources.time, "monotonic", lambda: next(ticks) * 0.25)
    s = resources.Sampler(ps=ps)
    return s.sample(docker=False, walks=False)


def test_with_psutil_the_machine_the_brain_commands_and_the_suites(monkeypatch, tmp_path):
    doc = _sampled(monkeypatch, tmp_path)
    m = doc["machine"]
    assert m["source"] == "psutil" and m["cores"] == 4 and m["cpu_pct"] == 50.0   # guest time not counted twice
    assert (m["network"]["down_bps"] > 0, m["network"]["up_bps"] > 0) == (True, True)
    pr = doc["processes"]
    assert pr["available"] and pr["counted"] == 10
    assert [b["what"] for b in pr["brain"]] == ["tui"]
    assert [x["pid"] for x in pr["suites"]] == [12] and pr["suites"][0]["tree_bytes"] == 110   # its worker in it
    assert doc["containers"]["state"] == "skipped" and doc["stores"]["state"] == "skipped"
    assert doc["overhead"]["state"] == "pending"


def test_with_psutil_each_cli_is_tied_to_its_session_and_its_tree_counted(monkeypatch, tmp_path):
    doc = _sampled(monkeypatch, tmp_path)
    by = {x["cli"]: x for x in doc["sessions"]}
    a = by[CLI_A]
    assert a["how"] == "command line" and a["session"].startswith("local_aaaaaaaa") and a["title"] == "Session A"
    assert a["tree_bytes"] == 300 + 50 + 70 + 40 and a["children"] == 3 and a["private"] == 350
    assert a["tokens_today"] == 5000 and a["live"] and a["cpu_pct"] is not None
    b = by[CLI_B]
    assert b["how"] == "folder" and b["session"].startswith("local_bbbbbbbb") and b["tokens_today"] is None
    gone = by["cccccccc-0000-4000-8000-000000000003"]
    assert gone["live"] is False and gone["how"] == "ledger" and gone["tokens_today"] == 700
    assert [x["live"] for x in doc["sessions"]] == [True, True, False]   # the live first
    assert doc["one_more_session_bytes"] in (200, 460)


def test_a_cli_whose_folder_two_sessions_hold_or_whose_flags_only_fork_is_said_unknown():
    a = {"cliSessionId": CLI_A, "cwd": "/w/x"}
    b = {"cliSessionId": CLI_B, "cwd": "/w/x"}
    by_cwd = {resources._norm("/w/x"): [a, b]}
    assert resources.tie({}, "/w/x", {}, by_cwd) == ("", "folder held by 2 sessions")
    assert resources.tie({"forked_from": FORKED}, "/w/y", {}, by_cwd) == ("", "forked from bbbbbbbb")
    assert resources.tie({}, "", {}, {}) == ("", "unknown (no folder readable)")
    assert resources.session_flags(["claude", "--session-id", CLI_A.upper()]) == {"id": CLI_A}
    assert resources.session_flags(["claude", "-r", CLI_A, "--fork-session"]) == {"forked_from": CLI_A}
    assert resources.session_flags(["claude", "--resume", "not-a-uuid"]) == {}


def test_what_a_process_is():
    assert resources.kind_of("claude", "/opt/claude/bin/claude", ["claude"]) == "cli"
    assert resources.kind_of("claude", "/Applications/Claude.app/Contents/MacOS/Claude", []) == ""
    assert resources.kind_of("node", "", ["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"]) == "cli"
    assert resources.kind_of("node", "", ["node", "server.js"]) == ""
    assert resources.kind_of("python", "", ["python", "-m", "brain", "usage"]) == "brain"
    assert resources.kind_of("python", "", ["python", "/venv/bin/brain", "status"]) == "brain"
    assert resources.kind_of("python", "", ["python", "-m", "pytest"]) == "suite"
    assert resources.kind_of("python", "", ["/venv/bin/pytest", "tests"]) == "suite"
    assert resources.kind_of("python", "", ["python", "app.py"]) == ""
    assert resources.brain_what(["python", "-m", "brain", "--root", "x", "usage"]) == "usage"   # past the flags
    assert resources.brain_what(["python", "-m", "brain", "--version"]) == ""
    assert resources.brain_what([r"C:\v\brain.exe", "tui"]) == "tui"


def test_the_app_sessions_are_read_through_the_closed_list_of_keys():
    assert classes.outside("app-sessions", set(resources.APP_KEYS)) == []


# --- the projects: each one's count stays its own -------------------------------------------------------------------

def test_by_project_sums_each_project_apart_and_project_scope_filters(monkeypatch, tmp_path):
    sess = [{"project": "lab", "live": True, "tree_bytes": 100, "cpu_pct": 2.0, "tokens_today": 10, "usd_today": 1.0},
            {"project": "lab", "live": False, "tree_bytes": None, "cpu_pct": None, "tokens_today": 5, "usd_today": 0.5},
            {"project": "acme", "live": True, "tree_bytes": 40, "cpu_pct": 1.0, "tokens_today": 0, "usd_today": 0.0}]
    cont = {"rows": [{"project": "acme", "mem_bytes": 1000, "cpu_pct": 0.5}, {"project": "", "mem_bytes": 7,
                                                                              "cpu_pct": 0.0}]}
    rows = {r["project"]: r for r in resources.by_project(sess, cont)}
    assert rows["lab"] == {"project": "lab", "sessions_live": 1, "sessions_today": 2, "tree_bytes": 100,
                           "cpu_pct": 2.0, "tokens_today": 15, "usd_today": 1.5, "containers": 0,
                           "container_bytes": 0, "container_cpu_pct": 0.0}
    assert rows["acme"]["containers"] == 1 and rows["acme"]["tokens_today"] == 0 and rows["acme"]["tree_bytes"] == 40
    assert list(rows)[-1] == ""   # the folders no project holds, last

    _feed(monkeypatch, [(1.0, 2.0)] * 4, [({}, None)] * 4)
    monkeypatch.setattr(resources, "_placer", lambda projs: lambda folder: "lab" if "lab" in folder else "acme")
    monkeypatch.setattr(resources, "containers", lambda st: {"state": "ok", "why": "", "rows": [
        {"name": "x", "project": "acme"}, {"name": "y", "project": "lab"}]})
    _ledger({"a.jsonl": _row(CLI_A, "/w/lab", 10, 0.1), "b.jsonl": _row(CLI_B, "/w/other", 20, 0.2)})
    doc = resources.Sampler(project="lab", ps=None).sample(walks=False, prime=False)
    assert [s["project"] for s in doc["sessions"]] == ["lab"]
    assert [p["project"] for p in doc["projects"]] == ["lab"] and doc["projects"][0]["tokens_today"] == 10
    assert [c["name"] for c in doc["containers"]["rows"]] == ["y"]


# --- the stores ------------------------------------------------------------------------------------------------------

def test_the_stores_are_brain_homes_entries_with_a_bounded_walk(monkeypatch, brain_home, tmp_path):
    monkeypatch.setattr(resources.tempfile, "gettempdir", lambda: str(tmp_path / "temp"))
    (brain_home / "usage").mkdir(parents=True)
    (brain_home / "usage" / "sessions.json").write_text("x" * 300, encoding="utf-8")
    (brain_home / "machine.json").write_text("{}", encoding="utf-8")
    st = resources.stores()
    by = {r["name"]: r for r in st["rows"]}
    assert by["usage"]["bytes"] == 300 and by["usage"]["complete"] and by["machine.json"]["bytes"] == 2
    monkeypatch.setattr(resources, "_size", lambda root, budget: (5, False))
    assert {r["complete"] for r in resources.stores()["rows"] if r["name"] == "usage"} == {False}
    lines = resources_view.render({"v": 1, "at": "t", "levels": [], "stores": resources.stores()})
    assert any("at least" in ln for ln in lines)


# --- the command ---------------------------------------------------------------------------------------------------

def _quiet_machine(monkeypatch, tmp_path):
    _feed(monkeypatch, [(1.0, 2.0)] * 40, [({}, None)] * 40)
    monkeypatch.setattr(resources, "_psutil", lambda: None)
    monkeypatch.setattr(resources.time, "sleep", lambda s: None)
    monkeypatch.setattr(resources.tempfile, "gettempdir", lambda: str(tmp_path))


def test_cli_json_keys_by_section_and_text(monkeypatch, capsys, tmp_path):
    _quiet_machine(monkeypatch, tmp_path)
    monkeypatch.setattr(resources, "_which", lambda name: None)   # no docker here
    root = str(tmp_path)
    assert cli.main(["--root", root, "resources", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) == {"v", "at", "machine", "processes", "sessions", "containers", "stores", "tokens", "quota",
                        "overhead", "projects", "levels", "one_more_session_bytes", "cost_ms"}
    assert doc["v"] == 1 and doc["containers"]["state"] == "absent" and doc["processes"]["available"] is False
    assert set(doc["machine"]) == {"name", "os", "cores", "cpu_pct", "memory", "disks", "network", "source"}
    assert [(x["what"], x["level"]) for x in doc["levels"]] == [("disk", "critical"), ("memory", "warn")]
    for by, key in (("machine", "machine"), ("project", "projects"), ("session", "sessions"),
                    ("container", "containers"), ("store", "stores")):
        assert cli.main(["--root", root, "resources", "--by", by, "--json", "--quick"]) == 0
        part = json.loads(capsys.readouterr().out)
        assert {"v", "at", "levels", key} <= set(part) and not ({"sessions", "stores"} - {key}) & set(part)
    assert cli.main(["--root", root, "resources", "--quick"]) == 0
    text = capsys.readouterr().out
    assert "WARN     committed memory 88 %" in text and "containers (skipped: --quick)" in text
    assert "the process rows need psutil" in text


def test_cli_exits_1_when_the_sample_fails(monkeypatch, capsys, tmp_path):
    def boom(self, **kw):
        raise OSError("the machine cannot be read")
    monkeypatch.setattr(resources.Sampler, "sample", boom)
    assert cli.main(["--root", str(tmp_path), "resources"]) == 1
    assert "the machine cannot be read" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["--root", str(tmp_path), "resources", "--by", "galaxy"])
    assert e.value.code == 2
