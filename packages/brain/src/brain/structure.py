"""``brain audit --diff``'s structure signals: the shape a change gives the code, measured on the change at zero token
(wi-brain-audit-structure; EXT-4, EXT-5 of the ADR on external kits). The scout's checks (brain.scout) see what goes
with a change (a test, the docs, the graph links); these see what the change does to the code itself.

size.cross        a code file the change takes past ``max_lines`` (NEW: split it in this PR, or justify it)
size.grow         a code file already past ``max_lines`` that the change grows again (DEFER to the repo's debt item,
                  SCOUT-1: the split is the debt's, not this PR's)
complexity.cross  a Python function whose cyclomatic complexity the change takes past ``complexity`` (NEW)
complexity.grow   a function already past it that the change makes more complex (DEFER)
dep.adr           a dependency the change adds to a manifest (pyproject.toml, requirements*.txt, package.json) that no
                  decision log of the project names (NEW)
shortcut.marker   a ``shortcut:`` comment the change adds without its ceiling, its trigger or its debt item (NEW)
symptom.cause     a symptom fix the change adds (a ``type: ignore`` or ``noqa`` comment, a skipped test, an ``except``
                  that swallows everything, a sleep, a retry, a longer timeout) with no "Root cause:" line in the PR
                  body or a commit message of the range (NEW; with the line it is shown as justified); a skipped test
                  is one turned off as such (``@pytest.mark.skip``, ``@unittest.skip``, ``xfail``), not a guard
                  (``skipif``, ``pytest.skip("git not available")``)

A line "Justified: <unit>: <reason>" in the PR body (``--pr-body FILE``) or a commit message of the range turns the
NEW finding of that unit into ``justified``: shown, never blocking. The thresholds are the project's (projects.yaml
``audit: {max_lines, complexity}``), :data:`DEFAULTS` otherwise. Everything is read from the two trees the scout
already holds: no diff is parsed, so a moved line is not an added one.
"""

from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from collections import Counter
from pathlib import Path

from . import inventory
from .inventory import git

DEFAULTS = {"max_lines": 1000, "complexity": 15}
CODE_EXTS = {".py", ".sh", ".bash", ".ps1", ".psm1", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs",
             ".java", ".kt", ".rb", ".cs", ".c", ".h", ".cpp", ".hpp"}
