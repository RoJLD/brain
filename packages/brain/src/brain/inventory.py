"""Facts about a project's repos, for ``brain audit`` and its scout, and nothing else (no severity, no output): the
files of a repo at a commit (git plumbing, no checkout) or in its working tree, the Python package layout, the units
(modules, scripts, commands), the docs set, the test evidence of each unit, the static production closure from the
declared entries, and the CodeRefs of the code stores. Zero token: AST, YAML and git only; a repo's code is never
imported or run.

A git failure raises AuditError (exit code 2): it never reads as an empty tree, which would look like 'no tests' and
create false debt. Side effects are module functions the tests can replace, as in brain.stacks: ``_run_git`` (every
git call, ``GIT_OPTIONAL_LOCKS=0``, no prompt) and ``_read_bytes`` (a working-tree file). Blobs and their parsed facts
are cached by blob id, so the weekly trend re-reads only what changed.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import posixpath
import re
import subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import graph

try:  # Python 3.11+; on 3.10 the tomli backport (a dependency there); without both, a pyproject.toml is not measured
    import tomllib
except ImportError:  # pragma: no cover - depends on the interpreter
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "LC_ALL": "C"}
SKIP_DIRS = {"upstream", "patches", "node_modules", "experiments", "__pycache__", ".venv", "venv", "site-packages"}
TEST_DIRS = {"tests", "test"}
SCRIPT_EXT = (".ps1", ".psm1", ".sh", ".bat", ".cmd")
TEXT_EXT = (".py", ".md", ".toml", ".json", ".psd1") + SCRIPT_EXT
IDENT = re.compile(r"[A-Za-z_]\w*")
DOTTED = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
DOTTED_FULL = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
FILE_REF = re.compile(r"(?<![\w.-])((?:[\w.-]+[/\\])*[\w.-]*[\w-]\.(?:py|ps1|psm1|psd1|sh|bat|cmd))(?![\w-])")
DASH_M = re.compile(r"(?<![\w-])-m\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
WORD = re.compile(r"[\w-]+")
STRING = re.compile(r"""(['"])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|[A-Za-z0-9][\w-]*)\1""")
IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^\n]*)"
                    r"|import[ \t]+([^\n]*))", re.M)
DASH_M_ARG = re.compile(r"(?<![\w-])-m\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?:[ \t]+([A-Za-z][\w-]*)(?=[\s'\"`;|&)]|$))?",
                        re.M)
SUBPARSER = re.compile(r"""\badd_parser\(\s*["']([\w-]+)["']""")
FIXTURE = re.compile(r"""([=(,\[]\s*)[rRbBuUfF]{0,2}("{3}|'{3}).*?\2""", re.S)
RUN = re.compile(r"""subprocess\.|\bPopen\(|\bcheck_output\(|\bcheck_call\(|\bos\.system\(|\brunpy\b|\brun_path\(|"""
                 r"""\brun_module\(|["'](?:powershell|pwsh|bash|sh|cmd)(?:\.exe)?["']\s*[,\]]|["']-File["']""")
ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?::[^=\n]*)?=(?!=)")
DEF = re.compile(r"^(\s*)(?:async\s+)?def\s+([A-Za-z_]\w*)")
USED = re.compile(r"(?<![.\w])([A-Za-z_]\w*)(?!\w)(?!\s*\()(?!\s*=[^=])")
TRIPLE = re.compile(r"""("{3}|'{3}).*?\1""", re.S)
STR = re.compile(r"""(["'])(?:\\.|(?!\1).)*\1""")
MAKE_TARGET = re.compile(r"^([\w.-]+(?:[ \t]+[\w.-]+)*)[ \t]*:(?![=:])")
MAKE_CALL = re.compile(r"(?<![\w-])make[ \t]+(?:-\S+[ \t]+)*([\w-]+(?:\.[\w-]+)*)")


class AuditError(Exception):
    """git failed, or the registry is wrong (exit code 2)."""


# --- side effects (replaced in the tests) ---

def _run_git(repo: Path, args: list[str], data: bytes | None = None,
             timeout: float = 300) -> tuple[int, bytes, bytes]:
    kw = {"input": data} if data is not None else {"stdin": subprocess.DEVNULL}
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout,
                           env=dict(os.environ, **GIT_ENV), **kw)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuditError(f"git {' '.join(args[:3])} in {repo}: {exc}") from exc
    return p.returncode, p.stdout, p.stderr


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def git(repo: Path, *args: str, allow: tuple = (0,)) -> str:
    """stdout of a git command in ``repo``; an exit code outside ``allow`` raises AuditError ('' for an allowed one
    other than 0)."""
    code, out, err = _run_git(repo, list(args))
    if code not in allow:
        raise AuditError(f"git {' '.join(args[:4])} in {repo} failed: "
                         f"{err.decode('utf-8', 'replace').strip()[-300:] or f'exit {code}'}")
    return out.decode("utf-8", "replace") if code == 0 else ""


_BLOBS: dict[str, bytes] = {}


