"""Negative controls for the stranger test's harness (wi-brain-harness-negative-controls): a harness that cannot fail
proves nothing. Each fault the upgrade test guards against is injected (stranger_test.py --fault) and the verdict must
be a no-go, failing at the step meant to catch it and at no other; the same run without a fault must be a go, or the
no-goes would prove nothing either. The skeptic review of brain #52 found seven false greens in this harness.

The fast tests here run in the default suite (the seams on a brain built by hand, the missing tag). The reruns
install the engine several times each (the last tag from GitHub, this checkout, then back): about 10 minutes each,
skipped unless selected with ``-m harness``; CI's ``harness-controls`` job runs them on a pull request that touches
the harness (docs/formats.md, « Negative controls »):

    pytest packages/brain/tests/test_harness_negative_controls.py -m harness -n 3
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "installer" / "stranger_test.py"
REPO = Path(__file__).resolve().parents[3]
FAULTS = ["rewrite", "truncated-ledger", "unreached", "wrong-engine"]      # each one rerun below


@pytest.fixture(scope="module")
def st():
    spec = importlib.util.spec_from_file_location("stranger_test_controls", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def harness(*args: str, timeout: float = 120, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, cwd=REPO, env=env)


# --- fast: in the default suite --------------------------------------------------------------------------------------

def test_no_tag_is_a_no_go_not_the_plain_test(tmp_path):
    """compat-prev with no tag found passes an empty --upgrade-from: the harness refuses it before any install (it
    used to run the plain stranger test instead, green, testing nothing of the upgrade)."""
    r = harness("--source", str(REPO), "--upgrade-from", "", "--work", str(tmp_path))
    assert r.returncode != 0 and "--upgrade-from: empty" in r.stderr
    assert not (tmp_path / "venv").exists() and not (tmp_path / "report.json").exists()


def test_a_fault_belongs_to_the_upgrade_test(tmp_path):
    r = harness("--source", str(REPO), "--fault", "rewrite", "--work", str(tmp_path))
    assert r.returncode == 2 and "with --upgrade-from" in r.stderr and not (tmp_path / "venv").exists()
    r = harness("--source", str(REPO), "--upgrade-from", "v0.0.0", "--fault", "nothing", "--work", str(tmp_path))
    assert r.returncode == 2 and "invalid choice" in r.stderr


def _brain(st, tmp_path):
    root, home = tmp_path / "brain", tmp_path / "home"
    root.mkdir()
    (root / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada Example"}}, indent=2) + "\n",
                                      encoding="utf-8")
    ledger = home / ".brain" / "ledger" / "engine"
    ledger.mkdir(parents=True)
    (ledger / "exec-2026-11.jsonl").write_text('{"v":1,"kind":"exec"}\n{"v":1,"kind":"exec","cpu_s":0.1}\n',
                                               encoding="utf-8")
    return root, home, ledger / "exec-2026-11.jsonl"


@pytest.mark.parametrize("fault, changed", [("rewrite", "config.json"), ("truncated-ledger", "exec-2026-11.jsonl")])
def test_the_no_loss_check_catches_each_injected_loss(st, tmp_path, fault, changed):
    root, home, ledger = _brain(st, tmp_path)
    before = st.snapshot([root, home / ".brain" / "ledger"])
    with ledger.open("a", encoding="utf-8") as fh:      # the older engine's reads append their events after it
        fh.write('{"v":1,"kind":"exec","task":"check"}\n')
    assert st.lost(before) == []
    step = st.inject(fault, root, home)
    assert step["ok"], step
    gone = st.lost(before)
    assert len(gone) == 1 and gone[0].startswith("changed: ") and gone[0].endswith("/" + changed), gone
    assert st.FAULTS[fault] == "no loss"


def test_a_fault_with_no_file_to_put_it_on_is_its_own_failure(st, tmp_path):
    """A fault that bit nothing must not pass for a caught one: its step fails, so the rerun sees an unexpected step."""
    step = st.inject("truncated-ledger", tmp_path / "brain", tmp_path / "home")
    assert not step["ok"] and "no file" in step["cmd"]


def test_an_unreached_format_fails_the_newer_data_step(st, tmp_path):
    root, home = tmp_path / "brain", tmp_path / "home"
    root.mkdir()
    (root / "members.yaml").write_text(st.fixture(st.UNREACHED, "older").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    assert "members: members.yaml +keys" in st.add_newer(root, home)["out"]
    (root / "members.yaml").write_text(st.fixture(st.UNREACHED, "older").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    step = st.add_newer(root, home, "unreached")
    assert not step["ok"] and "members: members.yaml unchanged" in step["out"]
    assert f"{st.UNREACHED} v1" in step["out"].split("reached no file: ")[1]
    assert st.FAULTS["unreached"] == "newer data"


def test_the_wrong_engine_goes_back_only_under_its_fault(st, tmp_path):
    prev, head = ("v0.3.1", ""), ("", str(REPO), False)
    assert st.back_to("wrong-engine", prev, head) == ("v0.3.1", "", False)
    assert all(st.back_to(f, prev, head) == head for f in ("", "rewrite", "unreached"))
    assert st.injected("", tmp_path, tmp_path) == st.injected("wrong-engine", tmp_path, tmp_path) == []


def test_every_fault_has_its_rerun(st):
    assert set(st.FAULTS) == set(FAULTS)


# --- slow: the reruns, -m harness ------------------------------------------------------------------------------------


@pytest.fixture
def selected(request):
    expr = request.config.getoption("markexpr") or ""
    if "harness" not in expr or "not harness" in expr:
        pytest.skip("installs the engine several times: run with -m harness")


def last_tag() -> str:
    r = subprocess.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD"], capture_output=True,
                       text=True, cwd=REPO, timeout=60)
    tag = r.stdout.strip()
    if r.returncode or not tag:
        pytest.fail("no tag before HEAD: fetch the tags (git fetch --tags), the upgrade test needs one")
    return tag


def rerun(*args: str, source: bool = True) -> tuple[int, dict, str]:
    """The harness run in a new short folder (pip's paths in the venv stay under Windows' limit), on a copy of this
    checkout of its own: pip builds a checkout in place, so two runs at once on the same one break each other."""
    work = Path(tempfile.mkdtemp(prefix="nc-"))
    try:
        copy = work / "src" / REPO.name                  # the same folder name: the harness's engine check reads it
        if source:
            shutil.copytree(REPO, copy, ignore=shutil.ignore_patterns(".git", "build", "*.egg-info", "__pycache__",
                                                                      ".venv", ".pytest_cache", ".ruff_cache"))
        # a pip cache of its own: runs at once sharing a warm one have failed to resolve setuptools (twice, locally)
        env = dict(os.environ, PIP_CACHE_DIR=str(work / "pip-cache"))
        r = harness(*(["--source", str(copy)] if source else []), *args, "--work", str(work / "run"), timeout=3600,
                    env=env)
        report = json.loads((work / "run" / "report.json").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return r.returncode, report, r.stdout[-6000:] + r.stderr[-2000:]


@pytest.mark.harness
@pytest.mark.parametrize("fault", ["none", *FAULTS])
def test_the_upgrade_test_fails_at_the_step_that_guards_against_each_fault(selected, st, fault):
    rc, report, out = rerun("--upgrade-from", last_tag(), *(["--fault", fault] if fault != "none" else []))
    failed = {s["step"] for s in report["steps"] if not s["ok"]}
    if fault == "none":
        assert (rc, report["verdict"], failed) == (0, "go", set()), out
    else:
        assert (rc, report["verdict"], report.get("fault")) == (1, "no-go", fault), out
        assert failed == {st.FAULTS[fault]}, out


@pytest.mark.harness
def test_the_plain_stranger_test_fails_on_a_leak(selected):
    """The plain run's negative control: the invented owner's name denied, as the author's would be. The leak alone
    must be found (every step ok); docker on the PATH, also a no-go, is not what this proves. The last tag is
    installed, as the pilot's go does: a checkout is no pin, so its brain refresh refuses (a dry run, not the go)."""
    rc, report, out = rerun("--ref", last_tag(), "--deny", "people:Ada Example", source=False)
    assert rc == 1 and report["verdict"] == "no-go", out
    assert all(s["ok"] for s in report["steps"]), out
    assert {lk["term"] for lk in report["leaks"]} == {"Ada Example"} and len(report["leaks"]) > 3, out
