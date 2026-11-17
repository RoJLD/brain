"""Typology packs (wi-brain-typology-packs, spec-brain-typology-packs E3, TYPO-1, TYPO-4): a pack of the neutral source
(``source/packs.yaml``, brain.neutral) names the typologies it is for and bundles the parts a kind of project adds to
the generic core, in one place instead of nine mechanisms that each select by kind.

**The manifest.** A typology pack is a pack of ``packs.yaml``, its keys the same file's (``title``, ``description``,
``projects``, ``rules``, ``procedures``, ``mcp``, ``hooks``) plus its parts (:data:`PARTS`)::

    typologies  [software]                       ids of the typology catalog (an entry covers its sub-profiles)
    layers      [code, docs_tests]               the graph layers it brings (research_graph layers)
    standards   {catalogs: [software], profiles: [software]}   the engine's catalogs it reads, the profiles it opts a
                                                 project in to (brain standards)
    stages      {build: [gate, ...]}             its gates by lifecycle stage (the catalog's, or a layer's own)
    done        [{id, text, evidence}]           its clauses of the definition of done, after the generic sentence
    doors       [{id, text}]                     its one-way doors
    roles       [{id, text}]                     its roles
    guards      [branches]                       the guards it turns on (brain.guards.GUARDS)
    registry    [repos, audit]                   the keys of a project's entry it reads (brain.projects.KEYS)

**The engine's packs.** The engine ships its typology packs in ``typology_packs.yaml`` beside this module
(:func:`engine`): ``software`` and ``research``, the real typologies of TYPO-1 (the others are named by the catalog,
their packs written with a real project, STD-5). A brain takes one in its own ``packs.yaml`` by its id with
``from: engine``: the engine's parts, the brain's own keys laid over them key by key (the nearest wins: a list the
brain gives replaces the engine's), as the owner's procedure files are laid over the engine's (:func:`overlay`).

**Nothing turns on by itself** (TYPO-4, LC-3's way). :func:`propose` reads a project's ``lifecycle.typologies``
(projects.yaml) and lists the packs whose typologies it meets, the engine's and the brain's: those it has, and for each
it has not, the step that gives it (a pack ``from: engine`` with ``projects: [P]`` appended to packs.yaml, or ``P``
added to a brain pack's projects) with the layers its store lacks and the standards it does not opt in to.
``brain typologies propose P --apply`` (:func:`apply`) writes the packs.yaml step only, comments kept and the source
checked as it would be; the layers (``research_graph layers add``) and the registry's standards (a PR of the
registry) stay the owner's next steps, printed. A typology pack is never the core pack, and a pack that comes from a
typology is given to the projects named, never to every one (TYPO-6: node-local). The definition of done is the
exception that keeps the rule before the packs: an item takes the clauses of its kinds' packs whether or not the brain
took them (brain.typologies.Catalog.done_clauses), so no clause is dropped by a pack not yet applied.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import graph, schema

FILE = Path(__file__).with_name("typology_packs.yaml")
VERSION = 1
FROM = "from"
ENGINE = "engine"
PARTS = ("typologies", "layers", "standards", "stages", "done", "doors", "roles", "guards", "registry")
TEXT_KEYS = {"id", "text"}               # a door's, a role's
STANDARDS_KEYS = {"catalogs", "profiles"}
ENGINE_KEYS = {"title", "description", "procedures", "mcp", *PARTS}   # an engine pack names no brain rules file


class PackError(ValueError):
    """The engine's typology_packs.yaml cannot be read: a broken install (brain doctor)."""


