"""``brain code-map``: each active CodeRef of the project's stores resolved to its GitNexus node, written to
<BRAIN_HOME>/code-map/<project>.json, with the coverage and the CodeRefs that do not resolve (brain.codemap).
"""

from __future__ import annotations

from pathlib import Path

from ._common import _project

ORDER = 380   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 470   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain code-map [--json]   each active CodeRef of the project's stores resolved to its GitNexus node (filePath,
                                  name, label) into $BRAIN_HOME/code-map/<project>.json, the coverage per repo
                                  (symbols and files with a CodeRef) and the CodeRefs that do not resolve, with why;
                                  exit 1 when GitNexus does not answer (brain.codemap)
"""


def cmd_code_map(args, root: Path) -> int:
    """brain code-map (brain.codemap): the project here or --project's."""
    from .. import codemap
    return codemap.main(_project(args, root), root, as_json=args.json)


def register(sub, ctx) -> None:
    cmp_ = sub.add_parser("code-map", help="each active CodeRef of the project's stores resolved to its GitNexus node, "
                                           "written to <BRAIN_HOME>/code-map/<project>.json, with the coverage and "
                                           "the CodeRefs that do not resolve (brain.codemap)")
    cmp_.add_argument("--json", action="store_true", help="print the map")


run = cmd_code_map
