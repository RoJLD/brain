import http.server
import io
import json
import shutil
import subprocess
import threading

import pytest

from brain import cli, codeindex, stacks
from conftest import run_git

REGISTRY = """\
infra:
  root: {tmp}/infra
  code_index: [../alpha, {{path: ../beta, branch: dev}}]
  stacks:
    gitnexus:
      start: [docker, compose, up, -d]
      health: {{urls: ['http://localhost:4747/api/health']}}
      index: {{api: 'http://127.0.0.1:4747/', container: gitnexus, timeout: 60}}
{extra}"""


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """Two repos: alpha on main (no origin, so its checked-out branch), beta with a dev branch."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    from conftest import GIT_ENV
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    out = {}
    for name in ("alpha", "beta"):
        r = tmp_path / name
        r.mkdir()
        run_git(r, "init", "-q", "-b", "main")
        run_git(r, "config", "commit.gpgsign", "false")
        (r / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        run_git(r, "add", "-A")
        run_git(r, "commit", "-q", "-m", "init")
        out[name] = r
    run_git(out["beta"], "branch", "dev")
    (tmp_path / "infra").mkdir()
    return out


def _registry(tmp_path, monkeypatch, extra="", text=None):
    f = tmp_path / "projects.yaml"
    f.write_text(text if text is not None else REGISTRY.format(tmp=tmp_path.as_posix(), extra=extra),
                 encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    return f


def _sha(repo, ref="HEAD"):
    return run_git(repo, "rev-parse", ref).strip()


def _commit(repo, branch="main"):
    run_git(repo, "checkout", "-q", branch)
    (repo / "b.py").write_text(f"x = {_sha(repo)!r}\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "more")


class Fake:
    """GitNexus: the container (docker exec) and its API. A snapshot reads the bundle's head with git; a job
    completes after ``steps`` polls and registers the clone at that head; time is simulated."""

    def __init__(self, monkeypatch, up=True, steps=2, fail="", snapshot=None, lose=False, query=True):
        self.t, self.up, self.steps, self.fail, self.snapshot, self.lose, self.query = \
            0.0, up, steps, fail, snapshot, lose, query
        self.clones, self.index, self.jobs, self.docker_calls, self.requests = {}, {}, {}, [], []
        monkeypatch.setattr(codeindex, "_clock", lambda: self.t)
        monkeypatch.setattr(codeindex, "_sleep", self.sleep)
        monkeypatch.setattr(codeindex, "_docker", self.docker)
        monkeypatch.setattr(codeindex, "_http", self.http)
        monkeypatch.setattr(codeindex, "_mcp_tool", self.mcp)
        monkeypatch.setattr(stacks, "_probe_url", lambda url, timeout: "" if self.up else "connection refused")

    def sleep(self, s):
        self.t += s

    def docker(self, argv, timeout, stdin=None):
        self.docker_calls.append(argv)
        if argv[:5] == ["docker", "exec", "-i", "gitnexus", "sh"]:
            assert argv[5:7] == ["-c", codeindex.SNAPSHOT]
            name, store, branch = argv[-3:]
            heads = subprocess.run(["git", "bundle", "list-heads", str(stdin)], capture_output=True,
                                   text=True).stdout.split()
            assert heads[1] == f"refs/heads/{branch}"
            self.clones[f"{store}/{name}"] = heads[0]
            return self.snapshot or (0, f"{heads[0]}\n")
        if argv[:4] == ["docker", "exec", "gitnexus", "du"]:
            return 0, f"3072\t{argv[-1]}\n"
        raise AssertionError(argv)

    def http(self, method, url, body=None, timeout=10.0):
        self.requests.append((method, url, body))
        if not self.up:
            return 0, "[WinError 10061] connection refused"
        path = url.split("127.0.0.1:4747", 1)[1]
        if (method, path) == ("POST", "/api/analyze"):
            job = f"job-{len(self.jobs) + 1}"
            self.jobs[job] = {"path": body["path"], "polls": 0}
            return 202, {"jobId": job, "status": "queued"}
        if method == "GET" and path.startswith("/api/analyze/"):
            job = self.jobs[path.rsplit("/", 1)[1]]
            job["polls"] += 1
            if self.fail:
                return 200, {"status": "failed", "error": self.fail}
            if job["polls"] < self.steps:
                return 200, {"status": "analyzing"}
            if not self.lose:
                self.index[job["path"]] = self.clones[job["path"]]
            return 200, {"status": "complete"}
        if (method, path) == ("GET", "/api/repos"):
            return 200, [{"name": p.rsplit("/", 1)[1], "path": p, "lastCommit": sha, "indexedAt": "2026-11-02T10:00:00Z",
                          "stats": {"files": 2, "nodes": 9, "edges": 12, "embeddings": 4}}
                         for p, sha in self.index.items()]
        raise AssertionError((method, url))  # never /api/query: a REST read breaks MCP's read-only open

    def mcp(self, url, name, arguments, timeout=10.0):
        assert url == "http://127.0.0.1:4747/api/mcp" and name == "cypher" and arguments["repo"]
        if not self.query:
            return "", "Error: LadybugDB unavailable for /data/gitnexus/repos/alpha/.gitnexus/lbug."
        rows = [("File", 2), ("Function", 5)] if "label(n)" in arguments["query"] else [("DEFINES", 5), ("CALLS", 7)]
        md = "| k | n |\n| --- | --- |\n" + "\n".join(f"| {k} | {n} |" for k, n in rows)
        return json.dumps({"markdown": md, "row_count": len(rows)}, indent=2) + "\n\n---\n**Next:** use context()", ""


def _lines(fn, *args, **kw):
    out = io.StringIO()
    rc = fn(*args, out=out, **kw)
    return rc, out.getvalue().splitlines()


def test_load_reads_the_repos_and_the_indexing_stack(tmp_path, monkeypatch, repos):
    _registry(tmp_path, monkeypatch)
    ix, declared = codeindex.load()
    assert ix.api == "http://127.0.0.1:4747" and ix.container == "gitnexus" and ix.timeout == 60
    assert ix.store == codeindex.STORE and ix.embeddings and ix.stack.name == "gitnexus"
    assert list(declared) == ["alpha", "beta"]
    assert declared["alpha"].path == repos["alpha"].resolve() and declared["alpha"].branch == ""
    assert declared["beta"].branch == "dev" and declared["beta"].project == "infra"


def test_a_worktree_is_named_after_its_main_checkout(tmp_path, monkeypatch, repos):
    wt = tmp_path / "wt-feature"
    run_git(repos["alpha"], "worktree", "add", "-q", "-b", "feature", str(wt))
    _registry(tmp_path, monkeypatch, text=REGISTRY.format(tmp=tmp_path.as_posix(), extra="")
              .replace("[../alpha, ", "[../wt-feature, "))
    _, declared = codeindex.load()
    assert "alpha" in declared and declared["alpha"].path == repos["alpha"].resolve()


def test_a_project_rooted_in_a_worktree_reads_its_siblings_from_the_main_checkout(tmp_path, monkeypatch, repos):
    """As repos: does (projects._resolve_root): a sibling of the main checkout is not one of the worktree's."""
    wt = tmp_path / "wts" / "alpha-wt"
    run_git(repos["alpha"], "worktree", "add", "-q", "-b", "feature", str(wt))
    _registry(tmp_path, monkeypatch, text=f"infra:\n  root: {wt.as_posix()}\n  code_index: [., ../beta]\n"
                                          "  stacks:\n    g:\n      start: [a]\n      health: {cmd: [b]}\n"
                                          "      index: {api: 'http://127.0.0.1:4747', container: gitnexus}\n")
    _, declared = codeindex.load()
    assert declared["alpha"].path == repos["alpha"].resolve() and declared["beta"].path == repos["beta"].resolve()


