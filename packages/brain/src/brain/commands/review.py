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
  brain review prep [PR | BASE..HEAD] [--out DIR] [--no-scout] [--json]   the review packet at zero token: the
                 diff, the touched files at the head, brain audit --diff's output, the lenses the touched surfaces
                 call for and how to run them (default origin/main..HEAD, into <BRAIN_HOME>/reviews/<head>)
  brain review stamp HEAD --findings N --fixed M [--contested K] [--note FILE] [--pr N] [--item ID] [--wave W]
                 [--stream S]   the review of that head ran: its counts, the note's finding lines, its place
  brain review check HEAD   exit 0 when that head was reviewed, 1 when not (the merge gate's question)
  brain review score [--wave W] [--json]   the error score: confirmed findings per PR by severity, lens and root
                 cause, the trend per wave, and the owner's rule: the reviews lighten once it falls over two waves
"""


def early(args) -> int:
    """Any repo, a brain or not: the review is of a PR, never of a brain's data."""
    return cmd_review(args)


def _wave_of(repo: Path, item: str) -> str:
    """The wave ``item`` is planned in (brain.waves), read from the repo's registered project; '' when none."""
    from .. import standards, waves
    proj = standards.project_of_repo(repo)
    for store in (proj.stores if proj is not None else []):
        try:
            if waves.applies(store):
                plan = waves.load(store)
                wid = plan.wave_of(item)
                if wid:
                    return plan.label(wid)
        except Exception:  # noqa: BLE001 - a plan that cannot be read leaves the stamp unplaced, never unwritten
            continue
    return ""


def _slug(repo: Path) -> str:
    """The repo's owner/name from its origin remote, '' without one."""
    from .. import public
    try:
        return public.repo_slug(review._git(repo, "remote", "get-url", "origin").strip())
    except review.ReviewError:
        return ""


def _stamp(args, repo: Path) -> int:
    """brain review stamp: the counts, the note and its finding lines, and where the review stands for the score."""
    note = Path(args.note).read_text(encoding="utf-8") if args.note else ""
    wave = args.wave or (_wave_of(repo, args.item) if args.item else "")
    f = review.stamp(args.head, args.findings, args.fixed, args.contested, note, repo, pr=args.pr or "",
                     item=args.item or "", stream=args.stream or "", wave=wave,
                     repo_slug=_slug(repo) if args.pr else "")
    rows = review.confirmed(review.parse_note(note))
    print(f"review: {f.stem[:12]} stamped ({args.findings} finding(s), {args.fixed} fixed, {args.contested} "
          f"contested{f', wave {wave}' if wave else ''}): {f}")
    if note and len(rows) != args.findings:
        print(f"review: the note describes {len(rows)} confirmed finding line(s), --findings says {args.findings} "
              "(docs/review.md, « The note's finding lines »: the score's lens and cause counts read the lines)",
              file=sys.stderr)
    return 0


def cmd_review(args, root: Path | None = None) -> int:
    repo = Path(args.repo).resolve() if getattr(args, "repo", None) else Path.cwd()
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
            return _stamp(args, repo)
        if args.review_cmd == "score":
            sc = review.score()
            print(json.dumps(sc, indent=2) if args.json else "\n".join(review.score_lines(sc, args.wave or "")))
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
    pr.add_argument("--json", action="store_true")
    st = rv.add_parser("stamp", help="the review of HEAD ran: its counts")
    st.add_argument("head")
    st.add_argument("--findings", type=int, required=True)
    st.add_argument("--fixed", type=int, required=True)
    st.add_argument("--contested", type=int, default=0)
    st.add_argument("--note", help="the review note (a file), kept with the stamp; its finding lines "
                                   "(« - high correctness A.b fixed: ... ») are the error score's rows")
    st.add_argument("--pr", help="the PR's number: a PR stamped on several heads counts once, its latest")
    st.add_argument("--item", help="the item the PR delivers: its wave (brain.waves) places the stamp")
    st.add_argument("--wave", help="the wave, when no item says it (X.Y.Z)")
    st.add_argument("--stream", help="the stream or lot the PR belongs to")
    ck = rv.add_parser("check", help="exit 0 when HEAD was reviewed")
    ck.add_argument("head")
    sc = rv.add_parser("score", help="the error score: confirmed findings per PR, per wave, and whether the reviews "
                                     "may lighten")
    sc.add_argument("--wave", help="one wave's score (with the trend)")
    sc.add_argument("--json", action="store_true")
    for p in (pr, st, ck):
        p.add_argument("--repo", help="the repo (default: here)")



