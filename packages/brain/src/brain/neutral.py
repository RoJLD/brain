"""The tool-neutral source of a personal brain: rules with a scope and an id, procedures, MCP servers and the packs
that carry them, in a form no agent owns (wi-brain-neutral-source; spec-brain-plugin §2.7 and §3 step 6,
spec-brain-scope-tree §3.7, spec-brain-personal-brain §3.3 and PB-4). ``brain render --target <tool>`` (brain.render)
turns it into each agent's own files; nothing it renders is edited by hand.

The source is the folder ``source/`` at the brain's root (config.json ``source`` names another)::

  source/packs.yaml          the marketplace and the packs: which rules, procedures and MCP servers go together,
                             with each target's own fields (claude: the plugin manifest and its marketplace entry)
  source/rules/<name>.md     rules: front matter (scope, title, intro, lock, a target's own title and intro), then
                             one ``## `` section per rule, its first line ``<!-- id: rule-x -->``
                             (``; overrides: rule-y`` or ``; paths: a/**, b/*.py`` may follow)
  source/procedures/<name>/  a procedure (an Agent Skills folder: SKILL.md with name and description, and its files);
                             the engine's own procedures (``brain/procedures/<name>/``, package data) come first, the
                             owner's files are laid over them
  source/mcp.yaml            the MCP servers: transport (stdio, http, sse), command, args, env, cwd, url, headers;
                             variables written ``${NAME}`` or ``${NAME:-default}``

**Scopes** (spec-brain-scope-tree §3.7). A rule's scope is a node of the scope tree: ``global``, a registered project,
or (once wi-brain-scope-tree builds them) a container. A project's chain is the global rules, then each ancestor's
rules from the root down (``rules/scopes/<id>.md``), then the project's own ``CLAUDE.md``: the nearest is read last.
Until the tree has parents, a project's chain is the global rules then its own. A rules file may ``lock`` rule ids
for its whole subtree; a lower rule that declares ``overrides:`` a locked id is reported (:func:`lock_findings`):
a conflict of text stays a matter of judgement, made visible. A scope's file (``rules/scopes/<id>.md``) may hold its
front matter only (scope, title, intro), a scope with no rule of its own yet: it renders nothing and locks nothing.
A project the brain reads and never writes (``access: read``, brain.projects) is no scope of this source: its rules
are written by its own sessions.

**Exactness.** YAML flow sequences (``[a, b]``) stay inline when an adapter writes JSON, block sequences go one item
per line: the source's style is the rendered file's, so the Claude adapter reproduces a hand-written manifest byte
for byte. Rule ids are the graph's Rule nodes (``notes/graph``): :func:`check` reports an id with no active Rule node
and an active Rule node anchored in the source that no section carries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FOLDER = "source"
PACKS = "packs.yaml"
MCP = "mcp.yaml"
RULES = "rules"
SCOPES = "rules/scopes"
PROCEDURES = "procedures"
SKILL = "SKILL.md"
PROJECT_RULES = ("CLAUDE.md", ".claude/CLAUDE.md")   # a project's own rules, in its repo (the nearest scope)
GLOBAL = "global"
TRANSPORTS = ("stdio", "http", "sse")
SERVER_KEYS = {"transport", "command", "args", "env", "cwd", "url", "headers", "about"}
PACK_KEYS = {"title", "description", "core", "projects", "rules", "procedures", "mcp", "hooks"}
TARGET_TEXT_KEYS = {"title", "intro"}
RULE_FILE_KEYS = {"scope", "title", "intro", "lock"}
META_KEYS = {"id", "overrides", "paths"}
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SKILL_NAME_MAX = 64          # Agent Skills: name, description limits (agentskills.io)
SKILL_DESCRIPTION_MAX = 1024
RULE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_META = re.compile(r"^<!--\s*(.*?)\s*-->\s*$")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


class Flow(list):
    """A list written in YAML flow style (``[a, b]``): an adapter writing JSON keeps it on one line."""


def _construct(node, loader):
    if isinstance(node, yaml.MappingNode):
        return {_construct(k, loader): _construct(v, loader) for k, v in node.value}
    if isinstance(node, yaml.SequenceNode):
        items = [_construct(x, loader) for x in node.value]
        return Flow(items) if node.flow_style else items
    return loader.construct_object(node, deep=True)


def load_yaml(text: str):
    """YAML read with its sequences' style kept (:class:`Flow`); safe tags only."""
    node = yaml.compose(text, Loader=yaml.SafeLoader)
    return None if node is None else _construct(node, yaml.SafeLoader(""))