@pytest.mark.parametrize("extra, message", [
    ("other: {root: x, code_index: [../alpha]}", "alpha is declared by infra and other"),
    ("other: {root: x, code_index: [{branch: main}]}", "a code_index entry is a path"),
    ("other: {root: x, code_index: ['../bad name']}", "GitNexus names a repo after its folder"),
    ("other: {root: x, stacks: {g2: {start: [a], health: {cmd: [b]}, index: {api: x, container: y}}}}",
     "declared by several stacks"),
    ("other: {root: x, stacks: {code-index: {start: [a], health: {cmd: [b]}}}}", "the name is reserved"),
])
def test_load_refuses_bad_declarations(tmp_path, monkeypatch, repos, extra, message):
    _registry(tmp_path, monkeypatch, extra)
    with pytest.raises(codeindex.CodeIndexError, match=message):
        codeindex.load()


@pytest.mark.parametrize("index, message", [
    ("{api: x}", "api and container are required"),
    ("{api: x, container: y, port: 1}", r"unknown key\(s\) port"),
])
def test_load_refuses_a_bad_index_declaration(tmp_path, monkeypatch, repos, index, message):
    text = REGISTRY.format(tmp=tmp_path.as_posix(), extra="").replace(
        "{api: 'http://127.0.0.1:4747/', container: gitnexus, timeout: 60}", index)
    _registry(tmp_path, monkeypatch, text=text)
    with pytest.raises(codeindex.CodeIndexError, match=message):
        codeindex.load()


