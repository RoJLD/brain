"""xerj as an opt-in backend of the code index (brain.xerj, brain.codebackends; wi-brain-code-index-xerj-backend):
never chosen by default, its node started and stopped by brain index --backend xerj --serve / --stop (a stack's start
and stop), brain index --backend xerj, brain health code-index and the adapter's search. The binary is a stand-in
(fixtures/xerj/fake_xerj.py) that answers with xerj's recorded output (fixtures/xerj, its README says where each
comes from)."""

import json
import os
import sys
from pathlib import Path

import pytest

from brain import cli, codebackends, codeindex, stacks, xerj
from test_codemap import _sha

FIXTURES = Path(__file__).parent / "fixtures" / "xerj"


class FakeXerj:
    def __init__(self, tmp_path, monkeypatch, up=True, **state):
        b = xerj.binary()
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_bytes(b"")
        self.file = tmp_path / "fake-xerj-state.json"
        self.file.write_text(json.dumps(state), encoding="utf-8")
        self.up = up
        monkeypatch.setenv("FAKE_XERJ_STATE", str(self.file))
        monkeypatch.setattr(xerj, "_argv", lambda: [sys.executable, str(FIXTURES / "fake_xerj.py")])
        monkeypatch.setattr(xerj, "answers", lambda *a, **k: self.up)
        monkeypatch.setattr(xerj, "running", lambda: self.up)

    @property
    def state(self) -> dict:
        return json.loads(self.file.read_text(encoding="utf-8"))

    def set(self, **kw) -> None:
        self.file.write_text(json.dumps({**self.state, **kw}), encoding="utf-8")

    def calls(self) -> list[dict]:
        return self.state.get("calls", [])


def _registry(tmp_path, monkeypatch, code_index, root=None, extra=""):
    root = root or tmp_path / "proj"
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo:\n  root: {root.as_posix()}\n  code_index: {json.dumps(code_index)}\n{extra}",
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))


# --- xerj's recorded output ---

def test_a_finished_autoindex_is_read_from_its_real_terminal_line():
    text = (FIXTURES / "autoindex-completed.txt").read_text(encoding="utf-8")
    done, why = xerj.outcome(3, text)
    assert why == "" and done["reason"] == "completed-with-junk" and done["code_files_indexed"] == "194"
    assert xerj.outcome(0, "xerj-done ok=true exit=0 reason=completed wall=22.2s") == (
        {"ok": "true", "exit": "0", "reason": "completed", "wall": "22.2s"}, "")
    refused = (FIXTURES / "autoindex-refused.txt").read_text(encoding="utf-8")
    assert xerj.outcome(3, refused)[1] == ""   # a dataset refused, the others indexed: finished


def test_a_failed_autoindex_says_why_in_one_line():
    aborted = (FIXTURES / "autoindex-aborted.txt").read_text(encoding="utf-8")
    assert xerj.outcome(1, aborted)[1].startswith("exited 1: error: _bulk: HTTP 413 Payload Too Large")
    assert xerj.outcome(3, "xerj-done ok=false exit=3 reason=stale-resume-plan wall=1.0s")[1] == \
        "not ok (stale-resume-plan)"
    assert xerj.outcome(3, "xerj-done ok=true exit=3 reason=completed-with-junk code_files=12 "
                           "code_files_indexed=0")[1] == "no code file indexed of 12"
    assert xerj.outcome(4, '{"decision": "plan"}')[1].startswith("xerj asks a decision (exit 4")
    assert xerj.outcome(None, "", timeout=5)[1] == "no end within 5 s (killed)"
    assert xerj.outcome(0, "<html>502</html>")[1].startswith("exited 0 without its xerj-done line")
    assert xerj.outcome(3, "")[1] == "exited 3 without its xerj-done line (not xerj's answer): no output"


def test_search_hits_map_to_the_adapters_rows():
    found = xerj.rows(json.loads((FIXTURES / "search.json").read_text(encoding="utf-8")))
    assert [r["rank"] for r in found] == [1, 2, 3, 4, 5]
    assert found[0] == {"rank": 1, "path": "src/wal/segment.rs", "line": 119, "name": "rotate", "kind": "function",
                        "score": 14.2, "backend": "xerj"}   # the matched line, not the symbol's first
    assert (found[1]["path"], found[1]["line"], found[1]["name"], found[1]["kind"]) == ("src/wal/mod.rs", 1, "", "")
    assert found[2]["line"] == 40 and found[3]["line"] == 12
    assert xerj.files(found) == ["src/wal/segment.rs", "src/wal/mod.rs", "docs/durability.md", "README.md"]


