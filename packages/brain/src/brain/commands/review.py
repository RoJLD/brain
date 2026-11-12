"""``brain review``: the review before the report, its zero-token part (brain.review, docs/review.md): the packet a
session's lens agents read, the stamp of a head once reviewed, and the check the merge gate asks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .. import review
from ..inventory import AuditError

ORDER = 57   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 57   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain review prep [PR | BASE..HEAD] [--out DIR] [--no-scout] [--json]   the review packet at zero token: the
                 diff, the touched files at the head, brain audit --diff's output, the lenses the touched surfaces
                 call for and how to run them (default origin/main..HEAD, into <BRAIN_HOME>/reviews/<head>)
  brain review stamp HEAD --findings N --fixed M [--contested K] [--note FILE]   the review of that head ran
  brain review check HEAD [--pr N | --body FILE] [--base REF]   exit 0 when that head was reviewed, 1 when not (the
                 merge gate's question); with the PR body, 1 also while a pinned decision the change touches (brain
                 adr pin, docs/pins.md) has no Keeps ID line in it (a decision in force) or Overrides ID: why (one a
                 later ADR supersedes); without one, the pins touched are listed and the stamp alone decides
"""


def early(args) -> int:
    """Any repo, a brain or not: the review is of a PR, never of a brain's data."""
    return cmd_review(args)


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
            p = review.prep(repo, args.target or "", Path(args.out) if args.out else None, scout=not args.no_scout,
                            standards=rows)
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
        return _check(args, repo)
    except (review.ReviewError, OSError) as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1


def _check(args, repo: Path) -> int:
    """brain review check: the stamp of the head, then the pinned decisions the change touches (with the PR body,
    each kept or overridden)."""
    rec = review.check(args.head, repo)
    touched, blocks, note = _pins(args, repo)
    if rec is None:
        print(f"review: {args.head} not reviewed (brain review prep, docs/review.md, then brain review stamp)")
    else:
        print(f"review: {rec['head'][:12]} reviewed {rec['at']}: {rec['findings']} finding(s), {rec['fixed']} fixed, "
              f"{rec['contested']} contested, {rec['open']} open")
    for x in touched:
        print(f"  pinned: {x['id']} ({x['day'] or '?'}) holds {x['holds']} ({', '.join(x['hits'][:3])})")
    for b in blocks:
        print(f"  BLOCK {b}")
    if note:
        print(f"  note: {note}")
    return 1 if rec is None or blocks else 0


def _pins(args, repo: Path) -> tuple[list[dict], list[str], str]:
    """(the pinned decisions the change touches, what blocks it, a note), from the PR body (--pr or --body). Without
    a body the pins are listed unjudged, and one that cannot be read is a note: the stamp alone decides then; with a
    body, it blocks."""
    body, base = None, args.base or ""
    try:
        if args.pr:
            r = subprocess.run(["gh", "pr", "view", str(args.pr), "--json", "body,baseRefName"], cwd=repo,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            if r.returncode:
                raise review.ReviewError(f"PR {args.pr}: {(r.stderr or r.stdout).strip()}")
            info = json.loads(r.stdout)
            body, base = str(info.get("body") or ""), base or f"origin/{info.get('baseRefName') or 'main'}"
        elif args.body:
            body = Path(args.body).read_text(encoding="utf-8")
        touched, blocks = review.pins_gate(repo, base or "origin/main", args.head, body)
    except (review.ReviewError, AuditError, OSError, ValueError, subprocess.SubprocessError) as exc:
        if body is None and not args.pr and not args.body:
            return [], [], f"the pins could not be read: {exc}"
        return [], [f"the pins could not be read: {exc}"], ""
    return touched, (blocks if body is not None else []), ""


def register(sub, ctx) -> None:
    rv = sub.add_parser("review", help="the review before the report: its packet at zero token, the stamp of a "
                                       "reviewed head, the merge gate's check").add_subparsers(dest="review_cmd",
                                                                                               required=True)
    pr = rv.add_parser("prep", help="the packet: diff, files at the head, the scout, the lenses (zero token)")
    pr.add_argument("target", nargs="?", help="a PR number (gh) or BASE..HEAD (default origin/main..HEAD)")
    pr.add_argument("--out", help="the packet's folder (default <BRAIN_HOME>/reviews/<head>)")
    pr.add_argument("--no-scout", action="store_true", help="leave brain audit --diff out")
    pr.add_argument("--json", action="store_true")
    st = rv.add_parser("stamp", help="the review of HEAD ran: its counts")
    st.add_argument("head")
    st.add_argument("--findings", type=int, required=True)
    st.add_argument("--fixed", type=int, required=True)
    st.add_argument("--contested", type=int, default=0)
    st.add_argument("--note", help="the review note (a file), kept with the stamp")
    ck = rv.add_parser("check", help="exit 0 when HEAD was reviewed")
    ck.add_argument("head")
    ck.add_argument("--pr", type=int, help="the PR whose body must keep or override each pinned decision touched")
    ck.add_argument("--body", help="the PR body, a file (instead of --pr)")
    ck.add_argument("--base", help="the base the change is read from (default: the PR's, else origin/main)")
    for p in (pr, st, ck):
        p.add_argument("--repo", help="the repo (default: here)")



