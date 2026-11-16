"""codebase-memory-mcp as a code index backend (brain.cbm, brain.codebackends): its settings kept off, its stdio
session under a deadline, brain index, brain health code-index and brain impact through it. The server is a stand-in
(fixtures/cbm/fake_cbm.py) that answers with CBM v0.12.1's real answers (fixtures/cbm/answers.json)."""

import json
import sys
from pathlib import Path

import pytest

from brain import cbm, cli, codebackends, codeindex
from conftest import run_git
from test_codemap import FakeGitNexus, _sha
from test_impact import GO2, lab  # noqa: F401  (lab: the fixture)

FIXTURES = Path(__file__).parent / "fixtures" / "cbm"
ANSWERS = json.loads((FIXTURES / "answers.json").read_text(encoding="utf-8"))
P = "brain-wt-0f3c9a21"   # the recorded answers' project


class FakeCbm:
    def __init__(self, tmp_path, monkeypatch, **state):
        b = cbm.binary()
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_bytes(b"")
        self.file = tmp_path / "fake-cbm-state.json"
        self.file.write_text(json.dumps(state), encoding="utf-8")
        monkeypatch.setenv("FAKE_CBM_STATE", str(self.file))
        monkeypatch.setattr(cbm, "_argv", lambda: [sys.executable, str(FIXTURES / "fake_cbm.py")])

    @property
    def state(self) -> dict:
        return json.loads(self.file.read_text(encoding="utf-8"))

    def set(self, **kw) -> None:
        self.file.write_text(json.dumps({**self.state, **kw}), encoding="utf-8")

    def calls(self) -> list[str]:
        return [name for name, _ in self.state.get("calls", [])]


OFF = {k: "false" for k in cbm.OFF}


# --- its settings ---

def test_the_settings_are_read_from_the_real_config_list():
    text = (FIXTURES / "config-list.txt").read_text(encoding="utf-8")
    assert "ui_enabled                = false" in text


def test_settings_on_by_default_are_set_off_before_any_session(tmp_path, monkeypatch):
    fake = FakeCbm(tmp_path, monkeypatch)
    assert cbm.not_off(cbm.settings()) == ["ui_enabled", "auto_watch", "watcher_enabled"]
    assert cbm.ensure_off() == ["ui_enabled", "auto_watch", "watcher_enabled"]
    assert fake.state["sets"] == [["ui_enabled", "false"], ["auto_watch", "false"], ["watcher_enabled", "false"]]
    assert cbm.ensure_off() == [] and cbm.not_off(cbm.settings()) == []
    fake.set(settings={}, sets=[])
    with cbm.Session() as s:
        cbm.status(s, P)
    assert [k for k, _ in fake.state["sets"]] == ["ui_enabled", "auto_watch", "watcher_enabled"]


def test_a_missing_setting_counts_as_on():
    assert cbm.not_off({"ui_enabled": "false"}) == ["auto_watch", "watcher_enabled", "auto_index"]


def test_health_says_unsafe_while_a_setting_is_on(tmp_path, monkeypatch, capsys):
    FakeCbm(tmp_path, monkeypatch)
    _registry(tmp_path, monkeypatch, [])
    assert cli.main(["health", "code-index"]) == 1
    out = capsys.readouterr().out
    assert "code-index cbm UNSAFE: its settings ui_enabled, auto_watch, watcher_enabled are on" in out
    assert "brain index --backend cbm sets them off" in out
    assert cli.main(["index"]) == 0 and "set to false" in capsys.readouterr().out
    assert cli.main(["health", "code-index"]) == 0
    assert capsys.readouterr().out.startswith("code-index cbm OK (settings off, 0 repo(s)")


# --- the session: down, slow, garbage ---

def test_not_installed_is_said_and_never_runs(tmp_path, monkeypatch):
    assert not cbm.installed()
    assert codebackends.why_not("cbm").startswith("codebase-memory-mcp is not installed")
    with pytest.raises(cbm.CbmError, match="not installed"):
        cbm.Session()