def test_search_rows_are_relative_to_the_indexed_folder(tmp_path):
    root = tmp_path / "snap"
    answer = {"hits": {"hits": [
        {"_score": 2, "_source": {"ax_path": f"{root.as_posix()}/pkg/a.py", "start_line": 3}},
        {"_score": 1, "_source": {"ax_path": ".\\pkg\\b.py"}},
        {"_score": 1, "_source": {"title": "no path: skipped"}},
        "not a hit"]}}
    found = xerj.rows(answer, root)
    assert [(r["path"], r["line"]) for r in found] == [("pkg/a.py", 3), ("pkg/b.py", None)]


@pytest.mark.parametrize("answer", [None, [], {}, {"hits": []}, {"hits": {"hits": "x"}}, {"error": "boom"}])
def test_an_answer_that_is_not_xerjs_is_refused(answer):
    with pytest.raises(xerj.XerjError, match="cannot read"):
        xerj.rows(answer)


def test_prefixes_have_no_dash_and_shared_ones_are_found():
    names = ["acme", "acme-data", "Acme_Data2", "trade.desk"]
    pre = [xerj.prefix(n) for n in names]
    assert pre == ["bxacme", "bxacmedata", "bxacmedata2", "bxtradedesk"]
    assert all("-" not in p for p in pre)   # xerj searches <prefix>-*: no prefix is another's followed by a dash
    assert xerj.clashes(names) == {}
    assert xerj.clashes(["acme-data", "acme_data", "acme"]) == {"bxacmedata": ["acme-data", "acme_data"]}


# --- never the default ---

def test_xerj_is_chosen_only_when_named(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, [])
    FakeXerj(tmp_path, monkeypatch)
    assert codebackends.why_not("xerj") == ""
    for purpose in ("index", "impact", "health", "search", "code-map"):
        assert "xerj" not in codebackends.choose(purpose)
    assert codebackends.choose("search", "xerj") == ["xerj"]
    assert codebackends.choose("index", "xerj") == ["xerj"]
    with pytest.raises(codeindex.CodeIndexError, match="xerj does not serve impact"):
        codebackends.choose("impact", "xerj")
    with pytest.raises(codeindex.CodeIndexError, match="xerj does not serve code-map"):
        codebackends.choose("code-map", "xerj")


def test_search_without_a_named_backend_leaves_the_authority_to_gitnexus(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, [])
    FakeXerj(tmp_path, monkeypatch)
    with pytest.raises(codeindex.CodeIndexError, match="GitNexus stays the search authority"):
        codebackends.search("fsync the wal", "alpha")
    with pytest.raises(codeindex.CodeIndexError, match="gitnexus does not serve search"):
        codebackends.search("fsync the wal", "alpha", backend="gitnexus")


