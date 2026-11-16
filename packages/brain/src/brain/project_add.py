"""``brain project add``: a project registered in a brain's ``projects.yaml`` by a command, a plan then ``--apply``
(wi-brain-project-add; the personal-brain boundary design, the scope tree's ``--parent``). Three ways in:

- ``--read``: a project the brain reads and never writes, its entry ``title``, ``access: read``, ``parent`` and
  ``classes`` only (no root: brain.projects' read-only entries);
- ``--existing DIR``: a standalone instance registered without a copy, its entry a ``root`` relative to the
  registry's checkout (its main checkout when the registry is read from a worktree), the folder holding its graph
  store (``--store``, default ``notes/graph``);
- ``--template T --dir DIR``: a new project's brain written by ``brain init DIR --template T --name NAME`` (its own
  step, run and logged), then registered like ``--existing``.

When the brain has a notes home (``config.json`` ``knowledge``, or a ``kind: knowledge`` entry: brain.knowledge),
the plan also writes the project's map there, ``maps/<name>.md`` (``scope: [name]``), never over a file
(wi-brain-project-add-notes); ``--no-notes`` leaves it out. An optional step: when it cannot be written, the entry
stays and the line says why.

``--parent NODE`` places it in the scope tree (a container of ``scopes.yaml``, such as a sphere ``brain init
--examples`` writes, or a project), ``--floor CLASS`` marks it with ``classes: {floor: CLASS}`` (a private project's
names join ``public.deny.repos`` when ``public.deny_from_tree`` is on), ``--title`` gives its one line.

**The qualification** (spec-brain-product-lifecycle 3.10, LC-1): five questions, each a setting of the Brain, asked
by the plan (each one unanswered is named with its option) or in the terminal with ``--interactive``, never by a
model. Their answers go to the entry's ``lifecycle`` (an instance or a template's project; a read-only entry holds
none):

1. the purpose and the audience: ``--profile`` (:data:`brain.projects.LIFECYCLE_PROFILES`) -> ``lifecycle.profile``;
2. what it produces: ``--kind K`` (repeatable, ids of the typology catalog, brain typologies) ->
   ``lifecycle.typologies`` (its items' clauses of done);
3. its stage, the entry point: ``--stage S`` (a lifecycle stage, or a standards stage read as one: mvp -> build) ->
   ``lifecycle.stage``, with ``since`` the day it is written;
4. its criticity: ``--floor CLASS`` -> ``classes.floor`` (the class floor of its node);
5. who works on it: ``--team`` (with ``--template``: the new brain is a team's, ``brain init --kind team``; an
   instance keeps the ``identity.kind`` of its own config.json, shown).

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

from . import config, graph, knowledge, paths, projects, scopes, typologies

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
    notes_home: Path | None = None    # the notes home the project's map goes to (brain.knowledge)
    notes: knowledge.Step | None = None   # its map there: write, or keep when there
    notes_why: str = ""               # why no map is planned
    who: str = ""                     # qualification 5: who works on it, as the plan says it

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


def lifecycle_of(args, cat: typologies.Catalog | None = None, today: str | None = None) -> dict:
    """The qualification's answers as the entry's ``lifecycle`` (questions 1 to 3): {} when none is answered. The
    kinds are ids of the typology catalog, the stage a lifecycle stage (a standards stage mapped to one); AddError
    names a value it does not take."""
    kinds = list(dict.fromkeys(getattr(args, "kinds", None) or []))
    profile, stage = getattr(args, "profile", None), getattr(args, "stage", None)
    if not (kinds or profile or stage):
        return {}
    cat = cat or typologies.load(config.load())
    lc: dict = {}
    for k in kinds:
        if not cat.known(k):
            raise AddError(f"--kind {k}: not in the typology catalog (brain typologies lists the kinds)")
    if kinds:
        lc["typologies"] = kinds
    if stage:
        mapped = cat.stage(stage)
        if mapped not in cat.stages:
            raise AddError(f"--stage {stage}: one of the lifecycle's stages ({', '.join(cat.stages)}) or the "
                           f"standards' ({', '.join(cat.standards_stages)})")
        lc["stage"] = mapped
        lc["since"] = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if profile:
        if profile not in projects.LIFECYCLE_PROFILES:
            raise AddError(f"--profile {profile}: one of {', '.join(projects.LIFECYCLE_PROFILES)}")
        lc["profile"] = profile
    return lc


def entry_for(args, registry: Path, lifecycle: dict | None = None) -> dict:
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
    if lifecycle:
        e["lifecycle"] = dict(lifecycle)
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
    answered = [f for f, v in (("--kind", getattr(args, "kinds", None)), ("--profile", getattr(args, "profile", None)),
                               ("--stage", getattr(args, "stage", None)), ("--team", getattr(args, "team", False)))
                if v]
    if args.read and answered:
        raise AddError(f"{', '.join(answered)}: a read-only project's entry holds title, access, parent and classes "
                       "only (its own sessions qualify it)")
    if getattr(args, "team", False) and not args.template:
        raise AddError("--team goes with --template (a new brain is a team's); an existing instance keeps the "
                       "identity.kind of its own config.json")


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
    entry = entry_for(args, registry, lifecycle_of(args, typologies.load(cfg)))
    init = None
    if args.template:
        init = ["brain", "init", str(Path(args.dir)), "--template", args.template, "--name", args.name,
                "--owner", config.owner_of(registry.parent)]
        from . import init as init_mod
        if getattr(args, "stage", None) in init_mod.STAGES:   # a standards stage: the standards its template selects
            init += ["--stage", args.stage]
        if getattr(args, "team", False):
            init += ["--kind", "team"]
        terms = _template_terms(registry, args.name, entry, cfg)
    else:
        terms = checked(registry, args.name, entry, cfg)
    home, step, why = notes_step(args, cfg, registry)
    return Plan(args.name, registry, entry, init, terms, home, step, why, who_of(args))


def who_of(args) -> str:
    """Qualification 5, who works on it: a new brain's kind (--team), else the identity.kind an instance's own
    config.json declares (read, never written); "" for a read-only project."""
    if args.template:
        return "a team (brain init --kind team)" if getattr(args, "team", False) else \
            "a person (brain init's default; --team for a team)"
    if not args.existing:
        return ""
    f = Path(args.existing) / config.FILE
    try:
        import json
        ident = json.loads(f.read_text(encoding="utf-8")).get("identity")
        kind = ident.get("kind") if isinstance(ident, dict) else None
    except (OSError, ValueError, AttributeError):
        kind = None
    return (f"{kind}, the identity.kind of its own {config.FILE}" if isinstance(kind, str) and kind
            else f"not declared (no identity.kind in {f}: its own brain says it)")


def notes_home(cfg: config.Config, registry: Path) -> Path | None:
    """Where the edited brain keeps its notes: ``knowledge.path`` of the config file beside its registry, else the
    first registry entry of kind knowledge. A config read from elsewhere ($BRAIN_PERSONAL, the pointer: when this
    brain holds no config file) is ignored, so a map never lands in another brain's notes."""
    if cfg.file is not None and _same(cfg.file.parent, registry.parent):
        home = knowledge.home(cfg)
    else:
        home = next(iter(projects.knowledge(registry.parent).values()), None)
    return Path(os.path.normpath(home)) if home is not None else None


