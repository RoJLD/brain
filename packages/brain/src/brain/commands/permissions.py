"""``brain permissions``: the permission hierarchy: a project's effective allow / ask / deny list on this machine and
where each rule comes from (brain.permissions).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import paths, permissions, projects, queue
from ._common import _on_main, _project

ORDER = 260   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 300   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain permissions [--project P | --all] [--machine H] [--session S] [--explain RULE|perm-ID] [--json]   the
                 permission hierarchy (engine allow-rules.txt, then permissions.yaml: global, profile, machine,
                 tenant, project, local, session): the effective allow / ask / deny list and where each rule comes
                 from, the guards (the hard deny layer), the never-grantable categories, and each settings file's state
  brain permissions check | render [--level user|project|local|session] [--repo DIR] [--write] [--json]
                 | grant [perm-ID] [--call C] --rule R --why W [--global|--project P|--machine H|...] [--dry-run]
                 render: an adapter's files (Claude Code's; adds the missing rules, never removes one; the user file
                 is install.ps1 -Apply's); grant: a rule appended in this branch, reviewed by PR (no --rule: proposals)
"""


def _brain_root(args) -> Path:
    """The Brain checkout acted on (--root, else the one above the current folder): where permissions.yaml is read
    and a grant written, whatever --project names (a worktree's file, not the installed clone's)."""
    return Path(args.root).resolve() if args.root else paths.find_root()


def cmd_permissions(args, root: Path) -> int:
    """``brain permissions``: the effective list of a project on a machine and where each rule comes from; ``check``,
    ``render`` (an adapter's settings files) and ``grant`` (a rule appended in a branch, reviewed by PR)."""
    sub = getattr(args, "permissions_cmd", None)
    base = _brain_root(args)
    try:
        if sub == "grant":
            return _permissions_grant(args, base)
        model = permissions.load(base)
        if sub == "check":
            for e in model.errors:
                print(f"error: {e}")
            print(f"permissions: {model.file or 'no ' + permissions.FILE}, {len(model.rules)} rule(s) with "
                  f"{model.engine_file.name if model.engine_file else 'no ' + permissions.ENGINE_FILE}, "
                  + (f"{len(model.errors)} error(s)" if model.errors else "OK"))
            return 1 if model.errors else 0
        if sub == "render":
            return _permissions_render(args, base, model)
    except permissions.PermissionsError as exc:
        print(f"brain: {exc}", file=sys.stderr)
        return 1
    if args.requests:
        only = None if args.all else _project(args, root)
        reqs = permissions.select(permissions.requests(model, only=only, days=args.days if args.days != 30 else 7),
                                  status=args.status or "", scope=args.scope or "", item=args.item or "",
                                  search=args.search or "", sort=args.sort)
        if args.json:
            print(json.dumps(reqs, ensure_ascii=False, indent=1))
        else:
            print("\n".join(permissions.requests_text(reqs, title="every project" if args.all else only.name)))
            print("  grant one: brain permissions grant <id> --rule R --why W [level] [--until D | --for-days N | "
                  "--while ITEM]")
        return 0
    scope = list(model.registry) if args.all else [_project(args, root).name]
    out = []
    for i, name in enumerate(scope):
        ctx = permissions.context(model, name, args.machine or "", args.session or "")
        if args.explain:
            text = args.explain
            if text.startswith("perm-"):
                d = permissions.find_denial(text, args.days)
                if d is None:
                    print(f"brain: {text}: no such denial in the last {args.days} days of transcripts", file=sys.stderr)
                    return 1
                text = d["call"]
            data = permissions.explain(model, ctx, text)
            data["proposals"] = permissions.propose(text) if args.explain.startswith("perm-") else []
            out.append(data)
            if not args.json:
                print("\n".join(permissions.explain_text(data)))
                for p in data["proposals"]:
                    print(f"  proposal: {p['rule'] or '-'} for {p['part'][:60]}" + (f" ({p['note']})" if p["note"]
                                                                                    else ""))
            continue
        data = permissions.show(model, ctx)
        if i:   # the user file is the same for every project of this machine
            data["files"] = [f for f in data["files"] if f["scope"] != "user"]
        out.append(data)
        if not args.json:
            print("\n".join(permissions.render_text(data)))
    if args.json:
        print(json.dumps(out if args.all else out[0], ensure_ascii=False, indent=1))
    elif not args.explain:
        print("  brain permissions --explain RULE|perm-ID: where a rule comes from; render: the settings files; "
              "grant: a rule, by PR")
    return 1 if model.errors else 0