@functools.lru_cache(maxsize=1)
def _read() -> dict:
    try:
        data = graph.load_yaml(FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - unreadable or not YAML: a broken install, said as one error
        raise PackError(f"{FILE.name}: not readable ({exc})") from None
    if not isinstance(data, dict) or data.get("v") != VERSION or not isinstance(data.get("packs"), dict):
        raise PackError(f"{FILE.name}: a mapping with v: {VERSION} and packs")
    return data


def engine() -> dict[str, dict]:
    """The engine's typology packs, {id: spec}, fresh copies (a caller may change them)."""
    import copy
    return {str(k): copy.deepcopy(v) if isinstance(v, dict) else {} for k, v in _read()["packs"].items()}


def overlay(pid: str, spec: dict) -> dict:
    """A brain's pack as it applies: ``from: engine`` takes the engine's pack ``pid`` with the brain's keys laid over it
    (the nearest wins); any other pack, or an engine id this engine does not ship, as given (check() says why)."""
    if not isinstance(spec, dict) or spec.get(FROM) != ENGINE:
        return spec
    try:
        base = engine().get(pid)
    except PackError:
        return spec
    return spec if base is None else {**base, **spec}


# --- checking -------------------------------------------------------------------------------------------------------

def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value)


@dataclass
class _Checker:
    """One pack's parts checked: ``errors`` gathers the shape errors and, in strict mode, the unknown ids."""
    where: str
    spec: dict
    strict: bool | None
    notes: list[str] | None
    errors: list[str] = field(default_factory=list)

    def ids(self, key: str) -> list[str]:
        value = self.spec.get(key)
        if value is not None and not _strings(value):
            self.errors.append(f"{self.where}: {key} is a list of ids")
            return []
        return list(value or [])

    def unknown(self, key: str, given, known, what: str) -> None:
        for x in given or []:
            if x not in known:
                self.errors += schema.tolerate(f"{self.where}: {key}: {what} {x!r} is not known to this engine",
                                               self.strict, self.notes)

    def standards(self) -> None:
        from . import standards
        std = self.spec.get("standards")
        if std is None:
            return
        if not (isinstance(std, dict) and not set(map(str, std)) - STANDARDS_KEYS
                and all(_strings(v) for v in std.values())):
            self.errors.append(f"{self.where}: standards is {{catalogs: [name], profiles: [id]}}")
            return
        self.unknown("standards.profiles", std.get("profiles"), standards.profiles(), "profile")
        self.unknown("standards.catalogs", std.get("catalogs"), {f.stem for f in standards.ENGINE_DIR.glob("*.yaml")},
                     "engine catalog")

    def stages(self, cat) -> None:
        stages = self.spec.get("stages")
        if stages is None:
            return
        if not (isinstance(stages, dict) and all(_strings(v) for v in stages.values())):
            self.errors.append(f"{self.where}: stages is {{stage: [a gate, in words]}}")
        elif cat is not None:
            known = set(cat.stages) | set(cat.standards_stages) | _layer_stages()
            self.unknown("stages", [str(s) for s in stages], known, "stage")

    def texts(self, key: str) -> None:
        """doors, roles: a list of {id, text}, an id once."""
        value = self.spec.get(key)
        if value is None:
            return
        if not (isinstance(value, list) and all(isinstance(x, dict) and set(map(str, x)) == TEXT_KEYS
                                                and _strings(list(x.values())) for x in value)):
            self.errors.append(f"{self.where}: {key} is a list of {{id, text}}")
            return
        got = [x["id"] for x in value]
        self.errors += [f"{self.where}: {key}: {i!r} twice" for i in sorted(set(got)) if got.count(i) > 1]


def part_errors(where: str, spec: dict, strict: bool | None = None, notes: list[str] | None = None,
                cat=None) -> list[str]:
    """What a pack's parts break: each part's shape is an error; an id this engine does not know (a typology, a layer,
    a standards profile or catalog, a stage, a guard, a registry key) a note in read mode, an error in strict mode
    (CI), so a pack written for a later engine is read by this one. ``cat``: the typology catalog with the brain's own
    ids (config.json typologies); default the engine's."""
    from . import guards, projects, typologies
    c = _Checker(where, spec, strict, notes)
    if cat is None:
        try:
            cat = typologies.load()
        except typologies.CatalogError:
            cat = None
    typs = c.ids("typologies")
    if typs and cat is not None:
        c.errors += typologies.unknown(f"{where}: typologies", typs, cat, strict, notes)
    c.unknown("layers", c.ids("layers"), _layer_names(), "layer")
    c.unknown("guards", c.ids("guards"), guards.GUARDS, "guard")
    c.unknown("registry", c.ids("registry"), projects.KEYS, "registry key")
    c.standards()
    c.stages(cat)
    if spec.get("done") is not None:
        c.errors += typologies.clauses_errors(f"{where}: done", spec.get("done"))
    c.texts("doors")
    c.texts("roles")
    return c.errors


