"""The stranger test (wi-brain-stranger-install-test): install the brain from the public repo into a fresh venv, as
someone who has never seen its author's machine would, then run the Lite scenario; its verdict is a pilot's go.

    python stranger_test.py [--ref v0.2.5 | --source DIR] [--pre-tag] [--deny people:NAME ...] [--work DIR] [--keep]
                            [--json] [--upgrade-from TAG|DIR]

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
   by hand, an SR from the transcript fixture, the older ``permissions.yaml`` (no command writes it), the engine's own
   exec events; a format with no place in :func:`where` fails the step. Then its brain check.
2. **The upgrade.** ``--ref`` or ``--source`` is installed over it, as an upgrade does; ``engine.pin`` is moved and
   committed if the version changed (docs/install.md); then, strict (``BRAIN_STRICT=1``: N reads N-1's data with no
   note), the store plan (``brain init`` on the existing brain), brain check, brain record check and the rest of the
   Lite scenario (``refresh --force`` for a checkout or a branch, which no pin names), and a recovery key declared.
3. **The rollback.** HEAD's additive fixtures (each ``newer`` file's keys that its ``older`` one lacks, JSONL lines
   under the same ``v`` and of a known kind) are laid over the brain's files, and a vault drill is recorded by HEAD's
   vault; TAG is installed back over HEAD (as ``install.ps1 -Apply`` does until the pin PR merges) and runs, in read
   mode (``BRAIN_STRICT=0``), brain check, brain record check, brain permissions check, brain vault status (which
   must show the drill) and a newer template's init plan. A TAG with the read mode must pass them; one before it
   (0.2.5) may refuse, cleanly (exit 1 or 2, no traceback, no usage error). Either way no file of the brain and not
   the vault state is changed or removed (sha-256 before and after).

The upgrade test reads PyYAML in the harness's own Python (CI installs it) and the fixtures from the checkout it runs
from.

Exit code 0 on a go, 1 when a check fails, 2 when the install fails. ``--json`` prints the report; it is also
written to ``<work>/report.json``.
"""

from __future__ import annotations

