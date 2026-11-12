"""``brain reference``: the technical reference, generated (brain.reference, wi-brain-technical-reference):
docs/reference/README.md and modules/<id>.md per module of the store's registry; ``--public`` renders a public repo's
neutral reference by feature domain into a checkout of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import config, reference, skew
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
"""


def _target(args, root: Path) -> Path:
    return Path(args.out).resolve() if getattr(args, "out", "") else root / reference.DIR


def files_for(args, root: Path) -> dict[str, str]:
    store = _store(args, root)
    if getattr(args, "public", False):
        prose = reference.load_prose(_target(args, root).parent.parent)[0]   # the checkout's own docs/reference.yaml
        return reference.render_public(store, args.repo or _root_repo(args, root), _root_repo(args, root), prose)
    return reference.render(root, store, _store_label(root, store))


def cmd_reference(args, root: Path) -> int:
    if args.public and not args.out:
        print("brain reference --public: give --out <a checkout of the public repo>/docs/reference", file=sys.stderr)
        return 1
    files = files_for(args, root)
    base = _target(args, root)
    prose_errors = reference.load_prose(base.parent.parent)[1]   # <repo>/docs/reference.yaml
    for line in prose_errors:   # a required field missing: the render is refused, as the README's YAML's
        print(f"error: {line} (schemas/reference.schema.json)", file=sys.stderr)
    if prose_errors:
        return 1
    denied = reference.denied(files, config.load(root)) if args.public else []
    for line in denied:   # what brain check --public would refuse: never written into a public repo
        print(f"brain: the public reference: {line} (brain features set <feature> public_title=... or public_id=...)",
              file=sys.stderr)
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
    rf.add_argument("--out", default="", help="the docs/reference folder to write or check (a checkout's)")


run = cmd_reference
