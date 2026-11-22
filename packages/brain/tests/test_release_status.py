"""wi-brain-release-status: brain release status, where a release stands (wave, version PR, tag, pin PR, install,
verify) and the next step with its owner; brain release verify, the after-install checks in one call, logged and
recorded (docs/release.md, « Where a release stands »)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from brain import classes, cli, releasestatus as rs, tagsig, update

NODES = """\
- {id: wave-s1, type: Milestone, status: reached, title: "one", props: {kind: wave, release: 0.1.0, seq: 1}}
- {id: wave-s2, type: Milestone, status: active, title: "two", props: {kind: wave, release: 0.2.0, seq: 2}}
- {id: wi-a, type: WorkItem, status: todo, title: "A"}
"""
EDGES = "- {from: wi-a, to: wave-s2, type: part_of}\n"


def _brain(tmp_path: Path, pin: str = "v0.1.0") -> Path:
    root = tmp_path / "planning"
    (root / "notes" / "graph" / "nodes").mkdir(parents=True)
    (root / "notes" / "graph" / "edges").mkdir()
    (root / "notes" / "graph" / "nodes" / "plan.yaml").write_text(NODES, encoding="utf-8")
    (root / "notes" / "graph" / "edges" / "plan.yaml").write_text(EDGES, encoding="utf-8")
    (root / "config.json").write_text(json.dumps({"v": 1, "engine": {"repo": "owner/engine", "pin": pin,
                                                                     "installer": "install.ps1"},
                                                  "identity": {"display_name": "Ada"}}), encoding="utf-8")
    return root


class Fake:
    """git show origin/<branch>:config.json and gh pr list answered from the test's data; every call kept."""

    def __init__(self, main_pin="v0.1.0", prs=(), fail=()):
        self.main_pin, self.prs, self.fail, self.calls = main_pin, list(prs), set(fail), []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        tool = argv[0]
        if tool in self.fail:
            raise FileNotFoundError(tool)
        if tool == "git" and "show" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"engine": {"pin": self.main_pin}}), "")
        if tool == "git":   # the default branch: origin/HEAD
            return subprocess.CompletedProcess(argv, 0, "origin/main\n", "")
        if tool == "gh":
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.prs), "")
        raise AssertionError(argv)


@pytest.fixture
def net(monkeypatch):
    """The engine's tags and the tag's signature, as the test sets them (no network)."""
    state = {"tags": ["v0.1.0"], "verdict": tagsig.VERIFIED}
    monkeypatch.setattr(update, "remote_tags", lambda repo, runner=None: list(state["tags"]))
    monkeypatch.setattr(tagsig, "verify", lambda root, repo, tag, runner=None: tagsig.verdict(
        state["verdict"], tag, signer="ada", why="" if state["verdict"] == tagsig.VERIFIED else "no signature"))
    return state


def _steps(rep):
    return {s["name"]: (s["state"], s["detail"]) for s in rep["steps"]}


def test_a_release_not_started_names_the_wave_first_and_its_owner(tmp_path, net):
    root = _brain(tmp_path)
    rep = rs.status(root, runner=Fake(), installed="0.1.0", rec={})
    assert rep["version"] == "0.2.0"   # the lowest live wave above the pin
    st = _steps(rep)
    assert st["wave"] == ("pending", "wave-s2 open (1 item(s))")
    assert st["version"] == ("pending", "no version PR yet")
    assert st["tag"] == ("pending", "v0.2.0 not on owner/engine")
    assert st["pin"][0] == "pending" and st["install"][0] == "pending" and st["verified"][0] == "pending"
    assert rep["next"]["name"] == "wave" and rep["next"]["owner"] == "coordinator"
    assert "brain wave close wave-s2" in rep["next"]["next"]


