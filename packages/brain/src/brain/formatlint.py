"""Format lints (wi-brain-format-lint; spec-brain-data-compat 6): three rules that keep the brain's home and its files
behind their one door, read by two backends the owner switches on or off, so the difference shows.

format.home-path      a path into the brain's home built by hand outside brain.paths: ``Path.home() / ".brain"``,
                      ``os.path.expanduser("~/.brain...")``, ``Path("~/.brain...").expanduser()``
format.direct-write   a file of the brain's home written around brain.stateio: a ``write_text()``, ``write_bytes()``,
                      ``open(..., "w"/"a"/"x")`` or ``.open("w")`` on a path built from ``brain_home()`` (directly,
                      or through a local name assigned from it in the same function), in a module other than
                      brain.stateio
format.real-home-test a test that reads the real home: ``Path.home()``, ``os.path.expanduser("~...")`` or
                      ``Path("~...").expanduser()`` in a test module (conftest.py pins the home: it is not one)

Which files a rule reads is decided here, for both backends: home-path and direct-write read the production modules
(not the tests; not brain/paths.py, resp. brain/stateio.py, the doors themselves), real-home-test the test modules.

**The backends**, each off by default (config.json ``audit.format_lints_python`` and ``audit.format_lints_ast_grep``,
optional keys):

- ``python``: the rules read in the AST of each file, as brain.norms reads its norms; nothing to install;
- ``ast-grep``: the same rules as ast-grep YAML (``brain/lints/*.yml``), run by the ``ast-grep`` binary at its
  pinned version (:data:`AST_GREP_PIN`); without the binary, or at another version, the backend is N/A and says why.
  The binary is the owner's install (the package README, « Format lints »): the engine never downloads it.

``brain audit --diff`` (the scout) reads the switched-on backends over the Python files a change touches: an occurrence
the change adds is an info line (shown, never blocking: nothing that passed is newly refused), those already in a
touched file one DEFER line per file and rule. ``brain lint formats [--compare]`` runs them over a repo, the
comparison printing what each backend finds that the other does not, and how long each took.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import config, inventory, norms, structure

BACKENDS = ("python", "ast-grep")
KEYS = {"python": "format_lints_python", "ast-grep": "format_lints_ast_grep"}   # config.json audit.<key>
AST_GREP_PIN = "0.51.0"
AST_GREP_TIMEOUT = 300
RULES_DIR = Path(__file__).with_name("lints")
SEVERITY = {"format.home-path": "P2", "format.direct-write": "P2", "format.real-home-test": "P2"}
FIX = {"format.home-path": "build it with brain.paths (brain_home() and its helpers), never by hand",
       "format.direct-write": "write it through brain.stateio (save, write_atomic, write_foreign), never a bare "
                              "write",
       "format.real-home-test": "read the test's temporary BRAIN_HOME or tmp_path, never the real home"}
RULE_FILES = {"format.home-path": "home-path.yml", "format.direct-write": "direct-write.yml",
              "format.real-home-test": "real-home-test.yml"}
_BRAIN_HOME_STR = re.compile(r"^~[/\\]+\.brain(?:[/\\]|$)")
_HOME_STR = re.compile(r"^~(?:[/\\]|$)")
_WRITE_MODE = re.compile(r"[wax+]")


@dataclass(frozen=True)
class Hit:
    check: str
    path: str
    line: int
    sig: str      # what tells it from another occurrence in the file: its source text, folded
    scope: str = ""


def enabled(root) -> list[str]:
    """The backends the owner switched on (config.json ``audit.format_lints_python`` / ``_ast_grep``: true)."""
    opts = config.load(root).data.get("audit")
    opts = opts if isinstance(opts, dict) else {}
    return [b for b in BACKENDS if opts.get(KEYS[b]) is True]


def checks_for(path: str) -> list[str]:
    """The rules that read the file ``path`` (POSIX, relative to its repo): none for a file that is not Python."""
    if not path.endswith(".py"):
        return []
    if inventory.is_test(path):
        return ["format.real-home-test"]
    if path.rsplit("/", 1)[-1] == "conftest.py" or inventory.in_tests(path):
        return []
    base = path.rsplit("/", 1)[-1]
    return [c for c, door in (("format.home-path", "paths.py"), ("format.direct-write", "stateio.py"))
            if base != door]


def _sig(text: str) -> str:
    return " ".join(text.split())[:160]


# --- the python backend ---

def _str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _home_call(n: ast.AST, m: norms.Module) -> bool:
    """``Path.home()`` (pathlib's, however imported)."""
    return (isinstance(n, ast.Call) and not n.args and isinstance(n.func, ast.Attribute) and n.func.attr == "home"
            and norms.dotted(n.func.value, m.names) in ("pathlib.Path", "Path"))


def _expanded(n: ast.AST, m: norms.Module, rx: re.Pattern) -> bool:
    """``os.path.expanduser(S)`` or ``Path(S).expanduser()`` with a literal S that ``rx`` matches."""
    if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "expanduser"):
        return False
    if norms.dotted(n.func, m.names) == "os.path.expanduser":
        return bool(n.args) and bool(rx.match(_str(n.args[0]) or ""))
    inner = n.func.value
    return (isinstance(inner, ast.Call) and norms.dotted(inner.func, m.names) in ("pathlib.Path", "Path")
            and bool(inner.args) and bool(rx.match(_str(inner.args[0]) or "")))


