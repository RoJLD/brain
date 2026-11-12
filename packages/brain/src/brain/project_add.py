"""``brain project add``: a project registered in a brain's ``projects.yaml`` by a command, a plan then ``--apply``
(wi-brain-project-add; the personal-brain boundary design, the scope tree's ``--parent``). Three ways in:

- ``--read``: a project the brain reads and never writes, its entry ``title``, ``access: read``, ``parent`` and
  ``classes`` only (no root: brain.projects' read-only entries);
- ``--existing DIR``: a standalone instance registered without a copy, its entry a ``root`` relative to the
  registry's checkout (its main checkout when the registry is read from a worktree), the folder holding its graph
  store (``--store``, default ``notes/graph``);
- ``--template T --dir DIR``: a new project's brain written by ``brain init DIR --template T --name NAME`` (its own
  step, run and logged), then registered like ``--existing``.

``--parent NODE`` places it in the scope tree (a container of ``scopes.yaml`` or a project), ``--floor CLASS`` marks it
with ``classes: {floor: CLASS}`` (a private project's names join ``public.deny.repos`` when ``public.deny_from_tree``
is on), ``--title`` gives its one line.

The plan shows the entry, where it is written and what the tree and the generated deny list gain; nothing is written
without ``--apply``. Before writing, the registry as it would be is checked by the same checks ``brain check`` runs
(brain.projects.check, brain.scopes.check): an error they would add refuses the write, one already there is left to
``brain check``. The entry is appended to the end of ``projects.yaml``, its comments and order kept. Each write is
logged as the owner's step in ``<BRAIN_HOME>/ledger/setup-<month>.jsonl`` (brain.firstrun's ledger: the command, its
exit code, its duration and what it wrote).

The registry acted on is the brain at ``--root``, else ``$BRAIN_PROJECTS``, else the nearest folder above the current
one that holds a ``projects.yaml``: never the pointer's brain from another folder, and its config.json and
scopes.yaml are read beside it (:func:`this_brain`). A brain's own registry is changed by a branch and a PR of that
brain, as any edit of it: the command writes in the checkout it runs in.
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config, graph, paths, projects, scopes

NAME = re.compile(r"[a-z][a-z0-9-]*\Z")   # an id of the tree: kebab-case from a letter (never read as a number)
STORE = projects.DEFAULTS["stores"][0]
VIA = "project-add"


class AddError(ValueError):
    """An answer the command cannot take: nothing is planned or written (exit 2)."""


@dataclass
class Plan:
    name: str
    registry: Path
    entry: dict
    init: list[str] | None = None     # brain init's step, with --template
    new_terms: list[str] | None = None   # what public.deny.repos gains, when public.deny_from_tree is on

    def text(self) -> str:
        return block(self.name, self.entry)


def block(name: str, entry: dict) -> str:
    """The entry as appended to projects.yaml: a block mapping, keys in the order given."""
    return yaml.safe_dump({name: entry}, sort_keys=False, allow_unicode=True, width=120, default_flow_style=False)


def registry_of(root: Path | None) -> Path:
    """The registry acted on: ``projects.yaml`` at --root when it is given, else $BRAIN_PROJECTS, else the nearest
    ``projects.yaml`` above the current folder; AddError when there is none (brain init writes it)."""
    env = os.environ.get("BRAIN_PROJECTS")
    if root:
        f = Path(root).resolve() / projects.REGISTRY
    elif env:
        f = Path(env).expanduser().resolve()
    else:
        start = Path.cwd().resolve()
        f = next((d / projects.REGISTRY for d in (start, *start.parents) if (d / projects.REGISTRY).is_file()),
                 start / projects.REGISTRY)
    if not f.is_file():
        raise AddError(f"no {projects.REGISTRY} at {f.parent} or above: brain init writes a brain's registry "
                       "(--root names the brain)")
    return f


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def relative_root(folder: Path, registry: Path) -> str:
    """The folder as the entry's root, with forward slashes: relative to the registry's main checkout (the registry
    outlives a worktree it is edited in), checked to resolve back to the folder from the registry's own checkout as
    brain.projects reads it (a worktree's own path first); absolute when no relative path does (another drive, a
    sibling worktree of the same name). AddError for a folder inside the worktree: it goes with the worktree."""
    here, folder = registry.parent.resolve(), folder.resolve()
    main = paths.main_checkout(here)
    main = main.resolve() if main else here
    if not _same(main, here) and _inside(folder, here):
        raise AddError(f"{folder} is inside the worktree {here}, removed with it: register it from the main checkout")
    try:
        rel = Path(os.path.relpath(folder, main)).as_posix()
    except ValueError:   # another drive (Windows)
        return folder.as_posix()
    want = folder if folder.exists() else None
    return rel if want is None or _same(projects._resolve_root(rel, here), want) else folder.as_posix()


def _raw(registry: Path) -> dict:
    try:
        data = graph.load_yaml(_text(registry)) or {}
    except (yaml.YAMLError, OSError, ValueError) as exc:   # said, never written over
        raise AddError(f"{registry}: not readable YAML ({exc}); brain check says why") from None
    if not isinstance(data, dict):
        raise AddError(f"{registry} is a {type(data).__name__}, not a mapping")
    return data


def _check_name(name: str, registry: Path, cfg: config.Config) -> None:
    if not NAME.match(name):
        raise AddError(f"{name!r}: a project's name is an id of the scope tree, kebab-case from a letter "
                       "(a-z, 0-9, -)")
    if name == scopes.GLOBAL:
        raise AddError(f"{name!r} is the tree's root")
    if name in {str(k) for k in _raw(registry)}:
        raise AddError(f"{name} is registered already in {registry} (an existing entry changes by an edit and a PR)")
    if name in scopes.nodes_of(cfg):
        raise AddError(f"{name} is a container of the scope tree already (ids are unique across projects and "
                       "containers)")


def _check_folder(folder: Path, store: str, registry: Path) -> None:
    if not folder.is_dir():
        raise AddError(f"--existing {folder}: no such folder")
    if not (folder / store).is_dir():
        raise AddError(f"--existing {folder}: no graph store at {store} (--store PATH names another; brain init "
                       f"{folder} writes a brain; --read registers a project the brain only reads)")
    for p in projects.load(registry.parent).values():
        if _same(p.root, folder):
            raise AddError(f"--existing {folder}: the root of {p.name} already (a second project at one root "
                           "declares its own stores: an edit of its entry)")


def entry_for(args, registry: Path) -> dict:
    """The new entry from the options, keys in the registry's usual order."""
    e: dict = {}
    if args.read:
        if args.title:
            e["title"] = args.title
        e["access"] = "read"
    else:
        folder = Path(args.existing or args.dir)
        e["root"] = relative_root(folder, registry)
        if args.title:
            e["title"] = args.title
        if args.store and Path(args.store).as_posix() != STORE:
            e["stores"] = [Path(args.store).as_posix()]
    if args.parent:
        e["parent"] = args.parent
    if args.floor:
        e["classes"] = {"floor": args.floor}
    return e


