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
  brain review prep [PR | BASE..HEAD] [--item ID] [--out DIR] [--no-scout] [--json]   the review packet at zero
                 token: the diff, the touched files at the head, brain audit --diff's output, the lenses the touched
                 surfaces call for, the invariants and failure modes to test (the item's brief section with --item)
                 and how to run them (default origin/main..HEAD, into <BRAIN_HOME>/reviews/<head>)
  brain review stamp HEAD --findings N --fixed M [--contested K] [--note FILE] [--pr N] [--item ID] [--wave W]
                 [--stream S]   the review of that head ran: its counts, the note's finding lines, its place
  brain review check HEAD [--pr N | --body FILE] [--base REF]   exit 0 when that head was reviewed, 1 when not (the
                 merge gate's question); with the PR body, 1 also while a pinned decision the change touches (brain
                 adr pin, docs/pins.md) has no Keeps ID line in it (a decision in force) or Overrides ID: why (one a
                 later ADR supersedes); without one, the pins touched are listed and the stamp alone decides
  brain review score [--wave W] [--json]   the error score: confirmed findings per PR by severity, lens and root
                 cause, the trend per wave, and the owner's rule: the reviews lighten once it falls over two waves
"""


def early(args) -> int:
    """Any repo, a brain or not: the review is of a PR, never of a brain's data."""
    return cmd_review(args)


def _plans(repo: Path) -> tuple[str, list]:
    """(the repo's registered project, the wave plans of its stores: brain.waves); a store that cannot be read is
    left out (the stamp is then unplaced, never unwritten)."""
    from .. import standards, waves
    proj = standards.project_of_repo(repo)
    out = []
    for store in (proj.stores if proj is not None else []):
        try:
            if waves.applies(store):
                out.append(waves.load(store))
        except Exception:  # noqa: BLE001 - a plan that cannot be read leaves the stamp unplaced, never unwritten
            continue
    return (getattr(proj, "name", "") or "", out)


def _wave_of(repo: Path, item: str, wave: str = "") -> tuple[str, str, str]:
    """(the release label, the wave id, its project) of the wave ``item`` is planned in, or of ``wave`` (a label or
    an id) when given; the id and the project are '' when no plan has it: they keep the stamp in its wave when the
    label moves."""
    name, plans = _plans(repo)
    for plan in plans:
        wid = plan.resolve(wave) if wave else plan.wave_of(item)
        if wid:
            return (plan.label(wid) if wave == wid else wave or plan.label(wid), wid, name)
    return (wave, "", "")


def _slug(repo: Path) -> str:
    """The repo's owner/name from its origin remote, else its folder's name (two repos' PR 7 stay apart)."""
    from .. import public
    try:
        slug = public.repo_slug(review._git(repo, "remote", "get-url", "origin").strip())
    except review.ReviewError:
        slug = ""
    if slug:
        return slug
    try:
        return Path(review._git(repo, "rev-parse", "--show-toplevel").strip()).name
    except review.ReviewError:
        return repo.name


def _stamp(args, repo: Path) -> int:
    """brain review stamp: the counts, the note and its finding lines, and where the review stands for the score."""
    note = Path(args.note).read_text(encoding="utf-8") if args.note else ""
    wave, wave_id, project = (_wave_of(repo, args.item or "", args.wave or "") if args.item or args.wave
                              else ("", "", ""))
    f = review.stamp(args.head, args.findings, args.fixed, args.contested, note, repo, pr=args.pr or "",
                     item=args.item or "", stream=args.stream or "", wave=wave, wave_id=wave_id, project=project,
                     repo_slug=_slug(repo) if args.pr else "")
    rows = review.confirmed(review.parse_note(note))
    print(f"review: {f.stem[:12]} stamped ({args.findings} finding(s), {args.fixed} fixed, {args.contested} "
          f"contested{f', wave {wave}' if wave else ''}): {f}")
    if args.item and not args.pr:
        print("review: --item without --pr: this stamp counts as one review of this head; pass --pr so that the PR "
              "counts once, by its latest stamp", file=sys.stderr)
    if note and len(rows) != args.findings:
        print(f"review: the note describes {len(rows)} confirmed finding line(s), --findings says {args.findings} "
              "(docs/review.md, « The note's finding lines »: the score's lens and cause counts read the lines)",
              file=sys.stderr)
    return 0


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
    except Exception as exc:  # noqa: BLE001 - no such item, or a store that cannot be read: exit 1, said
        raise review.ReviewError(f"--item {item}: {exc}") from None
    return (lambda files, changed: brief.failure_modes(proj, st, node, cfg, files, changed, public=pub)), pub


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
            return _stamp(args, repo)
        if args.review_cmd == "score":
            sc = review.score(labels=review.labels_now())
            wave = _wave_of(repo, "", args.wave)[0] if args.wave else ""   # a wave id read as its release now
            print(json.dumps(sc, indent=2) if args.json else "\n".join(review.score_lines(sc, wave)))
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
    pr.add_argument("--item", help="the item the PR delivers: its brief's « Invariants and failure modes to test » "
                                   "join the diff's in the packet")
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
    ck.add_argument("--pr", type=int, help="the PR whose body must keep or override each pinned decision touched")
    ck.add_argument("--body", help="the PR body, a file (instead of --pr)")
    ck.add_argument("--base", help="the base the change is read from (default: the PR's, else origin/main)")
    sc = rv.add_parser("score", help="the error score: confirmed findings per PR, per wave, and whether the reviews "
                                     "may lighten")
    sc.add_argument("--wave", help="one wave's score (with the trend)")
    sc.add_argument("--json", action="store_true")
    for p in (pr, st, ck):
        p.add_argument("--repo", help="the repo (default: here)")