def _home_path(n: ast.AST, m: norms.Module) -> bool:
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) and _home_call(n.left, m):
        return (_str(n.right) or "").replace("\\", "/").split("/", 1)[0] == ".brain"
    return _expanded(n, m, _BRAIN_HOME_STR)


def _from_home(e: ast.AST | None, m: norms.Module, q: str, seen: set[str] | None = None) -> bool:
    """Whether the expression ``e`` builds on ``brain_home()``: it calls it, or names a local of scope ``q`` assigned
    from such an expression."""
    if e is None:
        return False
    seen = set() if seen is None else seen
    for n in ast.walk(e):
        if isinstance(n, ast.Call) and (norms.dotted(n.func, m.names).rsplit(".", 1)[-1] == "brain_home"):
            return True
        if isinstance(n, ast.Name) and n.id not in seen:
            seen.add(n.id)
            if any(_from_home(v, m, q, seen) for v in m.assigned.get((q, n.id), [])):
                return True
    return False


def _mode(n: ast.Call, pos: int) -> str:
    """An open() call's literal mode: its argument at ``pos``, else its mode= ('' when not a literal)."""
    kw = norms._kw(n, "mode")
    return (_str(n.args[pos]) if len(n.args) > pos else _str(kw.value if kw else None)) or ""


def _write_target(n: ast.Call) -> ast.AST | None:
    """The path a call writes: ``p.write_text()``, ``p.write_bytes()``, ``p.open("w")``, ``open(p, "w")``; None
    for any other call (a read included)."""
    f = n.func
    if isinstance(f, ast.Attribute) and f.attr in ("write_text", "write_bytes"):
        return f.value
    if isinstance(f, ast.Attribute) and f.attr == "open":
        return f.value if _WRITE_MODE.search(_mode(n, 0)) else None
    if isinstance(f, ast.Name) and f.id == "open" and n.args:
        return n.args[0] if _WRITE_MODE.search(_mode(n, 1)) else None
    return None


def _direct_write(n: ast.AST, m: norms.Module, q: str) -> bool:
    return isinstance(n, ast.Call) and _from_home(_write_target(n), m, q)


def _real_home(n: ast.AST, m: norms.Module) -> bool:
    return _home_call(n, m) or _expanded(n, m, _HOME_STR)


def python_hits(path: str, text: str | None, checks: list[str] | None = None) -> list[Hit]:
    """The python backend's occurrences in one file ([] when it does not parse)."""
    checks = checks_for(path) if checks is None else checks
    tree = structure._parse(text) if checks else None
    if tree is None:
        return []
    m, out = norms.Module(tree), []
    for n, q in m.scope.items():
        found = []
        if "format.home-path" in checks and _home_path(n, m):
            found.append("format.home-path")
        if "format.direct-write" in checks and _direct_write(n, m, q):
            found.append("format.direct-write")
        if "format.real-home-test" in checks and _real_home(n, m):
            found.append("format.real-home-test")
        out += [Hit(c, path, n.lineno, _sig(ast.unparse(n)), q) for c in found]
    return sorted(set(out), key=lambda h: (h.line, h.check, h.sig))


# --- the ast-grep backend ---