def test_code_index_without_an_indexing_stack_is_an_error(tmp_path, monkeypatch, repos):
    _registry(tmp_path, monkeypatch, text=f"infra: {{root: {tmp_path.as_posix()}/infra, code_index: [../alpha]}}\n")
    with pytest.raises(codeindex.CodeIndexError, match="no stack declares index"):
        codeindex.load()
    assert cli.main(["index"]) == 2


def test_index_snapshots_the_branch_analyzes_and_records(tmp_path, monkeypatch, repos, brain_home):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch, steps=3)
    rc, lines = _lines(codeindex.run, ["alpha", "beta"])
    assert rc == 0
    alpha, beta = _sha(repos["alpha"]), _sha(repos["beta"], "dev")
    assert lines == [f"alpha OK (4 s, main@{alpha[:7]}, 2 files, 9 nodes, 12 edges, 4 embeddings, 3.0 MB)",
                     f"beta OK (4 s, dev@{beta[:7]}, 2 files, 9 nodes, 12 edges, 4 embeddings, 3.0 MB)"]
    post = [b for m, u, b in fake.requests if m == "POST" and u.endswith("/api/analyze")]
    assert post == [{"path": "/data/gitnexus/repos/alpha", "force": True, "embeddings": True},
                    {"path": "/data/gitnexus/repos/beta", "force": True, "embeddings": True}]
    rec = json.loads((brain_home / "code-index.json").read_text(encoding="utf-8"))
    assert rec["alpha"]["sha"] == alpha and rec["alpha"]["branch"] == "main" and rec["alpha"]["seconds"] == 4
    assert rec["alpha"]["labels"] == {"Function": 5, "File": 2} and rec["alpha"]["edge_types"] == {"CALLS": 7,
                                                                                                  "DEFINES": 5}
    assert rec["alpha"]["size_kb"] == 3072 and rec["alpha"]["gitnexus"]["path"] == "/data/gitnexus/repos/alpha"
    assert rec["beta"]["sha"] == beta and rec["beta"]["branch"] == "dev"
    assert not list((brain_home / "code-index").glob("*.bundle"))  # the bundle is removed
    assert run_git(repos["alpha"], "status", "--porcelain") == ""  # the repo is only read


def test_status_and_health_follow_the_branch(tmp_path, monkeypatch, repos):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch)
    rc, lines = _lines(codeindex.run, [])
    assert rc == 0 and lines[0] == f"alpha NOT INDEXED: main@{_sha(repos['alpha'])[:7]}; brain index alpha"
    assert _lines(codeindex.health) == (1, ["code-index STALE: alpha (not indexed), beta (not indexed); "
                                            "brain index --stale reindexes them"])
    assert _lines(codeindex.run, [], every=True)[0] == 0
    assert _lines(codeindex.health) == (0, ["code-index OK (2 repo(s) indexed at their branch head)"])
    old = _sha(repos["beta"], "dev")
    _commit(repos["beta"], "dev")
    _commit(repos["beta"], "dev")
    rc, lines = _lines(codeindex.health)
    assert rc == 1 and lines == [f"code-index STALE: beta (dev is 2 commits past the index ({old[:7]})); "
                                 "brain index --stale reindexes it"]
    fake.index.pop("/data/gitnexus/repos/alpha")
    rc, lines = _lines(codeindex.run, [])
    assert lines[0] == "alpha MISSING: GitNexus no longer lists it (its volume reset?); brain index alpha"
    assert lines[1].startswith("beta STALE: dev is 2 commits past the index")