def _layer_names() -> set[str]:
    try:
        from research_graph import layers as rg_layers
        return set(rg_layers.catalogue())
    except Exception:  # noqa: BLE001 - research_graph's catalogue unreadable: every layer a note, never a crash
        return set()


def _layer_stages() -> set[str]:
    """The stages the catalogue's layers inject (research's preregistration-backtest)."""
    try:
        from research_graph import layers as rg_layers
        return {str(i.get("stage")) for la in rg_layers.catalogue().values()
                for i in (la.lifecycle().get("injects") or []) if isinstance(i, dict)}
    except Exception:  # noqa: BLE001 - research_graph's catalogue unreadable: every layer stage a note, never a crash
        return set()


def source_errors(pid: str, raw: dict, applied: dict, *, strict: bool | None = None,
                  notes: list[str] | None = None, cat=None) -> list[str]:
    """A brain's pack in packs.yaml: ``from`` names the engine and an id it ships, a typology pack is never the core
    pack, a brain's own ``done`` is not read (a note), then its parts (:func:`part_errors`, on the pack as it
    applies, against ``cat``: the catalog with the brain's own ids)."""
    from . import neutral
    where = f"{neutral.PACKS}: pack {pid}"
    errors = []
    if "done" in raw:   # the engine's packs carry the clauses of done; a brain's own clauses wait on their reader
        errors += schema.tolerate(f"{where}: done: a brain's clauses of done are not read by this engine (the "
                                  "engine's packs carry them: brain item clauses)", strict, notes)
    if FROM in raw:
        if raw[FROM] != ENGINE:
            errors.append(f"{where}: from is {ENGINE!r} (the engine's typology pack of that id), not {raw[FROM]!r}")
        elif pid not in _engine_ids():
            errors.append(f"{where}: from: {ENGINE}, but the engine ships no typology pack {pid!r} (brain typologies "
                          f"packs: {', '.join(sorted(_engine_ids())) or 'none'})")
    if applied.get("typologies") and applied.get("core"):
        errors.append(f"{where}: a typology pack is never the core pack (the core is every project's, whatever its "
                      "kind)")
    return errors + part_errors(where, {k: v for k, v in applied.items() if k != "done" or "done" not in raw},
                                strict, notes, cat)


def _engine_ids() -> set[str]:
    try:
        return set(engine())
    except PackError:
        return set()


def self_check() -> list[str]:
    """What typology_packs.yaml itself breaks (the engine's tests run it, strict): a key an engine pack may not hold,
    a part's shape or an id unknown to this engine, a procedure the engine does not ship, a pack without typologies."""
    from . import neutral
    errors = []
    procs = {p.name for p in neutral.engine_procedures().iterdir() if p.is_dir()}
    for pid, spec in engine().items():
        where = f"{FILE.name}: pack {pid}"
        extra = sorted(set(map(str, spec)) - ENGINE_KEYS)
        if extra:
            errors.append(f"{where}: unknown key(s) {', '.join(extra)} (an engine pack: {', '.join(sorted(ENGINE_KEYS))})")
        if not spec.get("typologies"):
            errors.append(f"{where}: no typologies (an engine pack is a typology pack)")
        errors += [f"{where}: procedure {p!r} is not the engine's" for p in spec.get("procedures") or []
                   if p not in procs]
        errors += part_errors(where, spec, strict=True)
    return errors + _clause_collisions()


def _clause_collisions() -> list[str]:
    """A clause id of an engine pack that is the generic sentence's, or that two packs give one typology: done_clauses
    takes a clause id once, so the second would be dropped without a word."""
    from . import typologies
    generic = {str(c.get("id")) for c in typologies._read().get("done") or [] if isinstance(c, dict)}
    errors, by_kind = [], {}
    for pid, spec in engine().items():
        for c in spec.get("done") or []:
            cid = str(c.get("id")) if isinstance(c, dict) else ""
            if cid in generic:
                errors.append(f"{FILE.name}: pack {pid}: done: clause {cid!r} is the generic sentence's")
            for tid in spec.get("typologies") or []:
                if cid in by_kind.setdefault(tid, {}):
                    errors.append(f"{FILE.name}: pack {pid}: done: clause {cid!r} also given to {tid} by pack "
                                  f"{by_kind[tid][cid]}")
                by_kind[tid][cid] = pid
    return errors


