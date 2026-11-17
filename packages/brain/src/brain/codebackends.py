"""The code index as an adapter (wi-brain-code-index-adapter): ``brain index``, ``brain code-map``, ``brain impact``
and ``brain health code-index`` ask one interface which backend serves them, and each backend is declared in the tier
registry (tiers.yaml) with its requirements and its fallback.

Two backends index code:

- ``gitnexus`` (brain.codeindex): GitNexus in its container, declared by the stack whose ``index:`` names it. The
  code authority for search and the default: it serves all four (``brain code-map`` reads its Cypher).
- ``cbm`` (brain.cbm): codebase-memory-mcp's binary, run as a stdio MCP server for the time of a command. The code
  index of a machine without Docker (``brain index`` indexes the declared repos in place when no stack declares
  ``index:``) and ``brain impact`` on a worktree: it indexes the worktree in place under a temporary name, asks
  ``detect_changes`` against the base and deletes that index, so a branch never pushed anywhere has its symbols and
  callers. It serves index, impact and health, not code-map.

Without either, ``brain impact`` falls back to the file level (every CodeRef of a changed file, a Python symbol's
narrowed by the AST of both sides) and says why.

The interface names what it indexes (:attr:`Backend.kind`): code today; a typology pack may declare another kind of
artefact index (a CAD feature tree, a media index) with the same four doors, so a non-code index is not a second
one-way door (the typology packs' spec, its door 11).
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import cbm, codeindex, faults

PURPOSES = ("index", "code-map", "impact", "health")
CONTAINERS = ("File", "Module", "Folder", "Package", "Project", "Section")   # CBM's nodes that hold symbols
TEMP = re.compile(r"-wt-[0-9a-f]{8}$")   # a temporary project of brain impact (temp_name)


@dataclass(frozen=True)
class Backend:
    name: str
    kind: str              # what it indexes: code (a typology pack may add another kind)
    title: str
    serves: frozenset      # of PURPOSES
    tier: str              # its entry in tiers.yaml


BACKENDS = {
    "gitnexus": Backend("gitnexus", "code", "GitNexus", frozenset(PURPOSES), "code-index-gitnexus"),
    "cbm": Backend("cbm", "code", "codebase-memory-mcp", frozenset({"index", "impact", "health"}), "code-index-cbm"),
}


def why_not(name: str, root: Path | None = None) -> str:
    """'' when backend ``name`` is declared or installed on this machine, else why not (it may still be down)."""
    if name == "cbm":
        return "" if cbm.installed() else f"codebase-memory-mcp is not installed ({cbm.binary().as_posix()})"
    try:
        ix, _ = codeindex.load(root)
    except codeindex.CodeIndexError as exc:
        return f"the code index's declaration: {exc}"
    return "" if ix is not None else "no stack declares index: (the GitNexus stack)"


def choose(purpose: str, wanted: str | None = None, root: Path | None = None, worktree: bool = False) -> list[str]:
    """The backends to try for ``purpose``, in order: ``wanted`` alone when given (CodeIndexError when it does not
    serve it), else those this machine has: for impact on a worktree cbm first, else gitnexus first."""
    if wanted:
        if wanted not in BACKENDS:
            raise codeindex.CodeIndexError(f"unknown backend {wanted} (known: {', '.join(BACKENDS)})")
        if purpose not in BACKENDS[wanted].serves:
            raise codeindex.CodeIndexError(f"{wanted} does not serve {purpose} "
                                           f"(it serves {', '.join(sorted(BACKENDS[wanted].serves))})")
        return [wanted]
    order = ["cbm", "gitnexus"] if purpose == "impact" and worktree else ["gitnexus", "cbm"]
    return [b for b in order if purpose in BACKENDS[b].serves and not why_not(b, root)]


# --- cbm: brain index and brain health code-index ---

def _head(path: Path) -> tuple[str, str, bool, str]:
    """(branch, HEAD's commit, dirty, '') of the checkout CBM indexes in place, else (.., .., .., why not)."""
    if not (path / ".git").exists():
        return "", "", False, f"{path.as_posix()} is not a git checkout"
    code, sha = codeindex._git(path, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if code != 0 or not sha.strip():
        return "", "", False, f"no commit in {path.as_posix()}"
    _, branch = codeindex._git(path, "rev-parse", "--abbrev-ref", "HEAD")
    code, porcelain = codeindex._git(path, "status", "--porcelain", "--untracked-files=no")
    return branch.strip(), sha.strip(), bool(code == 0 and porcelain.strip()), ""


def cbm_state(r: codeindex.Repo, rec: dict | None) -> tuple[str, str]:
    """(OK, STALE, NOT INDEXED or ERROR; why) of ``r`` in CBM's record."""
    branch, sha, _, why = _head(r.path)
    if why:
        return "ERROR", why
    if not rec or not rec.get("sha"):
        return "NOT INDEXED", f"{branch}@{sha[:7]}"
    if rec["sha"] != sha:
        return "STALE", f"{branch or 'HEAD'} moved off the index ({str(rec['sha'])[:7]})"
    dirty = ", with uncommitted changes" if rec.get("dirty") else ""
    return "OK", f"{branch}@{sha[:7]}{dirty}, indexed {str(rec.get('indexed_at', '?'))[:16]}"


def cbm_index(repos: dict[str, codeindex.Repo], names: list[str], every: bool, stale: bool, out) -> int:
    """``brain index --backend cbm``: each repo's state (no name, no flag), else index the named, every or stale ones
    in place, as CBM's project named after the repo. CBM's settings are set off first in both cases."""
    try:
        changed = cbm.ensure_off()
    except cbm.CbmError as exc:
        print(f"brain index: codebase-memory-mcp: {exc}", file=out)
        return 1
    if changed:
        print(f"codebase-memory-mcp: {', '.join(changed)} set to false", file=out)
    if not repos:
        print("no repo declared under code_index: (cbm)", file=out)
        return 0
    rec = cbm.read_record()
    if not (names or every or stale):
        for r in repos.values():
            state, why = cbm_state(r, rec.get(r.name))
            print(f"{r.name} {state} (cbm): {why}" if state != "OK" else f"{r.name} OK (cbm, {why})", file=out)
        return 0
    chosen = [repos[n] for n in names] if names else list(repos.values())
    if stale:
        chosen = [r for r in chosen if cbm_state(r, rec.get(r.name))[0] != "OK"]
        if not chosen:
            print("every repo is indexed at its checkout's HEAD (cbm)", file=out)
            return 0
    try:
        with cbm.Session() as s:
            return max([_cbm_index_one(s, r, out) for r in chosen] or [0])
    except cbm.CbmError as exc:
        print(f"brain index: codebase-memory-mcp: {exc}", file=out)
        return 1


def _cbm_index_one(s: cbm.Session, r: codeindex.Repo, out) -> int:
    t0 = codeindex._clock()
    branch, sha, dirty, why = _head(r.path)
    if not why:
        try:
            got = cbm.index(s, r.path, r.name)
        except cbm.CbmError as exc:
            why = str(exc)
    if why:
        print(f"{r.name} FAILED (cbm, {codeindex._secs(t0)}): {why}", file=out, flush=True)
        return 1
    secs = round(codeindex._clock() - t0)
    cbm.save(r.name, {"project": r.project, "path": r.path.as_posix(), "branch": branch, "sha": sha, "dirty": dirty,
                      "indexed_at": faults.now().isoformat(timespec="seconds"), "seconds": secs,
                      "nodes": got.get("nodes"), "edges": got.get("edges"), "version": cbm.VERSION})
    note = "; with uncommitted changes (CBM reads the working tree)" if dirty else ""
    print(f"{r.name} OK (cbm, {secs} s, {branch}@{sha[:7]}, {got.get('nodes')} nodes, {got.get('edges')} edges){note}",
          file=out, flush=True)
    return 0


def cbm_health(repos: dict[str, codeindex.Repo], every: bool) -> tuple[int, str]:
    """(exit code, its line) of CBM in ``brain health code-index``: its settings off, and the repos it indexed (every
    declared repo when ``every``: it is the machine's code index) at their checkout's HEAD."""
    try:
        on = cbm.not_off(cbm.settings())
    except cbm.CbmError as exc:
        return 1, f"{codeindex.CHECK} cbm ERROR: {exc}"
    if on:
        return 1, (f"{codeindex.CHECK} cbm UNSAFE: its settings {', '.join(on)} are on (its UI, its watcher or its "
                   "auto-index start with a session); brain index --backend cbm sets them off")
    rec = cbm.read_record()
    checked = [r for r in repos.values() if every or r.name in rec]
    bad = [(r.name, *cbm_state(r, rec.get(r.name))) for r in checked]
    bad = [b for b in bad if b[1] != "OK"]
    if bad:
        word = "ERROR" if any(b[1] == "ERROR" for b in bad) else "STALE"
        return 1, (f"{codeindex.CHECK} cbm {word}: " + ", ".join(
            f"{n} ({'not indexed' if s == 'NOT INDEXED' else w})" for n, s, w in bad)
                   + "; brain index --backend cbm --stale reindexes " + ("it" if len(bad) == 1 else "them"))
    return 0, f"{codeindex.CHECK} cbm OK (settings off, {len(checked)} repo(s) at their checkout's HEAD)"


# --- cbm: brain impact on a worktree ---

def temp_name(folder: str, top: Path) -> str:
    """The temporary project a worktree is indexed under: the repo's name and a digest of the checkout's path."""
    digest = hashlib.sha1(str(top.resolve()).lower().encode("utf-8")).hexdigest()[:8]
    return f"{folder}-wt-{digest}"


def sweep(s: cbm.Session) -> list[str]:
    """Delete the temporary projects (``<repo>-wt-<digest>``) whose checkout is gone: one a run could not delete (it
    was killed, the server ended). The names deleted."""
    gone = [str(x.get("name")) for x in cbm.projects(s)
            if TEMP.search(str(x.get("name") or "")) and not Path(str(x.get("root_path") or "")).is_dir()]
    for name in gone:
        cbm.delete(s, name)
    return gone


def cbm_changes(top: Path, folder: str, base: str, depth: int) -> tuple[str, dict, str]:
    """(the temporary project's name, ``detect_changes``'s answer, '') for the checkout ``top`` against ``base``,
    else (.., {}, why not). The checkout is indexed in place (CBM's fast mode) and its index deleted after, the
    index failing or not, while the server answers; a temporary project left by an earlier run whose checkout is gone
    is deleted first (:func:`sweep`)."""
    name = temp_name(folder, top)
    try:
        with cbm.Session() as s:
            sweep(s)
            try:
                name = str(cbm.index(s, top, name, mode="fast").get("project") or name)   # CBM's own name for it
                return name, cbm.changes(s, name, base, depth), ""
            finally:
                try:
                    cbm.delete(s, name)
                except cbm.CbmError as exc:
                    print(f"brain impact: codebase-memory-mcp kept {name}: {exc}", file=sys.stderr)
    except cbm.CbmError as exc:
        return name, {}, f"codebase-memory-mcp: {exc}"


def _short(qn: str) -> str:
    return qn.rsplit(".", 1)[-1]


def symbols_of(answer: dict) -> tuple[list[dict], list[dict]]:
    """(the touched symbols, their callers) in brain impact's rows, from ``detect_changes``'s seeds and impacted; a
    file, module or folder node is not a symbol."""
    seeds = [x for x in answer.get("seeds") or [] if isinstance(x, dict) and x.get("qn")
             and str(x.get("label") or "") not in CONTAINERS]
    symbols = [{"id": str(x["qn"]), "name": _short(str(x["qn"])), "label": str(x.get("label") or ""),
                "path": str(x.get("file") or ""), "lines": [x.get("start"), x.get("end")]} for x in seeds]
    calls = [x for x in answer.get("impacted") or [] if isinstance(x, dict) and x.get("qn")]
    callers = [{"id": str(x["qn"]), "name": _short(str(x["qn"])), "label": str(x.get("label") or ""),
                "path": str(x.get("file") or ""), "callee": str(x.get("via_qn") or ""),
                "level": x.get("hop") if isinstance(x.get("hop"), int) else 0} for x in calls]
    return (sorted(symbols, key=lambda r: (r["path"], r["lines"][0] or 0, r["id"])),
            sorted(callers, key=lambda r: (r["level"], r["path"], r["id"])))


def truncated(answer: dict) -> bool:
    """True when ``detect_changes`` left some of its changes, seeds or impacted symbols out."""
    return bool(answer.get("truncated") or answer.get("seed_has_more") or answer.get("impacted_has_more")
                or answer.get("changed_has_more"))


def qualified(project: str, path: str, symbol: str) -> str:
    """CBM's qualified name of ``symbol`` in the file ``path``: the project, the path's folders and stem, the symbol,
    joined by dots."""
    stem = path.rsplit(".", 1)[0] if "." in path.rsplit("/", 1)[-1] else path
    return ".".join([project, *stem.split("/"), *symbol.split(".")])