def _permissions_render(args, base: Path, model) -> int:
    """render --level user|project|local|session: the plan of each target file; --write adds the missing rules (never
    the user file: install.ps1 -Apply, the owner's); --json for install.ps1 (the user level's rules)."""
    adapter = permissions.ADAPTERS.get(args.target)
    if adapter is None:
        print(f"brain: no adapter for {args.target} yet (built: {', '.join(permissions.ADAPTERS)})", file=sys.stderr)
        return 2
    project = getattr(args, "project_obj", None)
    name = project.name if project else ("" if args.level in ("user", "session") else _project(args, base).name)
    ctx = permissions.context(model, name, args.machine or "", args.session or "")
    if args.level == "session":
        if not args.session:
            print("brain: render --level session needs --session NAME", file=sys.stderr)
            return 2
        if model.errors:
            for e in model.errors:
                print(f"error: {e}")
            print("brain: the hierarchy has errors (brain permissions check): nothing is rendered", file=sys.stderr)
            return 1
        if args.out:
            added = permissions.write_session(model, ctx, Path(args.out))
            print(f"{args.out}: {added} rule(s) added; claude --settings {args.out}")
        else:
            print(json.dumps(permissions.session_settings(model, ctx), ensure_ascii=False, indent=2))
        return 0
    if args.level == "user" and args.json:   # install.ps1's input: every rule of the user scope, by verdict
        want = permissions.wanted(model, ctx, "user", adapter)
        print(json.dumps({"file": str(permissions.claude_home() / "settings.json"), "machine": ctx.machine,
                          **want, "expired": permissions.expired_rules(model, ctx, "user", adapter),
                          "errors": model.errors}, ensure_ascii=False, indent=1))
        return 1 if model.errors else 0
    if args.write and args.level == "user":
        print("brain: install.ps1 -Apply writes the user settings (the owner's); this prints its plan", file=sys.stderr)
        return 1
    plans = permissions.render(model, ctx, args.level, repo=Path(args.repo).resolve() if args.repo else None,
                               write=args.write, adapter=adapter)
    if args.json:
        print(json.dumps(plans, ensure_ascii=False, indent=1))
        return 1 if model.errors else 0
    if not plans:
        print(f"{args.level}: no target (a project level needs a registered project)")
    for p in plans:
        miss = [(v, x) for v in ("allow", "ask", "deny") for x in p["missing"][v]]
        state = "written" if p.get("written") else ("refused: " + p["refused"] if p["refused"] and miss else
                                                    "same" if not miss else "would add")
        print(f"{p['scope']:<7} {p['file']}: {p['present']} of {p['total']} present; {state}")
        for v, x in miss:
            print(f"  {v:<5} {x}")
        for v in ("allow", "ask", "deny"):
            for x in p["unmanaged"][v]:
                print(f"  held, declared by no level: {v} {x}")
    for e in model.errors:
        print(f"error: {e}")
    return 1 if model.errors else 0


