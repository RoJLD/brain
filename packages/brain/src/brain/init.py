"""``brain init``: a new personal brain from the package's templates, for a person or a team starting their own (the
first half of the setup wizard; spec-brain-personal-brain §5).

    brain init [DIR] [--owner NAME] [--template NAME|DIR] [--kind person|team] [--tenant ID] [--tier lite|default]
               [--name NAME] [--apply]

A plan by default; ``--apply`` writes it, then prints the next steps: the first commit (with the two ``git config
--global`` commands first when git has no identity on this machine, a fresh Git for Windows), Claude Code's plugin,
and the vault's runbook at the engine's tag. Nothing is overwritten: a file or a store that exists is kept, so a second
apply changes nothing. ``--owner`` may be left out where DIR already has a config.json: its ``identity.owner`` is the
owner. In DIR (default: the current folder), which becomes the owner's private repo:

- ``config.json`` (v1): ``identity`` (the owner, a person or a team, a tenant), the registry, the rules, memory and
  records, the template it was written from (``template``: its name and version), the engine that runs it
  (``engine``: this package's repo and tag), the machine profile it starts from (``tier``, Lite by default), the
  names of its Claude Code marketplace and core plugin (``adapters.claude``, the engine's defaults: no ``source``, so
  the installer's marketplace steps stay off) and ``public``: no public repo yet, and the terms that must never reach
  one (``deny``: the owner's name, this machine's user and host names);
- the template's files (``--template``, default ``generic``: ``templates/<name>/template.yaml``, or a folder holding
  one), rendered with the owner's name; the generic template writes:
- ``projects.yaml``: one project, the brain itself (``root: .``), its repo audited with the Claude rendering waived;
- ``boundary.yaml``: every file's side (brain.boundary), ``readiness_max: 0``, ``src/``, ``tests/`` and ``fixtures/``
  on the engine side, so whatever may be published one day is publishable from the first commit (``brain check``
  runs the boundary's check and the engine side's public scan, brain.boundary.gate); ``fixtures/README.md`` for the
  tests' invented data; ``README.md`` and ``.gitattributes`` (LF endings: the hooks' shell scripts; the paths
  ``brain merge-driver`` merges, ``merge=brain``);
- ``source/packs.yaml``: the neutral source (brain.neutral), the marketplace's owner and one core pack with the
  engine's hooks;
- ``notes/graph`` and ``notes/decisions.md``: ``research_graph init --owner`` (then its sync and kanban, so ``brain
  check`` passes at once);
- the Claude files, after the store: ``.claude-plugin/marketplace.json`` and ``plugins/<plugin>/`` (its manifest and
  the engine's hooks), by the code of ``brain render --target claude --write``: a local marketplace the owner adds
  once (``claude plugin marketplace add DIR``) and ``brain sync`` renders again after an engine upgrade. A rendered
  file that exists and differs is kept (``brain render --target claude --write`` replaces it);
- ``notes/journal.md``, neutral starter rules ``rules/global.md``, ``CLAUDE.md``, ``.gitignore``, ``memory/`` and
  ``records/``;
- with ``--preset``, ``--with``, ``--without``, ``--catalogue`` or ``--interactive``, the three screens of the modules
  (brain.firstrun: who you are, your machine, adjust) and their brain commands, run and logged after the files;
- the machine's pointer ``<BRAIN_HOME>/personal.json`` when the machine has none (the installer writes it too, and
  ``install.ps1 -Personal`` moves it).

The templates name no person, repo or host: the owner is the name given. A template is data and its manifest
(``name``, ``version``, ``engine``: the brain versions that can render it, ``title``, ``files``: {the brain's path:
the template's file, or "" for an empty one}, ``graphs``: the graph stores it starts, a list of {name, store, schema}
or {name, store, layers} whose first is the brain's main store; ``schema: default`` is the brain's base of work,
decisions and records (``templates/schemas/default.yaml``); ``layers: [work, decisions, records, research, ...]``
composes the schema from research_graph's catalogue of layers (``research_graph layers``), a name it does not hold
being the template's own layer, ``layers/<name>.yaml`` in its folder), never code (wi-brain-domain-templates). The
plan is a list of steps, local only: a later step (the owner's repos and data store, created on their keystroke:
wi-brain-init-stores) joins it without changing the others.
"""

from __future__ import annotations

import getpass
import json
import re
import socket
import subprocess
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from . import __version__, classes, config, graph, neutral, paths, render, schema, vault

