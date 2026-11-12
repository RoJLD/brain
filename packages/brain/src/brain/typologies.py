"""The typology catalog (wi-brain-typology-catalog, spec-brain-typology-packs E1, TYPO-3): one vocabulary of the kinds
of project, read by the graph layers' ``lifecycle`` ids, the project templates' profiles and the standards' profiles.

The engine's catalog is ``typologies.yaml`` beside this module (docs/typologies.md):

- **entries**: the kinds of project (``software``, ``research``, ``hardware-cad``, ``creation``, ``strategy``,
  ``marketing``, ``organisation``, ``compliance``), each with its labels (``en``, ``fr``), a description and its
  column to the Vision's modules (``vision``: J1, J2, J3, K3, K4);
- **sub-profiles**: a narrower kind of one entry (``cli`` of ``software``, ``trading`` of ``research``...). A
  sub-profile takes what its entry takes: a layer, a standards row or a pack named for the entry applies to it too,
  plus what names it (:meth:`Catalog.meets`);
- **stages**: the lifecycle's (LC-2: ``explore``, ``build``, ``launch``... for a living product, ``deliver`` and
  ``closed`` for a finite project), and ``standards_stages``, the standards' stages (``prototype``, ``mvp``, ``v1``,
  ``scale``) mapped to them (:meth:`Catalog.stage`);
- **the definition of done** in two layers (wi-brain-done-by-typology): ``done``, the generic sentence, and an
  entry's ``done``, its clauses (the software pack's: a PR, a test, the docs in the same PR, the scout, the
  worktree), which an item takes by its typologies (:func:`item_typologies`, :meth:`Catalog.done_clauses`); a clause
  whose ``evidence`` is ``pr`` makes ``brain item close`` require --pr (:func:`requires`).

Ids are stable and English, never renamed nor reused. A brain renames the labels, and adds its own entries or
sub-profiles, in config.json ``typologies`` (SCOPE-4's rule for a renamable catalogue, as ``scope_types``)::

    "typologies": {"software": {"fr": "Produit logiciel"},
                   "podcast": {"en": "Podcast", "parent": "creation"},
                   "venture": {"en": "Venture", "vision": ["K3"]}}

A key with ``parent`` adds (or names) a sub-profile of that entry; without it, an entry. An id the catalog does not
know, wherever a brain names one, is a note in read mode and an error in strict mode (CI) (:func:`unknown`), so a
brain written by a later catalog is read by this engine. ``brain typologies`` lists the catalog and shows an id
(brain.commands.typologies).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import config, schema

FILE = Path(__file__).with_name("typologies.yaml")
VERSION = 1
KEY = "typologies"   # config.json's key: a brain's labels and its own ids
ID = re.compile(r"^[a-z][a-z0-9-]*$")
ANY = ("*", "any")   # what a layer (*) or a standards row (any) names for every kind of project
LANGS = ("en", "fr")
VISION = re.compile(r"^[A-Z][0-9]+$")   # a module id of the Vision (J1, K4...)
ENTRY_KEYS = {"en", "fr", "description", "vision", "sub", "done"}
CLAUSE_KEYS = {"id", "text", "evidence"}
EVIDENCE = ("pr",)   # a clause's evidence brain item close requires: --pr
SUB_KEYS = {"en", "fr", "description"}
CONFIG_KEYS = {"en", "fr", "description", "vision", "parent"}
STAGE_KEYS = {"en", "fr", "shapes"}
SHAPES = ("living", "finite")


class CatalogError(ValueError):
    """The engine's typologies.yaml cannot be read: a broken install (brain doctor)."""


@dataclass
class Typology:
    id: str
    labels: dict[str, str]
    description: str = ""
    vision: tuple[str, ...] = ()
    parent: str = ""   # the entry of a sub-profile; "" for an entry
    origin: str = "engine"   # engine, or config.json for a brain's own id

    def label(self, lang: str = "en") -> str:
        return self.labels.get(lang) or self.labels.get("en") or self.id


