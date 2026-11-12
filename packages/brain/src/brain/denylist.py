"""The deny terms derived from the brain's own registries (wi-brain-public-deny-derived): what config.json
``public.deny`` holds by hand, the public check (brain.public), the commit guard (brain.guards) and brain boundary's
readiness also refuse from the day a machine, a project, a person, a spec or a module is declared. Zero token: the
registries are read as files.

The sources (``public.derive`` picks them, a list of these names; absent, all of them; ``[]``, none):

- ``hosts``: the machines of config.json ``hosts``, by name, and their ``aliases``;
- ``people``: config.json ``identity.owner`` and ``identity.display_name``, and members.yaml's people (``name``,
  ``person_id``);
- ``projects``: the projects registry's names (read-only ones too) and each project's repos, by name and by its main
  checkout's folder (brain.projects.repos_of); a project rooted in the brain's own repo (its root, or another folder,
  worktree or main checkout of the same git repo) gives its repos, not its name
  (a brain is often named as its engine: ``brain``);
- ``specs``: the file names, without ``.md``, under the brain's ``docs/specs`` (a spec's path is its name);
- ``modules``: the module registries of the brain's own stores (brain.modules), each entry's ``name``, and its ``id``
  when it is 4 characters or more (a short code such as ``D7`` or ``P2`` names nothing and is everywhere).

A derived term joins the hand list's category (hosts, people, repos for projects and modules, paths for specs), once
whatever its case. Never derived, in any spelling: a term shorter than 3 characters; the engine's own names
(``brain``, ``research-graph``); the owner or the name of a repo of ``public.repos``; a term of
``public.public_names`` (``{name: reason}``: a registry's name that is public, a third-party tool a project reads).
A registry that cannot be read (a YAML error, a conflict marker) raises :class:`DeriveError`: config.unexpected then
makes the public and secrets guards refuse, and brain check --public stops (exit code 2), never a shorter list.

:func:`undenied` is what ``brain check`` warns about: a declared private name that no deny list holds, which happens
when ``public.derive`` leaves its source out and the hand list does not name it in every spelling (``acme``
holds ``acme-lab``, not ``acme_lab``).

A term matches in every spelling of its separators (brain.boundary.term_regex): ``a-b``, ``a_b``, ``a b`` and ``ab``
are one term, so a hyphenated project name also refuses its Python module's name.
"""

from __future__ import annotations

from pathlib import Path

from . import config

SOURCES = ("hosts", "people", "projects", "specs", "modules")
CATEGORY = {"hosts": "hosts", "people": "people", "projects": "repos", "specs": "paths", "modules": "repos"}
MIN_LEN = 3
MIN_ID = 4
SPECS = "docs/specs"


def _public(cfg: config.Config) -> dict:
    return cfg.data.get("public") if isinstance(cfg.data.get("public"), dict) else {}


def sources(cfg: config.Config) -> tuple[str, ...]:
    """The sources ``public.derive`` picks (all when absent, unknown names passed over)."""
    want = _public(cfg).get("derive")
    if not isinstance(want, list):
        return SOURCES
    return tuple(s for s in SOURCES if s in want)


def public_names(cfg: config.Config) -> dict[str, str]:
    """public.public_names: {name: reason}, the registries' names that are public and never derived."""
    v = _public(cfg).get("public_names")
    return {str(k): str(x) for k, x in v.items()} if isinstance(v, dict) else {}


class DeriveError(Exception):
    """A registry public.derive reads cannot be read: the guards refuse (config.unexpected), the check stops."""


ENGINE_NAMES = ("brain", "research-graph")   # the engine's own names: a brain's repo is often named as its engine


