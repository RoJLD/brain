"""``brain audit --diff``'s norm lints (wi-brain-norm-lints; spec-brain-client-standards §2 and §4): four cheap norms
read in the AST of each Python file a change touches, at zero token.

norm.timeout      a ``subprocess.run``, ``call``, ``check_call`` or ``check_output``, or a ``urlopen``, without
                  ``timeout=``; the ``communicate()`` or ``wait()`` of a ``Popen`` without a timeout (a Popen takes
                  none itself)
norm.encoding     an ``open()`` (or ``io.open``) in text mode, a ``read_text()`` or a ``write_text()`` without
                  ``encoding=``
norm.naive-time   a naive datetime stored: ``datetime.now()`` or ``today()`` without a tz, or ``utcnow()``, made
                  text (``isoformat()``, ``str()``, an f-string), put in a dict (a record, ``dict(...)``) or given to
                  ``json.dump(s)``, directly or through a local name; ``strftime()`` (a display) and
                  ``astimezone()`` (aware) are not
norm.secret-argv  a secret passed to a child in its argv or its env: a token, password, secret or API key variable
                  (by its name: ``token``, ``gh_token``, ``password``, ``api_key``, ``self.secret``...; not a
                  ``token_path`` or a ``max_tokens``) in a subprocess call's command (a list literal, or the list a
                  local name holds), or in its ``env=`` (a dict literal, ``dict(...)``, the dict a local name holds,
                  a secret key such as ``"GH_TOKEN"`` given a value), or assigned to ``os.environ[...]`` or an
                  ``env[...]``. A secret travels by stdin or the keystore.

A call that unpacks ``**kwargs`` is not judged (the keyword may be in it), nor a mode that is not a literal. An
occurrence is told by its function and its source: one the change adds (that the file did not have, and that the
change did not move from another file) is a NEW line under config.json ``audit.norm_lints_strict`` (the owner's
opt-in), an info line otherwise (shown, never blocking: nothing that passed is newly refused). Those already in a
file the change touches, or moved there, make one DEFER line per file and norm, to the repo's debt item (fixed by
batches). A line
"Justified: <path>: <reason>" (or ``<path>::<function>``) in the PR body or a commit message turns a NEW line of it
into justified, as for the structure signals (brain.structure).
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass

from . import config, inventory, structure

STRICT_KEY = "norm_lints_strict"
SEVERITY = {"norm.timeout": "P2", "norm.encoding": "P2", "norm.naive-time": "P2", "norm.secret-argv": "P1"}
FIX = {"norm.timeout": "give it a timeout= (a hung child or server must not hang brain)",
       "norm.encoding": "say encoding='utf-8' (the console code page and the locale differ per machine)",
       "norm.naive-time": "store UTC: datetime.now(timezone.utc) (a time zone only at display)",
       "norm.secret-argv": "pass the secret by stdin or the keystore, never argv or env (other users read both)"}
RUNS = {"subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output"}
SPAWNS = RUNS | {"subprocess.Popen"}
NAIVE = {"datetime.datetime.now", "datetime.datetime.today", "datetime.datetime.utcnow"}
SECRET_PARTS = {"token", "password", "passwd", "pwd", "secret", "apikey", "passphrase", "credential", "credentials"}
KEY_KINDS = {"api", "private", "access", "secret", "auth", "signing"}   # api_key, private_key...: a bare key is not
NOT_SECRET_LAST = {"path", "file", "dir", "name", "id", "env", "var", "url", "count", "len", "kind", "type",
                   "prompt"}
NOT_SECRET_FIRST = {"max", "min", "n", "num", "total", "is", "has"}
CAMEL = re.compile(r"([a-z0-9])([A-Z])")


@dataclass(frozen=True)
class Hit:
    check: str
    scope: str    # the function's qualified name, '' at module level
    sig: str      # what tells it from another occurrence of the same scope
    line: int
    what: str     # how the why line says it


# --- names ---

def secret_name(name: str) -> bool:
    """Whether an identifier or an environment key names a secret: a token, password, secret or API key."""
    parts = [p for p in CAMEL.sub(r"\1_\2", name).lower().replace("-", "_").split("_") if p]
    if not parts or parts[-1] in NOT_SECRET_LAST or parts[0] in NOT_SECRET_FIRST:
        return False
    pairs = zip(parts, parts[1:])
    return bool(set(parts) & SECRET_PARTS) or any(b == "key" and a in KEY_KINDS for a, b in pairs)


def aliases(tree: ast.AST) -> dict[str, str]:
    """{local name: dotted origin} of a module's imports (``import subprocess as sp`` gives sp: subprocess)."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            for a in n.names:
                out[a.asname or a.name] = f"{n.module}.{a.name}"
    return out


