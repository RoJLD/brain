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
   public render: ``brain features render --repo R --out <checkout> --write`` and ``brain reference --public``), when
   one is found (``--planning``, else the personal brain);
5. **check**: ``installer/release_check.py`` (with ``--store`` when the planning brain's store is given), then its
   ``--preview``.

What stays a model's, said at the end: the ``### Upgrade`` section's numbered steps and their prose, the pilot page's
line of what each release brought, and the review. Every step runs a program with its arguments as a list, never a
shell: a theme with quotes, ``$`` or ``%`` reaches the script as typed.
"""

from __future__ import annotations

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
    return tuple(int(x) for x in v.split("."))


def plan(repo: Path, version: str, theme: str, *, planning: Path | None = None, store: str = "",
         repo_name: str = "brain", freeze: bool = True, python: str = sys.executable,
         brain: list[str] | None = None) -> tuple[str, list[Step]]:
    """(the previous version, the steps); ReleaseError on a version that does not move forward."""
    if not VERSION.fullmatch(version):
        raise ReleaseError(f"{version!r}: a version X.Y.Z (no v)")
    if not theme.strip():
        raise ReleaseError("--theme: the release's theme, for its CHANGELOG heading and its tag")
    prev = current_version(repo)
    if _version_key(version) < _version_key(prev):
        raise ReleaseError(f"{version} is before this checkout's {prev}")
    brain = brain or [python, "-m", "brain"]
    steps = []
    if version == prev:
        steps.append(Step("versions", f"same     versions: this checkout is at {version} already", "same"))
    else:
        edits = version_edits(repo, prev, version)
        lines = "; ".join(f"{e.path} ({e.count})" for e in edits)
        steps.append(Step("versions", f"edit     versions {prev} -> {version}: {lines}", edits=edits))
    frozen = (repo / STORES / f"v{prev}").is_dir()
    freeze_argv = [python, f"{INSTALLER}/freeze_store.py", f"v{prev}"]
    steps.append(Step("freeze", f"same     freeze: the store v{prev} wrote is frozen ({STORES}/v{prev})", "same")
                 if frozen else Step("freeze", "skip     freeze: --no-freeze (release_check refuses a version PR "
                                     f"without {STORES}/v{prev})", "skip") if not freeze
                 else Step("freeze", f"run      freeze: {' '.join(freeze_argv[1:])} (installs v{prev} in a fresh "
                                     "venv)", argv=freeze_argv))
    steps.append(Step("changelog", f"run      changelog: compile {version} --theme {theme!r} --write",
                      argv=[python, f"{INSTALLER}/changelog.py", "--repo", str(repo), "compile", version, "--theme",
                            theme, "--write"]))
    if planning is None:
        steps.append(Step("features", "skip     features and reference: no planning brain (--planning, or a personal "
                                      "brain): render FEATURES.md and docs/reference/ from it by hand", "skip"))
    else:
        steps.append(Step("features", f"run      features: FEATURES.md rendered from {planning} (the public render)",
                          argv=[*brain, "--root", str(planning), "features", "render", "--repo", repo_name, "--out",
                                str(repo), "--write"]))
        steps.append(Step("reference", f"run      reference: docs/reference/ rendered from {planning}",
                          argv=[*brain, "--root", str(planning), "reference", "--public", "--repo", repo_name,
                                "--out", str(repo / "docs" / "reference"), "--write"]))
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
    graph_dir = planning / "notes" / "graph" if planning else None
    store = args.store or (str(graph_dir) if graph_dir and graph_dir.is_dir() else "")
    return repo, planning, store


def _report(rows: list[dict]) -> int:
    for r in rows:
        print(f"{r['step']:<9}{r['outcome']}")
        if r.get("output") and r["outcome"].startswith("failed"):
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
    code = _report(apply(repo, steps)) if args.write else 0
    if not args.write:
        print("plan only: --write runs it, in this order, stopping at the first step that fails")
    print("\n".join(f"by hand  {x}" for x in BY_HAND))
    return code