def notes_step(args, cfg: config.Config, registry: Path) -> tuple[Path | None, knowledge.Step | None, str]:
    """The notes home, the project's map there (:func:`brain.knowledge.project_map`) and why there is none. An
    optional step: what it cannot read is its reason, never the command's failure."""
    if getattr(args, "no_notes", False):
        return None, None, "--no-notes"
    try:
        home = notes_home(cfg, registry)
        if home is None:
            return None, None, "this brain has no notes home (config.json knowledge, or a kind: knowledge entry)"
        if not home.is_dir():
            return home, None, f"the notes home {home} is no folder on this machine (brain notes init lays it out)"
        return home, knowledge.project_map(home, args.name, args.title or ""), ""
    except (OSError, UnicodeError, ValueError) as exc:
        return None, None, f"the notes home cannot be read ({exc})"


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
    lines += qualification_lines(p)
    lines.append(notes_line(p))
    return lines


def qualification_lines(p: Plan) -> list[str]:
    """The five questions of the qualification (spec-brain-product-lifecycle 3.10), each with its answer and where
    it goes, or the option that answers it; a read-only entry holds none."""
    if p.entry.get("access") == "read":
        return ["  qualification: none for a read-only project (its own sessions qualify it)"]
    lc = p.entry.get("lifecycle") or {}
    floor = (p.entry.get("classes") or {}).get("floor")
    stage = f"{lc['stage']} (since {lc.get('since')})" if lc.get("stage") else ""
    rows = [("1 purpose and audience", "lifecycle.profile", lc.get("profile"),
             "--profile " + "|".join(projects.LIFECYCLE_PROFILES)),
            ("2 what it produces", "lifecycle.typologies", ", ".join(lc.get("typologies") or []),
             "--kind K (brain typologies)"),
            ("3 stage", "lifecycle.stage", stage, "--stage S (brain typologies)"),
            ("4 criticity", "classes.floor", floor, "--floor CLASS"),
            ("5 who works on it", "identity.kind", p.who, "--team, with --template")]
    out = ["  qualification (spec-brain-product-lifecycle 3.10; --interactive asks them):"]
    for q, key, got, flag in rows:
        out.append(f"    {q}: {got} ({key})" if got else f"    {q}: not answered ({flag})")
    return out