def _list(value) -> list[str]:
    """A part's list as given, or [] when it is not a list of strings (check() says why)."""
    return [str(x) for x in value] if _strings(value) else []


def rows(src) -> list[dict]:
    """The typology packs as ``brain typologies packs`` lists them: the engine's (taken when the brain's packs.yaml
    holds it ``from: engine``), then the brain's own packs that name typologies; each with its projects and parts.
    ``src``: the brain's neutral source, or None."""
    shipped = engine()
    own = {p.id: p for p in (src.packs if src else []) if _typology_pack(p, shipped)}
    out = [_row(pid, spec, own.pop(pid, None)) for pid, spec in shipped.items()]
    return out + [_row(pid, p.spec, p, own=True) for pid, p in own.items()]


def _typology_pack(p, shipped: dict) -> bool:
    """A brain pack the listing shows: it names typologies, takes an engine pack, or bears an engine pack's id."""
    return bool(_list(p.spec.get("typologies"))) or FROM in (p.given or {}) or p.id in shipped


def _row(pid: str, spec: dict, p=None, own: bool = False) -> dict:
    """One row of :func:`rows`: an engine pack (``p`` the brain's pack of its id, if any) or a brain's own pack."""
    from . import neutral
    taken = own or (p is not None and (p.given or {}).get(FROM) == ENGINE)
    origin = neutral.PACKS if own or (p is not None and not taken) else ENGINE   # a same-id brain pack: the brain's
    return {"id": pid, "origin": origin, "taken": taken or p is not None, "projects": p.projects if p else [],
            **_parts(p.spec if p else spec)}


