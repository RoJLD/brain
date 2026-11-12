"""A project's own formats and migrations (wi-brain-project-formats; spec-brain-data-compat § 3 « Other projects »,
norm N1; the owner's PF-1 answer, « Opt-in run »): ``projects.yaml`` ``formats:`` and ``migrations:``, in any
language.

``formats:`` registers the persisted formats a project's code reads and writes, one entry each::

  formats:
    - id: alloc-contract                     # unique in the project
      glob: alloc/*.json                     # its files, relative to the repo: a glob or a list (** any folders)
      repo: quant                            # optional: a repo name of repos: (default: the project's first, its root)
      class: private                         # its data class (brain.classes.CLASSES)
      version: SCHEMA_VERSION                # where its version is read: free text
      schema: schemas/alloc.schema.json      # optional: a file that exists
      fixtures: tests/fixtures/alloc/        # optional: a folder that exists
      check: python -m quantlab.alloc --check   # optional: exit 0 valid, 1 invalid
      timeout: 120                           # optional: the check's bound in seconds (default 120, at most 3600)

**The declarations are checked always**, with the registry (``brain check`` in a brain's root, ``brain check --all``;
:func:`errors`): the keys and their shapes, an id unique in the project, a known data class, a repo the project
spans; then, where the repo's checkout is on this machine (:func:`presence`), a glob that matches a file, a schema
file and a fixtures folder that exist. **The check commands run only on demand** (:func:`run`: ``brain formats
check``, or ``brain check --formats``), never on a plain ``brain check``: each in its repo's checkout, with no shell
(a string is split as a POSIX shell would, a list is the argv), bounded by its timeout, its result (exit 0 pass, 1
fail) cached under ``$BRAIN_HOME/formats/<project>.json`` by the hashes of the command and of the files it judges
(its glob's files, its schema, its fixtures); a timeout or another exit code is an error, never cached. A project
the brain only reads (``access: read``) declares no format (its entry holds title, access, parent and classes only)
and is never loaded, so no command of it is ever run.

``migrations:`` is the glob check of the scout (``brain audit --diff``, :func:`migration_signals`): a change of a
``when`` file (a model, an SQL schema) comes with a new file of each ``add`` glob (a migration, a fixture)::

  migrations:
    - when: ["models/**/*.py", "db/*.sql"]
      add: ["migrations/*.py", "tests/fixtures/db/**"]
      repo: quant                            # optional, as above

A when-file changed (not a light touch: docstrings, imports or whitespace only) with no added file matching an
``add`` glob is a NEW ``format.migration`` finding on that file; a ``Justified: <path>: <reason>`` line (the PR body
or a commit message, as for the structure signals) makes it justified. An unknown key of an entry is a note in read
mode, kept, and an error in strict mode (CI), as every registry key (brain.schema.tolerate).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import boundary, classes, paths, schema, stateio

DIR = "formats"   # $BRAIN_HOME/formats/<project>.json: the checks' cached results (classes.ENGINE_STORES)
CACHE_V = 1
TIMEOUT = 120
MAX_TIMEOUT = 3600
TAIL = 20   # the lines of a check's output kept with its result
ID = re.compile(r"[a-z0-9][a-z0-9_.-]*")
FORMAT_KEYS = {
    "id": "the format's id, unique in the project (lowercase letters, digits, '.', '_', '-')",
    "glob": "its files, relative to the repo: a glob or a list (** any folders, * and ? within a name)",
    "repo": "the repo they live in, by its name in repos: (default: the project's first repo, its root)",
    "class": f"its data class: {', '.join(classes.CLASSES)}",
    "version": "where its version is read (a constant, a field, a header): free text",
    "schema": "its schema file, relative to the repo (optional; it must exist)",
    "fixtures": "its fixtures folder, relative to the repo (optional; it must exist)",
    "check": "a command that judges its files, run in the repo by brain formats check only: a string (split as a "
             "POSIX shell would, no shell) or an argv list; exit 0 valid, 1 invalid",
    "timeout": f"the check's bound in seconds (default {TIMEOUT}, at most {MAX_TIMEOUT})",
}
REQUIRED = ("id", "glob", "class", "version")
MIGRATION_KEYS = {
    "when": "the files whose change needs a migration (a model, an SQL schema): a glob or a list",
    "add": "the globs a change of a when file must add a file to, each one (a migration, a fixture)",
    "repo": "the repo, by its name in repos: (default: the project's first repo, its root)",
}


@dataclass
class Format:
    id: str
    globs: list[str]
    cls: str
    version: str
    repo: str = ""                 # '' : the project's first repo
    schema: str = ""
    fixtures: str = ""
    check: list[str] | None = None   # the argv; None: no check declared
    timeout: int = TIMEOUT


@dataclass
class Migration:
    when: list[str]
    add: list[str]
    repo: str = ""
    index: int = 0


@dataclass
class Result:
    format: str
    status: str                    # pass, fail, error, timeout, skipped (no check:), invalid (its declaration)
    cached: bool = False
    seconds: float = 0.0
    detail: str = ""
    tail: list[str] = field(default_factory=list)


# --- the declarations ---

def _globs(value) -> list[str] | None:
    value = [value] if isinstance(value, str) else value
    if isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value):
        return [v.strip().replace("\\", "/") for v in value]
    return None


def argv(value) -> list[str] | None:
    """A check: as an argv: a string split as a POSIX shell would (no shell runs it), a list of strings as given;
    None when it is neither, or empty."""
    if isinstance(value, str):
        try:
            out = shlex.split(value, posix=True)
        except ValueError:
            return None
        return out or None
    if isinstance(value, list) and value and all(isinstance(v, str) and v for v in value):
        return list(value)
    return None


def _unknown(where: str, entry: dict, known: dict) -> list[str]:
    extra = sorted(set(map(str, entry)) - set(known))
    return schema.tolerate(f"{where}: unknown key(s) {', '.join(extra)} (known: {', '.join(known)})") if extra else []


def _relpath_ok(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    p = value.replace("\\", "/")
    return not (p.startswith("/") or re.match(r"[A-Za-z]:", p) or ".." in p.split("/"))


def format_errors(where: str, value, repos: list[str] | None = None) -> list[str]:
    """What a project's formats: breaks: a list of mappings, each with id, glob, class and version, the optional
    keys of the right shape, ids unique; ``repos``: the project's repo names, when known, that repo: must name."""
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"{where}: formats is a list of mappings (brain projects --keys)"]
    errors, seen = [], set()
    for i, entry in enumerate(value):
        w = f"{where}: formats[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{w}: a mapping of {', '.join(FORMAT_KEYS)}")
            continue
        fid = entry.get("id")
        if isinstance(fid, str) and fid:
            w = f"{where}: format {fid}"
        errors += _unknown(w, entry, FORMAT_KEYS)
        errors += [f"{w}: {k} is required" for k in REQUIRED if k not in entry]
        if "id" in entry:
            if not isinstance(fid, str) or not ID.fullmatch(fid):
                errors.append(f"{w}: id is lowercase letters, digits, '.', '_' and '-' ({fid!r})")
            elif fid in seen:
                errors.append(f"{w}: its id is used twice in the project")
            else:
                seen.add(fid)
        if "glob" in entry and _globs(entry["glob"]) is None:
            errors.append(f"{w}: glob is a glob or a list of globs")
        elif "glob" in entry and not all(_relpath_ok(g) for g in _globs(entry["glob"]) or []):
            errors.append(f"{w}: glob is relative to the repo (no root, drive or '..')")
        if "class" in entry and entry["class"] not in classes.CLASSES:
            errors.append(f"{w}: class is one of {', '.join(classes.CLASSES)}, not {entry['class']!r}")
        if "version" in entry and (not isinstance(entry["version"], str) or not entry["version"].strip()):
            errors.append(f"{w}: version says where its version is read (a string)")
        for k in ("schema", "fixtures"):
            if k in entry and not _relpath_ok(entry[k]):
                errors.append(f"{w}: {k} is a path relative to the repo (no root, drive or '..')")
        if "check" in entry and argv(entry["check"]) is None:
            errors.append(f"{w}: check is a command: a string or a list of strings")
        t = entry.get("timeout", TIMEOUT)
        if not isinstance(t, int) or isinstance(t, bool) or not 1 <= t <= MAX_TIMEOUT:
            errors.append(f"{w}: timeout is a whole number of seconds from 1 to {MAX_TIMEOUT}")
        errors += _repo_error(w, entry, repos)
    return errors


