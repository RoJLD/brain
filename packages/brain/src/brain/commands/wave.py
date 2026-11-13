"""``brain wave``: the waves, milestones of kind wave whose id carries no version (wave-sN) and whose release is a
computed label: a new one, the closure its version PR makes (props.shipped_as), the closure check, the rename of a
legacy wave-X.Y.Z, the import of the items' free-text props.wave (brain.waves), the plan of its lots (brain.lots).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import closemerged, config, graph, lots, nextrelease, projects, waveimport, waverename, waves
from ._common import _project, _store
from ._common import _repos as _project_repos

ORDER = 55   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 55   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain wave add [X.Y.Z] [--parent MS] [--week W] [--title T]   a new wave wave-sN (a Milestone of kind wave; its id
                 is its place and carries no version), part of a milestone or an era; its release is computed, the
                 next patch after the last wave's (X.Y.Z, when given, must be it; a store's first wave names it); its
                 items join it by part_of (brain item link)
  brain wave close X.Y.Z [--carry-to X.Y.Z] [--drop ID]... [--write]   the version PR closes its wave (the wave of
                 that release, or the current one when the release jumped to the next minor or major): each open item
                 carried by name to a later wave (props.carried_to; a new wave-sN when none) or dropped, then the wave
                 reached with props.shipped_as X.Y.Z, from which the later waves' releases are computed; without
                 --write, the plan; refused while an open item is neither
  brain wave rename WAVE [NEW] [--write]   a legacy wave-X.Y.Z renamed once to an id without a version (default
                 wave-sN, its place): the YAML values that name it (its id, the edges' from and to, carried_to,
                 carried_via) rewritten in the store's node and edge files, the generated ones too (comments and free
                 text left), a default title « Wave X.Y.Z » made « Wave sN », a pending wave's props.release dropped
                 (its release computed from then on), the old id kept in props.renamed_from (it still resolves; a NEW
                 that is another wave's former id is refused); without --write, what it would rewrite
  brain wave close-merged X.Y.Z [--repo NAME]... [--repo-dir D]... [--since REF] [--until REF] [--write] [--json]
                 the items the PRs merged since the last release tag deliver (each by the changelog fragment it added,
                 changes/<item>.md, or an item id in its title), closed done with --pr "<repo> #N" and their titles as
                 the outcome; without --write, the plan; the wave's open items no merged PR names listed; a revert
                 takes its PR out; --write refused while a repo is not read (zero token, git only, as last fetched)
  brain wave check X.Y.Z   the closure rule alone (release_check.py --store runs it on a version PR): exit 1 while the
                 wave holds an open item neither carried nor dropped, or is not reached yet; then the release
                 forecast of a wave planned as the next patch or minor: a patch or a minor, the first PR that tipped
                 it and why (release_check --preview of the engine checkout's origin/main; advisory, the exit is the
                 closure rule's)
  brain wave import [--from X.Y.Z] [--write]   the items' free-text props.wave: a wave proposed per release it names
                 (X.Y.Z; --from: the first one, the earlier ones already tagged are listed and left out), the other
                 values listed to place by {owner}; --write creates the waves and their items' part_of edges
  brain wave plan [X.Y.Z] [--at-once N] [--hot NAME]... [--json]   the wave's lots (default: the current wave), at
                 zero token: its open items grouped by the files their predicted surface shares (brain collisions'),
                 hot files (READMEs, CHANGELOGs, formats.md, FEATURES.md, config.schema.json, changes/) counted apart,
                 in rounds by their depends_on, the lots that unblock the most first, at most the sessions cap less the
                 master's and N PRs verified at once (3) a round; the predicted conflicts, the hot files shared, the
                 items with no known surface, what the memory guard and the quota forecast say now, the wave's
                 quick-win slot (a fifth of its places for size S and high value: what fills it, the candidates);
                 refuses nothing
"""


def _ids(values: list[str] | None) -> list[str]:
    return [v.strip() for x in values or [] for v in x.split(",") if v.strip()]


def _close(args, root: Path, store: Path) -> int:
    c = waves.close(store, args.version, args.carry_to or "", _ids(args.drop), write=args.write, root=root)
    for i in c.carried:
        print(f"{i}: carried to {args.carry_to} ({c.carry_to})")
    for i in c.dropped:
        print(f"{i}: dropped")
    if c.left:
        print(f"wave {c.release}: not closed, {len(c.left)} open item(s) neither carried nor dropped: "
              f"{', '.join(c.left)} (--carry-to X.Y.Z, or --drop ID)", file=sys.stderr)
        return 1
    if c.created:
        print(f"{c.carry_to}: {'created' if args.write else 'to create'}, beside {c.wave}")
    tail = "written; then brain sync and brain check" if args.write else "not written: --write"
    shipped = f", shipped as {c.shipped_as}" if c.shipped_as and c.shipped_as != c.release else ""
    print(f"wave {c.release} ({c.wave}{shipped}): closes with {c.done} done, {len(c.carried)} carried, "
          f"{len(c.dropped)} dropped; {tail}")
    return 0