def _permissions_grant(args, base: Path) -> int:
    """grant [PERM] [--call C] --rule R --why W: a rule appended to permissions.yaml in this branch; without --rule,
    the narrow rules proposed for the call. A main checkout on main is refused: a grant is reviewed by PR."""
    denial = None
    call = args.call or ""
    if args.perm:
        denial = permissions.find_denial(args.perm, args.days)
        if denial is None and not call:
            print(f"brain: {args.perm}: no such denial in the last {args.days} days of transcripts (--call gives "
                  "the call)", file=sys.stderr)
            return 1
        call = call or denial["call"]
    if not args.rule:
        if not call:
            print("brain: grant needs a permission task (perm-...), --call or --rule", file=sys.stderr)
            return 2
        print(f"{call[:110]}")
        for p in permissions.propose(call):
            print(f"  proposal: {p['rule'] or '-'}  for: {p['part'][:70]}" + (f"  ({p['note']})" if p["note"] else ""))
        print("brain permissions grant ... --rule RULE --why WHY [level]: the rule goes into permissions.yaml")
        return 1
    f = base / permissions.FILE   # this checkout's own file, never one found elsewhere (the main checkout's)
    if not f.is_file():
        print(f"brain: no {permissions.FILE} in {base}: grant writes the file of the checkout it runs in",
              file=sys.stderr)
        return 1
    branch = _on_main(base)
    if branch and not args.dry_run:
        print(f"brain: {base} is the main checkout on {branch}: grant in a worktree's branch, reviewed by PR",
              file=sys.stderr)
        return 1
    selectors = {"project": args.project or "", "machine": args.machine or "", "profile": args.profile or "",
                 "tenant": args.tenant or "", "session": args.session or ""}
    if not any(selectors.values()) and not args.global_:
        if denial is None:
            print("brain: name the level: --global, --project P, --machine H, --profile X, --tenant T or --session S",
                  file=sys.stderr)
            return 2
        place = queue.Placer(list(projects.load(base).values()))
        selectors["project"] = place(denial["cwds"][0]) if denial["cwds"] else ""
        if not selectors["project"]:
            print("brain: the denial ran outside every registered project: name the level", file=sys.stderr)
            return 2
    asked_by, fors = "", []
    if args.perm:   # the request's provenance goes with the rule
        req = next((r for r in permissions.requests(permissions.load(base), days=args.days) if r["id"] == args.perm),
                   None)
        if req:
            asked_by, fors = (req["sessions"] or [""])[0], req["items"] + req["milestones"]
    line, path = permissions.grant(base, rule=args.rule, verdict=args.verdict, selectors=selectors,
                                   until=args.until or "", days=args.for_days or 0, while_=args.while_ or "",
                                   asked_by=asked_by, for_=fors,
                                   why=args.why or "",
                                   by=args.by or "", origin=args.perm or "",
                                   denial=f"{call} {denial['reason'] if denial else ''}".strip(),
                                   dry_run=args.dry_run, path=f)
    print(f"{'would append' if args.dry_run else 'appended'} to {path}:\n{line}")
    if not args.dry_run:
        print("next: commit it in this branch and open the PR (its review is the owner's); once merged, render it "
              "(brain permissions render --level project --write, a production repo through --repo and its own PR; "
              "a user-level rule by install.ps1 -Apply, the owner's)"
              + (f", then brain queue done {args.perm}" if args.perm else ""))
    return 0