def dotted(node: ast.AST, names: dict[str, str]) -> str:
    """The dotted name a Name or an Attribute chain stands for, its first name resolved by the imports ('' else)."""
    if isinstance(node, ast.Name):
        return names.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        head = dotted(node.value, names)
        return f"{head}.{node.attr}" if head else ""
    return ""


def _kw(call: ast.Call, name: str) -> ast.keyword | None:
    return next((k for k in call.keywords if k.arg == name), None)


def _unpacks(call: ast.Call) -> bool:
    return any(k.arg is None for k in call.keywords) or any(isinstance(a, ast.Starred) for a in call.args)


def _has(call: ast.Call, name: str, position: int) -> bool:
    """Whether ``call`` gives ``name`` (by keyword, or positionally at ``position``), or may (``**kwargs``)."""
    return _kw(call, name) is not None or len(call.args) > position or _unpacks(call)


# --- the context of a module ---

class Module:
    """One parsed text: its imports, its parents, each node's scope and the local assignments of each scope."""

    def __init__(self, tree: ast.AST):
        self.names = aliases(tree)
        self.parent: dict[ast.AST, ast.AST] = {}
        self.scope: dict[ast.AST, str] = {}
        self.assigned: dict[tuple[str, str], list[ast.AST]] = {}
        stack: list[tuple[ast.AST, str]] = [(tree, "")]
        while stack:
            node, q = stack.pop()
            self.scope[node] = q
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
                cq = f"{q}.{child.name}".lstrip(".") if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else q
                stack.append((child, cq))
            self._note(node, q)
        self.popens = {t for (_, t), vs in self.assigned.items() if any(self.spawn(v) == "subprocess.Popen"
                                                                         for v in vs)}

    def _note(self, node: ast.AST, q: str) -> None:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                self.assigned.setdefault((q, ast.unparse(t)), []).append(node.value)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and node.value is not None:
            self.assigned.setdefault((q, ast.unparse(node.target)), []).append(node.value)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            self.assigned.setdefault((q, ast.unparse(node.optional_vars)), []).append(node.context_expr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("append", "extend", "insert"):
            self.assigned.setdefault((q, ast.unparse(node.func.value)), []).extend(node.args)

    def spawn(self, node: ast.AST) -> str:
        """The subprocess function a call is ('' for any other node)."""
        if not isinstance(node, ast.Call):
            return ""
        name = dotted(node.func, self.names)
        return name if name in SPAWNS else ""

    def held(self, node: ast.AST, q: str) -> list[ast.AST]:
        """``node``, and when it is a local name what the scope assigns or appends to it."""
        return [node, *self.assigned.get((q, ast.unparse(node)), [])] if isinstance(node, ast.Name) else [node]


# --- the four norms ---

def _timeout(m: Module, n: ast.Call, q: str) -> list[Hit]:
    name = dotted(n.func, m.names)
    if name in RUNS or name.rsplit(".", 1)[-1] == "urlopen":
        pos = 2 if name.endswith("urlopen") else 99   # urlopen(url, data, timeout); run's timeout is keyword-only
        if not _has(n, "timeout", pos):
            return [Hit("norm.timeout", q, ast.unparse(n), n.lineno, f"{name.rsplit('.', 1)[-1]}() without a timeout")]
    f = n.func
    if isinstance(f, ast.Attribute) and f.attr in ("communicate", "wait") and ast.unparse(f.value) in m.popens:
        if not _has(n, "timeout", 1 if f.attr == "communicate" else 0):
            return [Hit("norm.timeout", q, ast.unparse(n), n.lineno, f"a Popen's {f.attr}() without a timeout")]
    return []


def _text_mode(n: ast.Call) -> bool | None:
    """open()'s mode: True for text, False for binary, None when not a literal."""
    mode = _kw(n, "mode")
    node = mode.value if mode else (n.args[1] if len(n.args) > 1 else None)
    if node is None:
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "b" not in node.value
    return None


def _encoding(m: Module, n: ast.Call, q: str) -> list[Hit]:
    name, f = dotted(n.func, m.names), n.func
    if name in ("open", "io.open"):
        if _text_mode(n) and not _has(n, "encoding", 3):
            return [Hit("norm.encoding", q, ast.unparse(n), n.lineno, "open() in text mode without an encoding")]
    elif isinstance(f, ast.Attribute) and f.attr in ("read_text", "write_text"):
        if not _has(n, "encoding", 0 if f.attr == "read_text" else 1):
            return [Hit("norm.encoding", q, ast.unparse(n), n.lineno, f"{f.attr}() without an encoding")]
    return []


def _naive(m: Module, n: ast.Call) -> bool:
    name = dotted(n.func, m.names)
    if name not in NAIVE:
        return False
    if name.endswith(("utcnow", "today")):
        return True
    tz = _kw(n, "tz")
    arg = tz.value if tz else (n.args[0] if n.args else None)
    return arg is None or (isinstance(arg, ast.Constant) and arg.value is None)


def _chained(m: Module, e: ast.AST) -> tuple[ast.AST, str]:
    """(the outermost expression of ``e``'s chain of replace() calls, the next method called on it or '')."""
    while True:
        p = m.parent.get(e)
        call = m.parent.get(p) if isinstance(p, ast.Attribute) else None
        if not (isinstance(call, ast.Call) and call.func is p):
            return e, ""
        if p.attr != "replace":
            return e, p.attr
        e = call


def _store(m: Module, e: ast.AST) -> str:
    """How the value ``e`` is stored: 'isoformat()', 'str()', 'an f-string', 'a dict', 'json.dump', or ''."""
    e, method = _chained(m, e)
    if method:
        return "isoformat()" if method == "isoformat" else ""
    p = m.parent.get(e)
    if isinstance(p, ast.FormattedValue):
        return "an f-string"
    if isinstance(p, ast.Dict) and any(v is e for v in p.values):
        return "a dict"
    if isinstance(p, ast.keyword):
        p = m.parent.get(p)
        return "a dict" if isinstance(p, ast.Call) and dotted(p.func, m.names) == "dict" else ""
    if isinstance(p, ast.Call) and any(a is e for a in p.args):
        return {"str": "str()", "json.dump": "json.dump", "json.dumps": "json.dump"}.get(dotted(p.func, m.names), "")
    return ""


def _uses(m: Module, e: ast.AST, q: str) -> tuple[str, str]:
    """(how the naive value ``e`` is stored, the local name it goes through or '')."""
    how = _store(m, e)
    p = m.parent.get(_chained(m, e)[0])
    if how or not (isinstance(p, ast.Assign) and len(p.targets) == 1 and isinstance(p.targets[0], ast.Name)):
        return how, ""
    var = p.targets[0].id
    for x, xq in m.scope.items():
        if xq == q and isinstance(x, ast.Name) and x.id == var and isinstance(x.ctx, ast.Load):
            how = _store(m, x)
            if how:
                return how, var
    return "", var


def _naive_time(m: Module, n: ast.Call, q: str) -> list[Hit]:
    if not _naive(m, n):
        return []
    how, var = _uses(m, n, q)
    if not how:
        return []
    via = f" (through {var})" if var else ""
    return [Hit("norm.naive-time", q, f"{ast.unparse(n)}{via} -> {how}", n.lineno,
                f"a naive {ast.unparse(n)} stored by {how}{via}")]


def _secrets_in(node: ast.AST) -> list[str]:
    """The secret names (variables, attributes, calls such as get_token()) an expression reads."""
    out = []
    for x in ast.walk(node):
        name = x.id if isinstance(x, ast.Name) else x.attr if isinstance(x, ast.Attribute) else ""
        if name and secret_name(name):
            out.append(ast.unparse(x))
    return out


def _entry(key: str, value: ast.AST) -> list[str]:
    """The secrets one env entry gives: its key when a secret's and given a value, else the secrets its value reads."""
    return [key] if key and secret_name(key) and not isinstance(value, ast.Constant) else _secrets_in(value)


def _env_secrets(value: ast.AST) -> list[str]:
    """The secrets an env mapping gives a child: a secret key given a value, or a secret value."""
    if isinstance(value, ast.Dict):
        return [s for k, v in zip(value.keys, value.values)
                for s in _entry(k.value if isinstance(k, ast.Constant) and isinstance(k.value, str) else "", v)]
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "dict":
        return [s for k in value.keywords for s in _entry(k.arg or "", k.value)]
    return []


def _argv_env(m: Module, n: ast.Call, q: str) -> list[Hit]:
    call = m.spawn(n)
    if not call:
        return []
    cmd = n.args[0] if n.args else (_kw(n, "args").value if _kw(n, "args") else None)
    env = _kw(n, "env")
    found = [("argv", s) for c in (m.held(cmd, q) if cmd is not None else []) for s in _secrets_in(c)]
    found += [("env", s) for v in (m.held(env.value, q) if env else []) for s in _env_secrets(v)]
    return [Hit("norm.secret-argv", q, f"{where}:{s}:{call}", n.lineno, f"{s} in the {where} of {call}()")
            for where, s in dict.fromkeys(found)]


def _environ_set(m: Module, n: ast.Assign, q: str) -> list[Hit]:
    """``os.environ["GH_TOKEN"] = token`` or ``env["GH_TOKEN"] = token``: a secret every child inherits."""
    out = []
    for t in n.targets:
        if not (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str)):
            continue
        holder = dotted(t.value, m.names) or ast.unparse(t.value)
        if (holder == "os.environ" or holder.lower().endswith(("env", "environ"))) and secret_name(t.slice.value) \
                and not isinstance(n.value, ast.Constant):
            out.append(Hit("norm.secret-argv", q, f"env:{ast.unparse(t)}", n.lineno,
                           f"{t.slice.value} set in {holder} for the children"))
    return out