@pytest.mark.parametrize("mode, message", [("slow", "tools/call: no answer in 2 s"),
                                           ("garbage", "an answer that is not JSON: Segmentation fault"),
                                           ("crash", "the server ended"),
                                           ("error:index_status", "index_status: project not found or not indexed")])
def test_a_slow_garbled_or_failing_server_is_one_line_and_never_left_running(tmp_path, monkeypatch, mode, message):
    fake = FakeCbm(tmp_path, monkeypatch, settings=OFF, mode=mode)
    s = cbm.Session()
    with pytest.raises(cbm.CbmError, match=message):
        s.call("index_status", {"project": P, "format": "json"}, timeout=2)
    s.close()
    assert s._p.poll() is not None
    assert fake.calls() == ["index_status"]


def test_the_real_answers_are_read(tmp_path, monkeypatch):
    FakeCbm(tmp_path, monkeypatch, settings=OFF)
    with cbm.Session() as s:
        got = cbm.index(s, tmp_path, P, mode="fast")
        assert (got["nodes"], got["edges"], got["status"]) == (17537, 99160, "indexed")
        assert [p["name"] for p in cbm.projects(s)] == ["alpha", "brain", "beta", P]
        with pytest.raises(cbm.CbmError, match="project not found or not indexed"):
            cbm.status(s, "nope")
        answer = cbm.changes(s, P, "origin/main", 2)
    symbols, callers = codebackends.symbols_of(answer)
    assert [(x["name"], x["path"], x["lines"]) for x in symbols] == [
        ("_now", "packages/brain/src/brain/codeindex.py", [214, 216])]
    assert [(x["name"], x["level"]) for x in callers] == [("index_one", 1), ("build", 1), ("run", 2),
                                                          ("main", 2), ("_by_index", 2)]
    assert not codebackends.truncated(answer)
    assert codebackends.qualified(P, "packages/brain/src/brain/codeindex.py", "_now") == symbols[0]["id"]


def test_detect_changes_asks_for_the_seeds_and_the_callers_named(tmp_path, monkeypatch):
    fake = FakeCbm(tmp_path, monkeypatch, settings=OFF)
    with cbm.Session() as s:
        cbm.changes(s, P, "abc123", 3)
    args = fake.state["calls"][0][1]
    names = {t["name"]: set(t["inputSchema"]["properties"]) for t in ANSWERS["tools"]}
    assert set(args) <= names["detect_changes"]   # v0.12.1's arguments
    assert (args["base_branch"], args["depth"], args["seeds"], args["via"]) == ("abc123", 3, "list", True)


# --- choosing a backend ---

def _registry(tmp_path, monkeypatch, code_index, stack=False, root=None):
    root = root or tmp_path / "proj"
    text = f"demo:\n  root: {root.as_posix()}\n  code_index: {json.dumps(code_index)}\n"
    if stack:
        text += ("  stacks:\n    gitnexus:\n      start: [docker, compose, up, -d]\n"
                 "      health: {urls: ['http://127.0.0.1:4747/api/health']}\n"
                 "      index: {api: 'http://127.0.0.1:4747', container: gitnexus}\n")
    reg = tmp_path / "projects.yaml"
    reg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))


def test_gitnexus_first_cbm_first_on_a_worktree_and_each_one_named(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch, [], stack=True)
    assert codebackends.choose("index") == ["gitnexus"]
    FakeCbm(tmp_path, monkeypatch, settings=OFF)
    assert codebackends.choose("index") == ["gitnexus", "cbm"]
    assert codebackends.choose("impact") == ["gitnexus", "cbm"]
    assert codebackends.choose("impact", worktree=True) == ["cbm", "gitnexus"]
    assert codebackends.choose("code-map") == ["gitnexus"]
    assert codebackends.choose("impact", "gitnexus", worktree=True) == ["gitnexus"]
    with pytest.raises(codeindex.CodeIndexError, match="cbm does not serve code-map"):
        codebackends.choose("code-map", "cbm")
    _registry(tmp_path, monkeypatch, [])
    assert codebackends.choose("index") == ["cbm"]   # no Docker stack: CBM is the machine's code index


