"""``brain typologies``: the typology catalog (brain.typologies, wi-brain-typology-catalog): its entries and their
sub-profiles, with the brain's labels (config.json typologies), the lifecycle's stages and the standards' stages mapped
to them; ``show ID``: one id, its entry and, with ``--stage``, the graph layers it is proposed there; ``packs``: the
typology packs (brain.typology_packs, wi-brain-typology-packs), the engine's and the brain's; ``propose PROJECT``: the
packs a project's typologies propose, a plan, then ``--apply`` writes packs.yaml (TYPO-4)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import config, neutral, status, typologies, typology_packs

ORDER = 192   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 222   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain typologies [--lang en|fr] [--json]   the typology catalog: the kinds of project (software, research,
                 hardware-cad, creation, strategy, marketing, organisation, compliance), each with its column to the
                 Vision's modules (J1...K4) and its sub-profiles (cli, service, trading...), the lifecycle's stages and
                 the standards' stages mapped to them; config.json typologies renames labels and adds a brain's ids
  brain typologies show ID [--stage S] [--lang en|fr] [--json]   one id: its entry, labels and description; --stage
                 (a lifecycle or standards stage): the graph layers a project of that kind is proposed there
  brain typologies packs [--json]   the typology packs: the engine's (software, research) and this brain's
                 (source/packs.yaml), each with its typologies and parts (layers, standards, stages, done, doors,
                 roles, guards, registry keys) and the projects that take it
  brain typologies propose PROJECT [--apply] [--json]   the packs the project's lifecycle.typologies meet: those it
                 takes, and for each other the step that gives it (a pack from: engine with projects: [PROJECT], or
                 PROJECT added to a pack's projects), the layers its store lacks and the standards profiles it does
                 not opt in to; --apply writes packs.yaml's steps (comments kept; refused if brain check would fail),
                 the layers and standards stay the owner's next steps (TYPO-4: nothing turns on by itself)
"""