def _repo_error(w: str, entry: dict, repos: list[str] | None) -> list[str]:
    if "repo" not in entry:
        return []
    r = entry["repo"]
    if not isinstance(r, str) or not r:
        return [f"{w}: repo is a repo name of the project's repos:"]
    if repos is not None and r not in repos:
        return [f"{w}: repo {r!r} is not one of the project's repos ({', '.join(repos) or 'none'})"]
    return []


def migration_errors(where: str, value, repos: list[str] | None = None) -> list[str]:
    """What a project's migrations: breaks: a list of mappings, each with when and add (globs)."""
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"{where}: migrations is a list of mappings of when and add (brain projects --keys)"]
    errors = []
    for i, entry in enumerate(value):
        w = f"{where}: migrations[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{w}: a mapping of {', '.join(MIGRATION_KEYS)}")
            continue
        errors += _unknown(w, entry, MIGRATION_KEYS)
        for k in ("when", "add"):
            g = _globs(entry.get(k))
            if g is None:
                errors.append(f"{w}: {k} is a glob or a list of globs")
            elif not all(_relpath_ok(x) for x in g):
                errors.append(f"{w}: {k} is relative to the repo (no root, drive or '..')")
        errors += _repo_error(w, entry, repos)
    return errors


def errors(where: str, entry: dict, repos: list[str] | None = None) -> list[str]:
    """The declarations of a registry entry (formats: and migrations:), checked by projects.check."""
    return format_errors(where, entry.get("formats"), repos) + migration_errors(where, entry.get("migrations"), repos)


