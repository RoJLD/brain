"""``brain uninstall [--purge] [--confirm-recovery STORE...] [--apply]`` (wi-brain-uninstall-purge): every trace of the
brain on this machine that its store registry knows, a plan first, removed with ``--apply`` by the owner (refused in
a Claude Code session's shell, as every owner's action of brain.detail).

Without ``--purge`` (the install, the data kept):

- the scheduled tasks this machine installed (brain.schedule's record), which run the command removed below;
- the Claude Code plugin and its marketplace (config.json ``adapters.claude``), through the ``claude`` CLI: its
  commands are named when the CLI is not found;
- the launcher on the PATH: ``<BRAIN_HOME>\\bin`` taken out of the user PATH on Windows, ``~/.local/bin/brain`` when it
  links into BRAIN_HOME elsewhere;
- the engine's install stores in BRAIN_HOME (:data:`brain.classes.ENGINE_STORES` of format ``install``: the venv, the
  slots, the launcher's folder, the tags' clones). One this command runs from (its venv, the launcher's folder when
  it was started from there) is left, with the command that removes it once this one has exited (Windows holds a
  running program's files).

With ``--purge``, every other entry of BRAIN_HOME and this machine's device key in its keystore (brain.vault), then
BRAIN_HOME itself once empty:

- a ``derived`` store (a cache, an index, a view: rebuilt from the rest) is removed;
- a store nothing else keeps (format ``truth-local`` or ``log``: the ledger, the session records, the vault, the
  machine's token...), a name no store covers (sealed by default, classes.home_unknown) and the device key are held
  until the owner confirms their recovery copy, by name (``--confirm-recovery ledger vault``) or ``all`` (the
  registry's stores and the key: a name no store covers is confirmed by its own name); brain vault seal and brain
  spool push make one; the purge cannot tell that a copy elsewhere is whole, so it asks;
- a write's leftover (``.tmp``, ``.bak``, ``.lock``...) follows its store.

It refuses a BRAIN_HOME it may not empty (:func:`home_refusal`: a filesystem root, the user's home, a folder that
holds the transcripts or the personal brain, one that holds none of the engine's stores). What it leaves, with the
command that removes it: the personal brain's merge driver; Claude Code's settings keep the rules and settings the
installer added. A step that fails is reported and the others still run.

What it never touches: Claude Code's transcripts (``~/.claude/projects``: Claude Code's), the personal brain's repo
and its remote, a path outside BRAIN_HOME other than the launcher's link (a store's path that resolves outside, a link
or a junction, has only its link removed).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import classes, config, paths, stateio

RUN_TIMEOUT = 120
ALL = "all"
KEYSTORE = "keystore"        # the name --confirm-recovery gives the device key
HELD_FORMATS = ("truth-local", "log")


@dataclass
class Step:
    """One trace: its kind (schedule, plugin, path, store, keystore, home), what the plan says, and how it goes."""
    kind: str
    name: str
    action: str              # remove, held, left, keep
    line: str
    apply: Callable[[], str] | None = None   # "" when done, else why it failed


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT, encoding="utf-8",
                          errors="replace")


def _under_test() -> bool:
    """Under pytest the real claude CLI and the real user PATH are never reached unless a test injects its own (as
    brain.paths refuses the real ~/.brain and brain.keystore the real keystore)."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _line(action: str, text: str) -> str:
    return f"{action:<8} {text}"


# --- the install --------------------------------------------------------------------------------------------------

