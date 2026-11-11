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
                 README.md and modules/<id>.md per module of the store's modules.yaml (what it does from its
                 features, the decisions in force on its nodes from the answered DDRs, earlier ones folded, an ADR no
                 DDR went to by its title; its rules, specs, items done and open, open questions), and the decisions
                 no module holds; no --write: exit 1 when docs/reference/ is not the render. brain sync writes it once
                 docs/reference/ exists. --public: a public repo's neutral reference by feature domain (its features'
                 public titles, its own code and docs), into --out (a checkout's docs/reference)
"""


def _target(args, root: Path) -> Path:
    return Path(args.out).resolve() if getattr(args, "out", "") else root / reference.DIR


def files_for(args, root: Path) -> dict[str, str]:
    store = _store(args, root)
    if getattr(args, "public", False):
        return reference.render_public(store, args.repo or _root_repo(args, root), _root_repo(args, root))
    return reference.render(root, store, _store_label(root, store))


def cmd_reference(args, root: Path) -> int:
    if args.public and not args.out:
        print("brain reference --public: give --out <a checkout of the public repo>/docs/reference", file=sys.stderr)
        return 1
    files = files_for(args, root)
    base = _target(args, root)
    if args.public:
        for line in reference.denied(files, config.load(root)):
            print(f"brain: warning: the public reference: {line} (brain features set <feature> public_title=...)",
                  file=sys.stderr)
    if not args.write:
        late = reference.stale(base, files)
        print("\n".join(f"{reference.DIR}/{p}: not the render" for p in late) or f"{reference.DIR}: up to date")
        return 1 if late else 0
    if skew.refuse_view(root, "reference --write", args.force, f"the committed {reference.DIR}"):
        return 1
    changed = reference.write(base, files)
    print(f"reference: {len(changed)} file(s) written in {base}" if changed else "reference: unchanged")
    return 0


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