def register(sub, ctx) -> None:
    who = ctx.who
    pe = sub.add_parser("permissions", help="the permission hierarchy: a project's effective allow / ask / deny list on "
                                            "this machine and where each rule comes from (brain.permissions)")
    pe.add_argument("--project", default=argparse.SUPPRESS, help="a registered project (same as brain --project)")
    pe.add_argument("--all", action="store_true", help="every registered project")
    pe.add_argument("--machine", help="another machine's host name (default: this one)")
    pe.add_argument("--session", help="a declared session or sub-session: its rules too")
    pe.add_argument("--explain", metavar="RULE", help="a rule, a call (Bash: cmd) or a permission task (perm-...): "
                                                      "where it is declared, what it falls in, what the call gets")
    pe.add_argument("--days", type=int, default=30, help="how far back a perm-... id is looked for (default 30)")
    pe.add_argument("--json", action="store_true", help="the data: rules, sources, files, guards, never")
    pe.add_argument("--requests", action="store_true", help="the permission requests: brain queue's permission "
                    "entries and the rules granted for them, with scope, reason, items, milestones, what each "
                    "unblocks, sessions, evidence, duration and status")
    pe.add_argument("--status", choices=["pending", "granted", "expired"], help="--requests: one status")
    pe.add_argument("--scope", help="--requests: a scope's start (global, project, project quant, machine...)")
    pe.add_argument("--item", help="--requests: those that unblock this item or milestone")
    pe.add_argument("--search", help="--requests: a text in the id, reason or evidence")
    pe.add_argument("--sort", choices=list(permissions.REQUEST_SORTS), default="unblocks", help="--requests' order")
    ps = pe.add_subparsers(dest="permissions_cmd")
    ps.add_parser("check", help="permissions.yaml and allow-rules.txt checked: levels, rules, never-grantable and "
                                "broad allow rules; exit 1 on an error")
    pr = ps.add_parser("render", help="an adapter's settings files: the plan, or --write the missing rules (never "
                                      "removes one)")
    pr.add_argument("--target", default="claude", help="the agent's adapter (built: claude)")
    pr.add_argument("--level", choices=["user", "project", "local", "session"], default="project",
                    help="user: ~/.claude/settings.json (install.ps1 -Apply writes it); project: each repo's "
                         ".claude/settings.json; local: .claude/settings.local.json; session: a --settings file")
    pr.add_argument("--machine", default=argparse.SUPPRESS, help="another machine's host name")
    pr.add_argument("--session", default=argparse.SUPPRESS, help="the session level's name")
    pr.add_argument("--repo", help="the folder to render the project or local level into (a worktree of a "
                                   "production repo, for a PR there)")
    pr.add_argument("--write", action="store_true", help="add the missing rules (not the user file, not a "
                                                         "production checkout); a settings file that is not a JSON "
                                                         "object is refused, never replaced; one that git does not "
                                                         "keep as it is (untracked, ignored or changed: "
                                                         "settings.local.json) is backed up beside itself (.bak) "
                                                         "first")
    pr.add_argument("--out", help="session level: write the file for claude --settings there")
    pr.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                    help="the plans; with --level user, the user scope's rules by verdict (install.ps1 reads it)")
    pg = ps.add_parser("grant", help="a permission task becomes a rule appended to permissions.yaml in this branch "
                                     "(reviewed by PR); without --rule, the narrow rules proposed for the call")
    pg.add_argument("perm", nargs="?", help="a permission task of brain queue (perm-...)")
    pg.add_argument("--call", help="the call when it has no perm-... id: 'Bash: cmd'")
    pg.add_argument("--rule", help="the rule, Claude Code's syntax or Shell(...) for Bash and PowerShell")
    pg.add_argument("--verdict", choices=["allow", "ask", "deny"], default="allow")
    pg.add_argument("--why", help=f"the reason ({permissions.WHY_MIN} characters at least)")
    pg.add_argument("--by", help=f"who decided it: '{who}, 2026-11-02'")
    pg.add_argument("--global", dest="global_", action="store_true", help="the global level")
    pg.add_argument("--machine", default=argparse.SUPPRESS, help="the machine level (with --project: local)")
    pg.add_argument("--profile", help="the profile level")
    pg.add_argument("--tenant", help="the tenant level")
    pg.add_argument("--session", default=argparse.SUPPRESS, help="the session level")
    pg.add_argument("--days", type=int, default=argparse.SUPPRESS, help="how far back the perm-... id is looked for")
    du = pg.add_mutually_exclusive_group()
    du.add_argument("--until", help="the rule's last day, YYYY-MM-DD (default: indefinite)")
    du.add_argument("--for-days", dest="for_days", type=int, help="the rule holds N days from today")
    du.add_argument("--while", dest="while_", help="the rule holds while this item is open")
    pg.add_argument("--dry-run", action="store_true", help="print the line, write nothing")


run = cmd_permissions
