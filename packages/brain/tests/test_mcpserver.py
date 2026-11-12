"""brain.mcpserver: the Brain as an MCP server, driven by a fake client over stdio and over loopback HTTP
(wi-brain-mcp-server)."""

import http.client
import io
import json
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import yaml
from brain import cli, ipcauth, mcpserver

CONTAINER = Path(mcpserver.__file__).resolve().parents[2] / "container"
GH_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # a key's shape, never a real one


def _brain(tmp_path: Path) -> Path:
    """A personal brain with a neutral source (one rule file, one procedure) and a decision log."""
    root = tmp_path / "brain"
    (root / "source" / "rules").mkdir(parents=True)
    (root / "source" / "packs.yaml").write_text("packs: {}\n", encoding="utf-8")
    (root / "source" / "rules" / "global.md").write_text(
        "---\nscope: global\ntitle: The owner's rules\n---\n\n## Style\n<!-- id: rule-style -->\nBe brief.\n",
        encoding="utf-8")
    proc = root / "source" / "procedures" / "tidy-up"
    proc.mkdir(parents=True)
    (proc / "SKILL.md").write_text("---\nname: tidy-up\ndescription: Tidy the backlog\n---\nStep one.\n",
                                   encoding="utf-8")
    (proc / "notes.md").write_text("extra\n", encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "decisions.md").write_text(
        "# Decisions\n\n## 2026-11-01 — First call\n\nText.\n\n## 2026-11-02 — Second call\n\nMore.\n",
        encoding="utf-8")
    return root


class Client:
    """A fake MCP client: one JSON-RPC exchange per call, through serve_stdio."""

    def __init__(self, server):
        self.server, self.next_id = server, 0

    def send(self, *messages) -> list:
        out = io.StringIO()
        mcpserver.serve_stdio(self.server, io.StringIO("".join(json.dumps(m) + "\n" for m in messages)), out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def call(self, method, params=None):
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        (answer,) = self.send(msg)
        assert answer["id"] == self.next_id
        return answer

    def tool(self, name, **arguments):
        return self.call("tools/call", {"name": name, "arguments": arguments})["result"]


@pytest.fixture
def client(tmp_path):
    return Client(mcpserver.Server(root=_brain(tmp_path)))


# --- the protocol -----------------------------------------------------------------------------------------------------

def test_initialize_negotiates_the_version_and_names_the_server(client):
    r = client.call("initialize", {"protocolVersion": "2025-03-26", "clientInfo": {"name": "cursor", "version": "2"},
                                   "capabilities": {}})["result"]
    assert r["protocolVersion"] == "2025-03-26"
    assert set(r["capabilities"]) == {"tools", "resources", "prompts"}
    assert r["serverInfo"]["name"] == "brain"
    assert client.server.client == {"name": "cursor", "version": "2"}
    r = client.call("initialize", {"protocolVersion": "1999-01-01"})["result"]
    assert r["protocolVersion"] == mcpserver.PROTOCOLS[0]   # an unknown version: the newest one offered


def test_notifications_and_responses_get_no_answer_and_errors_are_json_rpc(client):
    assert client.send({"jsonrpc": "2.0", "method": "notifications/initialized"},
                       {"jsonrpc": "2.0", "id": 7, "result": {}}) == []
    assert client.call("nope/nothing")["error"]["code"] == mcpserver.METHOD_NOT_FOUND
    assert client.call("tools/call", {"name": "no_such_tool"})["error"]["code"] == mcpserver.INVALID_PARAMS
    assert client.call("ping") == {"jsonrpc": "2.0", "id": client.next_id, "result": {}}
    out = io.StringIO()
    mcpserver.serve_stdio(client.server, io.StringIO("not json\n\n"), out)
    assert json.loads(out.getvalue())["error"]["code"] == mcpserver.PARSE_ERROR
    batch = client.send([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "x"}])
    assert batch == [[{"jsonrpc": "2.0", "id": 1, "result": {}}]]
    assert client.send({"id": 3, "method": "ping"})[0]["error"]["code"] == mcpserver.INVALID_REQUEST


