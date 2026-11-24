"""The inventory's code facts (brain.inventory): the text patterns it reads code, tests and docs with, a path's
normal form, and the facts of a Python file read from its AST (imports, definitions, the scripts it runs), cached by
blob id. Zero token: a file is parsed, never imported or run."""

from __future__ import annotations

import ast
import posixpath
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotations only: brain.inventory imports this module
    from .inventory import Tree

IDENT = re.compile(r"[A-Za-z_]\w*")
DOTTED = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
DOTTED_FULL = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
FILE_REF = re.compile(r"(?<![\w.-])((?:[\w.-]+[/\\])*[\w.-]*[\w-]\.(?:py|ps1|psm1|psd1|sh|bat|cmd))(?![\w-])")
WORD = re.compile(r"[\w-]+")
STRING = re.compile(r"""(['"])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|[A-Za-z0-9][\w-]*)\1""")
IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^\n]*)"
                    r"|import[ \t]+([^\n]*))", re.M)
SUBPARSER = re.compile(r"""\badd_parser\(\s*["']([\w-]+)["']""")
FIXTURE = re.compile(r"""([=(,\[]\s*)[rRbBuUfF]{0,2}("{3}|'{3}).*?\2""", re.S)
RUN = re.compile(r"""subprocess\.|\bPopen\(|\bcheck_output\(|\bcheck_call\(|\bos\.system\(|\brunpy\b|\brun_path\(|"""
                 r"""\brun_module\(|["'](?:powershell|pwsh|bash|sh|cmd)(?:\.exe)?["']\s*[,\]]|["']-File["']""")
ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?::[^=\n]*)?=(?!=)")
DEF = re.compile(r"^(\s*)(?:async\s+)?def\s+([A-Za-z_]\w*)")
USED = re.compile(r"(?<![.\w])([A-Za-z_]\w*)(?!\w)(?!\s*\()(?!\s*=[^=])")
TRIPLE = re.compile(r"""("{3}|'{3}).*?\1""", re.S)
STR = re.compile(r"""(["'])(?:\\.|(?!\1).)*\1""")


def _norm(p) -> str:
    p = posixpath.normpath(str(p).replace("\\", "/"))
    return "" if p in (".", "") else p.strip("/")


@dataclass(frozen=True)
class PyFacts:
    parsed: bool
    imports: tuple = ()        # (module, level, names, function) of every import statement; function: the outermost
    #                            def it sits in ('' at module level, in a class body or under the main guard)
    defs: bool = False         # a top-level def or class
    main_guard: bool = False   # if __name__ == "__main__"
    statements: int = 0        # top-level statements, the docstring left out
    strings: frozenset = frozenset()   # string constants shaped like a dotted name, or a command name
    lines: int = 0
    subcommands: frozenset = frozenset()   # argparse subcommands it declares (add_parser("name"))
    discovers: bool = False    # it imports its own package's modules by listing them, pkgutil.iter_modules(__path__)
    #                            (a command registry, brain.commands): an import of each one


_FACTS: dict[str, PyFacts] = {}
_TREES: dict[str, ast.Module | None] = {}


def _is_guard(stmt) -> bool:
    if not isinstance(stmt, ast.If) or not isinstance(stmt.test, ast.Compare) or len(stmt.test.comparators) != 1:
        return False
    sides = [stmt.test.left, stmt.test.comparators[0]]
    return ({type(s).__name__ for s in sides} == {"Name", "Constant"}
            and any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
            and any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides))


def _discovers(mod: ast.Module) -> bool:
    """A call of iter_modules(__path__) (pkgutil's): the module lists its own package's modules to import them."""
    return any(isinstance(n, ast.Call) and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
               == "iter_modules" and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "__path__"
               for n in ast.walk(mod))


def _imports(body, out: list, func: str = "") -> None:
    """Every import statement of a body and of the bodies nested in it (functions, classes, if, try, with...), with
    the outermost function it sits in."""
    for s in body:
        if isinstance(s, ast.Import):
            out += [(a.name, 0, (), func) for a in s.names]
        elif isinstance(s, ast.ImportFrom):
            out.append((s.module or "", s.level or 0, tuple(a.name for a in s.names), func))
        else:
            inner = func or (s.name if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) else "")
            for fld in ("body", "orelse", "finalbody"):
                sub = getattr(s, fld, None)
                if isinstance(sub, list):
                    _imports(sub, out, inner)
            for h in getattr(s, "handlers", None) or getattr(s, "cases", None) or ():
                _imports(h.body, out, inner)


def text_imports(text: str) -> list[tuple[str, int, tuple]]:
    """Import statements found by pattern (a test's evidence, no parse): (module, level, names)."""
    out = []
    for m in IMPORT.finditer(text):
        if m.group(4) is not None:
            for part in m.group(4).split("#")[0].split(","):
                name = part.split()[0] if part.split() else ""
                if DOTTED_FULL.fullmatch(name) or IDENT.fullmatch(name):
                    out.append((name, 0, ()))
        else:   # comments are cut line by line: a '# noqa' after '(' must not hide the names below it
            body = "\n".join(ln.split("#", 1)[0] for ln in m.group(3).strip("()").splitlines())
            names = tuple(n.split()[0] for n in body.replace("\n", ",").split(",")
                          if n.split() and IDENT.fullmatch(n.split()[0]))
            out.append((m.group(2), len(m.group(1)), names))
    return out