SCRIPT_EXTS = {".sh", ".bash", ".ps1", ".psm1", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
SEVERITY = {"size.cross": "P2", "size.grow": "P2", "complexity.cross": "P2", "complexity.grow": "P2",
            "dep.adr": "P1", "shortcut.marker": "P2", "symptom.cause": "P1"}
ROOT_CAUSE = re.compile(r"^\s*(?:[-*>]\s*)?(?:\*\*|__)?(?:root[ -]cause|cause racine)\b[^\n:]*:\s*\S",
                        re.IGNORECASE | re.MULTILINE)
JUSTIFIED = re.compile(r"^\s*(?:[-*>]\s*)?(?:\*\*|__)?justified(?:\*\*|__)?\s*:\s*`?([^\s`:]+(?:::[\w.]+)?)`?\s*:\s*\S",
                       re.IGNORECASE | re.MULTILINE)
SHORTCUT = re.compile(r"\bshortcut:", re.IGNORECASE)
CEILING = re.compile(r"\bceiling\s*[:=]", re.IGNORECASE)
TRIGGER = re.compile(r"\btrigger\s*[:=]", re.IGNORECASE)
ITEM = re.compile(r"\bwi-[a-z0-9][a-z0-9-]*")
TYPE_IGNORE = re.compile(r"type:\s*ignore")
NOQA = re.compile(r"\bnoqa\b", re.IGNORECASE)
REQUIREMENTS = re.compile(r"requirements[\w.-]*\.txt")
NPM_SECTIONS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
DECISION_FILE = re.compile(r"decision|(^|/)adrs?/", re.IGNORECASE)
SKIPS = {"skip", "xfail"}   # a test turned off as such (@pytest.mark.skip, @unittest.skip); skipif is a guard
BROAD = {"Exception", "BaseException"}
RETRY_CALL = re.compile(r"^(?:retry|retrying|Retry|backoff)$")          # @retry, Retry(...), tenacity, backoff
RETRY_LOOP = re.compile(r"^(?:attempts?|retry|retries|tries)$")          # for attempt in range(3)
RETRY_ARG = re.compile(r"^(?:max_)?retries$|^(?:max_)?attempts$")       # retries=3
TIMEOUT = re.compile(r"timeout", re.IGNORECASE)
LINE_SLEEP = re.compile(r"\b(?:sleep|Start-Sleep)\b\s+(?:-\w+\s+)?\d")
LINE_RETRY = re.compile(r"\bretr(?:y|ies)\b", re.IGNORECASE)
LINE_TIMEOUT = re.compile(r"timeout[\w-]*['\"]?\s*[:=]\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
LINE_COMMENT = re.compile(r"^\s*(?:#|//|<#|--|/\*|\*)")
WHAT = {"type-ignore": "a type: ignore", "noqa": "a noqa", "skip": "a skipped test",
        "swallow": "an except that swallows everything", "sleep": "a sleep", "retry": "a retry",
        "timeout": "a longer timeout"}


def thresholds(audit_cfg: dict | None) -> dict:
    """max_lines and complexity: the project's audit: block over :data:`DEFAULTS`."""
    return {k: int((audit_cfg or {}).get(k) or v) for k, v in DEFAULTS.items()}


def _lines(text: str | None) -> int:
    return 0 if not text else text.count("\n") + (not text.endswith("\n"))


def _parse(text: str | None) -> ast.AST | None:
    try:
        return ast.parse(text or "")
    except (SyntaxError, ValueError):
        return None


# --- cyclomatic complexity (McCabe: 1 + the decision points; a nested function or class counts on its own) ---

def _complexity(fn: ast.AST) -> int:
    n, stack = 1, list(ast.iter_child_nodes(fn))
    while stack:
        x = stack.pop()
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(x, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)):
            n += 1
        elif isinstance(x, ast.BoolOp):
            n += len(x.values) - 1
        elif isinstance(x, ast.comprehension):
            n += 1 + len(x.ifs)
        elif type(x).__name__ == "match_case":
            n += 1
        stack.extend(ast.iter_child_nodes(x))
    return n


def complexities(text: str | None) -> dict[str, int]:
    """{qualified name: cyclomatic complexity} of every function of a Python text ({} when it does not parse)."""
    tree, out = _parse(text), {}

    def walk(node: ast.AST, prefix: str) -> None:
        for x in ast.iter_child_nodes(node):
            if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[prefix + x.name] = _complexity(x)
                walk(x, f"{prefix}{x.name}.")
            elif isinstance(x, ast.ClassDef):
                walk(x, f"{prefix}{x.name}.")
            else:
                walk(x, prefix)

    if tree is not None:
        walk(tree, "")
    return out


# --- the symptom fixes and the shortcut markers ---

def comment_blocks(text: str | None, path: str) -> list[str]:
    """The comments of a file, consecutive comment lines joined into one block (a marker may run over a few
    lines). Python through tokenize (a string that holds '# noqa' is not a comment), else the lines that start
    like a comment."""
    rows: list[tuple[int, str]] = []
    if path.endswith(".py"):
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text or "").readline):
                if tok.type == tokenize.COMMENT:
                    rows.append((tok.start[0], tok.string))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            return []
    else:
        rows = [(i, ln.strip()) for i, ln in enumerate((text or "").splitlines(), 1) if LINE_COMMENT.match(ln)]
    blocks: list[str] = []
    last = -2
    for n, c in rows:
        if n == last + 1 and blocks:
            blocks[-1] += "\n" + c
        else:
            blocks.append(c)
        last = n
    return blocks


def _swallows(h: ast.ExceptHandler) -> bool:
    t = h.type
    names = [t] if not isinstance(t, ast.Tuple) else list(t.elts)
    broad = t is None or any(isinstance(x, ast.Name) and x.id in BROAD for x in names)
    quiet = all(isinstance(s, (ast.Pass, ast.Continue, ast.Break))
                or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                or (isinstance(s, ast.Return) and (s.value is None or isinstance(s.value, ast.Constant)))
                for s in h.body)
    return broad and quiet


