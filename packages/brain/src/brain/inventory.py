"""Facts about a project's repos, for ``brain audit`` and its scout, and nothing else (no severity, no output): the
files of a repo at a commit (git plumbing, no checkout) or in its working tree, the Python package layout, the units
(modules, scripts, commands), the docs set, the test evidence of each unit, the static production closure from the
declared entries, and the CodeRefs of the code stores. Zero token: AST, YAML and git only; a repo's code is never
imported or run.

A git failure raises AuditError (exit code 2): it never reads as an empty tree, which would look like 'no tests' and
create false debt. Side effects are module functions the tests can replace, as in brain.stacks: ``_run_git`` (every
git call, ``GIT_OPTIONAL_LOCKS=0``, no prompt) and ``_read_bytes`` (a working-tree file). Blobs and their parsed facts
are cached by blob id, so the weekly trend re-reads only what changed.

By concern: the text patterns and a Python file's facts (brain.inventory_python), the production closure
(brain.inventory_closure), the test evidence (brain.inventory_evidence), the code stores and their CodeRefs
(brain.inventory_stores); this module holds the side effects, the trees, the layout and the units, and keeps every
public name the others had here (brain.inventory.closure, Index, parse_code_ref, ...: __all__, and the private
_norm, _parse and _load_yaml that callers read). A patch of a moved name is its module's (brain.inventory_python.facts
for the closure's reads); ``_run_git`` and ``_read_bytes`` stay here.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import posixpath
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import diffs
from .inventory_closure import ALL, DASH_M_ARG, Index, closure, command_at, edges, subcommand_of
from .inventory_evidence import (
    Evidence,
    Reach,
    evidence,
    module_evidence,
    reexports,
    script_evidence,
    shim_target,
    stem,
    tests_reach,
    text_tokens,
    unit_evidence,
)
from .inventory_python import (
    ASSIGN,
    DEF,
    DOTTED,
    DOTTED_FULL,
    FILE_REF,
    FIXTURE,
    IDENT,
    IMPORT,
    RUN,
    STR,
    STRING,
    SUBPARSER,
    TRIPLE,
    USED,
    WORD,
    PyFacts,
    _norm,
    _parse,  # noqa: F401 (links.py reads brain.inventory._parse)
    facts,
    has_symbol,
    run_mentions,
    text_imports,
    without_fixtures,
)
from .inventory_stores import Store, _load_yaml, code_stores, parse_code_ref  # noqa: F401 (_load_yaml: callers)

try:  # Python 3.11+; on 3.10 the tomli backport (a dependency there); without both, a pyproject.toml is not measured
    import tomllib
except ImportError:  # pragma: no cover - depends on the interpreter
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

# brain.inventory's names: its own, and those of the concern modules it is the front of (kept for its callers)
__all__ = ["ALL", "ASSIGN", "DASH_M", "DASH_M_ARG", "DEF", "DOTTED", "DOTTED_FULL", "FILE_REF", "FIXTURE", "GIT_ENV",
           "IDENT", "IMPORT", "MAKE_CALL", "MAKE_TARGET", "RUN", "SCRIPT_EXT", "SKIP_DIRS", "STR", "STRING",
           "SUBPARSER", "TEST_DIRS", "TEXT_EXT", "TRIPLE", "USED", "WORD", "AuditError", "Evidence", "Index",
           "Layout", "PyFacts", "Reach", "RepoFacts", "Store", "Tree", "Unit", "closure", "code_stores", "collect",
           "command_at", "default_branch", "edges", "evidence", "facts", "frozen_store", "git", "git_tree",
           "has_symbol", "in_tests", "is_doc", "is_test", "layout", "make_targets", "module_evidence", "module_index",
           "parse_code_ref", "reading_ref", "reexports", "run_mentions", "script_evidence", "shim_target", "skipped",
           "stem", "subcommand_of", "tests_reach", "text_imports", "text_tokens", "unit_evidence", "wanted",
           "week_commits", "without_fixtures", "work_tree"]

GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat", "LC_ALL": "C"}
SKIP_DIRS = {"upstream", "patches", "node_modules", "experiments", "__pycache__", ".venv", "venv", "site-packages"}
TEST_DIRS = {"tests", "test"}
SCRIPT_EXT = (".ps1", ".psm1", ".sh", ".bat", ".cmd")
TEXT_EXT = (".py", ".md", ".toml", ".json", ".psd1") + SCRIPT_EXT
DASH_M = re.compile(r"(?<![\w-])-m\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
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
        raise AuditError(f"git {' '.join(diffs.shown(args)[:4])} in {repo} failed: "
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


# --- layout and units ---

@dataclass
class Layout:
    roots: list[str] | None            # package roots ('' = the repo root); None when unreadable
    tops: list[str] | None = None      # top-level package patterns (fnmatch); None = any
    scripts: dict[str, str] = field(default_factory=dict)   # console script -> module:function
    why: str = ""


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


def frozen_store(path: str) -> bool:
    """A file of a frozen store: under ``<a test folder>/**/fixtures/stores/`` (tests/fixtures/stores/<tag>/), a brain
    an older engine wrote and froze (wi-brain-old-store-fixture), data a test reads, never a doc or code a change is
    reviewed on. Any other fixture, code a test runs (a fake binary) included, is reviewed as it was."""
    parts = path.split("/")[:-1]
    return any(p in TEST_DIRS and any(parts[j:j + 2] == ["fixtures", "stores"] for j in range(i + 1, len(parts)))
               for i, p in enumerate(parts))


def is_test(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    if skipped(path) or base in ("conftest.py", "__init__.py") or frozen_store(path):   # a frozen store's hook: data
        return False
    if base.endswith(".py"):
        return base.startswith("test_") or base.endswith("_test.py")
    if base.endswith(".Tests.ps1") or re.search(r"\.(test|spec)\.(ts|tsx|js|mjs)$", base):
        return True
    return in_tests(path) and base.endswith((".ps1", ".sh", ".ts", ".tsx", ".js", ".mjs"))


def is_doc(path: str) -> bool:
    """The docs set: READMEs at any depth, docs/**, runbooks; not specs or plans (docs/specs, docs/*/plans...),
    changelogs, journals or a frozen store (:func:`frozen_store`)."""
    low = path.lower()
    base = low.rsplit("/", 1)[-1]
    dirs = low.split("/")[:-1]
    if not low.endswith(".md") or skipped(path) or (dirs[:1] == ["docs"] and {"specs", "plans"} & set(dirs)) \
            or base.startswith(("changelog", "journal")) or frozen_store(path):
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
