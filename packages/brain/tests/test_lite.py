"""The lite suite (wi-brain-lite-suite; marker ``lite``, ``pytest -m lite``): the core of the brain runs on the Lite
profile with Docker, gh, the network and the other engines out of reach, and keeps its guards, records, decision
queue, backlog (sync, check, refresh), journal, ADRs, rule injection, capture and generated views.

The scenario is the stranger test's (installer/stranger_test.py, ``lite_steps``), run here on this checkout's engine
instead of a fresh install (the fixture checks that the launcher imports this checkout's ``brain`` and
``research_graph``): a stranger's environment (a home of their own, a PATH of git, bash, the system and this Python's
scripts), from which ``docker``, ``podman`` and ``gh`` are taken out and replaced by shims that leave a mark when
anything calls them; the proxies pointed at a local listener that counts the connections; no ``BRAIN_GRAPH_PYTHON``
(the graph engine in process) and ``brain refresh --offline``. The steps the stranger test does not take follow: an
ADR, the records' check, a sync and a check again, the capture hook. Then what each step wrote is read back: the
journal, the decision log, the item, the DDR, the views regenerated with the item and the question, the links sync
derived, the capture hook's session event, and no mark and no connection.

One test, the whole scenario (about half a minute): under ``-n auto`` no worker runs it twice. It fails, never skips,
in the CI when the ``brain`` launcher is missing.
"""

import importlib.util
import json
import os
import shutil
import socket
import sys
import sysconfig
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "installer" / "stranger_test.py"
CHECKOUT = Path(__file__).resolve().parents[3]   # the repo: src/research_graph, packages/brain/src/brain
HIDDEN = ("docker", "podman", "gh")

pytestmark = [pytest.mark.lite, pytest.mark.skipif(not shutil.which("git"), reason="git not available")]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scripts() -> Path:
    """This interpreter's scripts folder, where pip put the ``brain`` launcher (a venv's, or setup-python's own)."""
    for folder in (Path(sysconfig.get_path("scripts")), Path(sys.executable).parent):
        if (folder / ("brain.exe" if os.name == "nt" else "brain")).is_file():
            return folder
    return Path()


class Listener:
    """A local TCP listener that counts the connections made to it: the proxies point here."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.count = 0
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.sock.getsockname()[1]}"

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.count += 1
            conn.close()

    def close(self):
        self.sock.close()


def _shims(folder: Path, marks: Path) -> None:
    """``docker``, ``podman`` and ``gh`` that leave a mark and fail: what calls them is seen."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in HIDDEN:
        if os.name == "nt":
            (folder / f"{name}.cmd").write_text(f"@echo off\r\necho {name}>>\"{marks}\"\r\nexit /b 1\r\n",
                                                encoding="utf-8")
        else:
            f = folder / name
            f.write_text(f"#!/bin/sh\necho {name} >> '{marks}'\nexit 1\n", encoding="utf-8")
            f.chmod(0o755)


def _system_bin(folder: Path, sources: list[str]) -> None:
    """A copy of the system folders by links, without the programs the suite hides (a runner keeps docker and gh in
    /usr/bin)."""
    folder.mkdir(parents=True, exist_ok=True)
    for src in sources:
        for entry in sorted(Path(src).iterdir()) if Path(src).is_dir() else []:
            if entry.name in HIDDEN or (folder / entry.name).exists():
                continue
            try:
                (folder / entry.name).symlink_to(entry)
            except OSError:
                continue


def lite_env(st, work: Path, scripts: Path, proxy: str) -> dict:
    """The stranger's environment, the hidden programs shimmed, the network to ``proxy``, this checkout first."""
    env = st.isolated_env(work, scripts)
    path = env["PATH"].split(os.pathsep)
    if os.name != "nt":   # /usr/bin and /bin replaced by links to them without docker, podman and gh
        system = [p for p in path if p in ("/usr/bin", "/bin")]
        _system_bin(work / "sysbin", system)
        path = [p for p in path if p not in system] + [str(work / "sysbin")]
    _shims(work / "shims", work / "marks.txt")
    env["PATH"] = os.pathsep.join([str(work / "shims"), *path])
    env.update({"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy, "ALL_PROXY": proxy, "NO_PROXY": "", "http_proxy": proxy,
                "https_proxy": proxy, "BRAIN_GRAPH_PYTHON": ""})
    env["PYTHONPATH"] = os.pathsep.join([str(CHECKOUT / "packages" / "brain" / "src"), str(CHECKOUT / "src")])
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
                 "--revisit", "When a service is added."], None, lambda o: "adr-" in o),
        ("record check", [brain, "record", "check"], None, lambda o: "1 DDR" in o and "0 error(s)" in o),
        ("sync", [brain, "sync", "--offline", "--force"], None, None),
        ("check again", [brain, "check"], None, lambda o: "graph-check OK" in o),
        ("hook capture", [st.git_bash(), str(plugin / "hooks" / "capture.sh"), "session-start"], start, None),
    ]