def repo_errors(where: str, entry: dict, repos: list[str]) -> list[str]:
    """The repo: values of a project's formats: and migrations: that name none of its repos (once its repos: are
    known, after :func:`errors` judged the shapes)."""
    out = []
    for key in ("formats", "migrations"):
        value = entry.get(key)
        for i, e in enumerate(value if isinstance(value, list) else []):
            if isinstance(e, dict) and isinstance(e.get("repo"), str) and e["repo"]:
                label = f"format {e['id']}" if key == "formats" and isinstance(e.get("id"), str) else f"{key}[{i}]"
                out += _repo_error(f"{where}: {label}", e, repos)
    return out


def check_project(where: str, entry: dict, repos: dict[str, Path], default: str) -> list[str]:
    """What a loaded project's formats: and migrations: break once its repos are known: a repo: none of them is, and
    what its checkouts on this machine lack (:func:`presence`)."""
    return (repo_errors(where, entry, list(repos))
            + presence(where, formats_of(entry.get("formats")), repos, default))


def formats_of(value) -> list[Format]:
    """The well-formed entries of a formats: value (format_errors names the others)."""
    out = []
    for entry in value if isinstance(value, list) else []:
        if not isinstance(entry, dict) or format_errors("", [entry]):
            continue
        t = entry.get("timeout", TIMEOUT)
        out.append(Format(entry["id"], _globs(entry["glob"]) or [], entry["class"], entry["version"].strip(),
                          str(entry.get("repo") or ""), str(entry.get("schema") or ""),
                          str(entry.get("fixtures") or ""), argv(entry["check"]) if "check" in entry else None, t))
    return out


