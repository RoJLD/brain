"""``brain review``: the review before the report, its zero-token part (brain.review, docs/review.md): the packet a
session's lens agents read, the stamp of a head once reviewed, and the check the merge gate asks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import review

ORDER = 57   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 57   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain review prep [PR | BASE..HEAD] [--item ID] [--out DIR] [--no-scout] [--json]   the review packet at zero
                 token: the diff, the touched files at the head, brain audit --diff's output, the lenses the touched
                 surfaces call for, the invariants and failure modes to test (the item's brief section with --item)
                 and how to run them (default origin/main..HEAD, into <BRAIN_HOME>/reviews/<head>)
  brain review stamp HEAD --findings N --fixed M [--contested K] [--note FILE]   the review of that head ran
  brain review check HEAD   exit 0 when that head was reviewed, 1 when not (the merge gate's question)
"""


def early(args) -> int:
    """Any repo, a brain or not: the review is of a PR, never of a brain's data."""
    return cmd_review(args)


def _modes(repo: Path, proj, item: str | None):
    """(the failure modes' builder, whether the repo is public) for brain review prep: with ``--item``, the brief's
    section of that item of the repo's project (brain.brief.failure_modes) plus the diff's; without, the diff's alone
    (brain.failuremodes), the public line when the repo is in config.json ``public.repos``."""
    from .. import config, public
    try:
        cfg = config.load(proj.root if proj is not None else None)
        pub = public.is_public(public.remote_of(repo, cfg)[1], cfg)
    except Exception:  # noqa: BLE001 - a remote or a config that cannot be read: no public line, never no packet
        pub = False
    if not item:
        return None, pub
    if proj is None:
        raise review.ReviewError(f"--item {item}: this repo belongs to no registered project (projects.yaml)")
    from .. import brief
    try:
        st, node, _ = brief._find(proj, item)
    except brief.BriefError as exc:
        raise review.ReviewError(f"--item {item}: {exc}") from None
    return (lambda files, changed: brief.failure_modes(proj, st, node, cfg, files, changed)), pub


def cmd_review(args, root: Path | None = None) -> int:
    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    try:
        if args.review_cmd == "prep":
            from .. import standards
            proj, rows = standards.project_of_repo(repo), []
            try:
                rows = standards.lenses(proj) if proj is not None else []
            except standards.StandardsError as exc:   # the packet without the standards lens, said
                print(f"review: no standards lens: {exc}", file=sys.stderr)
            modes, pub = _modes(repo, proj, args.item)
            p = review.prep(repo, args.target or "", Path(args.out) if args.out else None, scout=not args.no_scout,
                            standards=rows, item=args.item or "", modes=modes, public=pub)
            if args.json:
                print(json.dumps(p.__dict__, indent=2))
            else:
                print(f"review: packet of {p.head[:12]} (base {p.base[:12]}): {len(p.files)} file(s), lenses "
                      f"{', '.join(p.lenses)}" + (f", scout exit {p.scout_rc}" if p.scout_rc is not None else "")
                      + f"\n  {p.folder}/README.md (docs/review.md: the agents, the skeptics, then brain review stamp)")
            return 0
        if args.review_cmd == "stamp":
            note = Path(args.note).read_text(encoding="utf-8") if args.note else ""
            f = review.stamp(args.head, args.findings, args.fixed, args.contested, note, repo)
            print(f"review: {f.stem[:12]} stamped ({args.findings} finding(s), {args.fixed} fixed, {args.contested} "
                  f"contested): {f}")
            return 0
        rec = review.check(args.head, repo)
    except (review.ReviewError, OSError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if rec is None:
        print(f"review: {args.head} not reviewed (brain review prep, docs/review.md, then brain review stamp)")
        return 1
    print(f"review: {rec['head'][:12]} reviewed {rec['at']}: {rec['findings']} finding(s), {rec['fixed']} fixed, "
          f"{rec['contested']} contested, {rec['open']} open")
    return 0


def register(sub, ctx) -> None:
    rv = sub.add_parser("review", help="the review before the report: its packet at zero token, the stamp of a "
                                       "reviewed head, the merge gate's check").add_subparsers(dest="review_cmd",
                                                                                               required=True)
    pr = rv.add_parser("prep", help="the packet: diff, files at the head, the scout, the lenses (zero token)")
    pr.add_argument("target", nargs="?", help="a PR number (gh) or BASE..HEAD (default origin/main..HEAD)")
    pr.add_argument("--out", help="the packet's folder (default <BRAIN_HOME>/reviews/<head>)")
    pr.add_argument("--no-scout", action="store_true", help="leave brain audit --diff out")
    pr.add_argument("--item", help="the item the PR delivers: its brief's « Invariants and failure modes to test » "
                                   "join the diff's in the packet")
    pr.add_argument("--json", action="store_true")
    st = rv.add_parser("stamp", help="the review of HEAD ran: its counts")
    st.add_argument("head")
    st.add_argument("--findings", type=int, required=True)
    st.add_argument("--fixed", type=int, required=True)
    st.add_argument("--contested", type=int, default=0)
    st.add_argument("--note", help="the review note (a file), kept with the stamp")
    ck = rv.add_parser("check", help="exit 0 when HEAD was reviewed")
    ck.add_argument("head")
    for p in (pr, st, ck):
        p.add_argument("--repo", help="the repo (default: here)")



