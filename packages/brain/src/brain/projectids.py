"""Project ids, the doctrine (spec-brain-project-ids: ID-1 to ID-3): a project's registry key is its **id**, frozen at
birth; its name is a label; the names it had are aliases that resolve to it; a project that ends leaves a tombstone.

- **The id.** The key of an entry of ``projects.yaml`` (and of a container of ``scopes.yaml``): kebab-case from a
  letter, 2 to 40 characters (:data:`ID`), unique across projects, containers and every alias, never reused once
  retired (the entry stays, as a tombstone). A rename changes ``title`` or ``label``, never the key: records, ledgers,
  ``BRAIN_HOME`` files and ``--project`` lines keep naming it. A key that is not kebab-case today is a warning, never an
  error: it is frozen as it is (``brain project add`` mints kebab-case ones only).
- **The identity keys** (``brain projects --keys``): ``aliases``, the names the project had or people type (a list of
  ids of the same grammar); ``label``, a short display name (``title`` stays the one line saying what it is);
  ``status``, ``active`` (the default) or the fate of a project that ended (:data:`STATUSES`: ``merged``, ``split``,
  ``became-process``, ``archived``). A container of ``scopes.yaml`` takes ``aliases`` too.
- **A tombstone** (a ``status`` other than ``active``): the entry of a project that ended, kept so that its id and
  aliases are never reused and an old record still resolves. It holds :data:`TOMBSTONE_KEYS` only, no root, store or
  ledger: no command loads it (brain.projects); ``brain check --all`` refuses one that holds a live key. A status this
  engine does not know is a note (strict, CI: an error) and the entry is not loaded either: the key narrows. Its
  ``lineage`` (merged_into, split_into, became) is wi-brain-project-lineage's.
- **An alias resolves with a notice**: ``--project OLD`` and a scope reference run as the project's id and say so on
  stderr (:func:`canonical`); brain check --all refuses an alias that is another node's id or alias (:func:`check`).
- **Private stays private**: the aliases and the label of a private project join the deny terms with its key
  (brain.scopes.private_terms, brain.denylist).
- **A node id is a birth mark** (ID-3): ``wi-<slug>-...`` says where an item was born, never where it lives; no code
  reads a project from an id (a test of the engine's sources holds it).
- **A repo's** ``name:`` **is its frozen id** (:func:`repo_name_warnings`): a repo without one is named after its
  folder, and brain check --all warns when its project's graph names a repo token no registered repo answers to while
  that repo has no ``name:`` (a clone in another folder: give it the name the ids use).

Zero token: the registry and the tree are read as files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ID = re.compile(r"[a-z][a-z0-9-]{1,39}\Z")
ACTIVE = "active"
STATUSES = (ACTIVE, "merged", "split", "became-process", "archived")
#: What a tombstone holds: its names, its place and its class (the deny feed reads it); access narrows, so it may stay.
TOMBSTONE_KEYS = {"title", "label", "status", "aliases", "parent", "classes", "access"}
#: The identity keys every entry of the registry may hold, whatever its kind (a project, a read-only one, a mount, a
#: notes home); ``status`` is a project's (a tombstone is one).
NAME_KEYS = ("aliases", "label")
#: The prefixes of the ids that name a repo (``code:<repo>:...``), read by :func:`repo_name_warnings`.
REPO_IDS = re.compile(r"^(?:code|doc|test):([^:]+):")


def aliases(entry) -> list[str]:
    """The aliases an entry declares, as strings (an entry of another shape: none; check() says why)."""
    value = entry.get("aliases") if isinstance(entry, dict) else None
    return [a for a in value if isinstance(a, str) and a] if isinstance(value, list) else []


def label(entry) -> str:
    value = entry.get("label") if isinstance(entry, dict) else None
    return value if isinstance(value, str) else ""


def status(entry) -> str:
    """An entry's status: ``active`` when it declares none."""
    value = entry.get("status", ACTIVE) if isinstance(entry, dict) else ACTIVE
    return value if isinstance(value, str) else repr(value)