def migrations_of(value) -> list[Migration]:
    """The well-formed entries of a migrations: value."""
    out = []
    for i, entry in enumerate(value if isinstance(value, list) else []):
        if isinstance(entry, dict) and not migration_errors("", [entry]):
            out.append(Migration(_globs(entry["when"]) or [], _globs(entry["add"]) or [],
                                 str(entry.get("repo") or ""), i))
    return out


# --- the files ---

def matcher(globs: list[str]):
    rx = [boundary.glob_regex(g) for g in globs]
    return lambda path: any(r.match(path) for r in rx)


def files(top: Path, globs: list[str]) -> list[str]:
    """The files under ``top`` that match one of ``globs`` (relative, /-separated, sorted); a .git folder never."""
    hit = matcher(globs)
    out = []
    for dirpath, dirs, names in os.walk(top):
        dirs[:] = [d for d in dirs if d != ".git"]
        rel = Path(dirpath).relative_to(top).as_posix()
        for n in names:
            p = n if rel == "." else f"{rel}/{n}"
            if hit(p):
                out.append(p)
    return sorted(out)


def repo_path(f, repos: dict[str, Path], default: str) -> Path | None:
    """The checkout of the repo a format or a migration names (its project's first repo by default)."""
    return repos.get(f.repo or default)


def presence(where: str, fmts: list[Format], repos: dict[str, Path], default: str) -> list[str]:
    """What a project's formats declare and its checkouts lack: a glob that matches no file, a schema file or a
    fixtures folder that is not there. A repo not checked out on this machine is not judged."""
    errors = []
    for f in fmts:
        top = repo_path(f, repos, default)
        if top is None or not top.is_dir():
            continue
        w = f"{where}: format {f.id}"
        if not files(top, f.globs):
            errors.append(f"{w}: its glob {', '.join(f.globs)} matches no file in {top.name}")
        if f.schema and not (top / f.schema).is_file():
            errors.append(f"{w}: its schema {f.schema} is not a file in {top.name}")
        if f.fixtures and not (top / f.fixtures).is_dir():
            errors.append(f"{w}: its fixtures {f.fixtures} is not a folder in {top.name}")
    return errors


# --- the checks, on demand ---

def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def key(f: Format, top: Path) -> str:
    """The cache key of a format's check: the command, its timeout, and the content of every file it judges (its
    glob's files, its schema, its fixtures' files), by path."""
    judged = set(files(top, f.globs))
    if f.schema and (top / f.schema).is_file():
        judged.add(f.schema.replace("\\", "/"))
    if f.fixtures and (top / f.fixtures).is_dir():
        base = f.fixtures.replace("\\", "/").rstrip("/")
        judged |= {f"{base}/{x}" for x in files(top / base, ["**"])}
    h = {p: _sha((top / p).read_bytes()) for p in sorted(judged) if (top / p).is_file()}
    return _sha(json.dumps({"v": CACHE_V, "argv": f.check, "timeout": f.timeout, "files": h},
                           sort_keys=True).encode("utf-8"))


def cache_file(project: str) -> Path:
    return paths.brain_home() / DIR / f"{project}.json"


def _cache(project: str) -> stateio.State:
    return stateio.load(cache_file(project), known=CACHE_V,
                        check=lambda d: "" if isinstance(d.get("results", {}), dict) else "results is not a mapping")


def _tail(text: str) -> list[str]:
    return [line for line in (text or "").splitlines() if line.strip()][-TAIL:]


def _exe(args: list[str]) -> list[str]:
    found = shutil.which(args[0])
    return [found, *args[1:]] if found else args


