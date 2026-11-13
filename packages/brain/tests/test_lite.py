"""The lite suite (wi-brain-lite-suite; marker ``lite``, ``pytest -m lite``): the core of the brain runs on the Lite
profile with Docker, the network and the other engines hidden, and keeps its guards, records, decision queue,
backlog (sync, check, refresh), journal, ADRs, rule injection, capture and generated views.

The scenario is the stranger test's (installer/stranger_test.py, ``lite_steps``), run here on this checkout's engine
instead of a fresh install: a stranger's environment (a home of their own, a PATH of git, bash, the system and this
Python's scripts: no docker, no gh), no ``BRAIN_GRAPH_PYTHON`` (the graph engine in process), the network hidden (its
proxies pointed at a closed port) and ``brain refresh --offline``. The steps the stranger test does not take follow:
an ADR, the records' check, a sync and a check again, the capture hook, and the generated views on disk.
"""

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "installer" / "stranger_test.py"
CLOSED = "http://127.0.0.1:9"   # the discard port: a call that tries the network fails at once

pytestmark = [pytest.mark.lite, pytest.mark.skipif(not shutil.which("git"), reason="git not available")]


@pytest.fixture(scope="module")
def st():
    spec = importlib.util.spec_from_file_location("stranger_test_lite", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scripts() -> Path:
    """This Python's scripts folder, where the installed ``brain`` launcher is (the CI's pip install -e)."""
    folder = Path(sys.executable).parent
    return folder if (folder / ("brain.exe" if os.name == "nt" else "brain")).is_file() else Path()


def lite_env(st, work: Path, scripts: Path) -> dict:
    """The stranger's environment, the network hidden, this checkout's source first when PYTHONPATH names it."""
    env = st.isolated_env(work, scripts)
    env.update({"HTTP_PROXY": CLOSED, "HTTPS_PROXY": CLOSED, "ALL_PROXY": CLOSED, "NO_PROXY": "",
                "http_proxy": CLOSED, "https_proxy": CLOSED, "BRAIN_GRAPH_PYTHON": ""})
    if os.environ.get("PYTHONPATH"):
        env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    return env


def more_steps(st, root: Path, scripts: Path) -> list[tuple]:
    """What the core keeps beyond the stranger's scenario: an ADR, the records, sync and check, the capture hook."""
    brain = st._exe(scripts, "brain")
    plugin = root / "plugins" / "brain-core"
    start = json.dumps({"session_id": "lite", "hook_event_name": "SessionStart", "source": "startup",
                        "cwd": str(root)})
    return [
        ("adr", [brain, "adr", "new", "Keep the lite profile", "--context", "A first machine with no Docker.",
                 "--decision", "The brain runs on the Lite profile.", "--why", "Nothing else is installed yet.",
                 "--revisit", "When a service is added."], None, None),
        ("record check", [brain, "record", "check"], None, None),
        ("sync", [brain, "sync", "--offline", "--force"], None, None),
        ("check again", [brain, "check"], None, lambda o: "graph-check OK" in o),
        ("hook capture", [st.git_bash(), str(plugin / "hooks" / "capture.sh"), "session-start"], start, None),
    ]


@pytest.fixture(scope="module")
def ran(st, tmp_path_factory):
    """The scenario run once for the module: (its steps, the brain's root, the environment)."""
    scripts = _scripts()
    if scripts == Path():
        pytest.skip("no brain launcher beside this Python (pip install -e packages/brain)")
    work = tmp_path_factory.mktemp("lite")
    env = lite_env(st, work, scripts)
    root = work / "ada-brain"
    root.mkdir()
    steps = [(n, c[:2] + ["--offline", *c[2:]] if n == "refresh" else c, i, ok, *rest)
             for n, c, i, ok, *rest in st.lite_steps(root, scripts, dev=True)]
    hooks = st.hook_env_of(env, root, scripts)
    return st.run_steps(steps + more_steps(st, root, scripts), env, root, hooks), root, env


def _failed(results: list[dict]) -> str:
    return "\n\n".join(f"{r['step']}: rc {r['rc']}: {r['cmd']}\n{r['out'][-1500:]}" for r in results if not r["ok"])


def test_the_core_runs_its_lite_scenario_with_nothing_else(ran):
    results, root, env = ran
    assert [r["step"] for r in results if not r["ok"]] == [], _failed(results)
    names = {r["step"] for r in results}
    for step in ("check", "item", "decision", "journal", "refresh", "queue", "hook rules", "hook guard", "adr",
                 "record check", "sync", "hook capture"):
        assert step in names


def test_nothing_reached_for_docker_gh_or_the_network(ran):
    results, root, env = ran
    path = env["PATH"].split(os.pathsep)
    assert not any(Path(p, n).is_file() for p in path for n in ("docker", "docker.exe", "gh", "gh.exe"))
    assert env["BRAIN_GRAPH_PYTHON"] == "" and env["HTTPS_PROXY"] == CLOSED
    out = "\n".join(r["out"] for r in results)
    assert "Traceback" not in out


def test_the_records_the_logs_and_the_generated_views_are_written(ran):
    results, root, env = ran
    journal = (root / "notes" / "journal.md").read_text(encoding="utf-8")
    decisions = (root / "notes" / "decisions.md").read_text(encoding="utf-8")
    assert "First day" in journal and "Keep the lite profile" in decisions
    nodes = (root / "notes" / "graph" / "nodes" / "work.yaml").read_text(encoding="utf-8")
    assert "wi-first" in nodes
    for view in ("notes/kanban_graph.md", "notes/decision_queue.md"):
        assert "GENERATED by" in "".join((root / view).read_text(encoding="utf-8").splitlines(True)[:5]), view
    assert any((root / "records").rglob("*.yaml")) or any((root / "records").rglob("*.jsonl"))   # the decision's DDR
    home = Path(env["BRAIN_HOME"])
    assert home.is_dir() and any(home.rglob("*.jsonl")), "the capture hook wrote nothing to the ledger"
