"""``brain public deny render``: the deny list (config.json public.deny and the derived terms) rendered for another
scanner, a gitleaks configuration (brain.denyrender, wi-brain-deny-gitleaks-render): a plan, then ``--apply``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import config, denyrender
from ._common import root_of

ORDER = 448   # its place in brain --help's list of commands (brain.commands), after brain telemetry
USAGE_ORDER = 408   # its usage lines' place in brain --help's epilog, after brain telemetry's
USAGE = """\
  brain public deny render --format gitleaks [--out FILE] [--extend PATH] [--apply] [--json]
                                  config.json public.deny (and the terms derived from the registries) as a gitleaks
                                  configuration: one rule per category, extending the repo's .gitleaks.toml (--extend)
                                  or gitleaks' defaults; the plan (the file, rules and term counts, never the terms),
                                  then --apply writes it only when it changed, atomically, mode 600, never inside a
                                  git repository (default $XDG_CONFIG_HOME/brain/gitleaks-private-patterns.toml); exit
                                  2 when it cannot be rendered or written there
"""


def register(sub, ctx) -> None:
    pp = sub.add_parser("public", help="the public check's deny list for other tools: brain public deny render")
    ps = pp.add_subparsers(dest="public_cmd", required=True)
    deny = ps.add_parser("deny", help="the deny list (config.json public.deny)").add_subparsers(
        dest="deny_cmd", required=True)
    r = deny.add_parser("render", help="the deny list as another scanner's configuration (gitleaks): a plan, then "
                                       "--apply writes it outside any repository")
    r.add_argument("--format", required=True, choices=denyrender.FORMATS, help="the scanner (gitleaks)")
    r.add_argument("--out", help="the file to write (default $XDG_CONFIG_HOME/brain/gitleaks-private-patterns.toml); "
                                 "refused inside a git repository")
    r.add_argument("--extend", help="the gitleaks configuration it extends, a repo's .gitleaks.toml (default: "
                                    "gitleaks' own rules, useDefault)")
    r.add_argument("--apply", action="store_true", help="write the file (only when it changed)")
    r.add_argument("--json", action="store_true", help="the plan as JSON: out, format, rules, terms, state, refused "
                                                       "(never the terms)")


def early(args) -> int:
    out = Path(args.out).expanduser() if args.out else denyrender.default_out()
    extend = str(Path(args.extend).expanduser()) if args.extend and args.extend.startswith("~") else args.extend
    try:
        p = denyrender.plan(config.load(root_of(args)), out, extend, args.format)
    except (denyrender.RenderError, OSError) as exc:
        print(f"brain public deny render: {exc}", file=sys.stderr)
        return 2
    try:
        done = denyrender.apply(p) if args.apply and not p["refused"] else ""
    except (denyrender.RenderError, OSError) as exc:
        print(f"brain public deny render: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({**{k: v for k, v in p.items() if k != "text"}, "applied": done or None}))
    else:
        lines = denyrender.render_plan(p)
        if done:
            lines.append(f"  applied   {done}")
        print("\n".join(lines))
    return 2 if p["refused"] else 0