@contextlib.contextmanager
def _env(**values):
    """Environment variables set (a value) or unset (None) for the block, then restored."""
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def this_brain(registry: Path):
    """The brain being edited as every read of the command sees it: its folder first among the bases (its
    config.json, its scopes.yaml), its registry, whatever $CLAUDE_BRAIN_DIR, $BRAIN_PERSONAL or $BRAIN_CONFIG name."""
    return _env(CLAUDE_BRAIN_DIR=str(registry.parent), BRAIN_PROJECTS=str(registry), BRAIN_CONFIG=None)


def _registry_as(path: Path):
    """$BRAIN_PROJECTS set to ``path`` for the checks, then restored."""
    return _env(BRAIN_PROJECTS=str(path))


def _text(f: Path) -> str:
    with f.open(encoding="utf-8", newline="") as fh:   # its line endings kept
        return fh.read()


def _errors(registry: Path, cfg: config.Config) -> tuple[set[str], list[str]]:
    """What brain check would say of the registry at ``registry``: its errors and the generated deny terms."""
    with _registry_as(registry):
        errs = set(projects.check(cfg.root)) | set(scopes.check(cfg.root, cfg)[0])
        try:
            terms = scopes.private_terms(cfg)
        except (yaml.YAMLError, OSError, ValueError):   # a tree that cannot be read: its errors say why
            terms = []
    return errs, terms