@dataclass
class Clause:
    """A clause of the definition of done: the generic sentence's (``typology`` "") or an entry's."""
    id: str
    text: str
    typology: str = ""
    evidence: str = ""   # pr: brain item close requires --pr for an item that takes it


@dataclass
class Catalog:
    typologies: dict[str, Typology] = field(default_factory=dict)
    stages: dict[str, dict] = field(default_factory=dict)
    standards_stages: dict[str, str] = field(default_factory=dict)
    done: list[Clause] = field(default_factory=list)                  # the generic sentence
    clauses: dict[str, list[Clause]] = field(default_factory=dict)   # an entry's own clauses

    def entries(self) -> list[Typology]:
        return [t for t in self.typologies.values() if not t.parent]

    def subs(self, entry: str) -> list[Typology]:
        return [t for t in self.typologies.values() if t.parent == entry]

    def known(self, tid: str) -> bool:
        return tid in self.typologies

    def entry(self, tid: str) -> str:
        """The entry an id belongs to: itself for an entry, its parent for a sub-profile, "" when unknown."""
        t = self.typologies.get(tid)
        return "" if t is None else (t.parent or t.id)

    def kinds(self, tid: str) -> list[str]:
        """What a project of kind ``tid`` is: the id and, for a sub-profile, its entry (an unknown id: itself)."""
        e = self.entry(tid)
        return [tid] + ([e] if e and e != tid else [])

    def meets(self, tid: str, named) -> list[str]:
        """The ids of ``named`` (a layer's typologies, a row's profiles) that a project of kind ``tid`` meets: the id
        itself, its entry, or ``*``/``any``."""
        mine = set(self.kinds(tid))
        return [n for n in named if n in mine or n in ANY]

    def stage(self, sid: str) -> str:
        """A lifecycle stage for ``sid``: itself when the lifecycle knows it, the mapped stage for a standards stage
        (``mvp`` -> ``build``), else ``sid`` as given (a layer's own stage, a later catalog's)."""
        return sid if sid in self.stages else self.standards_stages.get(sid, sid)

    def done_clauses(self, typs) -> list[Clause]:
        """The definition of done of an item of kinds ``typs``: the generic sentence, then the clauses of each one's
        entry, once each (a sub-profile takes its entry's; an unknown id adds none)."""
        out, seen = list(self.done), set()
        for tid in typs:
            entry = self.entry(tid)
            if entry and entry not in seen:
                seen.add(entry)
                out += self.clauses.get(entry, [])
        return out


@functools.lru_cache(maxsize=1)
def _read() -> dict:
    """typologies.yaml parsed once per process (never mutated: :func:`engine` builds fresh objects from it)."""
    try:
        data = yaml.safe_load(FILE.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"{FILE.name}: not readable ({exc})") from None
    if not isinstance(data, dict) or data.get("v") != VERSION:
        raise CatalogError(f"{FILE.name}: a mapping with v: {VERSION}")
    return data


def _labels(spec: dict) -> dict[str, str]:
    return {lang: str(spec[lang]) for lang in LANGS if isinstance(spec.get(lang), str) and spec[lang]}


def engine() -> Catalog:
    """The engine's catalog, as typologies.yaml gives it."""
    data = _read()
    cat = Catalog()
    entries = data.get("entries") or {}
    for eid, spec in entries.items():
        _add_entry(cat, eid, spec or {})
    cat.stages = {str(k): dict(v or {}) for k, v in (data.get("stages") or {}).items()}
    cat.standards_stages = {str(k): str(v) for k, v in (data.get("standards_stages") or {}).items()}
    cat.done = [_clause(c) for c in data.get("done") or []]
    return cat


def _add_entry(cat: Catalog, eid: str, spec: dict) -> None:
    """An entry of typologies.yaml: itself, its sub-profiles and its clauses of done."""
    cat.typologies[eid] = Typology(eid, _labels(spec), str(spec.get("description") or ""),
                                   tuple(spec.get("vision") or ()))
    for sid, sub in (spec.get("sub") or {}).items():
        sub = sub or {}
        cat.typologies[sid] = Typology(sid, _labels(sub), str(sub.get("description") or ""), parent=eid)
    if spec.get("done"):
        cat.clauses[eid] = [_clause(c, eid) for c in spec["done"]]


