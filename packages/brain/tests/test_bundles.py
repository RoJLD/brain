import io
import json
import shutil

import pytest

from brain import bundles, cli, stacks

COMPONENTS = ("otel-collector", "prometheus", "loki", "grafana", "qdrant")
REGISTRY = """\
brain:
  root: {root}
  stacks:
    docker:
      start: [docker-desktop]
      detach: true
      health: {{cmd: [docker, version]}}
    otel-collector: {{bundle: sovereign, depends_on: [loki], health: {{urls: ['http://127.0.0.1:13133/']}},
                     placement: {{run: local, data: home}}}}
    prometheus: {{bundle: sovereign, depends_on: [docker], health: {{urls: ['http://127.0.0.1:9090/-/ready']}}}}
    loki: {{bundle: sovereign, depends_on: [docker], health: {{urls: ['http://127.0.0.1:3100/ready']}}}}
    grafana: {{bundle: sovereign, depends_on: [prometheus, loki], health: {{urls: ['http://127.0.0.1:3000/api/health']}}}}
{qdrant}"""
QDRANT = "    qdrant: {bundle: sovereign, depends_on: [docker], health: {urls: ['http://127.0.0.1:6333/readyz']}}\n"


def _registry(tmp_path, monkeypatch, qdrant=QDRANT):
    f = tmp_path / "projects.yaml"
    f.write_text(REGISTRY.format(root=tmp_path.as_posix(), qdrant=qdrant), encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    return stacks.load()


class Docker:
    """Docker, Compose and the health URLs, faked: a service is healthy once ``docker compose up -d`` started it, an
    image is present once pulled. Nothing real runs."""

    def __init__(self, monkeypatch, up=(), images=(), config=(0, "")):
        self.up, self.images, self.config, self.calls = set(up) | {"docker"}, set(images), config, []
        monkeypatch.setattr(stacks, "_resolve", lambda argv: list(argv))
        monkeypatch.setattr(stacks, "_run", self.run)
        monkeypatch.setattr(stacks, "_probe_url", self.probe)
        monkeypatch.setattr(stacks, "_spawn", lambda argv, cwd: None)
        monkeypatch.setattr(stacks, "_sleep", lambda s: None)
        monkeypatch.setattr(bundles, "_listening", lambda port: False)
        monkeypatch.setattr(stacks, "profile_off", lambda reg, root=None: {})

    PORTS = {"13133": "otel-collector", "9090": "prometheus", "3100": "loki", "3000": "grafana", "6333": "qdrant"}

    def probe(self, url, timeout):
        port = url.split(":")[2].split("/")[0]
        return "" if self.PORTS[port] in self.up else "connection refused"

    def run(self, argv, cwd, timeout):
        cmd = " ".join(argv)
        if cmd == "docker version":
            return 0, "29"
        if " config --quiet" in cmd:
            self.calls.append(("config", cmd))
            return self.config
        if cmd.startswith("docker image inspect"):
            return (0, "sha256:x") if argv[-1] in self.images else (1, "No such image")
        if cmd.startswith("docker compose config --hash") or cmd.startswith("docker compose ps"):
            return 1, ""  # Compose cannot tell: never stale
        self.calls.append((cmd, cwd))
        if cmd.startswith("docker compose pull"):
            doc = bundles.template("sovereign")["services"]
            self.images |= {doc[s]["image"] for s in argv[4:]}
        elif cmd.startswith("docker compose up -d "):
            self.up.add(argv[-1])
        return 0, ""


def test_the_shipped_bundle_is_pinned_loopback_only_and_matches_the_registry(tmp_path, monkeypatch):
    """The checks the plan makes, on the bundle this package ships and a registry that declares its stacks (the ADR's
    guarantees; a personal brain's own registry is checked by its own tests)."""
    reg = _registry(tmp_path, monkeypatch)
    comps = bundles.components(reg, "sovereign")
    assert bundles.names() == ["sovereign"] and sorted(s.name for s in comps) == sorted(COMPONENTS)
    doc, _ = bundles.render("sovereign", comps)
    ok, bad = bundles.problems("sovereign", doc, comps)
    assert bad == [] and ok[:2] == ["5 images pinned by tag and digest", "8 ports published on 127.0.0.1 only"]
    assert all(s.placement == "local" for s in comps)  # the classes and fallbacks are the registry's to declare
    assert {s.name: s.data for s in comps}["otel-collector"] == "home"  # the files DuckDB reads, on the host
    assert {s.data for s in comps if s.name != "otel-collector"} == {"volume"}  # databases in named volumes


def test_render_puts_home_data_under_brain_home_and_names_the_secret_file(tmp_path, monkeypatch, brain_home):
    reg = _registry(tmp_path, monkeypatch)
    doc, files = bundles.render("sovereign", bundles.components(reg, "sovereign"))
    svc = doc["services"]
    assert "./data/otel-collector:/var/lib/otelcol" in svc["otel-collector"]["volumes"]
    assert "qdrant:/qdrant/storage" in svc["qdrant"]["volumes"]
    assert list(doc["volumes"]) == ["prometheus", "loki", "grafana", "qdrant"]  # otel-collector's left the engine
    assert doc["secrets"]["grafana_admin_password"]["file"] == (brain_home / "secrets/grafana-admin-password").as_posix()
    assert sorted(files) == ["compose.yaml", "grafana-datasources.yaml", "loki.yaml", "otelcol.yaml", "prometheus.yml"]
    assert files["compose.yaml"].startswith(b"# Rendered by brain bundle apply")
    assert b"&" not in files["compose.yaml"].split(b"\n", 2)[2]  # the template's anchor written out in full
    monkeypatch.setenv("BRAIN_SECRET_GRAFANA_ADMIN_PASSWORD", str(tmp_path / "pw"))
    doc, _ = bundles.render("sovereign", bundles.components(reg, "sovereign"))
    assert doc["secrets"]["grafana_admin_password"]["file"] == (tmp_path / "pw").as_posix()


@pytest.mark.parametrize("service, problem", [
    ({"image": "qdrant/qdrant:latest"}, "is not pinned by tag and digest"),
    ({"image": "qdrant/qdrant:v1.19.2"}, "is not pinned by tag and digest"),
    ({"image": "qdrant/qdrant:latest@sha256:" + "a" * 64}, "is not pinned by tag and digest"),
    ({"image": "x:1@sha256:" + "a" * 64, "ports": ["6333:6333"]}, "port 6333:6333 is published beyond 127.0.0.1"),
    ({"image": "x:1@sha256:" + "a" * 64, "ports": ["0.0.0.0:6333:6333"]}, "published beyond 127.0.0.1"),
    ({"image": "x:1@sha256:" + "a" * 64, "ports": ["6333"]}, "published beyond 127.0.0.1"),
    ({"image": "x:1@sha256:" + "a" * 64, "ports": [{"target": 6333, "published": 6333}]}, "published beyond"),
    ({"image": "x:1@sha256:" + "a" * 64, "network_mode": "host"}, "network_mode host"),
    ({"image": "x:1@sha256:" + "a" * 64, "build": "."}, "it builds none"),
])
def test_problems_refuse_unpinned_images_and_ports_beyond_loopback(tmp_path, monkeypatch, service, problem):
    reg = _registry(tmp_path, monkeypatch)
    comps = [s for s in bundles.components(reg, "sovereign") if s.name == "qdrant"]
    ok, bad = bundles.problems("sovereign", {"services": {"qdrant": service}}, comps)
    assert ok == [] and any(problem in b for b in bad), bad


def test_problems_match_services_and_components(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch, qdrant="")
    good = {"image": "x:1@sha256:" + "a" * 64, "ports": ["127.0.0.1:1:1", {"host_ip": "127.0.0.1", "published": 2}]}
    comps = bundles.components(reg, "sovereign")
    _, bad = bundles.problems("sovereign", {"services": {"qdrant": good, "loki": good}}, comps)
    assert bad[0] == "service qdrant has no component: declare the stack qdrant with bundle: sovereign in projects.yaml"
    assert "component grafana has no service grafana in compose/sovereign/compose.yaml" in bad


def test_plan_writes_and_starts_nothing_and_says_what_the_apply_does(tmp_path, monkeypatch, brain_home, capsys):
    reg = _registry(tmp_path, monkeypatch)
    fake = Docker(monkeypatch)
    p = bundles.plan(reg, "sovereign")
    assert not (brain_home / "stacks").exists() and [c[0] for c in fake.calls] == ["config"]
    assert set(p.files.values()) == {"new"} and p.folders == ["data/otel-collector"] and p.problems == []
    assert p.volumes == ["brain-sovereign_prometheus", "brain-sovereign_loki", "brain-sovereign_grafana",
                         "brain-sovereign_qdrant"]
    rows = {r["component"]: r for r in p.rows}
    assert list(rows) == ["docker", "loki", "otel-collector", "prometheus", "grafana", "qdrant"]  # dependencies first
    assert rows["docker"]["action"] == "a dependency: up"
    assert rows["qdrant"]["state"] == "DOWN" and rows["qdrant"]["why"] == "not applied"
    assert rows["qdrant"]["action"] == "started" and rows["grafana"]["action"].startswith("waits for its secret file")
    assert p.pull == ["otel-collector", "prometheus", "loki", "qdrant"]  # grafana waits: nothing pulled for it
    assert bundles.main("plan", []) == 0
    out = capsys.readouterr().out
    assert "secret    grafana_admin_password:" in out and "(missing)" in out and "next      brain bundle apply" in out


def test_apply_writes_pulls_and_starts_then_a_second_apply_changes_nothing(tmp_path, monkeypatch, brain_home):
    reg = _registry(tmp_path, monkeypatch)
    fake = Docker(monkeypatch)
    out = io.StringIO()
    assert bundles.apply(reg, "sovereign", out=out) == 0
    where = brain_home / "stacks" / "sovereign"
    assert (where / "compose.yaml").is_file() and (where / "data" / "otel-collector").is_dir()
    run = [c[0] for c in fake.calls if c[0] != "config"]
    assert run == ["docker compose pull --quiet otel-collector prometheus loki qdrant", "docker compose up -d loki",
                   "docker compose up -d otel-collector", "docker compose up -d prometheus",
                   "docker compose up -d qdrant"]
    assert all(c[1] == where for c in fake.calls if c[0] != "config")
    text = out.getvalue()
    assert "grafana WAITS for its secret file" in text and "qdrant OK" in text
    fake.calls.clear()
    out = io.StringIO()
    assert bundles.apply(reg, "sovereign", out=out) == 0
    assert "wrote     nothing (every file unchanged)" in out.getvalue()
    assert not any("pull" in c[0] for c in fake.calls)  # every image present now
    # The owner fills the password file: the next apply starts grafana; its content is never read
    (brain_home / "secrets").mkdir()
    (brain_home / "secrets" / "grafana-admin-password").write_text("x", encoding="utf-8")  # a fake, gitleaks:allow
    fake.calls.clear()
    assert bundles.apply(reg, "sovereign", out=io.StringIO()) == 0
    assert ("docker compose up -d grafana", where) in fake.calls
    assert "docker compose pull --quiet grafana" in [c[0] for c in fake.calls]


def test_apply_refuses_when_a_check_fails(tmp_path, monkeypatch, brain_home):
    reg = _registry(tmp_path, monkeypatch, qdrant="")
    fake = Docker(monkeypatch)
    out = io.StringIO()
    assert bundles.apply(reg, "sovereign", out=out) == 1
    assert "nothing applied (1 problem(s))" in out.getvalue() and not (brain_home / "stacks").exists()
    assert [c for c in fake.calls if c[0] != "config"] == []  # nothing pulled, nothing started
    Docker(monkeypatch, config=(1, "services.qdrant.ports: invalid"))
    reg = _registry(tmp_path, monkeypatch)
    p = bundles.plan(reg, "sovereign")
    assert p.problems == ["docker compose config exited 1: services.qdrant.ports: invalid"]


def test_apply_without_start_writes_only(tmp_path, monkeypatch, brain_home):
    reg = _registry(tmp_path, monkeypatch)
    fake = Docker(monkeypatch)
    out = io.StringIO()
    assert bundles.apply(reg, "sovereign", start=False, out=out) == 0
    assert (brain_home / "stacks" / "sovereign" / "otelcol.yaml").is_file()
    assert [c[0] for c in fake.calls] == ["config"] and "brain up sovereign starts it" in out.getvalue()


def test_cli_bundle_plan_as_json_and_an_unknown_bundle(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch)
    Docker(monkeypatch)
    assert cli.main(["bundle", "plan", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["bundle"] == "sovereign" and "rendered" not in d and d["waiting"].keys() == {"grafana"}
    assert cli.main(["bundle", "plan", "nope"]) == 2
    assert "unknown bundle 'nope' (shipped: sovereign)" in capsys.readouterr().err


@pytest.mark.skipif(not shutil.which("docker"), reason="docker not on the PATH")
def test_docker_compose_config_accepts_the_rendering(tmp_path, monkeypatch):
    """docker compose config (client side: no engine, nothing started) on the template and on the rendering."""
    reg = _registry(tmp_path, monkeypatch)
    _, files = bundles.render("sovereign", bundles.components(reg, "sovereign"))
    assert bundles._compose_config(files) == ("docker compose config OK", "")
    template = {p.name: p.read_bytes() for p in (bundles.ROOT / "sovereign").iterdir() if p.is_file()}
    assert bundles._compose_config(template) == ("docker compose config OK", "")


def test_check_all_refuses_a_registry_the_shipped_bundle_does_not_match(tmp_path, monkeypatch, capsys):
    """brain check --all (and brain refresh in a brain): the bundle the engine ships, rendered with the registry's
    components, has every service a component and every component a service (wi-brain-test-split)."""
    assert cli._bundle_problems(_registry(tmp_path, monkeypatch), "sovereign") == []
    reg = _registry(tmp_path, monkeypatch, qdrant="")
    why = "service qdrant has no component: declare the stack qdrant with bundle: sovereign in projects.yaml"
    assert cli._bundle_problems(reg, "sovereign") == [why]
    assert cli.check_registry(tmp_path, []) == 1
    assert f"error: bundle sovereign: {why}" in capsys.readouterr().out
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "none.yaml"))   # no component declared: nothing to match
    assert cli._bundle_problems(stacks.load(), "sovereign") == []