ENGINE_REPO = "RoJLD/brain"   # where this package is published: config.json engine.repo
TEMPLATES = files(__package__) / "templates"
DEFAULT_TEMPLATE = "generic"
# a name the identity hint may print inside double quotes: no $, backtick, backslash or quote for a shell to expand
SHELL_SAFE_NAME = re.compile(r"[\w .'-]+")
MANIFEST = "template.yaml"
TEMPLATE_KEYS = {"name", "version", "engine", "title", "files", "graphs", "classes", "extends", "append"}
# an engine template's folder: a name one may give, or a base (``_name``) only other templates extend
BASE_RE = re.compile(r"_?[a-z0-9][a-z0-9_.-]*")
MAX_EXTENDS = 6   # a template's chain of bases: an owner's, a profile, _software, _project, generic, and one more
GRAPH_KEYS = {"name", "store", "schema", "layers"}
LAYER_RE = re.compile(r"[a-z][a-z0-9_]*")   # a layer's name (research_graph.layers.NAME_RE)
SCHEMAS = ("default",)   # templates/schemas/<name>.yaml; or a graph's layers, composed from research_graph's catalogue
# what config.json names, so every template writes it (a folder through its .gitkeep)
REQUIRED = ("projects.yaml", "rules/global.md", "source/packs.yaml", "memory/.gitkeep", "records/.gitkeep")
TIERS = ("lite", "default")
STAGES = ("prototype", "mvp", "v1", "scale")   # brain.standards.STAGES: the stage a profile's template selects for
DEFAULT_STAGE = "prototype"
KINDS = ("person", "team")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*")
STORE = "notes/graph"
PACKS = f"{neutral.FOLDER}/{neutral.PACKS}"
MARKETPLACE = ".claude-plugin/marketplace.json"
# a user or host name too common to deny as a whole word (it would refuse ordinary text)
COMMON_NAMES = {"user", "users", "admin", "administrator", "root", "owner", "default", "guest", "public", "runner",
                "localhost", "local", "host", "computer", "pc", "me", "you", "name", "test"}


class InitError(ValueError):
    """A bad argument: nothing is planned."""


@dataclass
class Step:
    action: str            # create (a file), keep (exists), store (research_graph init), render (the Claude files),
    path: Path             # point (the pointer)
    text: str | None = None
    why: str = ""
    graph: int | None = None   # a graph's keep or store step: its index in the template's graphs (0: the first)


@dataclass
class Template:
    name: str
    version: int
    title: str
    folder: object                  # a Traversable (the package's) or a Path (a folder of the owner's)
    engine: str = ""
    files: dict[str, str] = field(default_factory=dict)
    graphs: list[dict] = field(default_factory=lambda: [{"name": "work", "store": STORE, "schema": "default"}])
    classes: dict = field(default_factory=dict)     # {store: {class, paths, ...}}: the template's own stores
    origin: dict = field(default_factory=dict)      # the brain's path -> the folder of the template that gives it
    appends: dict = field(default_factory=dict)     # the brain's path -> [(folder, source)] appended, bases first
    extends: tuple[str, ...] = ()                   # the engine's templates it builds on, the nearest first
    layer_folders: tuple = ()                       # where its own layers are looked for (layers/<name>.yaml)

    def read(self, source: str) -> str:
        return (self.folder / source).read_text(encoding="utf-8") if source else ""

    def text(self, rel: str) -> str:
        """The text of the brain's path ``rel``: its file, from the template that gives it, then what the templates
        append to it, each on a line of its own."""
        source = self.files[rel]
        out = (self.origin.get(rel, self.folder) / source).read_text(encoding="utf-8") if source else ""
        for folder, extra in self.appends.get(rel, []):
            out += ("" if not out or out.endswith("\n") else "\n") + (folder / extra).read_text(encoding="utf-8")
        return out

    def appended(self, rel: str) -> str:
        """What the templates append to ``rel``, named (for a plan that keeps the file)."""
        return ", ".join(extra for _, extra in self.appends.get(rel, []))