def hits(text: str | None) -> list[Hit]:
    """Every norm occurrence of a Python text ([] when it does not parse)."""
    tree = structure._parse(text)
    if tree is None:
        return []
    m, out = Module(tree), []
    for n, q in m.scope.items():
        if isinstance(n, ast.Call):
            out += _timeout(m, n, q) + _encoding(m, n, q) + _naive_time(m, n, q) + _argv_env(m, n, q)
        elif isinstance(n, ast.Assign):
            out += _environ_set(m, n, q)
    return sorted(out, key=lambda h: (h.line, h.check, h.sig))


# --- the findings of a change ---

def strict(root) -> bool:
    """Whether the owner opts in to NEW lines for the norms a change adds (config.json ``audit.norm_lints_strict``
    true); default false: info lines, never blocking."""
    opts = config.load(root).data.get("audit")
    return isinstance(opts, dict) and opts.get(STRICT_KEY) is True


def _key(h: Hit) -> tuple[str, str, str]:
    return h.check, h.scope, h.sig


def _split(before: list[Hit], after: list[Hit], moved: Counter) -> tuple[list[Hit], list[Hit]]:
    """(the occurrences of ``after`` the change adds, those already there or moved here from another file)."""
    seen = Counter(_key(h) for h in before)
    added, old = [], []
    for h in after:
        k = _key(h)
        if seen[k] > 0:
            seen[k] -= 1
            old.append(h)
        elif moved[k] > 0:
            moved[k] -= 1
            old.append(h)
        else:
            added.append(h)
    return added, old