def test_each_step_moves_as_the_release_goes(tmp_path, net):
    root = _brain(tmp_path)
    (root / "notes" / "graph" / "nodes" / "plan.yaml").write_text(NODES.replace("status: active", "status: reached"),
                                                                 encoding="utf-8")
    vpr = {"number": 7, "title": "Release 0.2.0: two", "state": "OPEN", "headRefName": "chore/release-0.2.0"}
    lot = {"number": 6, "title": "A lot named 0.2.0", "state": "OPEN", "headRefName": "feat/x"}
    rep = rs.status(root, "0.2.0", runner=Fake(prs=[lot, vpr]), installed="0.1.0", rec={})
    assert _steps(rep)["wave"] == ("done", "wave-s2 closed")
    assert rep["next"] == {"name": "version", "state": "pending", "detail": "#7 open: Release 0.2.0: two",
                           "owner": "coordinator", "next": "review and merge #7"}
    net["tags"].append("v0.2.0")
    net["verdict"] = tagsig.UNSIGNED
    rep = rs.status(root, "0.2.0", runner=Fake(), installed="0.1.0", rec={})
    assert _steps(rep)["version"][0] == "done"
    assert rep["next"]["name"] == "tag" and rep["next"]["owner"] == "Ada"   # the owner by their display name
    net["verdict"] = tagsig.VERIFIED
    pin_pr = {"number": 9, "title": "Pin the engine to v0.2.0", "state": "OPEN", "headRefName": "chore/pin"}
    rep = rs.status(root, "0.2.0", runner=Fake(prs=[pin_pr]), installed="0.1.0", rec={})
    assert _steps(rep)["tag"] == ("done", "v0.2.0 signed by ada")
    assert rep["next"]["name"] == "pin" and rep["next"]["next"] == "review and merge #9"
    rep = rs.status(root, "0.2.0", runner=Fake(main_pin="v0.2.0"), installed="0.1.0", rec={})
    assert _steps(rep)["pin"] == ("done", "engine.pin v0.2.0 on the default branch")
    assert rep["next"]["name"] == "install" and rep["next"]["owner"] == "Ada"
    assert rep["next"]["next"].startswith("brain release apply")   # wi-brain-release-apply
    rep = rs.status(root, "0.2.0", runner=Fake(main_pin="v0.2.0"), installed="0.2.0",
                    rec={"version": "0.2.0", "ok": False, "at": "T", "checks": [{"name": "tests", "ok": False}]})
    assert rep["next"]["name"] == "verified" and rep["next"]["detail"] == "failed T: tests"
    rep = rs.status(root, "0.2.0", runner=Fake(main_pin="v0.2.0"), installed="0.2.0",
                    rec={"version": "0.2.0", "ok": True, "at": "T"})
    assert rep["next"] is None and all(s["state"] == "done" for s in rep["steps"])
    assert rs.lines(rep)[-1] == "next     none: the release is out here"


