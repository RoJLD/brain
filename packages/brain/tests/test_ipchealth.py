"""wi-brain-local-ipc-auth: brain health ipc (brain.ipchealth) and the collector's opt-in token (brain.bundles)."""

import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml
from brain import bundles, config, ipcauth, ipchealth, mcpserver
from test_bundles import _registry


def _config(tmp_path, monkeypatch, ipc=None):
    """The tests' owner's config.json, with an ipc block when given."""
    data = {"v": 1, "identity": {"owner": "Ada", "kind": "person"}}
    if ipc is not None:
        data["ipc"] = ipc
    f = tmp_path / "cfg" / "config.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    return config.load()


@pytest.fixture
def no_docker(monkeypatch):
    monkeypatch.setattr(ipchealth, "_docker", lambda argv: (None, ""))
    monkeypatch.setattr(ipchealth, "index_containers", lambda root=None: [])


def _run(cfg, named=True):
    out = io.StringIO()
    rc = ipchealth.health(cfg, named=named, out=out)
    return rc, out.getvalue().splitlines()


# --- the token and the MCP server -------------------------------------------------------------------------------------

def test_nothing_running_is_off_and_silent_under_all(tmp_path, monkeypatch, no_docker):
    monkeypatch.setattr(ipchealth, "probe_mcp", lambda port: ("OFF", "mcp: nothing answers"))
    cfg = _config(tmp_path, monkeypatch)
    assert _run(cfg, named=False) == (0, [])
    rc, lines = _run(cfg)
    assert rc == 0 and lines[0].startswith("ipc OFF no usable token") and "ipc OFF mcp: nothing answers" in lines


def test_a_required_token_that_is_missing_fails(tmp_path, monkeypatch, no_docker):
    monkeypatch.setattr(ipchealth, "probe_mcp", lambda port: ("OFF", "mcp: nothing answers"))
    rc, lines = _run(_config(tmp_path, monkeypatch, {"require_token": ["otel-collector"]}))
    assert rc == 1 and lines[0].startswith("ipc FAIL no usable token") and "otel-collector" in lines[0]
    rc, lines = _run(_config(tmp_path, monkeypatch, {"require_token": ["qdrant"]}))
    assert rc == 1 and any("only otel-collector can require the token" in line for line in lines)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_token_readable_beyond_its_owner_fails():
    f, _ = ipcauth.init()
    assert ipchealth.token_state()[0] == "OK"
    f.chmod(0o644)
    assert ipchealth.token_state()[0] == "FAIL"