def _number(node: ast.AST | None) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    return None


def _call_name(x: ast.Call) -> str:
    return getattr(x.func, "attr", None) or getattr(x.func, "id", None) or ""


def _timeout_value(x: ast.AST) -> float | None:
    """The number a timeout keyword or a timeout variable is given, else None."""
    if isinstance(x, ast.keyword):
        return _number(x.value) if x.arg and TIMEOUT.search(x.arg) else None
    if isinstance(x, (ast.Assign, ast.AnnAssign)):
        targets = x.targets if isinstance(x, ast.Assign) else [x.target]
        if any(isinstance(t, ast.Name) and TIMEOUT.search(t.id) for t in targets):
            return _number(x.value)
    return None


def _kind_def(x: ast.AST) -> str:
    for d in x.decorator_list:
        d = d.func if isinstance(d, ast.Call) else d
        if (getattr(d, "attr", None) or getattr(d, "id", None)) in SKIPS:
            return "skip"
    return ""


def _kind_call(x: ast.Call) -> str:
    name = _call_name(x)
    return "sleep" if name == "sleep" else "retry" if RETRY_CALL.match(name) else ""


def _kind_loop(x: ast.For) -> str:
    return "retry" if isinstance(x.target, ast.Name) and RETRY_LOOP.match(x.target.id) else ""


def _kind_keyword(x: ast.keyword) -> str:
    return "retry" if x.arg and RETRY_ARG.match(x.arg) and _number(x.value) is not None else ""


NODE_KINDS = {ast.FunctionDef: _kind_def, ast.AsyncFunctionDef: _kind_def, ast.ClassDef: _kind_def,
              ast.Call: _kind_call, ast.For: _kind_loop,
              ast.AsyncFor: _kind_loop, ast.keyword: _kind_keyword,
              ast.ExceptHandler: lambda x: "swallow" if _swallows(x) else ""}


def _node_kind(x: ast.AST) -> str:
    """The symptom one AST node stands for, or ''."""
    kind = NODE_KINDS.get(type(x))
    return kind(x) if kind else ""


def py_symptoms(text: str | None) -> tuple[Counter, Counter]:
    """(how many of each symptom kind, the timeout values) of a Python text."""
    kinds, timeouts = Counter(), Counter()
    for block in comment_blocks(text, "x.py"):
        kinds["type-ignore"] += len(TYPE_IGNORE.findall(block))
        kinds["noqa"] += len(NOQA.findall(block))
    tree = _parse(text)
    for x in ast.walk(tree) if tree is not None else ():
        kinds[_node_kind(x)] += 1
        v = _timeout_value(x)
        if v is not None:
            timeouts[v] += 1
    kinds.pop("", None)
    return kinds, timeouts


def line_symptoms(text: str | None) -> tuple[Counter, Counter]:
    """The same for a shell, PowerShell or JavaScript file, line by line."""
    kinds, timeouts = Counter(), Counter()
    for ln in (text or "").splitlines():
        if LINE_COMMENT.match(ln):
            continue
        kinds["sleep"] += bool(LINE_SLEEP.search(ln))
        kinds["retry"] += bool(LINE_RETRY.search(ln))
        for v in LINE_TIMEOUT.findall(ln):
            timeouts[float(v)] += 1
    return kinds, timeouts


def symptoms(path: str, before: str | None, after: str | None) -> list[str]:
    """The symptom kinds the change adds to one file (a timeout counts when a value it adds is above one it
    removes)."""
    if path.endswith(".py"):
        (k0, t0), (k1, t1) = py_symptoms(before), py_symptoms(after)
    elif Path(path).suffix in SCRIPT_EXTS or path.startswith(".github/workflows/"):
        (k0, t0), (k1, t1) = line_symptoms(before), line_symptoms(after)
    else:
        return []
    out = [k for k in WHAT if k != "timeout" and k1[k] > k0[k]]
    added, removed = t1 - t0, t0 - t1
    if added and removed and max(added) > min(removed):
        out.append("timeout")
    return out