def _cat(repo: Path, names) -> dict[str, tuple[str, bytes]]:
    """Read objects with one ``git cat-file --batch``: name -> (object id, content); blobs are cached by id."""
    want = [s for s in dict.fromkeys(names) if s and s not in _BLOBS]
    if not want:
        return {}
    code, out, err = _run_git(repo, ["cat-file", "--batch"], ("\n".join(want) + "\n").encode())
    if code:
        raise AuditError(f"git cat-file --batch in {repo} failed: {err.decode('utf-8', 'replace').strip()[-300:]}")
    got, pos = {}, 0
    for name in want:
        end = out.index(b"\n", pos)
        head = out[pos:end].split()
        if len(head) != 3:
            raise AuditError(f"git cat-file in {repo}: {name}: {out[pos:end].decode('utf-8', 'replace')}")
        sha, size = head[0].decode(), int(head[2])
        body = out[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
        if head[1] == b"blob":
            _BLOBS[sha] = body
        got[name] = (sha, body)
    return got


def _blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _commit_date(body: bytes) -> str:
    """The committer date of a commit object, in the committer's time zone (git's %cs)."""
    for line in body.split(b"\n"):
        if line.startswith(b"committer "):
            ts, tz = line.rsplit(b" ", 2)[-2:]
            off = (1 if tz[:1] == b"+" else -1) * (int(tz[1:3]) * 60 + int(tz[3:5]))
            return (datetime.fromtimestamp(int(ts), timezone.utc) + timedelta(minutes=off)).date().isoformat()
        if not line:
            break
    return ""


# --- trees ---

class Tree:
    """A repo's files at one point: ``files`` maps each POSIX path to its blob id ('' until a working-tree file is
    read). ``rev`` and ``date`` are the commit read ('' for a working tree)."""

    def __init__(self, repo: Path, files: dict[str, str], rev: str = "", date: str = "", branch: str = "",
                 work: bool = False):
        self.repo, self.files, self.rev, self.date, self.branch, self.work = repo, files, rev, date, branch, work
        self._by_base: dict[str, list[str]] | None = None

    @property
    def label(self) -> str:
        return f"{self.branch or 'HEAD'}@{self.rev[:7]}" if self.rev else f"{self.branch or 'HEAD'}+worktree"

    def has(self, path: str) -> bool:
        return path in self.files

    def by_base(self, name: str) -> list[str]:
        if self._by_base is None:
            self._by_base = {}
            for p in self.files:
                self._by_base.setdefault(p.rsplit("/", 1)[-1].lower(), []).append(p)
        return self._by_base.get(name.lower(), [])

    def prefetch(self, paths) -> None:
        if not self.work:
            _cat(self.repo, [self.files[p] for p in paths if p in self.files])

    def key(self, path: str) -> str:
        if self.work and path in self.files and not self.files[path]:
            self.text(path)
        return self.files.get(path, "")

    def text(self, path: str) -> str | None:
        if path not in self.files:
            return None
        sha = self.files[path]
        if self.work and not sha:
            try:
                data = _read_bytes(self.repo / path)
            except OSError:
                return None
            sha = self.files[path] = _blob_id(data)
            _BLOBS[sha] = data
        if sha not in _BLOBS:
            _cat(self.repo, [sha])
        return _BLOBS[sha].decode("utf-8", "replace").lstrip("\ufeff")


def wanted(path: str) -> bool:
    """The files an audit reads, fetched with the tree in one cat-file call."""
    base = path.rsplit("/", 1)[-1]
    return not skipped(path) and (path.endswith((".py", ".toml", ".psd1") + SCRIPT_EXT) or is_test(path)
                                  or is_doc(path) or base in ("package.json", "hooks.json", "schema.yaml")
                                  or (path.endswith(".yaml") and "/graph/nodes/" in path))


def git_tree(repo: Path, rev: str, branch: str = "") -> Tree:
    """The files of commit ``rev``: one ``git ls-tree`` and one ``git cat-file --batch`` (the commit and the files
    an audit reads that are not cached yet)."""
    files = {}
    for entry in git(repo, "ls-tree", "-r", "-z", "--full-tree", rev).split("\0"):
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob" and parts[0] != "120000":
            files[path] = parts[2]
    got = _cat(repo, [rev] + [sha for p, sha in files.items() if wanted(p)])
    sha, body = got.get(rev, ("", b""))
    return Tree(repo, files, sha, _commit_date(body), branch)


def work_tree(repo: Path) -> Tree:
    """The working tree: tracked and untracked (not ignored) files as they are on disk."""
    out = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    files = {p: "" for p in sorted(set(out.split("\0")) - {""}) if (repo / p).is_file()}
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    return Tree(repo, files, "", "", branch, work=True)


def default_branch(repo: Path) -> str:
    """The branch a full audit reads: origin/HEAD's name, else main, else master (a local branch)."""
    heads, origin = set(), ""
    for line in git(repo, "for-each-ref", "--format=%(refname) %(symref)", "refs/heads/",
                    "refs/remotes/origin/HEAD").splitlines():
        ref, _, sym = line.partition(" ")
        if ref.startswith("refs/heads/"):
            heads.add(ref[11:])
        elif sym.startswith("refs/remotes/origin/"):
            origin = sym[20:]
    for b in ([origin] if origin else []) + ["main", "master"]:
        if b in heads:
            return b
    raise AuditError(f"{repo}: no default branch (origin/HEAD, main or master)")


def reading_ref(repo: Path) -> tuple[str, str]:
    """(ref, branch) a full audit reads: the default branch's tip, or HEAD in a linked worktree (a branch's committed
    work, so a PR's view describes the PR)."""
    dot = repo / ".git"
    if not dot.exists():
        raise AuditError(f"{repo}: not a git checkout")
    if dot.is_file():  # a linked worktree
        return "HEAD", git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    b = default_branch(repo)
    return f"refs/heads/{b}", b


def week_commits(repo: Path, ref: str, ends: list[str]) -> list[str]:
    """For each ISO time of ``ends``, the last first-parent commit of ``ref`` before it ('' when none): one git log,
    as ``git rev-list -1 --first-parent --before`` would pick."""
    log = [ln.split() for ln in git(repo, "log", "--first-parent", "--format=%H %ct", ref).splitlines() if ln]
    out = []
    for end in ends:
        ts = datetime.fromisoformat(end.replace("Z", "+00:00")).timestamp()
        out.append(next((sha for sha, ct in log if int(ct) <= ts), ""))
    return out


# --- Python facts ---

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


_FACTS: dict[str, PyFacts] = {}
_TREES: dict[str, ast.Module | None] = {}


def _is_guard(stmt) -> bool:
    if not isinstance(stmt, ast.If) or not isinstance(stmt.test, ast.Compare) or len(stmt.test.comparators) != 1:
        return False
    sides = [stmt.test.left, stmt.test.comparators[0]]
    return ({type(s).__name__ for s in sides} == {"Name", "Constant"}
            and any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
            and any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides))


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
                      frozenset(SUBPARSER.findall(text)))
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