def _rename(args, store: Path) -> int:
    r = waverename.rename(store, args.wave, args.new or "", write=args.write)
    for rel, n in r.files.items():
        print(f"{rel}: {n} reference(s) to {r.old}")
    for rel, n in r.generated.items():
        print(f"{rel}: {n} reference(s) to {r.old} (generated: rewritten too, so the store loads before brain sync)")
    if r.title:
        print(f"title: {r.title} (its default title named the old release)")
    tail = (f"renamed, its release {r.release or '(computed at the next brain sync)'}; then brain sync and brain "
            f"check" if args.write else "not written: --write")
    n, k = sum(r.files.values()) + sum(r.generated.values()), len(r.files) + len(r.generated)
    print(f"{r.old} -> {r.new} (seq {r.seq}): {n} reference(s) in {k} file(s); {tail}")
    return 0


def _import(args, store: Path) -> int:
    imp = waveimport.do_import(store, write=args.write, start=args.start or "")
    for rel, items in imp.before.items():
        print(f"{rel}: before --from {args.start}, not imported: {', '.join(items)}")
    for rel, items in imp.waves.items():
        where = f"into {imp.existing[rel]}" if rel in imp.existing else "a new wave (wave-sN, its release pinned)"
        print(f"{rel}: {where}, {len(items)} item(s): {', '.join(items)}")
    for value, items in imp.to_place.items():
        print(f"to place by {config.name_of()} (names no release): {value!r}: {', '.join(items)}")
    if not imp.waves and not imp.to_place and not imp.before:
        print("import: no item with a free-text props.wave outside a wave")
        return 0
    if args.write:
        print("import: written; place each new wave under a milestone or an era (brain item link wave-X.Y.Z part_of "
              "MS), then brain sync and brain check")
    else:
        print("import: not written: --write")
    return 0


def _positive(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"{text!r}: a whole number of 1 or more")
    return n