def is_tombstone(entry) -> bool:
    """The entry of a project that ended: a ``status`` other than ``active``, known or not (the key narrows: a status
    this engine does not know is never read as a live project)."""
    return isinstance(entry, dict) and "status" in entry and entry["status"] != ACTIVE


def why_unloaded(name: str, entry) -> str:
    """What :func:`brain.projects.unloaded` says of a tombstone."""
    st = status(entry)
    if st not in STATUSES:
        return (f"{name!r} is not loaded: its status {st!r} is not one this engine knows ({', '.join(STATUSES)}): "
                "a newer brain's? it is read as a tombstone")
    return (f"{name!r} is a tombstone (status {st}): the project ended; its id and aliases stay reserved and its "
            "records keep naming it, but no command loads it")


# --- the names in use: ids and aliases, across the registry and the scope tree ---

def taken(registry: dict, containers: dict) -> dict[str, str]:
    """{every name in use: what holds it}: each registry key and container id (``project X``, ``scope X``), each
    alias (``an alias of project X``): what a new project's id may not be (brain project add). The first holder wins;
    :func:`check` reports a second one."""
    out: dict[str, str] = {}
    for kind, nodes in (("project", registry), ("scope", containers)):
        for nid in nodes:
            out.setdefault(str(nid), f"{kind} {nid}")
    for kind, nodes in (("project", registry), ("scope", containers)):
        for nid, entry in nodes.items():
            for a in aliases(entry):
                out.setdefault(a, f"an alias of {kind} {nid}")
    return out


def alias_map(registry: dict, containers: dict | None = None) -> dict[str, str]:
    """{alias: the id it resolves to}. An alias that is an id, or that two nodes declare, resolves to none
    (:func:`check` refuses both): never a guess between two projects."""
    nodes = {**(containers or {}), **registry}
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    for nid, entry in nodes.items():
        for a in dict.fromkeys(aliases(entry)):
            seen[a] = seen.get(a, 0) + 1
            out[a] = str(nid)
    return {a: nid for a, nid in out.items() if seen[a] == 1 and a not in nodes}


def notice(alias: str, nid: str, what: str = "--project") -> str:
    return f"brain: note: {what} {alias}: {alias!r} is an alias of {nid!r} (the project's id, frozen): running as {nid}"


def canonical(name: str | None, root: Path | None = None) -> str | None:
    """The registry key ``name`` names: itself when it is a key (or names nothing: the caller says so), else the id
    its alias resolves to, with a notice on stderr. A registry that cannot be read leaves ``name`` as given (the
    command's own read reports it)."""
    if not name:
        return name
    from . import projects
    try:
        reg = projects.raw(root)
    except Exception:  # noqa: BLE001 - a registry that cannot be read is projects.check's to report, never raised here
        return name
    if name in reg:
        return name
    nid = alias_map(reg).get(name)
    if nid is None:
        return name
    print(notice(name, nid), file=sys.stderr)
    return nid


# --- the check (brain check --all, through brain.scopes.check) ---

