"""``brain telemetry``: Claude Code's OpenTelemetry export as the sovereign collector stored it (brain.otel): the
summary per day, session and model, and the status of the export, the collector and its files."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .. import config, otel
from ._common import root_of

ORDER = 447   # its place in brain --help's list of commands (brain.commands), after brain ipc
USAGE_ORDER = 407   # its usage lines' place in brain --help's epilog, after brain ipc's
USAGE = """\
  brain telemetry summary [--days N] [--session ID] [--top N] [--dir PATH] [--json]
                                  Claude Code's OpenTelemetry export as the collector stored it (zero token): per
                                  UTC day, model and session the tokens by type, the cost, the API requests, errors
                                  and retries; the tool decisions by decision and source; the tools' runs, failures
                                  and error classes; the hooks' p50 and p90; rotated files read too; --days N is a
                                  rolling window (the last N x 24 hours, not N whole UTC days); a --session prefix
                                  that matches nothing is said; exit 1 when the collector's folder is missing
  brain telemetry status [--stale-hours H] [--url URL] [--timeout S] [--dir PATH] [--json]
                                  whether the export is on (config.json adapters.claude.telemetry, Claude Code's user
                                  settings), the collector's health endpoint answers (bounded) and each signal's last
                                  record is recent; exit 1 when the export is on and the collector does not answer,
                                  or receives nothing while Claude Code is active (a transcript written after the
                                  last record); a quiet spell, with no transcript since, is a warning
"""
NO_PROJECT = {"telemetry"}   # its parsers that take no --project after them: machine-wide


def register(sub, ctx) -> None:
    tm = sub.add_parser("telemetry", help="Claude Code's OpenTelemetry export as the collector stored it: summary, "
                                          "status").add_subparsers(dest="telemetry_cmd", required=True)
    sm = tm.add_parser("summary", help="per day, model and session: tokens, cost, API requests, errors and retries; "
                                       "tool decisions and failures; hook durations")
    sm.add_argument("--days", type=float, default=otel.DAYS, help=f"a rolling window: the last N x 24 hours, not whole UTC days "
                                                                    f"(default {otel.DAYS}; 0: all)")
    sm.add_argument("--session", help="only the sessions whose id starts with this")
    sm.add_argument("--top", type=int, default=otel.TOP, help=f"rows of the sessions, tools and hooks (default "
                                                              f"{otel.TOP}; 0: all)")
    sm.add_argument("--dir", help="the collector's files (default <BRAIN_HOME>/stacks/sovereign/data/otel-collector)")
    sm.add_argument("--json", action="store_true", help="one JSON object")
    st = tm.add_parser("status", help="the export on or off, the collector answering, each signal's last record")
    st.add_argument("--stale-hours", type=float, default=otel.STALE_HOURS,
                    help=f"a signal with no record for this long fails while the export is on and Claude Code "
                         f"wrote a transcript this long after its last record (default {otel.STALE_HOURS:g})")
    st.add_argument("--url", default=otel.HEALTH_URL, help=f"the collector's health endpoint (default "
                                                           f"{otel.HEALTH_URL}; loopback only)")
    st.add_argument("--timeout", type=float, default=otel.HEALTH_TIMEOUT,
                    help=f"seconds the health endpoint has to answer in full (default "
                         f"{otel.HEALTH_TIMEOUT:g}; on Windows a stopped collector may read as slow)")
    st.add_argument("--dir", help="the collector's files (default <BRAIN_HOME>/stacks/sovereign/data/otel-collector)")
    st.add_argument("--json", action="store_true", help="one JSON object")


def summary(args) -> int:
    where = Path(args.dir).expanduser() if args.dir else otel.folder()
    if not where.is_dir():
        print(f"brain telemetry summary: no collector folder {where} (brain telemetry status says why)",
              file=sys.stderr)
        return 1
    since = time.time() - args.days * 86400 if args.days and args.days > 0 else None
    stats = otel.Stats()
    s = otel.summary(otel.records(where, since=since, stats=stats), where, since, args.session, stats)
    doc = s.as_dict(top=max(args.top, 0))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("\n".join(otel.render(doc)))
    return 0


def status(args) -> int:
    from .. import ipchealth
    if not ipchealth.loopback_url(args.url):
        print(f"brain telemetry status: --url {args.url!r} is not a loopback http(s) URL", file=sys.stderr)
        return 2
    where = Path(args.dir).expanduser() if args.dir else None
    res = otel.status(config.load(root_of(args)), where, url=args.url, timeout=max(args.timeout, 0.05),
                      stale_hours=args.stale_hours)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for line in res["lines"]:
            st = line["state"]
            print(f"telemetry {st} {line['line']}" if st != "warning" else f"telemetry warning: {line['line']}")
    return res["exit"]


def early(args) -> int:
    return summary(args) if args.telemetry_cmd == "summary" else status(args)
