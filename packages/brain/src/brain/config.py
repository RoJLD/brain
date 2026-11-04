"""A personal brain's configuration, ``config.json``: the contract between the brain engine and the private repo of a
person or a team (wi-brain-personal-brain).

``brain config [--json]`` shows it resolved, ``brain config --keys`` lists what it may hold (the descriptions of
``schemas/config.schema.json``, the one source) and ``brain config --check`` checks it; ``brain check --all`` checks
it too. The schema is validated by brain.schema's validator, then what a schema cannot say: every path it declares
exists, and its owner is the owner its graph stores declare in ``schema.yaml``.

The file sits at the personal brain's root, next to the registry, and is found the same way (brain.projects):
``$BRAIN_CONFIG`` names it, else ``config.json`` in the places of :func:`brain.paths.bases`: ``$CLAUDE_BRAIN_DIR``,
``$BRAIN_PERSONAL``, the repo acted on, the machine's pointer ``<BRAIN_HOME>/personal.json`` (the installer writes
it), then a checkout that still holds this package. A brain without one runs on :data:`DEFAULTS`, its
owner read from its main graph store. Loading never fails: an unreadable file is reported by :func:`check` and the
defaults apply, so a bad file never stops another command.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import graph, paths, projects, schema

FILE = "config.json"
DEFAULTS = {"registry": "projects.yaml", "rules": [], "memory": "memory", "records": "records", "source": "source"}
PATH_KEYS = ("registry", "memory", "records", "source")   # declared paths that must exist (and each of rules)
DENY = ("people", "users", "hosts", "repos", "paths")
NO_OWNER = "the owner"
# The names of the Claude rendering (adapters.claude) when config.json gives none: the engine's own, no person's.
CLAUDE = {"marketplace": "brain", "plugin": "brain-core", "source": ""}


@dataclass
class Config:
    file: Path | None            # None: no config.json, the defaults
    root: Path                   # the personal brain's root: the file's folder, else the repo acted on
    data: dict = field(default_factory=dict)
    error: str = ""              # why the file could not be read (check() reports it)

    def get(self, key: str):
        return self.data.get(key, DEFAULTS.get(key))

    def path(self, key: str) -> Path:
        return self.root / self.get(key)


def config_file(root: Path | None = None) -> Path | None:
    env = os.environ.get("BRAIN_CONFIG")
    if env:
        return Path(env).expanduser()
    for base in paths.bases(root):
        if (base / FILE).is_file():
            return base / FILE
    return None


def load(root: Path | None = None) -> Config:
    f = config_file(root)
    if not f or not f.is_file():
        return Config(None, Path(root or os.getcwd()).resolve(), error=f"{f} not found" if f else "")
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Config(f, f.parent.resolve(), error=f"{f.name}: not readable JSON ({exc})")
    if not isinstance(data, dict):
        return Config(f, f.parent.resolve(), error=f"{f.name}: an object, got {type(data).__name__}")
    return Config(f, f.parent.resolve(), data)


def store_owners(cfg: Config) -> dict[str, str]:
    """{store: owner} for the graph stores of the projects whose root is the brain's root (its own stores)."""
    out = {}
    for store in projects.for_root(cfg.root).stores:
        f = store / "schema.yaml"
        if f.is_file():
            data = graph.load_yaml_file(f) or {}
            if isinstance(data, dict) and data.get("owner"):
                out[store.relative_to(cfg.root).as_posix() if store.is_relative_to(cfg.root) else str(store)] = \
                    str(data["owner"])
    return out


def owner(cfg: Config) -> str:
    """Who decides for the brain: identity.owner, else the owner its first store declares, else 'the owner'."""
    ident = cfg.data.get("identity")
    if isinstance(ident, dict) and isinstance(ident.get("owner"), str) and ident["owner"]:
        return ident["owner"]
    return next(iter(store_owners(cfg).values()), NO_OWNER)


def owner_of(root: Path | None = None) -> str:
    """The owner of the brain the command runs from (:func:`owner` of its config.json): the name its views, help
    texts and defaults give to whoever decides ("waiting on <owner>", ``--by``, the rules' "<owner> decides")."""
    return owner(load(root))


def display_name(cfg: Config) -> str:
    """The name the views show for the owner (wi-brain-owner-label, UX-16): identity.display_name, else
    :func:`owner`. ``owner`` stays the id ``--by`` writes and the stores declare: a record never changes for display."""
    ident = cfg.data.get("identity")
    if isinstance(ident, dict) and isinstance(ident.get("display_name"), str) and ident["display_name"].strip():
        return ident["display_name"].strip()
    return owner(cfg)


def name_of(root: Path | None = None) -> str:
    """:func:`display_name` of the brain the command runs from: the name in titles, help texts and confirmations
    (:data:`NO_OWNER` when neither identity nor a store names anyone)."""
    return display_name(load(root))