def _clause(c: dict, typology: str = "") -> Clause:
    return Clause(str(c.get("id")), " ".join(str(c.get("text") or "").split()), typology, str(c.get("evidence") or ""))


def load(cfg: config.Config | None = None) -> Catalog:
    """The engine's catalog with a brain's config.json ``typologies`` merged over it: a known id renamed (its labels,
    description or vision, never its parent), a new id added (a sub-profile with an entry as ``parent``, else an
    entry; the brain's entries first, so a sub-profile may name one). Malformed values are left out here;
    :func:`check` reports them."""
    cat = engine()
    given = cfg.data.get(KEY) if cfg is not None and isinstance(cfg.data, dict) else None
    specs = [(str(t), s) for t, s in (given.items() if isinstance(given, dict) else [])
             if isinstance(s, dict) and ID.match(str(t))]
    for tid, spec in sorted(specs, key=lambda ts: bool(ts[1].get("parent"))):   # entries, then sub-profiles
        _merge(cat, tid, spec)
    return cat


def _merge(cat: Catalog, tid: str, spec: dict) -> None:
    labels = _labels(spec)
    desc = spec.get("description") if isinstance(spec.get("description"), str) else None
    given = spec.get("vision")
    vision = tuple(v for v in given if isinstance(v, str)) if isinstance(given, list) else None
    t = cat.typologies.get(tid)
    if t is not None:   # a rename: the id and its place stay
        t.labels = {**t.labels, **labels}
        t.description = t.description if desc is None else desc
        t.vision = vision if vision is not None and not t.parent else t.vision
        return
    parent = spec.get("parent")
    if not parent:
        cat.typologies[tid] = Typology(tid, labels, desc or "", vision or (), origin=config.FILE)
    elif isinstance(parent, str) and cat.entry(parent) == parent:   # else no entry of that id: check() says so
        cat.typologies[tid] = Typology(tid, labels, desc or "", parent=parent, origin=config.FILE)


def unknown(where: str, ids, cat: Catalog, strict: bool | None = None, notes: list[str] | None = None,
            what: str = "typology") -> list[str]:
    """Each id of ``ids`` the catalog does not know (``*`` and ``any`` aside): a note in read mode (kept, a later
    catalog's id), an error in strict mode (CI)."""
    out = []
    for tid in ids:
        if isinstance(tid, str) and tid not in ANY and not cat.known(tid):
            out += schema.tolerate(f"{where}: {what} {tid!r} is not in the typology catalog (brain typologies)",
                                   strict, notes)
    return out


def check(cfg: config.Config) -> list[str]:
    """What config.json ``typologies`` breaks: not a mapping, an id that is not lowercase letters, digits and '-', a
    label that is empty, a parent that is no entry, a parent given to an engine id (its place is fixed), a vision that
    is not a list of module ids; an unknown key is a note in read mode."""
    given = cfg.data.get(KEY) if isinstance(cfg.data, dict) else None
    if given is None:
        return []
    if not isinstance(given, dict):
        return [f"{config.FILE}: {KEY} is a mapping of typology id -> {{en, fr, description, vision, parent}}"]
    base = engine()
    errors = []
    for tid, spec in given.items():
        where = f"{config.FILE}: {KEY} {tid}"
        if not ID.match(str(tid)):
            errors.append(f"{where}: a typology id is lowercase letters, digits and '-', starting with a letter")
        elif not isinstance(spec, dict):
            errors.append(f"{where}: a mapping of {', '.join(sorted(CONFIG_KEYS))}")
        else:
            errors += _spec_errors(where, str(tid), spec, given, base)
    return errors


