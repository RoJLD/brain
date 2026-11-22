"""The install in one owner gesture (wi-brain-release-apply; docs/release.md, « 4. The pin and the machines »).

``brain release apply`` installs the engine at the planning brain's ``engine.pin`` on this machine, after its pin PR
merged: its plan, one y (``--yes`` in a script of the owner's), then in order, stopping at the first step that fails
and saying which:

1. **plan**: the brain's own installer (config.json ``engine.installer``, from the brain's root) run without
   arguments: its plan, shown as it prints it (a plan that fails stops here, before the y);
2. **install**: the installer with ``-Apply``, in the owner's terminal (its output and prompts there);
3. **version**: ``brain --version`` of the engine now installed (the ``brain`` on the PATH, else this interpreter's
   ``-m brain``, in a new process) against ``engine.pin``;
4. **clone**: the owner's engine clone fast-forwarded (brain.engineclone: on main, clean and in no operation only;
   never a switch, a reset or a stash; any other state is said, not a failure);
5. **verify**: ``brain release verify`` with the new engine (``--no-tests`` passed on);
6. **sessions**: the open sessions of this machine named, to restart by the owner (a notice: nothing is restarted
   or sent).

A brain without an installer of its own is refused (``brain update`` is its one gesture). An owner gesture
(brain.gestures, category installer): refused in an agent's session after the plan, and by the owner guard.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

STEPS = ("install", "version", "clone", "verify", "sessions")
PLAN_TIMEOUT_S = 300
VERSION_TIMEOUT_S = 60
NOTICE_STATES = ("running", "asking", "idle", "stale")   # a session whose process may still run the old engine
Runner = Callable[..., subprocess.CompletedProcess]


class ApplyError(ValueError):
    """Nothing to apply here: no planning brain, no pin, no installer (exit 2)."""


@dataclass
class ApplyPlan:
    root: Path
    pin: str
    installer: Path
    brain: list[str] = field(default_factory=list)   # the new engine's command, for version and verify
    lines: list[str] = field(default_factory=list)


def installer_argv(script: Path, args: list[str]) -> list[str]:
    """The process that runs the installer: a .py with this interpreter, else brain.detail.script_argv (PowerShell
    for a .ps1, sh for a .sh, else the file itself)."""
    if script.suffix.lower() == ".py":
        return [sys.executable, str(script), *args]
    from . import detail
    return detail.script_argv(script, args)


def new_brain() -> list[str]:
    """The engine a new process runs: the brain command on the PATH (the installer's launcher), else this
    interpreter's -m brain (an install in place)."""
    exe = shutil.which("brain")
    return [exe] if exe else [sys.executable, "-m", "brain"]


def plan(root: Path, *, brain: list[str] | None = None) -> ApplyPlan:
    from . import release, update
    try:
        cfg = release._config_of(root)
    except release.ReleaseError as exc:
        raise ApplyError(str(exc)) from None
    eng = cfg.data.get("engine") if isinstance(cfg.data.get("engine"), dict) else {}
    pin = eng.get("pin")
    if not isinstance(pin, str) or not update.version_of(pin):
        raise ApplyError(f"{cfg.file}: engine.pin is {pin!r}, not a release tag vX.Y.Z")
    name = eng.get("installer")
    if not isinstance(name, str) or not name:
        raise ApplyError(f"{cfg.file}: no engine.installer: brain update is this brain's install, in one gesture")
    script = (cfg.root / name).resolve()
    if not script.is_file():
        raise ApplyError(f"{script}: the installer config.json engine.installer names is missing")
    p = ApplyPlan(root=cfg.root, pin=pin, installer=script, brain=brain or new_brain())
    p.lines = [
        f"plan     {script.name}: its plan, shown above (run without arguments)",
        f"install  {script.name} -Apply (its output and prompts in this terminal)",
        f"version  brain --version of the engine now installed ({' '.join(p.brain)}) against engine.pin {pin}",
        "clone    the engine clone fast-forwarded when on main and clean (never switched, reset or stashed)",
        "verify   brain release verify (the after-install checks, recorded for brain release status)",
        "sessions the open sessions named, to restart yourself (nothing is restarted)",
    ]
    return p


def show_plan(p: ApplyPlan, runner: Runner, out) -> tuple[bool, str]:
    """The installer's plan (no -Apply), printed; (ok, why)."""
    argv = installer_argv(p.installer, [])
    try:
        r = runner(argv, cwd=str(p.root), capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=PLAN_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{p.installer.name} could not run ({exc.__class__.__name__}: {exc})"
    text = ((r.stdout or "") + (r.stderr or "")).rstrip()
    if text:
        out(text)
    return (True, "") if r.returncode == 0 else (False, f"{p.installer.name}'s plan failed (exit {r.returncode})")


# --- the steps: (outcome, detail), outcome done, same, skipped or failed ---

def _install(p: ApplyPlan, ctx: dict) -> tuple[str, str]:
    argv = installer_argv(p.installer, ["-Apply"])
    try:   # the owner's terminal: the installer's own output and prompts (no capture)
        r = ctx["runner"](argv, cwd=str(p.root))
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", f"{p.installer.name} -Apply could not run ({exc.__class__.__name__})"
    if r.returncode != 0:
        return "failed", f"{p.installer.name} -Apply failed (exit {r.returncode}): its output above says where"
    return "done", f"{p.installer.name} -Apply"


def _version(p: ApplyPlan, ctx: dict) -> tuple[str, str]:
    from . import update
    try:
        r = ctx["runner"]([*p.brain, "--version"], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=VERSION_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", f"brain --version could not run ({exc.__class__.__name__})"
    said = (r.stdout or r.stderr or "").strip()
    got = update.version_of(said.split()[-1]) if said else None
    want = update.version_of(p.pin)
    if r.returncode != 0 or got is None:
        return "failed", f"brain --version said {said or 'nothing'!r} (exit {r.returncode})"
    if got != want:
        return "failed", f"brain {said.split()[-1]} runs, not the pin {p.pin}: the install did not take"
    return "done", f"brain {said.split()[-1]} = engine.pin {p.pin}"


def _clone(p: ApplyPlan, ctx: dict) -> tuple[str, str]:
    from . import engineclone, release
    if ctx["offline"]:
        return "skipped", "--offline: the engine clone left as it is"
    res = engineclone.refresh(p.root, cfg=release._config_of(p.root))   # its git calls bounded, their tree stopped
    if res.clone is None:
        return "skipped", res.said() or "no engine clone named (config.json engine.clone) or registered here"
    outcome = {engineclone.PULLED: "done", engineclone.SAME: "same"}.get(res.state, "skipped")
    return outcome, res.said()   # a clone left as it is is said, never a failure of the install


def _verify(p: ApplyPlan, ctx: dict) -> tuple[str, str]:
    argv = [*p.brain, "release", "verify", "--planning", str(p.root)] + ([] if ctx["tests"] else ["--no-tests"])
    try:
        r = ctx["runner"](argv, cwd=str(p.root))
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", f"brain release verify could not run ({exc.__class__.__name__})"
    if r.returncode != 0:
        return "failed", f"brain release verify failed (exit {r.returncode}): its lines above, its logs under " \
                         "$BRAIN_HOME/release/"
    return "done", "brain release verify passed"


def open_sessions() -> list[str]:
    """The sessions of this machine that may still run the engine that was there: live (running, asking, idle or
    stale), not archived; '' when the app's index cannot be read."""
    from . import sessions
    try:
        tree = sessions.load(briefs=False)
    except Exception:   # an unreadable app index or ledger: the notice says it could not list them
        return []
    out = []
    for node in tree.nodes.values():
        if node.get("archived"):
            continue
        state = sessions.state_of(node, tree.ends)
        if state in NOTICE_STATES:
            ident = sessions.short(node.get("host_id") or node.get("session") or "")
            out.append(f"{ident} {str(node.get('title') or '')[:60]} ({state})".replace("  ", " "))
    return sorted(out)


def _sessions(p: ApplyPlan, ctx: dict) -> tuple[str, str]:
    found = ctx["sessions"]()
    if not found:
        return "done", f"no open session found: new ones run {p.pin}"
    return "done", f"restart these {len(found)} session(s) to run {p.pin} (nothing restarted):\n" + "\n".join(found)


RUN = {"install": _install, "version": _version, "clone": _clone, "verify": _verify, "sessions": _sessions}


def run(p: ApplyPlan, *, runner: Runner = subprocess.run, tests: bool = True, offline: bool = False,
        sessions=open_sessions, say: Callable[[str], object] = print) -> list[dict]:
    """Each step in order, said as it ends; the first that fails stops the rest (in the rows as ``not run``)."""
    ctx = {"runner": runner, "tests": tests, "offline": offline, "sessions": sessions}
    rows, failed = [], False
    for name in STEPS:
        if failed:
            rows.append({"step": name, "outcome": "not run", "detail": ""})
            continue
        outcome, detail = RUN[name](p, ctx)
        rows.append({"step": name, "outcome": outcome, "detail": detail})
        say(f"{name:<9}{outcome:<8}{detail}".rstrip().replace("\n", "\n  "))
        failed = outcome == "failed"
    return rows


def main(args, *, runner: Runner = subprocess.run, brain: list[str] | None = None, ask=None, out=print,
         refused: str | None = None, sessions=open_sessions) -> int:
    """brain release apply: the plan (always: the installer's own), then, in the owner's terminal and on their y,
    the steps."""
    from . import detail, release
    root = release.planning_root(args)
    if root is None:
        print("brain release apply: no planning brain: --planning names it (or --root, or a personal brain)",
              file=sys.stderr)
        return 2
    try:
        p = plan(root, brain=brain)
    except ApplyError as exc:
        print(f"brain release apply: {exc}", file=sys.stderr)
        return 2
    out(f"apply    engine.pin {p.pin} of {p.root} on this machine")
    ok, why = show_plan(p, runner, out)
    out("\n".join(p.lines))
    if not ok:
        out(f"stopped  at plan: {why}; nothing installed")
        return 1
    refusal = detail.refused() if refused is None else refused
    if refusal:
        out(f"brain release apply: {refusal}; run it yourself in a terminal")
        return 1
    if not args.yes:
        if ask is None and not sys.stdin.isatty():
            out("brain release apply: no terminal to answer y; --yes runs it (nothing installed)")
            return 1
        if (ask or input)(f"Install {p.pin} on this machine now? [y/N] ").strip().lower() not in ("y", "yes", "o",
                                                                                               "oui"):
            out("nothing installed")
            return 0
    rows = run(p, runner=runner, tests=args.tests, offline=args.offline, sessions=sessions, say=out)
    failed = next((r for r in rows if r["outcome"] == "failed"), None)
    if failed:
        out(f"stopped  at {failed['step']}: the steps after it did not run; fix it, then run it again")
        return 1
    out(f"next     brain release status {p.pin.lstrip('v')}")
    return 0