def ast_grep() -> tuple[str, str]:
    """(the binary, '') when ``ast-grep`` at :data:`AST_GREP_PIN` is on the PATH, else ('', why not)."""
    exe = shutil.which("ast-grep")
    if not exe:
        return "", (f"ast-grep is not on the PATH (the owner's install, ast-grep-cli {AST_GREP_PIN}: README, "
                    "Format lints)")
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=30, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"ast-grep --version failed ({type(exc).__name__})"
    found = (re.search(r"\d+\.\d+\.\d+", out or "") or [""])[0]
    if found != AST_GREP_PIN:
        return "", f"ast-grep {found or '?'} found, the rules are pinned to {AST_GREP_PIN}"
    return exe, ""


def grep_hits(files: dict[str, Path], exe: str) -> tuple[list[Hit], str]:
    """The ast-grep backend's occurrences in ``files`` ({repo path: the file on disk}): one scan per rule over the
    files it reads; (hits, '') or ([], why it failed)."""
    by_rule: dict[str, list[str]] = {}
    for path in files:
        for c in checks_for(path):
            by_rule.setdefault(c, []).append(path)
    back = {str(Path(f).resolve()).replace("\\", "/").lower(): p for p, f in files.items()}
    out: list[Hit] = []
    for check, paths in sorted(by_rule.items()):
        argv = [exe, "scan", "--rule", str(RULES_DIR / RULE_FILES[check]), "--json=compact",
                *(str(files[p]) for p in paths)]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=AST_GREP_TIMEOUT, stdin=subprocess.DEVNULL)
            rows = json.loads(proc.stdout or "[]")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return [], f"ast-grep scan {RULE_FILES[check]} failed ({type(exc).__name__})"
        if not isinstance(rows, list):
            return [], f"ast-grep scan {RULE_FILES[check]}: not a JSON list"
        for r in rows if isinstance(rows, list) else []:
            key = str(Path(str(r.get("file", ""))).resolve()).replace("\\", "/").lower()
            path = back.get(key)
            start = ((r.get("range") or {}).get("start") or {}).get("line")
            if path is not None and isinstance(start, int):
                out.append(Hit(check, path, start + 1, _sig(str(r.get("text", "")))))
    return sorted(set(out), key=lambda h: (h.path, h.line, h.check)), ""


# --- a set of texts, by backend ---

def hits(texts: dict[str, str], backend: str) -> tuple[list[Hit], str]:
    """The occurrences of ``backend`` in ``texts`` ({repo path: Python text}); (hits, '') or ([], why N/A)."""
    texts = {p: t for p, t in texts.items() if checks_for(p) and t is not None}
    if backend == "python":
        return [h for p, t in sorted(texts.items()) for h in python_hits(p, t)], ""
    exe, why = ast_grep()
    if not exe:
        return [], why
    with tempfile.TemporaryDirectory(prefix="brain-format-lint-") as d:
        files = {}
        for p, t in texts.items():
            f = Path(d) / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(t, encoding="utf-8")
            files[p] = f
        return grep_hits(files, exe)


# --- the scout's lines ---

def _finding(key: str, check: str, unit: str, why: str, tag: str) -> dict:
    return {"key": key, "check": check, "severity": SEVERITY[check], "unit": unit,
            "class": "", "chain": "", "via": "", "why": why, "fix": FIX[check], "tag": tag}


def signals(repo: str, rows: list[tuple[str, str, str]], base: inventory.Tree, new: inventory.Tree,
            backends: list[str]) -> tuple[list[dict], dict[str, str]]:
    """The format lint lines of a change for the switched-on ``backends`` (info for what it adds, DEFER for what a
    touched file had), and {backend: why N/A}."""
    if not backends:
        return [], {}
    before, after = _texts(rows, base, new)
    out, na = [], {}
    for b in backends:
        now, why = hits(after, b)
        was, why_was = hits(before, b) if not why else ([], "")
        if why or why_was:
            na[f"format lints ({b})"] = why or why_was
        else:
            out += _lines(repo, b, now, was)
    return _one_per_occurrence(out), na


def _texts(rows: list[tuple[str, str, str]], base: inventory.Tree, new: inventory.Tree) -> tuple[dict, dict]:
    """(the base's texts, the change's) of the files a rule reads, each by its new path (a moved file: its old
    text)."""
    after = {p: new.text(p) for _, _, p in rows if p and checks_for(p) and new.text(p) is not None}
    return {p: base.text(old or p) for _, old, p in rows if p in after and base.has(old or p)}, after