def publishing(cfg: config.Config, names: list[str]) -> config.Config:
    """A copy of ``cfg`` whose public.public_names also hold ``names``: what a render for a public repo checks against
    (``brain reference --public --repo R``: R's name is the published repo's, not a private one)."""
    import copy
    data = copy.deepcopy(cfg.data)
    pub = data.setdefault("public", {}) if isinstance(data.get("public", {}), dict) else {}
    own = pub.get("public_names") if isinstance(pub.get("public_names"), dict) else {}
    pub["public_names"] = {**own, **{n: "the repo this render publishes" for n in names if n}}
    return config.Config(cfg.file, cfg.root, data, cfg.error)


def _key(t: str) -> str:
    """A name with its separators dropped, lowercased: one key for every spelling."""
    return "".join(t.replace("_", "-").replace(" ", "-").split("-")).lower()


def _never(cfg: config.Config) -> set[str]:
    out = {_key(k) for k in public_names(cfg)} | {_key(n) for n in ENGINE_NAMES}
    for r in _public(cfg).get("repos") or []:
        if isinstance(r, str):
            out.update(_key(p) for p in r.split("/") if p)
    return out


def _yaml(f: Path):
    """``f`` read as YAML; DeriveError when it cannot be (a YAML error, a conflict marker)."""
    from . import graph
    try:
        return graph.load_yaml_file(f)
    except Exception as exc:   # noqa: BLE001 - any failure to read a registry is a reason to refuse, said as one
        raise DeriveError(f"{f.name} cannot be read ({type(exc).__name__})") from exc


def _hosts(cfg: config.Config) -> list[str]:
    hosts = cfg.data.get("hosts") if isinstance(cfg.data.get("hosts"), dict) else {}
    out = []
    for name, facts in hosts.items():
        out.append(str(name))
        aliases = facts.get("aliases") if isinstance(facts, dict) else None
        out += [a for a in aliases or [] if isinstance(a, str)] if isinstance(aliases, list) else []
    return out


def _people(cfg: config.Config) -> list[str]:
    ident = cfg.data.get("identity") if isinstance(cfg.data.get("identity"), dict) else {}
    out = [ident[k] for k in ("owner", "display_name") if isinstance(ident.get(k), str)]
    f = (cfg.file.parent if cfg.file else cfg.root) / "members.yaml"
    if f.is_file():
        data = _yaml(f)
        if data is not None and not isinstance(data, dict):
            raise DeriveError(f"{f.name} is a {type(data).__name__}, not a mapping")
        people = data.get("people") if isinstance(data, dict) else None
        for p in people if isinstance(people, list) else []:
            if isinstance(p, dict):
                out += [p[k] for k in ("name", "person_id") if isinstance(p.get(k), str)]
    return out


def _own_root(root: Path, cfg: config.Config) -> bool:
    """Whether a project's ``root`` is the brain's own: the folder of its config.json, or a folder of the same git repo
    (a worktree of the brain and its main checkout are one brain: a registry read from one and a config.json from the
    other still agree)."""
    from . import paths
    if root.resolve() == cfg.root.resolve():
        return True
    mine = paths.main_checkout(cfg.root)
    return mine is not None and root.is_dir() and paths.main_checkout(root) == mine


def _projects(cfg: config.Config) -> list[str]:
    from . import projects
    reg = projects.registry_file(cfg.root)
    if reg is not None and reg.is_file():
        data = _yaml(reg)
        if data is not None and not isinstance(data, dict):
            raise DeriveError(f"{reg.name} is a {type(data).__name__}, not a mapping")
    try:
        loaded = projects.load(cfg.root)
        names = [n for n, p in loaded.items() if not _own_root(p.root, cfg)]
        names += list(projects.readonly(cfg.root))
    except Exception as exc:   # noqa: BLE001 - any failure to read the registry is a reason to refuse
        raise DeriveError(f"the projects registry cannot be read ({type(exc).__name__}: {exc})") from exc
    out = list(names)
    for p in loaded.values():
        try:
            out += [t for r in projects.repos_of(p) for t in (r.name, r.folder) if t]
        except (ValueError, OSError):   # RepoError, a path on another drive: the project's name is still denied
            pass
    return out


