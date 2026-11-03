"""Coverage measured (wi-brain-test-coverage): a repo's Python tests run under pytest-cov with test contexts, reduced
to a summary the store keeps, ``<store>/coverage/<repo>.json``. ``brain coverage`` writes it; ``brain sync`` reads it
for the tested_by links of a CodeRef's symbol (brain.links: the test modules that ran that function), ``brain audit``
for test.coverage and FEATURES.md for each feature's coverage. Zero token: the run is the repo's own pytest, the
reading is SQLite and JSON.

A run (``--run``) groups the repo's test modules by the folder of their nearest pytest configuration (a pyproject.toml
with [tool.pytest.ini_options], a pytest.ini, a tox.ini or setup.cfg with a pytest section) and runs pytest there, the
repo's package roots under ``--cov`` with ``--cov-context=test``; pytest-cov (and pytest-xdist for ``-n``) must be in
that Python. ``--from`` reads a coverage data file made elsewhere (the CI's ``.coverage``), with ``--cwd`` the folder
pytest ran in. The statements of each file come from ``coverage json`` (without its contexts: with them, the report of
this engine's suite is gigabytes); which test ran which line, from the data file's own tables. The repo's code is
never imported by the brain: pytest runs it in its own process.

The summary (sorted keys, so a run that changes nothing writes the same file): the repo, the commit measured (and
whether the tree was dirty), the day, the totals, and per source file its statements, covered lines and percent, and
``tests``: each test module that ran a line of one of its functions -> those functions' qualified names (a method
``Class.method``; a nested function counts for the function that holds it; module and class bodies run at import and
count for no test).
"""

from __future__ import annotations

import ast
import json
import os
import posixpath
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from . import inventory

FOLDER = "coverage"
VERSION = 1
CONFIGS = ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg")


class CoverageError(Exception):
    pass


def path_of(store_rel: str, repo: str) -> str:
    """The summary's path in the store's repo (``store_rel``: the store's folder there)."""
    return f"{store_rel}/{FOLDER}/{repo.lower()}.json"


def load(tree: inventory.Tree, store_rel: str, repo: str) -> dict | None:
    """The summary of ``repo`` kept in the store held by ``tree``; None when there is none or it is unreadable."""
    p = path_of(store_rel, repo)
    if not tree.has(p):
        return None
    try:
        data = json.loads(tree.text(p) or "")
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else None


def ran(summary: dict | None, path: str, symbol: str) -> set[str]:
    """The test modules that ran ``symbol`` of ``path`` (or a method of it, for a class), by the summary."""
    out: set[str] = set()
    for t, syms in ((((summary or {}).get("files") or {}).get(path) or {}).get("tests") or {}).items():
        if any(s == symbol or s.startswith(symbol + ".") for s in syms):
            out.add(t)
    return out


# --- symbols ---

def functions(text: str) -> dict[int, str]:
    """Line -> the qualified name of the outermost function (or method) that holds it: ``f``, ``Class.method``;
    the lines of a module or class body are left out."""
    try:
        mod = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    out: dict[int, str] = {}

    def walk(body, prefix: str) -> None:
        for s in body:
            if isinstance(s, ast.ClassDef):
                walk(s.body, f"{prefix}{s.name}.")
            elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                first = min([s.lineno] + [d.lineno for d in s.decorator_list])
                for n in range(first, (s.end_lineno or s.lineno) + 1):
                    out[n] = f"{prefix}{s.name}"
    walk(mod.body, "")
    return out


# --- reports ---

def _rel(path: str, root: Path, cwd: Path) -> str | None:
    """A path a report names, relative to the repo's root (posix); None outside it."""
    p = Path(path)
    p = p if p.is_absolute() else cwd / p
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _nums(numbits: bytes) -> list[int]:
    """The line numbers a coverage numbits blob holds (bit i of byte j: line 8j + i)."""
    return [j * 8 + i for j, byte in enumerate(numbits) for i in range(8) if byte & (1 << i)]