def _plan(args, root: Path, store: Path) -> int:
    try:
        name = _project(args, root).name
    except SystemExit:
        name = ""
    try:
        wp = lots.plan(store, root, args.version or "", name, args.at_once, tuple(args.hot or ()))
    except ValueError as exc:
        print(f"brain wave plan: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(wp.as_dict(), indent=2, ensure_ascii=False) if args.json else "\n".join(lots.render(wp)))
    return 0


def _check(args, root: Path, store: Path) -> int:
    """The closure rule (its exit), then the release forecast of that wave (advisory, brain.nextrelease)."""
    plan = waves.load(store, root)
    found = waves.closure_problems(plan, args.version)
    for line in found:
        print(f"error: {line}")
    if not found:
        print(f"wave {args.version}: closed, or no wave of that release (its version PR may go)")
    wid = plan.resolve(args.version)
    release = plan.label(wid) if wid else args.version
    if waves.release_key(release):
        for line in nextrelease.lines(nextrelease.forecast([r.path for r in _project_repos(args, root)]), release):
            print(line)
    return 1 if found else 0


def _repos(args, root: Path) -> list[tuple[str, Path]]:
    """The (name, checkout) pairs close-merged reads: --repo-dir's, else the project's repos (--repo's alone when
    given). The --repo-dirs are named by --repo, one name each in the same order, else as the registry names their
    main checkout (a worktree's main checkout counts), else by that main checkout's folder."""
    try:
        declared = [(r.name, r.path) for r in projects.repos_of(_project(args, root))]
    except (projects.RepoError, SystemExit):
        declared = []
    if args.repo_dir:
        if args.repo and len(args.repo) == len(args.repo_dir):
            return [(n.lower(), Path(d).resolve()) for n, d in zip(args.repo, args.repo_dir, strict=True)]
        names = {projects._repo_folder(Path(p)).lower(): n for n, p in declared}
        out = []
        for d in args.repo_dir:
            folder = projects._repo_folder(Path(d).resolve()).lower()
            out.append((names.get(folder, folder), Path(d).resolve()))
        return out
    wanted = {n.lower() for n in args.repo or []}
    return [(n, p) for n, p in declared if not wanted or n in wanted]


def _close_merged(args, root: Path, store: Path) -> int:
    repos = _repos(args, root)
    if not repos:
        print("brain wave close-merged: no repo to read (--repo-dir D, or the project's repos)", file=sys.stderr)
        return 1
    try:
        p = closemerged.plan(store, repos, args.version, args.since or "", args.until or "", root)
    except closemerged.CloseError as exc:
        print(f"brain wave close-merged: {exc}", file=sys.stderr)
        return 1
    if p.skipped:   # a repo not read: its items would read « no merged PR » and be carried or dropped next
        for name, why in p.skipped.items():
            print(f"brain wave close-merged: {name}: {why}"
                  + ("; nothing written (--repo leaves it out)" if args.write else ""), file=sys.stderr)
        if args.write or not p.ranges:
            return 1
    done: list[str] = []
    if args.write:
        try:
            closemerged.write(store, p, done)
        except graph.GraphError as exc:
            print(f"brain wave close-merged: {exc}; closed before it: {', '.join(done) or 'none'}", file=sys.stderr)
            return 1
    print(json.dumps(p.as_dict(), indent=2, ensure_ascii=False) if args.json
          else "\n".join(closemerged.render(p, args.write)))
    return 0


def cmd_wave(args, root: Path) -> int:
    store = _store(args, root)
    try:
        if args.wave_cmd == "add":
            node = waves.add(store, args.version or "", parent=args.parent or "", week=args.week or "",
                             title=args.title or "")
            label = waves.load(store).label(node["id"])
            print(f"{node['id']}: added, release {label}" + (f", part of {args.parent}" if args.parent else "")
                  + "; then brain sync and brain check")
            return 0
        if args.wave_cmd == "rename":
            return _rename(args, store)
        if args.wave_cmd == "close":
            return _close(args, root, store)
        if args.wave_cmd == "plan":
            return _plan(args, root, store)
        if args.wave_cmd == "close-merged":
            return _close_merged(args, root, store)
        if args.wave_cmd == "check":
            return _check(args, root, store)
        return _import(args, store)
    except graph.GraphError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1


def register(sub, ctx) -> None:
    wv = sub.add_parser("wave", help="the waves (milestones of kind wave: ids without a version, a computed release): "
                                     "add, the closure of the version PR, its check, rename, the import of "
                                     "props.wave").add_subparsers(dest="wave_cmd", required=True)
    wa = wv.add_parser("add", help="a new wave wave-sN, part of a milestone or an era; its release computed")
    wa.add_argument("version", nargs="?", help="its release, X.Y.Z: must be the computed one (a store's first wave "
                                               "names it)")
    wa.add_argument("--parent", help="the milestone or era it is part of")
    wa.add_argument("--week", help="props.week: the week it is planned for")
    wa.add_argument("--title", help="its title (default: Wave X.Y.Z)")
    wc = wv.add_parser("close", help="close a wave: its open items carried to a later wave or dropped, then reached")
    wc.add_argument("version", help="the wave's release (or its id)")
    wc.add_argument("--carry-to", help="the later wave the open items go to (its release or id)")
    wc.add_argument("--drop", action="append", help="an open item dropped instead (repeatable, or comma-separated)")
    wc.add_argument("--write", action="store_true", help="write it (without: the plan)")
    wr = wv.add_parser("rename", help="a legacy wave-X.Y.Z renamed once to an id without a version (default wave-sN)")
    wr.add_argument("wave", help="the wave (its id, its release or a former id)")
    wr.add_argument("new", nargs="?", help="the new id (default wave-sN, its place)")
    wr.add_argument("--write", action="store_true", help="write it (without: what it would rewrite)")
    wm = wv.add_parser("close-merged", help="close the items the PRs merged since the last release tag deliver (by "
                                            "their changelog fragment or an item id in their title): the plan, or "
                                            "--write")
    wm.add_argument("version", help="the wave's release (or its id)")
    wm.add_argument("--repo", action="append", help="only this repo of the project (repeatable); with as many "
                                                     "--repo-dir, their names, in order")
    wm.add_argument("--repo-dir", action="append", help="a checkout to read instead of the project's repos "
                                                         "(repeatable)")
    wm.add_argument("--since", help="the ref to read from (default: the last release tag before X.Y.Z)")
    wm.add_argument("--until", help="the ref to read to (default: vX.Y.Z when tagged, else origin's default branch "
                                       "as last fetched, else HEAD)")
    wm.add_argument("--write", action="store_true", help="close them (without: the plan)")
    wm.add_argument("--json", action="store_true", help="the plan, as JSON")
    wk = wv.add_parser("check", help="the closure rule: exit 1 while the wave holds an open item not carried or "
                                     "dropped, or is not reached yet")
    wk.add_argument("version", help="the wave's release (or its id)")
    wi = wv.add_parser("import", help=f"waves from the items' free-text props.wave; the rest listed for {ctx.who}")
    wi.add_argument("--from", dest="start", metavar="X.Y.Z", help="the first release to import: the earlier ones, "
                                                                    "already tagged, are listed and left out")
    wi.add_argument("--write", action="store_true", help="create the waves and the part_of edges")
    wp = wv.add_parser("plan", help="the wave's lots: items that share no file but hot ones, in rounds by their "
                                    "depends_on, sized by the caps in force (zero token, refuses nothing)")
    wp.add_argument("version", nargs="?", help="the wave's release (or its id); default: the current wave")
    wp.add_argument("--at-once", type=_positive, help=f"the PRs one machine verifies at once (default {lots.AT_ONCE})")
    wp.add_argument("--hot", action="append", help="a hot file more, counted apart (a name, or a folder ending in /; "
                                                   "repeatable)")
    wp.add_argument("--json", action="store_true", help="the data, as JSON")


run = cmd_wave
