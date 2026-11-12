"""``brain reference``: the technical reference, generated (brain.reference, wi-brain-technical-reference):
docs/reference/README.md and modules/<id>.md per module of the store's registry; ``--public`` renders a public repo's
neutral reference by feature domain into a checkout of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import asof, config, reference, skew
from ._common import _root_repo, _store, _store_label

ORDER = 46   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 33   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain reference [--write [--force]] [--public --repo R --out DIR]   the technical reference: docs/reference/
                 README.md, the twelve arc42 sections from the graph (goals and milestones, constraints from the
                 rules, context from the registry, strategy and its key decisions, building blocks, runtime,
                 deployment, concepts, the decisions by module, quality from the milestones' triggers and tests,
                 risks and debt, glossary), the prose from docs/reference.yaml (exit 1 when a required field is
                 missing), and modules/<id>.md per module of the store's modules.yaml (what it does from its
                 features, the decisions in force on its nodes from the answered DDRs, earlier ones folded, an ADR no
                 DDR went to by its title; its rules, specs, items done and open, open questions); no --write: exit 1
                 when docs/reference/ is not the render; a page there that is not generated is never overwritten.
                 Once written, brain sync keeps it current (the owner's opt-in). --public: a public repo's neutral
                 reference by feature domain (its features' public titles, its own code and docs, the goals,
                 strategy and glossary of its own docs/reference.yaml), into --out (a checkout's docs/reference),
                 written only when brain check --public would refuse none of it; --force: write under views.strict
                 with another engine than the pin
  brain reference --asof POINT [--out DIR]   the reference as of a wave (its id or release), a milestone or an era
                 (the commit of the day it was reached; a pending one as of now, with its target view: the features
                 and items planned in it), a date or a git ref, read from git (nothing checked out), with « Changes
                 since » the wave reached before (decisions taken and reversed, features whose status changed, items
                 done, modules added); written under BRAIN_HOME/views/reference/<project>/<point>/, never the repo
"""


def _target(args, root: Path) -> Path:
    return Path(args.out).resolve() if getattr(args, "out", "") else root / reference.DIR


def files_for(args, root: Path) -> dict[str, str]:
    store = _store(args, root)
    if getattr(args, "public", False):
        where = _prose_root(args, root)
        prose = reference.load_prose(where)[0] if where is not None else {}   # the checkout's own docs/reference.yaml
        return reference.render_public(store, args.repo or _root_repo(args, root), _root_repo(args, root), prose)
    return reference.render(root, store, _store_label(root, store))


def _prose_root(args, root: Path) -> Path | None:
    """The repo whose docs/reference.yaml the render reads: the root's; with --public, the checkout --out names
    (<checkout>/docs/reference), None when --out is not such a folder (no prose read)."""
    if not args.public:
        return root
    out = _target(args, root)
    return out.parent.parent if (out.parent.name, out.name) == ("docs", "reference") else None


def _prose_refused(where: Path | None) -> bool:
    """Whether that docs/reference.yaml breaks its schema: each error said; the render is then refused, as the
    README's YAML's."""
    errors = reference.load_prose(where)[1] if where is not None else []
    for line in errors:
        print(f"error: {line} (schemas/reference.schema.json)", file=sys.stderr)
    return bool(errors)


def _denied(args, root: Path, files: dict[str, str]) -> list[str]:
    """--public: what brain check --public would refuse in the render (never written into a public repo), each said."""
    denied = reference.denied(files, config.load(root)) if args.public else []
    for line in denied:
        print(f"brain: the public reference: {line} (brain features set <feature> public_title=... or public_id=...)",
              file=sys.stderr)
    return denied


def _asof(args, root: Path) -> int:
    """--asof: the reference as of a point, written under BRAIN_HOME/views (or --out), never into the repo."""
    from ._common import _project
    if args.public or args.write:
        print("brain reference --asof: renders under BRAIN_HOME/views (or --out), never --public nor --write",
              file=sys.stderr)
        return 1
    try:
        point, files = asof.render(_store(args, root), args.asof)
    except asof.AsofError as exc:
        print(f"brain reference --asof: {exc}", file=sys.stderr)
        return 1
    base = Path(args.out).resolve() if args.out else asof.out_dir(_project(args, root).name, point)
    changed, kept = reference.write(base, files)
    for p in kept:
        print(f"brain: {base / p} is not generated (no '{reference.MARKER}'): kept, not overwritten", file=sys.stderr)
    print(f"reference as of {point.label} ({point.sha[:12]}{', ' + point.day if point.day else ''}): {len(files)} "
          f"file(s) in {base}")
    return 1 if kept else 0


def cmd_reference(args, root: Path) -> int:
    if args.asof:
        return _asof(args, root)
    if args.public and not args.out:
        print("brain reference --public: give --out <a checkout of the public repo>/docs/reference", file=sys.stderr)
        return 1
    files = files_for(args, root)
    base = _target(args, root)
    if _prose_refused(_prose_root(args, root)):
        return 1
    denied = _denied(args, root, files)
    if not args.write:
        late = reference.stale(base, files)
        print("\n".join(f"{reference.DIR}/{p}: not the render" for p in late) or f"{reference.DIR}: up to date")
        return 1 if late or denied else 0
    if denied:
        print(f"brain reference --public: {len(denied)} line(s) a public check would refuse: nothing written",
              file=sys.stderr)
        return 1
    if skew.refuse_view(root, "reference --write", args.force, f"the committed {reference.DIR}"):
        return 1
    changed, kept = reference.write(base, files)
    for p in kept:
        print(f"brain: {base / p} is not generated (no '{reference.MARKER}'): kept, not overwritten", file=sys.stderr)
    print(f"reference: {len(changed)} file(s) written in {base}" if changed else "reference: unchanged")
    return 1 if kept else 0


def register(sub, ctx) -> None:
    rf = sub.add_parser("reference", help="the technical reference: docs/reference/, one page per module, the "
                                          "decisions in force (brain.reference)")
    rf.add_argument("--write", action="store_true", help="write docs/reference/ (brain sync does once it exists)")
    rf.add_argument("--force", action="store_true", help="--write even when the running engine is not config.json "
                                                         "engine.pin (refused under views.strict)")
    rf.add_argument("--public", action="store_true", help="the neutral reference of a public repo, by feature domain")
    rf.add_argument("--repo", default="", help="with --public: the repo whose features it renders")
    rf.add_argument("--out", default="", help="the docs/reference folder to write or check (a checkout's); with "
                                             "--asof, where the render goes")
    rf.add_argument("--asof", default="", metavar="POINT",
                    help="the reference as of a wave (id or release), a milestone, an era, a date (YYYY-MM-DD) or a "
                         "git ref, read from git, with « Changes since » the wave before and, for a pending milestone, "
                         "its target view; written under BRAIN_HOME/views/reference/<project>/<point>/")


run = cmd_reference