def test_offline_reads_no_network_and_says_unknown(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network read offline")
    monkeypatch.setattr(update, "remote_tags", boom)
    monkeypatch.setattr(tagsig, "verify", boom)
    fake = Fake()
    rep = rs.status(_brain(tmp_path), "0.2.0", offline=True, runner=fake, installed="0.1.0", rec={})
    st = _steps(rep)
    assert st["tag"] == ("unknown", "offline") and st["version"] == ("unknown", "offline")
    assert not any(c[0] == "gh" for c in fake.calls)


def test_a_tool_that_cannot_run_is_unknown_never_a_crash(tmp_path, net, monkeypatch):
    def down(repo, runner=None):
        raise OSError("git ls-remote owner/engine: exit 128")
    monkeypatch.setattr(update, "remote_tags", down)
    rep = rs.status(_brain(tmp_path), "0.2.0", runner=Fake(fail={"gh"}), installed="0.1.0", rec={})
    st = _steps(rep)
    assert st["tag"] == ("unknown", "git ls-remote owner/engine: exit 128")
    assert st["version"][0] == "unknown" and "gh could not run" in st["version"][1]
    assert st["pin"][0] == "unknown"   # no pin PR could be listed: never a « no PR yet »


def test_the_version_defaults_to_the_pin_once_no_wave_is_above_it(tmp_path, net):
    root = _brain(tmp_path, pin="v0.2.0")
    assert rs.status(root, runner=Fake(main_pin="v0.2.0"), installed="0.2.0", rec={})["version"] == "0.2.0"
    (root / "notes" / "graph" / "nodes" / "plan.yaml").write_text("[]\n", encoding="utf-8")
    assert rs.default_version(root / "notes" / "graph", root, "v0.3.1") == "0.3.1"
    with pytest.raises(rs.StatusError):
        rs.default_version(root / "notes" / "graph", root, None)
    with pytest.raises(rs.StatusError):
        rs.bare("next")


def _check_runner(results: dict):
    def run(argv, **kw):
        name = ("tests" if "pytest" in argv and "-c" not in argv else "has-pytest" if "-c" in argv
                else "version" if "--version" in argv else "probes" if "probes" in argv else "classes")
        rc, out = results.get(name, (0, ""))
        if rc is None:
            raise subprocess.TimeoutExpired(argv, 1)
        return subprocess.CompletedProcess(argv, rc, out, "boom\n" if rc else "")
    return run


def test_verify_runs_each_check_logs_it_and_records_the_verdict(tmp_path):
    root = _brain(tmp_path, pin="v0.2.0")
    (root / "tests").mkdir()
    said = []
    rec = rs.verify(root, runner=_check_runner({"version": (0, "brain 0.2.0\n")}), say=said.append)
    assert rec["ok"] is True and [c["name"] for c in rec["checks"]] == ["version", "probes", "classes", "tests"]
    assert rs.last_verify() == rec and rec["v"] == rs.V and rec["pin"] == "v0.2.0"
    log = Path(rec["checks"][0]["log"])
    assert log.parent == rs.record_file().parent and log.read_text(encoding="utf-8").startswith("$ ")
    assert said[0].startswith("version  OK")
    rec = rs.verify(root, runner=_check_runner({"version": (0, "brain 0.1.0\n"), "tests": (1, "1 failed")}),
                    say=said.append)
    assert rec["ok"] is False
    bad = {c["name"]: c["why"] for c in rec["checks"] if not c["ok"]}
    assert bad == {"version": "brain 0.1.0, the pin is v0.2.0", "tests": "exit 1"}
    assert rs.verify_step(rec["version"], rec).state == "pending"


def test_verify_skips_the_tests_without_pytest_or_a_tests_folder_and_survives_a_timeout(tmp_path):
    root = _brain(tmp_path, pin="v0.2.0")
    (root / "tests").mkdir()
    said = []
    rec = rs.verify(root, runner=_check_runner({"has-pytest": (1, ""), "version": (0, "brain 0.2.0"),
                                                "probes": (None, "")}), say=said.append)
    assert [c["name"] for c in rec["checks"]] == ["version", "probes", "classes"]
    assert said[0].startswith("tests    skipped: pytest is not installed")
    probes = next(c for c in rec["checks"] if c["name"] == "probes")
    assert probes["ok"] is False and probes["rc"] is None and "timed out after 180s" in probes["why"]
    assert [n for n, *_ in rs.checks(root, tests=False)] == ["version", "probes", "classes"]
    (root / "tests").rmdir()
    assert [n for n, *_ in rs.checks(root)] == ["version", "probes", "classes"]


def test_a_record_that_cannot_be_read_is_no_verify(tmp_path):
    f = rs.record_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("not json", encoding="utf-8")
    assert rs.last_verify() == {}
    f.write_text("[1]", encoding="utf-8")
    assert rs.last_verify() == {}
    assert rs.verify_step("0.2.0", {}).detail == "not verified on this machine"


def test_the_release_folder_is_an_engine_store(tmp_path):
    assert classes.ENGINE_STORES["release"].format == "derived"


def test_the_cli_runs_status_and_verify(tmp_path, net, monkeypatch, capsys):
    root = _brain(tmp_path, pin="v0.2.0")
    monkeypatch.setattr(rs, "status", lambda root, version="", **kw: {
        "version": version or "0.2.0", "repo": "owner/engine", "root": str(root), "next": None,
        "steps": [{"name": "wave", "state": "done", "detail": "wave-s2 closed", "owner": "", "next": ""}]})
    assert cli.main(["release", "status", "--planning", str(root), "--offline"]) == 0
    assert capsys.readouterr().out.splitlines()[:2] == ["release 0.2.0 (owner/engine)",
                                                         "  wave     done     wave-s2 closed"]
    assert cli.main(["release", "status", "0.2.0", "--planning", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "0.2.0"
    monkeypatch.setattr(rs, "verify", lambda root, tests=True, say=print: {
        "ok": tests, "version": "0.2.0", "pin": "v0.2.0", "checks": []})
    assert cli.main(["release", "verify", "--planning", str(root)]) == 0
    assert cli.main(["release", "verify", "--planning", str(root), "--no-tests"]) == 1
    assert "verify   FAILED" in capsys.readouterr().out
    assert sys.executable   # the checks run with this interpreter: the engine installed


def test_the_version_check_reads_brain_version_against_the_pin():
    assert rs._version_verdict("brain 0.2.0\n", "v0.2.0") == (True, "")
    assert rs._version_verdict("brain 0.2.0\n", None) == (True, "brain 0.2.0, no pin")
    assert rs._version_verdict("brain 0.1.9\n", "v0.2.0") == (False, "brain 0.1.9, the pin is v0.2.0")
    assert rs._version_verdict("", "v0.2.0") == (False, "no version in ''")


def test_a_closed_wave_counts_as_the_release_it_shipped_as(tmp_path, net):
    root = _brain(tmp_path)
    jumped = NODES.replace("status: active, title: \"two\", props: {kind: wave, release: 0.2.0, seq: 2}",
                           "status: reached, title: \"two\", props: {kind: wave, release: 0.2.0, shipped_as: 0.3.0, "
                           "seq: 2}")
    (root / "notes" / "graph" / "nodes" / "plan.yaml").write_text(jumped, encoding="utf-8")
    store = root / "notes" / "graph"
    assert rs.default_version(store, root, "v0.1.0") == "0.3.0"
    assert rs.wave_step(store, root, "0.3.0").state == "done"


def test_a_tag_that_could_not_be_checked_is_unknown_not_the_owners_to_sign(tmp_path, net):
    root = _brain(tmp_path)
    net["tags"].append("v0.2.0")
    net["verdict"] = tagsig.UNVERIFIABLE
    st = _steps(rs.status(root, "0.2.0", runner=Fake(), installed="0.1.0", rec={}))
    assert st["tag"] == ("unknown", "v0.2.0 cut, not verified: no signature")
    net["verdict"] = tagsig.UNKNOWN_KEY
    rep = rs.status(root, "0.2.0", runner=Fake(), installed="0.1.0", rec={})
    assert _steps(rep)["tag"][0] == "pending"


def test_a_pin_that_cannot_be_read_is_unknown(tmp_path, net):
    class NoShow(Fake):
        def __call__(self, argv, **kw):
            if argv[0] == "git" and "show" in argv:
                self.calls.append(argv)
                return subprocess.CompletedProcess(argv, 128, "", "fatal: invalid object name\n")
            return super().__call__(argv, **kw)
    root = _brain(tmp_path)
    st = _steps(rs.status(root, "0.2.0", runner=NoShow(), installed="0.1.0", rec={}))
    assert st["pin"] == ("unknown", "the default branch's pin unknown (git show origin/main:config.json failed)")
    st = _steps(rs.status(root, "0.2.0", runner=Fake(fail={"gh"}), installed="0.1.0", rec={}))
    assert st["pin"][0] == "unknown" and "gh could not run" in st["pin"][1]
    fake = Fake()
    rs.status(root, "0.2.0", offline=True, runner=fake, installed="0.1.0", rec={})
    assert not any("ls-remote" in c for c in fake.calls)   # offline: origin/HEAD read locally, else main


def test_a_record_that_cannot_be_written_removes_the_previous_pass(tmp_path, monkeypatch):
    from brain import stateio
    root = _brain(tmp_path, pin="v0.2.0")
    rs.verify(root, tests=False, runner=_check_runner({"version": (0, "brain 0.2.0")}))
    assert rs.last_verify()["ok"] is True

    def full(path, text):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(stateio, "write_atomic", full)
    said = []
    rec = rs.verify(root, tests=False, runner=_check_runner({"version": (0, "brain 0.1.0")}), say=said.append)
    assert rec["ok"] is False and rs.last_verify() == {}
    assert said[-1] == "record   not written (OSError), the previous one removed"


def test_another_planning_brains_verify_is_not_this_ones(tmp_path):
    rec = {"version": "0.2.0", "ok": True, "at": "T", "root": str(tmp_path / "other")}
    assert rs.verify_step("0.2.0", rec, tmp_path / "planning").state == "pending"
    assert rs.verify_step("0.2.0", rec, tmp_path / "other").state == "done"


def test_the_tag_s_next_move_is_brain_release_tag(tmp_path, net):
    """wi-brain-release-tag-command: the owner's move for a tag not cut yet is the one command."""
    step, cut = rs.tag_step(_brain(tmp_path), "0.2.0", "owner/engine", False, "Ada", Fake())
    assert (step.state, cut, step.owner) == ("pending", False, "Ada")
    assert step.next == "once the version PR is merged: brain release tag v0.2.0 in the engine checkout, your terminal"
