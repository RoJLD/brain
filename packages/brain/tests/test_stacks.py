import http.server
import io
import json
import socket
import threading

import pytest

from brain import cli, stacks

REGISTRY = """\
infra:
  root: {tmp}/infra
  stacks:
    docker:
      start: [docker-desktop]
      detach: true
      health: {{cmd: [docker, info]}}
      timeout: 30
app:
  root: {tmp}/app
  stacks:
    gitnexus:
      depends_on: [docker]
      cwd: ../GitNexus
      start: [docker, compose, up, -d]
      stop: [docker, compose, stop]
      health: {{urls: ['http://localhost:4747/api/health', 'http://localhost:4173']}}
      logs: [docker, compose, logs, --tail, '30']
      timeout: 20
{extra}"""


def _registry(tmp_path, monkeypatch, extra="", text=None):
    f = tmp_path / "projects.yaml"
    f.write_text(text if text is not None else REGISTRY.format(tmp=tmp_path.as_posix(), extra=extra),
                 encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    return f


class Fake:
    """Docker and HTTP: a stack is healthy once up, or ``delay`` seconds after its start; time is simulated."""

    def __init__(self, monkeypatch, up=(), delay=None, fail=None, logs="", missing=()):
        self.t, self.up, self.started, self.calls = 0.0, set(up), {}, []
        self.delay = {"docker": 5, "gitnexus": 3, **(delay or {})}
        self.fail, self.logs, self.missing = fail or {}, logs, set(missing)
        monkeypatch.setattr(stacks, "_clock", lambda: self.t)
        monkeypatch.setattr(stacks, "_sleep", self.sleep)
        monkeypatch.setattr(stacks, "_probe_url", self.probe)
        monkeypatch.setattr(stacks, "_run", self.run)
        monkeypatch.setattr(stacks, "_spawn", self.spawn)
        monkeypatch.setattr(stacks, "_resolve", lambda argv: None if argv[0] in self.missing else list(argv))

    def sleep(self, s):
        self.t += s

    def healthy(self, name):
        return name in self.up or (name in self.started and self.t - self.started[name] >= self.delay[name])

    def probe(self, url, timeout):
        return "" if self.healthy("gitnexus") else "[WinError 10061] connection refused"

    def spawn(self, argv, cwd):
        self.calls.append(("spawn", " ".join(argv)))
        self.started["docker"] = self.t

    def run(self, argv, cwd, timeout):
        cmd = " ".join(argv)
        if cmd == "docker info":
            return (0, "Server Version: 27") if self.healthy("docker") else (1, "Client:\nerror during connect: "
                                                                               "pipe not found")
        self.calls.append(("run", cmd, cwd))
        if cmd in self.fail:
            return self.fail[cmd]
        if cmd == "docker compose up -d":
            self.started["gitnexus"] = self.t
        elif cmd == "docker compose stop":
            self.up.discard("gitnexus")
            self.started.pop("gitnexus", None)
        elif cmd.startswith("docker compose logs"):
            return 0, self.logs
        return 0, ""


def _lines(fn, *args, **kw):
    out = io.StringIO()
    rc = fn(*args, out=out, **kw)
    return rc, out.getvalue().splitlines()


def test_registry_reads_every_project_and_resolves_cwd(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    reg = stacks.load()
    assert list(reg) == ["docker", "gitnexus"]
    g = reg["gitnexus"]
    assert g.project == "app" and g.cwd == (tmp_path / "GitNexus").resolve()
    assert g.start == ["docker", "compose", "up", "-d"] and g.timeout == 20 and not g.watch and not g.detach
    assert reg["docker"].detach and reg["docker"].health_cmd == ["docker", "info"]
    assert reg["docker"].cwd == (tmp_path / "infra").resolve()
    assert [s.name for s in stacks.plan(reg, ["gitnexus"])] == ["docker", "gitnexus"]


def test_registry_reads_a_stacks_file_and_splits_string_commands(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "stacks.yaml").write_text("web: {start: 'serve --port 8000', health: {urls: 'http://localhost:8000'}}\n",
                                      encoding="utf-8")
    _registry(tmp_path, monkeypatch, text=f"proj: {{root: {root.as_posix()}, stacks: stacks.yaml}}\n")
    web = stacks.load()["web"]
    assert web.start == ["serve", "--port", "8000"] and web.health_urls == ["http://localhost:8000"]


@pytest.mark.parametrize("extra, message", [
    ("other: {root: x, stacks: {gitnexus: {start: [a], health: {cmd: [b]}}}}", "declared by app and other"),
    ("other: {root: x, stacks: {web: {start: [a], health: {cmd: [b]}, port: 1}}}", "unknown key(s) port"),
    ("other: {root: x, stacks: {web: {start: [a]}}}", "no health check"),
    ("other: {root: x, stacks: {web: {health: {cmd: [b]}}}}", "no start command"),
    ("other: {root: x, stacks: {web: {start: [a], health: {cmd: [b]}, placement: k8s}}}", "not supported"),
    ("other: {root: x, stacks: {Web: {start: [a], health: {cmd: [b]}}}}", "a name is lowercase"),
])
def test_registry_refuses_bad_declarations(tmp_path, monkeypatch, extra, message):
    _registry(tmp_path, monkeypatch, extra)
    with pytest.raises(stacks.StackError, match=message.replace("(", r"\(").replace(")", r"\)")):
        stacks.load()


def test_plan_refuses_unknown_stacks_dependencies_and_cycles(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, "other: {root: x, stacks: {a: {start: [a], health: {cmd: [a]}, depends_on: [b]}, "
                                     "b: {start: [b], health: {cmd: [b]}, depends_on: [a]}, "
                                     "c: {start: [c], health: {cmd: [c]}, depends_on: [nope]}}}")
    reg = stacks.load()
    with pytest.raises(stacks.StackError, match="unknown stack"):
        stacks.plan(reg, ["web"])
    with pytest.raises(stacks.StackError, match="dependency cycle: a -> b -> a"):
        stacks.plan(reg, ["a"])
    with pytest.raises(stacks.StackError, match="depends on unknown stack 'nope'"):
        stacks.plan(reg, ["c"])
    assert stacks.main("up", ["web"]) == 2


def test_up_starts_dependencies_first_and_waits_for_health(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch)
    rc, lines = _lines(stacks.up, stacks.load(), ["gitnexus"])
    assert rc == 0 and lines == ["docker OK (5 s)", "gitnexus OK (3 s)"]
    assert fake.calls == [("spawn", "docker-desktop"),
                          ("run", "docker compose up -d", (tmp_path / "GitNexus").resolve())]


def test_up_leaves_a_healthy_stack_alone_but_applies_a_compose_file(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch, up={"docker", "gitnexus"})
    rc, lines = _lines(stacks.up, stacks.load(), [])
    assert rc == 0 and lines == ["docker OK (already up)", "gitnexus OK (0 s, compose file applied)"]
    assert fake.calls == [("run", "docker compose up -d", (tmp_path / "GitNexus").resolve())]  # idempotent in Compose


def test_up_force_runs_the_start_command_of_a_named_healthy_stack(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch, up={"docker", "gitnexus"})
    rc, lines = _lines(stacks.up, stacks.load(), ["docker"], force=True)
    assert rc == 0 and lines == ["docker OK (0 s)"] and fake.calls == [("spawn", "docker-desktop")]


@pytest.mark.parametrize("start, base", [
    ("[docker, compose, up, -d]", ["docker", "compose"]),
    ("[docker, compose, -f, prod.yml, -p, gn, up, -d]", ["docker", "compose", "-f", "prod.yml", "-p", "gn"]),
    ("['C:/Program Files/Docker/docker.exe', compose, up]", ["C:/Program Files/Docker/docker.exe", "compose"]),
    ("[docker-desktop]", None), ("[docker, compose, start]", None), ("[docker, run, up]", None)])
def test_compose_stacks_are_recognised_by_their_start_command(tmp_path, monkeypatch, start, base):
    _registry(tmp_path, monkeypatch, f"other: {{root: x, stacks: {{web: {{start: {start}, health: {{cmd: [b]}}}}}}}}")
    assert stacks._compose(stacks.load()["web"]) == base


CONFIG = "docker compose config --hash *"
PS = 'docker compose ps -a --format {{.Service}} {{.Label "com.docker.compose.config-hash"}}'
BOTH = "gitnexus aaa\ngitnexus-web bbb\n"


@pytest.mark.parametrize("config, ps, line", [
    ((0, BOTH), (0, BOTH), "gitnexus OK"),
    ((0, BOTH), (0, "gitnexus old\ngitnexus-web bbb\n"),
     "gitnexus STALE: gitnexus differs from the compose file; brain up gitnexus applies it"),
    ((0, BOTH), (0, "gitnexus old\n"),
     "gitnexus STALE: gitnexus, gitnexus-web differ from the compose file; brain up gitnexus applies it"),
    ((1, "no configuration file provided"), (0, "gitnexus old\n"), "gitnexus OK"),  # Compose cannot tell: not stale
    ((0, BOTH), (1, "error"), "gitnexus OK")])
def test_health_reports_a_compose_stack_whose_containers_differ_from_the_file(tmp_path, monkeypatch, config, ps,
                                                                              line):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch, up={"docker", "gitnexus"}, fail={CONFIG: config, PS: ps})
    rc, lines = _lines(stacks.health, stacks.load(), ["gitnexus", "docker"])
    assert lines == [line, "docker OK"] and rc == (1 if "STALE" in line else 0)
    assert all(c[2] == (tmp_path / "GitNexus").resolve() for c in fake.calls)


def test_up_reports_a_stack_that_never_gets_healthy_and_skips_its_dependents(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    Fake(monkeypatch, delay={"docker": 999})
    rc, lines = _lines(stacks.up, stacks.load(), ["gitnexus"])
    assert rc == 1
    assert lines == ["docker FAILED (30 s): not healthy after 30 s: docker info exited 1: error during connect: "
                     "pipe not found", "gitnexus SKIPPED (docker failed)"]


def test_up_reports_the_useful_log_line(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    Fake(monkeypatch, up={"docker"}, delay={"gitnexus": 999},
         logs="gitnexus-1 | starting\ngitnexus-1 | Error: EADDRINUSE 4747\ngitnexus-1 | exiting")
    rc, lines = _lines(stacks.up, stacks.load(), ["gitnexus"])
    assert rc == 1 and lines[1] == ("gitnexus FAILED (20 s): not healthy after 20 s: http://localhost:4747/api/health: "
                                    "[WinError 10061] connection refused | log: gitnexus-1 | Error: EADDRINUSE 4747")


def test_up_reports_a_failed_or_missing_start_command(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    Fake(monkeypatch, up={"docker"}, fail={"docker compose up -d": (1, "pulling\nno such file: docker-compose.yml")})
    rc, lines = _lines(stacks.up, stacks.load(), ["gitnexus"])
    assert rc == 1 and lines[1] == "gitnexus FAILED (0 s): start exited 1: no such file: docker-compose.yml"
    Fake(monkeypatch, missing={"docker-desktop"})
    rc, lines = _lines(stacks.up, stacks.load(), ["docker"])
    assert rc == 1 and lines == ["docker FAILED (0 s): start command not found: docker-desktop"]


def test_down_runs_stop_commands_in_reverse_order(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch, up={"docker", "gitnexus"})
    rc, lines = _lines(stacks.down, stacks.load(), [])
    assert rc == 0 and lines == ["gitnexus stopped (0 s)", "docker left alone (no stop command)"]
    assert fake.calls == [("run", "docker compose stop", (tmp_path / "GitNexus").resolve())]
    fake = Fake(monkeypatch)  # Docker is off: nothing to stop, nothing run
    rc, lines = _lines(stacks.down, stacks.load(), ["gitnexus"])
    assert rc == 0 and lines == ["gitnexus down (docker is down)"] and fake.calls == []
    Fake(monkeypatch, up={"docker"}, fail={"docker compose stop": (1, "permission denied")})
    rc, lines = _lines(stacks.down, stacks.load(), ["gitnexus"])
    assert rc == 1 and lines == ["gitnexus FAILED (0 s): stop exited 1: permission denied"]


def test_health_checks_watched_named_or_every_stack(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    Fake(monkeypatch, up={"docker"})
    rc, lines = _lines(stacks.health, stacks.load(), [])
    assert rc == 0 and lines == ["no watched stack; brain health --all checks the 2 declared (docker, gitnexus)"]
    rc, lines = _lines(stacks.health, stacks.load(), [], every=True)
    assert rc == 1 and lines == ["docker OK", "gitnexus DOWN: http://localhost:4747/api/health: [WinError 10061] "
                                              "connection refused"]
    rc, lines = _lines(stacks.health, stacks.load(), ["docker"])
    assert rc == 0 and lines == ["docker OK"]


def _hook(capsys):
    assert stacks.hook_main(["SessionStart"], io.StringIO('{"cwd": "."}')) == 0
    out = capsys.readouterr().out
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


def test_hook_is_silent_for_stopped_on_demand_stacks_and_reports_watched_ones(tmp_path, monkeypatch, capsys):
    f = _registry(tmp_path, monkeypatch)
    Fake(monkeypatch)
    assert _hook(capsys) == ""  # nothing watched, everything stopped: on demand
    f.write_text(f.read_text(encoding="utf-8").replace("      timeout: 20", "      timeout: 20\n      watch: true"),
                 encoding="utf-8")
    text = _hook(capsys)
    assert text.startswith("1 watched stack(s) down. `brain up gitnexus` starts them")
    assert "- gitnexus (app): http://localhost:4747/api/health" in text
    Fake(monkeypatch, up={"docker", "gitnexus"})
    assert _hook(capsys) == ""


def test_hook_stays_within_its_budget(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, "other: {root: x, stacks: {a: {start: [a], health: {cmd: [slow]}, watch: true}, "
                                     "b: {start: [b], health: {cmd: [slow]}, watch: true}}}")
    fake = Fake(monkeypatch)
    timeouts = []

    def slow(argv, cwd, timeout):
        timeouts.append(timeout)
        fake.t += timeout
        return None, ""
    monkeypatch.setattr(stacks, "_run", slow)
    text = _hook(capsys)
    assert timeouts == [stacks.HOOK_CMD_TIMEOUT, stacks.HOOK_BUDGET - stacks.HOOK_CMD_TIMEOUT]
    assert "2 watched stack(s) down" in text and "slow: no answer in 1 s" in text


def test_hook_never_fails_and_logs_its_errors(tmp_path, monkeypatch, capsys, brain_home):
    _registry(tmp_path, monkeypatch, text="app: {root: x, stacks: {web: {start: [a]}}}\n")
    assert _hook(capsys) == ""
    log = (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")
    assert "stacks-health:" in log and "no health check" in log


def test_cli_dispatches_stack_commands_outside_any_repo(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch)
    Fake(monkeypatch, up={"docker", "gitnexus"})
    monkeypatch.chdir(tmp_path)
    assert cli.main(["health", "--all"]) == 0
    assert capsys.readouterr().out.splitlines() == ["docker OK", "gitnexus OK"]
    assert cli.main(["up", "nope"]) == 2
    assert "unknown stack(s) nope" in capsys.readouterr().err


BUNDLE = ("box: {root: x, stacks: {db: {bundle: b, depends_on: [docker], health: {urls: 'http://localhost:4747/api/health'}"
          ", placement: {run: local, data: home}}, ui: {bundle: b, depends_on: [db], health: {cmd: [docker, info]}}}}")


@pytest.mark.parametrize("placement, message", [
    ("{run: k8s://brain}", "placement 'k8s://brain' is not supported (only: local) (planned"),
    ("ssh://node-b", "placement 'ssh://node-b' is not supported"),
    ("{data: nas:/brain}", "placement data 'nas:/brain' is not supported (only: home, volume) (planned"),
    ("{data: disk}", "placement data 'disk' is not supported (only: home, volume)"),
    ("{run: local, where: x}", "placement is a string or a mapping of run and data")])
def test_placement_says_where_a_stack_runs_and_where_its_data_lives(tmp_path, monkeypatch, placement, message):
    _registry(tmp_path, monkeypatch, f"other: {{root: x, stacks: {{web: {{start: [a], health: {{cmd: [b]}}, "
                                     f"placement: {placement}}}}}}}")
    with pytest.raises(stacks.StackError, match=message.replace("(", r"\(").replace(")", r"\)")):
        stacks.load()


def test_a_bundle_component_takes_its_commands_from_its_bundle(tmp_path, monkeypatch, brain_home):
    _registry(tmp_path, monkeypatch, BUNDLE)
    reg = stacks.load()
    db = reg["db"]
    assert db.bundle == "b" and db.data == "home" and db.placement == "local" and reg["ui"].data == "volume"
    assert db.cwd == brain_home / "stacks" / "b" and db.start == ["docker", "compose", "up", "-d", "db"]
    assert db.stop == ["docker", "compose", "stop", "db"] and db.logs[-1] == "db"
    assert stacks.expand(reg, ["b", "docker", "db"]) == ["db", "ui", "docker"]
    _registry(tmp_path, monkeypatch, "box: {root: x, stacks: {db: {bundle: b, start: [a], health: {cmd: [b]}}}}")
    with pytest.raises(stacks.StackError, match=r"commands from its bundle \(no start\)"):
        stacks.load()


def test_a_bundle_not_applied_is_skipped_by_up_left_alone_by_down_and_down_in_health(tmp_path, monkeypatch,
                                                                                       brain_home):
    _registry(tmp_path, monkeypatch, BUNDLE)
    fake = Fake(monkeypatch, up={"docker"})
    reg = stacks.load()
    why = "bundle b not applied (brain bundle plan b, then brain bundle apply b)"
    rc, lines = _lines(stacks.up, reg, [])
    assert rc == 0 and f"db SKIPPED ({why})" in lines and f"ui SKIPPED ({why})" in lines  # unnamed: not a failure
    assert not any("compose up -d db" in c[1] for c in fake.calls)  # nothing started before the owner's apply
    rc, lines = _lines(stacks.up, reg, ["ui"])
    assert rc == 1
    rc, lines = _lines(stacks.down, reg, ["db"])
    assert rc == 0 and lines == [f"db left alone ({why})"]
    rc, lines = _lines(stacks.health, reg, ["db"])
    assert rc == 1 and lines == [f"db DOWN: {why}"]
    assert stacks.main("health", ["b"]) == 1
    (brain_home / "stacks" / "b").mkdir(parents=True)
    (brain_home / "stacks" / "b" / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    fake.up.add("gitnexus")  # db's health URL answers
    rc, lines = _lines(stacks.up, stacks.load(), ["db"])
    assert rc == 0 and lines == ["docker OK (already up)", "db OK (0 s, compose file applied)"]
    assert ("run", "docker compose up -d db", brain_home / "stacks" / "b") in fake.calls


def test_a_bundle_component_is_stale_only_for_its_own_service(tmp_path, monkeypatch, brain_home):
    _registry(tmp_path, monkeypatch, BUNDLE)
    (brain_home / "stacks" / "b").mkdir(parents=True)
    (brain_home / "stacks" / "b" / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    Fake(monkeypatch, up={"docker", "gitnexus"}, fail={CONFIG: (0, "db aaa\nui bbb\n"), PS: (0, "db aaa\n")})
    assert stacks.state(stacks.load()["db"]) == ("OK", "")  # ui never started: not db's drift
    Fake(monkeypatch, up={"docker", "gitnexus"}, fail={CONFIG: (0, "db aaa\nui bbb\n"), PS: (0, "db old\n")})
    assert stacks.state(stacks.load()["db"]) == ("STALE", "db differs from the compose file; brain up db applies it")


def test_useful_line_prefers_the_last_error():
    assert stacks.useful_line("a\nERROR: port taken\nb\n") == "ERROR: port taken"
    assert stacks.useful_line("a\nlast\n\n") == "last"
    assert stacks.useful_line("") == ""


def test_probe_url_against_a_local_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's name
            self.send_response(200 if self.path == "/ok" else 503)
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        assert stacks._probe_url(f"{base}/ok", 2) == ""
        assert stacks._probe_url(f"{base}/down", 2) == "HTTP 503"
    finally:
        srv.shutdown()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert stacks._probe_url(f"http://127.0.0.1:{port}/", 1)  # nothing listens: a reason, not ''


def test_health_sh_end_to_end_reports_a_watched_stack_down_and_is_silent_once_up(tmp_path, brain_home):
    """The SessionStart script itself (the bash wrapper Claude Code runs), with the interpreter of BRAIN_PYTHON."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from test_capture import PLUGIN, _bash
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    py = Path(sys.executable).as_posix()
    reg = tmp_path / "projects.yaml"

    def run(code: int) -> subprocess.CompletedProcess:
        reg.write_text(f"app:\n  root: {tmp_path.as_posix()}\n  stacks:\n    web:\n      start: [a]\n"
                       f"      health: {{cmd: ['{py}', -c, 'raise SystemExit({code})']}}\n      watch: true\n",
                       encoding="utf-8")
        env = dict(os.environ, BRAIN_HOME=str(brain_home), BRAIN_PYTHON=sys.executable, BRAIN_PROJECTS=str(reg))
        return subprocess.run([bash, str(PLUGIN / "hooks" / "health.sh")], input='{"cwd": "."}', capture_output=True,
                              text=True, env=env, timeout=60)
    down = run(3)
    assert down.returncode == 0
    assert "1 watched stack(s) down" in json.loads(down.stdout)["hookSpecificOutput"]["additionalContext"]
    up = run(0)
    assert up.returncode == 0 and up.stdout == ""
