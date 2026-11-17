"""Where a release stands, and the checks after its install, in one command each (wi-brain-release-status;
docs/release.md, « Where a release stands »).

``brain release status [X.Y.Z]`` reads six steps of a release, each done, pending or unknown, then names the next
step and whose it is:

1. **wave**: the planning brain's wave of that release, closed (``reached``: ``brain wave close``) or not;
2. **version**: the engine's version PR, merged (or its tag cut), open, or not started (``gh pr list`` on the engine
   repo, the PRs whose title names the version and « release »);
3. **tag**: the release tag on the engine repo (``git ls-remote``), and signed by a releaser of the brain's
   ``allowed_signers`` (brain.tagsig, the tag fetched into a temporary folder);
4. **pin**: the planning brain's ``config.json`` ``engine.pin`` on its default branch at the tag (merged), else in
   the checkout (a pin branch), else an open PR whose title names the version and the pin;
5. **install**: this machine's engine (the one running) at the version;
6. **verified**: this machine's last ``brain release verify`` passed at that version.

The version is the one given, else the lowest live wave's release above the pin, else the pin's own. Every read
is bounded and none writes; ``--offline`` reads no network (the version, tag and pin PR steps say unknown). One
machine's install and verify are known here only: each machine runs ``brain release verify``.

``brain release verify`` runs the after-install checks in one call, each in its own process, its output in a log
file under ``$BRAIN_HOME/release/`` and one line on screen: the engine against the pin (``brain --version`` of this
interpreter), the dependency probes (``brain probes``), the store classes (``brain classes --check``) and the
brain's own tests (``python -m pytest tests -q``, when the brain has a ``tests`` folder and this interpreter has
pytest; ``--no-tests`` skips them). It writes ``$BRAIN_HOME/release/verified.json`` (derived: rebuilt by the next
verify), which ``status`` reads. Exit 0 when every check passed, 1 when one failed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__

Runner = Callable[..., subprocess.CompletedProcess]
V = 1                               # verified.json's version
FOLDER = "release"                  # $BRAIN_HOME/release: the last verify, its logs (classes.ENGINE_STORES)
RECORD = "verified.json"
TIMEOUT_S = 60                      # a read (gh, git) or a quick check
TESTS_TIMEOUT_S = 3600              # the brain's own tests
DONE, PENDING, UNKNOWN, NA = "done", "pending", "unknown", "n/a"
VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)$")


class StatusError(ValueError):
    """Nothing to report on: no planning brain, or no version given or found."""


@dataclass
class Step:
    name: str
    state: str          # done, pending, unknown or n/a
    detail: str
    owner: str = ""     # whose the next move is while it is pending
    next: str = ""      # that move


def key(version: str) -> tuple[int, int, int] | None:
    m = VERSION.match(str(version or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def bare(version: str) -> str:
    k = key(version)
    if not k:
        raise StatusError(f"{version!r} is not a version (X.Y.Z or vX.Y.Z)")
    return ".".join(map(str, k))


def _run(runner: Runner, argv: list[str], cwd: Path | None = None, timeout: float = TIMEOUT_S):
    """The program's (returncode, stdout, stderr); (None, '', why) when it could not run or timed out."""
    try:
        r = runner(argv, cwd=str(cwd) if cwd else None, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, "", f"{Path(argv[0]).name} timed out after {timeout:.0f}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", f"{Path(argv[0]).name} could not run ({exc.__class__.__name__})"
    return r.returncode, r.stdout or "", r.stderr or ""


# --- the inputs ---

def config_of(root: Path):
    """The planning brain's own config.json (not $BRAIN_CONFIG's, as brain release pin reads it); an empty one when
    it has none or it cannot be read."""
    from . import config, release
    try:
        return release._config_of(root)
    except release.ReleaseError:
        return config.Config(None, root.resolve(), {})


def engine_of(cfg) -> dict:
    eng = cfg.data.get("engine") if isinstance(cfg.data, dict) else None
    return eng if isinstance(eng, dict) else {}


def pin_of(root: Path, runner: Runner = subprocess.run) -> tuple[str | None, str | None]:
    """(the pin on the planning brain's default branch, the pin in its checkout): config.json engine.pin of
    origin/<default>, read with git show (None when git cannot), and of the working copy."""
    from . import release
    pin = engine_of(config_of(root)).get("pin")
    local = pin if isinstance(pin, str) and pin else None
    branch = release._default_branch(root, runner) or "main"
    rc, out, _ = _run(runner, ["git", "-C", str(root), "show", f"origin/{branch}:config.json"])
    main = None
    if rc == 0:
        try:
            eng = json.loads(out.lstrip("﻿")).get("engine")
            main = eng.get("pin") if isinstance(eng, dict) and isinstance(eng.get("pin"), str) else None
        except (ValueError, AttributeError):
            main = None
    return main, local


def default_version(store: Path, root: Path, pin: str | None) -> str:
    """The lowest live wave's release above the pin, else the pin's own version."""
    from . import waves
    floor = key(pin or "") or (0, 0, 0)
    found = []
    if (store / "nodes").is_dir():
        plan = waves.load(store, root)
        found = sorted(k for k in (key(plan.label(w)) for w in plan.live) if k and k > floor)
    if found:
        return ".".join(map(str, found[0]))
    if key(pin or ""):
        return bare(pin)
    raise StatusError("no version given, no wave above the pin and no pin: name the version (X.Y.Z)")


def _prs(runner: Runner, cwd: Path | None, repo: str | None, version: str, state: str) -> tuple[list[dict], str]:
    """The PRs (gh pr list --state STATE) whose title names the version; ([], why) when gh cannot list them."""
    argv = ["gh", "pr", "list", "--state", state, "--limit", "100", "--json", "number,title,state,headRefName",
            "--search", f"{version} in:title"]
    if repo:
        argv += ["--repo", repo]
    rc, out, err = _run(runner, argv, cwd)
    if rc != 0:
        return [], ("gh pr list failed: " + ((err or out).strip().splitlines() or ["no output"])[-1]) if rc else err
    try:
        prs = json.loads(out or "[]")
    except ValueError:
        return [], "gh pr list gave no JSON"
    named = re.compile(rf"(?<![\d.])v?{re.escape(version)}(?![\d]|\.\d)")
    return [p for p in prs if isinstance(p, dict) and named.search(str(p.get("title") or ""))], ""


def record_file() -> Path:
    from . import paths
    return paths.brain_home() / FOLDER / RECORD


def last_verify() -> dict:
    """This machine's last verify ({} when there is none, or it cannot be read)."""
    try:
        data = json.loads(record_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# --- the steps ---

def wave_step(store: Path, root: Path, version: str) -> Step:
    from . import waves
    if not (store / "nodes").is_dir():
        return Step("wave", UNKNOWN, f"no graph store at {store}")
    plan = waves.load(store, root)
    wid = plan.resolve(version)
    if not wid:
        return Step("wave", NA, f"no wave of {version}")
    if plan.status(wid) == "reached":
        return Step("wave", DONE, f"{wid} closed")
    return Step("wave", PENDING, f"{wid} open ({len(plan.items_of(wid))} item(s))", "coordinator",
                f"close it: brain wave close {wid}, once its items are done or carried")


def version_step(version: str, repo: str, tagged: bool, offline: bool, runner: Runner) -> Step:
    if tagged:
        return Step("version", DONE, f"v{version} tagged: the version PR is merged")
    if offline:
        return Step("version", UNKNOWN, "offline", "coordinator", f"brain release status {version} online")
    prs, why = _prs(runner, None, repo, version, "all")
    prs = [p for p in prs if "release" in str(p.get("title") or "").lower()]   # « Release X.Y.Z: theme »
    if why:
        return Step("version", UNKNOWN, why, "coordinator", f"gh pr list --repo {repo} --search '{version}'")
    merged = [p for p in prs if p.get("state") == "MERGED"]
    if merged:
        return Step("version", DONE, f"#{merged[0]['number']} merged")
    opened = [p for p in prs if p.get("state") == "OPEN"]
    if opened:
        return Step("version", PENDING, f"#{opened[0]['number']} open: {opened[0]['title']}", "coordinator",
                    f"review and merge #{opened[0]['number']}")
    return Step("version", PENDING, "no version PR yet", "coordinator",
                f"brain release prepare {version} --theme \"...\" in the engine checkout, then its PR")


def tag_step(root: Path, version: str, repo: str, offline: bool, owner: str, runner: Runner) -> tuple[Step, bool]:
    """The tag step, and whether the tag exists."""
    from . import tagsig, update
    tag = f"v{version}"
    if offline:
        return Step("tag", UNKNOWN, "offline"), False
    try:
        tags = update.remote_tags(repo, runner=runner)
    except OSError as exc:
        return Step("tag", UNKNOWN, str(exc)), False
    if tag not in tags:
        return Step("tag", PENDING, f"{tag} not on {repo}", owner,
                    f"once the version PR is merged: git tag -s {tag} on it, then git push origin {tag}"), False
    v = tagsig.verify(root, repo, tag, runner=runner)
    if v.get("status") == tagsig.VERIFIED:
        return Step("tag", DONE, f"{tag} signed by {v.get('signer')}"), True
    return Step("tag", PENDING, f"{tag} cut, not verified: {v.get('why') or v.get('status')}", owner,
                "sign it with a releaser key of allowed_signers (docs/release.md, « 3. The tag »)"), True


def pin_step(root: Path, version: str, pins: tuple[str | None, str | None], offline: bool, runner: Runner) -> Step:
    tag, (main, local) = f"v{version}", pins
    want = key(version)
    if key(main or "") and key(main) >= want:
        return Step("pin", DONE, f"engine.pin {main} on the default branch")
    if offline:
        return Step("pin", UNKNOWN if local != tag else PENDING, f"pin {main or 'none'} on the default branch"
                    + (f", {local} in this checkout" if local == tag else ""), "coordinator",
                    f"brain release pin {tag} --write in a pin branch, then its PR")
    prs, why = _prs(runner, root, None, version, "open")
    pin_prs = [p for p in prs if "pin" in str(p.get("title") or "").lower()]
    if pin_prs:
        return Step("pin", PENDING, f"#{pin_prs[0]['number']} open: {pin_prs[0]['title']}", "coordinator",
                    f"review and merge #{pin_prs[0]['number']}")
    if local == tag:
        return Step("pin", PENDING, f"{tag} in this checkout, no PR yet", "coordinator", "commit it and open its PR")
    return Step("pin", PENDING, f"pin {main or 'none'} on the default branch" + (f" ({why})" if why else ""),
                "coordinator", f"brain release pin {tag} --write in a pin branch of the planning brain, then its PR")


def install_step(cfg, version: str, installed: str) -> Step:
    have, want = key(installed), key(version)
    if have and have >= want:
        return Step("install", DONE, f"brain {installed} on this machine")
    name = engine_of(cfg).get("installer")
    name = name if isinstance(name, str) and name else None
    how = f"{name} -Apply (its plan first), then restart the sessions" if name else "brain update, then y"
    return Step("install", PENDING, f"brain {installed} on this machine", "owner", how)


def verify_step(version: str, rec: dict) -> Step:
    if rec.get("version") == version and rec.get("ok") is True:
        return Step("verified", DONE, f"verified {rec.get('at', '')}")
    if rec.get("version") == version:
        failed = [c.get("name") for c in rec.get("checks") or [] if isinstance(c, dict) and not c.get("ok")]
        return Step("verified", PENDING, f"failed {rec.get('at', '')}: {', '.join(map(str, failed))}", "session",
                    "fix what failed (its log under $BRAIN_HOME/release), then brain release verify")
    return Step("verified", PENDING, "not verified on this machine", "session", "brain release verify")


def status(root: Path, version: str = "", *, store: Path | None = None, offline: bool = False,
           installed: str = __version__, runner: Runner = subprocess.run, rec: dict | None = None) -> dict:
    """{version, steps, next}: the six steps of a release and the first pending one (:data:`DONE` all through: none)."""
    from . import config, update
    store = store or root / "notes" / "graph"
    cfg = config_of(root)
    pins = pin_of(root, runner)
    version = bare(version) if version else default_version(store, root, pins[0] or pins[1])
    repo = engine_of(cfg).get("repo") or update.ENGINE_REPO
    owner = config.display_name(cfg) if cfg.data else "owner"
    tag, tagged = tag_step(root, version, repo, offline, owner, runner)
    steps = [wave_step(store, root, version), version_step(version, repo, tagged, offline, runner), tag,
             pin_step(root, version, pins, offline, runner), install_step(cfg, version, installed),
             verify_step(version, last_verify() if rec is None else rec)]
    nxt = next((s for s in steps if s.state == PENDING), None)
    return {"version": version, "repo": repo, "root": str(root), "steps": [asdict(s) for s in steps],
            "next": asdict(nxt) if nxt else None}


def lines(rep: dict) -> list[str]:
    out = [f"release {rep['version']} ({rep['repo']})"]
    out += [f"  {s['name']:<9}{s['state']:<9}{s['detail']}" for s in rep["steps"]]
    n = rep["next"]
    out.append(f"next     {n['name']}: {n['next']} ({n['owner']})" if n else "next     none: the release is out here")
    return out


# --- verify ---

@dataclass
class Check:
    name: str
    ok: bool
    rc: int | None
    why: str
    log: str = ""


def checks(root: Path, *, tests: bool = True, python: str = sys.executable) -> list[tuple[str, list[str], Path, float]]:
    """(name, argv, cwd, timeout) of each after-install check; this interpreter runs each (the engine installed)."""
    brain = [python, "-m", "brain"]
    out = [("version", [*brain, "--version"], root, TIMEOUT_S),
           ("probes", [*brain, "probes"], root, TIMEOUT_S * 3),
           ("classes", [*brain, "--root", str(root), "classes", "--check"], root, TIMEOUT_S * 3)]
    if tests and (root / "tests").is_dir():
        out.append(("tests", [python, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"], root,
                    TESTS_TIMEOUT_S))
    return out


def _has_pytest(python: str, runner: Runner) -> bool:
    rc, _, _ = _run(runner, [python, "-c", "import pytest"])
    return rc == 0


def _version_verdict(out: str, pin: str | None) -> tuple[bool, str]:
    """``brain --version``'s output against the pin: (ok, why)."""
    got = (out.strip().split() or [""])[-1]
    if not key(got):
        return False, f"no version in {out.strip()!r}"
    if pin is None:
        return True, f"brain {got}, no pin"
    return (True, "") if key(got) == key(pin) else (False, f"brain {got}, the pin is {pin}")


def _check(name: str, argv: list[str], cwd: Path, timeout: float, folder: Path, pin: str | None,
           runner: Runner) -> Check:
    """One check run, its output written to <folder>/<name>.log (no log when it cannot be written)."""
    rc, out, err = _run(runner, argv, cwd, timeout)
    log = folder / f"{name}.log"
    try:
        log.write_text(f"$ {' '.join(argv)}\n{out}{err}", encoding="utf-8")
    except OSError:
        log = None
    if rc is None:
        ok, why = False, err.strip()
    elif rc != 0:
        ok, why = False, f"exit {rc}"
    else:
        ok, why = _version_verdict(out, pin) if name == "version" else (True, "")
    return Check(name, ok, rc, why, str(log) if log else "")


def _machine() -> str:
    from . import machine
    try:
        return machine.name()
    except (OSError, ValueError):  # the machine's name is a label only
        return ""


def verify(root: Path, *, tests: bool = True, python: str = sys.executable, runner: Runner = subprocess.run,
           now: datetime | None = None, say: Callable[[str], object] = lambda line: None) -> dict:
    """Run the checks, each one's output into its log; the record, written to :func:`record_file`."""
    folder = record_file().parent
    folder.mkdir(parents=True, exist_ok=True)
    pin = engine_of(config_of(root)).get("pin")
    pin = pin if isinstance(pin, str) and pin else None
    if tests and (root / "tests").is_dir() and not _has_pytest(python, runner):
        say("tests    skipped: pytest is not installed in this interpreter (pip install pytest, or --no-tests)")
        tests = False
    done = []
    for name, argv, cwd, timeout in checks(root, tests=tests, python=python):
        c = _check(name, argv, cwd, timeout, folder, pin, runner)
        done.append(c)
        say(f"{name:<9}{'OK' if c.ok else 'FAIL'}  {c.why or 'passed'}" + (f"  ({c.log})" if c.log and not c.ok
                                                                            else ""))
    at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec = {"v": V, "version": __version__, "pin": pin, "at": at, "machine": _machine(), "root": str(root),
           "ok": all(c.ok for c in done), "checks": [asdict(c) for c in done]}
    _write(rec, say)
    return rec


def _write(rec: dict, say: Callable[[str], object]) -> None:
    from . import stateio
    try:
        stateio.write_atomic(record_file(), json.dumps(rec, indent=1, sort_keys=True) + "\n")
    except OSError as exc:
        say(f"record   not written ({exc.__class__.__name__}): brain release status will not see this verify")


# --- the commands ---

def main_status(args) -> int:
    from . import release
    root = release.planning_root(args)
    try:
        if root is None:
            raise StatusError("no planning brain: --planning names it (or --root, or a personal brain)")
        rep = status(root, args.version or "", store=Path(args.store) if args.store else None,
                     offline=args.offline)
    except StatusError as exc:
        print(f"brain release status: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=2) if args.json else "\n".join(lines(rep)))
    return 0


def main_verify(args) -> int:
    from . import release
    root = release.planning_root(args)
    if root is None:
        print("brain release verify: no planning brain: --planning names it (or --root, or a personal brain)",
              file=sys.stderr)
        return 2
    rec = verify(root, tests=args.tests, say=(lambda line: None) if args.json else print)
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        print(f"verify   {'passed' if rec['ok'] else 'FAILED'}: brain {rec['version']}, pin {rec['pin'] or 'none'}, "
              f"recorded in {record_file()}")
    return 0 if rec["ok"] else 1