def run_one(f: Format, top: Path) -> Result:
    """Run a format's check in ``top``, bounded: pass (exit 0), fail (1), timeout, or error (another exit code, a
    command not found)."""
    t0 = time.monotonic()
    try:
        cp = subprocess.run(_exe(f.check or []), cwd=top, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=f.timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Result(f.id, "timeout", seconds=time.monotonic() - t0, detail=f"stopped after {f.timeout} s")
    except OSError as exc:
        return Result(f.id, "error", seconds=time.monotonic() - t0, detail=f"cannot run {f.check[0]!r}: "
                      f"{exc.__class__.__name__}")
    status = {0: "pass", 1: "fail"}.get(cp.returncode, "error")
    detail = "" if status != "error" else f"exit {cp.returncode} (a check exits 0 or 1)"
    return Result(f.id, status, seconds=time.monotonic() - t0, detail=detail,
                  tail=_tail(cp.stdout + "\n" + cp.stderr))


def run(project: str, fmts: list[Format], repos: dict[str, Path], default: str, *, only: str = "",
        fresh: bool = False, timeout: int | None = None) -> list[Result]:
    """Each format's check (``only``: the one of that id), in its repo's checkout: a cached result whose key still
    holds is reused unless ``fresh``; a pass or a fail is written to the cache, a timeout or an error never is.
    ``timeout`` overrides every format's own."""
    state = _cache(project)
    cached = state.data.get("results", {}) if state.status == "ok" else {}
    results, changed = [], False
    for f in fmts:
        if only and f.id != only:
            continue
        if timeout is not None:
            f = Format(**{**f.__dict__, "timeout": timeout})
        top = repo_path(f, repos, default)
        if f.check is None:
            results.append(Result(f.id, "skipped", detail="no check: declared"))
            continue
        if top is None or not top.is_dir():
            results.append(Result(f.id, "error", detail=f"its repo {f.repo or default} is not checked out here"))
            continue
        k = key(f, top)
        hit = cached.get(f.id)
        if not fresh and isinstance(hit, dict) and hit.get("key") == k and hit.get("status") in ("pass", "fail"):
            results.append(Result(f.id, hit["status"], cached=True, seconds=0.0,
                                  tail=list(hit.get("tail") or [])))
            continue
        r = run_one(f, top)
        results.append(r)
        if r.status in ("pass", "fail"):
            cached[f.id] = {"key": k, "status": r.status, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "seconds": round(r.seconds, 3), "tail": r.tail}
            changed = True
    if changed and state.writable:
        try:
            stateio.save(state, {**state.data, "results": cached})
        except (OSError, stateio.StateError):
            pass   # the cache is a convenience: a result not written is run again next time
    return results


# --- the scout's glob check ---

def migration_signals(repo: str, default: str, rules: list[Migration], rows, touched: dict[str, bool],
                      body: str) -> list[dict]:
    """The scout's ``format.migration`` findings in repo ``repo`` (``default``: the project's first repo, the one
    a rule without repo: names): a when-file changed (a light touch aside) with no file added that matches one of
    the rule's add globs. NEW on the first such when-file, justified with a 'Justified: <path>: <reason>' line."""
    from .structure import JUSTIFIED
    justified = {m.group(1).strip() for m in JUSTIFIED.finditer(body or "")}
    added = sorted(path for st, _, path in rows if st[:1] in "AC" and path)
    out = []
    for m in rules:
        if (m.repo or default) != repo:
            continue
        when = matcher(m.when)
        hit = sorted(path for st, _, path in rows if path and st[:1] != "D" and when(path)
                     and not touched.get(path, False))
        if not hit:
            continue
        missing = [g for g in m.add if not any(matcher([g])(a) for a in added)]
        if not missing:
            continue
        unit = hit[0]
        tag = "justified" if unit in justified else "NEW"
        more = f" (+{len(hit) - 1} more)" if len(hit) > 1 else ""
        out.append({"key": f"{repo}:format.migration:{unit}", "check": "format.migration",
                    "severity": "P1" if tag == "NEW" else "info", "unit": unit, "class": "", "chain": "",
                    "via": "", "tag": tag,
                    "why": f"{unit}{more} matches migrations[{m.index}].when: no new file matching "
                           f"{', '.join(missing)}",
                    "fix": "add the migration and its fixture (projects.yaml migrations:), or a "
                           f"'Justified: {unit}: <reason>' line"})
    return out