def schedule_steps(run=_run) -> list[Step]:
    """The scheduled tasks this machine installed (brain.schedule's record), each removed."""
    from . import schedule
    try:
        record = schedule.installed()
    except (stateio.StateError, OSError, ValueError) as exc:   # unreadable or newer: said, nothing removed blind
        return [Step("schedule", "record", "left", _line("left", f"the schedules' record could not be read ({exc}): "
                                                                 "brain schedule list"))]
    if not record:
        return []
    sys_ = None if run is _run and _under_test() else schedule.system(run)   # never the real scheduler in a test
    if sys_ is None:
        return [Step("schedule", n, "left", _line("left", f"schedule {n}: no scheduler answers here"))
                for n in sorted(record)]

    def delete(name):
        return lambda: sys_.delete(name) or ""
    return [Step("schedule", n, "remove", _line("remove", f"schedule {n} ({rec.get('where') or sys_.where(n)})"),
                 delete(n)) for n, rec in sorted(record.items())]


def plugin_steps(cfg: config.Config, run=_run, claude: str | None = None) -> list[Step]:
    """The core plugin and its marketplace, through the claude CLI (at user scope, as install.ps1 installs them)."""
    names = config.claude(cfg)
    plugin = f"{names['plugin']}@{names['marketplace']}"
    argvs = [("plugin", plugin, ["plugin", "uninstall", plugin, "--scope", "user"]),
             ("marketplace", names["marketplace"], ["plugin", "marketplace", "remove", names["marketplace"]])]
    exe = claude if claude is not None else (None if _under_test() else shutil.which("claude"))
    if not exe:
        return [Step("plugin", name, "left", _line("left", f"{what} {name}: no claude CLI here (claude "
                                                            f"{' '.join(argv)}, in your terminal)"))
                for what, name, argv in argvs]
    present = {"plugin": _listed(run, [exe, "plugin", "list", "--json"], "id"),
               "marketplace": _listed(run, [exe, "plugin", "marketplace", "list", "--json"], "name")}

    def call(argv):
        def go():
            r = run([exe, *argv])
            said = (r.stderr or r.stdout or "").strip().splitlines()
            return "" if r.returncode == 0 else (said[-1] if said else f"exit {r.returncode}")
        return go
    return [Step("plugin", name, "remove", _line("remove", f"{what} {name} (claude {' '.join(argv)})"), call(argv))
            for what, name, argv in argvs if present[what] is None or name in present[what]]


def _listed(run, argv: list[str], key: str) -> set[str] | None:
    """The names a ``claude ... list --json`` gives (None when it cannot say: the step is then planned anyway)."""
    import json
    try:
        r = run(argv)
        rows = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return {str(x.get(key)) for x in rows if isinstance(x, dict)} if isinstance(rows, list) else None


class WindowsUserPath:
    """The user PATH of the registry (HKCU\\Environment), as install.ps1 writes it."""

    def get(self) -> str:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return str(winreg.QueryValueEx(k, "Path")[0])
        except OSError:
            return ""

    def set(self, value: str) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, value)
        try:   # new terminals see it without a sign-out, as [Environment]::SetEnvironmentVariable does
            import ctypes
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)
        except (OSError, AttributeError):   # no user32 (not Windows): the next sign-in sees it
            pass


def _same_dir(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(a.strip().strip('"'))) == os.path.normcase(os.path.normpath(str(b)))


def path_steps(home: Path, user_path=None, windows: bool | None = None) -> list[Step]:
    """The launcher on the PATH: <BRAIN_HOME>\\bin out of the user PATH (Windows), else ~/.local/bin/brain when it
    links into BRAIN_HOME."""
    windows = os.name == "nt" if windows is None else windows
    if windows:
        if user_path is None and _under_test():
            return []
        up = user_path or WindowsUserPath()
        bin_dir = home / "bin"
        parts = [p for p in up.get().split(";") if p]
        kept = [p for p in parts if not _same_dir(p, bin_dir)]
        if len(kept) == len(parts):
            return []
        return [Step("path", str(bin_dir), "remove", _line("remove", f"{bin_dir} from the user PATH"),
                     lambda: up.set(";".join(kept)) or "")]
    link = Path.home() / ".local" / "bin" / "brain"
    if not link.is_symlink():
        return []
    target = Path(os.readlink(link))
    if not _inside(target if target.is_absolute() else link.parent / target, home):
        return []
    return [Step("path", str(link), "remove", _line("remove", f"{link} (the launcher's link)"), lambda: _unlink(link))]