def test_stale_reindexes_only_what_is_behind(tmp_path, monkeypatch, repos):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch)
    _lines(codeindex.run, [], every=True)
    assert _lines(codeindex.run, [], stale=True) == (0, ["every repo is indexed at its branch head"])
    _commit(repos["alpha"])
    rc, lines = _lines(codeindex.run, [], stale=True)
    assert rc == 0 and len(lines) == 1 and lines[0].startswith(f"alpha OK (2 s, main@{_sha(repos['alpha'])[:7]}")
    assert len(fake.jobs) == 3


def test_health_without_gitnexus_reads_the_record_only(tmp_path, monkeypatch, repos):
    _registry(tmp_path, monkeypatch)
    fake = Fake(monkeypatch)
    _lines(codeindex.run, [], every=True)
    fake.up = False
    assert _lines(codeindex.health) == (0, ["code-index OK (2 repo(s) indexed at their branch head; gitnexus does "
                                            "not answer: its registry was not checked)"])
    rc, lines = _lines(codeindex.run, ["alpha"])
    assert rc == 1 and lines == ["brain index: gitnexus is down (http://localhost:4747/api/health: connection "
                                 "refused); brain up gitnexus starts it"]


@pytest.mark.parametrize("kw, why", [
    ({"fail": "Error: EACCES: permission denied, open '/data/gitnexus/registry.json.tmp'"},
     "analyze failed: Error: EACCES: permission denied, open '/data/gitnexus/registry.json.tmp'"),
    ({"steps": 1000}, "analyze not complete after 60 s (job job-1 left running)"),
    ({"snapshot": (1, "mkdir: cannot create directory '/data/gitnexus/repos': Permission denied\n")},
     "snapshot exited 1: mkdir: cannot create directory '/data/gitnexus/repos': Permission denied"),
    ({"snapshot": (0, "0123456789abcdef\n")}, "snapshot: GitNexus's clone is at 0123456, not "),
    ({"lose": True}, "analyze complete but GitNexus does not list /data/gitnexus/repos/alpha"),
])
def test_index_reports_why_it_failed_and_records_nothing(tmp_path, monkeypatch, repos, brain_home, kw, why):
    _registry(tmp_path, monkeypatch)
    Fake(monkeypatch, **kw)
    rc, lines = _lines(codeindex.run, ["alpha"])
    assert rc == 1 and len(lines) == 1 and lines[0].startswith("alpha FAILED (") and why in lines[0]
    assert not (brain_home / "code-index.json").exists()


def test_measures_are_best_effort_and_say_when_mcp_does_not_answer(tmp_path, monkeypatch, repos, brain_home):
    _registry(tmp_path, monkeypatch)
    Fake(monkeypatch, query=False)
    rc, lines = _lines(codeindex.run, ["alpha"])
    assert rc == 0 and lines[0].endswith("3.0 MB); MCP does not answer: Error: LadybugDB unavailable for "
                                         "/data/gitnexus/repos/alpha/.gitnexus/lbug.")
    rec = json.loads((brain_home / "code-index.json").read_text(encoding="utf-8"))["alpha"]
    assert "labels" not in rec and rec["size_kb"] == 3072 and rec["mcp_error"].startswith("Error: LadybugDB")


