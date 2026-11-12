"""``brain typologies``: the typology catalog (brain.typologies, wi-brain-typology-catalog): its entries and their
sub-profiles, with the brain's labels (config.json typologies), the lifecycle's stages and the standards' stages mapped
to them; ``show ID``: one id, its entry and, with ``--stage``, the graph layers it is proposed there."""

from __future__ import annotations

import json
from pathlib import Path

from .. import config, status, typologies

ORDER = 192   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 222   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain typologies [--lang en|fr] [--json]   the typology catalog: the kinds of project (software, research,
                 hardware-cad, creation, strategy, marketing, organisation, compliance), each with its column to the
                 Vision's modules (J1...K4) and its sub-profiles (cli, service, trading...), the lifecycle's stages and
                 the standards' stages mapped to them; config.json typologies renames labels and adds a brain's ids
  brain typologies show ID [--stage S] [--lang en|fr] [--json]   one id: its entry, labels and description; --stage
                 (a lifecycle or standards stage): the graph layers a project of that kind is proposed there
"""


def cmd_typologies(args, root: Path) -> int:
    cfg = config.load(root)
    try:
        cat = typologies.load(cfg)
    except typologies.CatalogError as exc:
        raise SystemExit(f"brain: {exc} (reinstall the engine)") from None
    if getattr(args, "typ_cmd", None) == "show":
        return _show(cat, args)
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


def register(sub, ctx) -> None:
    ty = sub.add_parser("typologies", help="the typology catalog: the kinds of project, their sub-profiles and "
                                           "stages (brain.typologies)")
    ty.add_argument("--lang", choices=typologies.LANGS, default="en", help="the labels' language (default en)")
    ty.add_argument("--json", action="store_true", help="stable keys")
    tsub = ty.add_subparsers(dest="typ_cmd")
    sh = tsub.add_parser("show", help="one typology id: its entry, labels and the layers proposed at a stage")
    sh.add_argument("id", help="a typology id (an entry or a sub-profile)")
    sh.add_argument("--stage", help="a lifecycle stage (explore, build...) or a standards stage (prototype, mvp...)")
    sh.add_argument("--lang", choices=typologies.LANGS, default="en", help="the labels' language (default en)")
    sh.add_argument("--json", action="store_true", help="stable keys")


run = cmd_typologies