def test_every_backend_is_declared_in_the_tier_registry():
    from brain import tiers
    reg, errs = tiers.capabilities()
    assert errs == []
    for b in codebackends.BACKENDS.values():
        assert reg[b.tier].fallback and reg[b.tier].provides


# --- brain index and brain health with cbm ---

def test_index_with_cbm_records_the_head_and_health_follows_it(tmp_path, monkeypatch, make_repo, capsys):
    repo = make_repo("alpha", {"a.py": "def f():\n    return 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    fake = FakeCbm(tmp_path, monkeypatch, settings=OFF)
    assert cli.main(["index"]) == 0
    assert capsys.readouterr().out == f"alpha NOT INDEXED (cbm): main@{_sha(repo)[:7]}\n"
    assert cli.main(["health", "code-index"]) == 1
    assert "code-index cbm STALE: alpha (not indexed)" in capsys.readouterr().out
    assert cli.main(["index", "--all"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("alpha OK (cbm, ") and f"main@{_sha(repo)[:7]}, 17537 nodes, 99160 edges)" in out
    rec = cbm.read_record()["alpha"]
    assert (rec["sha"], rec["path"], rec["dirty"], rec["version"]) == (_sha(repo), repo.as_posix(), False, "0.12.1")
    assert fake.state["calls"][-1] == ["index_repository", {"repo_path": repo.as_posix(), "name": "alpha",
                                                            "mode": "full"}]
    assert cli.main(["health", "code-index"]) == 0
    make_repo.commit(repo, {"a.py": "def f():\n    return 2\n"})
    assert cli.main(["health", "code-index"]) == 1
    assert "alpha (main moved off the index" in capsys.readouterr().out
    assert cli.main(["index", "--stale"]) == 0 and cli.main(["index", "--stale"]) == 0
    assert capsys.readouterr().out.endswith("every repo is indexed at its checkout's HEAD (cbm)\n")


def test_index_with_cbm_down_is_one_line_and_exit_1(tmp_path, monkeypatch, make_repo, capsys):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    FakeCbm(tmp_path, monkeypatch, settings=OFF, mode="crash")
    assert cli.main(["index", "alpha"]) == 1
    assert "alpha FAILED (cbm" in capsys.readouterr().out and cbm.read_record() == {}


def test_index_backend_gitnexus_without_its_stack_is_a_declaration_error(tmp_path, monkeypatch, make_repo, capsys):
    repo = make_repo("alpha", {"a.py": "x = 1\n"})
    _registry(tmp_path, monkeypatch, ["."], root=repo)
    FakeCbm(tmp_path, monkeypatch, settings=OFF)
    assert cli.main(["index", "--backend", "gitnexus", "alpha"]) == 2
    assert "no stack declares index:" in capsys.readouterr().err


# --- brain impact on a worktree ---

def _impact_answers(tmp_path, monkeypatch) -> None:
    """The recorded answers, detect_changes's over the lab repo: go changed, called by cli.main and Engine.run."""
    answers = json.loads(json.dumps(ANSWERS))
    d = answers["detect_changes"]["result"]["structuredContent"]
    d.update(changed_files=["src/lab/core.py"], seeds=[
        {"qn": f"{P}.src.lab.core.go", "label": "Function", "file": "src/lab/core.py", "start": 1, "end": 2,
         "seed_reason": "hunk"}], impacted=[
        {"qn": f"{P}.src.lab.cli.main", "label": "Function", "file": "src/lab/cli.py", "hop": 1,
         "via_qn": f"{P}.src.lab.core.go", "via_edge": "CALLS"},
        {"qn": f"{P}.src.lab.core.Engine.run", "label": "Method", "file": "src/lab/core.py", "hop": 1,
         "via_qn": f"{P}.src.lab.core.go", "via_edge": "CALLS"}])
    answers["detect_changes"]["result"]["content"][0]["text"] = json.dumps(d)
    f = tmp_path / "answers-lab.json"
    f.write_text(json.dumps(answers), encoding="utf-8")
    monkeypatch.setenv("FAKE_CBM_ANSWERS", str(f))


def _worktree(lab, make_repo, tmp_path):
    wt = tmp_path / "lab-wt"
    run_git(lab, "worktree", "add", "-q", "-b", "wt-branch", str(wt))
    make_repo.write(wt, {"src/lab/core.py": GO2})
    return wt


def _impact(capsys, repo, *args):
    rc = cli.main(["impact", *args, "--repo-dir", str(repo), "--json"])
    return rc, json.loads(capsys.readouterr().out)


def test_impact_on_a_worktree_asks_cbm_first_and_places_the_coderefs(lab, make_repo, monkeypatch, capsys, tmp_path):
    gn = FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, [])
    fake = FakeCbm(tmp_path, monkeypatch, settings=OFF)
    _impact_answers(tmp_path, monkeypatch)
    wt = _worktree(lab, make_repo, tmp_path)
    rc, d = _impact(capsys, wt)
    assert (rc, d["mode"], d["why_files"]) == (0, "cbm", "")
    assert [s["name"] for s in d["symbols"]] == ["go"]
    assert [(c["name"], c["level"], c["callee"].rsplit(".", 1)[-1]) for c in d["callers"]] == [
        ("main", 1, "go"), ("run", 1, "go")]
    assert [(t["ref"], t["how"]) for t in d["coderefs"]] == [
        ("code:lab:lab/cli.py::main", "caller"), ("code:lab:lab/core.py::Engine.run", "caller"),
        ("code:lab:lab/core.py::go", "symbol")]   # the same CodeRefs GitNexus's index places (test_impact)
    name = codebackends.temp_name("lab", wt)
    assert fake.calls() == ["index_repository", "detect_changes", "delete_project"]   # the temporary index deleted
    assert [a.get("project") or a.get("name") for _, a in fake.state["calls"]] == [name] * 3
    assert fake.state["calls"][1][1]["base_branch"] == d["base"]
    assert not gn.queries                       # GitNexus was not asked
    assert "feat-cli" in [f["id"] for f in d["features"]]   # reached through its caller
    cli.main(["impact", "--repo-dir", str(wt)])
    assert capsys.readouterr().out.splitlines()[1] == (
        "symbols (codebase-memory-mcp, this checkout indexed in place): 1 touched in 1 file(s), 2 caller(s)")


def test_impact_falls_back_from_cbm_to_gitnexus_then_to_the_file_level(lab, make_repo, monkeypatch, capsys,
                                                                        tmp_path):
    FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, [], up=False)
    fake = FakeCbm(tmp_path, monkeypatch, settings=OFF, mode="error:detect_changes")
    wt = _worktree(lab, make_repo, tmp_path)
    rc, d = _impact(capsys, wt)
    assert (rc, d["mode"]) == (0, "files")
    assert d["why_files"] == ("codebase-memory-mcp: detect_changes: project not found or not indexed; gitnexus does "
                              "not answer at http://127.0.0.1:4747: brain up gitnexus, then brain index lab")
    assert [(t["ref"], t["how"], t["via"]) for t in d["coderefs"]] == [("code:lab:lab/core.py::go", "ast", "modified")]
    assert fake.calls()[-1] == "delete_project"   # deleted even when detect_changes failed


def test_impact_of_a_commit_range_is_not_asked_of_cbm(lab, make_repo, monkeypatch, capsys, tmp_path):
    FakeGitNexus(monkeypatch, {"lab": (lab, _sha(lab))}, [], up=False)
    fake = FakeCbm(tmp_path, monkeypatch, settings=OFF)
    make_repo.commit(lab, {"src/lab/core.py": GO2})
    rc, d = _impact(capsys, lab, "--diff", "main..HEAD", "--backend", "cbm")
    assert (rc, d["mode"]) == (0, "files")
    assert d["why_files"] == "codebase-memory-mcp reads a checkout's working tree, not a commit range"
    assert fake.calls() == []