def lf(text: str) -> str:
    """Text with LF line ends (a Windows checkout may hold CRLF; git stores LF)."""
    return text.replace("\r\n", "\n")


def front_matter(text: str) -> tuple[dict, str]:
    """(the YAML front matter, the body after it); ({}, text) when there is none."""
    m = _FRONT.match(lf(text))
    if not m:
        return {}, lf(text)
    data = load_yaml(m.group(1))
    return (data if isinstance(data, dict) else {}), lf(text)[m.end():]


def variables(value) -> list[tuple[str, str | None]]:
    """The ``${NAME}`` and ``${NAME:-default}`` a value holds, (name, default or None), in order, once each."""
    out: list[tuple[str, str | None]] = []
    if isinstance(value, dict):
        for v in value.values():
            out += [x for x in variables(v) if x not in out]
    elif isinstance(value, list):
        for v in value:
            out += [x for x in variables(v) if x not in out]
    elif isinstance(value, str):
        out += [(m.group(1), m.group(2)) for m in VARIABLE.finditer(value)]
    return out


# --- the model --------------------------------------------------------------------------------------------------

@dataclass
class Rule:
    id: str                    # "" in a project's CLAUDE.md, where ids are optional
    title: str                 # the heading's text
    text: str                  # the section as rendered: its heading and body, the meta line taken out
    scope: str
    file: Path
    line: int                  # 1-based line of its heading in the file
    overrides: str = ""
    paths: list[str] = field(default_factory=list)


@dataclass
class RuleFile:
    file: Path
    rel: str                   # relative to the source folder (a project's: its path in the repo)
    scope: str
    meta: dict
    preamble: str              # the body before the first rule, meta taken out ("" usually)
    rules: list[Rule]
    lock: list[str]
    project: bool = False      # a project's own CLAUDE.md: rendered as written, ids optional

    def heading(self, target: str = "") -> tuple[str, str]:
        """(title, intro) for a target: its own when the front matter has them, else the neutral ones."""
        own = self.meta.get(target) if target and isinstance(self.meta.get(target), dict) else {}
        return (str(own.get("title", self.meta.get("title")) or ""), str(own.get("intro", self.meta.get("intro"))
                                                                         or ""))

    def body(self) -> str:
        """The rules as written, meta lines taken out: the preamble, then each rule's section."""
        return self.preamble + "".join(r.text for r in self.rules)

    def render(self, target: str = "") -> str:
        """The file as an agent reads it: ``# title``, the intro, then the rules. A project's file as written."""
        if self.project:
            return self.body()
        title, intro = self.heading(target)
        head = (f"# {title}\n\n" if title else "") + (intro.rstrip("\n") + "\n\n" if intro else "")
        return head + self.body().lstrip("\n")


@dataclass
class Procedure:
    name: str
    files: dict[str, Path]     # relative path -> the file it comes from (the owner's over the engine's)
    meta: dict                 # SKILL.md front matter
    engine: bool = False       # the engine ships it (package data)


@dataclass
class Server:
    name: str
    spec: dict                 # as declared, key order and list styles kept

    @property
    def transport(self) -> str:
        return str(self.spec.get("transport") or ("stdio" if "command" in self.spec else "http"))


@dataclass
class Pack:
    id: str
    spec: dict

    @property
    def core(self) -> bool:
        return bool(self.spec.get("core"))

    @property
    def projects(self) -> list[str] | None:
        """The projects it applies to; None: every one (the owner's scope)."""
        p = self.spec.get("projects")
        return None if p is None else [str(x) for x in p]

    def items(self, key: str) -> list[str]:
        return [str(x) for x in self.spec.get(key) or []]

    def target(self, name: str) -> dict:
        t = self.spec.get(name)
        return t if isinstance(t, dict) else {}