import argparse
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
    exit code is one it allows (0 by default), no traceback is printed and its check, when it has one, holds."""
    out = []
    for name, cmd, stdin, ok, *codes in steps:
        rc, text = run(cmd, hook_env if hook_env and name.startswith("hook") else env, root, stdin)
        good = rc in (codes[0] if codes else (0,)) and "Traceback" not in text and (ok is None or bool(ok(text)))
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


def where(root: Path, home: Path) -> dict[str, list[Path]]:
    """Where each registered format lives in a brain (docs/formats.md), its files found there. ``template`` lives
    in a template's folder, not in a brain: the store plan reads the engine's, the rollback a newer one."""
    def found(base: Path, pattern: str) -> list[Path]:
        return sorted(base.glob(pattern)) if base.is_dir() else []
    return {"ar": found(root, "records/ar/*.jsonl"), "config": found(root, "config.json"),
            "ddr": found(root, "records/ddr/*.yaml"), "event": found(home / ".brain" / "ledger", "**/exec-*.jsonl"),
            "packs": found(root, "source/packs.yaml"), "permissions": found(root, "permissions.yaml"),
            "projects": found(root, "projects.yaml"), "sr": found(root, "records/sr/*/*.yaml"), "template": []}


def formats() -> list[tuple[str, int]]:
    """The registered formats and their versions: one ``<format>/v<N>`` folder each under tests/fixtures/formats/."""
    return sorted((d.parent.name, int(d.name[1:])) for d in FORMATS.glob("*/v*") if d.is_dir() and d.name[1:].isdigit())


def fixture(fmt: str, which: str, v: int = 1) -> Path:
    return next((FORMATS / fmt / f"v{v}").glob(f"{which}.*"))


def written(root: Path, home: Path) -> dict:
    """The step that checks the older engine wrote every registered format (a format with no place here fails it:
    a new format joins the upgrade test with its fixtures)."""
    places = where(root, home)
    missing = [f"{fmt} v{v}" for fmt, v in formats() if fmt != "template" and not places.get(fmt)]
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


def add_newer(root: Path, home: Path) -> dict:
    """HEAD's additive fixtures put into the brain HEAD worked on: each registered format's newer keys laid over its
    files (JSONL: the additive lines appended). The step that reports it."""
    out = []
    places = where(root, home)
    for fmt, v in formats():
        for f in places.get(fmt, []):
            if f.suffix == ".jsonl":
                add = additive_lines(fmt, v)
                with f.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write("".join(x + "\n" for x in add))
            else:
                before = _load(f)
                after = overlay(json.loads(json.dumps(before)), _load(fixture(fmt, "older", v)),
                                _load(fixture(fmt, "newer", v)))
                add = [] if after == before else ["keys"]
                if add:
                    _dump(f, after)
            what = (f"+{len(add)} line(s)" if f.suffix == ".jsonl" else "+keys") if add else "unchanged"
            out.append(f"{fmt}: {f.name} {what}")
    return {"step": "newer data", "cmd": "HEAD's additive fixtures laid over the brain", "rc": 0, "ok": True,
            "out": "\n".join(out)}


def snapshot(root: Path, extra: list[Path]) -> dict[str, str]:
    """{path: sha256} of every file of the brain (but .git) and of ``extra``."""
    import hashlib
    files = [f for f in root.rglob("*") if f.is_file() and ".git" not in f.relative_to(root).parts]
    return {f.as_posix(): hashlib.sha256(f.read_bytes()).hexdigest() for f in files + [f for f in extra if f.is_file()]}


def lost(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """What the older engine removed or rewrote: data lost in the rollback direction."""
    return sorted(f"{'removed' if p not in after else 'changed'}: {p}" for p, h in before.items() if after.get(p) != h)


def _py(scripts: Path, code: str, env: dict, root: Path) -> tuple[int, str]:
    return run([_exe(scripts, "python"), "-c", code], env, root)


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


def upgrade(work: Path, env: dict, scripts: Path, prev: tuple[str, str], head: tuple[str, str, bool]) -> list[dict]:
    """The upgrade test, in one venv and one brain (``work/ada-brain``):

    1. the previous engine (``prev``: a tag, or a checkout) writes every registered format: brain init, a commit, a
       decision, an AR, an SR from the transcript fixture, the older permissions.yaml (no command writes it), the
       engine's own exec events; then its check;
    2. HEAD (``head``: ref, source, pre_tag) is installed over it, the pin moved as the docs say, then, strict
       (BRAIN_STRICT=1: no note on N-1's data either), the store plan, brain check, brain record check and the rest
       of the Lite scenario;
    3. the rollback: HEAD's additive fixtures laid over the brain and a vault drill on record (written by HEAD's
       vault), the previous engine installed over HEAD as the installer does until the pin moves, then its check,
       record check, vault status, permissions check and a newer template's plan, in read mode (BRAIN_STRICT=0). An
       engine that has the read mode must pass them; one before it (0.2.5) may refuse, cleanly. Either way no file
       of the brain, the vault drill included, is changed or removed."""
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
    ok = phase("previous", run_steps(first + older, env, root))
    shutil.copyfile(fixture("permissions", "older"), root / "permissions.yaml")
    with (root / "boundary.yaml").open("a", encoding="utf-8", newline="\n") as fh:    # the template has no rule for it
        fh.write('  - {glob: "permissions.yaml", side: personal, why: "the permission hierarchy"}\n')
    ok = phase("previous", [written(root, home)] + run_steps(
        [("git add", ["git", "add", "-A"], None, None), ("commit", ["git", "commit", "-q", "-m", "data"], None, None),
         ("check", [brain, "check"], None, lambda o: "graph-check OK" in o),
         ("record check", [brain, "record", "check"], None, None)], env, root)) and ok
    if not ok:
        return steps

    ref, source, pre_tag = head
    _, inst = install(work, ref, source, pre_tag, over=True, step="upgrade")
    if not phase("upgrade", inst):
        return steps
    strict = dict(env, BRAIN_STRICT="1")
    phase("HEAD", [pin_moved(root, strict, scripts)])
    phase("HEAD", run_steps(lite_steps(root, scripts, first=False, dev=bool(source or pre_tag)) + [
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
                   "st = vault.load_state()\n"   # the shapes vault.canary and vault.drill write
                   f"st['canary']['recovery'] = {{'sealed_at': {SEALED!r}, 'fingerprint': fp}}\n"
                   f"st['drill']['recovery'] = {{'at': {DRILLED!r}, 'fingerprint': fp}}\n"
                   "vault.save_state(st)\n"
                   "print(vault.state_file())", env, root)
    state = Path(text.strip().splitlines()[-1]) if rc == 0 and text.strip() else home / ".brain" / "vault" / "state.json"
    manifest = template / "template.yaml"
    if rc == 0 and manifest.is_file():
        _dump(manifest, overlay(_load(manifest), _load(fixture("template", "older")), _load(fixture("template", "newer"))))
    phase("rollback", [{"step": "drill", "cmd": "a vault drill on record, written by HEAD", "rc": rc, "ok": rc == 0,
                        "out": text}, add_newer(root, home)])
    before = snapshot(root, [state])
    prev_ref, prev_source = prev
    _, inst = install(work, prev_ref, prev_source, False, over=True, step="rollback install")
    if not phase("rollback", inst):
        return steps
    rc, text = _py(scripts, "import brain.schema as s; print(hasattr(s, 'mode'))", env, root)
    tolerant = text.strip().endswith("True")
    codes = (0,) if tolerant else (0, 1, 2)      # 1: a check's errors; 2: a command's refusal (brain init's)

    def clean(o: str) -> bool:                   # a refusal, not a command the older engine lacks
        return "usage: brain" not in o and "invalid choice" not in o

    reads = dict(env, BRAIN_STRICT="0")
    empty = work / "template-plan"
    empty.mkdir(exist_ok=True)
    phase("rollback", run_steps([
        ("version", [brain, "--version"], None, lambda o: o.startswith("brain ")),
        ("check", [brain, "check"], None, clean, codes),
        ("record check", [brain, "record", "check"], None, clean, codes),
        ("permissions", [brain, "permissions", "check"], None, clean, codes),
        ("vault status", [brain, "vault", "status"], None, lambda o: f"drilled {DRILLED}" in o),
    ], reads, root) + run_steps([
        ("template plan", [brain, "init", "--owner", OWNER, "--template", str(template)], None, clean, codes),
    ], reads, empty))
    gone = lost(before, snapshot(root, [state]))
    phase("rollback", [{"step": "no loss", "cmd": f"{len(before)} file(s) unchanged, the vault drill included "
                        f"({'read mode' if tolerant else 'an engine before the read mode: refusals allowed'})",
                        "rc": int(bool(gone)), "ok": not gone, "out": "\n".join(gone)}])
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


def upgrade_from(value: str) -> tuple[str, str]:
    """--upgrade-from's (ref, source): a folder is a checkout to install, anything else a tag of the public repo."""
    return ("", str(Path(value).resolve())) if Path(value).is_dir() else (value, "")


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
    ap.add_argument("--ref", default="v0.2.5", help="the tag (or, with --pre-tag, the branch) to install")
    ap.add_argument("--source", help="install this local checkout of the repo instead (a dry run of the harness)")
    ap.add_argument("--pre-tag", action="store_true", help="research-graph from --ref, then brain with --no-deps")
    ap.add_argument("--deny", action="append", default=[], help="category:term that must appear nowhere")
    ap.add_argument("--work", help="the folder to work in (default: a new temporary one)")
    ap.add_argument("--keep", action="store_true", help="keep the work folder")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--upgrade-from", metavar="TAG|DIR",
                    help="the upgrade test: this tag (or a checkout of it) writes the data, then --ref or --source "
                         "is installed over it and runs on it, then the tag again reads what that one wrote")
    args = ap.parse_args(argv)
    deny = parse_deny(args.deny)
    work = Path(args.work or tempfile.mkdtemp(prefix="stranger-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = str(Path(args.source).resolve()) if args.source else ""
    prev = upgrade_from(args.upgrade_from) if args.upgrade_from else None
    if prev:
        scripts, steps = install(work, prev[0], prev[1], False, step="install previous")
    else:
        scripts, steps = install(work, args.ref, source, args.pre_tag)
    installed = all(s["ok"] for s in steps)
    report = {"ref": args.source or args.ref, "pre_tag": args.pre_tag, "platform": sys.platform,
              "python": sys.version.split()[0], "work": str(work), "steps": list(steps), "leaks": []}
    if prev:
        report["upgrade_from"] = args.upgrade_from
    if installed:
        env = isolated_env(work, scripts)
        report["docker_on_path"] = bool(shutil.which("docker", path=env["PATH"]))
        if prev:
            report["steps"] += upgrade(work, env, scripts, prev, (args.ref, source, args.pre_tag))
        else:
            report["steps"] += scenario(work, env, scripts)
        texts = {f"output of {s['step']}": s["out"] for s in report["steps"]}
        texts.update(brain_files(work / "ada-brain"))
        report["leaks"] = leaks(texts, deny)
    failed = [s for s in report["steps"] if not s["ok"]]
    report["verdict"] = "go" if installed and not failed and not report["leaks"] and \
        not report.get("docker_on_path") else "no-go"
    (work / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    else:
        print(f"stranger test: {report['ref']}{' (pre-tag)' if args.pre_tag else ''}"
              f"{' upgraded from ' + args.upgrade_from if prev else ''} on {sys.platform}, Python "
              f"{report['python']}, in {work}")
        for s in report["steps"]:
            where = f"{s['phase']}: " if s.get("phase") else ""
            print(f"  {'ok  ' if s['ok'] else 'FAIL'} {where + s['step']:<12} rc {s['rc']}  {s['cmd']}")
            if not s["ok"]:
                print("       " + "\n       ".join(s["out"].strip().splitlines()[-12:]))
        if report.get("docker_on_path"):
            print("  FAIL docker is on the reduced PATH")
        for lk in report["leaks"]:
            print(f"  LEAK {lk['category']} term {lk['term']!r} in {lk['where']}")
        print(f"verdict: {report['verdict']} (report: {work / 'report.json'})")
    if not args.keep and not args.work and report["verdict"] == "go":
        shutil.rmtree(work, ignore_errors=True)
    return 2 if not installed else 0 if report["verdict"] == "go" else 1


if __name__ == "__main__":
    sys.exit(main())
