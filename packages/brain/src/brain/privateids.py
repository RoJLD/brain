"""The personal graph's ids and ADR titles that a public repo refuses (wi-brain-public-private-ids): the ``graph``
check of ``brain check --public`` and of the public commit guard (brain.public, brain.guards). Zero token: the stores'
node files are read as YAML, the lines matched by one regex and set lookups.

What is refused, in the lines of a public repo (its files, the lines its commits add, their messages):

- an id of the personal graph, of the shapes ``wi-``, ``adr-``, ``feat-``, ``ddr-``, ``spec-`` and ``les-``, that a
  store of the registry holds (brain.crossstore: every store of every registered project on this machine):

  - an ADR's or a DDR's id, whatever its project: the owner's decisions and answers stay private;
  - any other id of a project that is not the public repo's own: the projects with a repo named as the public repo
    (``acme/engine``: a project with a repo ``engine``), whose items, features, specs and lessons the engine cites on
    purpose (its CHANGELOG, its docstrings, FEATURES.md);

- an ADR's title, of 4 words or more, matched on its first 8 words (or all of them when shorter), whatever the case
  and the punctuation between the words: a title copied whole, or cut where a view truncates it.

An id that no store holds passes (a test's invented ``adr-2026-01-01-x``), as does a file under ``public.allow``; an
id followed by a file's extension (``adr-x.md``) is the id. The index is read only for a repo of ``public.repos``
(brain.public.rules with its slug): a render or a PR body checked without its repo checks no graph id.
The ids are not part of the stamp's key (brain.public.rules_hash): a new item every few minutes would void every
stamp, and a line checked before an id existed cannot hold it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PREFIXES = ("wi", "adr", "feat", "ddr", "spec", "les")
ALWAYS = ("ADR", "DDR")   # refused whatever their project
TOKEN = re.compile(r"(?<![A-Za-z0-9_-])((?:" + "|".join(PREFIXES) + r")-[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?)")
WORD = re.compile(r"\w+")
MIN_WORDS = 4
WINDOW = 8


@dataclass
class Index:
    ids: dict[str, str] = field(default_factory=dict)                   # id -> what the finding says
    titles: dict[int, dict[tuple, str]] = field(default_factory=dict)   # window -> {its words: the ADR's id}
    firsts: set[str] = field(default_factory=set)                       # the first words of the windows
    own: list[str] = field(default_factory=list)                        # the public repo's own projects
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.ids or self.titles)


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD.findall(text)]


def own_projects(loaded: dict, slug: str) -> list[str]:
    """The projects of ``loaded`` with a repo (by name or folder) named as the public repo ``owner/name``."""
    from . import projects
    name = slug.rsplit("/", 1)[-1].lower()
    out = []
    for pname, p in loaded.items():
        try:
            repos = projects.repos_of(p)
        except (ValueError, OSError):   # RepoError, a path on another drive: not this repo's project
            continue
        if any(name in (r.name.lower(), r.folder.lower()) for r in repos):
            out.append(pname)
    return out


_CACHE: dict[tuple, Index] = {}


def _stamp(stores: list) -> tuple:
    """What the index of ``stores`` depends on: each nodes file's path, size and time (a commit guard that runs
    twice in one process reads them once)."""
    out = []
    for _, store in stores:
        for f in sorted((Path(store) / "nodes").glob("*.yaml")):
            try:
                st = f.stat()
                out.append((str(f), st.st_size, st.st_mtime_ns))
            except OSError:
                out.append((str(f), -1, -1))
    return tuple(out)


def index(root: Path, slug: str) -> Index:
    """The ids and ADR titles a public repo ``slug`` refuses, read from every store of the registry at ``root``;
    kept for this process while no nodes file changes."""
    from . import crossstore, projects
    try:
        loaded = projects.load(root)
        stores = crossstore.stores(list(loaded.values()))
    except Exception as exc:   # noqa: BLE001 - an unreadable registry: said in the check's notes
        return Index(errors=[f"the personal graph's ids are not checked: the registry cannot be read ({exc})"])
    key = (str(root), slug.lower(), _stamp(stores))
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = _build(loaded, stores, slug)
    return _CACHE[key]


def _build(loaded: dict, stores: list, slug: str) -> Index:
    from . import graph
    idx = Index()
    idx.own = own_projects(loaded, slug) if slug else []
    for label, store in stores:
        project = label.split(":", 1)[0]
        try:
            nodes = graph.node_index(store)
        except Exception as exc:   # noqa: BLE001 - a store that does not load: said, the others still read
            idx.errors.append(f"the ids of {label} are not checked: {type(exc).__name__}")
            continue
        for nid, (_, node) in nodes.items():
            kind = str(node.get("type") or "")
            if kind == "ADR" and isinstance(node.get("title"), str):
                w = words(node["title"])
                if len(w) >= MIN_WORDS:
                    key = tuple(w[:WINDOW])
                    idx.titles.setdefault(len(key), {}).setdefault(key, nid)
                    idx.firsts.add(key[0])
            if not TOKEN.fullmatch(nid):
                continue
            if kind in ALWAYS:
                idx.ids.setdefault(nid, f"the private {kind} {nid} ({label})")
            elif project not in idx.own:
                idx.ids.setdefault(nid, f"the private id {nid} ({label}, not this repo's project)")
    return idx


def _held(token: str, idx: Index) -> str:
    """The id of ``idx`` that ``token`` is, or that it starts with before a ``.`` (a file name: ``adr-x.md``)."""
    while token:
        if token in idx.ids:
            return token
        token = token.rpartition(".")[0]
    return ""


def find(line: str, idx: Index) -> list[str]:
    """What ``line`` holds of ``idx``: the private ids, then the ADR titles, each said once."""
    out = [idx.ids[nid] for m in TOKEN.finditer(line) if (nid := _held(m.group(1), idx))]
    if idx.titles:
        w = words(line)
        for i, first in enumerate(w):
            if first not in idx.firsts:
                continue
            for k, keys in idx.titles.items():
                nid = keys.get(tuple(w[i:i + k])) if i + k <= len(w) else None
                if nid:
                    out.append(f"the title of the private ADR {nid}")
    return list(dict.fromkeys(out))
