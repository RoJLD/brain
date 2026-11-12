"""``brain check``: records check, no conflict marker in the store, journals, decision logs and records, then
research_graph check (--all: every project's, then the registry and the ids across every store; in a brain's own
root, that registry check too).
"""

from __future__ import annotations

from pathlib import Path

from .. import docjoin, public
from ._common import _project, _scope, _store, root_of
from ._stores import _check_store, _each_store, _merge_marks, _registry_scope, _registry_too, check_registry

ORDER = 120   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 120   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain check [--all]   the records (schema, ids, secret scan), the open items attached to no milestone (a warning),
                        the proposed specs ready to turn active (a warning), the hard-rule ratio (Rule nodes with an enforced_by edge; a soft rule is a warning), the
                        generated views (a stale one: a warning on the default branch, an error under config.json
                        views.strict; one views: line on another branch; a warning outside git; brain views,
                        docs/views.md), members.yaml and the owner-decides answers' signatures (brain identity:
                        warnings, errors under config.json identity.require_signed; nothing without members.yaml,
                        docs/identity.md), then research_graph check (given
                        the project's other repos' checkouts, where the anchors of their Doc, Test and Workflow nodes are read); --all: every
                        project's, then the registry
                        (its keys, repos, stacks, code_index), the tier registry (every capability and stack declares
                        its class, profile, requirements, cost and fallback) and the ids, unique across every store of
                        every project (an id shared on purpose is waived under shared_ids:), and the edges between
                        stores (an edge may name another store's id: one whose end is in no store is an error with
                        --all, a warning in a brain's own root without it); at a root several projects share, each
                        one's stores (the root's own checks are its owner's). The registry's check judges the
                        projects' formats: and migrations: declarations; --formats then runs their check: commands
                        (brain formats check, opt-in: never on a plain brain check)
  brain check --public [--repo DIR] [--remote NAME] [--history] [--engine] [--json]   before a push to a public repo
                        (config.json public.repos), at zero token: no denied term (public.deny), secret, e-mail or home
                        folder, data or sealed file, nor a domain's patterns (public.patterns, public.refuse), nor the personal graph's
                        decision ids and titles or another project's ids (brain.privateids) in the
                        tracked files, and with --history in the commits not on the remote yet (gitleaks too when on
                        the PATH); green with --history, it stamps HEAD for the public guard on git push, keyed by
                        the engine version, the rules' hash and gitleaks (a change of any: rerun it); --engine:
                        the files brain boundary sends to the engine, in this checkout (a dry run)
  brain check --public --refresh   the same with --history in every local checkout of a public repo (the
                        registry's repos whose remote is in public.repos), by this engine: what the installer's -Apply
                        and brain update run after an install, so that no stamp is left of the old engine; a HEAD
                        already stamped is left, a checkout with uncommitted work skipped and named
"""


def cmd_check(args, root: Path) -> int:
    rc = _cmd_check(args, root)
    if getattr(args, "formats", False):   # opt-in (PF-1): the projects' format checks, after the rest
        from .formats import run_scope
        print("== formats")
        rc = run_scope(_scope(args, root, root_shared=True)) or rc
    return rc


def _cmd_check(args, root: Path) -> int:
    _merge_marks(root, "brain refresh regenerates them")
    if args.all:
        return _each_store(args, root, sync=False, check=True)
    scope = _scope(args, root, root_shared=True)
    if len(scope) > 1:   # the projects that share this root
        return _each_store(args, root, sync=False, check=True, scope=scope)
    rc = _check_store(args, root, _store(args, root))
    if _registry_too(args, root):   # a brain's own root: its own data too, as refresh checks it
        print("== registry")
        rc = check_registry(root, _registry_scope(root)) or rc
        for line in docjoin.check_lines(root, _project(args, root).name):   # a document under docgraph/ the join leaves out (wi-brain-docgraph-read)
            print(f"warning: {line}")
    return rc


def register(sub, ctx) -> None:
    ck = sub.add_parser("check", help="records check, no conflict marker in the store, journals, decision logs and "
                                      "records, then research_graph check (--all: every project's, then the "
                                      "registry and the ids across every store; in a brain's own root, that "
                                      "registry check too)")
    ck.add_argument("--all", action="store_true", help="every project of the registry, then the registry's keys, "
                                                       "repos, stacks and code_index, the ids across every store and "
                                                       "the edges between stores (one to an id in no store: an error)")
    ck.add_argument("--formats", action="store_true", help="then run the projects' format checks (projects.yaml "
                                                           "formats: check:, as brain formats check does): opt-in")
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
    ck.add_argument("--refresh", action="store_true", help="--public: --history in every local checkout of a public "
                                                           "repo (the registry's), by this engine; a checkout with "
                                                           "uncommitted work is skipped and named")


def early(args) -> int | None:
    if args.public and args.refresh:   # the installer's -Apply and brain update, after an install
        code, lines = public.refresh(root=root_of(args))
        print("\n".join(lines))
        return code
    if args.public:  # a public repo has no graph store: before find_root
        root = root_of(args)
        return public.main(Path(args.repo).resolve() if args.repo else root or Path.cwd(), history=args.history,
                           remote=args.remote or "", engine=args.engine, as_json=args.json)
    return None


run = cmd_check