@dataclass
class Source:
    root: Path                 # the personal brain's root
    folder: Path               # its neutral source
    data: dict = field(default_factory=dict)          # packs.yaml
    packs: list[Pack] = field(default_factory=list)
    rule_files: dict[str, RuleFile] = field(default_factory=dict)   # rel -> file, the source's own
    procedures: dict[str, Procedure] = field(default_factory=dict)
    servers: dict[str, Server] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def core(self) -> Pack | None:
        return next((p for p in self.packs if p.core), None)

    @property
    def marketplace(self) -> dict:
        m = self.data.get("marketplace")
        return m if isinstance(m, dict) else {}

    @property
    def pointers(self) -> dict:
        p = self.data.get("pointers")
        return p if isinstance(p, dict) else {}

    def scope_files(self, scope: str) -> list[RuleFile]:
        return [f for f in self.rule_files.values() if f.scope == scope]


# --- reading ------------------------------------------------------------------------------------------------------

def folder(root: Path) -> Path:
    """The neutral source of the brain at ``root``: config.json ``source`` (relative to its folder), else source/."""
    from . import config
    cfg = config.load(root)
    named = cfg.data.get("source") if cfg.file and cfg.root.resolve() == Path(root).resolve() else None
    return (Path(root) / (named if isinstance(named, str) and named else FOLDER)).resolve()


def applies(root: Path) -> bool:
    """Whether the brain at ``root`` has a neutral source (its packs.yaml)."""
    return (folder(root) / PACKS).is_file()


def brain_root(start: Path | None = None) -> Path:
    """The personal brain acted on: ``start`` (default: the repo above the current folder) when it has a neutral
    source, else the brain its config.json is found in (brain.config), else the checkout that holds this package."""
    from . import config, paths
    here = Path(start) if start else paths.find_root()
    if applies(here):
        return here
    cfg = config.load(here)
    if cfg.file and applies(cfg.root):
        return cfg.root
    return paths.personal_root() or paths.package_repo() or here


def engine_procedures() -> Path:
    """The procedures the engine ships (package data)."""
    return Path(__file__).resolve().parent / PROCEDURES


def parse_rules(text: str, file: Path, rel: str, *, scope: str = "", project: bool = False) -> RuleFile:
    """A rules file: its front matter and its ``## `` sections, each with the meta of its first line."""
    meta, body = ({}, lf(text)) if project else front_matter(text)
    scope = str(meta.get("scope") or scope)
    head = len(lf(text).splitlines()) - len(body.splitlines())   # lines before the body (the front matter)
    lines = body.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    preamble = "".join(lines[: starts[0]] if starts else lines)
    rules = []
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        section = lines[i:end]
        info: dict[str, str] = {}
        m = _META.match(section[1].rstrip("\n")) if len(section) > 1 else None
        if m and (not project or (_meta(m.group(1)) and set(_meta(m.group(1))) <= META_KEYS)):
            info = _meta(m.group(1))   # a project's other comments stay its text
            section = section[:1] + section[2:]
        globs = [p.strip() for p in info.get("paths", "").split(",") if p.strip()]
        if globs:   # said in the text: an agent that loads every rule still reads where this one applies
            section = section[:1] + ["\n", f"Applies to files matching {', '.join(f'`{g}`' for g in globs)}.\n"] \
                + section[1:]
        rules.append(Rule(id=info.get("id", ""), title=lines[i][3:].strip(), text="".join(section), scope=scope,
                          file=file, line=head + i + 1, overrides=info.get("overrides", ""), paths=globs))
    lock = meta.get("lock") or []
    return RuleFile(file=file, rel=rel, scope=scope, meta=meta, preamble=preamble, rules=rules,
                    lock=[str(x) for x in lock] if isinstance(lock, list) else [], project=project)