def _lines(repo: str, b: str, now: list[Hit], was: list[Hit]) -> list[dict]:
    """One backend's lines: an info line per occurrence ``now`` adds to ``was``, one DEFER line per file and rule for
    those it had."""
    seen = Counter((h.check, h.path, h.sig) for h in was)
    out, old = [], {}
    for h in now:
        k = (h.check, h.path, h.sig)
        if seen[k] > 0:
            seen[k] -= 1
            old.setdefault((h.path, h.check), []).append(h.line)
            continue
        unit = f"{h.path}::{h.scope}" if h.scope else h.path
        out.append(_finding(f"{repo}:{h.check}:{h.path}:{h.line}:{b}", h.check, unit, f"line {h.line} ({b}): {h.sig}",
                            "info"))
    for (path, check), lines in sorted(old.items()):
        shown = ", ".join(map(str, lines[:8])) + (", ..." if len(lines) > 8 else "")
        out.append(_finding(f"{repo}:{check}:{path}:{b}", check, path, f"{len(lines)} already in the file ({b}; "
                            f"line {shown}): {FIX[check]}, by batches", "DEFER"))
    return out


def _one_per_occurrence(rows: list[dict]) -> list[dict]:
    """Both backends on: an occurrence both found (or a file's deferred rule) is said once, by the first backend."""
    out, seen = [], set()
    for r in rows:
        k = (r["tag"], r["key"].rsplit(":", 1)[0])   # the key without its backend
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# --- brain lint formats: a repo, one backend or both compared ---

def repo_texts(top: Path) -> dict[str, Path]:
    """The Python files of the repo at ``top`` that a rule reads, as git lists them (tracked and untracked, ignored
    files left out): {repo path: the file}."""
    out = inventory.git(top, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return {p: top / p for p in sorted(set(out.split("\0"))) if p and checks_for(p) and (top / p).is_file()}


def run(top: Path, backends: list[str]) -> dict[str, dict]:
    """{backend: {hits, seconds, why}} over the repo at ``top``."""
    files = repo_texts(top)
    report: dict[str, dict] = {}
    for b in backends:
        t0 = time.perf_counter()
        if b == "python":
            found = [h for p, f in files.items() for h in python_hits(p, f.read_text(encoding="utf-8",
                                                                                     errors="replace"))]
            why = ""
        else:
            exe, why = ast_grep()
            found, why = grep_hits(files, exe) if exe else ([], why)
        report[b] = {"hits": found, "seconds": round(time.perf_counter() - t0, 3), "why": why}
    return report


def compare(report: dict[str, dict]) -> dict[str, list[Hit]]:
    """{only <backend>: the occurrences that backend found and the other did not} (by rule, file and line)."""
    if len(report) < 2 or any(r["why"] for r in report.values()):
        return {}
    keys = {b: {(h.check, h.path, h.line) for h in r["hits"]} for b, r in report.items()}
    a, b = list(report)
    return {f"only {a}": [h for h in report[a]["hits"] if (h.check, h.path, h.line) not in keys[b]],
            f"only {b}": [h for h in report[b]["hits"] if (h.check, h.path, h.line) not in keys[a]]}


def render(report: dict[str, dict], diff: dict[str, list[Hit]], limit: int = 20) -> list[str]:
    out = []
    for b, r in report.items():
        if r["why"]:
            out.append(f"{b}: N/A: {r['why']}")
            continue
        by = Counter(h.check for h in r["hits"])
        out.append(f"{b}: {len(r['hits'])} occurrence(s) in {r['seconds']:.2f} s"
                   + "".join(f"; {c} {by[c]}" for c in SEVERITY if by[c]))
    for label, rows in diff.items():
        out.append(f"{label} ({len(rows)}):")
        out += [f"  {h.path}:{h.line} {h.check}: {h.sig}" for h in rows[:limit]]
        out += [f"  ... {len(rows) - limit} more"] if len(rows) > limit else []
    if len(report) == 1:
        only = next(iter(report.values()))
        out += [f"  {h.path}:{h.line} {h.check}: {h.sig}" for h in only["hits"][:limit]]
        out += [f"  ... {len(only['hits']) - limit} more (--json: all)"] if len(only["hits"]) > limit else []
    return out