class _McpHandler(http.server.BaseHTTPRequestHandler):
    """A StreamableHTTP MCP server: JSON for initialize, 202 for the notification, an event stream for tools/call."""
    seen: list = []

    def log_message(self, *args):
        pass

    def _reply(self, status, body="", ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("mcp-session-id", "s-1")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_DELETE(self):
        self.seen.append(("DELETE", self.headers.get("mcp-session-id")))
        self._reply(200)

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append((msg["method"], self.headers.get("mcp-session-id")))
        if msg["method"] == "initialize":
            return self._reply(200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {}}}))
        if msg["method"] == "notifications/initialized":
            return self._reply(202)
        repo = msg["params"]["arguments"]["repo"]
        result = {"content": [{"type": "text", "text": "Error: no such repo"}], "isError": True} if repo == "nope" \
            else {"content": [{"type": "text", "text": "rows"}]}
        data = json.dumps({"jsonrpc": "2.0", "id": 2, "result": result})
        self._reply(200, f"event: message\ndata: {data}\n\n", "text/event-stream")


def test_mcp_tool_speaks_streamable_http():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _McpHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/api/mcp"
    try:
        assert codeindex._mcp_tool(url, "cypher", {"repo": "alpha", "query": "q"}) == ("rows", "")
        assert _McpHandler.seen == [("initialize", None), ("notifications/initialized", "s-1"),
                                    ("tools/call", "s-1"), ("DELETE", "s-1")]
        assert codeindex._mcp_tool(url, "cypher", {"repo": "nope", "query": "q"}) == ("", "Error: no such repo")
    finally:
        server.shutdown()
        server.server_close()
    text, why = codeindex._mcp_tool(url, "cypher", {}, timeout=1)
    assert text == "" and why


def test_table_reads_the_cypher_tool_markdown():
    text = json.dumps({"markdown": "| k | n |\n| --- | --- |\n| File | 2 |\n| Function | 5 |\n| bad | x |"}) + \
        "\n\n---\n**Next:** ..."
    assert codeindex._table(text) == {"Function": 5, "File": 2}
    assert codeindex._table("not json") == {}


def test_a_missing_repo_or_branch_is_an_error_line(tmp_path, monkeypatch, repos):
    _registry(tmp_path, monkeypatch, text=REGISTRY.format(tmp=tmp_path.as_posix(), extra="")
              .replace("branch: dev", "branch: nope").replace("../alpha", "../gone"))
    Fake(monkeypatch)
    rc, lines = _lines(codeindex.run, [])
    assert lines[0] == f"gone ERROR: {(tmp_path / 'gone').as_posix()} is not a git checkout"
    assert lines[1] == f"beta ERROR: no branch nope in {repos['beta'].resolve().as_posix()}"
    rc, lines = _lines(codeindex.run, ["beta"])
    assert rc == 1 and "no branch nope" in lines[0]


def test_cli_index_and_health_code_index(tmp_path, monkeypatch, repos, capsys):
    _registry(tmp_path, monkeypatch)
    Fake(monkeypatch)
    assert cli.main(["index", "nope"]) == 2
    assert "unknown repo(s) nope (declared under code_index: alpha, beta)" in capsys.readouterr().err
    assert cli.main(["health", "code-index"]) == 1
    assert cli.main(["index", "--stale"]) == 0
    capsys.readouterr()
    assert cli.main(["health", "code-index"]) == 0
    assert capsys.readouterr().out == "code-index OK (2 repo(s) indexed at their branch head)\n"
    assert cli.main(["health", "gitnexus", "code-index"]) == 0
    assert capsys.readouterr().out == "gitnexus OK\ncode-index OK (2 repo(s) indexed at their branch head)\n"
    assert cli.main(["health", "--all"]) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("code-index OK")


def test_without_code_index_health_all_is_silent_and_a_named_check_says_so(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, text="p: {root: x, stacks: {web: {start: [a], health: {urls: [http://h]}}}}\n")
    monkeypatch.setattr(stacks, "_probe_url", lambda url, timeout: "")
    assert cli.main(["health", "--all"]) == 0
    assert capsys.readouterr().out == "web OK\n"
    assert cli.main(["health", "code-index"]) == 0
    assert capsys.readouterr().out == "code-index OK (no repo declared under code_index:)\n"