def test_an_internal_error_names_its_type_only(client, monkeypatch, capsys):
    monkeypatch.setitem(mcpserver.METHODS, "ping", lambda s, p: (_ for _ in ()).throw(RuntimeError("C:/secret/path")))
    err = client.call("ping")["error"]
    assert err == {"code": mcpserver.INTERNAL_ERROR, "message": "internal error (RuntimeError)"}
    assert "C:/secret/path" in capsys.readouterr().err   # the detail on stderr, never to the client


# --- tools ------------------------------------------------------------------------------------------------------------

def test_tools_list_gives_each_tool_a_closed_schema_and_its_kind(client):
    tools = {t["name"]: t for t in client.call("tools/list")["result"]["tools"]}
    assert set(tools) == {t.name for t in mcpserver.TOOLS}
    assert {"brain_items", "brain_item_show", "brain_check", "memory_read", "memory_propose"} <= set(tools)
    for t in tools.values():
        assert t["inputSchema"]["type"] == "object" and t["inputSchema"]["additionalProperties"] is False
    assert tools["memory_propose"]["annotations"]["readOnlyHint"] is False
    assert tools["brain_items"]["annotations"]["readOnlyHint"] is True


def test_graph_tools_run_the_brain_command_with_validated_arguments(client, monkeypatch):
    seen = []
    monkeypatch.setattr(mcpserver.Server, "brain", lambda self, argv: (seen.append(argv), ("ok", False))[1])
    assert client.tool("brain_items", project="brain", text="-rf mcp", status=["todo", "doing"], limit=5) == \
        {"content": [{"type": "text", "text": "ok"}], "isError": False}
    assert seen[-1] == ["--project=brain", "items", "--limit=5", "--status=todo", "--status=doing", "--text=-rf mcp"]
    client.tool("brain_item_show", id="wi-brain-mcp-server")
    assert seen[-1] == ["item", "show", "wi-brain-mcp-server"]
    client.tool("brain_spec_show", ref="spec-x", section="2.1")
    assert seen[-1] == ["spec", "show", "spec-x", "--section=2.1"]
    client.tool("brain_adr_show", ref="First call", titles=True)
    assert seen[-1] == ["adr", "show", "First call", "--titles"]
    n = len(seen)
    for name, args in (("brain_item_show", {"id": "--all"}), ("brain_adr_show", {"ref": " -x"}),
                       ("brain_items", {"project": "../x"}), ("brain_items", {"status": ["open"]}),
                       ("brain_items", {"limit": True}), ("brain_items", {"evil": 1}),
                       ("brain_item_show", {}), ("brain_items", {"text": "a\nb"})):
        r = client.tool(name, **args)
        assert r["isError"] is True, (name, args)
    assert len(seen) == n   # nothing ran


def test_a_tool_runs_brain_in_a_child_process_against_its_root(client):
    r = client.tool("brain_adr_show", ref="Second call")   # the decision log of the served root, nowhere else
    assert r["isError"] is False and "## 2026-11-02 — Second call" in r["content"][0]["text"]


@pytest.mark.parametrize("ref", ["C:/Users/x/.ssh/id_ed25519", "c:\\x\\key", "/etc/passwd", "../x.md",
                                 "notes/../../x.md", "doc:brain:../../x.md::k", "doc:brain:C:/x.md", "~/x.md",
                                 "notes\\x.md", "a/ ../b"])
def test_a_spec_ref_never_leaves_the_project_s_repos(client, monkeypatch, ref):
    seen = []
    monkeypatch.setattr(mcpserver.Server, "brain", lambda self, argv: (seen.append(argv), ("x", False))[1])
    r = client.tool("brain_spec_show", ref=ref)
    assert r["isError"] is True and "no .." in r["content"][0]["text"] and seen == []