def shortcut_gaps(path: str, before: str | None, after: str | None) -> list[str]:
    """For each shortcut: marker the change adds, what it lacks (ceiling, trigger, debt item); [] when complete."""
    old = Counter(b for b in comment_blocks(before, path) if SHORTCUT.search(b))
    out = []
    for block, n in (Counter(b for b in comment_blocks(after, path) if SHORTCUT.search(b)) - old).items():
        miss = [w for w, rx in (("a ceiling", CEILING), ("a trigger", TRIGGER), ("a debt item", ITEM))
                if not rx.search(block)]
        out += [", ".join(miss)] * n if miss else []
    return out


# --- dependencies ---

def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_name(spec: str) -> str:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return _norm(m.group(1)) if m else ""


def _package_json(text: str) -> set[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return set()
    sections = [data.get(sec) for sec in NPM_SECTIONS] if isinstance(data, dict) else []
    return {k.lower() for sec in sections if isinstance(sec, dict) for k in sec}


def _requirements(text: str) -> set[str]:
    return {_req_name(ln) for ln in text.splitlines() if ln.strip() and ln.lstrip()[0] not in "#-"} - {""}


def _poetry(data: dict) -> set[str]:
    poetry = (data.get("tool") or {}).get("poetry") or {}
    tables = [poetry.get("dependencies") or {}]
    tables += [(g or {}).get("dependencies") or {} for g in (poetry.get("group") or {}).values()]
    return {_norm(k) for t in tables for k in t if k != "python"}


def _pyproject(text: str) -> set[str]:
    """[project] dependencies and optional-dependencies, [dependency-groups], Poetry's dependencies and groups."""
    try:
        import tomllib
    except ImportError:   # Python 3.10
        import tomli as tomllib
    try:
        data = tomllib.loads(text)
    except ValueError:
        return set()
    proj = data.get("project") or {}
    groups = [proj.get("dependencies") or [], *(proj.get("optional-dependencies") or {}).values(),
              *(data.get("dependency-groups") or {}).values()]
    return _poetry(data) | ({_req_name(s) for g in groups for s in g if isinstance(s, str)} - {""})


def dependencies(path: str, text: str | None) -> set[str]:
    """The dependency names a manifest declares (normalized), or set() when it is not one or does not parse."""
    name = Path(path).name
    read = (_pyproject if name == "pyproject.toml" else _package_json if name == "package.json"
            else _requirements if REQUIREMENTS.fullmatch(name) else None)
    return read(text) if read and text else set()


def _named(name: str, texts: list[str]) -> bool:
    rx = re.compile(r"(?<![\w-])" + re.escape(_norm(name)) + r"(?![\w-])")
    return any(rx.search(_norm(t)) for t in texts)


# --- the signals of one change ---

def body_of(top: Path, base_rev: str, new_rev: str, pr_body: str = "") -> str:
    """The PR body (as given) and the messages of the range's commits: where Root cause: and Justified: lines are
    read."""
    log = git(top, "log", "--format=%B", f"{base_rev}..{new_rev or 'HEAD'}")
    return f"{pr_body}\n{log}"


def _finding(repo: str, check: str, unit: str, why: str, fix: str, tag: str) -> dict:
    return {"key": f"{repo}:{check}:{unit}", "check": check, "severity": SEVERITY[check], "unit": unit,
            "class": "", "chain": "", "via": "", "why": why, "fix": fix, "tag": tag}


def _size(repo: str, path: str, before: str | None, after: str, top: int) -> list[dict]:
    n0, n1 = _lines(before), _lines(after)
    if n1 > top >= n0:
        return [_finding(repo, "size.cross", path, f"{n0} -> {n1} lines: past {top}",
                         "split it in this PR, or a 'Justified: <path>: <reason>' line", "NEW")]
    if n0 > top and n1 > n0:
        return [_finding(repo, "size.grow", path, f"{n0} -> {n1} lines, already past {top}",
                         "its split, in the debt item", "DEFER")]
    return []


def _moved(rows: list[tuple[str, str, str]], base: inventory.Tree, new: inventory.Tree) -> dict[str, int]:
    """{function: complexity} of the functions the change takes out of their base file: moved elsewhere, a function
    keeps the complexity it had."""
    out: dict[str, int] = {}
    for _, old, path in rows:
        was = old or path
        if was.endswith(".py") and base.has(was):
            now = set(complexities(new.text(path))) if path else set()
            for q, n in complexities(base.text(was)).items():
                if q not in now:
                    out[q] = max(out.get(q, 0), n)
    return out


def _complexity_of(repo: str, path: str, before: str | None, after: str, top: int, moved: dict) -> list[dict]:
    mine, out = complexities(before), []
    for q, n1 in complexities(after).items():
        n0, unit = mine.get(q, moved.get(q)), f"{path}::{q}"
        if n1 > top and (n0 is None or n0 <= top):
            out.append(_finding(repo, "complexity.cross", unit, f"cyclomatic complexity "
                                f"{'new' if n0 is None else n0} -> {n1}: past {top}",
                                "fewer branches (a table, an early return, a helper), or a 'Justified:' line", "NEW"))
        elif n0 is not None and n0 > top and n1 > n0:
            out.append(_finding(repo, "complexity.grow", unit, f"cyclomatic complexity {n0} -> {n1}, already past "
                                f"{top}", "its simplification, in the debt item", "DEFER"))
    return out


def _file(repo: str, old: str, path: str, before: str | None, after: str, ctx: dict) -> list[dict]:
    """The structure findings of one changed file."""
    ext, out = Path(path).suffix, []
    if ext in CODE_EXTS:
        out += _size(repo, path, before, after, ctx["max_lines"])
    if ext == ".py":
        out += _complexity_of(repo, path, before, after, ctx["complexity"], ctx["moved"])
    for name in sorted(dependencies(path, after) - dependencies(old, before)):
        if not _named(name, ctx["decisions"]):
            out.append(_finding(repo, "dep.adr", name, f"a new dependency in {path} that no decision log names",
                                "an ADR line that says why it is worth depending on (or a 'Justified:' line)", "NEW"))
    for gap in shortcut_gaps(path, before, after):
        out.append(_finding(repo, "shortcut.marker", path, f"a shortcut: marker without {gap}",
                            "say its ceiling: (when it stops being enough), its trigger: (what makes it be redone) "
                            "and its debt item (wi-...)", "NEW"))
    kinds = symptoms(path, before, after)
    if kinds:
        out.append(_finding(repo, "symptom.cause", path, f"{', '.join(WHAT[k] for k in kinds)} added",
                            "a 'Root cause:' line in the PR body (what failed and why), the cause fixed, or a "
                            "'Justified: <path>: <reason>' line when it is by design",
                            "justified" if ctx["root_cause"] else "NEW"))
    return out


def signals(repo: str, rows: list[tuple[str, str, str]], base: inventory.Tree, new: inventory.Tree, limits: dict,
            body: str, decision_texts: list[str]) -> list[dict]:
    """The structure findings of a change: ``rows`` the scout's (status, old path, new path), ``limits`` from
    :func:`thresholds`, ``body`` the PR body and commit messages, ``decision_texts`` the project's decision logs (a
    decision log the change itself edits counts too)."""
    pairs = [(old or path, path) for _, old, path in rows if path and new.text(path) is not None]
    edited = [new.text(p) or "" for _, p in pairs if DECISION_FILE.search(p)]
    ctx = {**limits, "moved": _moved(rows, base, new), "decisions": decision_texts + edited,
           "root_cause": bool(ROOT_CAUSE.search(body))}
    out = [f for old, path in pairs
           for f in _file(repo, old, path, base.text(old) if base.has(old) else None, new.text(path), ctx)]
    justified = {m.group(1).strip() for m in JUSTIFIED.finditer(body)}
    for f in out:
        if f["tag"] == "NEW" and {f["unit"], f["unit"].split("::", 1)[0]} & justified:
            f["tag"] = "justified"
    return out