def _version(text: str) -> tuple[int, ...]:
    parts = [int(x) for x in re.findall(r"\d+", text)[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def engine_fits(spec: str, version: str = __version__) -> bool:
    """Whether ``version`` meets ``spec``: comma-separated ``>=``, ``>``, ``<=``, ``<``, ``==`` constraints."""
    have = _version(version)
    ops = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
           "==": lambda a, b: a == b}
    for part in filter(None, (p.strip() for p in (spec or "").split(","))):
        m = re.fullmatch(r"(>=|<=|==|>|<)\s*v?(\d+(?:\.\d+){0,2})", part)
        if not m:
            raise InitError(f"{MANIFEST}: engine {spec!r}: constraints like >=0.2.1, <0.3")
        if not ops[m.group(1)](have, _version(m.group(2))):
            return False
    return True


def known_templates() -> list[str]:
    """The engine's templates one may name: a folder of templates/ with a manifest, not a base (``_name``)."""
    return sorted(d.name for d in TEMPLATES.iterdir() if NAME_RE.fullmatch(d.name) and (d / MANIFEST).is_file())


def _manifest(spec: str) -> tuple[object, dict]:
    """(the template's folder, its manifest's data): one of the package's, else a folder holding a template.yaml."""
    folder = TEMPLATES / spec if BASE_RE.fullmatch(spec) else None
    if folder is None or not (folder / MANIFEST).is_file():
        folder = Path(spec).expanduser()
        if not (folder / MANIFEST).is_file():
            raise InitError(f"--template {spec!r}: not one of the engine's ({', '.join(known_templates())}) nor a "
                            f"folder with a {MANIFEST}")
    try:
        data = graph.load_yaml_file((folder / MANIFEST)) or {}
    except Exception as exc:   # a YAML error: the manifest may be the owner's or a domain's
        raise InitError(f"--template {spec}: {MANIFEST} is not readable YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise InitError(f"--template {spec}: {MANIFEST} is a mapping")
    return folder, data


def _head(spec: str, data: dict) -> None:
    """The engine range first (a newer template says "needs brain >=X", not "unknown key(s)": docs/formats.md), then
    the keys, the name and the version."""
    engine = str(data.get("engine") or "")
    if not engine_fits(engine):
        raise InitError(f"--template {spec}: it needs brain {engine}, this is {__version__} (install the engine at a "
                        "tag that fits: brain update)")
    unknown = set(data) - TEMPLATE_KEYS
    if unknown:   # a template within this engine's range: a newer key is noted in read mode, refused in CI
        for message in schema.tolerate(f"--template {spec}: {MANIFEST}: unknown key(s) {', '.join(sorted(unknown))} "
                                       f"(known: {', '.join(sorted(TEMPLATE_KEYS))})"):
            raise InitError(message)
    name, version = data.get("name"), data.get("version")
    if not (isinstance(name, str) and BASE_RE.fullmatch(name)):
        raise InitError(f"--template {spec}: {MANIFEST}: name is lower case letters, digits, '.', '_' and '-'")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise InitError(f"--template {spec}: {MANIFEST}: version is a whole number, 1 or more")


def _paths(spec: str, folder, data: dict, key: str) -> dict[str, str]:
    """``files`` or ``append``: {the brain's path: the template's file}, each path inside the brain, each file there."""
    fs = data.get(key) or {}
    if not isinstance(fs, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in fs.items()):
        raise InitError(f"--template {spec}: {MANIFEST}: {key} maps the brain's path to the template's file")
    for rel, source in fs.items():
        if rel == config.FILE or rel.startswith("/") or ".." in rel.replace("\\", "/").split("/"):
            raise InitError(f"--template {spec}: {MANIFEST}: {rel!r}: a path inside the brain, not config.json")
        if (source or key == "append") and not (folder / source).is_file():
            raise InitError(f"--template {spec}: {MANIFEST}: {rel}: no file {source!r} in the template")
    return dict(fs)


def _base(spec: str, data: dict, chain: tuple[str, ...]) -> Template | None:
    """The engine's template ``extends`` names, loaded (a chain of at most :data:`MAX_EXTENDS`, never a cycle)."""
    ext = data.get("extends")
    if ext is None:
        return None
    if not (isinstance(ext, str) and BASE_RE.fullmatch(ext) and (TEMPLATES / ext / MANIFEST).is_file()):
        raise InitError(f"--template {spec}: {MANIFEST}: extends {ext!r}: one of the engine's templates "
                        f"({', '.join(sorted(d.name for d in TEMPLATES.iterdir() if (d / MANIFEST).is_file()))})")
    if ext in chain or len(chain) > MAX_EXTENDS:
        raise InitError(f"--template {spec}: {MANIFEST}: extends {ext!r}: a cycle or a chain past {MAX_EXTENDS} "
                        f"({' -> '.join(chain + (ext,))})")
    return load_template(ext, chain + (ext,))


def load_template(spec: str = DEFAULT_TEMPLATE, _chain: tuple[str, ...] = ()) -> Template:
    """The template ``spec`` names: one of the package's (``templates/<name>``), else a folder holding a
    template.yaml. Its manifest is checked, and the engine it asks for. A template that ``extends`` one of the
    engine's takes its files, appends, graphs and classes, and adds or replaces its own (a file of the same path, its
    graphs when it gives some)."""
    spec = spec or DEFAULT_TEMPLATE
    if not _chain and spec.startswith("_") and (TEMPLATES / spec / MANIFEST).is_file():
        raise InitError(f"--template {spec}: a base the engine's templates extend, not one to start from (one of "
                        f"{', '.join(known_templates())})")
    folder, data = _manifest(spec)
    _head(spec, data)
    base = _base(spec, data, _chain or (spec,))
    if base is None and not isinstance(data.get("files"), dict):
        raise InitError(f"--template {spec}: {MANIFEST}: files maps the brain's path to the template's file")
    own = _paths(spec, folder, data, "files")
    fs = {**(base.files if base else {}), **own}
    origin = {**(base.origin if base else {}), **{rel: folder for rel in own}}
    appends = {rel: list(v) for rel, v in (base.appends if base else {}).items()}
    for rel, source in _paths(spec, folder, data, "append").items():
        if rel not in fs:
            raise InitError(f"--template {spec}: {MANIFEST}: append {rel}: not a file the template writes")
        appends.setdefault(rel, []).append((folder, source))
    missing = [r for r in REQUIRED if r not in fs]
    if missing:
        raise InitError(f"--template {spec}: {MANIFEST}: files misses what config.json names: {', '.join(missing)}")
    if not isinstance(data.get("classes") or {}, dict):
        raise InitError(f"--template {spec}: {MANIFEST}: classes: {{store: {{class, paths}}}}")
    declared = {**(base.classes if base else {}), **(data.get("classes") or {})}
    _, errors = classes.stores(config.Config(None, Path("."), {"classes": {"stores": declared}}))
    if errors:
        raise InitError(f"--template {spec}: {MANIFEST}: classes: " + ("; ".join(errors) or "{store: {class, paths}}"))
    own_graphs = "graphs" in data or base is None
    graphs = graphs_of(spec, data.get("graphs")) if own_graphs else [dict(g) for g in base.graphs]
    tpl = Template(data["name"], data["version"], str(data.get("title") or ""), folder, str(data.get("engine") or ""),
                   fs, graphs, declared, origin, appends,
                   ((data["extends"],) + base.extends) if base else (),
                   (folder,) + (base.layer_folders if base else ()))
    for i, g in enumerate(tpl.graphs):   # each graph's layers compose: the catalogue's and the template's own
        if g.get("layers"):
            try:
                graph_schema(g, "x", tpl)
            except ValueError as exc:
                raise InitError(f"--template {spec}: {MANIFEST}: graphs[{i}] ({g['name']}): {exc}") from exc
    return tpl


def classes_block(tpl: Template) -> dict:
    """config.json's starting ``classes``: the template's stores, then the engine's own machine stores (sealed), then
    a private catch-all for the rest of the repo, so a fresh brain passes brain check --all."""
    stores = dict(tpl.classes)
    for name, (path, cls) in classes.KNOWN.items():
        if name not in stores:
            stores[name] = {"class": cls, "paths": [path]}
    if not any("**" in s.get("paths", []) for s in stores.values()):
        stores["repo"] = {"class": "private", "paths": ["**"], "why": "rules, graph, ADRs, journal, records"}
    return {"stores": stores}


def graphs_of(spec: str, declared) -> list[dict]:
    """The manifest's ``graphs``, checked: a list of {name, store, schema} or {name, store, layers}, names and stores
    unique, a store inside the brain; none declared: one, ``work`` at notes/graph. ``layers``: the layers its schema
    is composed of (research_graph layers: the catalogue's names, or the template's own, ``layers/<name>.yaml`` in its
    folder), instead of ``schema``."""
    if declared is None:
        return Template("", 1, "", None).graphs
    where = f"--template {spec}: {MANIFEST}: graphs"
    if not isinstance(declared, list) or not declared:
        raise InitError(f"{where} is a list of {{name, store, schema}}, one at least")
    out, names, stores = [], set(), set()
    for i, g in enumerate(declared):
        if not isinstance(g, dict) or set(g) - GRAPH_KEYS:
            raise InitError(f"{where}[{i}]: a mapping of {', '.join(sorted(GRAPH_KEYS))}")
        name, store, schema = g.get("name"), g.get("store"), g.get("schema", "default")
        if not (isinstance(name, str) and NAME_RE.fullmatch(name)) or name in names:
            raise InitError(f"{where}[{i}]: name is lower case letters, digits, '.', '_' and '-', each once")
        if not isinstance(store, str) or not store or store.startswith("/") or \
                ".." in store.replace("\\", "/").split("/") or store in stores:
            raise InitError(f"{where}[{i}] ({name}): store is a folder inside the brain, each once")
        layer_names = g.get("layers")
        if layer_names is not None:
            if "schema" in g:
                raise InitError(f"{where}[{i}] ({name}): schema or layers, not both")
            if not isinstance(layer_names, list) or not layer_names or \
                    not all(isinstance(x, str) and LAYER_RE.fullmatch(x) for x in layer_names):
                raise InitError(f"{where}[{i}] ({name}): layers is a list of layer names, one at least")
        elif schema not in SCHEMAS:
            raise InitError(f"{where}[{i}] ({name}): schema {schema!r}: only {', '.join(SCHEMAS)} for now "
                            "(the brain's base: work, decisions, records), or layers: [NAME, ...]")
        names.add(name)
        stores.add(store)
        out.append({"name": name, "store": store, **({"layers": list(layer_names)} if layer_names is not None else
                                                     {"schema": schema})})
    return out


def template_layers(tpl: Template | None, names) -> dict:
    """The template's own layers among ``names`` (``layers/<name>.yaml`` in its folder), by name: research_graph's
    Layer objects; a name of the catalogue is the catalogue's."""
    from research_graph import layers

    out = {}
    for n in names:
        if n in layers.catalogue():
            continue
        folders = (tpl.layer_folders or (tpl.folder,)) if tpl is not None else ()
        f = next((d / "layers" / f"{n}.yaml" for d in folders if d is not None and (d / "layers" / f"{n}.yaml")
                  .is_file()), None)
        if f is None:
            raise InitError(f"layer {n!r}: not in the catalogue ({', '.join(layers.catalogue())}) nor the template's "
                            f"layers/{n}.yaml")
        try:
            data = graph.load_yaml(f.read_text(encoding="utf-8"))
        except Exception as exc:   # a YAML error in the template's own layer file
            raise InitError(f"layers/{n}.yaml is not readable YAML ({exc})") from exc
        layer = layers.parse_layer(data, f"layers/{n}.yaml")
        if layer.name != n:
            raise InitError(f"layers/{n}.yaml holds layer {layer.name!r}")
        out[n] = layer
    return out


def graph_schema(g: dict, owner: str, tpl: Template | None = None) -> str:
    """A graph's schema.yaml: the default one (``schema``), or the one its ``layers`` compose (``templates:`` and
    ``endpoints:`` included), with its owner."""
    if not g.get("layers"):
        return schema_text(g.get("schema", "default"), owner)
    from research_graph import layers

    resolved = layers.resolve(g["layers"], template_layers(tpl, g["layers"]))
    return layers.render(layers.compose_layers(resolved, owner), layers.header_for(resolved))


def schema_text(name: str, owner: str) -> str:
    """A store's schema.yaml from the engine's ``templates/schemas/<name>.yaml``, with its owner. ``default``, the
    brain's base: the work, the decisions and the records layers (DDR, Session, Action: what brain sync generates
    from records/), so that a new brain's decisions and sessions are nodes of its graph from the first sync."""
    text = (TEMPLATES / "schemas" / f"{name}.yaml").read_text(encoding="utf-8")
    return text.replace("{owner_line}", f"owner: {json.dumps(owner, ensure_ascii=False)}\n")


def schema_layers(text: str) -> list[str]:
    """The layers of a schema.yaml text (a template's schema name gives its text by :func:`schema_text`)."""
    if "\n" not in text:   # a schema's name (as before 0.3.3)
        text = schema_text(text, "x")
    data = graph.load_yaml(text) or {}
    return list((data.get("layers") or {}).keys())


def template(name: str, tpl: str = DEFAULT_TEMPLATE) -> str:
    """A file of one of the package's templates, as it is (its variables unrendered)."""
    return (TEMPLATES / tpl / name).read_text(encoding="utf-8")


def machine_terms() -> dict[str, list[str]]:
    """This machine's user and host names, for public.deny: never one so common it would refuse ordinary text."""
    out: dict[str, list[str]] = {}
    for cat, read in (("users", getpass.getuser), ("hosts", lambda: socket.gethostname().split(".")[0])):
        try:
            term = (read() or "").strip()
        except Exception:   # no user name in this environment (a container without one): nothing to deny
            continue
        if len(term) >= 3 and term.lower() not in COMMON_NAMES:
            out[cat] = [term]
    return out


def config_text(owner: str, kind: str = "person", tenant: str | None = None, tier: str = "lite",
                tpl: Template | None = None) -> str:
    ident = {"owner": owner, "kind": kind, **({"tenant": tenant} if tenant else {})}
    claude = {k: config.CLAUDE[k] for k in ("marketplace", "plugin")}   # no source: a local marketplace
    tpl = tpl or load_template()
    data = {"v": 1, "identity": ident, "registry": "projects.yaml", "rules": ["rules/global.md"], "memory": "memory",
            "records": "records", "template": {"name": tpl.name, "version": tpl.version},
            "engine": {"repo": ENGINE_REPO, "pin": f"v{__version__}"}, "tier": {"base": tier}, "modules": {},
            "adapters": {"claude": claude}, "public": {"repos": [], "deny": {"people": [owner], **machine_terms()}},
            "classes": classes_block(tpl)}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _appended_yaml(tpl: Template, rel: str, text: str, name: str) -> None:
    """A YAML file with what the template appends still reads as YAML; an append to the registry lands under the
    brain's own entry, the last one (the fragment is indented as its keys)."""
    try:
        data = graph.load_yaml(text)
    except Exception as exc:   # the template's fragment, not the owner's input
        raise InitError(f"--template {tpl.name}: {rel} with what it appends is not YAML ({exc})") from exc
    if rel == "projects.yaml" and (not isinstance(data, dict) or list(data)[-1:] != [name]):
        raise InitError(f"--template {tpl.name}: projects.yaml: what it appends goes under the brain's own entry "
                        f"({name}), which must be the registry's last")


def files_for(owner: str, kind: str, tenant: str | None, tier: str, name: str,
              tpl: Template | None = None, stage: str = DEFAULT_STAGE) -> dict[str, str]:
    """{path relative to the brain: text} for every file brain init writes but the store and the Claude files:
    config.json, then the template's files (with what it appends to them) with their variables rendered. A YAML
    file must read as YAML once rendered (an appended fragment that breaks it is the template's error)."""
    tpl = tpl or load_template()
    values = {"owner": owner, "owner_q": json.dumps(owner, ensure_ascii=False), "name": name,
              "title_q": json.dumps(f"{owner}'s brain: rules, decisions, backlog and journal", ensure_ascii=False),
              "stage": stage}
    out = {config.FILE: config_text(owner, kind, tenant, tier, tpl)}
    for rel in tpl.files:
        out[rel] = re.sub(r"\{(owner|owner_q|name|title_q|stage)\}", lambda m: values[m.group(1)], tpl.text(rel))
        if rel in tpl.appends and rel.endswith((".yaml", ".yml")):
            _appended_yaml(tpl, rel, out[rel], name)
    return out


def owner_in(root: Path) -> str:
    """identity.owner of the config.json already in ``root`` ('' when it has none)."""
    try:
        data = json.loads((Path(root) / config.FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    ident = data.get("identity") if isinstance(data, dict) else None
    return ident["owner"] if isinstance(ident, dict) and isinstance(ident.get("owner"), str) else ""


def claude_names(root: Path) -> dict[str, str]:
    """The marketplace and core plugin names of the brain at ``root`` (its own config.json adapters.claude, else the
    engine's defaults)."""
    f = Path(root) / config.FILE
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return config.claude(config.Config(f, Path(root), data if isinstance(data, dict) else {}))


def _render_step(root: Path, created: set[str], plugin: str, store: str = STORE) -> Step:
    """The Claude files: ``keep`` when the brain's source, config.json and main store exist and the render is current,
    else ``render`` (done by apply, after the stores)."""
    dest = root / MARKETPLACE
    if not created & {"config.json", "projects.yaml", PACKS} and (root / store / "schema.yaml").is_file():
        try:
            r = render.render(root, "claude")
            if not render.stale(render.plan(r, render.bases_for(root, None, None)), bases=("brain",)):
                return Step("keep", dest, why=f"and plugins/{plugin}/: current")
        except render.RenderError:
            pass   # apply reports it
    return Step("render", dest, why=f"and plugins/{plugin}/ with the engine's hooks: brain render --target claude "
                                    "--write")


def render_claude(root: Path) -> tuple[int, list[str]]:
    """``brain render --target claude --write`` for a new brain, never over a file: when a rendered file exists and
    differs (or a stray would be removed), nothing is written and each such file is named. (exit code, lines)."""
    try:
        r = render.render(root, "claude")
    except render.RenderError as exc:
        return 1, [f"error: brain render: {exc}"]
    bases = render.bases_for(root, None, None)
    held = [x for x in render.plan(r, bases) if x["state"] in ("differs", "foreign", "stray")]
    if held:
        return 0, [f"keep     {x['rel']} ({x['state']}: brain render --target claude --write replaces it)"
                   for x in held]
    render.write(r, bases)
    return 0, []


def _file_step(path: Path, text: str, appended: str) -> Step:
    """A file of the template: created, or kept when it exists (never written over); a kept file names what the
    template appends to it, for the owner to add by hand."""
    if not path.exists():
        return Step("create", path, text)
    return Step("keep", path, why=f"exists; the template appends {appended} to it: add that by hand, as the new file "
                                  "would hold it" if appended else "exists")


def plan(root: Path, owner: str, *, kind: str = "person", tenant: str | None = None, tier: str = "lite",
         name: str = "brain", template_spec: str = DEFAULT_TEMPLATE, stage: str = DEFAULT_STAGE) -> list[Step]:
    """What brain init would do in ``root``, file by file, in order (the owner: ``owner``, else the one of the
    config.json already in ``root``)."""
    owner = " ".join((owner or owner_in(root) or "").split())
    if not owner:
        raise InitError('--owner NAME: the person or team who decides for this brain (brain init --owner "Your Name")')
    if kind not in KINDS:
        raise InitError(f"--kind {kind!r}: one of {', '.join(KINDS)}")
    if tier not in TIERS:
        raise InitError(f"--tier {tier!r}: one of {', '.join(TIERS)} (Recommended is computed per machine: brain "
                        "profile set recommended)")
    if not NAME_RE.fullmatch(name):
        raise InitError(f"--name {name!r}: lower case letters, digits, '.', '_' and '-'")
    if stage not in STAGES:
        raise InitError(f"--stage {stage!r}: one of {', '.join(STAGES)} (the standards a profile's template selects)")
    tpl = load_template(template_spec)
    root = Path(root).resolve()
    steps, created = [], set()
    for rel, text in files_for(owner, kind, tenant, tier, name, tpl, stage).items():
        steps.append(_file_step(root / rel, text, tpl.appended(rel)))
        if steps[-1].action == "create":
            created.add(rel)
    for i, g in enumerate(tpl.graphs):
        schema = root / g["store"] / "schema.yaml"
        if schema.exists():
            steps.append(Step("keep", schema.parent, why="a graph store already", graph=i))
            continue
        try:
            text = graph_schema(g, owner, tpl)
        except ValueError as exc:
            raise InitError(f"--template {template_spec}: graphs[{i}] ({g['name']}): {exc}") from exc
        steps.append(Step("store", schema.parent, text,
                          why=f"research_graph init --owner {owner}, layers {', '.join(schema_layers(text))}",
                          graph=i))
    steps.append(_render_step(root, created, claude_names(root)["plugin"], tpl.graphs[0]["store"]))
    pointer, there = paths.personal_file(), paths.pointer_root()
    if there is None:
        steps.append(Step("point", pointer, json.dumps({"root": root.as_posix()}) + "\n", why=f"-> {root}"))
    elif there.resolve() != root:
        steps.append(Step("keep", pointer, why=f"points to {there} (install.ps1 -Personal moves it)"))
    return steps


def apply(root: Path, steps: list[Step], owner: str) -> int:
    """Write what the plan creates; the store, then the Claude files, then the pointer. The exit code of the store's
    init, else of the render (whose lines are printed)."""
    root = Path(root).resolve()
    code = 0
    for s in steps:
        if s.action in ("create", "point"):
            s.path.parent.mkdir(parents=True, exist_ok=True)
            s.path.write_text(s.text or "", encoding="utf-8", newline="\n")
        elif s.action == "store":   # a later graph keeps its views beside it and no decision log (brain.projects)
            # later by its index in the template's graphs: the first one may be kept (it exists) and this one new
            later = [] if not s.graph else ["--views", s.path.parent.relative_to(root).as_posix(), "--no-decisions"]
            rc = graph.research_graph(root, s.path, *later, "init", "--owner", " ".join(owner.split()))
            if not rc and s.text:   # the brain's schema over the one research_graph init just wrote: a new store only
                (s.path / "schema.yaml").write_text(s.text, encoding="utf-8", newline="\n")
            code = code or rc
        elif s.action == "render":
            rc, lines = render_claude(root)
            for line in lines:
                print(line)
            code = code or rc
    return code


def show(root: Path, steps: list[Step]) -> list[str]:
    out = []
    for s in steps:
        rel = s.path.relative_to(root).as_posix() if s.path.is_relative_to(root) else str(s.path)
        word = {"store": "create", "point": "point"}.get(s.action, s.action)
        out.append(f"{word:<8} {rel}" + (f" ({s.why})" if s.why else ""))
    return out


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)


def git_identity_missing(root: Path) -> list[str]:
    """The keys of git's identity (``user.name``, ``user.email``) a first commit in ``root`` lacks: it would stop at
    "Author identity unknown" (a fresh Git for Windows). ``git var GIT_AUTHOR_IDENT`` and ``GIT_COMMITTER_IDENT``
    decide as the commit does (the config, the ``GIT_AUTHOR_*``/``GIT_COMMITTER_*``/``EMAIL`` variables, git's own
    guess); when they fail, the keys git's config does not set. Empty when the commit would pass, and when git is not
    found or fails otherwise (no hint rather than a wrong one)."""
    try:
        if all(_git(root, "var", ident).returncode == 0 for ident in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT")):
            return []
        missing = []
        for key in ("user.name", "user.email"):
            done = _git(root, "config", "--get", key)
            if done.returncode == 1 or (done.returncode == 0 and not done.stdout.strip()):
                missing.append(key)
            elif done.returncode:
                return []
    except (OSError, subprocess.SubprocessError):
        return []
    return missing


def identity_hint(missing: list[str], owner: str, kind: str = "person") -> str:
    """The line ``brain init --apply`` adds to its next steps when git has no identity yet: the commands to set it,
    once, before the first commit; '' when nothing is missing. The owner's name for a person when PowerShell and bash
    both keep it as typed inside double quotes (letters, digits, spaces, ``.``, ``'``, ``-``), a placeholder else."""
    if not missing:
        return ""
    name = owner if kind == "person" and SHELL_SAFE_NAME.fullmatch(owner or "") else "Your Name"
    cmds = {"user.name": f'git config --global user.name "{name}"',
            "user.email": 'git config --global user.email "you@example.com"'}
    return ("      git's identity first, once (none on this machine yet: the first commit would stop at \"Author "
            "identity unknown\"): " + "; ".join(cmds[k] for k in missing if k in cmds))


def wants_modules(args) -> bool:
    """The three screens are asked for: a preset, a box, a private catalogue or --interactive."""
    return bool(getattr(args, "preset", None) or getattr(args, "with_", None) or getattr(args, "without", None)
                or getattr(args, "catalogue", None) or getattr(args, "interactive", False))


def _tier(args) -> str:
    """config.json tier.base: --tier, else the preset's engine base when it is lite or default (recommended is this
    machine's, frozen by brain profile set), else lite."""
    if getattr(args, "tier", None):
        return args.tier
    preset = getattr(args, "preset", None)
    return preset if preset in TIERS else "default" if preset else "lite"


def command_line(root: Path, args, owner: str, tier: str, preset: str, with_: list[str],
                 without: list[str]) -> list[str]:
    """The one brain init command that makes the same choice with no screen: what --interactive ends on."""
    words = ["brain", "init", str(root), "--owner", owner]
    if args.kind != "person":
        words += ["--kind", args.kind]
    for flag, value, default in (("--tenant", args.tenant, None), ("--template", getattr(args, "template", None),
                                                                     DEFAULT_TEMPLATE),
                                 ("--name", args.name, "brain"), ("--stage", getattr(args, "stage", None),
                                                                  DEFAULT_STAGE),
                                 ("--catalogue", getattr(args, "catalogue", None), None)):
        if value and value != default:
            words += [flag, str(value)]
    if getattr(args, "tier", None):
        words += ["--tier", tier]
    words += ["--preset", preset] + [w for m in with_ for w in ("--with", m)] + [w for m in without
                                                                              for w in ("--without", m)]
    return words + ["--apply"]


def _screens(root: Path, args, out=print) -> tuple:
    """The three screens (brain.firstrun) and the choice they make, with its steps: printed, or asked at each
    screen with --interactive."""
    from . import firstrun
    extra = Path(args.catalogue) if getattr(args, "catalogue", None) else None
    cat, notes = firstrun.catalogue_for(root, extra)
    facts = firstrun.facts_of(root)
    preset, with_, without = (getattr(args, "preset", None) or "lite", list(getattr(args, "with_", None) or []),
                              list(getattr(args, "without", None) or []))
    if getattr(args, "interactive", False):
        preset, with_, without = firstrun.interactive(cat, facts, preset, with_, without, out=out)
        args.preset, args.with_, args.without = preset, with_, without
    ch = firstrun.choose(cat, preset, facts, with_, without)
    ch.notes = notes + ch.notes
    screens = [] if getattr(args, "interactive", False) else (
        firstrun.render_presets(cat, facts) + firstrun.render_machine(cat, facts)
        + firstrun.render_adjust(cat, ch, facts))
    return ch, firstrun.steps(root, ch), screens


def _show_modules(root: Path, args, owner: str, tier: str, mod: tuple) -> list[str]:
    """The screens, the plan's brain commands and the one command that makes the same choice; --interactive then asks
    whether to apply. The command, for the log."""
    from . import firstrun
    ch, mod_steps, screens = mod
    same = command_line(root, args, owner, tier, ch.preset, getattr(args, "with_", None) or [],
                        getattr(args, "without", None) or [])
    print("\n".join(screens + firstrun.render_plan(mod_steps)))
    print(f"the same, without the screens: {firstrun.shown(same)}")
    if getattr(args, "interactive", False) and not args.apply:
        args.apply = firstrun.ASK("apply? [y/N] ").strip().lower() in ("y", "yes", "o", "oui")
    return same


def _run_modules(root: Path, mod: tuple) -> int:
    """The module steps in order, each logged; 1 when one fails (the next ones are not run)."""
    from . import firstrun
    ch, mod_steps, _ = mod
    done = firstrun.apply(root, mod_steps)
    for r in done:
        print(f"{'ok' if r['exit'] == 0 else 'FAILED'} ({r['exit']}): {r['command']}")
        if r["exit"] != 0 and r["output"]:
            print("  " + r["output"][-800:].replace("\n", "\n  "))
    if any(r["exit"] != 0 for r in done):
        return 1
    if ch.fetch:
        print(f"to download (not done here: offline): {', '.join(ch.fetch)}; the installer brings them "
              "(install.ps1 reads brain profile render)")
    return 0


def _next_steps(root: Path, owner: str, kind: str) -> None:
    print("next: git init and commit (a private repo of your own, never a public one); brain check; brain profile "
          "(this machine's profile); brain item add --help (your first item); brain journal add --title ...; "
          "brain sync after an edit (brain refresh --on-main: sync and check, in this checkout)")
    hint = identity_hint(git_identity_missing(root), owner, kind)
    if hint:
        print(hint)
    names = claude_names(root)
    folder = f'"{root}"' if " " in str(root) else str(root)
    print(f"      Claude Code, once: claude plugin marketplace add {folder}, then claude plugin install "
          f"{names['plugin']}@{names['marketplace']} (brain sync renders the plugin again after an engine upgrade)")
    print(f"      the vault, before anything leaves this machine: brain classes (each store's class), brain vault "
          f"status (your device key, your recovery key, the daily canary); the runbook: {vault.RUNBOOK}")


def _apply_files(root: Path, steps: list[Step], owner: str, same: list[str]) -> int:
    """The files, then config.json checked; with the modules, brain init's own step logged (``same``: its command)."""
    from . import firstrun
    code = apply(root, steps, owner)
    errors = config.check(root)
    for e in errors:
        print(f"error: {e}")
    if same:
        firstrun.log_init(root, same, code or (1 if errors else 0))
    return code or (1 if errors else 0)


def _planned(root: Path, args, tier: str) -> tuple:
    """(the file steps, the template, the owner, the modules' (choice, steps, screens) or None)."""
    spec = getattr(args, "template", None) or DEFAULT_TEMPLATE
    steps = plan(root, args.owner or "", kind=args.kind, tenant=args.tenant, tier=tier, name=args.name,
                 stage=getattr(args, "stage", None) or DEFAULT_STAGE, template_spec=spec)
    owner = " ".join((args.owner or owner_in(root)).split())
    return steps, load_template(spec), owner, (_screens(root, args) if wants_modules(args) else None)


def main(args) -> int:
    from . import firstrun
    root, tier = Path(args.dir or ".").resolve(), _tier(args)
    if getattr(args, "interactive", False) and not firstrun.tty():
        print("brain init: --interactive needs a terminal; --preset ID [--with ID]... [--without ID]... makes the same "
              "choice without the screens")
        return 2
    try:
        steps, tpl, owner, mod = _planned(root, args, tier)
    except (InitError, firstrun.SetupError) as exc:
        print(f"brain init: {exc}")
        return 2
    print(f"brain init: {root} for {owner} ({args.kind}, {tier}), template {tpl.name} v{tpl.version}, engine "
          f"{ENGINE_REPO}@v{__version__}")
    print("\n".join(show(root, steps)))
    same = _show_modules(root, args, owner, tier, mod) if mod else []
    if not args.apply:
        print("(plan only: brain init --apply writes it)" + ("" if mod else "; the modules: brain init "
              "--interactive (who you are, your machine, adjust), or --preset lite|default|recommended"))
        return 0
    code = _apply_files(root, steps, owner, same)
    if code:
        return code
    if mod and _run_modules(root, mod):
        return 1
    _next_steps(root, owner, args.kind)
    return 0
