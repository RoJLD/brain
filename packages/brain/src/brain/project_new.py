"""``brain project new``: the new-project wizard (wi-brain-project-wizard, spec-brain-client-standards §8, STD-5;
spec-brain-typology-packs: its kinds are the typology catalog's ids). A first slice: what we produce (``--kind``, one
or several ids of the catalog), its stage (``--stage``), then, a plan then ``--apply``, the project's brain written by
``brain init`` from the profile template of its first kind that has one (``--template`` names another), with the
answers recorded in its registry entry: ``lifecycle: {typologies, stage}`` (brain item clauses reads its typologies).

STD-5: code products and research first. A kind whose entry is neither ``software`` nor ``research`` (creation,
strategy, marketing, hardware-cad, organisation, compliance) is named by the catalog but not offered yet: the plan
says so and writes nothing.

A later answer re-runs the same plan: in a folder that already holds the project's brain, the plan shows what the
answers change in its entry (its lifecycle, its standards' stage) and writes nothing: an existing registry changes
by a branch and a PR, as the cockpit's wizards say. The languages and tools, the data classes, the packs, procedures,
hooks and permissions the item names are later slices (its item's split).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import config, init, typologies

OFFERED = ("software", "research")   # STD-5: the entries the wizard offers first


class WizardError(ValueError):
    """An answer the wizard cannot take: nothing is planned (exit 2)."""


@dataclass
class Answers:
    kinds: list[str]
    stage: str                  # the standards' stage brain init takes
    lifecycle_stage: str        # the lifecycle's stage it reads as (brain typologies)
    template: str
    entries: list[str] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)   # the layers the kinds are proposed at the stage
    missing: list[str] = field(default_factory=list)  # those the template's graph does not hold

    def lifecycle(self) -> dict:
        return {"typologies": list(self.kinds), "stage": self.lifecycle_stage}


def templates_of(cat: typologies.Catalog) -> dict[str, str]:
    """{kind: the engine's profile template it takes}: a kind that names a template, else its entry's (trading:
    research)."""
    named = set(init.known_templates()) - {init.DEFAULT_TEMPLATE}
    out = {}
    for tid in cat.typologies:
        for k in cat.kinds(tid):
            if k in named:
                out[tid] = k
                break
    return out


def offered(cat: typologies.Catalog) -> list[str]:
    """The kinds the wizard offers with a template of their own (the cockpit's choices), in the catalog's order."""
    have = templates_of(cat)
    return [t for t in cat.typologies if t in have and cat.entry(t) in OFFERED]


def resolve(cat: typologies.Catalog, kinds: list[str], stage: str, template: str | None = None) -> Answers:
    """The answers checked: each kind an id of the catalog of an offered entry, the stage one of brain init's, the
    template the one given or the first kind's."""
    if not kinds:
        raise WizardError("--kind K: what the project produces, an id of the typology catalog (brain typologies)")
    for k in kinds:
        if not cat.known(k):
            raise WizardError(f"--kind {k}: not in the typology catalog (brain typologies lists the kinds)")
        if cat.entry(k) not in OFFERED:
            raise WizardError(f"--kind {k}: a kind of {cat.entry(k)}, named by the catalog and not offered yet "
                              "(STD-5: code products and research first; brain init DIR writes the generic brain)")
    if stage not in init.STAGES:
        raise WizardError(f"--stage {stage}: one of {', '.join(init.STAGES)}")
    have = templates_of(cat)
    chosen = template or next((have[k] for k in kinds if k in have), None)
    if chosen is None:
        raise WizardError(f"--kind {', '.join(kinds)}: no profile template of its own yet; --template one of "
                          f"{', '.join(sorted(set(have.values())))}, or a folder holding a template.yaml")
    layers: list[str] = []
    for k in kinds:
        layers += [la for la in typologies.layers(cat, k, stage) if la not in layers]
    try:
        graphs = init.load_template(chosen).graphs
    except init.InitError as exc:
        raise WizardError(f"--template {chosen}: {exc}") from None
    held = set(graphs[0].get("layers") or []) if graphs else set()
    return Answers(list(kinds), stage, cat.stage(stage), chosen, list(dict.fromkeys(cat.entry(k) for k in kinds)),
                   sorted(layers), sorted(set(layers) - held) if held else [])


def summary(cat: typologies.Catalog, a: Answers) -> list[str]:
    """The answers as the plan shows them, before brain init's own plan."""
    kinds = ", ".join(f"{k} ({cat.typologies[k].label()}, {cat.entry(k)} "
                      f"[{', '.join(cat.typologies[cat.entry(k)].vision)}])" for k in a.kinds)
    return [f"brain project new: what it produces: {kinds}",
            f"  stage: {a.stage} (the lifecycle's {a.lifecycle_stage}); template: {a.template}",
            f"  layers its kinds are proposed at {a.lifecycle_stage}: {', '.join(a.layers) or 'none'}"
            + (f"; not in the template's graph: {', '.join(a.missing)} (research_graph layers add, once written)"
               if a.missing else ""),
            f"  its registry entry records lifecycle: {{typologies: [{', '.join(a.kinds)}], "
            f"stage: {a.lifecycle_stage}}} (brain item clauses reads its typologies)"]


def existing(root: Path, name: str) -> dict | None:
    """The project's entry in the folder's projects.yaml when it already holds a brain, else None."""
    f = root / "projects.yaml"
    if not (root / config.FILE).is_file() or not f.is_file():
        return None
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    entry = data.get(name) if isinstance(data, dict) else None
    return entry if isinstance(entry, dict) else {}


def changes(entry: dict, a: Answers) -> list[str]:
    """What the answers change in an existing entry: its lifecycle's typologies and stage, its standards' stage."""
    lc = entry.get("lifecycle") if isinstance(entry.get("lifecycle"), dict) else {}
    std = entry.get("standards") if isinstance(entry.get("standards"), dict) else {}
    pairs = [("lifecycle.typologies", lc.get("typologies"), a.kinds),
             ("lifecycle.stage", lc.get("stage"), a.lifecycle_stage)]
    if std:
        pairs.append(("standards.stage", std.get("stage"), a.stage))
    return [f"  {key}: {old if old is not None else '(none)'} -> {new}" for key, old, new in pairs
            if (old if not isinstance(old, list) else list(old)) != new]


def main(args) -> int:
    root = Path(args.dir).resolve()
    try:
        cat = typologies.load(config.load(root))
        a = resolve(cat, list(dict.fromkeys(args.kinds or [])), args.stage, args.template)
    except (WizardError, typologies.CatalogError) as exc:
        print(f"brain project new: {exc}")
        return 2
    print("\n".join(summary(cat, a)))
    entry = existing(root, args.name)
    if entry is not None:
        diff = changes(entry, a)
        print(f"{root} already holds the brain of {args.name}: " + ("the answers change its entry in projects.yaml:"
                                                                   if diff else "the answers change nothing"))
        print("\n".join(diff) + ("\n(written by a branch and a PR of that brain, never here)" if diff else ""))
        return 2 if args.apply and diff else 0
    ns = _init_args(args, a)
    return init.main(ns)


def _init_args(args, a: Answers):
    """brain init's arguments for the answers: the template, the stage, the name, the owner, and the lifecycle."""
    import argparse
    return argparse.Namespace(dir=args.dir, owner=args.owner, template=a.template, kind="person", tenant=None,
                              tier=None, name=args.name, stage=a.stage, preset=None, with_=None, without=None,
                              catalogue=None, interactive=False, apply=args.apply, lifecycle=a.lifecycle())