def candidate(registry: Path, name: str, entry: dict) -> str:
    """The registry's text with the entry appended, in the file's own line endings; AddError when the text does not
    read back with the entry as given (a flow mapping, a document end marker: a hand edit then)."""
    text = _text(registry)
    nl = "\r\n" if "\r\n" in text else "\n"
    sep = "" if not text or text.endswith("\n") else nl
    out = text + sep + block(name, entry).replace("\n", nl)
    try:
        back = graph.load_yaml(out)
    except (yaml.YAMLError, ValueError):
        back = None
    if not isinstance(back, dict) or back.get(name) != entry:
        raise AddError(f"{registry}: an entry appended at its end does not read back (a flow mapping or a document "
                       "end marker): add it by hand")
    return out


def _write(f: Path, text: str) -> None:
    with f.open("w", encoding="utf-8", newline="") as fh:   # the line endings as given
        fh.write(text)


def checked(registry: Path, name: str, entry: dict, cfg: config.Config) -> list[str]:
    """The deny terms the entry adds when public.deny_from_tree is on; AddError naming the errors the entry would add
    to brain check's (those already there are left to brain check)."""
    before, terms_before = _errors(registry, cfg)
    text = candidate(registry, name, entry)
    tmp = registry.with_name(f".{registry.name}.{os.getpid()}.add")
    try:
        _write(tmp, text)
        after, terms_after = _errors(tmp, cfg)
    finally:
        tmp.unlink(missing_ok=True)
    after = {e.replace(str(tmp), str(registry)).replace(tmp.name, registry.name) for e in after}
    new = sorted(after - before)
    if new:
        raise AddError("the entry would add to brain check: " + "; ".join(new[:3])
                       + (f" (+{len(new) - 3})" if len(new) > 3 else ""))
    return sorted(set(terms_after) - set(terms_before), key=str.lower) if config.deny_from_tree(cfg) else []


def _check_options(args) -> None:
    """The options' combinations: one way in, --dir with --template only, no store for a read-only project."""
    if len([m for m in ("read", "existing", "template") if getattr(args, m)]) != 1:
        raise AddError("one of --read, --existing DIR or --template T (with --dir DIR)")
    if args.template and not args.dir:
        raise AddError("--template T writes a new project's brain: --dir DIR names its folder")
    if args.dir and not args.template:
        raise AddError("--dir goes with --template (--existing DIR registers a folder that holds a brain)")
    if args.read and args.store:
        raise AddError("--store: a read-only project has no store")
    if args.floor and args.floor not in _classes():
        raise AddError(f"--floor {args.floor}: one of {', '.join(_classes())}")


def _check_target(args, registry: Path) -> None:
    """The folder: an existing instance holds its store; a template's folder is new or empty, and the machine has its
    pointer already (brain init points a machine without one at the brain it writes: here the new project, not the
    brain that registers it)."""
    if args.existing:
        _check_folder(Path(args.existing), Path(args.store).as_posix() if args.store else STORE, registry)
    if args.template and Path(args.dir).exists() and any(Path(args.dir).iterdir()):
        raise AddError(f"--dir {args.dir}: not empty (--existing registers a folder that holds a brain)")
    if args.template and paths.pointer_root() is None:
        raise AddError(f"--template: this machine has no pointer ({paths.personal_file()}): brain init would point "
                       "it at the new project; install this brain first (its installer, or brain init of it)")


def plan(args, registry: Path) -> Plan:
    """The plan for the registry, read as :func:`this_brain` sets it."""
    _check_options(args)
    cfg = config.load(registry.parent)
    _check_name(args.name, registry, cfg)
    _check_target(args, registry)
    entry = entry_for(args, registry)
    init = None
    if args.template:
        init = ["brain", "init", str(Path(args.dir)), "--template", args.template, "--name", args.name,
                "--owner", config.owner_of(registry.parent)]
        terms = _template_terms(registry, args.name, entry, cfg)
    else:
        terms = checked(registry, args.name, entry, cfg)
    return Plan(args.name, registry, entry, init, terms)