def test_a_spec_ref_inside_the_repos_passes():
    for ref in ("spec-brain-plugin", "doc:brain:docs/x.md::2-1", "docs/specs/a.md", "notes/x..y.md"):
        assert mcpserver.spec_ref(ref), ref


def test_every_answer_passes_the_secret_scan(client, monkeypatch):
    monkeypatch.setattr(mcpserver.Server, "brain", lambda self, argv: (f"line one\ntoken {GH_TOKEN}\nline three",
                                                                       False))
    text = client.tool("brain_next")["content"][0]["text"]
    assert GH_TOKEN not in text
    assert text.startswith("line one\n[dropped") and "[1 line(s) dropped by the secret scan]" in text


def test_the_scan_runs_before_the_cut_and_on_names_and_descriptions(client, monkeypatch):
    monkeypatch.setattr(mcpserver, "MAX_TEXT", 30)
    cut = mcpserver.clean("x" * 10 + " " + GH_TOKEN)   # the cut would leave a key's first 19 characters
    assert GH_TOKEN[:19] not in cut and "[1 line(s) dropped" in cut
    proc = client.server.root / "source" / "procedures" / "tidy-up" / "SKILL.md"
    proc.write_text(f"---\nname: tidy-up\ndescription: uses {GH_TOKEN}\n---\nStep one.\n", encoding="utf-8")
    listed = json.dumps(client.call("prompts/list")["result"])
    assert GH_TOKEN not in listed and "tidy-up" in listed


def test_a_body_nested_past_the_parser_s_depth_is_a_parse_error(client):
    out = io.StringIO()
    deep = "[" * 200_000 + "]" * 200_000
    mcpserver.serve_stdio(client.server, io.StringIO(deep + "\n" + json.dumps({"jsonrpc": "2.0", "id": 9,
                                                                              "method": "ping"}) + "\n"), out)
    first, second = (json.loads(line) for line in out.getvalue().splitlines())
    assert first["error"]["code"] == mcpserver.PARSE_ERROR and second == {"jsonrpc": "2.0", "id": 9, "result": {}}


# --- memory -----------------------------------------------------------------------------------------------------------

@pytest.fixture
def memory_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.delenv("BRAIN_MEMORY_MAP", raising=False)
    d = tmp_path / "claude" / "projects" / "E--work-app" / "memory"
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text("- [x](x.md)\n", encoding="utf-8")
    return d


def test_memory_read_lists_folders_then_notes_then_a_note(client, memory_dir):
    assert client.tool("memory_read")["content"][0]["text"].endswith("\nE--work-app")
    assert "MEMORY.md" in client.tool("memory_read", project="E--work-app")["content"][0]["text"]
    assert client.tool("memory_read", project="E--work-app", note="MEMORY.md")["content"][0]["text"] == "- [x](x.md)\n"
    assert client.tool("memory_read", project="E--work-app", note="none.md")["isError"] is True
    assert client.tool("memory_read", project="E--work-app", note="../../secret.md")["isError"] is True


def test_memory_propose_writes_the_note_the_sync_exports_and_refuses_a_secret(client, memory_dir):
    r = client.tool("memory_propose", project="E--work-app", note="fact.md", content="A durable fact.")
    assert r["isError"] is False and "reviewed PR" in r["content"][0]["text"]
    assert (memory_dir / "fact.md").read_text(encoding="utf-8") == "A durable fact.\n"
    r = client.tool("memory_propose", project="E--work-app", note="leak.md", content=f"key {GH_TOKEN}")
    assert r["isError"] is True and "secret pattern" in r["content"][0]["text"]
    assert not (memory_dir / "leak.md").exists()
    assert client.tool("memory_propose", project="E--elsewhere", note="a.md", content="x")["isError"] is True
    assert client.tool("memory_propose", project="E--work-app", note="a.txt", content="x")["isError"] is True
    assert client.tool("memory_propose", project="E--work-app", note="a.md", content="")["isError"] is True
    assert sorted(p.name for p in memory_dir.iterdir()) == ["MEMORY.md", "fact.md"]