def contexts(data: Path, root: Path, cwd: Path) -> tuple[dict[str, dict[int, set]], str]:
    """(source file -> line -> the test modules that ran it, the coverage version) from a coverage data file (its
    SQLite tables, read without the coverage package): a context ``<test file>::<case>|run`` stands for that test
    module; the empty context (imports, collection) for none."""
    try:
        db = sqlite3.connect(f"file:{data.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise CoverageError(f"{data}: {exc}") from exc
    try:
        meta = dict(db.execute("select key, value from meta").fetchall())
        files = {i: _rel(p, root, cwd) for i, p in db.execute("select id, path from file")}
        tests: dict[int, str | None] = {}
        for i, ctx in db.execute("select id, context from context"):
            name = str(ctx or "").split("|", 1)[0].split("::", 1)[0]
            tests[i] = _rel(name, root, cwd) if name else None
        out: dict[str, dict[int, set]] = {}
        for fid, cid, bits in db.execute("select file_id, context_id, numbits from line_bits"):
            f, t = files.get(fid), tests.get(cid)
            if f and t:
                lines = out.setdefault(f, {})
                for n in _nums(bits):
                    lines.setdefault(n, set()).add(t)
    except sqlite3.Error as exc:
        raise CoverageError(f"{data}: not a coverage data file ({exc})") from exc
    finally:
        db.close()
    return out, str(meta.get("version") or "")


def _merge(reports: list[tuple[dict, dict, Path]], root: Path) -> dict[str, dict]:
    """Source file -> its statements, executed lines and contexts (line -> test modules), over every run."""
    files: dict[str, dict] = {}
    for rep, ctxs, cwd in reports:
        for name, f in (rep.get("files") or {}).items():
            rel = _rel(name, root, cwd)
            if rel is None:
                continue
            cur = files.setdefault(rel, {"statements": 0, "executed": set(), "contexts": {}})
            cur["statements"] = max(cur["statements"], int((f.get("summary") or {}).get("num_statements") or 0))
            cur["executed"] |= set(f.get("executed_lines") or [])
        for rel, lines in ctxs.items():
            for n, ts in (lines.items() if rel in files else ()):
                files[rel]["contexts"].setdefault(n, set()).update(ts)
    return files


def _entry(root: Path, rel: str, cur: dict) -> dict:
    """One file of the summary: its numbers, and each test module -> the functions of the file it ran."""
    src = root / rel
    fn = functions(src.read_text(encoding="utf-8", errors="replace")) if src.is_file() else {}
    tests: dict[str, set] = {}
    for line, ts in cur["contexts"].items():
        for t in ts if fn.get(line) else ():
            tests.setdefault(t, set()).add(fn[line])
    s, c = cur["statements"], min(len(cur["executed"]), cur["statements"])
    return {"statements": s, "covered": c, "percent": _pct(c, s),
            **({"tests": {t: sorted(q) for t, q in sorted(tests.items())}} if tests else {})}


def summarize(reports: list[tuple[dict, dict, Path]], root: Path, repo: str, commit: str = "", dirty: bool = False,
              day: str = "", tool: str = "") -> dict:
    """The summary of runs, each (its ``coverage json`` report: the statements and executed lines of each file, its
    contexts: file -> line -> test modules, the folder pytest ran in); the files' executed lines unioned."""
    files = {rel: _entry(root, rel, cur) for rel, cur in sorted(_merge(reports, root).items())}
    total_s, total_c = sum(f["statements"] for f in files.values()), sum(f["covered"] for f in files.values())
    return {"version": VERSION, "repo": repo.lower(), "commit": commit, "dirty": dirty, "measured": day,
            "tool": f"coverage {tool}".strip(), "statements": total_s, "covered": total_c,
            "percent": _pct(total_c, total_s), "files": files}


def _pct(c: int, s: int) -> float:
    return round(100.0 * c / s, 1) if s else 100.0


def render(summary: dict) -> str:
    return json.dumps(summary, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# --- a run ---

def _has_pytest_config(folder: Path) -> bool:
    for name in CONFIGS:
        f = folder / name
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if name == "pytest.ini" or "[tool.pytest.ini_options]" in text or "[pytest]" in text \
                or "[tool:pytest]" in text:
            return True
    return False


def suites(root: Path, tests: list[str]) -> list[tuple[str, list[str]]]:
    """(the folder pytest runs in, its test folders relative to it) for the repo's Python test modules, grouped by
    their nearest pytest configuration (the repo's root when none)."""
    groups: dict[str, set] = {}
    for t in tests:
        if not t.endswith(".py"):
            continue
        d = posixpath.dirname(t)
        cfg = d
        while cfg and not _has_pytest_config(root / cfg):
            cfg = posixpath.dirname(cfg)
        top = d[len(cfg) + 1:] if cfg else d
        groups.setdefault(cfg, set()).add(top.split("/", 1)[0] if top else posixpath.basename(t))
    return [(cfg, sorted(g)) for cfg, g in sorted(groups.items())]


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _report(python: str, data: Path, where: Path, out: Path) -> dict:
    """``coverage json`` of a data file, without its contexts: the statements and executed lines of each file."""
    js = subprocess.run([python, "-m", "coverage", "json", f"--data-file={data}", "-o", str(out)], cwd=where,
                        capture_output=True, text=True)
    if js.returncode != 0 or not out.is_file():
        raise CoverageError(f"coverage json failed in {where} (coverage installed in {python}?): "
                            f"{(js.stderr or js.stdout).strip()[:300]}")
    return json.loads(out.read_text(encoding="utf-8"))


def run(root: Path, repo: str, tests: list[str], sources: list[str], python: str = "", workers: str = "",
        extra: list[str] | None = None, echo=print) -> tuple[dict, int]:
    """Run each pytest suite of the repo under pytest-cov with test contexts; (the summary, pytest's worst exit
    code). ``sources``: the package roots measured, relative to the root."""
    python = python or sys.executable
    reports: list[tuple[dict, dict, Path]] = []
    worst, tool = 0, ""
    covs = [f"--cov={(root / s).resolve()}" for s in sources] or [f"--cov={root.resolve()}"]
    with tempfile.TemporaryDirectory(prefix="brain-cov-") as tmp:
        for i, (cwd, folders) in enumerate(suites(root, tests)):
            where = root / cwd if cwd else root
            data = Path(tmp) / f".coverage.{i}"
            # the checkout's own code first, before what the Python has installed (an editable install elsewhere)
            env = dict(os.environ, COVERAGE_FILE=str(data), PYTHONPATH=os.pathsep.join(
                [str((root / s).resolve()) for s in sources] + [os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep))
            cmd = [python, "-m", "pytest", *folders, *covs, "--cov-context=test", "--cov-report=",
                   *(["-n", workers] if workers else []), *(extra or [])]
            echo(f"brain coverage: {cwd or '.'}: {' '.join(cmd[1:])}")
            rc = subprocess.run(cmd, cwd=where, env=env).returncode
            if rc not in (0, 1):   # 1: some test failed, the coverage is still read
                raise CoverageError(f"pytest exited {rc} in {where} (pytest-cov installed in {python}?)")
            worst = max(worst, rc)
            ctxs, tool = contexts(data, root, where)
            reports.append((_report(python, data, where, Path(tmp) / f"coverage.{i}.json"), ctxs, where))
    head = _git(root, "rev-parse", "HEAD")
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=no"))
    return summarize(reports, root, repo, head, dirty, date.today().isoformat(), tool), worst


def from_data(data: Path, cwd: Path, root: Path, repo: str, python: str = "") -> dict:
    """The summary of a coverage data file made elsewhere (the CI's ``.coverage``, run with --cov-context=test),
    pytest having run in ``cwd`` of this checkout (``coverage json`` reads its sources for the statements)."""
    if not data.is_file():
        raise CoverageError(f"{data}: no such file")
    ctxs, tool = contexts(data, root, cwd)
    with tempfile.TemporaryDirectory(prefix="brain-cov-") as tmp:
        rep = _report(python or sys.executable, data.resolve(), cwd, Path(tmp) / "coverage.json")
    head = _git(root, "rev-parse", "HEAD")
    return summarize([(rep, ctxs, cwd)], root, repo, head, False, date.today().isoformat(), tool)


def measure(repo, run_tests: bool, data: str = "", cwd: str = "", python: str = "",
            workers: str = "") -> tuple[dict, int]:
    """brain coverage's measure of a registered repo (``repo``: its projects.Repo): its suites run (``run_tests``), or
    a data file read (``data``, pytest having run in ``cwd``, default the repo's root); (the summary, pytest's exit)."""
    if data:
        return from_data(Path(data), Path(cwd or repo.path).resolve(), repo.path, repo.name, python), 0
    if not run_tests:
        raise CoverageError("--run (run the repo's tests) or --from DATA (a .coverage file)")
    rf = inventory.collect(inventory.work_tree(repo.path), repo.name, repo.lang, repo.roots, repo.waive)
    return run(repo.path, repo.name, rf.tests, sorted(set(rf.root_of.values())) or (repo.roots or []), python,
               workers)


def lines(summary: dict, top: int = 10) -> list[str]:
    """The summary in text: the totals, then the least covered files."""
    files = summary.get("files") or {}
    at = str(summary.get("commit") or "?")[:7] + (" (dirty)" if summary.get("dirty") else "")
    out = [f"{summary.get('repo')}: {summary.get('percent')} % of {summary.get('statements')} statements "
           f"({len(files)} files) at {at}"]
    for p, f in sorted(files.items(), key=lambda kv: (kv[1]["percent"], kv[0]))[:top]:
        out.append(f"  {f['percent']:5.1f} %  {f['covered']}/{f['statements']}  {p}")
    return out