def _meta(text: str) -> dict[str, str]:
    """``id: rule-x; overrides: rule-y`` -> {id, overrides}; an unknown key is kept for check() to report."""
    out = {}
    for part in text.split(";"):
        key, sep, value = part.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def load(root: Path) -> Source:
    """The neutral source of the brain at ``root``. Never raises: what is wrong is in ``errors`` (check() adds the
    cross-checks)."""
    base = folder(root)
    src = Source(root=Path(root).resolve(), folder=base)
    f = base / PACKS
    if not f.is_file():
        src.errors.append(f"{f} not found")
        return src
    try:
        data = load_yaml(f.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        src.errors.append(f"{PACKS}: not readable YAML ({exc})")
        return src
    src.data = data if isinstance(data, dict) else {}
    packs = src.data.get("packs")
    for pid, spec in (packs.items() if isinstance(packs, dict) else []):
        src.packs.append(Pack(str(pid), spec if isinstance(spec, dict) else {}))
    for rf in sorted((base / RULES).rglob("*.md")) if (base / RULES).is_dir() else []:
        rel = rf.relative_to(base).as_posix()
        default = rf.stem if rel.startswith(SCOPES + "/") else ""
        src.rule_files[rel] = parse_rules(rf.read_text(encoding="utf-8"), rf, rel, scope=default)
    for name in sorted({p.name for d in (engine_procedures(), base / PROCEDURES) if d.is_dir()
                        for p in d.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))}):
        src.procedures[name] = _procedure(name, base)
    mf = base / MCP
    if mf.is_file():
        try:
            mcp = load_yaml(mf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            src.errors.append(f"{MCP}: not readable YAML ({exc})")
            mcp = {}
        servers = mcp.get("servers") if isinstance(mcp, dict) else None
        for name, spec in (servers.items() if isinstance(servers, dict) else []):
            src.servers[str(name)] = Server(str(name), spec if isinstance(spec, dict) else {})
    return src


def _procedure(name: str, base: Path) -> Procedure:
    files: dict[str, Path] = {}
    engine = engine_procedures() / name
    for d in (engine, base / PROCEDURES / name):   # the owner's files laid over the engine's
        if d.is_dir():
            for p in sorted(d.rglob("*")):
                if p.is_file() and "__pycache__" not in p.parts:
                    files[p.relative_to(d).as_posix()] = p
    meta = front_matter(files[SKILL].read_text(encoding="utf-8"))[0] if SKILL in files else {}
    return Procedure(name=name, files=files, meta=meta, engine=engine.is_dir())


def project_rules(root: Path, project: str) -> RuleFile | None:
    """A project's own rules (its CLAUDE.md), as the nearest scope of its chain; None when it has none here."""
    for name in PROJECT_RULES:
        f = Path(root) / name
        if f.is_file():
            return parse_rules(f.read_text(encoding="utf-8"), f, name, scope=project, project=True)
    return None


def ancestors(src: Source, project: str) -> list[str]:
    """The scope nodes between global and ``project``, from the root down. None yet: the scope tree's parents come
    with wi-brain-scope-tree (projects.yaml ``parent:``, scopes.yaml)."""
    return []


def chain(src: Source, project: str | None, project_root: Path | None = None) -> list[RuleFile]:
    """A project's rules, broadest first and nearest last: the global files, each ancestor's, then the project's own
    (spec-brain-scope-tree §3.7). No project: the global files alone."""
    files = src.scope_files(GLOBAL)
    for node in ancestors(src, project) if project else []:
        files += src.scope_files(node)
    if project and project_root is not None:
        own = project_rules(project_root, project)
        if own:
            files.append(own)
    return files


# --- checking -------------------------------------------------------------------------------------------------------

def check(src: Source, nodes: list[str] | None = None) -> list[str]:
    """What is wrong in the neutral source: its files, the packs' references, the rules' ids and scopes (``nodes``:
    the scope nodes that exist, default global and the registered projects), the procedures (Agent Skills' name and
    description), the MCP servers, then the rule ids against the graph's Rule nodes."""
    errors = list(src.errors)
    if not src.data:
        return errors
    readonly: set[str] = set()
    invalid: dict[str, object] = {}
    if nodes is None:
        from . import projects
        nodes = [GLOBAL, *(p.name for p in projects.load(src.root).values())]
        readonly = set(projects.readonly(src.root))
        invalid = projects.invalid_access(src.root)   # a typo in access: named as one, never as read only
    known = set(nodes) | {GLOBAL}
    from . import schema
    refused = schema.newer(PACKS, src.data.get("v"))
    if refused:          # a newer brain's packs: refused whole, never rendered half understood
        return errors + [refused]
    for key in src.data:
        if key not in ("v", "marketplace", "pointers", "packs"):
            errors += schema.tolerate(f"{PACKS}: unknown key {key!r}")
    if not src.packs:
        errors.append(f"{PACKS}: no packs")
    cores = [p.id for p in src.packs if p.core]
    if len(cores) != 1:
        errors.append(f"{PACKS}: one pack must be core: true (the one every session gets), found {cores or 'none'}")
    ids: dict[str, str] = {}
    for rel, rf in src.rule_files.items():
        where = f"{RULES}/{rel.split('/', 1)[1]}" if "/" in rel else rel
        for k in rf.meta:
            if k not in RULE_FILE_KEYS and not isinstance(rf.meta[k], dict):
                errors.append(f"{where}: unknown front matter key {k!r}")
            elif isinstance(rf.meta[k], dict) and set(rf.meta[k]) - TARGET_TEXT_KEYS:
                errors.append(f"{where}: {k}: only {sorted(TARGET_TEXT_KEYS)} (got {sorted(rf.meta[k])})")
        if not rf.scope:
            errors.append(f"{where}: no scope (front matter scope: global, a project or a scope node)")
        elif rf.scope in readonly:
            errors.append(f"{where}: scope {rf.scope!r} is a read-only project: the brain never writes its rules (its "
                          "own sessions do)")
        elif rf.scope in invalid:
            errors.append(f"{where}: scope {rf.scope!r} is not loaded: access is read or write, not "
                          f"{invalid[rf.scope]!r}")
        elif rf.scope not in known:
            errors.append(f"{where}: scope {rf.scope!r} is not a node of the scope tree ({', '.join(sorted(known))})")
        if rf.preamble.strip():
            errors.append(f"{where}: text before the first rule (a rule is a '## ' section; the intro goes in the "
                          "front matter)")
        if not rf.rules and not rel.startswith(SCOPES + "/"):   # a scope's file may hold its front matter only
            errors.append(f"{where}: no rule (one '## ' section per rule)")
        elif not rf.rules and rf.lock:
            errors.append(f"{where}: lock in a scope file without a rule (it renders nothing and locks nothing: lock a "
                          "rule where it is written)")
        for r in rf.rules:
            at = f"{where}:{r.line}"
            if not r.id:
                errors.append(f"{at}: rule {r.title!r} has no id (its first line: <!-- id: rule-x -->)")
            elif not RULE_ID.fullmatch(r.id):
                errors.append(f"{at}: rule id {r.id!r} is not kebab-case")
            elif r.id in ids:
                errors.append(f"{at}: rule id {r.id} already in {ids[r.id]}")
            else:
                ids[r.id] = at
    for rel, rf in src.rule_files.items():
        for r in rf.rules:
            m = _META.match(r.text.splitlines()[1]) if len(r.text.splitlines()) > 1 else None
            if m:
                errors.append(f"{rel}:{r.line}: a second meta line under {r.title!r}")
        for lid in rf.lock:
            if lid not in ids:
                errors.append(f"{rel}: lock {lid!r} names no rule")
    errors += _check_meta_keys(src)
    for p in src.packs:
        for k in p.spec:
            if k not in PACK_KEYS and not isinstance(p.spec[k], dict):
                errors.append(f"{PACKS}: pack {p.id}: unknown key {k!r}")
        for rel in p.items("rules"):
            if rel not in src.rule_files:
                errors.append(f"{PACKS}: pack {p.id}: rules {rel!r} not in {FOLDER}/")
        for name in p.items("procedures"):
            if name not in src.procedures:
                errors.append(f"{PACKS}: pack {p.id}: procedure {name!r} not in {FOLDER}/{PROCEDURES}/ nor the "
                              "engine's")
        for name in p.items("mcp"):
            if name not in src.servers:
                errors.append(f"{PACKS}: pack {p.id}: MCP server {name!r} not in {MCP}")
        for proj in p.projects or []:
            if proj in readonly:
                errors.append(f"{PACKS}: pack {p.id}: project {proj!r} is read only: the brain renders nothing for it")
            elif proj in invalid:
                errors.append(f"{PACKS}: pack {p.id}: project {proj!r} is not loaded: access is read or write, not "
                              f"{invalid[proj]!r}")
            elif proj not in known:
                errors.append(f"{PACKS}: pack {p.id}: project {proj!r} is not registered")
    for name, proc in src.procedures.items():
        errors += _check_procedure(name, proc)
    for name, s in src.servers.items():
        errors += _check_server(name, s)
    errors += _check_graph(src, ids)
    return errors


def _check_meta_keys(src: Source) -> list[str]:
    out = []
    for rel, rf in src.rule_files.items():
        for r in rf.rules:
            lines = lf(r.file.read_text(encoding="utf-8")).splitlines()
            m = _META.match(lines[r.line]) if r.line < len(lines) else None
            for k in _meta(m.group(1)) if m else {}:
                if k not in META_KEYS:
                    out.append(f"{rel}:{r.line}: unknown rule meta key {k!r} ({', '.join(sorted(META_KEYS))})")
    return out


def _check_procedure(name: str, proc: Procedure) -> list[str]:
    where = f"{PROCEDURES}/{name}"
    if SKILL not in proc.files:
        return [f"{where}: no {SKILL}"]
    out = []
    got = proc.meta.get("name")
    if got != name:
        out.append(f"{where}/{SKILL}: name {got!r}, the folder is {name!r}")
    if not SKILL_NAME.fullmatch(name) or len(name) > SKILL_NAME_MAX:
        out.append(f"{where}: the name must be lowercase letters, digits and hyphens, {SKILL_NAME_MAX} at most")
    desc = proc.meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        out.append(f"{where}/{SKILL}: no description")
    elif len(desc) > SKILL_DESCRIPTION_MAX:
        out.append(f"{where}/{SKILL}: description of {len(desc)} characters, {SKILL_DESCRIPTION_MAX} at most")
    return out


def _check_server(name: str, s: Server) -> list[str]:
    where = f"{MCP}: {name}"
    out = [f"{where}: unknown key {k!r}" for k in s.spec if k not in SERVER_KEYS]
    t = s.transport
    if t not in TRANSPORTS:
        out.append(f"{where}: transport {t!r} ({', '.join(TRANSPORTS)})")
    elif t == "stdio" and not s.spec.get("command"):
        out.append(f"{where}: a stdio server needs a command")
    elif t != "stdio" and not s.spec.get("url"):
        out.append(f"{where}: a {t} server needs a url")
    for key in ("env", "headers"):
        if key in s.spec and not isinstance(s.spec[key], dict):
            out.append(f"{where}: {key} is a mapping")
    if "args" in s.spec and not isinstance(s.spec["args"], list):
        out.append(f"{where}: args is a list")
    return out


def _check_graph(src: Source, ids: dict[str, str]) -> list[str]:
    """Each rule id an active Rule node of the brain's main store, and each active Rule node anchored in the source
    carried by a section (a rule removed from the source turns its node retired)."""
    from . import graph
    store = src.root / "notes" / "graph"
    if not (store / "schema.yaml").is_file():
        return []
    index = graph.node_index(store)
    out = []
    for rid, at in ids.items():
        node = index.get(rid, (None, {}))[1]
        if node.get("type") != "Rule":
            out.append(f"{at}: {rid} is not a Rule node of notes/graph (a new rule gets its node, CLAUDE.md)")
        elif node.get("status") != "active":
            out.append(f"{at}: {rid} is {node.get('status')!r} in notes/graph, not active")
    prefix = src.folder.relative_to(src.root).as_posix() + "/" if src.folder.is_relative_to(src.root) else None
    for nid, (_, node) in index.items():
        anchor = str(node.get("anchor") or "")
        if (node.get("type") == "Rule" and node.get("status") == "active" and prefix and anchor.startswith(prefix)
                and nid not in ids):
            out.append(f"notes/graph: {nid} is anchored at {anchor} but no rule of the source has that id "
                       "(retire the node, or give the section its id)")
    return out


def lock_findings(src: Source, projects_roots: dict[str, Path] | None = None) -> list[str]:
    """The lower rules that declare ``overrides:`` a rule locked higher in their chain, and the overrides that name
    no rule: one line each. ``projects_roots`` ({project: root}) adds each project's own CLAUDE.md."""
    known = {r.id for rf in src.rule_files.values() for r in rf.rules if r.id}
    out = []
    for project, root in (projects_roots or {None: None}).items():
        files = chain(src, project, root)
        for i, rf in enumerate(files):
            locked = {lid: f.rel for f in files[:i] for lid in f.lock}
            for r in rf.rules:
                if not r.overrides:
                    continue
                where = f"{rf.file}:{r.line}" if rf.project else f"{rf.rel}:{r.line}"
                if r.overrides in locked:
                    out.append(f"{where}: {r.id or r.title!r} overrides {r.overrides}, locked by {locked[r.overrides]}")
                elif r.overrides not in known:
                    out.append(f"{where}: {r.id or r.title!r} overrides {r.overrides}, which names no rule")
    return sorted(set(out))