def cmd_typologies(args, root: Path) -> int:
    cfg = config.load(root)
    try:
        cat = typologies.load(cfg)
    except typologies.CatalogError as exc:
        raise SystemExit(f"brain: {exc} (reinstall the engine)") from None
    if getattr(args, "typ_cmd", None) == "show":
        return _show(cat, args)
    if getattr(args, "typ_cmd", None) == "packs":
        return _packs(root, args)
    if getattr(args, "typ_cmd", None) == "propose":
        return _propose(root, args)
    if args.json:
        print(json.dumps(typologies.describe(cat, args.lang), ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    for t in cat.entries():
        mark = "" if t.origin == "engine" else f" ({t.origin})"
        print("\n".join(status._row(t.id, f"{t.label(args.lang)} [{', '.join(t.vision) or '-'}]{mark}: "
                                          f"{t.description}")))
        for s in cat.subs(t.id):
            mark = "" if s.origin == "engine" else f" ({s.origin})"
            print("\n".join(status._row(f"  {s.id}", f"{s.label(args.lang)}{mark}: {s.description}")))
    stages = ", ".join(f"{sid} ({'/'.join(spec.get('shapes', []))})" for sid, spec in cat.stages.items())
    print(f"stages: {stages}")
    print("standards stages: " + ", ".join(f"{k} -> {v}" for k, v in cat.standards_stages.items()))
    return 0


def _show(cat: typologies.Catalog, args) -> int:
    tid = args.id
    if not cat.known(tid):
        print(f"{tid}: not in the typology catalog (an id of a later catalog is tolerated where a brain names it); "
              "brain typologies lists the known ones")
        return 1
    t = cat.typologies[tid]
    entry = cat.typologies[cat.entry(tid)]
    data = {"id": tid, "label": t.label(args.lang), "labels": t.labels, "description": t.description,
            "entry": entry.id, "vision": list(entry.vision), "origin": t.origin,
            "sub": [s.id for s in cat.subs(tid)]}
    if args.stage:
        data["stage"] = cat.stage(args.stage)
        data["layers"] = typologies.layers(cat, tid, args.stage)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    kind = "an entry" if not t.parent else f"a sub-profile of {entry.id}"
    print(f"{tid}: {data['label']}, {kind} [{', '.join(entry.vision) or '-'}]")
    if t.description:
        print(f"  {t.description}")
    if data["sub"]:
        print(f"  sub-profiles: {', '.join(data['sub'])}")
    if args.stage:
        named = "" if data["stage"] == args.stage else f" (read as {data['stage']})"
        print(f"  layers proposed at {args.stage}{named}: {', '.join(data['layers']) or 'none'}")
    return 0


def _packs(root: Path, args) -> int:
    """The engine's typology packs and the brain's packs that name typologies (or take one from the engine)."""
    try:
        engine = typology_packs.engine()
    except typology_packs.PackError as exc:
        raise SystemExit(f"brain: {exc} (reinstall the engine)") from None
    src = neutral.load(root) if neutral.applies(root) else None
    own = {p.id: p for p in (src.packs if src else []) if p.spec.get("typologies") or p.spec.get(typology_packs.FROM)}
    rows = []
    for pid, spec in engine.items():
        p = own.get(pid)
        rows.append({"id": pid, "origin": "engine", "taken": p is not None and p.spec.get(typology_packs.FROM) == "engine",
                     "projects": (p.projects if p else []), **_parts(p.spec if p else spec)})
    for pid, p in own.items():
        if pid not in engine:
            rows.append({"id": pid, "origin": neutral.PACKS, "taken": True, "projects": p.projects,
                         **_parts(p.spec)})
    if args.json:
        print(json.dumps({"packs": rows}, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    for r in rows:
        whom = ("every project" if r["projects"] is None else ", ".join(r["projects"]) or "no project")
        state = f"taken for {whom}" if r["taken"] else "not taken (brain typologies propose PROJECT)"
        print(f"{r['id']} ({r['origin']}): for {', '.join(r['typologies']) or '-'}; {state}")
        for key in typology_packs.PARTS[1:]:
            value = r.get(key)
            if value:
                print(f"  {key}: {_short(value)}")
    return 0


def _parts(spec: dict) -> dict:
    return {k: spec.get(k) or ([] if k not in ("standards", "stages") else {}) for k in typology_packs.PARTS}


def _short(value) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in value.items())
    return ", ".join(str(x.get("id")) if isinstance(x, dict) else str(x) for x in value)


def _propose(root: Path, args) -> int:
    try:
        kinds, props, store = typology_packs.propose(root, args.name)
    except (typology_packs.ProposeError, typology_packs.PackError) as exc:
        print(f"brain typologies propose: {exc}")
        return 2
    written: list[str] = []
    if args.apply and any(p.step for p in props):
        try:
            written = typology_packs.apply(root, args.name, props)
        except ValueError as exc:
            print(f"brain typologies propose: {exc}; nothing written")
            return 1
    if args.json:
        print(json.dumps({"project": args.name, "typologies": kinds, "packs": [p.as_dict() for p in props],
                          "store": store.as_posix() if store else None, "written": written},
                         ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    print("\n".join(typology_packs.plan_lines(args.name, kinds, props, store)))
    for line in written:
        print(f"written: {line}")
    if written:
        print("next: brain render (or brain sync) renders what the packs carry; a PR of this brain records it")
    elif any(p.step for p in props) and not args.apply:
        print(f"(plan only: brain typologies propose {args.name} --apply writes it)")
    return 0


def register(sub, ctx) -> None:
    ty = sub.add_parser("typologies", help="the typology catalog: the kinds of project, their sub-profiles and "
                                           "stages (brain.typologies)")
    ty.add_argument("--lang", choices=typologies.LANGS, default="en", help="the labels' language (default en)")
    ty.add_argument("--json", action="store_true", help="stable keys")
    tsub = ty.add_subparsers(dest="typ_cmd")
    sh = tsub.add_parser("show", help="one typology id: its entry, labels and the layers proposed at a stage")
    sh.add_argument("id", help="a typology id (an entry or a sub-profile)")
    sh.add_argument("--stage", help="a lifecycle stage (explore, build...) or a standards stage (prototype, mvp...)")
    # SUPPRESS: given before show (brain typologies --json show X), the parent's value stays
    sh.add_argument("--lang", choices=typologies.LANGS, default=argparse.SUPPRESS,
                    help="the labels' language (default en)")
    sh.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="stable keys")
    pk = tsub.add_parser("packs", help="the typology packs: the engine's and this brain's, their typologies and parts")
    pk.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="stable keys")
    pp = tsub.add_parser("propose", help="the packs a project's typologies propose: a plan, then --apply writes "
                                         "packs.yaml")
    # its dest: the parent's --project is another flag (the project acted on)
    pp.add_argument("name", metavar="PROJECT", help="a project of this brain's registry (projects.yaml)")
    pp.add_argument("--apply", action="store_true", help="write packs.yaml's steps (default: the plan)")
    pp.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="stable keys")


run = cmd_typologies