def _spec_errors(where: str, tid: str, spec: dict, given: dict, base: Catalog) -> list[str]:
    errors = [f"{where}: {lang} is a label" for lang in LANGS
              if lang in spec and not (isinstance(spec[lang], str) and spec[lang].strip())]
    if not _vision_ok(spec.get("vision")):
        errors.append(f"{where}: vision is a list of the Vision's module ids (J1, K4...)")
    elif spec.get("vision") is not None and (spec.get("parent") or base.typologies.get(tid, Typology(tid, {})).parent):
        errors.append(f"{where}: vision is an entry's; a sub-profile takes its entry's")
    parent = spec.get("parent")
    if parent is not None and tid in base.typologies:
        errors.append(f"{where}: an engine id keeps its place; parent is for a brain's own sub-profile")
    elif parent is not None and not (isinstance(parent, str) and _is_entry(parent, given, base)):
        errors.append(f"{where}: parent {parent!r} is no entry of the catalog (brain typologies)")
    unknown_keys = sorted(set(map(str, spec)) - CONFIG_KEYS)
    if unknown_keys:
        errors += schema.tolerate(f"{where}: unknown key(s) {', '.join(unknown_keys)} (known: "
                                  f"{', '.join(sorted(CONFIG_KEYS))})")
    return errors


def _vision_ok(vision) -> bool:
    return vision is None or (isinstance(vision, list) and all(isinstance(v, str) and VISION.match(v) for v in vision))


def _is_entry(tid: str, given: dict, base: Catalog) -> bool:
    if tid in base.typologies:
        return not base.typologies[tid].parent
    spec = given.get(tid)
    return isinstance(spec, dict) and not spec.get("parent") and bool(ID.match(tid))


def layers(cat: Catalog, tid: str, stage: str) -> list[str]:
    """The catalogue's graph layers (research_graph) a project of kind ``tid`` is proposed at ``stage``: those open to
    the id, to its entry or to any kind, at the stage (a standards stage read as its lifecycle stage) or at any."""
    from research_graph import layers as rg_layers
    names: list[str] = []
    for kind in cat.kinds(tid):
        names += [la.name for la in rg_layers.proposed(kind, cat.stage(stage)) if la.name not in names]
    return sorted(names)


# --- the definition of done by typology (wi-brain-done-by-typology) --------------------------------------------------

def item_typologies(props: dict | None, project_lifecycle=None) -> tuple[list[str], str]:
    """(an item's typologies, where they come from): its ``props.typology`` (an id, or ids separated by commas or
    spaces), else its project's ``lifecycle.typologies`` (projects.yaml), else ([], "")."""
    given = (props or {}).get("typology")
    if isinstance(given, list):
        own = [str(t) for t in given if str(t).strip()]
    else:
        own = str(given or "").replace(",", " ").split()
    if own:
        return own, "props.typology"
    lc = project_lifecycle if isinstance(project_lifecycle, dict) else {}
    typs = lc.get("typologies")
    if isinstance(typs, list) and typs:
        return [str(t) for t in typs if isinstance(t, str) and t], "lifecycle.typologies"
    return [], ""


def requires(cat: Catalog, typs) -> list[Clause]:
    """The clauses whose evidence brain item close requires for an item of kinds ``typs`` (a ``pr`` clause:
    --pr). An item whose project declares no typology keeps the rule before the catalog, --pr required (DONE-1): the
    software clauses' ``pr``."""
    clauses = cat.done_clauses(typs) if typs else cat.done_clauses(["software"])
    return [c for c in clauses if c.evidence]


