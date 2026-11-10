"""brain audit's feature coverage (check ``feature.coverage``, wi-brain-audit-feature-coverage): the commands and
modules of a repo's command registry that no feature names, at zero token.

The units: in each package of the repo whose ``commands/`` lists its own modules (a command registry, brain.commands),
each command module of ``commands/`` (not the ``_`` helpers) and each module beside its ``cli.py`` (not the ``__``
files). A feature names one when an active ``implemented_by`` CodeRef of it points at the unit's file (a symbol's
CodeRef names its file), or when its title says the unit: ``<console> <command>`` for a command module (each command
its ``register`` adds on its first parameter, else the file's stem; the console scripts that run the package, else
its name), the dotted name for a module (``pkg.stateio``). Any feature of the project's stores counts, whatever its
status: the matrix lists the capability.

brain.audit runs it on every repo (info findings, never counted, and a section of the full audit); brain.scout makes
the one of a command or module the change adds a NEW line, and the one of a touched unit already there a DEFER line
to the repo's debt item, or a LEFT line under config.json ``audit.feature_coverage_strict`` (the owner's opt-in).
"""

from __future__ import annotations

import ast
import posixpath
import re
from dataclasses import dataclass

from . import config, inventory
from .features import Model

STRICT_KEY = "feature_coverage_strict"


@dataclass(frozen=True)
class Target:
    unit: inventory.Unit
    kind: str                  # command or module
    label: str                 # how it is said: 'brain quiet', 'brain.stateio'
    phrases: tuple[str, ...]   # what a title that names it says


def feature_paths(fm: Model, repo: str) -> set[str]:
    """The files of ``repo`` (as written and under src/) an active implemented_by CodeRef of a feature names."""
    out: set[str] = set()
    for fid in fm.features:
        for cid in fm.code(fid):
            try:
                r, path, _ = inventory.parse_code_ref(cid)
            except ValueError:
                continue   # coderef.dangling reports it
            if r.lower() == repo:
                out.update({path, f"src/{path}"})
    return out


def _parser_name(n: ast.AST, sub: str) -> str:
    """The literal name of a ``<sub>.add_parser("name", ...)`` call ('' for any other node)."""
    f = getattr(n, "func", None)
    if not (isinstance(f, ast.Attribute) and f.attr == "add_parser" and isinstance(f.value, ast.Name)
            and f.value.id == sub):
        return ""
    a = n.args[0] if n.args else None
    return a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else ""


def top_commands(text: str) -> list[str]:
    """The commands a command module's ``register(sub, ctx)`` adds: the literal names of the ``add_parser`` calls on
    its first parameter, in source order (the subcommands' parsers are left out)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    reg = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "register" and n.args.args),
               None)
    if reg is None:
        return []
    calls = sorted((n for n in ast.walk(reg) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))
    return [x for x in (_parser_name(n, reg.args.args[0].arg) for n in calls) if x]


def _consoles(rf: inventory.RepoFacts, top: str) -> list[str]:
    """How the package in the folder ``top`` is run: the console scripts whose module is in it, else its name."""
    dotted = next((d.rsplit(".", 1)[0] for d, p in sorted(rf.modules.items()) if posixpath.dirname(p) == top
                   and "." in d), "")
    got = sorted(c for c, m in rf.console.items() if dotted and (m == dotted or m.startswith(dotted + ".")))
    return got or [dotted.rsplit(".", 1)[-1] or posixpath.basename(top)]


def _target(rf: inventory.RepoFacts, u: inventory.Unit, pkg: str, consoles: list[str]) -> Target | None:
    """``u`` as a target of the registry ``pkg`` (None when it is not one: a ``__`` file, a ``_`` helper of commands/,
    a module elsewhere)."""
    folder, base = posixpath.split(u.path)
    if u.kind != "module" or base.startswith("__"):
        return None
    if folder == pkg.rstrip("/"):
        return Target(u, "module", u.name, (u.name,))
    if folder != f"{pkg}commands" or base.startswith("_"):
        return None
    cmds = top_commands(rf.tree.text(u.path) or "") or [base[:-3].replace("_", "-")]
    said = tuple(f"{c} {cmd}" for c in consoles for cmd in cmds)
    return Target(u, "command", said[0], said + (u.name,))


def targets(rf: inventory.RepoFacts, registries: list[str]) -> list[Target]:
    """The commands and modules of each command registry (``registries``: the package prefixes, brain.audit's
    _registries) with the phrases a title names each by."""
    out: list[Target] = []
    for pkg in registries:
        consoles = _consoles(rf, pkg.rstrip("/"))
        out += [t for t in (_target(rf, u, pkg, consoles) for u in rf.units) if t is not None]
    return out


def _says(title: str, phrase: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(phrase)}(?![\w-])", title) is not None


def unnamed(fm: Model, repo: str, found: list[Target]) -> list[Target]:
    """The targets no feature names: no active implemented_by of their file, no title that says them."""
    paths = feature_paths(fm, repo)
    titles = [str(n.get("title") or "") for n in fm.features.values()]
    return [t for t in found if t.unit.path not in paths
            and not any(_says(title, ph) for title in titles for ph in t.phrases)]


def summary(found: list[Target], missing: list[Target]) -> dict:
    """The full audit's section for a repo: {units, named, unnamed: [{unit, kind, name}]}."""
    return {"units": len(found), "named": len(found) - len(missing),
            "unnamed": [{"unit": t.unit.path, "kind": t.kind, "name": t.label} for t in missing]}


def text_line(s: dict) -> str:
    """brain audit's line for a repo's section."""
    head = f"  feature coverage: {s['named']} of {s['units']} commands and modules named by a feature"
    return head + ("; no feature names: " + ", ".join(f"{x['name']} ({x['unit']})" for x in s["unnamed"])
                   if s["unnamed"] else "")


def view_lines(s: dict) -> list[str]:
    """notes/audit.md's section for a repo."""
    out = ["### Feature coverage", "", f"{s['named']} of {s['units']} commands and modules named by a feature (an "
           "implemented_by of their file, or a title that says them)."]
    if s["unnamed"]:
        out += ["", "No feature names:", ""] + [f"- {x['kind']} `{x['name']}` (`{x['unit']}`)" for x in s["unnamed"]]
    return out + [""]


def strict(root) -> bool:
    """Whether the owner opts in to a LEFT line for a touched command or module no feature names (config.json
    ``audit.feature_coverage_strict`` true); default false: a DEFER line to the repo's debt item."""
    opts = config.load(root).data.get("audit")
    return isinstance(opts, dict) and opts.get(STRICT_KEY) is True