def _parts(spec: dict) -> dict:
    """A pack's parts for the listing: a mapping part as given when it is one, a list part as given when it is a list
    of strings (doors, roles, done: of mappings), else empty (check() says why)."""
    out = {}
    for k in PARTS:
        v = spec.get(k)
        if k in ("standards", "stages"):
            out[k] = v if isinstance(v, dict) else {}
        elif k in ("done", "doors", "roles"):
            out[k] = [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
        else:
            out[k] = _list(v)
    return out


# --- what a project's typologies propose (TYPO-4) -------------------------------------------------------------------

@dataclass
class Proposal:
    pack: str
    origin: str                      # engine, or the brain's packs.yaml
    meets: list[str]                 # the pack's typologies the project's kinds meet
    active: bool                     # the project has it already
    step: str = ""                   # add (a new pack from: engine), extend (the project added to its projects),
    #                                  shadowed (a brain pack of the engine pack's id hides it: nothing --apply writes)
    layers: list[str] = field(default_factory=list)      # its layers the project's store lacks
    standards: list[str] = field(default_factory=list)   # its standards profiles the project does not opt in to
    spec: dict = field(default_factory=dict, repr=False)  # its parts as it applies (brain project new reads them)

    def as_dict(self) -> dict:
        return {"pack": self.pack, "origin": self.origin, "meets": self.meets, "active": self.active,
                "step": self.step, "layers": self.layers, "standards": self.standards}


class ProposeError(ValueError):
    """A project the plan cannot be made for (not a loaded project of the registry): nothing is planned."""


def propose(root: Path, project: str) -> tuple[list[str], list[Proposal], Path | None]:
    """(the project's typologies, the packs they propose, its first store): every pack (the brain's, then the engine's
    it does not hold) whose typologies a kind of the project meets."""
    from . import config, neutral, projects, typologies
    regs = projects.load(root)
    if project not in regs:
        raise ProposeError(f"{project}: not a project of this brain's registry (brain projects)")
    p = regs[project]
    kinds, _ = typologies.item_typologies({}, p.lifecycle)
    if not kinds:
        return [], [], (p.stores[0] if p.stores else None)
    cat = typologies.load(config.load(root))
    store = p.stores[0] if p.stores else None
    std = p.standards if isinstance(p.standards, dict) else {}
    return kinds, proposals(_candidates(neutral.load(root), project), kinds, cat, _store_layers(store),
                            std.get("profiles")), store


def proposals(candidates, kinds: list[str], cat, have_layers: set[str] | None, profiles) -> list[Proposal]:
    """The candidates (:func:`_candidates`, :func:`engine_candidates`) a kind of ``kinds`` meets, each with what the
    project lacks: the layers its store does not hold (``have_layers``, None: unknown) and the standards profiles its
    selection (``profiles``, its ``standards.profiles``) does not meet, a sub-profile meeting its entry's (cli meets
    software, brain.standards.kinds)."""
    from . import standards
    have_profiles = {k for x in (profiles if isinstance(profiles, list) else []) for k in standards.kinds(str(x))}
    out = [_proposal(c, kinds, cat, have_layers, have_profiles) for c in candidates]
    return [pr for pr in out if pr.meets]


def engine_candidates() -> list[tuple[str, str, dict, bool, str]]:
    """The candidates of a brain whose packs.yaml holds the core only (one brain init writes): each engine pack, its
    step ``add``."""
    return [(pid, ENGINE, spec, False, "add") for pid, spec in engine().items()]


def _proposal(candidate, kinds: list[str], cat, have_layers: set[str] | None, have_profiles: set[str]) -> Proposal:
    """One candidate pack against a project: the typologies it meets (none: not proposed), its step, what it lacks."""
    pid, origin, spec, active, step = candidate
    meets = sorted({t for k in kinds for t in cat.meets(k, _list(spec.get("typologies")))})
    packstd = spec.get("standards") if isinstance(spec.get("standards"), dict) else {}
    layers = [la for la in _list(spec.get("layers")) if have_layers is not None and la not in have_layers]
    return Proposal(pid, origin, meets, active, "" if active else step, layers,
                    [x for x in _list(packstd.get("profiles")) if x not in have_profiles], spec)


def _candidates(src, project: str) -> list[tuple[str, str, dict, bool, str]]:
    """(id, origin, spec as it applies, the project takes it, the step that gives it): the brain's packs but the core,
    then the engine's packs the brain does not hold; a brain pack that bears an engine pack's id without ``from:
    engine`` nor typologies of its own hides that pack: its typologies are the engine's, its step ``shadowed``."""
    from . import neutral
    shipped = engine()
    out = []
    for pk in src.packs:
        if pk.core:
            continue
        shadow = pk.id in shipped and FROM not in (pk.given or {}) and not _list(pk.spec.get("typologies"))
        out.append((pk.id, neutral.PACKS, shipped[pk.id] if shadow else pk.spec,
                    not shadow and (pk.projects is None or project in pk.projects),
                    "shadowed" if shadow else "extend"))
    own = {pk.id for pk in src.packs}
    return out + [c for c in engine_candidates() if c[0] not in own]


def _store_layers(store: Path | None) -> set[str] | None:
    """The catalogue's layers a store holds (research_graph layers), None when it has no readable schema."""
    if store is None or not (store / "schema.yaml").is_file():
        return None
    try:
        from research_graph import layers as rg_layers
        data = graph.load_yaml((store / "schema.yaml").read_text(encoding="utf-8")) or {}
        return set(rg_layers.store_layers(data)["present"])
    except Exception:  # noqa: BLE001 - a schema the layers cannot read: no layer step proposed, check says why
        return None


def plan_lines(project: str, kinds: list[str], props: list[Proposal], store: Path | None) -> list[str]:
    """The plan as ``brain typologies propose`` prints it: each pack, what applying writes, the owner's next steps."""
    if not kinds:
        return [f"{project}: no lifecycle.typologies in its registry entry: nothing to propose (brain project new "
                "records them; brain typologies lists the kinds)"]
    lines = [f"{project}: typologies {', '.join(kinds)}"]
    if not props:
        return lines + ["  no typology pack meets them (brain typologies packs lists the packs and their typologies)"]
    for pr in props:
        lines += _plan_pack(project, pr, store)
    todo = [pr for pr in props if pr.step in ("add", "extend")]
    lines.append(f"--apply writes packs.yaml's {len(todo)} step(s); the layers and standards above stay the owner's"
                 if todo else "nothing for --apply to write")
    return lines


def _plan_pack(project: str, pr: Proposal, store: Path | None) -> list[str]:
    """One pack's lines of the plan: its state, then the layers and the standards it would bring."""
    from . import neutral
    states = {"add": f"to take: packs.yaml gains it, from: engine, projects: [{project}]",
              "extend": f"to take: {project} added to its projects",
              "shadowed": f"hidden by {neutral.PACKS}'s own pack {pr.pack}, which is not from: engine: give yours "
                          "from: engine, or rename it, to take the engine's"}
    lines = [f"  {pr.pack} ({pr.origin}; for {', '.join(pr.meets)}): {'taken' if pr.active else states[pr.step]}"]
    if pr.layers and store is not None:
        lines.append(f"    layers its store lacks: {', '.join(pr.layers)} (the owner: research_graph --store "
                     f"\"{store.as_posix()}\" layers add {' '.join(pr.layers)} --write)")
    if pr.standards:
        lines.append(f"    standards profiles it does not opt in to: {', '.join(pr.standards)} (projects.yaml "
                     f"{project}: standards.profiles, by a PR of the registry; brain standards)")
    return lines


# --- applying the packs.yaml steps ----------------------------------------------------------------------------------

def apply(root: Path, project: str, props: list[Proposal]) -> list[str]:
    """packs.yaml with the steps written: a pack ``from: engine`` appended at the end of ``packs:`` for each ``add``
    (indented as its first pack), the project appended to the pack's own ``projects:`` for each ``extend``; comments
    and line ends kept. The source is checked as it would be: an error it would add, or a check that fails, puts the
    file back byte for byte and refuses (ValueError). Returns what was written, one line each."""
    from . import neutral
    f = neutral.folder(root) / neutral.PACKS
    if not f.is_file():
        raise ValueError(f"{f}: not found (brain init writes the neutral source)")
    original = f.read_bytes()
    text = original.decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines, done = _edited(neutral.lf(text).splitlines(), project, props)
    if not done:
        return []
    before = set(neutral.check(neutral.load(root)))
    f.write_bytes((eol.join(lines) + eol).encode("utf-8"))
    try:
        after = [e for e in neutral.check(neutral.load(root)) if e not in before]
    except BaseException:
        f.write_bytes(original)
        raise
    if after:
        f.write_bytes(original)
        raise ValueError("packs.yaml as it would be: " + "; ".join(after))
    return done


def _edited(lines: list[str], project: str, props: list[Proposal]) -> tuple[list[str], list[str]]:
    """(packs.yaml's lines with the steps written, what was written)."""
    from . import neutral
    done = []
    name = _scalar(project)
    for pr in props:
        if pr.step == "extend":
            lines = _extend(lines, pr.pack, name)
            done.append(f"{neutral.PACKS}: pack {pr.pack} projects += {project}")
    adds = [pr for pr in props if pr.step == "add"]
    if adds:
        pad, sub = _pack_indent(lines)
        lines = _append(lines, [x for pr in adds for x in (
            f"{pad}{pr.pack}:   # the engine's typology pack (brain typologies packs), for {', '.join(pr.meets)}",
            f"{pad}{sub}{FROM}: {ENGINE}", f"{pad}{sub}projects: [{name}]")])
        done += [f"{neutral.PACKS}: pack {pr.pack} (from: engine, projects: [{project}])" for pr in adds]
    return lines, done


def _scalar(value: str) -> str:
    """A project's name as a YAML flow scalar: quoted when plain YAML would read it as something else (on, 1, a: b)."""
    import yaml
    return yaml.safe_dump([value], default_flow_style=True, width=1 << 20).strip()[1:-1]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _content(line: str) -> bool:
    return bool(line.strip()) and not line.lstrip().startswith("#")


def _block(lines: list[str], start: int, indent: int) -> int:
    """The end (exclusive) of the block opened at ``start``: after its last line, not blank nor a comment, indented
    more than ``indent``."""
    end, last = start + 1, start
    while end < len(lines):
        if _content(lines[end]):
            if _indent(lines[end]) <= indent:
                break
            last = end
        end += 1
    return last + 1


def _child_indent(lines: list[str], start: int, end: int) -> int | None:
    """The indent of the first content line of the block ``start``..``end`` (its keys' indent), None when empty."""
    return next((_indent(lines[i]) for i in range(start + 1, end) if _content(lines[i])), None)


def _packs_line(lines: list[str]) -> int:
    for i, ln in enumerate(lines):
        if re.match(r"^packs\s*:\s*(#.*)?$", ln):
            return i
    raise ValueError("packs.yaml: no block 'packs:' at the top level to write into (edit it by hand)")


def _pack_indent(lines: list[str]) -> tuple[str, str]:
    """(the packs' indent, a pack's keys' indent beyond it), as the file writes them; two spaces each by default."""
    top = _packs_line(lines)
    end = _block(lines, top, 0)
    pad = _child_indent(lines, top, end)
    if not pad:
        return "  ", "  "
    head = next(i for i in range(top + 1, end) if _content(lines[i]))
    sub = _child_indent(lines, head, _block(lines, head, pad))
    return " " * pad, " " * ((sub - pad) if sub and sub > pad else 2)


def _append(lines: list[str], new: list[str]) -> list[str]:
    end = _block(lines, _packs_line(lines), 0)
    return lines[:end] + new + lines[end:]


def _extend(lines: list[str], pack: str, name: str) -> list[str]:
    """``name`` appended to pack ``pack``'s own ``projects:`` (a flow list, or a block list): the pack at the packs'
    indent, its key at the pack's keys' indent, never a nested mapping's."""
    top = _packs_line(lines)
    pend = _block(lines, top, 0)
    pad = _child_indent(lines, top, pend)
    head = next((i for i in range(top + 1, pend) if _indent(lines[i]) == pad
                 and re.match(rf"^\s*{re.escape(pack)}\s*:(\s|$)", lines[i])), None)
    if head is None:
        raise ValueError(f"packs.yaml: pack {pack} not found under packs: (edit it by hand)")
    if re.match(rf"^\s*{re.escape(pack)}\s*:\s*\{{", lines[head]):
        raise ValueError(f"packs.yaml: pack {pack} is a flow mapping ({{...}}): edit it by hand")
    end = _block(lines, head, pad)
    keys = _child_indent(lines, head, end)
    for i in range(head + 1, end):
        m = re.match(r"^(\s+)projects\s*:\s*(.*?)(\s*#.*)?$", lines[i])
        if m and len(m.group(1)) == keys:
            return _extended(lines, i, end, m, pack, name)
    raise ValueError(f"packs.yaml: pack {pack} has no projects: it applies to every project already")


def _extended(lines: list[str], i: int, end: int, m, pack: str, name: str) -> list[str]:
    value, comment = m.group(2).rstrip(), m.group(3) or ""   # the comment and its spacing kept
    if value.startswith("[") and value.endswith("]") and not any(q in value for q in "'\""):
        items = [x.strip() for x in value[1:-1].split(",") if x.strip()]
        return [*lines[:i], f"{m.group(1)}projects: [{', '.join([*items, name])}]{comment}", *lines[i + 1:]]
    last = _last_item(lines, i + 1, end) if value == "" else None
    if last is None:
        raise ValueError(f"packs.yaml: pack {pack}'s projects is not a plain [flow] or block list (edit it by hand)")
    return lines[: last + 1] + [f"{lines[last][: _indent(lines[last])]}- {name}"] + lines[last + 1:]


def _last_item(lines: list[str], start: int, end: int) -> int | None:
    """The last ``- item`` line of the block list that starts at ``start`` (blank and comment lines between), None
    when there is none."""
    last, j = None, start
    while j < end and (not lines[j].strip() or lines[j].lstrip().startswith(("-", "#"))):
        if lines[j].lstrip().startswith("-"):
            last = j
        j += 1
    return last