def _finding(repo: str, check: str, unit: str, line: str, why: str, tag: str) -> dict:
    return {"key": f"{repo}:{check}:{unit}{line}", "check": check, "severity": SEVERITY[check], "unit": unit,
            "class": "", "chain": "", "via": "", "why": why, "fix": FIX[check], "tag": tag}


def _added(repo: str, path: str, h: Hit, strict_: bool) -> dict:
    unit = f"{path}::{h.scope}" if h.scope else path
    why = f"line {h.line}: {h.what}" + ("" if strict_ else " (advisory: NEW under config.json audit."
                                                          f"{STRICT_KEY})")
    return _finding(repo, h.check, unit, f":{h.line}", why, "NEW" if strict_ else "info")


def _deferred(repo: str, path: str, old: list[Hit]) -> list[dict]:
    out = []
    for check in SEVERITY:
        lines = [h.line for h in old if h.check == check]
        if lines:
            shown = ", ".join(map(str, lines[:8])) + (", ..." if len(lines) > 8 else "")
            out.append(_finding(repo, check, path, "", f"{len(lines)} already in the file (line {shown}): "
                                f"{FIX[check]}, by batches", "DEFER"))
    return out


def signals(repo: str, rows: list[tuple[str, str, str]], base: inventory.Tree, new: inventory.Tree, body: str,
            strict_: bool = False) -> list[dict]:
    """The norm findings of a change: ``rows`` the scout's (status, old path, new path), ``body`` the PR body and
    commit messages (its Justified: lines), ``strict_`` the owner's opt-in (:func:`strict`)."""
    files = []
    for _, old, path in rows:
        was = old or path
        before = hits(base.text(was)) if was.endswith(".py") and base.has(was) else []
        after = hits(new.text(path)) if path.endswith(".py") and new.text(path) is not None else []
        files.append((path, before, after))
    moved = sum((Counter(map(_key, b)) - Counter(map(_key, a)) for _, b, a in files), Counter())
    out = []
    for path, before, after in files:
        added, old = _split(before, after, moved)
        out += [_added(repo, path, h, strict_) for h in added] + _deferred(repo, path, old)
    justified = {m.group(1).strip() for m in structure.JUSTIFIED.finditer(body)}
    for f in out:
        if f["tag"] == "NEW" and {f["unit"], f["unit"].split("::", 1)[0]} & justified:
            f["tag"] = "justified"
    return out