def check(registry: dict, containers: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings) of the names: an alias of the wrong shape, an alias that is its own id, another node's id
    or another node's alias, a label that is not one line; an id that is not kebab-case is a warning (frozen as it
    is). A tombstone's keys are brain.projects.check's."""
    errors: list[str] = []
    warnings: list[str] = []
    holders: dict[str, str] = {}
    for kind, nodes in (("project", registry), ("scope", containers)):
        for nid in nodes:
            holders.setdefault(str(nid), f"{kind} {nid}")
    for kind, nodes in (("project", registry), ("scope", containers)):
        for nid, entry in nodes.items():
            nid = str(nid)
            where = f"{kind} {nid}"
            if kind == "project" and not ID.match(nid) and nid != "global":
                warnings.append(f"{where}: its id is not kebab-case from a letter, 2 to 40 characters ({ID.pattern}): "
                                "an id is frozen, so it stays as it is (a new project takes one; brain projects --keys)")
            if not isinstance(entry, dict):
                continue
            errors += _alias_errors(where, nid, entry, holders)
            if "label" in entry and (not isinstance(entry["label"], str) or not entry["label"].strip()
                                     or "\n" in entry["label"]):
                errors.append(f"{where}: label is one line of text (a short display name)")
    return errors, warnings


def _alias_errors(where: str, nid: str, entry: dict, holders: dict[str, str]) -> list[str]:
    value = entry.get("aliases")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(a, str) for a in value):
        return [f"{where}: aliases is a list of names (ids of the same grammar: kebab-case from a letter)"]
    errors = []
    for a in value:
        if a == "global":
            errors.append(f"{where}: alias {a!r} is the tree's root")
        elif not ID.match(a):
            errors.append(f"{where}: alias {a!r} is not kebab-case from a letter, 2 to 40 characters")
        elif a == nid:
            errors.append(f"{where}: alias {a!r} is its own id")
        elif holders.get(a) == f"an alias of {where}":
            errors.append(f"{where}: alias {a!r} is listed twice")
        elif a in holders:
            errors.append(f"{where}: alias {a!r} is {holders[a]} already: an id or an alias is never reused (two "
                          "nodes answering to one name would route a --project to the wrong store)")
        else:
            holders[a] = f"an alias of {where}"
    return errors


def tombstone_errors(where: str, entry: dict) -> list[str]:
    """A tombstone holds :data:`TOMBSTONE_KEYS` only: a root, a store or a ledger would make a project that ended
    live again; its status is a string (an unknown one is a note, strict an error)."""
    from . import schema
    errors = []
    extra = sorted(set(map(str, entry)) - TOMBSTONE_KEYS)
    if extra:
        errors.append(f"{where}: a tombstone (status {status(entry)}) holds {', '.join(sorted(TOMBSTONE_KEYS))} "
                      f"only, not {', '.join(extra)} (a live key: the project ended; remove them, or set status: "
                      "active)")
    st = entry.get("status")
    if not isinstance(st, str):
        errors.append(f"{where}: status is one of {', '.join(STATUSES)}")
    elif st not in STATUSES:
        errors += schema.tolerate(f"{where}: status {st!r} is not one of {', '.join(STATUSES)}")
    if "title" in entry and not isinstance(entry["title"], str):
        errors.append(f"{where}: title is a string")
    return errors


# --- a repo's name: is its frozen id (folds wi-brain-repo-name-portable's warning) ---

def repo_name_warnings(projs, root: Path | None = None) -> list[str]:
    """For each loaded project that spans a repo without ``name:`` (named after its folder), the repo tokens its
    stores' ids use (``code:<repo>:``, ``doc:<repo>:``, ``test:<repo>:``) that no registered repo answers to: a clone
    in another folder than the one the ids were made in. One warning per such repo, naming the tokens."""
    from . import projects
    known = projects.repo_tokens(root)
    out = []
    for p in projs:
        nameless = _nameless(p)
        if not nameless:
            continue
        used: set[str] = set()
        for store in projects.stores_of(p):
            if (store / "nodes").is_dir():
                used |= {m.group(1).lower() for nid in projects.node_ids(store) if (m := REPO_IDS.match(nid))}
        stray = sorted(used - known)
        if not stray:
            continue
        for path, folder in nameless:
            out.append(f"project {p.name}: its repo {path} has no name: and is named after its folder ({folder}), "
                       f"while its graph's ids name {', '.join(stray[:3])}{' ...' if len(stray) > 3 else ''}: a clone "
                       "in another folder? give the repo name: <the name its ids use> (a repo's name is its frozen id)")
    return out


def _nameless(p) -> list[tuple[str, str]]:
    """(path as declared, folder name) of each repo of ``p`` without ``name:``: its ``repos:`` entries, or its root
    when it declares none (the default); [] for a project that shares its root (its repo is its owner's)."""
    from . import projects
    if p.shares_root_with:
        return []
    declared = p.repos if isinstance(p.repos, list) else []
    if not declared:
        return [(".", projects._repo_folder(p.root).lower())] if p.root.is_dir() else []
    out = []
    for e in declared:
        e = {"path": e} if isinstance(e, str) else e
        if isinstance(e, dict) and isinstance(e.get("path"), str) and not e.get("name"):
            path = projects._resolve_root(e["path"], p.root)
            out.append((e["path"], projects._repo_folder(path).lower() if path.is_dir() else Path(e["path"]).name))
    return out