# --- the stores ---------------------------------------------------------------------------------------------------

def _inside(p: Path, home: Path) -> bool:
    try:
        p.resolve().relative_to(home.resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_link(p: Path) -> bool:
    """A symbolic link, or a Windows junction (its reparse tag: Path.is_junction is Python 3.12's)."""
    if p.is_symlink():
        return True
    try:
        return getattr(os.lstat(p), "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1)
    except OSError:
        return False


def _unlink(p: Path) -> str:
    try:
        if p.is_dir() and not p.is_symlink():
            os.rmdir(p)   # a junction: the link only
        else:
            p.unlink()
        return ""
    except OSError as exc:
        return str(exc)


def remove(p: Path, home: Path) -> str:
    """``p`` removed, "" or why not: a link or a junction has only itself removed, a folder that resolves outside
    BRAIN_HOME is refused (never followed)."""
    if not (p.exists() or p.is_symlink()):
        return ""
    if _is_link(p):
        return _unlink(p)
    if not _inside(p, home):
        return f"{p} resolves outside {home}: not removed"
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return ""
    except OSError as exc:
        return str(exc)


def _store_of(name: str) -> tuple[str, classes.Known] | None:
    """The engine store a top-level name of BRAIN_HOME is (a write's leftover: its base's store)."""
    base = classes.HOME_TRANSIENT.split(name)[0] if classes.HOME_TRANSIENT.search(name) else name
    for store, k in classes.ENGINE_STORES.items():
        if k.path == f"$BRAIN_HOME/{base}":
            return store, k
    return None


def _within(child: Path, parent: Path) -> bool:
    """``child`` is ``parent`` or under it (resolved)."""
    try:
        c, p = child.resolve(), parent.resolve()
    except OSError:
        return False
    return c == p or p in c.parents


def _running_from(p: Path) -> bool:
    """This command runs from ``p``: its interpreter's venv (sys.prefix) or its launcher (sys.argv[0], the copy in
    <BRAIN_HOME>\\bin that Windows holds while it runs)."""
    return any(_within(Path(x), p) for x in (sys.prefix, sys.argv[0] if sys.argv and sys.argv[0] else sys.prefix))


def home_refusal(home: Path) -> str:
    """Why ``home`` is not a BRAIN_HOME the purge may empty ('' when it is): a filesystem root, the user's home or a
    folder above it, a folder that holds Claude Code's transcripts or the personal brain, or one that holds none of
    the engine's stores (a BRAIN_HOME set to the wrong folder would otherwise lose everything in it)."""
    if not home.is_absolute():
        return f"BRAIN_HOME {home} is not an absolute path"
    if home.resolve().parent == home.resolve():
        return f"BRAIN_HOME {home} is a filesystem root"
    personal = paths.personal_root()
    for what, other in (("the user's home", Path.home()), ("Claude Code's transcripts", paths.projects_dir()),
                        ("the personal brain", personal)):
        if other is not None and _within(Path(other), home):
            return f"BRAIN_HOME {home} holds {what} ({other})"
    try:
        names = {p.name for p in home.iterdir()}
    except OSError:
        return ""   # absent: nothing to remove there
    if names and not any(_store_of(n) for n in names):
        return f"BRAIN_HOME {home} holds none of the engine's stores: not a brain's home"
    return ""


def _nested(store: str) -> list[str]:
    """The engine stores inside a top-level one (the collector's log inside stacks)."""
    top = classes.ENGINE_STORES[store].path + "/"
    return sorted(n for n, k in classes.ENGINE_STORES.items() if k.path.startswith(top))


def _cleanup_command(p: Path) -> str:
    return (f"Remove-Item -Recurse -Force '{p}'" if os.name == "nt" else f"rm -rf '{p}'")


def _held(store: str, known, confirmed: set[str]) -> bool:
    """A store nothing else keeps, or a name no store covers, not yet confirmed. ``all`` releases the registry's
    stores only: a name no store covers is confirmed by its own name."""
    if known is not None and known.format not in HELD_FORMATS:
        return False
    return store not in confirmed and (known is None or ALL not in confirmed)


def store_step(entry: Path, home: Path, purge: bool, confirmed: set[str]) -> Step | None:
    """What becomes of one top-level entry of BRAIN_HOME."""
    found = _store_of(entry.name)
    store, known = found if found else (entry.name, None)
    fmt = known.format if known else "unknown"
    inner = _nested(store) if known else []
    what = f"{entry} ({store}, {fmt}{', with ' + ', '.join(inner) if inner else ''})"
    if fmt == "install":
        if _running_from(entry):
            return Step("store", store, "left", _line("left", f"{what}: this command runs from it; once it has "
                                                              f"exited: {_cleanup_command(entry)}"))
        return Step("store", store, "remove", _line("remove", what), lambda: remove(entry, home))
    if not purge:
        return None
    if _held(store, known, confirmed):
        why = "nothing else keeps it" if known else "no store covers it (sealed by default; all does not cover it)"
        return Step("store", store, "held", _line("held", f"{what}: {why}; --confirm-recovery {store} once its "
                                                          "recovery copy is confirmed (brain vault seal, brain spool "
                                                          "push)"))
    return Step("store", store, "remove", _line("remove", what), lambda: remove(entry, home))


def store_steps(home: Path, purge: bool, confirmed: set[str]) -> list[Step]:
    """Each top-level entry of BRAIN_HOME: the install stores always, the rest with --purge."""
    try:
        entries = sorted(home.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    steps = [store_step(e, home, purge, confirmed) for e in entries]
    return [s for s in steps if s is not None]


def _key_step(ks, key: str, what: str, confirmed: set[str]) -> Step:
    from . import keystore
    line = f"keystore {ks.name}: {keystore.SERVICE}/{key} ({what})"
    if ks.name == "file":
        return Step("keystore", KEYSTORE, "left", _line("left", f"{line}: a mounted identity file, read only: remove "
                                                                "it where it is mounted"))
    if KEYSTORE not in confirmed and ALL not in confirmed:
        return Step("keystore", KEYSTORE, "held", _line("held", f"{line}: the vault's sealed copies then open with the "
                                                                "recovery key only; --confirm-recovery keystore once "
                                                                "it is at hand"))
    return Step("keystore", KEYSTORE, "remove", _line("remove", line),
                lambda: "" if ks.delete(key) else "the keystore did not delete it")


def keystore_steps(cfg: config.Config, confirmed: set[str], backend=None) -> list[Step]:
    """This machine's device key in its keystore (brain.vault), and the previous one of a rotation not finished: held
    until their recovery is confirmed (the vault's sealed copies then open with the recovery key only)."""
    from . import keystore, vault
    try:
        ks = backend if backend is not None else keystore.backend()
        keys = [(k, w) for k, w in ((vault.keystore_key(cfg), "this machine's device key"),
                                    (vault.previous_key(cfg), "its previous key, a rotation not finished"))
                if ks is not None and ks.get(k) is not None]
    except (keystore.KeystoreError, OSError) as exc:   # refused (under pytest) or broken: said, nothing removed
        return [Step("keystore", KEYSTORE, "left", _line("left", f"the keystore could not be read ({exc})"))]
    return [_key_step(ks, k, w, confirmed) for k, w in keys]


def other_steps(cfg: config.Config, home: Path, run=_run) -> list[Step]:
    """What the installer set up outside BRAIN_HOME that the purge leaves, each with the command that removes it: the
    personal brain's merge driver (it runs <BRAIN_HOME>'s launcher) and Claude Code's user settings."""
    steps = []
    root = paths.personal_root()
    if root is not None and not (run is _run and _under_test()):
        r = run(["git", "-C", str(root), "config", "--get", "merge.brain.driver"])
        if getattr(r, "returncode", 1) == 0 and (r.stdout or "").strip():
            steps.append(Step("merge", str(root), "left", _line(
                "left", f"merge.brain.driver in {root}'s git config (it runs the launcher removed above): "
                        f"git -C {root} config --remove-section merge.brain")))
    settings = paths.projects_dir().parent / "settings.json"
    steps.append(Step("settings", str(settings), "keep", _line(
        "keep", f"{settings}: the permission rules and the telemetry settings the installer added are Claude "
                "Code's settings now (taken out by hand)")))
    return steps


# --- the plan and its apply ---------------------------------------------------------------------------------------

def plan(cfg: config.Config, purge: bool = False, confirmed: set[str] | None = None, *, run=_run,
         claude: str | None = None, user_path=None, keystore_backend=None) -> list[Step]:
    """Every step, in the order they apply: what runs the command first (schedules, plugin, PATH), then BRAIN_HOME.
    A BRAIN_HOME the purge may not empty (:func:`home_refusal`) gives one refused step and nothing else."""
    confirmed = set(confirmed or ())
    home = paths.brain_home()
    why = home_refusal(home)
    if why:
        return [Step("home", str(home), "refused", _line("refused", f"{why}: nothing planned"))]
    steps = [*schedule_steps(run), *plugin_steps(cfg, run, claude), *path_steps(home, user_path)]
    if purge:
        steps += keystore_steps(cfg, confirmed, keystore_backend)
    steps += store_steps(home, purge, confirmed)
    if purge:
        steps.append(Step("home", str(home), "remove", _line("remove", f"{home} once empty"),
                          lambda: _rmdir_if_empty(home)))
    else:
        steps.append(Step("home", str(home), "keep", _line("keep", f"{home}: the data stores (--purge removes them)")))
    steps += other_steps(cfg, home, run)
    steps.append(Step("transcripts", str(paths.projects_dir()), "keep",
                      _line("keep", f"{paths.projects_dir()}: Claude Code's transcripts, not the brain's")))
    return steps


KEPT = "kept: "   # an apply that left its target on purpose (BRAIN_HOME not empty): not a failure


def _rmdir_if_empty(home: Path) -> str:
    try:
        if not home.is_dir():
            return ""
        left = sorted(p.name for p in home.iterdir())
        if left:
            return f"{KEPT}not empty ({', '.join(left)}); once they are gone: {_cleanup_command(home)}"
        home.rmdir()
        return ""
    except OSError as exc:
        return str(exc)


def unknown_names(confirmed: set[str]) -> list[str]:
    """The --confirm-recovery names that are neither a top-level engine store, the keystore, all, nor an entry of
    BRAIN_HOME (a store inside another, the collector in stacks, is confirmed by the one that holds it)."""
    try:
        present = {_store_of(p.name)[0] if _store_of(p.name) else p.name for p in paths.brain_home().iterdir()}
    except OSError:
        present = set()
    top = {n for n, k in classes.ENGINE_STORES.items()
           if k.path.startswith("$BRAIN_HOME/") and "/" not in k.path[len("$BRAIN_HOME/"):]}
    known = top | {KEYSTORE, ALL} | present
    return sorted(n for n in confirmed if n not in known)


def apply(steps: list[Step]) -> list[tuple[Step, str]]:
    """Each removal applied in order, with its outcome ("done", "kept: why" or "failed: why"); held, left and kept
    steps not. A step that raises fails alone: the others still run and the report is whole."""
    out = []
    for s in steps:
        if s.action != "remove" or s.apply is None:
            out.append((s, ""))
            continue
        try:
            why = s.apply()
        except Exception as exc:   # Justified: one trace that fails must not leave the rest undone and unreported
            why = f"{type(exc).__name__}: {exc}"
        out.append((s, "done" if not why else why if why.startswith(KEPT) else f"failed: {why}"))
    return out
