"""The deny terms derived from the brain's own registries (wi-brain-public-deny-derived): what config.json
``public.deny`` holds by hand, the public check (brain.public), the commit guard (brain.guards) and brain boundary's
readiness also refuse from the day a machine, a project, a person, a spec or a module is declared. Zero token: the
registries are read as files.

The sources (``public.derive`` picks them, a list of these names; absent, all of them; ``[]``, none):

- ``hosts``: the machines of config.json ``hosts``, by name, and their ``aliases``;
- ``people``: config.json ``identity.owner`` and ``identity.display_name``, and members.yaml's people (``name``,
  ``person_id``);
- ``projects``: the projects registry's names (read-only ones too) and each project's repos, by name and by its main
  checkout's folder (brain.projects.repos_of);
- ``specs``: the file names, without ``.md``, under the brain's ``docs/specs`` (a spec's path is its name);
- ``modules``: the module registries of the brain's own stores (brain.modules), each entry's ``name``, and its ``id``
  when it is 4 characters or more (a short code such as ``D7`` or ``P2`` names nothing and is everywhere).

A derived term joins the hand list's category (hosts, people, repos for projects and modules, paths for specs), once
whatever its case. Never derived: a term shorter than 3 characters; the owner or the name of a repo of
``public.repos`` (the engine's own name, its GitHub owner); a term of ``public.public_names`` (``{name: reason}``: a
registry's name that is public, a third-party tool a project reads).

:func:`undenied` is what ``brain check`` warns about: a declared private name that no deny list holds, which happens
when ``public.derive`` leaves its source out and the hand list does not name it.

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


def _never(cfg: config.Config) -> set[str]:
    out = {k.lower() for k in public_names(cfg)}
    for r in _public(cfg).get("repos") or []:
        if isinstance(r, str):
            out.update(p.lower() for p in r.split("/") if p)
    return out


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
        from . import graph
        try:
            data = graph.load_yaml_file(f)
        except Exception:   # noqa: BLE001 - a YAML error or a conflict marker: brain identity check says why
            data = None
        people = data.get("people") if isinstance(data, dict) else None
        for p in people if isinstance(people, list) else []:
            if isinstance(p, dict):
                out += [p[k] for k in ("name", "person_id") if isinstance(p.get(k), str)]
    return out


def _projects(cfg: config.Config) -> list[str]:
    from . import projects
    try:
        loaded = projects.load(cfg.root)
        names = [*loaded, *projects.readonly(cfg.root)]
    except Exception:   # noqa: BLE001 - an unreadable registry: brain check --all says why
        return []
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
    except Exception:   # noqa: BLE001 - an unreadable registry: brain check --all says why
        return []
    seen: set[Path] = set()
    for store in stores:
        try:
            f = modules.registry_file(store, cfg.root)
            if f is None or f.resolve() in seen:
                continue
            seen.add(f.resolve())
            reg = modules.registry(store, cfg.root) or []
        except Exception:   # noqa: BLE001 - an unreadable registry: brain modules --check says why
            continue
        for m in reg:
            if isinstance(m.get("name"), str):
                out.append(m["name"])
            if len(str(m["id"])) >= MIN_ID:
                out.append(str(m["id"]))
    return out


READERS = {"hosts": _hosts, "people": _people, "projects": _projects, "specs": _specs, "modules": _modules}


def declared(cfg: config.Config) -> list[tuple[str, str]]:
    """(source, name) of every private name the registries declare, whatever public.derive says, once each per
    source; the names never derived are left out."""
    never = _never(cfg)
    out: list[tuple[str, str]] = []
    for src in SOURCES:
        seen: set[str] = set()
        for t in READERS[src](cfg):
            t = t.strip()
            if len(t) < MIN_LEN or t.lower() in never or t.lower() in seen:
                continue
            seen.add(t.lower())
            out.append((src, t))
    return out


def terms(cfg: config.Config) -> list[tuple[str, str]]:
    """(category, term) derived from the sources public.derive picks."""
    picked = set(sources(cfg))
    return [(CATEGORY[src], t) for src, t in declared(cfg) if src in picked]


def undenied(cfg: config.Config) -> list[tuple[str, str]]:
    """(source, name) of the declared private names no deny list holds (a term of public.deny, the derived ones and
    the scope tree's): what brain check warns about."""
    from . import boundary
    held = [boundary.term_regex(t) for _, t in config.deny_terms(cfg)]
    return [(src, t) for src, t in declared(cfg) if not any(rx.search(t.replace("\\", "/")) for rx in held)]


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
        return [f"public: the deny terms could not be derived ({type(exc).__name__}: {exc})"]
    return [f"public: the {src} name {t!r} is in no deny list (config.json public.derive leaves out {src}): add "
            f"{src} to public.derive, the name to public.deny, or to public.public_names with its reason"
            for src, t in missing]