# --- resources and prompts --------------------------------------------------------------------------------------------

def test_resources_are_the_rules_the_procedures_files_and_the_decision_log(client):
    uris = {r["uri"] for r in client.call("resources/list")["result"]["resources"]}
    assert uris == {"brain://rules/rules/global.md", "brain://procedures/tidy-up/SKILL.md",
                    "brain://procedures/tidy-up/notes.md", "brain://decisions"} | \
        {u for u in uris if u.startswith("brain://procedures/") and "tidy-up" not in u}   # the engine's own
    rules = client.call("resources/read", {"uri": "brain://rules/rules/global.md"})["result"]["contents"][0]["text"]
    assert rules.startswith("# The owner's rules\n") and "Be brief." in rules and "id: rule-style" not in rules
    index = client.call("resources/read", {"uri": "brain://decisions"})["result"]["contents"][0]["text"]
    assert "- 2026-11-01 — First call\n- 2026-11-02 — Second call" in index
    assert client.call("resources/read", {"uri": "brain://procedures/tidy-up/notes.md"})["result"]["contents"][0][
        "text"] == "extra\n"
    for uri in ("brain://rules/../config.json", "brain://procedures/tidy-up/../../x", "file:///etc/passwd",
                "brain://nothing"):
        assert client.call("resources/read", {"uri": uri})["error"]["code"] == mcpserver.RESOURCE_NOT_FOUND
    tpl = client.call("resources/templates/list")["result"]["resourceTemplates"]
    assert [t["uriTemplate"] for t in tpl] == ["brain://decisions/{ref}"]


def test_an_adr_resource_reads_through_brain_adr_show(client, monkeypatch):
    seen = []
    monkeypatch.setattr(mcpserver.Server, "brain", lambda self, argv: (seen.append(argv), ("the ADR", False))[1])
    r = client.call("resources/read", {"uri": "brain://decisions/First%20call"})["result"]
    assert r["contents"][0]["text"] == "the ADR" and seen == [["adr", "show", "First call"]]
    assert client.call("resources/read", {"uri": "brain://decisions/--all"})["error"]["code"] == \
        mcpserver.INVALID_PARAMS


def test_prompts_are_the_procedures(client):
    prompts = {p["name"]: p for p in client.call("prompts/list")["result"]["prompts"]}
    assert prompts["tidy-up"]["description"] == "Tidy the backlog"
    msg = client.call("prompts/get", {"name": "tidy-up", "arguments": {"task": "wave 0.3.3"}})["result"]
    text = msg["messages"][0]["content"]["text"]
    assert text.startswith("Step one.") and "notes.md" in text and text.endswith("Apply this procedure to: wave 0.3.3\n")
    assert client.call("prompts/get", {"name": "nope"})["error"]["code"] == mcpserver.INVALID_PARAMS


# --- HTTP -------------------------------------------------------------------------------------------------------------