def ask(args, read=None, out=print) -> None:
    """--interactive: each question the options leave unanswered, asked in the terminal; an empty answer leaves it
    unanswered. ``read`` replaces the prompt (brain.firstrun.ASK, a test's)."""
    from . import firstrun
    read = read or firstrun.ASK
    out("brain project add: the qualification (an empty answer leaves a question unanswered)")
    if not args.read:
        if not getattr(args, "profile", None):
            args.profile = read(f"1 purpose and audience ({'|'.join(projects.LIFECYCLE_PROFILES)}): ").strip() or None
        if not getattr(args, "kinds", None):
            args.kinds = read("2 what it produces (ids of brain typologies, comma-separated): ").replace(
                ",", " ").split() or None
        if not getattr(args, "stage", None):
            args.stage = read("3 stage (explore, build, launch...; or prototype, mvp, v1, scale): ").strip() or None
    if not args.floor:
        args.floor = read(f"4 criticity, its class floor ({'|'.join(_classes())}): ").strip() or None
    if args.template and not getattr(args, "team", False):
        args.team = read("5 who works on it: a person or a team? [person/team] ").strip().lower() in ("team", "t")


def notes_line(p: Plan) -> str:
    if p.notes is None:
        return f"  in the notes home: no map ({p.notes_why})"
    verb = "kept as it is (there already)" if p.notes.action == "keep" else "written, never over a file"
    return f"  in the notes home {p.notes_home}: {p.notes.path}, the project's map (scope: {p.name}), {verb}"


def write_notes(p: Plan) -> str:
    """The project's map written in the notes home after the entry; the line that says what was done, or why not
    (an optional step: a failure never undoes the entry)."""
    if p.notes is None or p.notes.action != "write" or p.notes_home is None:
        return ""
    try:
        done = knowledge.apply(p.notes_home, [p.notes])
    except OSError as exc:
        return f"the notes home: {p.notes.path} not written ({exc}); the entry is registered: write it by hand"
    if done and done[0].startswith("kept"):   # written by someone else since the plan: theirs, kept as it is
        return f"the notes home: {p.notes.path} kept as it is (written since the plan) in {p.notes_home}"
    return f"the notes home: {done[0].strip()} in {p.notes_home}: commit it in the notes repo"


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
                        ("--title", args.title), ("--profile", getattr(args, "profile", None)),
                        ("--stage", getattr(args, "stage", None))):
        if value:
            w += [flag, str(value)]
    w += [x for k in getattr(args, "kinds", None) or [] for x in ("--kind", k)]
    return (w + (["--read"] if args.read else []) + (["--team"] if getattr(args, "team", False) else [])
            + (["--no-notes"] if getattr(args, "no_notes", False) else []) + ["--apply"])


def main(args) -> int:
    t0 = time.monotonic()
    if getattr(args, "project", None):
        print("brain project add: --project is not taken here: --root names the brain whose registry it writes")
        return 2
    if getattr(args, "interactive", False):
        from . import firstrun
        if not firstrun.tty():
            print("brain project add: --interactive needs a terminal; --profile, --kind, --stage, --floor and --team "
                  "answer the same questions")
            return 2
        try:
            ask(args)
        except (EOFError, KeyboardInterrupt):
            print()
            print("brain project add: cancelled, nothing written")
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
        noted = write_notes(p)
        f = log(p.registry, words_of(args), 0, time.monotonic() - t0,
                p.text() + notes_line(p).strip() + "\n" + (noted + "\n" if noted else ""))
    print(f"wrote {p.name} in {p.registry}; logged in {f}; then brain sync and brain check (a PR of this brain)")
    if noted:
        print(noted)
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
