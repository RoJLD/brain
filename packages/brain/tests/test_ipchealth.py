"""wi-brain-local-ipc-auth: brain health ipc (brain.ipchealth) and the collector's opt-in token (brain.bundles)."""

import io
import json
import os
import socket
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

def test_a_machine_without_the_token_is_silent_under_all_and_nothing_is_probed(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(ipchealth, "probe_mcp", lambda port, token=True: called.append("probe") or ("OFF", "x"))
    monkeypatch.setattr(ipchealth, "_docker", lambda argv: called.append("docker") or (None, ""))
    monkeypatch.setattr(ipchealth, "index_containers", lambda root=None: [])
    cfg = _config(tmp_path, monkeypatch)
    assert _run(cfg, named=False) == (0, []) and called == []
    rc, lines = _run(cfg)
    assert rc == 0 and lines[0].startswith("ipc OFF no usable token") and called == ["probe", "docker"]


def test_a_required_token_that_is_missing_fails(tmp_path, monkeypatch, no_docker):
    monkeypatch.setattr(ipchealth, "probe_mcp", lambda port, token=True: ("OFF", "mcp: nothing answers"))
    rc, lines = _run(_config(tmp_path, monkeypatch, {"require_token": ["otel-collector"]}), named=False)
    assert rc == 1 and lines[0].startswith("ipc FAIL no usable token") and "otel-collector" in lines[0]
    rc, lines = _run(_config(tmp_path, monkeypatch, {"require_token": ["qdrant"]}))
    assert rc == 1 and any("only otel-collector can require the token" in line for line in lines)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_token_readable_by_every_user_fails_a_group_or_acl_passes():
    f, _ = ipcauth.init()
    assert ipchealth.token_state()[0] == "OK"
    f.chmod(0o640)   # a group bit (or an ACL's mask): how a container's user may read it
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


class _Answer(BaseHTTPRequestHandler):
    def do_POST(self):
        # the request's body read before the answer: a server that closes with it unread resets the connection on
        # Windows, which the probe reads as « not the MCP server » (the test flaked on the Windows CI)
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


def test_a_server_that_answers_without_the_token_fails_only_when_the_machine_has_one():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        state, what = ipchealth.probe_mcp(httpd.server_address[1])
        assert state == "FAIL" and "without the token" in what
        assert ipchealth.probe_mcp(httpd.server_address[1], token=False)[0] == "OFF"   # another program
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert ipchealth.probe_mcp(httpd.server_address[1])[0] == "OFF"   # closed: nothing answers


def test_a_listener_that_is_not_http_never_crashes_the_check():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)

    def reply():
        for _ in range(2):   # the connection check, then the request
            conn, _ = srv.accept()
            try:
                conn.recv(1024)
                conn.sendall(b"-ERR unknown command\r\n")
            except OSError:
                pass
            conn.close()

    threading.Thread(target=reply, daemon=True).start()
    try:
        assert ipchealth.probe_mcp(srv.getsockname()[1], token=False)[0] == "OFF"
    finally:
        srv.close()


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


def test_each_container_is_inspected_alone_and_one_that_fails_hides_no_other(monkeypatch):
    calls = []

    def docker(argv):
        calls.append(argv)
        if argv[0] == "ps":
            return 0, "brain-sovereign-loki-1\tbrain-sovereign\nother-app\tother\ngitnexus\t\nbrain-mcp-1\tbrain-mcp\n"
        name = argv[-1]
        if name == "brain-mcp-1":   # stopped between ps and inspect
            return 1, "Error: No such object: brain-mcp-1"
        host = "0.0.0.0" if name == "gitnexus" else "127.0.0.1"
        return 0, "WARNING: a note on stderr\n" + json.dumps(_container(name, "10001", host))

    monkeypatch.setattr(ipchealth, "_docker", docker)
    monkeypatch.setattr(ipchealth, "index_containers", lambda root=None: ["gitnexus"])
    found = ipchealth.containers()
    assert [c["Name"] for c in found] == ["/brain-sovereign-loki-1", "/gitnexus", "brain-mcp-1"]
    assert not any("other-app" in c for c in calls)
    judged = [st for c in found for st, _ in ipchealth.judge_container(c)]
    assert judged == ["OK", "FAIL", "warning"]


def test_the_report_names_what_has_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr(ipchealth, "probe_mcp", lambda port, token=True: ("OFF", "mcp: nothing answers"))
    monkeypatch.setattr(ipchealth, "containers", lambda root=None: [_container("gitnexus", "node")])
    monkeypatch.setattr(ipchealth, "index_containers", lambda root=None: ["gitnexus"])
    ipcauth.init()
    rc, lines = _run(_config(tmp_path, monkeypatch), named=False)
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


def test_a_missing_or_unusable_token_makes_the_collector_wait_with_the_fix(tmp_path, monkeypatch):
    reg = _registry(tmp_path, monkeypatch)
    _config(tmp_path, monkeypatch, {"require_token": ["otel-collector"]})
    monkeypatch.setattr(bundles, "_compose_config", lambda files: ("docker compose config OK", ""))
    p = bundles.plan(reg, "sovereign", tmp_path)
    assert "brain ipc token --init" in p.waiting["otel-collector"]
    ipcauth.token_file().parent.mkdir(parents=True, exist_ok=True)
    ipcauth.token_file().write_text("short\n", encoding="utf-8")   # a file, but no usable token
    assert "otel-collector" in bundles.plan(reg, "sovereign", tmp_path).waiting
    ipcauth.token_file().unlink()
    ipcauth.init()
    assert "otel-collector" not in bundles.plan(reg, "sovereign", tmp_path).waiting
