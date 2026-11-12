"""The stranger test (wi-brain-stranger-install-test): install the brain from the public repo into a fresh venv, as
someone who has never seen its author's machine would, then run the Lite scenario; its verdict is a pilot's go.

    python stranger_test.py [--ref v0.4.0 | --source DIR] [--pre-tag] [--deny people:NAME ...] [--work DIR] [--keep]
                            [--json] [--upgrade-from TAG|DIR [--fault NAME]]

Standard library only, on Windows, Linux or macOS (a container: ``docker run --rm -v <this folder>:/t:ro python:3.12
python /t/stranger_test.py``; Docker is the harness there, never something the brain needs):

- **Isolated.** A new folder with its own home (HOME, USERPROFILE), BRAIN_HOME, Claude config folder and git config;
  no BRAIN_* or CLAUDE_BRAIN_DIR variable of the caller's; a PATH reduced to the venv, git, bash and the system folder,
  so no ``docker`` is reachable. The only network is pip's: the package index, and GitHub for the source.
- **Installed as the docs say.** ``pip install "brain @ git+https://github.com/RoJLD/brain.git@REF#subdirectory=
  packages/brain"``, which brings research-graph at the tag it pins. ``--pre-tag`` (a branch before its tag exists):
  research-graph from the same ref first, then brain with ``--no-deps`` and its plain dependencies. ``--source DIR``
  installs a local checkout instead (a dry run of the harness, not the go).
- **The Lite scenario**, as an invented owner (Ada Example): brain init (plan, then apply), git init and the first
  commit, brain check, brain profile, an item, a decision, a journal line, brain refresh --on-main, brain status,
  brain queue, the cockpit's first screen (brain tui --once), brain boundary --check, a help text (the owner's name,
  never the author's), and the hooks the local marketplace ships: the rules injected at SessionStart and the guard
  refusing ``gh repo create --public``.
- **Checked.** Every step exits 0 (the guard's refusal is its expected output); the queue and the rules carry the
  owner's name; no traceback; and no term of ``--deny`` (``category:term``, e.g. the author's name: they are read
  from the caller's arguments, never written in this file) in any output or in the brain's files.

**The upgrade test** (``--upgrade-from TAG|DIR``, wi-brain-upgrade-test; spec-brain-data-compat N8, COMPAT-2 and
COMPAT-3; CI's ``compat-prev`` job on every pull request, from the last tag), in one venv and one brain:

1. **The previous engine writes.** TAG (or a checkout of it) is installed; brain init and the first commit; then
   every registered format (a ``tests/fixtures/formats/<format>/v<N>/`` folder) is written: a decision (DDR), an AR
   by hand, an SR from the transcript fixture, the older ``permissions.yaml`` and ``members.yaml`` (no command
   writes them), the engine's own exec events; a format with no place in :func:`where` fails the step. Then its
   brain check.
2. **The upgrade.** ``--ref`` or ``--source`` is installed over it, as an upgrade does; ``engine.pin`` is moved and
   committed if the version changed (docs/install.md); then, strict (``BRAIN_STRICT=1``: N reads N-1's data with no
   note), the store plan (``brain init`` on the existing brain), brain sync (the plugin rendered again, the documented
   step after an upgrade), brain check, brain record check and the rest of the Lite scenario (``refresh --force`` for
   a checkout or a branch, which no pin names), and a recovery key declared.
3. **The rollback.** HEAD's additive fixtures (each ``newer`` file's keys that its ``older`` one lacks, JSONL lines
   under the same ``v`` and of a known kind) are laid over the brain's files (a format they reach no file of fails
   the step), and a canary and a drill are put on record: their entries, field for field, saved by HEAD's vault (no
   age here, so no real seal or drill). TAG is installed back over HEAD (as ``install.ps1 -Apply`` does until the pin
   PR merges) and runs, in read mode (``BRAIN_STRICT=0``), brain check, brain record check, brain permissions check,
   brain vault status (which must show the drill), brain perf (the ledger's events) and a newer template's init plan.
   A TAG with the read mode must pass them, its brain check exiting 0, or 1 when its one failure is the plugin
   HEAD's sync rendered (files under ``plugins/``, whose hooks carry the engine's version: not redone, the rollback
   writes nothing); one before it (0.2.5) may only refuse HEAD's newer keys (exit 1 or 2,
   every ``error:`` line an unknown key or field, no traceback, no usage error). No file of the brain and of
   ``$BRAIN_HOME/vault`` is changed or removed, and the ledger's files only grow (sha-256 before and after).
4. **And back.** HEAD is installed again and makes the same reads in read mode, all exiting 0, with the drill shown;
   still nothing lost over the round trip.

After each install, brain's ``direct_url.json`` must name the engine meant (the tag, or the checkout): two engines
can share a version. ``--upgrade-from`` refuses an empty value and the ``--source`` checkout itself. Docker on the
reduced PATH is only reported here (the pilot's isolation, not the upgrade's; GitHub's Windows runners have it). The
upgrade test
reads PyYAML in the harness's own Python (CI installs it) and the fixtures from the checkout it runs from.

**Negative controls** (``--fault NAME``, with ``--upgrade-from``; wi-brain-harness-negative-controls): one fault
injected into the upgrade test, whose verdict must then be a no-go, failing at the step that guards against it
(tests/test_harness_negative_controls.py reruns each, ``pytest -m harness``). ``rewrite``: config.json rewritten
after the older engine's reads (the same data, other bytes), as an older engine that saves what it reads would;
``truncated-ledger``: an exec ledger's first line dropped there; ``unreached``: the members format's newer fixture
replaced by its older one, so its additive keys reach no file; ``wrong-engine``: the previous engine reinstalled in
place of HEAD for the way back. The missing tag needs no seam: ``--upgrade-from ""`` is refused.

Exit code 0 on a go, 1 when a check fails (an upgrade's or rollback's install included), 2 when the first install
fails. ``--json`` prints the report; it is also
written to ``<work>/report.json``.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO = "https://github.com/RoJLD/brain.git"
OWNER = "Ada Example"
EMAIL = "ada@example.invalid"
PLAIN_DEPS = ["pyyaml>=6", "tomli>=2; python_version < '3.11'"]


def run(cmd: list[str], env: dict, cwd: Path, stdin: str | None = None, timeout: float = 600) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{cmd[0]}: {exc}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def git_bash() -> str:
    """The bash that runs the hooks, as Claude Code's: on Windows, Git for Windows' (a bare ``bash`` there starts
    WSL's System32 bash.exe, found before the PATH), else the PATH's."""
    if os.name != "nt":
        return shutil.which("bash") or "bash"
    git = shutil.which("git")
    candidates = [Path(git).parent.parent / "bin" / "bash.exe"] if git else []
    candidates += [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"]
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        candidates.insert(0, Path(found))
    return next((str(c) for c in candidates if c.is_file()), "bash")


def isolated_env(work: Path, scripts: Path) -> dict:
    """The environment of a stranger: a home of its own, nothing of the caller's brain, no docker on the PATH."""
    home = work / "home"
    home.mkdir(parents=True, exist_ok=True)
    gitconfig = home / ".gitconfig"
    gitconfig.write_text(f"[user]\n\tname = {OWNER}\n\temail = {EMAIL}\n[init]\n\tdefaultBranch = main\n"
                         "[commit]\n\tgpgsign = false\n[core]\n\tautocrlf = false\n", encoding="utf-8")
    keep = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL", "TZ",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    folders = [str(scripts)]
    for found in (shutil.which("git"), git_bash()):
        if found:
            folders.append(str(Path(found).parent))
    if os.name == "nt":
        folders.append(os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32"))
    else:
        folders += ["/usr/bin", "/bin"]
    env.update({"HOME": str(home), "USERPROFILE": str(home), "BRAIN_HOME": str(home / ".brain"),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"), "GIT_CONFIG_GLOBAL": str(gitconfig),
                "GIT_CONFIG_NOSYSTEM": "1", "BRAIN_NOTIFY": "off", "PYTHONUTF8": "1",
                "PATH": os.pathsep.join(dict.fromkeys(folders))})
    return env


def install(work: Path, ref: str, source: str, pre_tag: bool, over: bool = False,
            step: str = "install") -> tuple[Path, list[dict]]:
    """A fresh venv in ``work/venv`` with the brain installed; (its scripts folder, the install steps). ``over``:
    installed over the venv already there, as an upgrade (or the installer's rollback) does: research-graph and brain
    are reinstalled even at the same version."""
    target = work / "venv"
    if not over:
        venv.EnvBuilder(with_pip=True, clear=True).create(target)
    scripts = target / ("Scripts" if os.name == "nt" else "bin")
    py = str(scripts / ("python.exe" if os.name == "nt" else "python"))
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1")
    pip = [py, "-m", "pip", "install", "-q"]
    force = ["--force-reinstall", "--no-deps"] if over else []
    if source:
        plan = [[*pip, *force, str(Path(source))],
                [*pip, "--no-deps", *force[:1], str(Path(source) / "packages" / "brain")],
                [*pip, *PLAIN_DEPS]]
    elif pre_tag:
        plan = [[*pip, *force, f"research-graph @ git+{REPO}@{ref}"],
                [*pip, "--no-deps", *force[:1], f"brain @ git+{REPO}@{ref}#subdirectory=packages/brain"],
                [*pip, *PLAIN_DEPS]]
    elif over:   # the tag's research-graph pin first, then brain itself, then whatever else the tag needs
        plan = [[*pip, *force, f"research-graph @ git+{REPO}@{ref}"],
                [*pip, *force, f"brain @ git+{REPO}@{ref}#subdirectory=packages/brain"],
                [*pip, f"brain @ git+{REPO}@{ref}#subdirectory=packages/brain"]]
    else:
        plan = [[*pip, f"brain @ git+{REPO}@{ref}#subdirectory=packages/brain"]]
    steps = []
    for cmd in plan:
        rc, out = run(cmd, env, work, timeout=900)
        steps.append({"step": step, "cmd": " ".join(cmd[1:]), "rc": rc, "ok": rc == 0, "out": out[-2000:]})
        if rc:
            break
    return scripts, steps


def _exe(scripts: Path, name: str) -> str:
    return str(scripts / (f"{name}.exe" if os.name == "nt" else name))


def run_steps(steps: list[tuple], env: dict, root: Path, hook_env: dict | None = None) -> list[dict]:
    """Each (name, cmd, stdin, check[, exit codes]) run in ``root``: (step, cmd, rc, ok, out). A step is ok when its
    exit code is one it allows (0 by default; the codes may be a function of the exit code and the output), no
    traceback is printed and its check, when it has one, holds."""
    out = []
    for name, cmd, stdin, ok, *codes in steps:
        rc, text = run(cmd, hook_env if hook_env and name.startswith("hook") else env, root, stdin)
        allowed = codes[0] if codes else (0,)
        code_ok = allowed(rc, text) if callable(allowed) else rc in allowed
        good = code_ok and "Traceback" not in text and (ok is None or bool(ok(text)))
        out.append({"step": name, "cmd": " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd)),
                    "rc": rc, "ok": good, "out": text[-4000:]})
    return out


def lite_steps(root: Path, scripts: Path, first: bool = True, dev: bool = False) -> list[tuple]:
    """The Lite scenario's steps. ``first=False``, for a brain that already exists: no init apply and no first commit,
    and the init plan is the store plan (what this engine's template would add to the brain's store). ``dev``: the
    engine is a checkout or a branch, which no pin names, so brain refresh runs with --force (brain.skew)."""
    brain = _exe(scripts, "brain")
    plugin = root / "plugins" / "brain-core"
    session = json.dumps({"session_id": "stranger", "hook_event_name": "SessionStart", "source": "startup",
                          "cwd": str(root)})
    push = json.dumps({"session_id": "stranger", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": "gh repo create my-brain --public"}, "cwd": str(root)})
    setup = [
        ("init apply", [brain, "init", "--owner", OWNER, "--apply"], None, lambda o: "claude plugin install" in o),
        ("git init", ["git", "init", "-q"], None, None),
        ("git add", ["git", "add", "-A"], None, None),
        ("first commit", ["git", "commit", "-q", "-m", "my brain"], None, None),
    ]
    return [
        ("version", [brain, "--version"], None, lambda o: o.startswith("brain ")),
        ("init plan" if first else "store plan", [brain, "init", "--owner", OWNER], None,
         lambda o: "plan only" in o and "template generic" in o),
        *(setup if first else []),
        ("check", [brain, "check"], None, lambda o: "graph-check OK" in o and "public scan green" in o),
        ("profile", [brain, "profile"], None, lambda o: "lite" in o),
        ("item", [brain, "item", "add", "wi-first", "--title", "My first item", "--priority", "P1", "--reason",
                  "the pilot's first step"], None, lambda o: "wi-first" in o),
        ("decision", [brain, "decision", "ask", "--title", "Pick a name", "--question", "Which name for the project?",
                      "--option", "Orion: short and free", "--option", "Atlas: taken elsewhere", "--why",
                      "short and free", "--no-notify"], None, lambda o: f"{OWNER} answers" in o),
        ("journal", [brain, "journal", "add", "--title", "First day", "Installed the brain and tried it."], None,
         None),
        ("refresh", [brain, "refresh", "--on-main", *(["--force"] if dev else [])], None, lambda o: "0 project(s) failed" in o),
        ("status", [brain, "status"], None, lambda o: f"waiting on {OWNER}" in o),
        ("queue", [brain, "queue"], None, lambda o: f"waiting on {OWNER}" in o and "Pick a name" in o),
        ("cockpit", [brain, "tui", "--once"], None, lambda o: f"{OWNER}'s queue" in o and "wi-first" in o),
        ("boundary", [brain, "boundary", "--check"], None, None),
        ("help", [brain, "decision", "answer", "--help"], None, lambda o: f"{OWNER}'s own answer" in o),
        ("hook rules", [git_bash(), str(plugin / "hooks" / "inject-rules.sh"), "SessionStart"], session,
         lambda o: f"{OWNER}'s rules" in o),
        ("hook guard", [git_bash(), str(plugin / "hooks" / "guard.sh"), "shell"], push,
         lambda o: '"deny"' in o or "refused" in o.lower()),
    ]


def hook_env_of(env: dict, root: Path, scripts: Path) -> dict:
    return dict(env, CLAUDE_PLUGIN_ROOT=str(root / "plugins" / "brain-core"), CLAUDE_PROJECT_DIR=str(root),
                BRAIN_PYTHON=_exe(scripts, "python"))


def scenario(work: Path, env: dict, scripts: Path) -> list[dict]:
    """The Lite scenario in ``work/ada-brain``: (step, cmd, rc, ok, out) for each step."""
    root = work / "ada-brain"
    root.mkdir(exist_ok=True)
    return run_steps(lite_steps(root, scripts), env, root, hook_env_of(env, root, scripts))


# --- the upgrade test (--upgrade-from): spec-brain-data-compat N8, COMPAT-2 and COMPAT-3 ---------------------------

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
FORMATS = FIXTURES / "formats"
SESSION = "aaaabbbb-1111-2222-3333-444455556666"        # the transcript fixture's session
RECOVERY = "age1" + "strangerrecoverypublickeyfortheupgradetest".ljust(58, "0")   # a public key's shape, no key
SEALED, DRILLED = "2026-11-01T08:00:00Z", "2026-11-01T09:00:00Z"
DIGEST = "0" * 64                                     # a canary's sha-256 (no canary file: nothing is opened here)
# what an engine before the read mode may say of HEAD's additive data: its refusal, never another error
NEWER = re.compile(r"unknown key|unknown field|unexpected field|brain update|written by brain >")
STALE_ROW = re.compile(r"^\s+(differs|new|stray)\s+(\S+)")
RENDER_STALE = re.compile(r"^brain render: \d+ file\(s\) not current", re.M)
# the negative controls (--fault): each a fault the upgrade test must catch, and the step that catches it
FAULTS = {"rewrite": "no loss", "truncated-ledger": "no loss", "unreached": "newer data", "wrong-engine": "engine"}
UNREACHED = "members"           # the format whose newer fixture --fault unreached makes add nothing


def stale_render_only(rc: int, out: str) -> bool:
    """The rollback's brain check under an older engine with the read mode: 0, or 1 when its one failure is the
    plugin HEAD's brain sync rendered (``plugins/``: the engine's own hooks, ``brain_version`` in common.sh at the
    least), which the older engine finds not current. Every other part of the check must be green; an output it does
    not recognise fails closed. The render is not redone: the rollback writes nothing (no loss)."""
    if rc == 0:
        return True
    if rc != 1 or not RENDER_STALE.search(out):
        return False
    rows = [m.group(2) for m in map(STALE_ROW.match, out.splitlines()) if m]
    records = re.search(r"^records: .*; (\d+) error\(s\)", out, re.M)
    return (bool(rows) and all(r.startswith("plugins/") for r in rows) and bool(records)
            and records.group(1) == "0" and not re.search(r"^\s*error:", out, re.M)
            and "graph-check OK" in out and "public scan green" in out)


def where(root: Path, home: Path) -> dict[str, list[Path]]:
    """Where each registered format lives in a brain (docs/formats.md), its files found there. ``template`` lives
    in a template's folder, not in a brain: the store plan reads the engine's, the rollback a newer one; ``status``
    is printed by brain doctor --json, ``docgraph`` read by brain docgraph, ``catalogue`` printed by brain catalogue
    emit: none is stored (:data:`NOT_STORED`)."""
    def found(base: Path, pattern: str) -> list[Path]:
        return sorted(base.glob(pattern)) if base.is_dir() else []
    return {"ar": found(root, "records/ar/*.jsonl"), "config": found(root, "config.json"),
            "ddr": found(root, "records/ddr/*.yaml"), "event": found(home / ".brain" / "ledger", "**/exec-*.jsonl"),
            "packs": found(root, "source/packs.yaml"), "permissions": found(root, "permissions.yaml"),
            "projects": found(root, "projects.yaml"), "members": found(root, "members.yaml"),
            "readme": found(root, "readme.yaml"), "sr": found(root, "records/sr/*/*.yaml"),
            "standards": found(root, "standards/*.yaml"), "template": [], "status": [], "docgraph": [],
            "catalogue": [], "reference": found(root, "docs/reference.yaml"),
            "modules": found(root, "notes/graph/modules.yaml")}


NOT_STORED = ("template", "status", "docgraph", "catalogue")   # registered formats a brain holds no file of (where())


def formats() -> list[tuple[str, int]]:
    """The registered formats and their versions: one ``<format>/v<N>`` folder each under tests/fixtures/formats/."""
    return sorted((d.parent.name, int(d.name[1:])) for d in FORMATS.glob("*/v*") if d.is_dir() and d.name[1:].isdigit())


def fixture(fmt: str, which: str, v: int = 1) -> Path:
    return next((FORMATS / fmt / f"v{v}").glob(f"{which}.*"))


def written(root: Path, home: Path) -> dict:
    """The step that checks the older engine wrote every registered format (a format with no place here fails it:
    a new format joins the upgrade test with its fixtures)."""
    places = where(root, home)
    missing = [f"{fmt} v{v}" for fmt, v in formats() if fmt not in NOT_STORED and not places.get(fmt)]
    out = "\n".join(f"{fmt}: {', '.join(p.name for p in places.get(fmt, [])) or '-'}" for fmt, _ in formats())
    return {"step": "formats", "cmd": "every registered format written", "rc": int(bool(missing)),
            "ok": not missing and bool(formats()), "out": out + ("\nmissing: " + ", ".join(missing) if missing else "")}


def overlay(target, older, newer):
    """``target`` with what ``newer`` adds to ``older`` (a newer brain's additive keys) put at the same place. A key
    ``older`` has and ``target`` lacks, in a mapping of one entry (a fixture's one project), stands for each entry of
    ``target``; lists are matched item by item. Nothing ``target`` already holds is changed."""
    if isinstance(target, dict) and isinstance(older, dict) and isinstance(newer, dict):
        keys = list(newer)
        for i, (k, v) in enumerate(newer.items()):
            if k not in older:
                if k not in target:      # at its place in newer: before the next of newer's keys target has
                    following = next((n for n in keys[i + 1:] if n in target), None)
                    items = list(target.items())
                    at = next((j for j, (n, _) in enumerate(items) if n == following), len(items))
                    target.clear()
                    target.update(items[:at] + [(k, v)] + items[at:])
            elif k in target:
                overlay(target[k], older[k], v)
            elif len(older) == 1:
                for t in target.values():
                    overlay(t, older[k], v)
    elif isinstance(target, list) and isinstance(older, list) and isinstance(newer, list):
        for t, o, n in zip(target, older, newer, strict=False):
            overlay(t, o, n)
    return target


def additive_lines(fmt: str, v: int = 1) -> list[str]:
    """A JSONL format's newer lines that are additive: under the folder's ``v`` and of a kind the older file has (a
    higher ``v`` or a new kind is a newer brain's line, skipped by the reader, not an additive change)."""
    def lines(which: str) -> list[dict]:
        return [json.loads(x) for x in fixture(fmt, which, v).read_text(encoding="utf-8").splitlines() if x.strip()]
    kinds = {r.get("kind") for r in lines("older")}
    return [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in lines("newer")
            if r.get("v") == v and r.get("kind") in kinds]


def _load(f: Path):
    import yaml  # imported when used: the plain stranger test runs on the standard library alone
    text = f.read_text(encoding="utf-8")
    return json.loads(text) if f.suffix == ".json" else yaml.safe_load(text)


def _dump(f: Path, data) -> None:
    import yaml
    text = (json.dumps(data, indent=2, ensure_ascii=False) + "\n" if f.suffix == ".json"
            else yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    f.write_text(text, encoding="utf-8")


def newer_fixture(fmt: str, v: int, fault: str = "") -> Path:
    """A format's newer fixture; under the negative control ``unreached``, UNREACHED's older one (it adds nothing)."""
    return fixture(fmt, "older" if fault == "unreached" and fmt == UNREACHED else "newer", v)


def add_newer(root: Path, home: Path, fault: str = "") -> dict:
    """HEAD's additive fixtures put into the brain HEAD worked on: each registered format's newer keys laid over its
    files (JSONL: the additive lines appended). The step that reports it; it fails when a format's newer keys reached
    none of its files (the rollback would then test nothing of it). ``fault`` ``unreached`` (a negative control):
    UNREACHED's newer fixture is its older one, which adds nothing."""
    out: list[str] = []
    reached: set[str] = set()
    places = where(root, home)
    for fmt, v in formats():
        for f in places.get(fmt, []):
            if f.suffix == ".jsonl":
                add = additive_lines(fmt, v)
                with f.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write("".join(x + "\n" for x in add))
            else:
                before = _load(f)
                after = overlay(copy.deepcopy(before), _load(fixture(fmt, "older", v)),
                                _load(newer_fixture(fmt, v, fault)))
                add = [] if after == before else ["keys"]
                if add:
                    _dump(f, after)
            if add:
                reached.add(fmt)
            what = (f"+{len(add)} line(s)" if f.suffix == ".jsonl" else "+keys") if add else "unchanged"
            out.append(f"{fmt}: {f.name} {what}")
    missing = [f"{fmt} v{v}" for fmt, v in formats() if fmt not in NOT_STORED and fmt not in reached]
    if missing:
        out.append("reached no file: " + ", ".join(missing))
    return {"step": "newer data", "cmd": "HEAD's additive fixtures laid over the brain", "rc": int(bool(missing)),
            "ok": not missing, "out": "\n".join(out)}


def snapshot(bases: list[Path]) -> dict[str, tuple[int, str]]:
    """{path: (size, sha256)} of every file under ``bases`` (folders or files; .git left out)."""
    import hashlib
    out = {}
    for base in bases:
        if base.is_file():
            files = [base]
        else:
            files = [f for f in base.rglob("*") if f.is_file() and ".git" not in f.relative_to(base).parts] \
                if base.is_dir() else []
        for f in files:
            data = f.read_bytes()
            out[f.as_posix()] = (len(data), hashlib.sha256(data).hexdigest())
    return out


def appended(path: str) -> bool:
    """A ledger file is append-only: another engine may add its lines, never change the ones there."""
    return "/ledger/" in path


def lost(before: dict[str, tuple[int, str]]) -> list[str]:
    """What an engine removed or rewrote since ``before`` was taken: data lost (a ledger file may only grow)."""
    import hashlib
    out = []
    for p, (size, h) in before.items():
        f = Path(p)
        if not f.is_file():
            out.append(f"removed: {p}")
            continue
        data = f.read_bytes()
        grows = appended(p)
        if hashlib.sha256(data[:size] if grows else data).hexdigest() != h or (len(data) < size if grows else
                                                                                  len(data) != size):
            out.append(f"changed: {p}")
    return sorted(out)


def injected(fault: str, root: Path, home: Path) -> list[dict]:
    """The step of a fault put on the brain after the older engine's reads (inject), none for the other faults."""
    return [inject(fault, root, home)] if fault in ("rewrite", "truncated-ledger") else []


def back_to(fault: str, prev: tuple[str, str], head: tuple[str, str, bool]) -> tuple[str, str, bool]:
    """The engine reinstalled for the way back: HEAD; the previous one under the negative control ``wrong-engine``."""
    return (*prev, False) if fault == "wrong-engine" else head


def inject(fault: str, root: Path, home: Path) -> dict:
    """A negative control's fault put on the brain after the older engine's reads (``rewrite``: config.json saved
    again with the same data and other bytes; ``truncated-ledger``: an exec ledger's first line dropped), the step that
    reports it. It is ok when the fault was put: the no-loss check, not this step, must then fail."""
    if fault == "rewrite":
        files = [root / "config.json"] if (root / "config.json").is_file() else []
        for f in files:
            text = f.read_text(encoding="utf-8")
            again = json.dumps(json.loads(text), indent=4) + "\n"
            f.write_text(again + ("\n" if again == text else ""), encoding="utf-8")
    else:
        files = [f for f in where(root, home)["event"] if f.read_bytes().strip()][:1]
        for f in files:     # its first line: the older engine's reads appended theirs after the snapshot
            lines = f.read_bytes().splitlines(keepends=True)
            f.write_bytes(b"".join(lines[1:]))
    return {"step": "fault", "cmd": f"--fault {fault}: {', '.join(f.name for f in files) or 'no file to put it on'}",
            "rc": int(not files), "ok": bool(files), "out": ""}


def _py(scripts: Path, code: str, env: dict, root: Path) -> tuple[int, str]:
    return run([_exe(scripts, "python"), "-c", code], env, root)


def engine_is(scripts: Path, env: dict, root: Path, ref: str, source: str) -> dict:
    """The step that checks which engine the venv now runs, from brain's direct_url.json: the tag (its requested
    revision) or the checkout (its folder). Two engines can share a version (HEAD before its bump): a reinstall that
    kept the other one's files would otherwise test the wrong engine and pass."""
    rc, text = _py(scripts, "from importlib.metadata import distribution\n"
                   "print(distribution('brain').read_text('direct_url.json') or '')", env, root)
    try:
        info = json.loads(text.strip().splitlines()[-1]) if rc == 0 and text.strip() else {}
    except ValueError:
        info = {}
    url = str(info.get("url", "")).rstrip("/")
    if source:
        ok = url.lower().endswith("/" + Path(source).name.lower()) or \
            url.lower().endswith("/" + Path(source).name.lower() + "/packages/brain")
        want = f"the checkout {Path(source).name}"
    else:
        ok = (info.get("vcs_info") or {}).get("requested_revision") == ref
        want = f"the ref {ref}"
    return {"step": "engine", "cmd": f"the venv runs {want}", "rc": rc, "ok": rc == 0 and ok, "out": text}


def read_steps(brain: str, check, codes: tuple, check_codes=None) -> list[tuple]:
    """The reads an engine makes of a brain another engine wrote: its checks, the vault (which must show the drill)
    and the ledger's events (brain perf). ``check_codes``, when given, replaces ``codes`` for brain check alone."""
    return [
        ("version", [brain, "--version"], None, lambda o: o.startswith("brain ")),
        ("check", [brain, "check"], None, check, check_codes or codes),
        ("record check", [brain, "record", "check"], None, check, codes),
        ("permissions", [brain, "permissions", "check"], None, check, codes),
        ("vault status", [brain, "vault", "status"], None, lambda o: f"drilled {DRILLED}" in o),
        ("events", [brain, "perf", "--since", "2026-01-01"], None, check, codes),
    ]


def pin_moved(root: Path, env: dict, scripts: Path) -> dict:
    """The documented upgrade step (docs/install.md, « Updates »): config.json's engine.pin moved to the engine now
    installed, and committed; nothing when it is already there."""
    rc, text = run([_exe(scripts, "brain"), "--version"], env, root)
    version = text.split()[1] if rc == 0 and len(text.split()) > 1 else ""
    f = root / "config.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    pin = (data.get("engine") or {}).get("pin", "")
    if not version or pin == f"v{version}":
        return {"step": "pin", "cmd": f"engine.pin {pin}", "rc": rc, "ok": rc == 0, "out": text}
    data.setdefault("engine", {})["pin"] = f"v{version}"
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rc, more = run(["git", "commit", "-q", "-am", f"engine.pin v{version}"], env, root)
    return {"step": "pin", "cmd": f"engine.pin {pin} -> v{version}", "rc": rc, "ok": rc == 0, "out": text + more}


def upgrade(work: Path, env: dict, scripts: Path, prev: tuple[str, str], head: tuple[str, str, bool],
            fault: str = "") -> list[dict]:
    """The upgrade test, in one venv and one brain (``work/ada-brain``):

    1. the previous engine (``prev``: a tag, or a checkout) writes every registered format: brain init, a commit, a
       decision, an AR, an SR from the transcript fixture, the older permissions.yaml and members.yaml (no command
       writes them), the engine's own exec events; then its check;
    2. HEAD (``head``: ref, source, pre_tag) is installed over it, the pin moved as the docs say, then, strict
       (BRAIN_STRICT=1: no note on N-1's data either), the store plan, brain check, brain record check and the rest
       of the Lite scenario;
    3. the rollback: HEAD's additive fixtures laid over the brain and a vault drill on record (written by HEAD's
       vault), the previous engine installed over HEAD as the installer does until the pin moves, then its check,
       record check, vault status, permissions check and a newer template's plan, in read mode (BRAIN_STRICT=0). An
       engine that has the read mode must pass them (its check may only find HEAD's plugin render not current:
       stale_render_only); one before it (0.2.5) may refuse, cleanly. Either way no file
       of the brain, the vault drill included, is changed or removed.

    ``fault`` (a negative control, FAULTS) injects one fault the test must catch."""
    root = work / "ada-brain"
    root.mkdir(exist_ok=True)
    home = Path(env["HOME"])
    brain = _exe(scripts, "brain")
    steps: list[dict] = []

    def phase(name: str, items: list[dict]) -> bool:
        for s in items:
            s["phase"] = name
        steps.extend(items)
        return all(s["ok"] for s in items)

    first = lite_steps(root, scripts)[:6]          # version, init plan, init apply, git init, git add, first commit
    older = [
        ("decision", [brain, "decision", "ask", "--title", "Pick a colour", "--question", "Which colour?", "--option",
                      "Teal: calm", "--option", "Red: loud", "--why", "calm", "--no-notify"], None, None),
        ("ar", [brain, "record", "ar", "--kind", "commit", "--repo", "ada/brain", "--sha", "0123456789abcdef",
                "--subject", "my brain", "--session", SESSION], None, None),
        ("sr", [brain, "record", "sr", "--transcript", str(FIXTURES / "transcript.jsonl"), "--session", SESSION,
                "--summary", "a first session", "--closed"], None, None),
    ]
    ok = phase("previous", [engine_is(scripts, env, root, *prev)] + run_steps(first + older, env, root))
    shutil.copyfile(fixture("permissions", "older"), root / "permissions.yaml")
    shutil.copyfile(fixture("members", "older"), root / "members.yaml")
    shutil.copyfile(fixture("readme", "older"), root / "readme.yaml")   # opt-in: no command writes it
    (root / "docs").mkdir(exist_ok=True)   # the reference's prose (wi-brain-reference-arc42): opt-in, by hand too
    shutil.copyfile(fixture("reference", "older"), root / "docs" / "reference.yaml")
    shutil.copyfile(fixture("modules", "older"), root / "notes" / "graph" / "modules.yaml")   # written by hand
    (root / "standards").mkdir(exist_ok=True)   # a local standards catalog (brain.standards): opt-in too
    shutil.copyfile(fixture("standards", "older"), root / "standards" / "local.yaml")
    with (root / "boundary.yaml").open("a", encoding="utf-8", newline="\n") as fh:    # the template has no rule
        fh.write('  - {glob: "permissions.yaml", side: personal, why: "the permission hierarchy"}\n')
        fh.write('  - {glob: "members.yaml", side: personal, why: "who belongs to the brain"}\n')
        fh.write('  - {glob: "readme.yaml", side: personal, why: "the text of the generated README"}\n')
        fh.write('  - {glob: "standards/**", side: personal, why: "the brain\'s local standards catalogs"}\n')
    ok = phase("previous", [written(root, home)] + run_steps(
        [("git add", ["git", "add", "-A"], None, None), ("commit", ["git", "commit", "-q", "-m", "data"], None, None),
         ("check", [brain, "check"], None, lambda o: "graph-check OK" in o),
         ("record check", [brain, "record", "check"], None, None)], env, root)) and ok
    if not ok:
        return steps

    ref, source, pre_tag = head
    _, inst = install(work, ref, source, pre_tag, over=True, step="upgrade")
    if not phase("upgrade", inst + [engine_is(scripts, env, root, ref, source)]):
        return steps
    strict = dict(env, BRAIN_STRICT="1")
    dev = bool(source or pre_tag)
    phase("HEAD", [pin_moved(root, strict, scripts)])
    phase("HEAD", run_steps(lite_steps(root, scripts, first=False, dev=dev)[:2] + [   # version, store plan
        # the documented step after an upgrade: brain sync renders the plugin again (docs/install.md)
        ("sync", [brain, "sync", *(["--force"] if dev else [])], None, None),
        ("git add", ["git", "add", "-A"], None, None),
        ("commit", ["git", "commit", "-q", "--allow-empty", "-m", "brain sync after the upgrade"], None, None),
    ] + lite_steps(root, scripts, first=False, dev=dev)[2:] + [
        ("record check", [brain, "record", "check"], None, lambda o: "0 error(s), 0 warning(s)" in o),
        ("recipient", [brain, "vault", "recipient", "add", "recovery", "--kind", "recovery", "--age", RECOVERY,
                       "--write"], None, None),
        ("git add", ["git", "add", "-A"], None, None),
        ("commit", ["git", "commit", "-q", "-m", "after the upgrade"], None, None)],
        strict, root, hook_env_of(strict, root, scripts)))

    # the rollback direction: HEAD's additive data, a drill on record, then the previous engine over it
    template = work / "newer-template"
    rc, text = _py(scripts, "import pathlib, shutil; from brain import config, init, vault\n"
                   f"shutil.copytree(init.TEMPLATES / init.DEFAULT_TEMPLATE, {str(template)!r}, dirs_exist_ok=True)\n"
                   "cfg = config.load(pathlib.Path.cwd())\n"
                   "fp = vault.recipients(cfg)[0]['recovery'].fingerprint(cfg.root)\n"
                   "st = vault.load_state()\n"   # the entries vault.canary and vault.drill write, field for field
                   f"st['canary']['recovery'] = {{'sealed_at': {SEALED!r}, 'opened_at': '', 'error': '', "
                   f"'adapter': 'age', 'fingerprint': fp, 'digest': {DIGEST!r}}}\n"
                   f"st['drill']['recovery'] = {{'at': {DRILLED!r}, 'fingerprint': fp}}\n"
                   "vault.save_state(st)\n"
                   "print(vault.state_file())", env, root)
    manifest = template / "template.yaml"
    if rc == 0 and manifest.is_file():
        _dump(manifest, overlay(_load(manifest), _load(fixture("template", "older")),
                                _load(fixture("template", "newer"))))
    phase("rollback", [{"step": "drill", "cmd": "a canary and a drill on record (their entries, written by HEAD's "
                        "vault)", "rc": rc, "ok": rc == 0, "out": text}, add_newer(root, home, fault)])
    kept = [root, home / ".brain" / "ledger", home / ".brain" / "vault"]
    before = snapshot(kept)
    prev_ref, prev_source = prev
    _, inst = install(work, prev_ref, prev_source, False, over=True, step="rollback install")
    if not phase("rollback", inst + [engine_is(scripts, env, root, prev_ref, prev_source)]):
        return steps
    rc, text = _py(scripts, "import brain.schema as s; print(hasattr(s, 'mode'))", env, root)
    tolerant = text.strip().endswith("True")
    codes = (0,) if tolerant else (0, 1, 2)      # 1: a check's errors; 2: a command's refusal (brain init's)

    def clean(o: str) -> bool:
        """A refusal of HEAD's newer keys, not a command the older engine lacks, nor any other error."""
        if "usage: brain" in o or "invalid choice" in o:
            return False
        return tolerant or all(NEWER.search(line) for line in o.splitlines() if line.lstrip().startswith("error:"))

    reads = dict(env, BRAIN_STRICT="0")
    empty = work / "template-plan"
    empty.mkdir(exist_ok=True)
    # HEAD's sync rendered the plugin with its own hooks: an older engine with the read mode finds it not current
    phase("rollback", run_steps(read_steps(brain, clean, codes, stale_render_only if tolerant else None), reads,
                                root) + run_steps([
        ("template plan", [brain, "init", "--owner", OWNER, "--template", str(template)], None,
         lambda o: clean(o) and ("plan only" in o or bool(NEWER.search(o))), codes),
    ], reads, empty))
    phase("rollback", injected(fault, root, home))
    gone = lost(before)
    mode = "read mode" if tolerant else "an engine before the read mode: refusals of the newer keys allowed"
    phase("rollback", [{"step": "no loss", "cmd": f"{len(before)} file(s) unchanged (ledgers only appended), the "
                        f"vault drill included ({mode})", "rc": int(bool(gone)), "ok": not gone,
                        "out": "\n".join(gone)}])

    # and back: HEAD reads what both engines left, in read mode, and nothing is lost over the whole round trip
    _, inst = install(work, *back_to(fault, prev, head), over=True, step="reinstall")
    if not phase("back", inst + [engine_is(scripts, env, root, ref, source)]):
        return steps
    phase("back", run_steps(read_steps(brain, None, (0,)), reads, root))
    gone = lost(before)
    phase("back", [{"step": "no loss", "cmd": f"{len(before)} file(s) unchanged over the round trip", "rc":
                    int(bool(gone)), "ok": not gone, "out": "\n".join(gone)}])
    return steps


def leaks(texts: dict[str, str], deny: list[tuple[str, str]]) -> list[dict]:
    """Each denied term found, whole word and case-insensitive, in the outputs and files given ({where: text})."""
    found = []
    for cat, term in deny:
        rx = re.compile(rf"(?i)(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])")
        for where, text in texts.items():
            if rx.search(text):
                found.append({"category": cat, "term": term, "where": where})
    return found


def brain_files(root: Path) -> dict[str, str]:
    out = {}
    for f in root.rglob("*"):
        if f.is_file() and ".git" not in f.relative_to(root).parts:
            try:
                out[f.relative_to(root).as_posix()] = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    return out


def upgrade_from(value: str, source: str = "") -> tuple[str, str]:
    """--upgrade-from's (ref, source): a folder is a checkout to install, anything else a tag of the public repo. An
    empty value (a CI step that found no tag) or the --source checkout itself is refused: it would test nothing."""
    if not value.strip():
        raise SystemExit("--upgrade-from: empty (no previous tag found?)")
    if Path(value).is_dir():
        folder = str(Path(value).resolve())
        if source and Path(folder) == Path(source).resolve():
            raise SystemExit("--upgrade-from: the --source checkout itself: an upgrade from it tests nothing")
        return "", folder
    return value, ""


def parse_deny(values: list[str]) -> list[tuple[str, str]]:
    out = []
    for v in values:
        cat, sep, term = v.partition(":")
        if not sep or not term.strip():
            raise SystemExit(f"--deny {v!r}: category:term, e.g. people:Name")
        out.append((cat.strip(), term.strip()))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", default="v0.4.0", help="the tag (or, with --pre-tag, the branch) to install")
    ap.add_argument("--source", help="install this local checkout of the repo instead (a dry run of the harness)")
    ap.add_argument("--pre-tag", action="store_true", help="research-graph from --ref, then brain with --no-deps")
    ap.add_argument("--deny", action="append", default=[], help="category:term that must appear nowhere")
    ap.add_argument("--work", help="the folder to work in (default: a new temporary one)")
    ap.add_argument("--keep", action="store_true", help="keep the work folder")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--upgrade-from", metavar="TAG|DIR",
                    help="the upgrade test: this tag (or a checkout of it) writes the data, then --ref or --source "
                         "is installed over it and runs on it, then the tag again reads what that one wrote")
    ap.add_argument("--fault", choices=sorted(FAULTS),
                    help="a negative control of the upgrade test: inject this fault; the verdict must be a no-go")
    args = ap.parse_args(argv)
    try:            # a pipe on Windows is cp1252: a step's output (pip's included) must not crash the report
        sys.stdout.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError, OSError):
        pass
    if args.fault and args.upgrade_from is None:
        ap.error("--fault: a fault of the upgrade test, with --upgrade-from")
    deny = parse_deny(args.deny)
    work = Path(args.work or tempfile.mkdtemp(prefix="stranger-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = str(Path(args.source).resolve()) if args.source else ""
    prev = upgrade_from(args.upgrade_from, source) if args.upgrade_from is not None else None
    if prev:
        scripts, steps = install(work, prev[0], prev[1], False, step="install previous")
    else:
        scripts, steps = install(work, args.ref, source, args.pre_tag)
    installed = all(s["ok"] for s in steps)
    report = {"ref": args.source or args.ref, "pre_tag": args.pre_tag, "platform": sys.platform,
              "python": sys.version.split()[0], "work": str(work), "steps": list(steps), "leaks": []}
    if prev:
        report["upgrade_from"] = args.upgrade_from
    if args.fault:
        report["fault"] = args.fault
    if installed:
        env = isolated_env(work, scripts)
        report["docker_on_path"] = bool(shutil.which("docker", path=env["PATH"]))
        if prev:
            report["steps"] += upgrade(work, env, scripts, prev, (args.ref, source, args.pre_tag), args.fault or "")
        else:
            report["steps"] += scenario(work, env, scripts)
        texts = {f"output of {s['step']}": s["out"] for s in report["steps"]}
        texts.update(brain_files(work / "ada-brain"))
        report["leaks"] = leaks(texts, deny)
    failed = [s for s in report["steps"] if not s["ok"]]
    # docker off the PATH is the pilot's isolation (a stranger's machine needs none), not what the upgrade test checks:
    # there it is reported only (GitHub's Windows runners keep docker.exe in System32)
    docker = bool(report.get("docker_on_path")) and not prev
    report["verdict"] = "go" if installed and not failed and not report["leaks"] and not docker else "no-go"
    (work / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    else:
        print(f"stranger test: {report['ref']}{' (pre-tag)' if args.pre_tag else ''}"
              f"{' upgraded from ' + args.upgrade_from if prev else ''} on {sys.platform}, Python "
              f"{report['python']}, in {work}")
        if args.fault:
            print(f"  fault injected: {args.fault} (a negative control: the verdict must be no-go, at its "
                  f"{FAULTS[args.fault]!r} step)")
        for s in report["steps"]:
            where = f"{s['phase']}: " if s.get("phase") else ""
            print(f"  {'ok  ' if s['ok'] else 'FAIL'} {where + s['step']:<12} rc {s['rc']}  {s['cmd']}")
            if not s["ok"]:
                print("       " + "\n       ".join(s["out"].strip().splitlines()[-12:]))
        if report.get("docker_on_path"):
            print(f"  {'FAIL' if docker else 'note'} docker is on the reduced PATH")
        for lk in report["leaks"]:
            print(f"  LEAK {lk['category']} term {lk['term']!r} in {lk['where']}")
        print(f"verdict: {report['verdict']} (report: {work / 'report.json'})")
    if not args.keep and not args.work and report["verdict"] == "go":
        shutil.rmtree(work, ignore_errors=True)
    return 2 if not installed else 0 if report["verdict"] == "go" else 1


if __name__ == "__main__":
    sys.exit(main())