def without_fixtures(text: str) -> str:
    """A test's text without the triple-quoted strings it uses as values (sample code, expected output): the names in
    them are not evidence. Docstrings stay."""
    return FIXTURE.sub(lambda m: m.group(1) + "''", text)


def _code_part(line: str) -> str:
    """A Python line without its comment (a '#' outside quotes)."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def _statements(lines: list[str]) -> list[str]:
    """Physical lines joined into statements (open brackets continue a statement; a def or class starts one)."""
    out, buf, depth = [], [], 0
    for ln in lines:
        if buf and (DEF.match(ln) or re.match(r"\s*(?:class|@)\b", ln)):
            out.append(" ".join(buf))
            buf, depth = [], 0
        buf.append(ln)
        bare = STR.sub("", ln)
        depth += sum(bare.count(c) for c in "([{") - sum(bare.count(c) for c in ")]}")
        if depth <= 0:
            out.append(" ".join(buf))
            buf, depth = [], 0
    return out + ([" ".join(buf)] if buf else [])


def run_mentions(text: str) -> list[str]:
    """The script file names a Python test runs: in a statement that starts a process (subprocess, os.system, runpy,
    powershell, pwsh, bash) or calls a function of the test whose body starts one, or bound to a name such a
    statement uses (directly or through other names); never in a comment, a docstring, a fixture string or a CodeRef
    id."""
    lines = [_code_part(ln) for ln in TRIPLE.sub("''", text).splitlines()]
    runners = set()
    for i, ln in enumerate(lines):
        m = DEF.match(ln)
        if not m:
            continue
        ind = len(m.group(1))
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= ind:
                break
            if RUN.search(nxt):
                runners.add(m.group(2))
                break
    call = re.compile(rf"\b(?:{'|'.join(map(re.escape, sorted(runners)))})\(") if runners else None

    def runs(ln: str) -> bool:
        return bool(RUN.search(ln) or (call and call.search(ln)))

    stmts = _statements(lines)
    names: set = set()
    for ln in stmts:
        if runs(ln):
            names.update(USED.findall(ln))
    assigns = [(m.group(1), ln[m.end():]) for ln in stmts for m in [ASSIGN.match(ln)] if m]
    for _ in range(3):   # a name a run statement uses, bound from other names
        grew = {w for n, rhs in assigns if n in names for w in USED.findall(rhs)} - names
        if not grew:
            break
        names |= grew
    out = []
    for ln in stmts:
        toks = [m.group(1) for m in FILE_REF.finditer(ln) if not re.search(r"code:[\w.-]+:$", ln[:m.start()])]
        a = ASSIGN.match(ln)
        if toks and (runs(ln) or (a and a.group(1) in names)):
            out += toks
    return out


def _parse(key: str, text: str) -> ast.Module | None:
    if key not in _TREES:
        try:
            _TREES[key] = ast.parse(text)
        except (SyntaxError, ValueError):
            _TREES[key] = None
    return _TREES[key]


def facts(tree: Tree, path: str) -> PyFacts:
    key = tree.key(path) or f"{tree.repo}:{path}"
    if key in _FACTS:
        return _FACTS[key]
    text = tree.text(path) or ""
    mod = _parse(key, text)
    if mod is None:
        out = PyFacts(False, lines=text.count("\n") + 1)
    else:
        imports: list = []
        _imports(mod.body, imports)
        strings = {m.group(2) for m in STRING.finditer(text)}
        body = mod.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        out = PyFacts(True, tuple(imports),
                      any(isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for s in mod.body),
                      any(_is_guard(s) for s in mod.body), len(body), frozenset(strings), text.count("\n") + 1,
                      frozenset(SUBPARSER.findall(text)), _discovers(mod))
    _FACTS[key] = out
    return out


def _definitions(body):
    """(name, node) of a module or class body's definitions, looking into if/try blocks (research_graph's
    code_layer)."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield stmt.name, stmt
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                for n in ast.walk(t) if isinstance(t, (ast.Tuple, ast.List)) else [t]:
                    if isinstance(n, ast.Name):
                        yield n.id, stmt
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            yield stmt.target.id, stmt
        elif isinstance(stmt, ast.If):
            yield from _definitions(stmt.body)
            yield from _definitions(stmt.orelse)
        elif isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
            yield from _definitions(stmt.body)
            for h in stmt.handlers:
                yield from _definitions(h.body)
            yield from _definitions(stmt.orelse)
            yield from _definitions(stmt.finalbody)


def has_symbol(tree: Tree, path: str, symbol: str) -> bool | None:
    """Whether ``symbol`` (``A`` or ``A.b``) is defined in the Python file; None when it does not parse."""
    mod = _parse(tree.key(path) or f"{tree.repo}:{path}", tree.text(path) or "")
    if mod is None:
        return None
    body, node = mod.body, None
    for i, part in enumerate(symbol.split(".")):
        if i:
            if not isinstance(node, ast.ClassDef):
                return False
            body = node.body
        node = next((n for name, n in _definitions(body) if name == part), None)
        if node is None:
            return False
    return True