def _specs(cfg: config.Config) -> list[str]:
    d = cfg.root / SPECS
    return sorted(f.stem for f in d.rglob("*.md")) if d.is_dir() else []


def _modules(cfg: config.Config) -> list[str]:
    from . import modules, projects
    out: list[str] = []
    try:
        stores = projects.for_root(cfg.root).stores
    except Exception as exc:   # noqa: BLE001 - any failure to read the registry is a reason to refuse
        raise DeriveError(f"the projects registry cannot be read ({type(exc).__name__}: {exc})") from exc
    seen: set[Path] = set()
    for store in stores:
        f = modules.registry_file(store, cfg.root)
        if f is None or f.resolve() in seen:
            continue
        seen.add(f.resolve())
        data = _yaml(f)
        if data is not None and not isinstance(data, list):
            raise DeriveError(f"{f.name} is a {type(data).__name__}, not a list")
        for m in data or []:
            if not (isinstance(m, dict) and m.get("id")):
                continue
            if isinstance(m.get("name"), str):
                out.append(m["name"])
            if len(str(m["id"])) >= MIN_ID:
                out.append(str(m["id"]))
    return out


READERS = {"hosts": _hosts, "people": _people, "projects": _projects, "specs": _specs, "modules": _modules}


def declared(cfg: config.Config, picked: tuple[str, ...] = SOURCES) -> list[tuple[str, str]]:
    """(source, name) of every private name the registries of ``picked`` declare, once each per source; the names
    never derived are left out. DeriveError when one of them cannot be read."""
    never = _never(cfg)
    out: list[tuple[str, str]] = []
    for src in SOURCES:
        if src not in picked:
            continue
        seen: set[str] = set()
        for t in READERS[src](cfg):
            t = t.strip()
            if len(t) < MIN_LEN or _key(t) in never or t.lower() in seen:
                continue
            seen.add(t.lower())
            out.append((src, t))
    return out


def terms(cfg: config.Config) -> list[tuple[str, str]]:
    """(category, term) derived from the sources public.derive picks; DeriveError when one cannot be read."""
    return [(CATEGORY[src], t) for src, t in declared(cfg, sources(cfg))]


def spellings(name: str) -> list[str]:
    """``name`` with its separators (``-``, ``_``, a space) in each spelling, none included."""
    from . import boundary
    parts = [p for p in boundary.SEPARATORS.split(name) if p]
    return list(dict.fromkeys(sep.join(parts) for sep in ("-", "_", " ", ""))) if len(parts) > 1 else [name]


def undenied(cfg: config.Config) -> list[tuple[str, str]]:
    """(source, name) of the declared private names no deny list holds in every spelling (a term of public.deny, the
    derived ones and the scope tree's): what brain check warns about. A name's source that cannot be read is
    passed over here (config.unexpected names it)."""
    from . import boundary
    held = [boundary.term_regex(t) for _, t in config.deny_terms(cfg)]
    out = []
    for src in SOURCES:
        try:
            names = declared(cfg, (src,))
        except DeriveError:
            continue
        out += [(s, t) for s, t in names
                if not all(any(rx.search(v.replace("\\", "/")) for rx in held) for v in spellings(t))]
    return out


def check_lines(root: Path | None = None) -> list[str]:
    """brain check's warnings in a brain's own root that publishes (config.json public.repos): one per declared
    private name no deny list holds; [] for a brain with no public repo."""
    cfg = config.load(root)
    pub = _public(cfg)
    if not (isinstance(pub.get("repos"), list) and pub["repos"]):
        return []
    try:
        missing = undenied(cfg)
    except Exception as exc:   # noqa: BLE001 - config.unexpected names it, and the guards refuse
        return [f"public: the deny list could not be built ({type(exc).__name__}: {exc}): brain check --public "
                "and the guards refuse until it can"]
    return [f"public: the {src} name {t!r} is in no deny list (config.json public.derive leaves out {src}): add "
            f"{src} to public.derive, the name to public.deny, or to public.public_names with its reason"
            for src, t in missing]
