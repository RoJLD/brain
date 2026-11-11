"""The map of realisations (brain.modulemap): who realises each module of a store's registry and where, beside the
registry's document fields (brain.modules). Zero token.

A registry entry gains hand-written fields (``schemas/modules.schema.json``): ``wanted`` (the owner wants the module),
``capabilities`` (the engine's capabilities of ``tiers.yaml`` that realise it in a brain), ``depends_on`` and ``uses``
(its hard and soft dependencies, ids of the registry, classified from the documents' ``declared``), ``ai`` (a model),
``realized_by`` (each realisation: project, kind, what, paths, ref, licence, state, contract, ships_in, retire) and
``map_review`` (proposed by a session, or validated by the owner).

``brain modules --check`` validates an entry that carries ``realized_by`` or ``map_review``, and only such an entry (a
registry written before the map passes as before, whatever free fields it holds): its shape against the schema, the module ids it names, the capabilities
(``tiers.yaml``), the projects (the projects registry, read-only ones included), the paths at their ref when the
project's checkout is on this machine, a wanted module with neither a realisation nor an open item. It warns (never
fails) of a wanted module with no item done or open 90 days after its ``since``. The checks run on the store that
keeps the registry; the open and done items counted are those of every store that reads it (brain.modules.lookup).

The view (brain.modules.render) gains, when an entry carries the map: the realisations and their state, the map's
gaps (a wanted module with no realisation, a lab realisation with no target one, a product phase with no product
realisation) and the declared dependencies still to classify.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

from . import graph, modules, schema

MAP = ("wanted", "capabilities", "depends_on", "uses", "ai", "realized_by", "map_review")
KIND = "modules"   # the schema: schemas/modules.schema.json
TARGETS = ("product", "brain", "app")   # the kinds a lab realisation hands over to
PRODUCT_PHASE = re.compile(r"^(MVP|V\d)")   # a phase of the product's roadmap (MVP, V1, V1.5, V2...)


MARKS = ("realized_by", "map_review")   # the fields only the map writes: what makes an entry a map entry


def has_map(m: dict) -> bool:
    """An entry that carries the map: ``realized_by`` or ``map_review`` (:data:`MARKS`), names no free-form registry
    used before. The map's checks and view apply to it only; a hand entry whose own ``wanted``, ``uses`` or ``ai``
    means something else stays a hand entry, checked as before."""
    return any(k in m for k in MARKS)


def _ids(value) -> list[str]:
    return [str(x) for x in value] if isinstance(value, list) else []


def _realisations(m: dict) -> list[dict]:
    found = m.get("realized_by")
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []


def _live(m: dict) -> list[dict]:
    """The realisations not retired."""
    return [r for r in _realisations(m) if r.get("state") != "retired"]


def _shape(m: dict) -> list[str]:
    """What the schema refuses in ``m``; a realisation's unknown key is a newer brain's (an error in strict mode)."""
    s = schema.load(KIND)
    errors: list[str] = []
    unknown: list[tuple[str, str]] = []
    schema._validate(m, s, s, str(m["id"]), errors, unknown)
    for path, key in unknown:
        errors += schema.tolerate(f"{path}: unknown field {key!r}")
    return errors


def _capabilities() -> set[str]:
    from . import tiers
    return set(tiers.capabilities()[0])


def _projects(root: Path | None) -> tuple[set[str], dict[str, Path]]:
    """(the names of the projects registry, read-only ones included; {name: root} of those on this machine)."""
    from . import projects
    try:
        names = {str(n) for n in projects.raw(root)}
        roots = {p.name: p.root for p in projects.load(root).values()}
    except (OSError, ValueError, graph._yaml().YAMLError):
        return set(), {}
    return names, roots


CHECKED = ("partial", "built", "running")   # the states whose paths exist: a planned or retired one's may not


def _git(top: Path, *args: str) -> int | None:
    """git's exit code in ``top`` (its output unread, never decoded); None when git cannot run."""
    try:
        return subprocess.run(["git", "-C", str(top), *args], capture_output=True, timeout=30,
                              stdin=subprocess.DEVNULL).returncode
    except (OSError, subprocess.SubprocessError):
        return None


