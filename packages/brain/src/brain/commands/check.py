"""``brain check``: records check, no conflict marker in the store, journals, decision logs and records, then
research_graph check (--all: every project's, then the registry and the ids across every store; in a brain's own
root, that registry check too).
"""

from __future__ import annotations

from pathlib import Path

from .. import public
from ._common import _store, root_of
from ._stores import _check_store, _each_store, _merge_marks, _registry_scope, _registry_too, check_registry

ORDER = 120   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 120   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain check [--all]   the records (schema, ids, secret scan), the open items attached to no milestone (a warning),
                        the proposed specs ready to turn active (a warning), the hard-rule ratio (Rule nodes with an enforced_by edge; a soft rule is a warning), a stale
                        links graph (a warning), then research_graph check (given the project's other repos'
                        checkouts, where the anchors of their Doc, Test and Workflow nodes are read); --all: every
                        project's, then the registry
                        (its keys, repos, stacks, code_index), the tier registry (every capability and stack declares
                        its class, profile, requirements, cost and fallback) and the ids, unique across every store of
                        every project (an id shared on purpose is waived under shared_ids:)
  brain check --public [--repo DIR] [--remote NAME] [--history] [--engine] [--json]   before a push to a public repo
                        (config.json public.repos), at zero token: no denied term (public.deny), secret, e-mail or home
                        folder, data or sealed file, nor a domain's patterns (public.patterns, public.refuse) in the
                        tracked files, and with --history in the commits not on the remote yet (gitleaks too when on
                        the PATH); green with --history, it stamps HEAD for the public guard on git push; --engine:
                        the files brain boundary sends to the engine, in this checkout (a dry run)
"""


def cmd_check(args, root: Path) -> int:
    _merge_marks(root, "brain refresh regenerates them")
    if args.all:
        return _each_store(args, root, sync=False, check=True)
    rc = _check_store(args, root, _store(args, root))
    if _registry_too(args, root):   # a brain's own root: its own data too, as refresh checks it
        print("== registry")
        rc = check_registry(root, _registry_scope(root)) or rc
    return rc


def register(sub, ctx) -> None:
    ck = sub.add_parser("check", help="records check, no conflict marker in the store, journals, decision logs and "
                                      "records, then research_graph check (--all: every project's, then the "
                                      "registry and the ids across every store; in a brain's own root, that "
                                      "registry check too)")
    ck.add_argument("--all", action="store_true", help="every project of the registry, then the registry's keys, "
                                                       "repos, stacks and code_index, and the ids across every store")
    ck.add_argument("--public", action="store_true", help="before a push to a public repo: no private term, secret, "
                                                          "personal data, data file or domain pattern (brain.public)")
    ck.add_argument("--repo", help="--public: the checkout to check (default: --root, else the current folder)")
    ck.add_argument("--remote", help="--public: the remote the push goes to (default: the one of public.repos, "
                                     "else origin)")
    ck.add_argument("--history", action="store_true", help="--public: the commits not on the remote yet too; a "
                                                           "green check stamps HEAD for the public guard")
    ck.add_argument("--engine", action="store_true", help="--public: the engine side of this checkout "
                                                          "(boundary.yaml), the extraction's dry run")
    ck.add_argument("--json", action="store_true", help="--public: stable keys")


def early(args) -> int | None:
    if args.public:  # a public repo has no graph store: before find_root
        root = root_of(args)
        return public.main(Path(args.repo).resolve() if args.repo else root or Path.cwd(), history=args.history,
                           remote=args.remote or "", engine=args.engine, as_json=args.json)
    return None


run = cmd_check