# --- layout and units ---

@dataclass
class Layout:
    roots: list[str] | None            # package roots ('' = the repo root); None when unreadable
    tops: list[str] | None = None      # top-level package patterns (fnmatch); None = any
    scripts: dict[str, str] = field(default_factory=dict)   # console script -> module:function
    why: str = ""


def _norm(p) -> str:
    p = posixpath.normpath(str(p).replace("\\", "/"))
    return "" if p in (".", "") else p.strip("/")


def layout(tree: Tree, roots: list[str] | None = None) -> Layout:
    """Package roots: ``roots`` when given, else [tool.setuptools] package-dir / packages, packages.find where, src/,
    the top-level packages."""
    scripts: dict[str, str] = {}
    tops, found = None, None
    if tree.has("pyproject.toml"):
        if tomllib is None:
            return Layout(None, why="pyproject.toml needs Python 3.11+ (tomllib)")
        try:
            data = tomllib.loads(tree.text("pyproject.toml") or "")
        except tomllib.TOMLDecodeError as exc:
            return Layout(None, why=f"pyproject.toml does not parse: {exc}")
        scripts = {str(k): str(v) for k, v in ((data.get("project") or {}).get("scripts") or {}).items()}
        st = (data.get("tool") or {}).get("setuptools") or {}
        pdir, pk = st.get("package-dir") or {}, st.get("packages")
        if isinstance(pdir, dict) and "" in pdir:
            found = [_norm(pdir[""])]
        if isinstance(pk, list):
            tops, found = sorted({str(p).split(".")[0] for p in pk}), found or [""]
        elif isinstance(pk, dict) and isinstance(pk.get("find"), dict):
            found = found or [_norm(w) for w in pk["find"].get("where") or ["."]]
            tops = [str(i).split(".")[0] for i in pk["find"].get("include") or []] or None
    if roots:   # given: they replace the discovered roots and their package filter
        found, tops = [_norm(r) for r in roots], None
    if not found:
        found = ["src"] if any(f.startswith("src/") and f.endswith(".py") for f in tree.files) else [""]
    return Layout(found, tops, scripts)


def skipped(path: str) -> bool:
    parts = path.split("/")
    return any(p in SKIP_DIRS for p in parts[:-1]) or parts[-1].startswith("_generated") or path.endswith(".ipynb")


def in_tests(path: str) -> bool:
    return any(p in TEST_DIRS for p in path.split("/")[:-1])