def _template_terms(registry: Path, name: str, entry: dict, cfg: config.Config) -> list[str]:
    """With --template the folder is written by brain init first: its root is checked then (an entry naming a store
    not there yet would read as an error of the plan); the plan checks the placement on a read-only stand-in."""
    stand_in = {k: v for k, v in entry.items() if k in projects.READ_ONLY_KEYS}
    stand_in["access"] = "read"
    return checked(registry, name, stand_in, cfg)


def _classes() -> tuple[str, ...]:
    from .classes import CLASSES
    return CLASSES


def render(p: Plan, apply: bool) -> list[str]:
    lines = [f"brain project add {p.name}: its entry in {p.registry}" + ("" if apply else " (plan: --apply writes it)")]
    if p.init:
        lines.append(f"  first: {' '.join(p.init)} --apply (a logged step: its own plan above)")
    lines += ["  " + line for line in p.text().rstrip("\n").splitlines()]
    where = p.entry.get("parent", scopes.GLOBAL)
    lines.append(f"  in the scope tree: under {where}" + (f", class floor {p.entry['classes']['floor']}"
                                                          if "classes" in p.entry else ""))
    if p.new_terms:
        lines.append(f"  public.deny.repos gains (public.deny_from_tree): {', '.join(p.new_terms)}")
    return lines


def write(p: Plan) -> None:
    _write(p.registry, candidate(p.registry, p.name, p.entry))


def log(registry: Path, words: list[str], code: int, seconds: float, output: str) -> Path:
    from . import firstrun
    return firstrun.log({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "event": "setup-step",
                         "via": VIA, "by": config.owner_of(registry.parent), "command": firstrun.shown(words),
                         "cwd": str(registry.parent), "exit": code, "seconds": round(seconds, 2),
                         "output": output[-firstrun.OUTPUT_MAX:]})


def words_of(args) -> list[str]:
    """The command as the owner typed it, for the ledger."""
    w = ["brain", "project", "add", args.name]
    for flag, value in (("--existing", args.existing), ("--template", args.template), ("--dir", args.dir),
                        ("--store", args.store), ("--parent", args.parent), ("--floor", args.floor),
                        ("--title", args.title)):
        if value:
            w += [flag, str(value)]
    return w + (["--read"] if args.read else []) + ["--apply"]


def main(args) -> int:
    t0 = time.monotonic()
    if getattr(args, "project", None):
        print("brain project add: --project is not taken here: --root names the brain whose registry it writes")
        return 2
    try:
        registry = registry_of(getattr(args, "root", None))
        with this_brain(registry):
            p = plan(args, registry)
    except AddError as exc:
        print(f"brain project add: {exc}")
        return 2
    if p.init and not args.apply:
        from . import cli
        code = cli.main(p.init[1:])   # brain init's own plan, written nowhere
        if code:
            print(f"brain project add: brain init's plan exited {code}: nothing would be registered")
            return code
    print("\n".join(render(p, args.apply)))
    if not args.apply:
        return 0
    if p.init and not _init(p, args):
        return 2
    with this_brain(registry):
        try:
            write(p)
        except AddError as exc:
            print(f"brain project add: {exc}")
            return 2
        f = log(p.registry, words_of(args), 0, time.monotonic() - t0, p.text())
    print(f"wrote {p.name} in {p.registry}; logged in {f}; then brain sync and brain check (a PR of this brain)")
    return 0


def _init(p: Plan, args) -> bool:
    """brain init's step, run and logged, then the entry checked against the folder it wrote; False when either
    fails (the plan's note says what is left)."""
    from . import firstrun
    with this_brain(p.registry):
        by = config.owner_of(p.registry.parent)
    res = firstrun.run([*p.init, "--apply"], p.registry.parent, by=by)
    print(res["output"])
    if res["exit"] != 0:
        print(f"brain project add: brain init exited {res['exit']}: nothing registered")
        return False
    with this_brain(p.registry):
        try:
            p.new_terms = checked(p.registry, p.name, p.entry, config.load(p.registry.parent))
        except AddError as exc:
            print(f"brain project add: {exc} (the brain at {args.dir} is written; register it with --existing)")
            return False
    return True
