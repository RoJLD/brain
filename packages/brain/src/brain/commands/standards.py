"""``brain standards``: the standards registry (brain.standards, wi-brain-standards-registry): ``list`` its rows (the
engine's catalogs, then the project's local ones), ``show`` one, ``check`` the catalogs and the project's opt-in
(projects.yaml standards:) and say which applicable standards' checks do not cover its repos' languages.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import projects, standards
from ._common import _print_json, _project

ORDER = 125   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 125   # its usage lines' place in brain --help's epilog
RUNS_VIA = {   # brain perf --usage: how a subcommand that may never run from the CLI is reached (brain.adoption)
    "standards show": "on demand: one standard read by hand (brain standards lists them)",
    "standards lenses": "wired: brain review prep adds the same rows to its packet as the standards lens",
    "standards rules": "on demand: a project's rules text, written into its rules",
    "standards ci": "on demand: a project's CI skeleton, once, then adapted by hand",
}
USAGE = """\
  brain standards list [--catalog C] [--domain D] [--profile P] [--stage S] [--enforcement E] [--status S]
                 [--applicable] [--json] | show ID [--json] | check [--json]   the standards registry: one row per
                 standard (its domain, statement, the profiles it applies to, the stage it is required from, how it
                 is enforced and by what check, the languages that check covers, how the Brain itself meets it,
                 proposed or validated), from the engine's catalogs and the brain's local ones that projects.yaml
                 standards.catalogs names (docs/standards.md). list filters the rows (--stage: those required at
                 that stage; --applicable: those the project's standards: opt-in selects, with why); show prints one;
                 check exits 1 when a catalog breaks its format, an id is found twice, the project's standards: is
                 malformed or names an unknown profile, stage or id, or a local catalog cannot be read, and lists the
                 applicable standards whose check does not cover a repo's language (a gap, not an error); 2 when one
                 of the engine's catalogs cannot be read. A project without standards: follows none
  brain standards lenses | rules [--write FILE] | ci [--write FILE] [--json]   the registry's consumers for the
                 project: lenses, its review-lens rows, the questions brain review prep adds as the standards lens;
                 rules, its rule rows as a markdown section of rules text (only what needs judgement); ci, a GitHub
                 Actions skeleton from its check and measure rows with an adapter, one step per slot and repo (the
                 usual tool of its language as a comment; the engine runs no tool). Nothing when it declares none
"""


def _load(args, root: Path):
    """(the project, its catalogs, its selection, the errors of its local catalogs)."""
    p = _project(args, root)
    catalogs, sel, errors = standards.for_project(p)
    return p, catalogs, sel, errors


def _matches(row: standards.Row, args) -> bool:
    pairs = (("catalog", row.catalog), ("domain", row.domain), ("enforcement", row.enforcement),
             ("status", row.status))
    if any(getattr(args, k, "") and getattr(args, k) != v for k, v in pairs):
        return False
    if getattr(args, "stage", "") and not standards.required_at(row, args.stage):
        return False
    profile = getattr(args, "profile", "")
    return not profile or profile in row.profiles or "any" in row.profiles


def _chosen(args, p, rows: list[standards.Row], sel) -> list[tuple[standards.Row, str]]:
    """The rows list prints, each with why it applies (--applicable) or "", after the filters."""
    if not args.applicable:
        chosen = [(r, "") for r in rows]
    elif sel is None:
        print(f"brain standards: project {p.name} declares no standards: in projects.yaml (docs/standards.md): "
              "it follows none", file=sys.stderr)
        chosen = []
    else:
        chosen = standards.applicable(rows, sel)
    return [(r, why) for r, why in chosen if _matches(r, args)]


def _print_rows(chosen: list[tuple[standards.Row, str]]) -> None:
    domain = None
    for r, why in sorted(chosen, key=lambda rw: (rw[0].catalog, rw[0].domain, rw[0].id)):
        if (r.catalog, r.domain) != domain:
            domain = (r.catalog, r.domain)
            print(f"== {r.catalog} / {r.domain}")
        tail = f"  [{why}]" if why else ""
        print(f"  {r.id}  {r.enforcement}, from {r.stage}, {'/'.join(r.profiles)}, {r.status}{tail}")
        print(f"      {' '.join(r.statement.split())}")
    by = ", ".join(f"{n} {k}" for k, n in standards.counts([r for r, _ in chosen]).items())
    print(f"{len(chosen)} standard(s): {by}")


def _cmd_list(args, root: Path) -> int:
    p, catalogs, sel, errors = _load(args, root)
    for e in errors:
        print(f"brain standards: {e}", file=sys.stderr)
    chosen = _chosen(args, p, standards.rows_of(catalogs), sel)
    if args.json:
        _print_json({"project": p.name, "concerned": sel is not None, "applicable": bool(args.applicable),
                     "standards": [{**r.as_dict(), "selected_by": why} for r, why in chosen]})
    elif chosen:
        _print_rows(chosen)
    else:
        print("no standard" + (" applies" if args.applicable else " matches"))
    return 1 if errors else 0


def _cmd_show(args, root: Path) -> int:
    _, catalogs, _, errors = _load(args, root)
    found = next((r for r in standards.rows_of(catalogs) if r.id == args.id), None)
    if found is None:
        print(f"brain standards: no standard {args.id!r} (brain standards list)", file=sys.stderr)
        return 1
    d = found.as_dict()
    if args.json:
        _print_json(d)
        return 0
    print(f"{found.id}" + (f": {found.title}" if found.title else ""))
    cov = found.coverage
    lines = [("catalog", found.catalog), ("domain", found.domain), ("statement", found.statement),
             ("why", found.why), ("profiles", ", ".join(found.profiles)), ("required from", found.stage),
             ("enforcement", found.enforcement), ("check", found.check), ("adapter", found.adapter),
             ("languages", ", ".join(found.languages)),
             ("the Brain", (str(cov.get("status") or "") + (f": {cov['by']}" if cov.get("by") else "")) if cov else ""),
             ("status", found.status), ("source", found.source), ("refs", ", ".join(found.refs)),
             ("file", found.file)]
    for label, value in lines:
        if value:
            print(f"  {label}: {' '.join(str(value).split())}")
    return 0


def _languages(p, notes: list[str]) -> tuple[dict[str, str], dict[str, set]]:
    """({repo: its language}, {repo: the adapter slots its tools: declares}) of the project; ({}, {}) with a note
    when its repos cannot be read."""
    try:
        repos = projects.repos_of(p)
    except projects.RepoError as exc:
        notes.append(f"its repos cannot be read ({exc}): the languages are not compared")
        return {}, {}
    return {r.name: r.lang for r in repos}, {r.name: set(r.tools) for r in repos}


def report(p, catalogs: list[standards.Catalog], sel, errors: list[str]) -> dict:
    """What brain standards check says, with stable keys: the catalogs, the errors, the notes, the applicable ids
    and the language gaps of a project (``errors``: those of its local catalogs that cannot be read)."""
    notes = [n for cat in catalogs for n in cat.notes]
    errors = errors + [e for cat in catalogs for e in cat.errors] + standards.duplicates(catalogs)
    rows = standards.rows_of(catalogs)
    chosen, gaps = [], []
    if sel is not None:
        ids = None if errors else {r.id for r in rows}   # a local catalog unread: its ids would be named unknown
        errors += standards.selection_errors(f"project {p.name}", p.standards, ids, notes=notes)
        chosen = standards.applicable(rows, sel)
        gaps = standards.gaps(chosen, *_languages(p, notes))
    return {"project": p.name, "concerned": sel is not None, "catalogs": [
        {"name": c.name, "file": c.path.as_posix(), "engine": c.engine, "rows": len(c.rows)} for c in catalogs],
        "rows": len(rows), "applicable": [r.id for r, _ in chosen], "errors": errors, "gaps": gaps, "notes": notes}


def _cmd_check(args, root: Path) -> int:
    p, catalogs, sel, errors = _load(args, root)
    data = report(p, catalogs, sel, errors)
    if args.json:
        _print_json(data)
        return 1 if data["errors"] else 0
    for c in data["catalogs"]:
        print(f"catalog {c['name']} ({'engine' if c['engine'] else c['file']}): {c['rows']} row(s)")
    for line in ([f"note: {n}" for n in data["notes"]] + [f"error: {e}" for e in data["errors"]]
                 + [f"gap: {g}" for g in data["gaps"]]):
        print(line)
    if data["concerned"]:
        gaps = f", {len(data['gaps'])} not covered on every language" if data["gaps"] else ""
        print(f"standards check: {len(data['applicable'])} of {data['rows']} standard(s) apply to {p.name}{gaps}")
    else:
        print(f"standards check: {data['rows']} standard(s); project {p.name} declares no standards: "
              "(not concerned)")
    return 1 if data["errors"] else 0


def _out(text: str, args) -> None:
    if getattr(args, "write", None):
        Path(args.write).write_text(text, encoding="utf-8", newline="\n")
        print(f"standards: written {args.write}")
    else:
        sys.stdout.write(text)


def _cmd_lenses(args, root: Path) -> int:
    p = _project(args, root)
    lines = standards.lenses(p)
    if args.json:
        _print_json({"project": p.name, "lenses": lines})
    else:
        print("\n".join(f"- {line}" for line in lines) if lines else
              f"no review-lens standard applies to {p.name} (brain standards list --applicable)")
    return 0


def _cmd_rules(args, root: Path) -> int:
    p = _project(args, root)
    text = standards.rules_text(p)
    if args.json:
        _print_json({"project": p.name, "rules": text})
    elif text:
        _out(text, args)
    else:
        print(f"no rule standard applies to {p.name} (brain standards list --applicable)")
    return 0


def _cmd_ci(args, root: Path) -> int:
    p = _project(args, root)
    notes: list[str] = []
    langs, slots = _languages(p, notes)
    try:
        tools = {r.name: dict(r.tools) for r in projects.repos_of(p)}
    except projects.RepoError:
        tools = {name: {} for name in slots}
    plan = standards.ci_plan(p, langs, tools)
    if args.json:
        _print_json({"project": p.name, "plan": plan, "notes": notes})
    elif plan:
        _out(standards.ci_yaml(p, plan, langs), args)
    else:
        print(f"no check or measure standard with an adapter applies to {p.name} (brain standards list --applicable)")
    for n in notes:
        print(f"brain standards: {n}", file=sys.stderr)
    return 0


def cmd_standards(args, root: Path) -> int:
    try:
        return {"list": _cmd_list, "show": _cmd_show, "check": _cmd_check, "lenses": _cmd_lenses,
                "rules": _cmd_rules, "ci": _cmd_ci}[args.standards_cmd](args, root)
    except standards.StandardsError as exc:
        print(f"brain standards: {exc}", file=sys.stderr)
        return 2


def register(sub, ctx) -> None:
    st = sub.add_parser("standards", help="the standards registry: list, show and check its rows and the project's "
                                          "opt-in (brain.standards)")
    ss = st.add_subparsers(dest="standards_cmd", required=True)
    sl = ss.add_parser("list", help="the rows, by catalog and domain (--applicable: those the project follows)")
    sl.add_argument("--catalog", default="", help="one catalog (software, research...)")
    sl.add_argument("--domain", default="", help="one domain")
    sl.add_argument("--profile", default="", help="the rows that apply to this profile (a row of profile any too)")
    sl.add_argument("--stage", default="", help="the rows required at this stage (theirs at or before it)")
    sl.add_argument("--enforcement", default="", help="check, measure, test-template, review-lens or rule")
    sl.add_argument("--status", default="", help="proposed or validated")
    sl.add_argument("--applicable", action="store_true", help="the rows the project's standards: selects, with why")
    sh = ss.add_parser("show", help="one standard, every field")
    sh.add_argument("id")
    sc = ss.add_parser("check", help="exit 1 when a catalog breaks its format or cannot be read, an id is found "
                                     "twice, or the project's standards: is malformed or names an unknown profile, "
                                     "stage or id")
    sle = ss.add_parser("lenses", help="the review-lens rows: the standards lens brain review prep adds")
    sr = ss.add_parser("rules", help="the rule rows as a markdown section of rules text")
    sci = ss.add_parser("ci", help="a CI workflow skeleton from the check and measure rows with an adapter")
    for p in (sr, sci):
        p.add_argument("--write", metavar="FILE", help="write it to FILE instead of printing it")
    for p in (sl, sh, sc, sle, sr, sci):
        p.add_argument("--json", action="store_true", help="stable keys")


run = cmd_standards