def describe(cat: Catalog, lang: str = "en") -> dict:
    """The catalog with stable keys: what ``brain typologies --json`` prints."""
    def one(t: Typology) -> dict:
        d = {"id": t.id, "label": t.label(lang), "labels": t.labels, "description": t.description,
             "origin": t.origin}
        if t.parent:
            d["parent"] = t.parent
        else:
            d["vision"] = list(t.vision)
            d["sub"] = [s.id for s in cat.subs(t.id)]
        return d
    return {"v": VERSION, "entries": [one(t) for t in cat.entries()],
            "sub_profiles": [one(t) for t in cat.typologies.values() if t.parent],
            "stages": [{"id": s, "label": (spec.get(lang) or spec.get("en") or s), "shapes": spec.get("shapes", [])}
                       for s, spec in cat.stages.items()],
            "standards_stages": dict(cat.standards_stages),
            "done": {"generic": [c.id for c in cat.done], **{e: [c.id for c in cs] for e, cs in cat.clauses.items()}}}


def self_check() -> list[str]:
    """What typologies.yaml itself breaks (the engine's tests run it): an id of the wrong shape or used twice,
    an unknown key, an entry without both labels or its vision, a stage without its shapes, a standards stage mapped
    to no stage."""
    data = _read()
    errors: list[str] = []
    seen: set[str] = set()
    for eid, spec in (data.get("entries") or {}).items():
        errors += _entry_errors(eid, spec, seen)
    stages = data.get("stages") or {}
    errors += [f"stage {sid}: en, fr and shapes ({', '.join(SHAPES)})" for sid, spec in stages.items()
               if not _stage_ok(spec)]
    errors += [f"standards stage {k}: maps to {v!r}, no stage" for k, v in (data.get("standards_stages") or {}).items()
               if v not in stages]
    errors += _clauses_errors("done", data.get("done"), required=True)
    errors += [e for eid, spec in (data.get("entries") or {}).items() if isinstance(spec, dict)
               for e in _clauses_errors(f"entry {eid}: done", spec.get("done"))]
    return errors


def _clauses_errors(where: str, clauses, required: bool = False) -> list[str]:
    if clauses is None and not required:
        return []
    if not (isinstance(clauses, list) and clauses):
        return [f"{where}: a list of clauses {{id, text, evidence}}"]
    ids = [c.get("id") for c in clauses if isinstance(c, dict)]
    errors = [f"{where}: clause {c!r}: id and text, evidence one of {', '.join(EVIDENCE)}" for c in clauses
              if not (isinstance(c, dict) and set(c) <= CLAUSE_KEYS and c.get("id") and c.get("text")
                      and c.get("evidence", "pr") in EVIDENCE)]
    return errors + [f"{where}: clause {i!r} twice" for i in set(ids) if ids.count(i) > 1]


def _entry_errors(eid, spec, seen: set[str]) -> list[str]:
    errors = _one(f"entry {eid}", eid, spec, ENTRY_KEYS, seen)
    if not (isinstance(spec, dict) and spec.get("vision") and all(VISION.match(str(v)) for v in spec["vision"])):
        errors.append(f"entry {eid}: vision is a non-empty list of the Vision's module ids")
    subs = spec.get("sub") if isinstance(spec, dict) else None
    for sid, sub in (subs.items() if isinstance(subs, dict) else []):
        errors += _one(f"sub-profile {sid} of {eid}", sid, sub, SUB_KEYS, seen)
    return errors


def _stage_ok(spec) -> bool:
    return (isinstance(spec, dict) and set(spec) <= STAGE_KEYS and all(spec.get(lang) for lang in LANGS)
            and bool(spec.get("shapes")) and set(spec["shapes"]) <= set(SHAPES))


def _one(where: str, tid, spec, keys: set[str], seen: set[str]) -> list[str]:
    errors = []
    if not (isinstance(tid, str) and ID.match(tid)):
        errors.append(f"{where}: an id is lowercase letters, digits and '-'")
    if tid in seen:
        errors.append(f"{where}: the id is used twice")
    seen.add(tid)
    if not isinstance(spec, dict):
        return errors + [f"{where}: a mapping"]
    if set(spec) - keys:
        errors.append(f"{where}: unknown key(s) {', '.join(sorted(set(spec) - keys))}")
    errors += [f"{where}: {lang} is a label" for lang in LANGS if not spec.get(lang)]
    if not spec.get("description"):
        errors.append(f"{where}: a description")
    return errors