def test_the_mcp_server_refusing_without_the_token_is_ok(tmp_path):
    ipcauth.init()
    httpd = mcpserver.make_http(mcpserver.Server(root=tmp_path), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert ipchealth.probe_mcp(httpd.server_address[1])[0] == "OK"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_server_that_answers_without_the_token_fails():
    class Open(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Open)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        state, what = ipchealth.probe_mcp(httpd.server_address[1])
        assert state == "FAIL" and "without the token" in what
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert ipchealth.probe_mcp(httpd.server_address[1])[0] == "OFF"   # closed: nothing answers


# --- the containers ---------------------------------------------------------------------------------------------------

def _container(name, user, host_ip="127.0.0.1"):
    return {"Name": f"/{name}", "Config": {"User": user},
            "NetworkSettings": {"Ports": {"8791/tcp": [{"HostIp": host_ip, "HostPort": "8791"}], "9/tcp": None}}}


def test_a_container_beyond_loopback_fails_and_one_as_root_warns():
    assert ipchealth.judge_container(_container("a", "10001")) == \
        [("OK", "container a: ports on loopback only, user 10001")]
    assert ipchealth.judge_container(_container("b", "10001", "0.0.0.0"))[0][0] == "FAIL"
    assert ipchealth.judge_container(_container("c", "10001", ""))[0][0] == "FAIL"   # empty: every address
    assert ipchealth.judge_container(_container("d", "0:0")) == [("warning", "container d runs as root (user 0:0)")]
    assert ipchealth.judge_container(_container("e", ""))[0][0] == "warning"


def test_the_containers_are_the_brain_s_compose_projects_and_the_code_index(monkeypatch):
    calls = []

    def docker(argv):
        calls.append(argv)
        if argv[0] == "ps":
            return 0, "brain-sovereign-loki-1\tbrain-sovereign\nother-app\tother\ngitnexus\t\nbrain-mcp-1\tbrain-mcp\n"
        return 0, json.dumps([_container(n, "10001") for n in argv[1:]])

    monkeypatch.setattr(ipchealth, "_docker", docker)
    monkeypatch.setattr(ipchealth, "index_containers", lambda root=None: ["gitnexus"])
    found = ipchealth.containers()
    assert [c["Name"] for c in found] == ["/brain-sovereign-loki-1", "/gitnexus", "/brain-mcp-1"]
    assert calls[-1][0] == "inspect" and "other-app" not in calls[-1]


def test_the_report_names_what_has_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr(ipchealth, "probe_mcp", lambda port: ("OFF", "mcp: nothing answers"))
    monkeypatch.setattr(ipchealth, "containers", lambda root=None: [_container("gitnexus", "node")])
    monkeypatch.setattr(ipchealth, "index_containers", lambda root=None: ["gitnexus"])
    ipcauth.init()
    rc, lines = _run(_config(tmp_path, monkeypatch))
    assert rc == 0
    assert any("collector takes OTLP without the token" in line for line in lines)
    assert any("GitNexus has no authentication" in line for line in lines)
    rc, lines = _run(_config(tmp_path, monkeypatch, {"require_token": ["otel-collector"]}))
    assert not any("collector takes OTLP" in line for line in lines)


# --- the collector's opt-in token -------------------------------------------------------------------------------------

def test_the_collector_requires_the_token_only_when_the_owner_opts_in(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch)
    comps = bundles.components(reg, "sovereign")
    _config(tmp_path, monkeypatch)
    doc, files = bundles.render("sovereign", comps)
    template = (bundles.ROOT / "sovereign" / "otelcol.yaml").read_bytes()
    assert files["otelcol.yaml"] == template and bundles.TOKEN_SECRET not in (doc.get("secrets") or {})
    _config(tmp_path, monkeypatch, {"require_token": ["otel-collector"]})
    doc, files = bundles.render("sovereign", comps)
    assert doc["secrets"][bundles.TOKEN_SECRET] == {"file": ipcauth.token_file().as_posix()}
    assert bundles.TOKEN_SECRET in doc["services"]["otel-collector"]["secrets"]
    assert all(bundles.TOKEN_SECRET not in (s.get("secrets") or []) for n, s in doc["services"].items()
               if n != "otel-collector")
    cfg = yaml.safe_load(files["otelcol.yaml"].decode("utf-8"))
    assert cfg["extensions"]["bearertokenauth"] == {"filename": bundles.TOKEN_MOUNT}
    assert all(p["auth"] == {"authenticator": "bearertokenauth"}
               for p in cfg["receivers"]["otlp"]["protocols"].values())
    assert cfg["service"]["extensions"] == ["health_check", "bearertokenauth"]
    assert cfg["service"]["pipelines"] == yaml.safe_load(template.decode("utf-8"))["service"]["pipelines"]


def test_a_missing_token_makes_the_collector_wait_for_the_owner(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch)
    _config(tmp_path, monkeypatch, {"require_token": ["otel-collector"]})
    monkeypatch.setattr(bundles, "_compose_config", lambda files: ("docker compose config OK", ""))
    p = bundles.plan(reg, "sovereign", tmp_path)
    assert "otel-collector" in p.waiting and str(ipcauth.token_file().as_posix()) in p.waiting["otel-collector"]
    ipcauth.init()
    assert "otel-collector" not in bundles.plan(reg, "sovereign", tmp_path).waiting