def test_not_installed_is_said_and_never_runs(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    assert not xerj.installed()
    assert codebackends.why_not("xerj").startswith("xerj is not installed")
    with pytest.raises(xerj.XerjError, match="not installed"):
        xerj._exec(["search"], 5)
    assert cli.main(["index", "--backend", "xerj"]) == 1
    assert "brain index: xerj is not installed" in capsys.readouterr().out
    monkeypatch.setattr(xerj, "answers", lambda *a, **k: False)
    assert xerj.serve(sys.stdout) == 1 and "xerj FAILED: xerj is not installed" in capsys.readouterr().out


# --- brain index --backend xerj and brain health code-index ---

def test_index_records_the_branch_head_and_health_says_it_without_counting(tmp_path, monkeypatch, make_repo, capsys):
    repo = make_repo("alpha", {"a.py": "def f():\n    return 1\n"})
    (repo / "untracked.py").write_text("x = 1\n", encoding="utf-8")
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    fake = FakeXerj(tmp_path, monkeypatch, up=False)
    assert cli.main(["index", "--backend", "xerj"]) == 0
    out = capsys.readouterr().out
    assert out == (f"alpha NOT INDEXED (xerj): main@{_sha(repo)[:7]}\n"
                   f"(xerj does not answer at {xerj.URL}; brain up xerj starts it)\n")
    assert cli.main(["index", "--backend", "xerj", "--all"]) == 1
    assert "xerj does not answer at" in capsys.readouterr().out and fake.calls() == []
    fake.up = True
    assert cli.main(["index", "--backend", "xerj", "--all"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("alpha OK (xerj, ") and f"main@{_sha(repo)[:7]}, prefix bxalpha, completed-with-junk)" in out
    call = fake.calls()[-1]
    snap = xerj.snapshot_dir("alpha")
    assert call["args"] == ["autoindex", str(snap), "--url", xerj.URL, "--prefix", "bxalpha", "--state-dir",
                            str(xerj.state_dir("alpha")), "--no-graph", "--max-minutes", "0", "--progress", "plain"]
    assert call["env"] == {"XERJ_DISABLE_FEEDBACK": "true", "XERJ_NO_AUTOSTART": "1", "HF_HUB_OFFLINE": "1"}
    assert (snap / "a.py").is_file() and not (snap / "untracked.py").exists()   # the commit, not the working tree
    rec = xerj.read_record()["alpha"]
    assert (rec["sha"], rec["prefix"], rec["code_files_indexed"]) == (_sha(repo), "bxalpha", "194")
    repos = codeindex.load(opt_in=True)[1]   # health's own line (a counted backend runs beside it on a real machine)
    assert codebackends.xerj_health(repos) == (
        0, f"code-index xerj OK (opt-in, 1 repo(s) at their branch head, node up at {xerj.URL})")
    make_repo.commit(repo, {"a.py": "def f():\n    return 2\n"})
    fake.up = False
    rc, out = codebackends.xerj_health(repos)
    assert rc == 0   # opt-in: said, never counted
    assert "code-index xerj STALE (opt-in, not counted): alpha (main moved off the index" in out
    assert "node down at" in out and "brain up xerj starts it" in out
    fake.up = True
    assert cli.main(["index", "--backend", "xerj", "--stale"]) == 0
    assert cli.main(["index", "--backend", "xerj", "--stale"]) == 0
    assert capsys.readouterr().out.endswith("every repo is indexed at its branch head (xerj)\n")
    assert (snap / "a.py").read_text(encoding="utf-8") == "def f():\n    return 2\n"


def test_a_failed_autoindex_is_one_line_exit_1_and_no_record(tmp_path, monkeypatch, make_repo, capsys):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    FakeXerj(tmp_path, monkeypatch, autoindex="autoindex-aborted.txt", exit=1)
    assert cli.main(["index", "--backend", "xerj", "alpha"]) == 1
    out = capsys.readouterr().out
    assert "alpha FAILED (xerj" in out and "HTTP 413 Payload Too Large" in out and xerj.read_record() == {}


def test_a_slow_autoindex_is_killed_at_its_deadline(tmp_path, monkeypatch, make_repo, capsys):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    FakeXerj(tmp_path, monkeypatch, mode="slow")
    monkeypatch.setattr(xerj, "INDEX_TIMEOUT", 1.0)
    assert cli.main(["index", "--backend", "xerj", "alpha"]) == 1
    assert "no end within 1 s (killed)" in capsys.readouterr().out


def test_xerj_alone_never_stands_for_a_counted_backend(tmp_path, monkeypatch, make_repo, capsys):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    FakeXerj(tmp_path, monkeypatch)
    with pytest.raises(codeindex.CodeIndexError, match="no stack declares index:"):
        codeindex.load()   # the default path's verdict is unchanged by an installed opt-in arm
    assert cli.main(["health", "code-index"]) == 2 and "no stack declares index:" in capsys.readouterr().err
    ix, repos = codeindex.load(opt_in=True)   # xerj named
    assert ix is None and list(repos) == ["alpha"]
    assert cli.main(["index", "--backend", "xerj"]) == 0


def test_repos_sharing_a_prefix_are_neither_indexed_nor_searched(tmp_path, monkeypatch, make_repo, capsys):
    a, b = make_repo("acme-data", {"a.py": "x = 1\n"}), make_repo("acme_data", {"b.py": "y = 2\n"})
    _registry(tmp_path, monkeypatch, [a.as_posix(), b.as_posix()], root=tmp_path)
    fake = FakeXerj(tmp_path, monkeypatch)
    assert cli.main(["index", "--backend", "xerj", "--all"]) == 1
    assert "acme-data, acme_data share xerj's prefix bxacmedata" in capsys.readouterr().out
    assert fake.calls() == [] and xerj.read_record() == {}
    with pytest.raises(codeindex.CodeIndexError, match="share xerj's prefix bxacmedata"):
        codebackends.search("x", "acme-data", backend="xerj")


def test_health_says_error_apart_from_stale(tmp_path, monkeypatch, make_repo):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    FakeXerj(tmp_path, monkeypatch, up=False)
    xerj.save("alpha", {"sha": "0" * 40})
    _, repos = codeindex.load(opt_in=True)
    assert " xerj STALE (opt-in, not counted): alpha (main moved off the index" in codebackends.xerj_health(repos)[1]
    monkeypatch.setattr(codebackends, "xerj_state", lambda r, rec: ("ERROR", "no branch main"))
    rc, line = codebackends.xerj_health(repos)
    assert rc == 0 and " xerj ERROR (opt-in, not counted): alpha (no branch main)" in line


# --- the adapter's search ---

def test_search_runs_xerj_search_json_and_returns_rows(tmp_path, monkeypatch, make_repo):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    fake = FakeXerj(tmp_path, monkeypatch)
    found = codebackends.search("fsync the WAL segment on rotation", "alpha", k=3, backend="xerj")
    assert [(r["path"], r["line"]) for r in found] == [("src/wal/segment.rs", 119), ("src/wal/mod.rs", 1),
                                                       ("src/wal/segment.rs", 40)]
    call = fake.calls()[-1]
    assert call["args"] == ["search", "--url", xerj.URL, "--prefix", "bxalpha", "-k", "3", "--json",
                            "--disable-feedback", "fsync the WAL segment on rotation"]
    assert call["env"]["XERJ_NO_AUTOSTART"] == "1" and call["env"]["XERJ_DISABLE_FEEDBACK"] == "true"
    with pytest.raises(codeindex.CodeIndexError, match="unknown repo beta"):
        codebackends.search("wal", "beta", backend="xerj")


@pytest.mark.parametrize("mode, why", [
    ("down", "exited 1: xerj search: query failed against http://127.0.0.1:9200/bxalpha-\\*: connection refused"),
    ("garbage", "cannot read \\(no JSON\\)"),
])
def test_search_down_or_garbage_is_one_line(tmp_path, monkeypatch, make_repo, mode, why):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    FakeXerj(tmp_path, monkeypatch, mode=mode)
    with pytest.raises(codeindex.CodeIndexError, match=why):
        codebackends.search("wal", "alpha", backend="xerj")


def test_search_slow_is_killed_and_a_stopped_node_is_never_started(tmp_path, monkeypatch, make_repo):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    fake = FakeXerj(tmp_path, monkeypatch, mode="slow")
    monkeypatch.setattr(xerj, "QUERY_TIMEOUT", 1.0)
    with pytest.raises(codeindex.CodeIndexError, match="no answer within 1 s"):
        codebackends.search("wal", "alpha", backend="xerj")
    fake.up = False
    n = len(fake.calls())
    with pytest.raises(codeindex.CodeIndexError, match="brain up xerj starts it"):
        codebackends.search("wal", "alpha", backend="xerj")
    assert len(fake.calls()) == n   # no client call: xerj's clients would start a stopped node
    with pytest.raises(xerj.XerjError, match="does not start with '-'"):
        xerj.search("--url http://elsewhere", "alpha")


# --- the service: --serve and --stop ---

def test_serve_starts_the_node_detached_on_loopback_with_feedback_off(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    fake = FakeXerj(tmp_path, monkeypatch, up=False)
    assert cli.main(["index", "--backend", "xerj", "--serve"]) == 0
    assert capsys.readouterr().out.startswith(f"xerj started (pid 4242, {xerj.URL}, data ")
    call = fake.calls()[-1]
    assert call["args"] == ["--detach", "--insecure", "--bind", "127.0.0.1", "--port", "9200", "--no-auto-port",
                            "--embed-mode", "lexical", "--disable-feedback", "--data-dir", str(xerj.data_dir())]
    assert call["env"] == {"XERJ_DISABLE_FEEDBACK": "true", "XERJ_NO_AUTOSTART": "1", "HF_HUB_OFFLINE": "1"}
    assert not any(a in ("init", "feedback") for c in fake.calls() for a in c["args"])
    fake.up = True
    assert cli.main(["index", "--backend", "xerj", "--serve"]) == 0
    assert capsys.readouterr().out == f"xerj OK (already up at {xerj.URL})\n" and len(fake.calls()) == 1
    fake.up, n = False, len(fake.calls())
    fake.set(mode="down")
    assert cli.main(["index", "--backend", "xerj", "--serve"]) == 1
    assert "xerj FAILED: exited 1: error: Address already in use" in capsys.readouterr().out
    assert len(fake.calls()) == n + 1


def test_serve_and_stop_are_xerjs_alone(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    assert cli.main(["index", "--serve"]) == 2
    assert cli.main(["index", "--backend", "cbm", "--stop"]) == 2
    assert cli.main(["index", "--backend", "xerj", "--serve", "alpha"]) == 2
    assert "--serve and --stop start and stop xerj's node" in capsys.readouterr().err


def test_serve_leaves_another_service_on_the_port_alone(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    fake = FakeXerj(tmp_path, monkeypatch, up=False)
    monkeypatch.setattr(xerj, "answers", lambda *a, **k: True)   # something answers, but not the engine's xerj
    assert xerj.serve(sys.stdout) == 1
    assert "answers but not the engine's xerj" in capsys.readouterr().out and fake.calls() == []


def test_serve_slow_is_killed_at_its_deadline(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    FakeXerj(tmp_path, monkeypatch, up=False, mode="slow")
    monkeypatch.setattr(xerj, "SERVE_TIMEOUT", 1.0)
    assert xerj.serve(sys.stdout) == 1 and "xerj FAILED: no answer within 1 s (its log: " in capsys.readouterr().out


SOFT = os.name != "nt"   # POSIX asks first (SIGTERM); a detached node on Windows has no console: forced at once


class Procs:
    """Live processes by pid (their program file), and the kills asked; ``after_soft``: what a pid runs once the
    soft signal is sent (None: gone; 'stays': still the node; a path: another program got the pid)."""
    def __init__(self, monkeypatch, exes: dict, after_soft=None):
        self.exes, self.kills, self.after_soft = dict(exes), [], after_soft
        monkeypatch.setattr(xerj, "_exe", lambda pid: self.exes.get(pid, ""))
        monkeypatch.setattr(xerj, "_kill", self.kill)
        monkeypatch.setattr(xerj, "_sleep", lambda s: None)
        monkeypatch.setattr(xerj, "STOP_TIMEOUT", 0.0)

    def kill(self, pid, force):
        self.kills.append((pid, force))
        if force or self.after_soft is None:
            self.exes.pop(pid, None)
        elif self.after_soft != "stays":
            self.exes[pid] = self.after_soft


def _lock(pid: int, name: str = "node.lock") -> None:
    xerj.data_dir().mkdir(parents=True, exist_ok=True)
    (xerj.data_dir() / name).write_text(f"{pid}\n", encoding="utf-8")


OTHER = str(Path(sys.executable).resolve())


def test_stop_kills_only_the_engines_xerj_its_lock_names(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    monkeypatch.setattr(xerj, "answers", lambda *a, **k: False)
    procs = Procs(monkeypatch, {4242: str(xerj.binary()), 777: OTHER, 778: str(tmp_path / "elsewhere" / "xerj.exe")})
    assert xerj.stop(sys.stdout) == 0 and capsys.readouterr().out == "xerj is not running\n"
    for pid, exe in ((777, OTHER), (778, str(tmp_path / "elsewhere" / "xerj.exe"))):   # another xerj too
        _lock(pid)
        assert xerj.stop(sys.stdout) == 1
        assert capsys.readouterr().out == f"xerj left alone: pid {pid} of its lock is {exe}, not " \
                                          f"{xerj.binary().as_posix()}\n"
    assert procs.kills == []
    _lock(4242)
    assert cli.main(["index", "--backend", "xerj", "--stop"]) == 0
    assert capsys.readouterr().out.startswith("xerj stopped (pid 4242, ") and procs.kills == [(4242, not SOFT)]
    assert xerj.stop(sys.stdout) == 0
    assert capsys.readouterr().out == "xerj is not running (pid 4242 of its lock is gone)\n"


def test_stop_forces_a_node_that_does_not_end_and_reads_the_held_lock(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    procs = Procs(monkeypatch, {4242: str(xerj.binary())}, after_soft="stays")
    _lock(4242, "node.lock.pid")
    assert xerj.stop(sys.stdout) == 0
    assert procs.kills == ([(4242, False), (4242, True)] if SOFT else [(4242, True)])
    assert ", forced)" in capsys.readouterr().out


@pytest.mark.skipif(not SOFT, reason="POSIX: the soft signal, then a re-check before the forced one")
def test_a_pid_reused_after_the_soft_stop_is_never_forced(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    procs = Procs(monkeypatch, {4242: str(xerj.binary())}, after_soft=OTHER)
    _lock(4242)
    assert xerj.stop(sys.stdout) == 0 and procs.kills == [(4242, False)]


def test_stop_waits_for_the_node_to_end(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    procs = Procs(monkeypatch, {4242: str(xerj.binary())}, after_soft="stays")
    monkeypatch.setattr(xerj, "STOP_TIMEOUT", 60.0)
    polls = []

    def sleep(s):   # the node ends on the third poll of the wait
        polls.append(s)
        if len(polls) == 3:
            procs.exes.pop(4242, None)
    monkeypatch.setattr(xerj, "_sleep", sleep)
    monkeypatch.setattr(xerj, "_kill", lambda pid, force: procs.kills.append((pid, force)))   # it ends by itself
    _lock(4242)
    assert xerj.stop(sys.stdout) == 0 and len(polls) == 3 and procs.kills == [(4242, not SOFT)]


def test_stop_leaves_a_node_it_did_not_start_alone(tmp_path, monkeypatch, capsys):
    _registry(tmp_path, monkeypatch, [])
    monkeypatch.setattr(xerj, "answers", lambda *a, **k: True)
    procs = Procs(monkeypatch, {})
    assert xerj.stop(sys.stdout) == 1 and "not the engine's node" in capsys.readouterr().out and procs.kills == []


# --- the real probes: the port, the process ---

def test_answers_probes_the_port_without_a_proxy(monkeypatch):
    import http.server
    import threading

    class Ok(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"version": {"number": "8.13.0"}}')

        def log_message(self, *a):
            pass
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")   # a proxy would make the probe fail
    srv = http.server.HTTPServer(("127.0.0.1", 0), Ok)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert xerj.answers(f"http://127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()
        srv.server_close()
    assert not xerj.answers(f"http://127.0.0.1:{srv.server_port}", timeout=1.0)


def test_exe_reads_a_live_process_and_running_needs_the_engines_binary(tmp_path, monkeypatch):
    me = xerj._exe(os.getpid())
    assert me and Path(me).name.lower().startswith("python")
    assert xerj._exe(2 ** 22 + 7) == ""   # no such process
    _registry(tmp_path, monkeypatch, [])
    monkeypatch.setattr(xerj, "answers", lambda *a, **k: True)
    _lock(os.getpid())
    assert not xerj.running()   # a live python holds the lock: not the engine's xerj
    monkeypatch.setattr(xerj, "binary", lambda: Path(me))
    assert xerj._ours(me) and xerj.running()
    monkeypatch.setattr(xerj, "answers", lambda *a, **k: False)
    assert not xerj.running()


# --- the snapshot ---

def test_extract_keeps_files_and_folders_only(tmp_path):
    import io
    import tarfile
    tar = tmp_path / "t.tar"
    with tarfile.open(tar, "w") as t:
        for name in ("src/ok.py", "../evil.py", "C:evil.py"):
            data = b"x = 1\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("lnk")
        link.type, link.linkname = tarfile.SYMTYPE, "../../outside"
        t.addfile(link)
    into = tmp_path / "into"
    into.mkdir()
    assert sorted(xerj.extract(tar, into)) == ["../evil.py", "C:evil.py", "lnk"]
    assert (into / "src" / "ok.py").is_file() and sorted(p.name for p in tmp_path.iterdir()) == ["into", "t.tar"]


def test_a_failed_snapshot_is_one_line(tmp_path, make_repo):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    with pytest.raises(xerj.XerjError, match="git archive of .* exited 128"):
        xerj.snapshot(repo, "0" * 40, tmp_path / "snaps" / "alpha")
    blocked = tmp_path / "file"
    blocked.write_text("", encoding="utf-8")
    with pytest.raises(xerj.XerjError, match="snapshot of .* into "):
        xerj.snapshot(repo, _sha(repo), blocked / "alpha")   # its parent is a file: the disk refuses


def test_the_documented_stack_declaration_loads(tmp_path, monkeypatch):
    """docs/code-index.md's stack: started and stopped by the engine, never watched, its tier keys present."""
    doc = (Path(__file__).parents[1] / "docs" / "code-index.md").read_text(encoding="utf-8")
    block = doc.split("```yaml\n", 1)[1].split("```", 1)[0]
    extra = "".join("  " + line + "\n" if line.strip() else "\n" for line in block.splitlines())   # under a project
    _registry(tmp_path, monkeypatch, [], extra=extra)
    s = stacks.load()["xerj"]
    assert s.start == ["brain", "index", "--backend", "xerj", "--serve"]
    assert s.stop == ["brain", "index", "--backend", "xerj", "--stop"]
    assert s.health_urls == [f"{xerj.URL}/"] and not s.watch
    assert s.tier["profile"] == "custom" and s.tier["fallback"]