def _repo(top: Path, ref: str) -> str:
    """'' when ``top`` is in a git repository where ``ref`` is a commit, else why the paths cannot be checked."""
    if _git(top, "rev-parse", "--git-dir") != 0:
        return "not a git repository"
    return "" if _git(top, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") == 0 else f"ref {ref} is no commit"


def _path_at(top: Path, ref: str, path: str) -> bool:
    """Whether ``path`` (relative to ``top``, a project's root, maybe a folder of its repo) exists at ``ref``."""
    return _git(top, "cat-file", "-e", f"{ref}:./{path.replace(chr(92), '/').strip('/')}") == 0


def _check_realisation(mid: str, i: int, r: dict, names: set[str], roots: dict[str, Path]) -> list[str]:
    """A realisation's project (registered) and its paths at their ref, when the project's root is on this machine
    and the realisation's state says they exist (:data:`CHECKED`), or its ref is given."""
    project, out = str(r.get("project") or ""), []
    where = f"{mid}.realized_by[{i}] ({project or '?'})"
    if project and names and project not in names:
        out.append(f"{where}: project {project} is not in the projects registry")
    top, paths = roots.get(project), r.get("paths") if isinstance(r.get("paths"), list) else []
    if top is None or not top.is_dir() or not paths or (r.get("state") not in CHECKED and not r.get("ref")):
        return out   # no checkout here, no path, or not built yet: nothing to check
    ref = str(r.get("ref") or "HEAD")
    why = _repo(top, ref)
    if why:
        return out + [f"{where}: its paths cannot be checked in {top}: {why}"]
    return out + [f"{where}: path {p} is not in {project} at {ref}" for p in paths if not _path_at(top, ref, str(p))]


def _check_ids(mid: str, m: dict, known: set[str], caps: set[str]) -> list[str]:
    out = [f"{mid}: {key} {d} is not in {modules.REGISTRY}" for key in ("depends_on", "uses")
           for d in _ids(m.get(key)) if d not in known]
    out += [f"{mid}: depends_on {d} is also in uses" for d in _ids(m.get("depends_on")) if d in _ids(m.get("uses"))]
    out += [f"{mid}: capability {c} is not in tiers.yaml" for c in _ids(m.get("capabilities")) if c not in caps]
    return out


def readers(store: Path, root: Path | None) -> list[Path]:
    """The stores whose module checks read ``store``'s registry: itself, and those that read it through config.json
    ``modules.store`` (brain.modules.lookup)."""
    out = [store]
    if root is None:
        return out
    from . import crossstore, projects
    try:
        found = crossstore.stores(list(projects.load(root).values()))
    except (OSError, ValueError, graph._yaml().YAMLError):
        return out
    mine = (store / modules.REGISTRY).resolve()
    for _, s in found:
        f = modules.registry_file(s, root)
        if s.resolve() != store.resolve() and f is not None and f.resolve() == mine:
            out.append(s)
    return out


def built(store: Path, root: Path | None) -> dict[str, tuple[int, int]]:
    """{module: (items done, items open)} with it as primary, over every store that reads the registry."""
    out: dict[str, tuple[int, int]] = {}
    for s in readers(store, root):
        for n in modules.items(s):
            mod = str((n.get("props") if isinstance(n.get("props"), dict) else {}).get("module") or "")
            d, o = out.get(mod, (0, 0))
            out[mod] = (d + (n.get("status") == "done"), o + (n.get("status") in modules.OPEN))
    return out


def problems(store: Path, root: Path | None = None) -> list[str]:
    """What ``brain modules --check`` refuses in the map (exit 1), on the store that keeps the registry: the entries
    that carry it only (:func:`has_map`)."""
    if not (store / modules.REGISTRY).is_file():
        return []   # a store that reads another's registry: that store's check says it, once
    reg = modules.registry(store, root) or []
    mapped = [m for m in reg if has_map(m)]
    if not mapped:
        return []
    known, caps, (names, roots) = {str(m["id"]) for m in reg}, _capabilities(), _projects(root)
    counts, out = built(store, root), []
    for m in mapped:
        mid = str(m["id"])
        out += _shape(m) + _check_ids(mid, m, known, caps)
        for i, r in enumerate(_realisations(m)):
            out += _check_realisation(mid, i, r, names, roots)
        if m.get("wanted") is True and not _live(m) and not counts.get(mid, (0, 0))[1]:
            out.append(f"{mid}: wanted, with no realisation and no open item that builds it")
    return list(dict.fromkeys(out))


def warnings(store: Path, root: Path | None = None, today: date | None = None) -> list[str]:
    """What ``brain modules --check`` and brain check warn of, never a failure: a wanted module with no item done or
    open 90 days (:data:`brain.modules.DORMANT_DAYS`) after its ``since``: to put back to sleep."""
    if not (store / modules.REGISTRY).is_file():
        return []
    today, counts, out = today or date.today(), built(store, root), []
    for m in modules.registry(store, root) or []:
        since = modules._day(m.get("since"))
        exists = any(r.get("state") in CHECKED for r in _live(m))
        if m.get("wanted") is not True or since is None or any(counts.get(str(m["id"]), (0, 0))) or exists:
            continue   # not wanted, no day, something done or open, or a realisation that exists
        if today >= since + timedelta(days=modules.DORMANT_DAYS):
            out.append(f"{m['id']}: wanted since {since}, no item done or open in {modules.DORMANT_DAYS} days: "
                       "dormant, to put back to sleep")
    return out


# --- the view ---

def _row(mid: str, m: dict, r: dict | None) -> str:
    cell = modules._cell
    want = ("yes" if m["wanted"] else "no") if isinstance(m.get("wanted"), bool) else "-"
    if r is None:
        return f"| {mid} | {cell(m.get('name', ''))} | {want} | - | - | - | - | - | {m.get('map_review', '-')} |"
    return (f"| {mid} | {cell(m.get('name', ''))} | {want} | {cell(r.get('project', ''))} | {cell(r.get('kind', ''))}"
            f" | {cell(r.get('what', '')) or '-'} | {cell(r.get('state', ''))} | {cell(r.get('ships_in', '')) or '-'}"
            f" | {m.get('map_review', '-')} |")


def _gaps(mapped: list[dict]) -> list[str]:
    out = []
    for m in mapped:
        mid, kinds = str(m["id"]), {r.get("kind") for r in _live(m) if isinstance(r.get("kind"), str)}
        if m.get("wanted") is True and not kinds:
            out.append(f"- {mid}: wanted, no realisation")
        if "lab" in kinds and not kinds & set(TARGETS):
            out.append(f"- {mid}: a lab realisation, no target realisation (product, brain or app)")
        if PRODUCT_PHASE.match(str(m.get("phase") or "")) and "product" not in kinds and m.get("status") != "proposed":
            out.append(f"- {mid}: product phase {m['phase']}, no product realisation")
    return out or ["None."]


def _unclassified(mapped: list[dict]) -> list[str]:
    out = []
    for m in mapped:
        left = [d for d in _ids(m.get("declared")) if d not in _ids(m.get("depends_on")) + _ids(m.get("uses"))]
        if left:
            out.append(f"- {m['id']}: {', '.join(left)} (declared, counted soft until classified)")
    return out or ["None."]


def view_lines(reg: list[dict]) -> list[str]:
    """The view's sections on the map; none for a registry with no entry that carries it (its view is unchanged)."""
    mapped = [m for _, m in modules._order([m for m in reg if has_map(m)])]   # by brick, then id
    if not mapped:
        return []
    review = sum(1 for m in mapped if m.get("map_review") == "proposed")
    out = ["", "## Realisations", "",
           f"{len(mapped)} module(s) carry the map, {review} proposed and waiting on the owner's review.", "",
           "| Module | Name | Wanted | Project | Kind | What | State | Ships in | Review |",
           "|---|---|---|---|---|---|---|---|---|"]
    for m in mapped:
        rows = _realisations(m) or [None]
        out += [_row(str(m["id"]), m, r) for r in rows]
    out += ["", "## Map gaps", ""] + _gaps(mapped)
    out += ["", "## Dependencies to classify", ""] + _unclassified(mapped)
    return out


def data(reg: list[dict]) -> list[dict]:
    """brain modules --json's ``map``: each entry that carries the map, its map fields."""
    return [{"id": m["id"], **{k: m[k] for k in MAP if k in m}} for m in reg if has_map(m)]