def is_test(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    if skipped(path) or base in ("conftest.py", "__init__.py"):
        return False
    if base.endswith(".py"):
        return base.startswith("test_") or base.endswith("_test.py")
    if base.endswith(".Tests.ps1") or re.search(r"\.(test|spec)\.(ts|tsx|js|mjs)$", base):
        return True
    return in_tests(path) and base.endswith((".ps1", ".sh", ".ts", ".tsx", ".js", ".mjs"))


def is_doc(path: str) -> bool:
    """The docs set: READMEs at any depth, docs/**, runbooks; not specs or plans (docs/specs, docs/*/plans...),
    changelogs or journals."""
    low = path.lower()
    base = low.rsplit("/", 1)[-1]
    dirs = low.split("/")[:-1]
    if not low.endswith(".md") or skipped(path) or (dirs[:1] == ["docs"] and {"specs", "plans"} & set(dirs)) \
            or base.startswith(("changelog", "journal")):
        return False
    return base == "readme.md" or low.startswith("docs/") or "runbook" in base


def module_index(tree: Tree, lay: Layout) -> tuple[dict[str, str], dict[str, str]]:
    """(module -> path, package -> path of its __init__.py or '') for the .py files under the package roots; a
    package is also a module (its __init__.py)."""
    mods: dict[str, str] = {}
    pkgs: dict[str, str] = {}
    for path in sorted(tree.files):
        if not path.endswith(".py") or skipped(path) or in_tests(path) or path.endswith("/conftest.py") \
                or is_test(path):
            continue
        for root in lay.roots or []:
            pre = root + "/" if root else ""
            if not path.startswith(pre):
                continue
            rel = path[len(pre):-3].split("/")
            if (root == "" and (len(rel) < 2 or not tree.has(f"{rel[0]}/__init__.py"))) \
                    or not all(IDENT.fullmatch(p) for p in rel) \
                    or (lay.tops and not any(fnmatch.fnmatchcase(rel[0], t) for t in lay.tops)):
                break
            name = ".".join(rel[:-1] if rel[-1] == "__init__" else rel)
            if rel[-1] == "__init__":
                pkgs[name] = path
            for i in range(1, len(rel)):
                pkgs.setdefault(".".join(rel[:i]), "")
            if name:
                mods[name] = path
            break
    return mods, pkgs


@dataclass
class Unit:
    repo: str
    path: str
    kind: str              # module, script or command
    name: str              # dotted module, script file name, or command name
    cls: str = "other"     # entry, prod or other (the production closure)
    chain: str = ""        # how the closure reached it


@dataclass
class RepoFacts:
    name: str
    tree: Tree
    lang: str
    layout: Layout
    modules: dict[str, str]
    packages: dict[str, str]
    units: list[Unit]
    exempt: list[str]
    waived: list[tuple[str, str]]
    tests: list[str]
    docs: list[str]
    console: dict[str, str]          # console script (or package.json bin) -> its module, or its file for a bin
    root_of: dict[str, str] = field(default_factory=dict)   # module path -> its package root
    evidence: "Evidence | None" = None
    reach: "Reach | None" = None     # the tests' import reach (unit_evidence sets both)
    no_entry: bool = False           # a production repo no declared entry reaches: every unit counted as prod
    bins: dict[str, str] = field(default_factory=dict)      # package.json bin -> that package.json


def collect(tree: Tree, name: str, lang: str = "py", roots: list[str] | None = None,
            waive: dict[str, str] | None = None) -> RepoFacts:
    """The units of one repo: modules (``__init__`` without a def or class left out, trivial modules exempt),
    scripts, commands; and its tests and docs."""
    lay = layout(tree, roots)
    mods, pkgs = module_index(tree, lay) if lay.roots is not None else ({}, {})
    tests = sorted(p for p in tree.files if is_test(p))
    docs = sorted(p for p in tree.files if is_doc(p))
    pjson = sorted(p for p in tree.files if p.endswith("package.json") and not skipped(p)
                   and p.rsplit("/", 1)[-1] == "package.json")
    tree.prefetch([p for p in tree.files if wanted(p)])

    def reason(path: str) -> str:
        return next((r for g, r in (waive or {}).items() if fnmatch.fnmatchcase(path, g)), "")

    units: list[Unit] = []
    exempt, waived = [], []
    root_of = {}
    for root in lay.roots or []:
        for p in mods.values():
            if p.startswith(root + "/" if root else "") and p not in root_of:
                root_of[p] = root
    for dotted, path in sorted(mods.items(), key=lambda kv: kv[1]):
        if lang == "ts":
            continue
        f = facts(tree, path)
        if path.endswith("/__init__.py") and not f.defs:
            continue
        if reason(path):
            waived.append((path, reason(path)))
        elif f.parsed and not f.defs and f.statements <= 10:
            exempt.append(path)
        else:
            units.append(Unit(name, path, "module", dotted))
    modpaths = set(mods.values())
    for path in sorted(tree.files):
        dirs = path.split("/")[:-1]
        if skipped(path) or in_tests(path) or is_test(path) or "docs" in dirs:
            continue
        if path.endswith(SCRIPT_EXT) or (path.endswith(".py") and path not in modpaths
                                          and any(d in ("scripts", "hooks") for d in dirs)):
            if reason(path):
                waived.append((path, reason(path)))
            else:
                units.append(Unit(name, path, "script", path.rsplit("/", 1)[-1]))
    console: dict[str, str] = {}
    for cname, target in sorted(lay.scripts.items()):
        mod = target.split(":")[0].strip()
        console[cname] = mod
        units.append(Unit(name, mods.get(mod, "pyproject.toml"), "command", cname))
    bin_of: dict[str, str] = {}
    for pj in pjson:
        try:
            data = json.loads(tree.text(pj) or "{}")
        except ValueError:
            continue
        bins = data.get("bin") or {}
        if isinstance(bins, str):
            bins = {str(data.get("name", "")).split("/")[-1]: bins}
        for cname, rel in sorted(bins.items()) if isinstance(bins, dict) else []:
            path = _norm(posixpath.join(posixpath.dirname(pj), str(rel)))
            console[str(cname)] = path
            bin_of[str(cname)] = pj
            units.append(Unit(name, path, "command", str(cname)))
    targets = set(console.values())
    if lang != "ts":
        delegated = set()   # python -m pkg runs __main__.py, which runs pkg.cli: one command, not two
        for dotted, path in mods.items():
            if path.endswith("/__main__.py") and "." in dotted:
                pkg = dotted.rsplit(".", 1)[0]
                for mod, level, names, _ in facts(tree, path).imports:
                    base = ".".join(pkg.split(".")[:len(pkg.split(".")) - level + 1]) if level else ""
                    full = ".".join(x for x in (base, mod) if x)
                    delegated.update(c for c in [f"{full}.{n}" for n in names] + [full]
                                     if c in mods and c.startswith(pkg + ".") and c != dotted)
        for dotted, path in sorted(mods.items(), key=lambda kv: kv[1]):
            if dotted in targets or reason(path):
                continue
            if path.endswith("/__main__.py"):
                pkg = dotted.rsplit(".", 1)[0] if "." in dotted else ""
                if pkg and pkg not in targets:
                    units.append(Unit(name, path, "command", pkg))
            elif facts(tree, path).main_guard and dotted not in delegated:
                units.append(Unit(name, path, "command", dotted))
    return RepoFacts(name, tree, lang, lay, mods, pkgs, units, exempt, waived, tests, docs, console, root_of,
                     bins=bin_of)


def make_targets(tree: Tree) -> dict[str, set]:
    """Makefile target -> the modules its recipe runs with -m (a doc that names `make <target>` documents them)."""
    out: dict[str, set] = {}
    for mk in ("Makefile", "makefile", "GNUmakefile"):
        cur: list[str] = []
        for line in (tree.text(mk) or "").splitlines():
            if line.startswith("\t"):
                for d in DASH_M.findall(line):
                    for t in cur:
                        out.setdefault(t, set()).add(d)
            elif line.strip() and not line.lstrip().startswith("#"):
                m = MAKE_TARGET.match(line)
                cur = m.group(1).split() if m else []
    return out


# --- test evidence ---

@dataclass
class Evidence:
    names: dict[str, set] = field(default_factory=dict)   # stem of test_<stem>.py / test_*_<stem>.py -> tests
    exact: dict[str, set] = field(default_factory=dict)   # stem of test_<stem>.py or Pester <stem>.Tests.ps1
    imports: dict[str, set] = field(default_factory=dict)
    from_names: dict[str, dict] = field(default_factory=dict)   # module -> name imported from it -> tests
    dotted: dict[str, set] = field(default_factory=dict)  # dotted names in the text (and their prefixes)
    files: dict[str, set] = field(default_factory=dict)   # file paths in the text (and their path suffixes)
    runs: dict[str, set] = field(default_factory=dict)    # the script paths a test runs (and their path suffixes)
    per_test: dict[str, tuple] = field(default_factory=dict)   # Python test -> (imports, dotted names, words)


def _add(d: dict, k: str, v: str) -> None:
    d.setdefault(k, set()).add(v)


def _suffixes(tok: str):
    segs = tok.replace("\\", "/").split("/")
    return ("/".join(segs[i:]) for i in range(len(segs)))


def text_tokens(text: str, dotted: dict, files: dict, src: str, tops: set | None = None) -> None:
    for tok in set(DOTTED.findall(text)):
        if tops is not None and tok.split(".", 1)[0] not in tops:
            continue
        parts = tok.split(".")
        for i in range(2, len(parts) + 1):
            _add(dotted, ".".join(parts[:i]), src)
    for tok in set(FILE_REF.findall(text)):
        for suf in _suffixes(tok):
            _add(files, suf, src)


def evidence(tree: Tree, tests: list[str], tops: set | None = None) -> Evidence:
    """What the tests name. A Python test's triple-quoted value strings (sample code, expected output) are left out
    of its imports and names; a script counts as run only where the test starts a process with it."""
    ev = Evidence()
    for t in tests:
        base = t.rsplit("/", 1)[-1]
        if base.startswith("test_") and base.endswith(".py"):
            parts = base[5:-3].split("_")
            _add(ev.exact, base[5:-3], t)
            for i in range(len(parts)):
                _add(ev.names, "_".join(parts[i:]), t)
        elif base.endswith(".Tests.ps1"):
            _add(ev.exact, base[:-10], t)
        raw = tree.text(t) or ""
        if not t.endswith(".py"):   # a Pester or shell test runs what it names
            text_tokens(raw, ev.dotted, ev.files, t, tops)
            for tok in set(FILE_REF.findall(raw)):
                for suf in _suffixes(tok):
                    _add(ev.runs, suf, t)
            continue
        text = without_fixtures(raw)
        imps = []
        for mod, level, names in text_imports(text):
            if level or not mod:
                continue
            imps.append((mod, names))
            _add(ev.imports, mod, t)
            for n in names:
                _add(ev.imports, f"{mod}.{n}", t)
                ev.from_names.setdefault(mod, {}).setdefault(n, set()).add(t)
        text_tokens(text, ev.dotted, ev.files, t, tops)
        for tok in set(run_mentions(raw)):
            for suf in _suffixes(tok):
                _add(ev.runs, suf, t)
        ev.per_test[t] = (imps, set(DOTTED.findall(text)), set(WORD.findall(raw.lower())))
    return ev


def stem(u: Unit) -> str:
    base = u.path.rsplit("/", 1)[-1][:-3]
    return u.name.split(".")[-1] if base == "__init__" else base


def reexports(rf: RepoFacts) -> dict[str, set]:
    """Module -> names its package's __init__ re-exports from it (one level)."""
    out: dict[str, set] = {}
    for pkg, init in rf.packages.items():
        if not init:
            continue
        for mod, level, names, _ in facts(rf.tree, init).imports:
            target = f"{pkg}.{mod}" if level == 1 and mod and "." not in mod else \
                mod if level == 0 and mod.startswith(pkg + ".") and mod.count(".") == pkg.count(".") + 1 else ""
            if target:
                out.setdefault(target, set()).update(names)
    return out


@dataclass
class Reach:
    """Which tests reach each module of a repo through imports (bit i stands for tests[i])."""
    tests: list[str]
    named: dict[str, set]   # test -> the module paths it imports or names (not their parent packages)
    near: dict[str, int]    # module path -> tests that import it or a module that imports it
    far: dict[str, int]     # module path -> tests whose import closure reaches it

    def of(self, mask: int) -> list[str]:
        return [t for i, t in enumerate(self.tests) if mask >> i & 1]


def tests_reach(rf: RepoFacts, ev: Evidence, idx: "Index") -> Reach:
    """The static import closure of each Python test inside its repo: every import (in functions too, a package's
    parents) and string constants equal to a module, as the production closure follows them."""
    name = rf.name
    tests = sorted(ev.per_test)
    named: dict[str, set] = {}
    direct: dict[str, int] = {}

    def hit(path: str, i: int) -> None:
        direct[path] = direct.get(path, 0) | 1 << i

    for i, t in enumerate(tests):
        imps, dotted, _ = ev.per_test[t]
        mine = named.setdefault(t, set())
        for mod, names in imps:
            explicit = [f"{mod}.{n}" for n in names if f"{mod}.{n}" in idx.modules]
            if not explicit:
                parts = mod.split(".")
                explicit = next(([".".join(parts[:k])] for k in range(len(parts), 0, -1)
                                 if ".".join(parts[:k]) in idx.modules), [])
            mine.update(idx.modules[d][1] for d in explicit if idx.modules[d][0] == name)
            for d in _resolve_import(mod, 0, names, "", idx):
                if idx.modules[d][0] == name:
                    hit(idx.modules[d][1], i)
        for tok in dotted:   # -m p.mod, run_module('p.mod')
            parts = tok.split(".")
            for k in range(len(parts), 1, -1):
                got = idx.modules.get(".".join(parts[:k]))
                if got and got[0] == name:
                    mine.add(got[1])
                    hit(got[1], i)
                    break
    succ = {p: {q for (r, q), _ in _py_edges((name, p), rf, idx, "*") if r == name and q != p}
            for p in rf.modules.values()}
    near = dict(direct)
    for p, outs in succ.items():
        if direct.get(p):
            for q in outs:
                near[q] = near.get(q, 0) | direct[p]
    far = dict(direct)
    work = deque(far)
    while work:
        p = work.popleft()
        for q in succ.get(p, ()):
            old = far.get(q, 0)
            if old | far[p] != old:
                far[q] = old | far[p]
                work.append(q)
    return Reach(tests, named, near, far)


def _confirmed(t: str, u: Unit, reach: Reach | None, strict: bool) -> bool:
    """A test named after a module tests it when it imports nothing of the repo (it runs it some other way; not for
    an ambiguous stem), or imports the module or a module of its package, or reaches it through its imports."""
    if reach is None:
        return not strict
    mine = reach.named.get(t, set())
    if not mine and not strict:
        return True
    folder = posixpath.dirname(u.path)
    if any(posixpath.dirname(p) == folder for p in mine):
        return True
    i = reach.tests.index(t) if t in reach.tests else -1
    return i >= 0 and bool(reach.far.get(u.path, 0) >> i & 1)


def module_evidence(u: Unit, rf: RepoFacts, ev: Evidence, stems: dict[str, int], rex: dict[str, set],
                    reach: Reach | None = None) -> tuple[str, list[str]]:
    """(via, tests) of a module, strongest first: 'name' (a unique test_<stem>.py or test_*_<stem>.py that does not
    test another package), 'import', 're-export' (one level, through the package __init__), 'invocation' (its dotted
    or file path in a test's text, fixtures left out), 'name (ambiguous stem)' (confirmed by the test's imports),
    'indirect' (a test imports a module that imports it, and names its stem), 'indirect (unnamed)' (only reached
    through what the tests import: P2 at most); ('', []) when no test."""
    s = stem(u)
    ambiguous = stems.get(s, 0) > 1
    named = [t for t in sorted(ev.names.get(s, ())) if _confirmed(t, u, reach, ambiguous)]
    if named and not ambiguous:
        return "name", named
    if ev.imports.get(u.name):
        return "import", sorted(ev.imports[u.name])
    pkg = u.name.rsplit(".", 1)[0] if "." in u.name else ""
    got = [t for n in rex.get(u.name, ()) for t in ev.from_names.get(pkg, {}).get(n, ())]
    if got:
        return "re-export", sorted(set(got))
    root = rf.root_of.get(u.path, "")
    hits = ev.dotted.get(u.name, set()) | ev.files.get(u.path, set()) \
        | (ev.files.get(u.path[len(root) + 1:], set()) if root else set())
    if hits:
        return "invocation", sorted(hits)
    if named:
        return "name (ambiguous stem)", named
    if reach is not None:
        near = [t for t in reach.of(reach.near.get(u.path, 0)) if s.lower() in ev.per_test[t][2]]
        if near:
            return "indirect", near
        far = reach.of(reach.far.get(u.path, 0))
        if far:
            return "indirect (unnamed)", far
    return "", []


def script_evidence(u: Unit, ev: Evidence) -> tuple[str, list[str]]:
    """('name', tests) for test_<stem>.py or Pester <stem>.Tests.ps1, ('runs', tests) for a test that runs it; else
    ('', the tests that only name it)."""
    base = u.name
    s = base.rsplit(".", 1)[0]
    if ev.exact.get(s):
        return "name", sorted(ev.exact[s])
    hits = ev.runs.get(base, set()) | ev.runs.get(u.path, set())
    if hits:
        return "runs", sorted(hits)
    return "", sorted(ev.files.get(base, set()) | ev.files.get(u.path, set()))


def unit_evidence(rf: RepoFacts, idx: "Index", tops: set | None) -> dict[str, tuple[str, list[str]]]:
    """Module path -> (via, tests) for every module unit of a repo (module_evidence, with the repo's stems,
    re-exports and import reach); sets ``rf.evidence`` and ``rf.reach``."""
    ev = rf.evidence = evidence(rf.tree, rf.tests, tops)
    reach = rf.reach = tests_reach(rf, ev, idx)
    mods = [u for u in rf.units if u.kind == "module"]
    stems: dict[str, int] = {}
    for u in mods:
        stems[stem(u)] = stems.get(stem(u), 0) + 1
    rex = reexports(rf)
    return {u.path: module_evidence(u, rf, ev, stems, rex, reach) for u in mods}


def shim_target(u: Unit, rf: RepoFacts, idx: "Index") -> tuple[str, str] | None:
    """A .py script of 20 lines or fewer that imports one project module takes that module's evidence: (repo, path)
    of that module."""
    if not u.path.endswith(".py"):
        return None
    f = facts(rf.tree, u.path)
    if f.lines > 20:
        return None
    hits = {_resolve_import(m, lv, n, "", idx)[0] for m, lv, n, _ in f.imports
            if not lv and _resolve_import(m, lv, n, "", idx)}
    return idx.modules[hits.pop()] if len(hits) == 1 else None


# --- the production closure ---

@dataclass
class Index:
    """Every repo of a project: the modules, packages, ``__main__`` modules and console scripts by name."""
    modules: dict[str, tuple[str, str]] = field(default_factory=dict)
    packages: dict[str, tuple[str, str]] = field(default_factory=dict)
    mains: dict[str, tuple[str, str]] = field(default_factory=dict)
    console: dict[str, tuple[str, str]] = field(default_factory=dict)
    dotted_of: dict[tuple[str, str], str] = field(default_factory=dict)

    @classmethod
    def build(cls, repos: dict[str, RepoFacts]) -> "Index":
        idx = cls()
        for name, rf in repos.items():
            for d, p in rf.modules.items():
                idx.modules.setdefault(d, (name, p))
                idx.dotted_of[(name, p)] = d
                if p.endswith("/__main__.py"):
                    idx.mains.setdefault(d.rsplit(".", 1)[0], (name, p))
            for d, p in rf.packages.items():
                idx.packages.setdefault(d, (name, p))
            for c, target in rf.console.items():
                path = rf.modules.get(target) or (target if rf.tree.has(target) else "")
                if path:
                    idx.console.setdefault(c, (name, path))
        return idx

    def top_packages(self) -> set[str]:
        if "_tops" not in self.__dict__:
            self._tops = {d.split(".")[0] for d in self.packages} | {d.split(".")[0] for d in self.modules}
        return self._tops

    def module_file(self, dotted: str, main: bool = False) -> tuple[str, str] | None:
        """The file ``python -m dotted`` (``main``: a module, or a package with a ``__main__.py``; a package without
        one cannot run) or ``import dotted`` runs."""
        if main and dotted in self.mains:
            return self.mains[dotted]
        if main and dotted in self.packages:
            return None
        return self.modules.get(dotted)


def _resolve_import(mod: str, level: int, names: tuple, own: str, idx: Index) -> list[str]:
    if level:
        parts = own.split(".") if own else []
        if level - 1 > len(parts):
            return []
        mod = ".".join(parts[:len(parts) - (level - 1)] + ([mod] if mod else []))
    if not mod:
        return []
    out = [f"{mod}.{n}" for n in names if f"{mod}.{n}" in idx.modules]
    parts = mod.split(".")
    for i in range(len(parts), 0, -1):  # the module itself, else its longest importable prefix; then its parents
        d = ".".join(parts[:i])
        if d in idx.modules:
            out.append(d)
    return out


def _label(node: tuple[str, str], idx: Index) -> str:
    d = idx.dotted_of.get(node)
    if d:
        return d.split(".", 1)[1] if "." in d else d
    return node[1].rsplit("/", 1)[-1]


ALL = "*"   # every subcommand of a command module may run


def subcommand_of(func: str, subs: frozenset) -> str:
    """The argparse subcommand a function implements (cmd_publish, do_publish, publish_cmd -> publish), or ''."""
    n = func.lstrip("_")
    for pre in ("cmd_", "command_", "do_", "run_", "handle_"):
        if n.startswith(pre):
            n = n[len(pre):]
            break
    for suf in ("_cmd", "_command"):
        if n.endswith(suf):
            n = n[:-len(suf)]
    return n if n in {s.replace("-", "_") for s in subs} else ""


def _py_edges(node: tuple[str, str], rf: RepoFacts, idx: Index, allowed) -> list[tuple[tuple[str, str], object]]:
    """A Python file's imports and string constants equal to a module or a command. An import inside the function of
    an argparse subcommand counts only when that subcommand may run (``allowed``: ALL or the subcommands named)."""
    f = facts(rf.tree, node[1])
    own = idx.dotted_of.get(node, "")
    own_pkg = own if node[1].endswith("/__init__.py") else own.rsplit(".", 1)[0] if "." in own else ""
    out = []
    for mod, level, names, func in f.imports:
        if func and allowed != ALL and f.subcommands:
            sub = subcommand_of(func, f.subcommands)
            if sub and sub not in allowed:
                continue
        out += [(idx.modules[d], ALL) for d in _resolve_import(mod, level, names, own_pkg, idx)]
    for s in f.strings:
        hit = idx.modules.get(s) or (idx.console.get(s) if not IDENT.fullmatch(s) else None)
        if hit:
            out.append((hit, ALL))
    return out


def edges(node: tuple[str, str], repos: dict[str, RepoFacts], idx: Index, allowed=ALL) \
        -> list[tuple[tuple[str, str], object]]:
    """(file, subcommands) for each file a file names: Python imports and string constants equal to a module or a
    command; in other text, ``-m <dotted> [subcommand]``, script and config file names that resolve to a file of the
    same repo, command names (.exe). The subcommands are ALL, or the set a ``-m`` line names."""
    repo, path = node
    rf = repos[repo]
    if path.endswith(".py"):
        return [(n, s) for n, s in _py_edges(node, rf, idx, allowed) if n != node]
    out: list = []
    text = rf.tree.text(path) or ""
    tops = idx.top_packages()
    for d, sub in DASH_M_ARG.findall(text):
        if d.split(".")[0] in tops:
            hit = idx.module_file(d, main=True)
            if hit:
                out.append((hit, frozenset([sub.replace("-", "_")]) if sub else ALL))
    for tok in set(FILE_REF.findall(text)):
        tok = tok.replace("\\", "/")
        base = tok.rsplit("/", 1)[-1]
        cands = [p for p in rf.tree.by_base(base) if p == tok or p.endswith("/" + tok.lstrip("./"))] \
            or rf.tree.by_base(base)
        here = [p for p in cands if posixpath.dirname(p) == posixpath.dirname(path)]
        out += [((repo, p), ALL) for p in (here or (cands if len(cands) <= 3 else []))]
    for w in set(WORD.findall(text)) & set(idx.console):
        if not IDENT.fullmatch(w) or f"{w}.exe" in text or command_at(text, w):
            out.append((idx.console[w], ALL))
    return [(n, s) for n, s in out if n != node]


def command_at(text: str, name: str) -> bool:
    """A plain-word command name (brain, quant) counts only where a command starts: at a line's start, or after
    ``&``, ``|``, ``;``, ``(`` or a quote; not in prose ("the quant platform")."""
    return re.search(rf"(?m)(?:^\s*|[&|;(`'\"]\s*){re.escape(name)}(?=[\s'\"`)]|$)", text) is not None


def closure(repos: dict[str, RepoFacts], seeds: dict[str, list[str]], idx: Index) \
        -> tuple[dict[tuple[str, str], tuple[int, tuple]], dict[str, list[str]]]:
    """Breadth-first from the seeds: every file reached, with (depth, labels of the files before it), and the seeds
    that resolve to nothing, by repo. A seed is ``script:<console script>``, a repo file or a dotted module. A command
    module run as ``-m <dotted> <subcommand>`` reaches the imports of that subcommand's function only (the scheduler
    runs ``alloc shadow``, not ``alloc publish``); imported, or run without a subcommand, it reaches them all."""
    reached: dict[tuple[str, str], tuple[int, tuple]] = {}
    allowed: dict[tuple[str, str], object] = {}
    missing: dict[str, list[str]] = {}
    queue: deque = deque()

    def visit(node, depth: int, chain: tuple, subs) -> None:
        old = allowed.get(node)
        new = ALL if ALL in (old, subs) else frozenset(old or ()) | subs
        if node not in reached:
            reached[node] = (depth, chain)
        if old is None or new != old:
            allowed[node] = new
            queue.append(node)

    for repo, specs in seeds.items():
        rf = repos[repo]
        for spec in specs:
            if spec.startswith("script:"):
                node = idx.console.get(spec[7:])
            elif rf.tree.has(_norm(spec)):
                node = (repo, _norm(spec))
            elif DOTTED_FULL.fullmatch(spec) or IDENT.fullmatch(spec):
                node = idx.module_file(spec, main=True) or idx.module_file(spec)
            else:
                node = None
            if node is None:
                missing.setdefault(repo, []).append(spec)
            else:
                visit(node, 0, (), ALL)
    while queue:
        node = queue.popleft()
        depth, chain = reached[node]
        for nxt, subs in edges(node, repos, idx, allowed[node]):
            visit(nxt, depth + 1, chain + (_label(node, idx),), subs)
    return reached, missing


# --- code stores and CodeRefs ---

_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def parse_code_ref(cid: str) -> tuple[str, str, str]:
    """(repo, path, symbol) of ``code:<repo>:<path>[::<symbol>]``, research_graph's code_layer grammar; ValueError
    otherwise."""
    if not cid.startswith("code:"):
        raise ValueError("must start with 'code:'")
    repo, sep, rest = cid[5:].partition(":")
    if not sep or not _REPO.fullmatch(repo):
        raise ValueError("expected code:<repo>:<path>[::<symbol>]")
    path, sep, symbol = rest.partition("::")
    if sep and not _SYMBOL.fullmatch(symbol):
        raise ValueError(f"bad symbol {symbol!r}")
    if not path or "\\" in path or ":" in path or path.startswith("/") \
            or any(p in {"", ".", ".."} for p in path.split("/")):
        raise ValueError(f"bad path {path!r}")
    if sep and not path.endswith(".py"):
        raise ValueError("a symbol needs a .py file")
    return repo, path, symbol if sep else ""


@dataclass
class Store:
    repo: str
    path: str                      # its folder in that repo
    node_types: list
    code_refs: list[tuple[str, str]] = field(default_factory=list)   # (id, status)
    repo_nodes: set = field(default_factory=set)

    @property
    def code_layer(self) -> bool:
        return "CodeRef" in self.node_types


_YAML: dict[str, object] = {}


def _load_yaml(tree: Tree, path: str):
    key = tree.key(path) or f"{tree.repo}:{path}"
    if key not in _YAML:
        y = graph._yaml()
        try:
            _YAML[key] = graph.load_yaml(tree.text(path) or "")
        except y.YAMLError:
            _YAML[key] = None
    return _YAML[key]


def code_stores(repos: dict[str, RepoFacts], declared: list[tuple[str, str]]) -> list[Store]:
    """The project's stores (``declared``: (repo, folder)) and any ``notes/graph`` or ``ops/graph`` of a repo whose
    schema has CodeRef (hedge-fund's operations graph), with their CodeRef and Repo nodes."""
    out, seen = [], set()
    auto = [(r, s) for r in repos for s in ("notes/graph", "ops/graph")]
    for repo, rel in list(declared) + auto:
        if (repo, rel) in seen or repo not in repos:
            continue
        seen.add((repo, rel))
        tree = repos[repo].tree
        if not tree.has(f"{rel}/schema.yaml"):
            continue
        schema = _load_yaml(tree, f"{rel}/schema.yaml") or {}
        types = list(schema.get("node_types") or []) if isinstance(schema, dict) else []
        if (repo, rel) not in declared and "CodeRef" not in types:
            continue
        st = Store(repo, rel, types)
        if st.code_layer:
            files = sorted(p for p in tree.files if p.startswith(f"{rel}/nodes/") and p.endswith(".yaml"))
            tree.prefetch(files)
            for f in files:
                text = tree.text(f) or ""
                if "CodeRef" not in text and "Repo" not in text:
                    continue
                for n in _load_yaml(tree, f) or []:
                    if isinstance(n, dict) and n.get("type") == "CodeRef":
                        st.code_refs.append((str(n.get("id")), str(n.get("status", ""))))
                    elif isinstance(n, dict) and n.get("type") == "Repo":
                        st.repo_nodes.add(str(n.get("id")))
        out.append(st)
    return out