@pytest.fixture
def httpd(tmp_path):
    ipcauth.init()
    httpd = mcpserver.make_http(mcpserver.Server(root=_brain(tmp_path)), "127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _post(httpd, body, headers=None, method="POST", path="/mcp"):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "Authorization": f"Bearer {ipcauth.read()}", **(headers or {})}
    conn.request(method, path, body=data if method == "POST" else None, headers={k: v for k, v in h.items() if v})
    r = conn.getresponse()
    out = r.status, r.read(), dict(r.getheaders())
    conn.close()
    return out


def test_http_answers_with_the_machine_s_token_only(httpd):
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
    status, body, _ = _post(httpd, init)
    assert status == 200 and json.loads(body)["result"]["serverInfo"]["name"] == "brain"
    status, body, headers = _post(httpd, init, {"Authorization": None})
    assert status == 401 and headers["WWW-Authenticate"].startswith("Bearer") and b"result" not in body
    assert _post(httpd, init, {"Authorization": "Bearer " + "x" * 43})[0] == 401
    assert _post(httpd, init, {"Authorization": f"Basic {ipcauth.read()}"})[0] == 401
    assert _post(httpd, {"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202
    status, body, _ = _post(httpd, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                            {"MCP-Protocol-Version": "2025-06-18"})
    assert status == 200 and json.loads(body)["result"]["tools"]


def test_http_refuses_a_foreign_host_or_origin_a_big_body_and_other_methods(httpd):
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert _post(httpd, ping, {"Host": "evil.example:8791"})[0] == 403
    assert _post(httpd, ping, {"Origin": "http://evil.example"})[0] == 403
    assert _post(httpd, ping, {"Origin": "null"})[0] == 403
    assert _post(httpd, ping, {"Origin": "http://localhost:3000"})[0] == 200
    assert _post(httpd, ping, {"MCP-Protocol-Version": "1999-01-01"})[0] == 400
    assert _post(httpd, ping, path="/other")[0] == 404
    assert _post(httpd, b"{not json")[0] == 400
    with socket.create_connection(("127.0.0.1", httpd.server_address[1]), timeout=30) as sock:   # said, not sent
        sock.sendall(f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {ipcauth.read()}\r\n"
                     f"Content-Length: {mcpserver.MAX_BODY + 1}\r\n\r\n".encode())
        assert sock.recv(100).startswith(b"HTTP/1.1 413 ")
    status, _, headers = _post(httpd, ping, method="GET")
    assert status == 405 and headers["Allow"] == "POST"
    assert _post(httpd, ping, {"Authorization": None}, method="GET")[0] == 401   # the token first, then the method


def test_http_binds_loopback_only_and_never_without_a_token(tmp_path, monkeypatch):
    server = mcpserver.Server(root=tmp_path)
    with pytest.raises(ipcauth.TokenError, match="brain ipc token --init"):
        mcpserver.make_http(server, "127.0.0.1", 0)
    ipcauth.init()
    for host in ("0.0.0.0", "192.168.1.10", "::", "example.com"):
        with pytest.raises(ValueError, match="loopback address only"):
            mcpserver.make_http(server, host, 0)
    monkeypatch.setenv(mcpserver.CONTAINER_ENV, "1")   # inside the image: its compose file publishes on 127.0.0.1
    assert mcpserver.bindable("0.0.0.0")
    monkeypatch.setattr(mcpserver.os, "geteuid", lambda: 0, raising=False)
    with pytest.raises(ValueError, match="as root"):
        mcpserver.make_http(server, "0.0.0.0", 0)


def test_a_rotated_token_revokes_the_old_one_without_a_restart(httpd):
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    old = ipcauth.read()
    ipcauth.token_file().unlink()
    assert _post(httpd, ping, {"Authorization": f"Bearer {old}"})[0] == 401   # no file: every request refused
    ipcauth.init()
    assert ipcauth.read() != old
    assert _post(httpd, ping, {"Authorization": f"Bearer {old}"})[0] == 401
    assert _post(httpd, ping)[0] == 200   # the new one


# --- the machine's token ----------------------------------------------------------------------------------------------

def test_the_token_is_made_once_and_never_printed(tmp_path, monkeypatch, capsys, brain_home):
    assert ipcauth.read() is None
    assert cli.main(["ipc", "token"]) == 1
    assert "no usable token" in capsys.readouterr().out
    assert cli.main(["ipc", "token", "--init"]) == 0
    tok = ipcauth.read()
    out = capsys.readouterr().out
    assert tok and len(tok) >= ipcauth.MIN_LENGTH and tok not in out and "made" in out
    assert ipcauth.token_file() == brain_home / "ipc" / "token"
    assert cli.main(["ipc", "token", "--init"]) == 0 and ipcauth.read() == tok   # kept
    assert "kept" in capsys.readouterr().out
    short = tmp_path / "short"
    short.write_text("abc\n", encoding="utf-8")
    monkeypatch.setenv(ipcauth.ENV, str(short))
    assert ipcauth.read() is None


@pytest.mark.parametrize("host,ok", [("127.0.0.1", True), ("127.8.0.1", True), ("::1", True), ("[::1]", True),
                                     ("localhost", True), ("LOCALHOST", True), ("0.0.0.0", False), ("::", False),
                                     ("10.0.0.1", False), ("localhost.evil.example", False), ("", False),
                                     (None, False)])
def test_loopback(host, ok):
    assert ipcauth.is_loopback(host) is ok


def test_host_header_and_authorization_parsing():
    assert ipcauth.host_of("127.0.0.1:8791") == "127.0.0.1"
    assert ipcauth.host_of("[::1]:8791") == "::1"
    assert ipcauth.host_of("localhost") == "localhost"
    assert ipcauth.authorized("Bearer " + "t" * 40, "t" * 40)
    assert ipcauth.authorized("bearer   " + "t" * 40, "t" * 40)
    assert not ipcauth.authorized("Bearer " + "t" * 39, "t" * 40)
    assert not ipcauth.authorized(None, "t" * 40)
    assert not ipcauth.authorized("Bearer ", "")


# --- the commands -----------------------------------------------------------------------------------------------------

def test_brain_mcp_tools_lists_each_tool_and_its_kind(capsys):
    assert cli.main(["mcp", "tools"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(mcpserver.TOOLS)
    assert any(line.split()[:2] == ["memory_propose", "write"] for line in lines)


def test_brain_mcp_serve_http_refuses_a_non_loopback_address(capsys):
    assert cli.main(["mcp", "serve", "--http", "--host", "0.0.0.0", "--port", "0"]) == 2   # before any root is read
    assert "loopback address only" in capsys.readouterr().err


# --- the container ----------------------------------------------------------------------------------------------------

def test_the_container_runs_as_a_user_and_publishes_on_loopback_only():
    docker = (CONTAINER / "Dockerfile").read_text(encoding="utf-8")
    base = next(line for line in docker.splitlines() if line.startswith("FROM "))
    assert "@sha256:" in base   # pinned by digest
    user = [line.split()[1] for line in docker.splitlines() if line.startswith("USER ")]
    assert user and user[-1].split(":")[0] not in ("0", "root")
    assert "BRAIN_MCP_CONTAINER=1" in docker and "BRAIN_IPC_TOKEN_FILE=/run/secrets/" in docker
    compose = yaml.safe_load((CONTAINER / "compose.yaml").read_text(encoding="utf-8"))
    (svc,) = compose["services"].values()
    assert svc["user"] == "${BRAIN_UID:-10001}:${BRAIN_GID:-10001}"   # 10001 unless the token file's owner
    assert svc["restart"] == "no" and svc["read_only"] is True and svc["cap_drop"] == ["ALL"]
    assert svc["ports"] and all(str(p).startswith("127.0.0.1:") for p in svc["ports"])
    assert svc["secrets"] == ["brain-ipc-token"] and not svc.get("environment")


@pytest.mark.docker
@pytest.mark.skipif(not shutil.which("docker"), reason="docker not on the PATH")
def test_docker_compose_config_accepts_the_container_definition(tmp_path):
    token = tmp_path / "token"
    token.write_text("t" * 43 + "\n", encoding="utf-8")
    env = {**__import__("os").environ, "BRAIN_ROOT_DIR": str(tmp_path), "BRAIN_IPC_TOKEN": str(token)}
    p = subprocess.run(["docker", "compose", "-f", str(CONTAINER / "compose.yaml"), "config", "--quiet"], env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
