"""wi-brain-hook-latency: the hooks start no process they do not need. The launchers find Python and read their JSON
without a fork, a guard does not import urllib.request, the registry is read through libyaml; git that only reads is
left to bash (tests/test_guards.py: the pre-filter against the guards' tables)."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from test_capture import PLUGIN, _bash

import brain
from brain import graph, paths, projects

HOOKS = PLUGIN / "hooks"


def _sh(script: str, **env) -> subprocess.CompletedProcess:
    bash = _bash()
    if not bash:
        pytest.skip("no bash")
    return subprocess.run([bash, "-c", f'source "{(HOOKS / "common.sh").as_posix()}"; {script}'], capture_output=True,
                          text=True, timeout=60, env=dict(os.environ, **env))


def test_brain_python_finds_a_path_or_a_name_without_a_fork(tmp_path):
    out = _sh('brain_python "" "$NOPE" "$PY" && echo "$brain_py"', NOPE=str(tmp_path / "none.exe"), PY=sys.executable)
    assert out.stdout.strip() == sys.executable
    name = Path(sys.executable).stem   # python: looked up in PATH by hash
    out = _sh(f'brain_python "$NOPE" {name} && echo "$brain_py"', NOPE=str(tmp_path / "none.exe"),
              PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    assert out.returncode == 0 and Path(out.stdout.strip()).stem.lower() == name.lower()
    assert _sh('brain_python "$NOPE" no-such-python-x; echo "rc=$?"', NOPE=str(tmp_path / "x")).stdout.strip() == \
        "rc=1"


def test_brain_python_skips_the_store_stubs(tmp_path):
    stub = tmp_path / "WindowsApps" / "python3.exe"
    stub.parent.mkdir()
    stub.write_bytes(b"MZ")
    stub.chmod(0o755)
    out = _sh('brain_python "$STUB" "$PY" && echo "$brain_py"', STUB=str(stub), PY=sys.executable)
    assert out.stdout.strip() == sys.executable


def test_the_launchers_do_not_fork_before_python():
    """No $(cat), no $(command -v), no printf | python, no $(cd ...) for the plugin root when Claude Code gives it."""
    for sh in HOOKS.glob("*.sh"):
        if sh.name in ("common.sh", "inject-rules.sh"):   # inject-rules runs once per session, with tr, sed and awk
            continue
        code = "\n".join(line for line in sh.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))
        code = re.sub(r"#.*", "", code)
        for fork in ("$(cat)", "command -v", "| BRAIN_HOOK_T0", '| "$', "$(cd "):
            assert fork not in code, (sh.name, fork)
        if "brain_py" in code:
            assert re.search(r'^brain_python [^\n]*&& BRAIN_HOOK_T0=\$brain_t0 "\$brain_py" -X utf8 -I ', code, re.M), \
                sh.name


def test_no_hook_imports_urllib_request():
    """paths.installed_checkout (asked by every config read) reads a file: URL with urllib.parse: urllib.request cost
    a hook ~50 ms."""
    code = ("import sys, brain.guards, brain.paths as p; p.bases(); p.installed_checkout(); "
            "print('urllib.request' in sys.modules)")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60,
                         env=dict(os.environ, PYTHONPATH=str(Path(brain.__file__).parents[1])))
    assert out.stdout.strip() == "False", out.stderr


@pytest.mark.parametrize("path", ["brain-clone", "a dir/with %25 percent", "é-accents"])
def test_a_file_url_reads_back_as_its_path(tmp_path, path):
    p = tmp_path / path
    assert paths.file_url_path(p.as_uri()) == p


def test_a_unc_file_url(tmp_path):
    assert paths.file_url_path("file://server/share/brain") == Path("//server/share/brain")


def test_the_registry_is_read_through_libyaml(tmp_path, monkeypatch):
    reg = tmp_path / "projects.yaml"
    reg.write_text("demo: {root: ., production: [.], title: 'é « x »', when: 2026-11-03}\nother: {root: ../o}\n",
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    assert projects.raw() == yaml.safe_load(reg.read_text(encoding="utf-8"))
    seen = []
    real = yaml.load

    def spy(text, Loader):
        seen.append(Loader)
        return real(text, Loader=Loader)

    monkeypatch.setattr(yaml, "load", spy)
    projects.raw()
    assert seen == [getattr(yaml, "CSafeLoader", yaml.SafeLoader)]
    assert graph.load_yaml("a: [1, 2]") == {"a": [1, 2]}


# wi-brain-read-hint-matcher: Claude Code starts the read hint only when the call's path or command names a brain's
# file (the hooks' if conditions), so a call that names none starts no bash at all. Before: every Read, Grep, Bash and
# PowerShell call started bash (on the owner's machine, 4,854 of 4,981 runs in a week stopped at its fast path, each
# a bash start of ~85 ms); after: only Grep (its path is a folder or a glob, which a permission rule cannot match) and
# the calls whose path or command names one.

def _rule(pattern: str, shell: bool) -> re.Pattern:
    """A permission rule's specifier as Claude Code matches it: a file path (gitignore style, ``//`` absolute, ``**/``
    any folders, ``*`` within one) or a shell command (``*`` anything)."""
    if shell:
        return re.compile("^" + ".*".join(map(re.escape, pattern.split("*"))) + "$", re.S)
    body = re.escape(pattern.removeprefix("/")).replace(r"\*\*/", "(?:.*/)?").replace(r"\*", "[^/]*")
    return re.compile("^" + body + "$")


def _readhint_hooks() -> dict[str, list[dict]]:
    engine = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    for g in engine["hooks"]["PreToolUse"]:
        out.setdefault(g["matcher"], []).extend(h for h in g["hooks"] if "readhint.sh" in h["command"])
    return {m: hs for m, hs in out.items() if hs}


def _starts(hooks: list[dict], tool: str, value: str) -> bool:
    for h in hooks:
        if "if" not in h:
            return True
        m = re.fullmatch(rf"{tool}\((.*)\)", h["if"])
        assert m, h["if"]
        if _rule(m.group(1), tool != "Read").match(value):
            return True
    return False


READS = ["/e/b/notes/graph/nodes/work.yaml", "/e/b/notes/graph/edges/work.yml", "/e/b/notes/decisions.md",
         "/e/b/notes/scientific_decisions.md", "/e/b/notes/journal.md", "/e/b/notes/kanban_graph.md",
         "/e/b/notes/roadmap_graph.md", "/e/b/notes/plan_graph.md", "/e/b/notes/decision_queue.md", "/e/b/FEATURES.md"]
SHELLS = ["grep -n wi-x notes/graph/nodes/work.yaml", "cat notes/decisions.md", "Get-Content notes\\journal.md",
          "head -40 notes/kanban_graph.md", "sls x FEATURES.md", "type notes\\decision_queue.md",
          "rg wi-x notes/graph/edges/work.yaml"]


def test_the_read_hint_starts_only_on_a_likely_hit():
    from brain import readhint
    hooks = _readhint_hooks()
    assert set(hooks) == {"Read", "Grep", "Bash", "PowerShell"}
    assert all("if" in h for t in ("Read", "Bash", "PowerShell") for h in hooks[t])
    assert [h.get("if") for h in hooks["Grep"]] == [None]   # a folder or a glob: the bash fast path filters it
    assert {readhint.kind_of(p) for p in READS} == {k for _, k in readhint.KINDS}   # every kind of brain file
    for p in READS:   # every file the hint names starts it
        assert _starts(hooks["Read"], "Read", p), p
    for c in SHELLS:
        assert _starts(hooks["Bash"], "Bash", c) and _starts(hooks["PowerShell"], "PowerShell", c), c
    for p in ("/e/b/src/app.py", "/e/b/notes/README.md", "/e/b/notes/graph/schema.yaml", "/e/b/nodes.yaml"):
        assert not _starts(hooks["Read"], "Read", p), p   # a call that names none starts no process
    for c in ("git status", "python -m pytest -q", "gh pr view 12"):
        assert not _starts(hooks["Bash"], "Bash", c), c


def test_what_the_if_conditions_let_through_the_bash_fast_path_still_filters():
    """The if conditions only narrow: each sample they let through still reaches readhint.sh's own filter, so a hit
    the bash fast path saw before, it sees now (the Python hint decides as before)."""
    text = (HOOKS / "readhint.sh").read_text(encoding="utf-8")
    fast = re.search(r"brain_files='([^']+)'", text).group(1)
    for value in READS + SHELLS:
        assert re.search(fast, json.dumps(value)), value
