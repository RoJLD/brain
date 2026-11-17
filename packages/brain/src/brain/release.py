"""The version PR's mechanical part in one command (wi-brain-release-prepare; docs/release.md, « 2. The version PR »).

``brain release prepare X.Y.Z --theme T`` prints the plan of the engine checkout's version PR, step by step, and
``--write`` runs it, in this order, stopping at the first step that fails:

1. **versions**: both ``__version__``, the research-graph pin, ``brain_version``, the install lines of the READMEs,
   docs/install.md and docs/pilot.md, the stranger test's default ``--ref`` and its usage line: only the patterns that
   name the version being replaced (``@vP``, ``--branch vP``, ``blob/vP``, ``here vP``, ``# brain P``...), so that a
   past release's mention in prose stays;
2. **freeze**: ``installer/freeze_store.py vP``, the store and the formats the previous release wrote (skipped when its
   store is already frozen, or with ``--no-freeze``);
3. **changelog**: ``installer/changelog.py compile X.Y.Z --theme T --write``, the fragments into the dated sections;
4. **features** and **reference**: ``FEATURES.md`` and ``docs/reference/`` rendered from the planning brain (the
   public render: ``brain features render --repo R --out <checkout>/FEATURES.md --write`` and ``brain reference --public``), when
   one is found (``--planning``, else the personal brain), both with ``--force``: they run with the release's engine,
   ahead of the planning brain's ``engine.pin`` until its pin PR, which ``views.strict`` would otherwise refuse;
5. **check**: ``installer/release_check.py`` (with ``--store`` when the planning brain's store is given), then its
   ``--preview``.

What stays a model's, said at the end: the ``### Upgrade`` section's numbered steps and their prose, the pilot page's
line of what each release brought, and the review. Every step runs a program with its arguments as a list, never a
shell: a theme with quotes, ``$`` or ``%`` reaches the script as typed.

``brain release pin vX.Y.Z`` (wi-brain-release-pin) plans the planning brain's pin PR once the tag is cut, and
``--write`` writes its files, in a branch of that brain (refused on its default branch: origin/HEAD, else asked of
the remote, and main or master). The brain is ``--planning``, else ``--root``, else the checkout holding the current
folder (a pin branch's worktree), else the personal brain. The shim is written first, then ``config.json``, each
atomically, each said as it is written: a failure between them is told, and a rerun plans what is left.

- **pin**: ``config.json`` ``engine.pin`` moved to the tag (brain.update.rewrite_json: its keys, order, indent, line
  endings and BOM kept); a tag before the pin is refused (a rollback is the owner's);
- **stores**: for a brain that declares ``classes:``, the engine stores it leaves at their default
  (``brain classes --suggest``'s lines), added to ``classes.stores`` in the same write; they are this engine's, so the
  plan says when it is not the tag's;
- **shim**: the adapter plugin's transitional ``plugins/<adapters.claude.plugin>/brain/__init__.py``, when the brain
  keeps one: its ``PIN = "vX.Y.Z"`` line follows the pin;
- **upgrade**: the tag's CHANGELOG sections after the pin (read from the code host, brain.update.changelog), the
  ``### Upgrade`` steps that name ``config.json`` listed, to read and make by hand (the standard « Install the
  engine » step aside: the pin PR is that step);
- **waiting**: the brain's open PRs (``gh pr list``) whose title or body names the version: the lot PRs that waited
  for the tag.

Then by hand: ``brain sync`` with the new engine, the ADR, the journal, the PR.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

VERSION = re.compile(r"\d+\.\d+\.\d+")
INIT = "packages/brain/src/brain/__init__.py"
RG_INIT = "src/research_graph/__init__.py"
STORES = "packages/brain/tests/fixtures/stores"
INSTALLER = "packages/brain/installer"
BY_HAND = ["the ### Upgrade section of packages/brain/CHANGELOG.md: number its steps (the standard ones first) and "
           "write their reasons, then « Nothing to run for the rest » (docs/release.md, « The version PR »)",
           "docs/pilot.md: the line of what each release brought, with this one's",
           "the review of the version PR, then brain review stamp"]

Runner = Callable[..., subprocess.CompletedProcess]


class ReleaseError(ValueError):
    """A version or a checkout that cannot be prepared (exit 2)."""


def _patterns(prev: str, new: str) -> list[tuple[str, str]]:
    p = re.escape(prev)
    return [(rf'__version__ = "{p}"', f'__version__ = "{new}"'), (rf"brain_version={p}\b", f"brain_version={new}"),
            (rf"@v{p}\b", f"@v{new}"), (rf"--branch v{p}\b", f"--branch v{new}"), (rf"blob/v{p}\b", f"blob/v{new}"),
            (rf"\(here v{p}\)", f"(here v{new})"), (rf"# brain {p}\b", f"# brain {new}"),
            (rf"--ref v{p}\b", f"--ref v{new}"), (rf'default="v{p}"', f'default="v{new}"')]


VERSION_FILES = (INIT, RG_INIT, "packages/brain/pyproject.toml", "packages/brain/src/brain/adapters/claude/hooks/common.sh",
                 "README.md", "packages/brain/README.md", "docs/install.md", "docs/pilot.md",
                 f"{INSTALLER}/stranger_test.py")


@dataclass
class Edit:
    path: str
    count: int
    text: str        # the file's new text


@dataclass
class Step:
    name: str
    line: str                         # what the plan says
    state: str = "todo"               # todo, same, skip
    argv: list[str] = field(default_factory=list)   # the program a --write runs ([] for the file edits)
    edits: list[Edit] = field(default_factory=list)


def current_version(repo: Path) -> str:
    m = re.search(r'__version__ = "([^"]+)"', (repo / INIT).read_text(encoding="utf-8"))
    if not m:
        raise ReleaseError(f"{repo / INIT}: no __version__")
    return m.group(1)


def version_edits(repo: Path, prev: str, new: str) -> list[Edit]:
    """Each file of :data:`VERSION_FILES` whose version lines name ``prev``, with its new text."""
    out = []
    for rel in VERSION_FILES:
        f = repo / rel
        if not f.is_file():
            continue
        with f.open(encoding="utf-8", newline="") as fh:
            text = fh.read()
        count = 0
        for pat, repl in _patterns(prev, new):
            text, n = re.subn(pat, repl, text)
            count += n
        if count:
            out.append(Edit(rel, count, text))
    return out


def _version_key(v: str) -> tuple[int, ...]:
    if not VERSION.fullmatch(v):
        raise ReleaseError(f"{v!r}: not a version X.Y.Z")
    return tuple(int(x) for x in v.split("."))


def previous_version(repo: Path, runner: Runner = subprocess.run) -> str:
    """The release this version PR follows: the last tag vX.Y.Z reachable from HEAD, so that a second run after a
    partial --write still knows it; this checkout's __version__ where git names no tag."""
    try:
        r = runner(["git", "-C", str(repo), "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
                   capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        r = None
    tag = (r.stdout or "").strip() if r is not None and r.returncode == 0 else ""
    return tag[1:] if VERSION.fullmatch(tag[1:]) else current_version(repo)


def _compiled(repo: Path, version: str) -> bool:
    """The brain's CHANGELOG already holds this version's section (a compile ran: a second one would add another)."""
    f = repo / "packages" / "brain" / "CHANGELOG.md"
    return f.is_file() and any(line.startswith(f"## {version} ") for line in
                               f.read_text(encoding="utf-8").splitlines())


def plan(repo: Path, version: str, theme: str, *, planning: Path | None = None, store: str = "",
         repo_name: str = "brain", freeze: bool = True, python: str = sys.executable,
         brain: list[str] | None = None) -> tuple[str, list[Step]]:
    """(the previous version, the steps); ReleaseError on a version that does not move forward."""
    if not VERSION.fullmatch(version):
        raise ReleaseError(f"{version!r}: a version X.Y.Z (no v)")
    if not theme.strip():
        raise ReleaseError("--theme: the release's theme, for its CHANGELOG heading and its tag")
    prev = previous_version(repo)
    if _version_key(version) <= _version_key(prev):
        raise ReleaseError(f"{version} is not after the last release, {prev}")
    brain = brain or [python, "-m", "brain"]
    steps = []
    edits = version_edits(repo, prev, version)
    if edits:
        lines = "; ".join(f"{e.path} ({e.count})" for e in edits)
        steps.append(Step("versions", f"edit     versions {prev} -> {version}: {lines}", edits=edits))
    else:
        steps.append(Step("versions", f"same     versions: no line names {prev} any more", "same"))
    frozen = (repo / STORES / f"v{prev}").is_dir()
    freeze_argv = [python, f"{INSTALLER}/freeze_store.py", f"v{prev}"]
    steps.append(Step("freeze", f"same     freeze: the store v{prev} wrote is frozen ({STORES}/v{prev})", "same")
                 if frozen else Step("freeze", "skip     freeze: --no-freeze (release_check refuses a version PR "
                                     f"without {STORES}/v{prev})", "skip") if not freeze
                 else Step("freeze", f"run      freeze: {' '.join(freeze_argv[1:])} (installs v{prev} in a fresh "
                                     "venv)", argv=freeze_argv))
    steps.append(Step("changelog", f"same     changelog: packages/brain/CHANGELOG.md holds ## {version} already", "same")
                 if _compiled(repo, version) else
                 Step("changelog", f"run      changelog: compile {version} --theme {theme!r} --write",
                      argv=[python, f"{INSTALLER}/changelog.py", "--repo", str(repo), "compile", version, "--theme",
                            theme, "--write"]))
    if planning is None:
        steps.append(Step("features", "skip     features and reference: no planning brain (--planning, or a personal "
                                      "brain): render FEATURES.md and docs/reference/ from it by hand", "skip"))
    else:
        steps.append(Step("features", f"run      features: FEATURES.md rendered from {planning} (the public render)",
                          argv=[*brain, "--root", str(planning), "features", "render", "--repo", repo_name, "--out",
                                str(repo / "FEATURES.md"), "--write", "--force"]))
        steps.append(Step("reference", f"run      reference: docs/reference/ rendered from {planning}",
                          argv=[*brain, "--root", str(planning), "reference", "--public", "--repo", repo_name,
                                "--out", str(repo / "docs" / "reference"), "--write", "--force"]))
    check = [python, f"{INSTALLER}/release_check.py", "--repo", str(repo)] + (["--store", store] if store else [])
    steps.append(Step("check", "run      check: release_check.py" + (f" --store {store}" if store else "")
                      + ", then its --preview", argv=check))
    return prev, steps


def _run(argv: list[str], repo: Path, runner: Runner) -> tuple[int, str]:
    r = runner(argv, cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def apply(repo: Path, steps: list[Step], runner: Runner = subprocess.run) -> list[dict]:
    """Each step run in order; the first that fails stops the rest (they are said, not run)."""
    out, failed = [], False
    for st in steps:
        if failed or st.state != "todo":
            out.append({"step": st.name, "outcome": "not run" if failed and st.state == "todo" else st.state})
            continue
        if st.edits:
            for e in st.edits:
                with (repo / e.path).open("w", encoding="utf-8", newline="") as fh:   # its line endings kept
                    fh.write(e.text)
            out.append({"step": st.name, "outcome": "done"})
            continue
        code, text = _run(st.argv, repo, runner)
        out.append({"step": st.name, "outcome": "done" if code == 0 else f"failed (exit {code})",
                    "output": text[-1500:]})
        if st.name == "check" and code == 0:
            pcode, ptext = _run([*st.argv, "--preview"], repo, runner)
            out.append({"step": "preview", "outcome": "done" if pcode == 0 else f"failed (exit {pcode})",
                        "output": ptext[-1500:]})
        failed = code != 0
    return out


def find_repo(start: Path) -> Path:
    """The engine checkout holding ``start``: the nearest folder with packages/brain/src/brain/__init__.py."""
    for d in (start, *start.parents):
        if (d / INIT).is_file():
            return d
    raise ReleaseError(f"{start}: not in an engine checkout (no {INIT} above it): --repo names one")


def _where(args) -> tuple[Path, Path | None, str]:
    """(the engine checkout, the planning brain, the store release_check reads); ReleaseError without a checkout."""
    from . import paths
    repo = Path(args.repo).resolve() if args.repo else find_repo(Path.cwd())
    if not (repo / INIT).is_file():
        raise ReleaseError(f"{repo}: no {INIT} (--repo names the engine checkout)")
    planning = Path(args.planning).resolve() if args.planning else (
        Path(args.root).resolve() if getattr(args, "root", None) else paths.personal_root())
    if planning is not None and not ((planning / "config.json").is_file() or (planning / "notes" / "graph").is_dir()):
        raise ReleaseError(f"{planning}: no brain there (no config.json, no notes/graph): --planning names the brain "
                           "that plans the releases")
    graph_dir = planning / "notes" / "graph" if planning else None
    store = args.store or (str(graph_dir) if graph_dir and graph_dir.is_dir() else "")
    return repo, planning, store


def _report(rows: list[dict]) -> int:
    for r in rows:
        print(f"{r['step']:<9}{r['outcome']}")
        if r.get("output") and (r["outcome"].startswith("failed") or r["step"] in ("check", "preview")):
            print("  " + r["output"].replace("\n", "\n  "))
    return 1 if any(r["outcome"].startswith("failed") for r in rows) else 0


def main_prepare(args) -> int:
    try:
        repo, planning, store = _where(args)
        prev, steps = plan(repo, args.version, args.theme, planning=planning, store=store,
                           repo_name=args.repo_name, freeze=args.freeze)
    except (ReleaseError, OSError) as exc:
        print(f"brain release prepare: {exc}", file=sys.stderr)
        return 2
    print(f"release  {prev} -> {args.version} in {repo}")
    print("\n".join(st.line for st in steps))
    try:
        code = _report(apply(repo, steps)) if args.write else 0
    except OSError as exc:   # a file locked or read-only: the steps before it are done, a second run resumes
        print(f"brain release prepare: {exc} (run it again once the file is free: it resumes)", file=sys.stderr)
        return 1
    if not args.write:
        print("plan only: --write runs it, in this order, stopping at the first step that fails")
    print("\n".join(f"by hand  {x}" for x in BY_HAND))
    return code


# --- brain release pin (wi-brain-release-pin) ---

TAG = re.compile(r"v\d+\.\d+\.\d+")
SHIM = "plugins/{plugin}/brain/__init__.py"
SHIM_PIN = re.compile(r'^(PIN = ")([^"]*)(")', re.M)
DEFAULT_BRANCHES = {"main", "master"}
PIN_BY_HAND = ["brain sync with the new engine (a venv at the tag: sync refuses another engine than the pin), in this "
               "branch, so the hooks it renders go in the same PR",
               "the Upgrade steps listed above that name config.json, then the ADR of the pin (brain adr new) and the "
               "journal entry (brain journal add); then the pin PR, merged after its checks (docs/release.md, « 4. "
               "The pin and the machines »)"]


@dataclass
class PinPlan:
    root: Path
    file: Path                                      # the planning brain's config.json
    prev: str                                       # the pin it holds
    tag: str
    stores: dict = field(default_factory=dict)      # the classes.stores lines to add
    stores_note: str = ""                           # why none is added, when that is not "none missing"
    shim: Path | None = None                        # the shim whose PIN line moves (None: none, or at the tag)
    shim_text: str = ""                             # its new text
    shim_line: str = ""                             # what the plan says of it
    upgrade: list[str] = field(default_factory=list)   # the Upgrade steps that name config.json
    upgrade_note: str = ""                          # why the changelog could not be read ('' when it was)
    waiting: list[dict] = field(default_factory=list)  # the open PRs naming the version
    waiting_note: str = ""                          # why they could not be listed
    engine: str = ""                                # the version of the engine that plans (its stores are these)

    def writes(self) -> bool:
        return self.prev != self.tag or bool(self.stores) or self.shim is not None


def pin_plan(root: Path, tag: str, *, opener=None, runner: Runner = subprocess.run) -> PinPlan:
    """The planning brain's pin PR as a plan; ReleaseError on a tag that is not a release or goes back."""
    from . import __version__, update
    if not TAG.fullmatch(tag):
        raise ReleaseError(f"{tag!r}: a release tag vX.Y.Z")
    cfg = _config_of(root)
    eng = cfg.data.get("engine")
    prev = eng.get("pin") if isinstance(eng, dict) else None
    if not isinstance(prev, str) or not update.version_of(prev):
        raise ReleaseError(f"{cfg.file}: engine.pin is {prev!r}, not a release tag vX.Y.Z (set it by hand first)")
    if update.version_of(tag) < update.version_of(prev):
        raise ReleaseError(f"{tag} is before the pin {prev}: a rollback is the owner's, by hand (docs/release.md)")
    p = PinPlan(root=cfg.root, file=cfg.file, prev=prev, tag=tag, engine=__version__)
    p.stores, p.stores_note = _missing_stores(cfg)
    _shim(p, cfg)
    repo = eng.get("repo") if isinstance(eng.get("repo"), str) else update.ENGINE_REPO
    lines = update.changelog(repo, tag, prev, opener=opener) if update.version_of(tag) > update.version_of(prev) else []
    if lines is None:
        p.upgrade_note = f"the CHANGELOG at {tag} could not be read: read its Upgrade section by hand"
    else:
        p.upgrade = config_steps(lines)
    p.waiting, p.waiting_note = waiting_prs(cfg.root, tag, runner)
    return p


def _config_of(root: Path):
    """The planning brain's own config.json (not $BRAIN_CONFIG's: the pin moves in the brain named)."""
    from . import config
    f = root / config.FILE
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ReleaseError(f"{root}: no {config.FILE} to pin: --planning names the brain") from None
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"{f}: not readable JSON ({exc})") from None
    if not isinstance(data, dict):
        raise ReleaseError(f"{f}: an object, got {type(data).__name__}")
    return config.Config(f, f.parent.resolve(), data)


def _missing_stores(cfg) -> tuple[dict, str]:
    """The engine stores a brain that declares classes leaves at their default (brain classes --suggest's lines)."""
    from . import classes
    if not isinstance(cfg.data.get("classes"), dict):
        return {}, "the brain declares no classes: block (brain classes --suggest prints one to edit)"
    _, errors = classes.stores(cfg)
    if errors:
        return {}, f"its classes: block has errors ({errors[0]}): brain classes, then again"
    return classes.suggest(cfg)["stores"], ""


def _shim(p: PinPlan, cfg) -> None:
    """The adapter plugin's transitional shim, when the brain keeps one: its PIN line follows engine.pin."""
    adapters = cfg.data.get("adapters")
    claude = adapters.get("claude") if isinstance(adapters, dict) else None
    plugin = claude.get("plugin") if isinstance(claude, dict) else None
    f = cfg.root / SHIM.format(plugin=plugin) if isinstance(plugin, str) and plugin else None
    if f is None or not f.is_file():
        p.shim_line = "skip     shim: none (no adapters.claude.plugin, or no brain/__init__.py in it)"
        return
    with f.open(encoding="utf-8", newline="") as fh:
        text = fh.read()
    m = SHIM_PIN.search(text)
    rel = f.relative_to(cfg.root).as_posix()
    if not m:
        p.shim_line = f"skip     shim: {rel} has no PIN line"
    elif m.group(2) == p.tag:
        p.shim_line = f"same     shim: {rel} PIN is {p.tag}"
    else:
        p.shim, p.shim_text = f, text[:m.start(2)] + p.tag + text[m.end(2):]
        p.shim_line = f"edit     shim: {rel} PIN {m.group(2)} -> {p.tag}"


STEP = re.compile(r"^(\d+)\. (.*)")
INSTALL_STEP = "Install the engine"   # the standard step every release has: the pin PR and its installer are it


def config_steps(lines: list[str]) -> list[str]:
    """The Upgrade steps of the CHANGELOG's sections (update.changelog's lines) that name config.json, one line each:
    the version, the step's number and its bold title (else its first words)."""
    out, version, upgrade, step = [], "", False, None

    def close():
        title = re.match(r"\*\*(.+?)\*\*", step[2]) if step else None
        if step and "config.json" in step[2] and not (title and title.group(1).startswith(INSTALL_STEP)):
            out.append(f"{step[0]} step {step[1]}: {title.group(1) if title else step[2][:80]}")

    for line in lines:
        head = re.match(r"^## (\d+\.\d+\.\d+)", line)
        if head or line.startswith("### "):
            close()
            step = None
            version = head.group(1) if head else version
            upgrade = line.strip() == "### Upgrade"
            continue
        m = STEP.match(line) if upgrade else None
        if m:
            close()
            step = [version, m.group(1), m.group(2)]
        elif step and line.startswith(" "):
            step[2] += " " + line.strip()
        elif step and line.strip():
            close()
            step = None
    close()
    return out


def waiting_prs(root: Path, tag: str, runner: Runner = subprocess.run) -> tuple[list[dict], str]:
    """The planning brain's open PRs whose title or body names the version (vX.Y.Z or X.Y.Z, wave-X.Y.Z): the lot
    PRs that waited for the tag; ([], why) when gh cannot list them."""
    try:
        r = runner(["gh", "pr", "list", "--state", "open", "--limit", "200", "--json", "number,title,body"],
                   cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"gh could not run ({exc})"
    if r.returncode != 0:
        return [], "gh pr list failed: " + ((r.stderr or r.stdout or "").strip().splitlines() or ["no output"])[-1]
    try:
        prs = json.loads(r.stdout or "[]")
    except ValueError:
        return [], "gh pr list gave no JSON"
    named = re.compile(rf"(?<![\d.])v?{re.escape(tag[1:])}(?![\d]|\.\d)")
    return [{"number": x.get("number"), "title": x.get("title") or ""} for x in prs if isinstance(x, dict)
            and named.search(f"{x.get('title') or ''}\n{x.get('body') or ''}")], ""


def pin_branch(root: Path, runner: Runner = subprocess.run) -> str:
    """The planning brain's branch, when the pin may be written there; ReleaseError on its default branch, a detached
    HEAD or no git repo."""
    try:
        r = runner(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True,
                   timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseError(f"{root}: git could not run ({exc})") from None
    branch = (r.stdout or "").strip() if r.returncode == 0 else ""
    if not branch or branch == "HEAD":
        raise ReleaseError(f"{root} is on no branch (not a git repo, or a detached HEAD): git switch -c "
                           "chore/pin-<tag>")
    default = _default_branch(root, runner)
    if branch in DEFAULT_BRANCHES | ({default} if default else set()):
        raise ReleaseError(f"{root} is on its default branch {branch}: the pin goes by a PR (git switch -c "
                           "chore/pin-<tag>, then again)")
    return branch


def _default_branch(root: Path, runner: Runner) -> str:
    """origin's default branch: origin/HEAD when the clone set it, else asked of the remote ('' when neither says)."""
    for argv, pick in ((["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], lambda s: s.split("/", 1)[-1]),
                       (["ls-remote", "--symref", "origin", "HEAD"],
                        lambda s: (re.search(r"^ref: refs/heads/(\S+)\s+HEAD", s, re.M) or [None, ""])[1])):
        try:
            r = runner(["git", "-C", str(root), *argv], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        found = pick((r.stdout or "").strip()) if r.returncode == 0 else ""
        if found:
            return found
    return ""


def pin_write(p: PinPlan, say: Callable[[str], object] = lambda line: None) -> list[str]:
    """The shim's PIN line, then config.json (engine.pin and the stores, one write), each written atomically; what
    was done, line by line, also said as it is done (``say``), so that a failure after the first write still tells
    it (a rerun resumes: it plans what is left). A config.json moved since the plan is refused (ValueError) before
    any write."""
    from . import stateio, update
    _pinned(p)
    done = []

    def did(line: str) -> None:
        done.append(line)
        say(line)
    if p.shim is not None:
        stateio.write_atomic(p.shim, p.shim_text)   # newline="\n": its own line endings, in the text, kept
        did(f"written  shim: {p.shim.relative_to(p.root).as_posix()}")
    if p.prev != p.tag or p.stores:
        def move(data: dict) -> None:
            _pin_is(data, p)
            data["engine"]["pin"] = p.tag
            if p.stores:
                block = data["classes"].setdefault("stores", {})
                for name, line in p.stores.items():
                    block.setdefault(name, line)
        update.rewrite_json(p.file, move)
        did(f"written  {p.file.name}: engine.pin {p.tag}" + (f", classes.stores + {', '.join(p.stores)}"
                                                             if p.stores else ""))
    return done


def _pin_is(data, p: PinPlan) -> None:
    eng = data.get("engine") if isinstance(data, dict) else None
    if not isinstance(eng, dict) or eng.get("pin") != p.prev:
        raise ValueError(f"{p.file.name} engine.pin is no longer {p.prev}: nothing written (plan again)")


def _pinned(p: PinPlan) -> None:
    """config.json still pins what the plan read (checked before the first write)."""
    _pin_is(json.loads(p.file.read_text(encoding="utf-8-sig")), p)


def pin_lines(p: PinPlan) -> list[str]:
    out = [f"pin      {p.root}: {p.prev} -> {p.tag}" if p.prev != p.tag else f"same     pin: {p.file.name} engine.pin "
           f"is {p.tag}"]
    if p.stores:
        out.append(f"edit     stores: classes.stores + {', '.join(p.stores)} (the stores engine {p.engine} declares "
                   "that the brain leaves at their default)")
    else:
        out.append(f"same     stores: {p.stores_note or 'none missing (brain classes --suggest)'}")
    if p.engine != p.tag[1:]:
        out.append(f"note     this engine is {p.engine}, not {p.tag}: the stores are its own (run brain release pin "
                   "with the tag's engine for the tag's)")
    out.append(p.shim_line)
    if p.upgrade_note:
        out.append(f"upgrade  {p.upgrade_note}")
    else:
        out.append("upgrade  " + (f"{len(p.upgrade)} step(s) name config.json, to read (what this command writes "
                                  "aside, by hand):" if p.upgrade
                                  else f"no Upgrade step after {p.prev} names config.json beyond the install"))
        out += [f"  {s}" for s in p.upgrade]
    if p.waiting_note:
        out.append(f"waiting  {p.waiting_note}")
    else:
        out.append(f"waiting  {len(p.waiting)} open PR(s) name {p.tag[1:]}" + (":" if p.waiting else ""))
        out += [f"  #{w['number']} {w['title']}" for w in p.waiting]
    return out


def _pin_data(p: PinPlan) -> dict:
    return {"root": str(p.root), "pin": p.prev, "tag": p.tag, "stores": p.stores, "stores_note": p.stores_note,
            "shim": p.shim_line, "upgrade": p.upgrade, "upgrade_note": p.upgrade_note, "waiting": p.waiting,
            "waiting_note": p.waiting_note, "engine": p.engine}


def planning_root(args, cwd: Path | None = None) -> Path | None:
    """The brain whose pin moves: --planning, else --root, else the brain checkout holding the current folder (a
    folder with config.json and .git: a pin branch's worktree), else the personal brain."""
    from . import paths
    if args.planning:
        return Path(args.planning).resolve()
    if getattr(args, "root", None):
        return Path(args.root).resolve()
    here = (cwd or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "config.json").is_file() and (d / ".git").exists():
            return d
    return paths.personal_root()


def main_pin(args) -> int:
    root = planning_root(args)
    try:
        if root is None:
            raise ReleaseError("no planning brain: --planning names it (or --root, or a personal brain)")
        p = pin_plan(root, args.tag)
        if args.json:   # the plan as data: nothing written
            print(json.dumps(_pin_data(p), indent=2))
            return 0
        branch = pin_branch(p.root) if args.write and p.writes() else ""
    except (ReleaseError, OSError) as exc:
        print(f"brain release pin: {exc}", file=sys.stderr)
        return 2
    print("\n".join(pin_lines(p)))
    if args.write and p.writes():
        try:
            pin_write(p, say=print)
            print(f"branch   {branch}: commit them with the rest of the pin PR")
        except (ValueError, OSError) as exc:
            print(f"brain release pin: {exc}", file=sys.stderr)
            return 1
    elif not args.write:
        print("plan only: --write writes config.json and the shim, in a pin branch of the planning brain")
    print("\n".join(f"by hand  {x}" for x in PIN_BY_HAND))
    return 0