def _failed(results: list[dict]) -> str:
    return "\n\n".join(f"{r['step']}: rc {r['rc']}: {r['cmd']}\n{r['out'][-1500:]}" for r in results if not r["ok"])


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def test_the_core_runs_its_lite_scenario_with_nothing_else(tmp_path):
    st = _load("stranger_test_lite")
    scripts = _scripts()
    if scripts == Path():
        if os.environ.get("CI"):
            pytest.fail("no brain launcher beside this Python: the CI must run the lite suite (pip install -e)")
        pytest.skip("no brain launcher beside this Python (pip install -e packages/brain)")
    listener = Listener()
    try:
        env = lite_env(st, tmp_path, scripts, listener.url)
        root = tmp_path / "ada-brain"
        root.mkdir()
        hooks = {**st.hook_env_of(env, root, scripts), "BRAIN_PYTHON": sys.executable}
        probe = [("engine", [sys.executable, "-c", "import brain, research_graph; print(brain.__file__); "
                             "print(research_graph.__file__)"], None, None)]
        steps = [(n, c[:2] + ["--offline", *c[2:]] if n == "refresh" else c, i, ok, *rest)
                 for n, c, i, ok, *rest in st.lite_steps(root, scripts, dev=True)]
        results = st.run_steps(probe + steps + more_steps(st, root, scripts), env, root, hooks)
    finally:
        listener.close()
    assert [r["step"] for r in results if not r["ok"]] == [], _failed(results)

    # this checkout's engine, not an installed release nor another checkout
    for line in results[0]["out"].split():
        assert Path(line).resolve().is_relative_to(CHECKOUT.resolve()), line
    # nothing called docker, podman or gh, and nothing went to the network
    assert not (tmp_path / "marks.txt").exists(), (tmp_path / "marks.txt").read_text(encoding="utf-8")
    assert listener.count == 0
    # the backlog, the logs and the records
    assert "First day" in _read(root, "notes/journal.md")
    assert "Keep the lite profile" in _read(root, "notes/decisions.md")
    assert "wi-first" in _read(root, "notes/graph/nodes/work.yaml")
    assert list((root / "records").rglob("ddr-*")), "the decision's DDR"
    # the generated views, regenerated with what the scenario added
    assert "wi-first" in _read(root, "notes/kanban_graph.md")
    assert "Pick a name" in _read(root, "notes/decision_queue.md")
    generated = list((root / "notes" / "graph" / "nodes").glob("_generated_*.yaml"))
    assert generated and all(f.stat().st_size for f in generated), "sync derived no node"
    # the rules injected, the guard's refusal, the capture hook's event
    out = {r["step"]: r["out"] for r in results}
    assert "Ada Example's rules" in out["hook rules"] and '"deny"' in out["hook guard"]
    events = [json.loads(x) for f in (Path(env["BRAIN_HOME"]) / "ledger").glob("events-*.jsonl")
              for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(e.get("event") == "session_start" and e.get("session_id") == "lite" for e in events), events


def test_the_shims_mark_a_call_and_the_listener_counts_one(tmp_path):
    """The two nets the scenario relies on catch what they claim: a docker call leaves a mark, a proxied request a
    connection (a net that never fires would let the scenario pass vacuously)."""
    import subprocess
    import urllib.request
    _shims(tmp_path / "shims", tmp_path / "marks.txt")
    docker = shutil.which("docker", path=str(tmp_path / "shims"))
    assert docker and subprocess.run([docker, "ps"], capture_output=True, timeout=30).returncode == 1
    assert "docker" in (tmp_path / "marks.txt").read_text(encoding="utf-8")
    listener = Listener()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": listener.url}))
        with pytest.raises(OSError):
            opener.open("http://example.invalid/", timeout=5)
    finally:
        listener.close()
    assert listener.count == 1