def rules_files(cfg: Config) -> list[Path]:
    """The owner's rules for every project (config.json ``rules``), as paths."""
    rules = cfg.get("rules")
    return [cfg.root / r for r in rules if isinstance(r, str) and r] if isinstance(rules, list) else []


def claude(cfg: Config) -> dict[str, str]:
    """adapters.claude, each name defaulting to :data:`CLAUDE`: the marketplace, the core plugin (its guards and hooks
    sign with its name) and the marketplace's source repo on GitHub."""
    adapters = cfg.data.get("adapters") if isinstance(cfg.data.get("adapters"), dict) else {}
    given = adapters.get("claude") if isinstance(adapters.get("claude"), dict) else {}
    return {k: str(given.get(k) or v) for k, v in CLAUDE.items()}


def deny_terms(cfg: Config) -> list[tuple[str, str]]:
    """(category, term) for each term of public.deny, in DENY's order."""
    deny = (cfg.data.get("public") or {}).get("deny") if isinstance(cfg.data.get("public"), dict) else None
    if not isinstance(deny, dict):
        return []
    return [(cat, t) for cat in DENY for t in deny.get(cat) or [] if isinstance(t, str) and t]


def allowed(cfg: Config) -> dict[str, str]:
    """public.allow: {glob: reason}, the files where a denied term is expected."""
    pub = cfg.data.get("public")
    allow = pub.get("allow") if isinstance(pub, dict) else None
    return {str(k): str(v) for k, v in allow.items()} if isinstance(allow, dict) else {}


def check(root: Path | None = None) -> list[str]:
    """What is wrong in config.json: unreadable, the schema (brain.schema's validator), a declared path that does not
    exist, an owner other than its stores'. [] when there is no file (the defaults apply)."""
    cfg = load(root)
    if cfg.error:
        return [cfg.error] if cfg.file else []
    if cfg.file is None:
        return []
    # read mode outside CI: a newer brain's key is noted and kept; a newer v is refused in both modes
    found, unknown = schema.validate("config", cfg.data, schema.mode())
    errors = [e.replace("config", FILE, 1) for e in found]
    for u in unknown:
        schema.tolerate(u.replace("config", FILE, 1), strict=False)
    for key in PATH_KEYS:
        if key in cfg.data and isinstance(cfg.data[key], str) and not cfg.path(key).exists():
            errors.append(f"{FILE}: {key} {cfg.data[key]!r} does not exist")
    rules = cfg.data.get("rules")
    for rule in rules if isinstance(rules, list) else []:
        if isinstance(rule, str) and not (cfg.root / rule).is_file():
            errors.append(f"{FILE}: rules {rule!r} does not exist")
    engine = cfg.data.get("engine")
    installer = engine.get("installer") if isinstance(engine, dict) else None
    if isinstance(installer, str) and installer and not (cfg.root / installer).is_file():
        errors.append(f"{FILE}: engine.installer {installer!r} does not exist")
    ident = cfg.data.get("identity")
    if isinstance(ident, dict) and isinstance(ident.get("owner"), str):
        for store, who in store_owners(cfg).items():
            if who != ident["owner"]:
                errors.append(f"{FILE}: identity.owner {ident['owner']!r}, but {store}/schema.yaml says owner: {who}")
    return errors


def describe(cfg: Config) -> dict:
    """The configuration resolved, with stable keys: what brain config prints."""
    ident = cfg.data.get("identity") if isinstance(cfg.data.get("identity"), dict) else {}
    terms = deny_terms(cfg)
    pub = cfg.data.get("public") if isinstance(cfg.data.get("public"), dict) else {}
    return {"file": str(cfg.file) if cfg.file else None, "root": str(cfg.root), "v": cfg.data.get("v"),
            "owner": owner(cfg), "display_name": display_name(cfg), "kind": ident.get("kind", "person"),
            "tenant": ident.get("tenant"),
            "registry": cfg.get("registry"), "rules": list(cfg.get("rules") or []), "memory": cfg.get("memory"),
            "records": cfg.get("records"), "source": cfg.get("source"), "engine": cfg.data.get("engine"),
            "claude": claude(cfg), "public_repos": list(pub.get("repos") or []),
            "personal": str(paths.personal_root()) if paths.personal_root() else None,
            "deny": {cat: sum(1 for c, _ in terms if c == cat) for cat in DENY},
            "allow": sorted(allowed(cfg)), "secrets": sorted(cfg.data.get("secrets") or {})}


def keys() -> list[tuple[str, str]]:
    """(key, what it holds) for every key of the schema, nested ones dotted: what brain config --keys prints."""
    root = schema.load("config")
    out: list[tuple[str, str]] = []

    def walk(props: dict, prefix: str) -> None:
        for name, sub in props.items():
            if "$ref" in sub:
                sub = {**schema._resolve(sub["$ref"], root), **{k: v for k, v in sub.items() if k != "$ref"}}
            out.append((prefix + name, sub.get("description", "")))
            if isinstance(sub.get("properties"), dict):
                walk(sub["properties"], f"{prefix}{name}.")

    walk(root["properties"], "")
    return out
