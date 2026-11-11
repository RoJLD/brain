"""Data classes per store (wi-brain-data-classes).

Every store of a personal brain declares its class in ``config.json`` (``classes.stores``), and the class says where
the store may go and how. The engine holds the classes and their matrix (:data:`POLICY`: a class by an exit gives
``clear``, ``sealed``, ``opt-in`` or ``never``); the personal brain holds the stores::

    "classes": {"stores": {
        "memory": {"class": "confidential", "paths": ["memory/**"], "to": ["devices", "cloud-model"],
                   "waive": {"git-private": "in clear in the private remote until the encrypted-git trial decides"}},
        "ledger": {"class": "sealed", "paths": ["$BRAIN_HOME/ledger"], "to": ["offsite", "backup"]},
        "repo":   {"class": "private", "paths": ["**"]}}}

A path is a glob over the brain repo's tracked files (``**`` any folders, ``*`` within a name), or a machine path
outside the repo: ``$BRAIN_HOME/...`` or ``~/...``. The first store whose glob matches a tracked file classes it,
in the order of the file, so specific stores come first and a catch-all last.

:func:`check` (``brain classes --check``, ``brain check --all``) refuses:

- a store without a valid class, an unknown exit, a waiver without its reason (15 characters or more);
- a tracked file that no store classes;
- a destination its class forbids: an exit in ``to`` the class says ``never`` for, and the git reality: tracked
  files whose class does not allow the repo's remote in clear (``git-private``, or ``git-public`` when the remote is
  one of ``public.repos``);
- a class under the floor of its project's scope chain (``classes: {floor: ...}`` on the nodes of ``scopes.yaml``,
  spec-brain-scope-tree §3.9). Until the scope tree's registry exists, :func:`scope_chain` reads it when present and
  finds no floor otherwise.

The engine's own stores outside the repo (:data:`ENGINE_STORES`: every name it writes under BRAIN_HOME, and the
transcripts) each carry a suggested data class and a format class (truth-local, log, derived, install, external). One
that a brain does not declare is never without a class: it takes its suggested one, never looser than sealed (secret
for the secrets), and the check notes it without failing (COMPAT-6); ``brain classes --suggest`` prints the lines to
declare. A name in BRAIN_HOME that no store covers is noted too, sealed by default.

The engine also reads :data:`SOURCES` it never writes: the desktop app's session metadata is read through a closed
list of keys, never its text keys (:data:`APP_TEXT_KEYS`: the turn report, the pending reminders, the prompt
snapshots, the connectors' configuration); :func:`outside` says which keys a reader took beyond the list.

A waiver (``waive: {exit: reason}``) keeps a known gap visible: ``brain classes`` and the check print it, it is never
silent. :func:`decide` is what an exit's adapter asks before a store leaves (the session archive, the data remote,
a notes service): ``clear``, ``sealed`` (only through ``brain vault seal``) or ``never``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import boundary, config, graph, paths, projects

CLASSES = ("public", "private", "confidential", "sealed", "resident", "secret")
TENANT = "tenant:"                      # tenant:<id>, a hosted team's store: sealed to its own recipients only
TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RANK = {c: i for i, c in enumerate(CLASSES)}   # the floor's order; a tenant's store ranks as confidential

CLASS_TEXT = {
    "public": "free to publish once brain check --public passes: the engine, domain templates",
    "private": "the private repo in clear; off the machine otherwise only sealed: rules, graph, ADRs, specs",
    "confidential": "never in clear in git or with a third party: decisions touching money or people, memory, "
                    "heirs and members, a scope tree that names employers",
    "sealed": "never in git; off the machine only sealed client-side: transcripts, ledgers, session states, "
              "datasets, indexes, backups",
    "resident": "never leaves the machine, even sealed: data under a residency clause",
    "secret": "never in the brain: key values, tokens, passwords and key shares live in a keystore",
    "tenant": "a hosted team's store (tenant:<id>): its own private repo, sealed to its own recipients only",
}

EXITS = {
    "git-public": "a public git repo",
    "git-private": "the private repo's remote (a code host, GitHub)",
    "offsite": "a copy outside git that leaves the machine: a NAS, a data remote, a dataset host, an archive",
    "backup": "the backups",
    "devices": "the owner's other devices: a second machine, a phone's sync",
    "third-party": "a third-party notes or documents service",
    "cloud-model": "a cloud model's context",
    "local-model": "a local model's context",
}
HOW = ("clear", "sealed", "opt-in", "never")

# How each class may reach each exit: clear (as it is), sealed (only sealed client-side, brain vault seal), opt-in
# (only when the store names the exit in its ``to``), never.
_ROW = {
    "public":       ("clear", "clear", "clear", "clear", "clear", "clear", "clear", "clear"),
    "private":      ("never", "clear", "sealed", "sealed", "clear", "opt-in", "clear", "clear"),
    "confidential": ("never", "sealed", "sealed", "sealed", "clear", "never", "opt-in", "clear"),
    "sealed":       ("never", "never", "sealed", "sealed", "sealed", "never", "never", "opt-in"),
    "resident":     ("never", "never", "never", "never", "never", "never", "never", "clear"),
    "secret":       ("never", "never", "never", "never", "never", "never", "never", "never"),
    "tenant":       ("never", "clear", "sealed", "sealed", "never", "never", "opt-in", "clear"),
}
POLICY = {c: dict(zip(EXITS, row)) for c, row in _ROW.items()}

# How a store is read and written (spec-brain-data-compat §1, its format class); its data class says where it may go.
FORMATS = {
    "truth-local": "one machine, no git: what nothing else keeps; backed up before a write-back, read-only for an "
                   "engine older than the one that wrote it",
    "log": "append-only, never rewritten; bad or unknown lines are skipped and counted",
    "derived": "rebuilt from the rest (a cache, a view, an index, a stamp): never edited, never migrated",
    "install": "an engine install (a venv, a launcher, a tag's clone): the installer rebuilds it",
    "external": "written by another tool, read by the engine only",
}
FLOOR = "sealed"    # COMPAT-6: an engine store a brain does not declare takes its class, never looser than this


@dataclass(frozen=True)
class Known:
    """One of the engine's own stores outside the repo: where, its suggested data class (the default while a brain
    does not declare it), its format class and what it holds."""
    path: str
    cls: str
    format: str
    what: str


# The engine's own stores outside the repo, a specific path before the folder that holds it. A brain declares each
# (classes.stores); one it does not declare takes its suggested class here, never looser than sealed (secret for the
# secrets), and brain check --all notes it without failing (COMPAT-6). tests/test_classes_home.py fails on a name
# the engine's code writes under BRAIN_HOME that this list does not hold.
ENGINE_STORES = {
    "ledger": Known("$BRAIN_HOME/ledger", "sealed", "log",
                    "the token ledger's events, the session records' lines, the engine's own timings and errors"),
    "sessions": Known("$BRAIN_HOME/sessions", "sealed", "truth-local", "the session records, the children's reports"),
    "resume": Known("$BRAIN_HOME/resume", "sealed", "derived", "the resume packs, one per project"),
    "digest": Known("$BRAIN_HOME/digest", "sealed", "derived", "the digests"),
    "vault": Known("$BRAIN_HOME/vault", "sealed", "truth-local",
                   "the sealed copies, the canaries, the device's public facts and the vault's state"),
    "transcripts": Known("~/.claude/projects", "sealed", "external",
                         "the agent's transcripts: prompts, tool inputs and outputs, sometimes a secret"),
    "usage": Known("$BRAIN_HOME/usage", "sealed", "log",
                   "the token ledger's views, quota.json and quota.jsonl, the session starts, the usage audits"),
    "budget": Known("$BRAIN_HOME/budget", "sealed", "truth-local", "the context budget watch's marks per session"),
    "forecast": Known("$BRAIN_HOME/forecast", "sealed", "derived", "the forecasts, one folder per project"),
    "announce": Known("$BRAIN_HOME/announce", "sealed", "truth-local",
                      "the mid-session marks: the decisions already announced to a session"),
    "handover": Known("$BRAIN_HOME/handover", "sealed", "truth-local",
                      "the hand-over notes and their mirror, the cockpit's launch scripts"),
    "inbox": Known("$BRAIN_HOME/inbox", "sealed", "log", "the owner's messages to sessions"),
    "features": Known("$BRAIN_HOME/features", "sealed", "derived", "the feature stores' indexes (sqlite)"),
    "cache": Known("$BRAIN_HOME/cache", "sealed", "derived",
                   "the app metadata's picked keys (a closed list), the governor's and the guards' caches"),
    "memory-sync": Known("$BRAIN_HOME/memory-sync", "sealed", "truth-local",
                         "the memory export's state, alerts and backups"),
    "schedules": Known("$BRAIN_HOME/schedules", "sealed", "truth-local", "the scheduled tasks this machine installed"),
    "alerts": Known("$BRAIN_HOME/alerts", "sealed", "truth-local", "the alerts already raised and sent"),
    "probes": Known("$BRAIN_HOME/probes", "sealed", "derived", "the dependency probes' last run (brain.depprobes)"),
    "notify": Known("$BRAIN_HOME/notify", "sealed", "truth-local", "the notifications' state and the quiet hours"),
    "secrets": Known("$BRAIN_HOME/secrets", "secret", "truth-local",
                     "the stack bundles' secret files: never copied, never in the brain"),
    "collector": Known("$BRAIN_HOME/stacks/sovereign/data/otel-collector", "sealed", "log",
                       "the telemetry collector's data, after its processors"),
    "stacks": Known("$BRAIN_HOME/stacks", "sealed", "truth-local", "the rendered stack bundles and their data"),
    "telemetry": Known("$BRAIN_HOME/telemetry", "sealed", "truth-local",
                       "the telemetry consent record and the report outbox"),
    "code-index": Known("$BRAIN_HOME/code-index", "sealed", "derived", "the code index's bundles"),
    "code-index-record": Known("$BRAIN_HOME/code-index.json", "sealed", "truth-local", "the repos indexed, and when"),
    "code-map": Known("$BRAIN_HOME/code-map", "sealed", "derived", "the code maps, one per project"),
    "public-check": Known("$BRAIN_HOME/public-check", "sealed", "derived",
                          "the public check's stamps, per repo and commit"),
    "reviews": Known("$BRAIN_HOME/reviews", "sealed", "truth-local", "the reviews' findings and stamps"),
    "backup": Known("$BRAIN_HOME/backup", "sealed", "truth-local",
                     "copies before a write-back: a work tree's settings files, <project>-<key>/<folder>, 10 each"),
    "cockpit": Known("$BRAIN_HOME/tui.json", "sealed", "truth-local", "the cockpit's settings"),
    "update-check": Known("$BRAIN_HOME/update.json", "sealed", "derived", "the last engine tags read, and when"),
    "personal": Known("$BRAIN_HOME/personal.json", "sealed", "truth-local",
                      "the pointer to this machine's personal brain"),
    "profile": Known("$BRAIN_HOME/profile.json", "sealed", "truth-local", "this machine's frozen tier profile"),
    "venv": Known("$BRAIN_HOME/venv", "sealed", "install", "the brain command's own Python environment"),
    "bin": Known("$BRAIN_HOME/bin", "sealed", "install", "the brain command's launcher, alone on the PATH"),
    "engine-clones": Known("$BRAIN_HOME/engine", "sealed", "install",
                           "the engine tags' clones an installer or a shim keeps"),
}
# The suggested class of each engine store: {name: (path, class)}.
KNOWN = {name: (k.path, k.cls) for name, k in ENGINE_STORES.items()}
TRANSCRIPTS = "~/.claude/projects"      # read under $CLAUDE_CONFIG_DIR when it is set (brain.paths.projects_dir)
# A write's leftover beside an engine store's file, the same store: a name ending in .tmp, .bak or .lock, or set
# aside with its stamp (``<name>.unreadable-<UTC stamp>``, brain.stateio). Told by the suffix, never by a substring:
# export.tmpl or sync.lockfile is a name of its own.
HOME_TRANSIENT = re.compile(r"\.(?:tmp|bak|lock)$|\.unreadable-\d")


@dataclass(frozen=True)
class Source:
    """What the engine reads outside its stores and never writes: where, and the closed list of keys it may read
    (``keys``; a key's own list in ``nested``, ``key.*`` for the entries of a mapping; None: whole files are read).
    ``never`` names the keys that hold texts: never read, never copied into a store."""
    path: str
    what: str
    keys: frozenset | None = None
    nested: dict = field(default_factory=dict)
    never: tuple = ()


# The desktop app's session metadata (ST-1, spec-brain-session-telemetry §3.7): brain.sessions, brain.governor,
# brain.tidy and the capture hook (through brain.sessions) read these keys and no other; tests/test_classes_home.py
# holds every reader to them and checks that no text key reaches a store.
APP_TEXT_KEYS = ("lastTurnReport", "pendingSystemReminder", "promptAppendSnapshot", "remoteMcpServersConfig",
                 "spawnSeed")
APP_SESSION_KEYS = frozenset({"sessionId", "cliSessionId", "title", "createdAt", "lastActivityAt", "isArchived",
                              "completedTurns", "model", "effort", "branch", "lineageDetached", "spawnedFrom", "prs",
                              "cwd"})
APP_SPAWN_KEYS = frozenset({"sessionId", "taskId", "name", "sideSession"})
SOURCES = {
    "app-sessions": Source("$LOCALAPPDATA/Claude-Data/*/claude-code-sessions",
                           "the desktop app's metadata of each session: both ids, the parent, the dates, the state",
                           APP_SESSION_KEYS, {"spawnedFrom": APP_SPAWN_KEYS}, APP_TEXT_KEYS),
    "app-worktrees": Source("$LOCALAPPDATA/Claude-Data/*/git-worktrees.json",
                            "the desktop app's worktrees and the session leasing each",
                            frozenset({"worktrees"}), {"worktrees.*": frozenset({"path", "leasedBy"})}),
    "app-notes": Source("$LOCALAPPDATA/Claude-Data/*/side-session-notes",
                        "the notes a family of sessions shares: read whole by brain resume and the briefs, never "
                        "written"),
}


def outside(source: str, read) -> list[str]:
    """The keys of ``read`` (``key``, ``key.sub`` or ``key.*.sub``) that the source's closed list does not allow,
    sorted; a text key always counts, at any depth."""
    src = SOURCES[source]
    if src.keys is None:
        return []
    bad = []
    for k in set(read):
        parts = k.split(".")
        if any(p in src.never for p in parts):
            bad.append(k)
        elif len(parts) == 1:
            if parts[0] not in src.keys:
                bad.append(k)
        else:
            parent, sub = ".".join(parts[:-1]), parts[-1]
            allowed = src.nested.get(parent)
            if parts[0] not in src.keys or allowed is None or sub not in allowed:
                bad.append(k)
    return sorted(bad)
STORE_KEYS = {"class", "paths", "to", "waive", "project", "why"}
REASON_MIN = 15
SEALED_SUFFIXES = (".age", ".gpg")      # a tracked file that is already sealed is not in clear
PLACEHOLDERS = (".gitkeep", ".keep")    # an empty one keeps a folder in git: no data, so never in clear
SCOPES = "scopes.yaml"


class ClassError(ValueError):
    """A bad classes block (brain classes exits 2)."""


@dataclass
class Store:
    name: str
    cls: str
    globs: list[str] = field(default_factory=list)      # over the repo's tracked files
    machine: list[str] = field(default_factory=list)    # $BRAIN_HOME/... or ~/..., as declared
    to: list[str] = field(default_factory=list)
    waive: dict[str, str] = field(default_factory=dict)
    project: str = ""
    why: str = ""
    regexes: list = field(default_factory=list, repr=False)

    @property
    def kind(self) -> str:
        """The class's row in :data:`POLICY`: tenant for tenant:<id>."""
        return "tenant" if self.cls.startswith(TENANT) else self.cls

    @property
    def rank(self) -> int:
        return RANK["confidential"] if self.kind == "tenant" else RANK[self.cls]


def class_ok(cls) -> bool:
    if not isinstance(cls, str):
        return False
    if cls.startswith(TENANT):
        return bool(TENANT_ID.match(cls[len(TENANT):]))
    return cls in CLASSES


def how(cls: str, exit_: str) -> str:
    """The matrix: clear, sealed, opt-in or never for a class and an exit."""
    return POLICY["tenant" if cls.startswith(TENANT) else cls][exit_]


def is_machine(path: str) -> bool:
    return path.startswith(("$BRAIN_HOME", "~"))


def expand(path: str) -> Path:
    """A machine path: $BRAIN_HOME/... under brain_home(), ~/... under the home folder (~/.claude/projects/... under
    $CLAUDE_CONFIG_DIR when the variable is set)."""
    if path.rstrip("/") == "$BRAIN_HOME":
        return paths.brain_home()
    if path.startswith("$BRAIN_HOME/"):
        return paths.brain_home() / path[len("$BRAIN_HOME/"):]
    if path.rstrip("/") == TRANSCRIPTS or path.startswith(TRANSCRIPTS + "/"):
        return paths.projects_dir() / path[len(TRANSCRIPTS) + 1:]
    return Path(path).expanduser()


def stores(cfg: config.Config) -> tuple[list[Store], list[str]]:
    """The declared stores in their order, and what is wrong in their shape."""
    block = cfg.data.get("classes")
    if block is None:
        return [], []
    errors: list[str] = []
    if not isinstance(block, dict) or not isinstance(block.get("stores"), dict):
        return [], ["classes: a mapping with stores: {name: {class, paths, to, waive}}"]
    out = []
    for name, d in block["stores"].items():
        where = f"classes.stores.{name}"
        if not isinstance(d, dict):
            errors.append(f"{where}: a mapping with class and paths")
            continue
        unknown = set(d) - STORE_KEYS
        if unknown:
            errors.append(f"{where}: unknown key(s) {', '.join(sorted(unknown))} (known: {', '.join(sorted(STORE_KEYS))})")
        cls = d.get("class")
        if not class_ok(cls):
            errors.append(f"{where}: class {cls!r} is not one of {', '.join(CLASSES)} or {TENANT}<id>")
            continue
        globs = d.get("paths")
        if not isinstance(globs, list) or not globs or not all(isinstance(g, str) and g for g in globs):
            errors.append(f"{where}: paths is a non-empty list of globs or machine paths")
            continue
        to = d.get("to") or []
        if not isinstance(to, list) or any(t not in EXITS for t in to):
            errors.append(f"{where}: to names exits among {', '.join(EXITS)}")
            to = [t for t in to if t in EXITS] if isinstance(to, list) else []
        waive = d.get("waive") or {}
        if not isinstance(waive, dict):
            errors.append(f"{where}: waive is {{exit: reason}}")
            waive = {}
        for exit_, reason in waive.items():
            if exit_ not in EXITS:
                errors.append(f"{where}: waive names an unknown exit {exit_!r}")
            elif not isinstance(reason, str) or len(reason.strip()) < REASON_MIN:
                errors.append(f"{where}: waive.{exit_} needs its reason ({REASON_MIN} characters or more)")
        s = Store(name, cls, [g for g in globs if not is_machine(g)], [g for g in globs if is_machine(g)],
                  list(to), {k: str(v) for k, v in waive.items() if k in EXITS}, str(d.get("project") or ""),
                  str(d.get("why") or ""))
        s.regexes = [boundary.glob_regex(g.rstrip("/")) for g in s.globs]
        out.append(s)
    return out, errors


def classify(declared: list[Store], files: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """({store: [tracked files]}, [files no store classes]): the first store whose glob matches wins."""
    by: dict[str, list[str]] = {s.name: [] for s in declared}
    orphans = []
    for f in files:
        for s in declared:
            if any(r.match(f) for r in s.regexes):
                by[s.name].append(f)
                break
        else:
            orphans.append(f)
    return by, orphans


def store_of(declared: list[Store], path: str) -> Store | None:
    """The store that classes a repo path (/-separated, relative) or a machine path ($BRAIN_HOME/..., ~/...)."""
    if is_machine(path):
        target = expand(path)
        for s in declared:
            for m in s.machine:
                base = expand(m)
                if target == base or base in target.parents:
                    return s
        return None
    for s in declared:
        if any(r.match(path) for r in s.regexes):
            return s
    return None


def default_stores(declared: list[Store]) -> list[Store]:
    """The engine stores (:data:`ENGINE_STORES`) that no declared store covers, each a store of its suggested class:
    the class it takes until the brain declares it (COMPAT-6)."""
    return [Store(name, k.cls, [], [k.path]) for name, k in ENGINE_STORES.items() if not store_of(declared, k.path)]


def effective(declared: list[Store]) -> list[Store]:
    """The declared stores, then the engine stores they leave out at their default class: what a path or an exit is
    decided by."""
    return declared + default_stores(declared)


def home_unknown(declared: list[Store]) -> list[str]:
    """The names at the top of BRAIN_HOME that neither a declared store nor an engine store covers (a store written
    by a newer or another engine, or by hand); a write's leftover (``.tmp``, ``.bak``...) is not counted."""
    try:
        names = sorted(p.name for p in paths.brain_home().iterdir())
    except OSError:
        return []
    every = effective(declared)
    return [n for n in names if not HOME_TRANSIENT.search(n) and not store_of(every, f"$BRAIN_HOME/{n}")]


def tracked(root: Path) -> list[str]:
    try:
        return boundary.tracked(root)
    except (boundary.BoundaryError, OSError, subprocess.SubprocessError):
        return []


def remote_exit(root: Path, cfg: config.Config) -> str:
    """git-public when the repo's origin is one of public.repos, git-private when it has another remote, '' when it
    pushes nowhere."""
    try:
        out = subprocess.run(["git", "-C", str(root), "remote", "-v"], capture_output=True, text=True,
                             timeout=10, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    urls = {line.split()[1] for line in out.splitlines() if len(line.split()) >= 2}
    if not urls:
        return ""
    pub = cfg.data.get("public") if isinstance(cfg.data.get("public"), dict) else {}
    for repo in pub.get("repos") or []:
        name = str(repo).lower()
        if any(re.search(rf"[:/]{re.escape(name)}(?:\.git)?/?$", u.lower()) for u in urls):
            return "git-public"
    return "git-private"


# --- the scope tree (spec-brain-scope-tree §3.9, §3.13): read when present ---
def scopes_file(cfg: config.Config) -> Path | None:
    """$BRAIN_SCOPES, else config.json's scopes, else scopes.yaml beside the registry; None when there is none."""
    env = os.environ.get("BRAIN_SCOPES")
    if env:
        f = Path(env).expanduser()
    elif isinstance(cfg.data.get("scopes"), str):
        f = cfg.root / cfg.data["scopes"]
    else:
        f = cfg.root / SCOPES
    return f if f.is_file() else None


def scope_nodes(cfg: config.Config) -> dict[str, dict]:
    """{node id: its mapping} from scopes.yaml (``scopes:``), {} when there is no tree yet."""
    f = scopes_file(cfg)
    if not f:
        return {}
    data = graph.load_yaml_file(f) or {}
    nodes = data.get("scopes") if isinstance(data, dict) else None
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in nodes.items()} if isinstance(nodes, dict) else {}


def own_project(cfg: config.Config) -> str:
    """The registry's project whose root is the brain's root (the brain's own stores belong to it), else ''."""
    try:
        for name, p in projects.load(cfg.root).items():
            if p.root.resolve() == cfg.root.resolve():
                return name
    except Exception:  # noqa: BLE001 - a broken registry is projects.check's to report
        return ""
    return ""


def scope_chain(cfg: config.Config, project: str, nodes: dict[str, dict] | None = None) -> list[str]:
    """The node ids above a project, nearest first, up to (not including) global: its ``parent:`` in the registry,
    then each node's ``parent``. [] without a tree or a parent."""
    nodes = scope_nodes(cfg) if nodes is None else nodes
    if not nodes or not project:
        return []
    try:
        entry = projects.raw(cfg.root).get(project) or {}
    except Exception:  # noqa: BLE001
        entry = {}
    node = entry.get("parent") if isinstance(entry, dict) else None
    chain: list[str] = []
    while isinstance(node, str) and node and node != "global" and node not in chain:
        chain.append(node)
        node = (nodes.get(node) or {}).get("parent")
    return chain


def floor(cfg: config.Config, project: str, nodes: dict[str, dict] | None = None) -> tuple[str, str]:
    """(the strictest class floor along the project's scope chain, the node that sets it), ('', '') without one."""
    nodes = scope_nodes(cfg) if nodes is None else nodes
    best, where = "", ""
    for node in scope_chain(cfg, project, nodes):
        f = ((nodes.get(node) or {}).get("classes") or {}).get("floor")
        if f in CLASSES and (not best or RANK[f] > RANK[best]):
            best, where = f, node
    return best, where


@dataclass
class Report:
    stores: list[Store]
    errors: list[str] = field(default_factory=list)
    waived: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    files: dict[str, list[str]] = field(default_factory=dict)
    remote: str = ""
    declared: bool = False
    defaulted: list[Store] = field(default_factory=list)   # engine stores undeclared, at their suggested class
    unknown: list[str] = field(default_factory=list)       # names in BRAIN_HOME no store covers
    home_notes: list[str] = field(default_factory=list)    # what brain check --all prints of the two


def home_notes(defaulted: list[Store], unknown: list[str]) -> list[str]:
    """The notes of the engine stores a brain leaves undeclared and of the names in BRAIN_HOME no store covers: they
    never fail a check (COMPAT-6)."""
    out = []
    if defaulted:
        out.append(f"{len(defaulted)} engine store(s) undeclared take their suggested class by default: "
                   + ", ".join(f"{s.name} ({s.cls})" for s in defaulted)
                   + " (brain classes --suggest prints the lines to declare)")
    if unknown:
        out.append(f"{len(unknown)} name(s) in BRAIN_HOME that no store covers, {FLOOR} by default: "
                   + ", ".join(unknown) + " (declare them in classes.stores)")
    return out


def check(root: Path | None = None, cfg: config.Config | None = None) -> Report:
    """Every store has a class and goes only where its class allows; see the module's docstring."""
    cfg = cfg or config.load(root)
    declared, errors = stores(cfg)
    rep = Report(declared, errors, declared="classes" in cfg.data)
    if cfg.file is None:
        rep.notes.append("no config.json: no class declared")
        return rep
    if not rep.declared:
        rep.errors.append(f"{config.FILE} declares no data classes (classes.stores): every store needs one "
                          "(brain classes --suggest prints a starting set)")
        return rep
    files = tracked(cfg.root)
    rep.files, orphans = classify(declared, files)
    if orphans:
        rep.errors.append(f"{len(orphans)} tracked file(s) have no class (no store's glob matches): "
                          + ", ".join(orphans[:5]) + (" ..." if len(orphans) > 5 else ""))
    rep.defaulted = default_stores(declared)
    rep.unknown = home_unknown(declared)
    rep.home_notes = home_notes(rep.defaulted, rep.unknown)
    rep.notes += rep.home_notes
    rep.remote = remote_exit(cfg.root, cfg)
    by_name = {s.name: s for s in declared}
    for s in declared:
        for exit_ in s.to:
            if how(s.cls, exit_) == "never":
                _refuse(rep, s, exit_, f"store {s.name} ({s.cls}) declares {exit_}, which its class forbids")
        clear = [f for f in rep.files.get(s.name, []) if not f.endswith(SEALED_SUFFIXES)
                 and not placeholder(cfg.root, f)]
        if clear and rep.remote and how(s.cls, rep.remote) not in ("clear",):
            allowed = how(s.cls, rep.remote)
            _refuse(rep, s, rep.remote,
                    f"store {s.name} ({s.cls}): {len(clear)} tracked file(s) go to {rep.remote} in clear, which its "
                    + ("class forbids" if allowed == "never" else f"class allows {allowed} only"),
                    " (untrack them, seal them, or waive it with its reason)")
    _floors(cfg, rep, by_name)
    return rep


def placeholder(root: Path, path: str) -> bool:
    """An empty .gitkeep (or .keep) that only keeps a folder in git: it holds no data, whatever the folder's class."""
    f = root / path
    return f.name in PLACEHOLDERS and f.is_file() and f.stat().st_size == 0


def _refuse(rep: Report, s: Store, exit_: str, line: str, advice: str = "") -> None:
    if exit_ in s.waive:
        rep.waived.append(f"{line}; reason: {s.waive[exit_]}")
    else:
        rep.errors.append(line + advice)


def _floors(cfg: config.Config, rep: Report, by_name: dict[str, Store]) -> None:
    nodes = scope_nodes(cfg)
    if not nodes:
        rep.notes.append("no scope tree (scopes.yaml): no class floor to check")
        return
    own = own_project(cfg)
    for s in by_name.values():
        fl, node = floor(cfg, s.project or own, nodes)
        if fl and s.rank < RANK[fl]:
            rep.errors.append(f"store {s.name} ({s.cls}) is under the floor {fl} that scope {node} sets for "
                              f"project {s.project or own}")


def decide(cfg: config.Config, store: str, exit_: str) -> str:
    """What an exit's adapter may do with a store: clear, sealed or never (opt-in resolved by the store's ``to``,
    a waiver counting as the owner's explicit yes). An engine store the brain does not declare is decided at its
    suggested class (COMPAT-6). Unknown store or exit: never."""
    declared, _ = stores(cfg)
    s = next((x for x in effective(declared) if x.name == store), None)
    if s is None or exit_ not in EXITS:
        return "never"
    h = how(s.cls, exit_)
    if h == "opt-in":
        return "clear" if exit_ in s.to or exit_ in s.waive else "never"
    if h != "clear" and exit_ in s.waive:
        return "clear"
    return h


def engine_line(name: str) -> dict:
    """An engine store's declaration at its suggested class; the stores nothing else keeps (truth-local, log) go to
    the offsite copy and the backups, sealed."""
    k = ENGINE_STORES[name]
    line: dict = {"class": k.cls, "paths": [k.path]}
    if k.format in ("truth-local", "log") and all(how(k.cls, e) != "never" for e in ("offsite", "backup")):
        line["to"] = ["offsite", "backup"]
    return line


def suggest(cfg: config.Config) -> dict:
    """A starting classes block: the engine's machine stores, the brain's own folders by their usual class, and a
    catch-all; brain classes --suggest prints it to edit, never writes it. A brain that already declares classes gets
    only the lines it misses: the engine stores it leaves at their default (a name it already uses gets ``home-``)."""
    if isinstance(cfg.data.get("classes"), dict):
        declared, errors = stores(cfg)
        if not errors:
            names = {s.name for s in declared}
            return {"stores": {(s.name if s.name not in names else f"home-{s.name}"): engine_line(s.name)
                               for s in default_stores(declared)}}
    root = cfg.root
    folders = {"memory": "confidential", "records/ddr": "confidential", "notes": "private", "docs": "private",
               "records": "private"}
    out: dict = {}
    for rel, cls in folders.items():
        if (root / rel).is_dir():
            out[rel.replace("/", "-")] = {"class": cls, "paths": [f"{rel}/**"]}
    for name in ENGINE_STORES:
        out[name] = engine_line(name)
    out["repo"] = {"class": "private", "paths": ["**"]}
    return {"stores": out}


def sources() -> list[str]:
    """The sources the engine reads and never writes, as text lines: where, and the closed list of keys."""
    lines = []
    for name, src in SOURCES.items():
        keys = (f"{len(src.keys)} key(s): " + ", ".join(sorted(src.keys))
                + "".join(f"; {k}: {', '.join(sorted(v))}" for k, v in src.nested.items())) \
            if src.keys is not None else "whole files"
        lines.append(f"source {name}: {src.path}: read only, {keys}"
                     + (f"; never: {', '.join(src.never)}" if src.never else ""))
    return lines


def matrix() -> list[str]:
    """The class by exit matrix as text lines."""
    w = max(len(c) for c in POLICY)
    head = " " * (w + 2) + "  ".join(f"{e:<11}" for e in EXITS)
    rows = [f"{c:<{w}}  " + "  ".join(f"{POLICY[c][e]:<11}" for e in EXITS) for c in POLICY]
    return [head, *rows]


def render(rep: Report) -> list[str]:
    lines = []
    for s in rep.stores:
        where = ([f"{len(rep.files.get(s.name, []))} tracked"] if s.globs else []) + s.machine
        exits = ", ".join(f"{e}:{how(s.cls, e)}" for e in s.to) or "-"
        lines.append(f"{s.name:<14} {s.cls:<13} {'; '.join(where):<34} to {exits}"
                     + (f"  waived: {', '.join(s.waive)}" if s.waive else ""))
    for s in rep.defaulted:
        lines.append(f"{s.name:<14} {s.cls:<13} {'; '.join(s.machine):<34} by default (undeclared)")
    if rep.remote:
        lines.append(f"remote: {rep.remote}")
    lines += sources()
    lines += [f"note: {n}" for n in rep.notes]
    lines += [f"waived: {w}" for w in rep.waived]
    lines += [f"error: {e}" for e in rep.errors]
    lines.append(f"classes: {len(rep.stores)} store(s), " + (f"{len(rep.errors)} error(s)" if rep.errors else "OK")
                 + (f", {len(rep.waived)} waived" if rep.waived else ""))
    return lines


def as_dict(rep: Report) -> dict:
    return {"stores": [{"name": s.name, "class": s.cls, "paths": s.globs + s.machine, "tracked": len(rep.files.get(
        s.name, [])), "to": {e: how(s.cls, e) for e in s.to}, "waive": s.waive, "project": s.project}
        for s in rep.stores], "remote": rep.remote, "errors": rep.errors, "waived": rep.waived, "notes": rep.notes,
        "defaulted": [{"name": s.name, "class": s.cls, "paths": s.machine,
                       "format": ENGINE_STORES[s.name].format} for s in rep.defaulted],
        "unknown": rep.unknown,
        "sources": {n: {"path": src.path, "keys": sorted(src.keys) if src.keys is not None else None,
                        "nested": {k: sorted(v) for k, v in src.nested.items()}, "never": list(src.never)}
                    for n, src in SOURCES.items()}}


def _show_paths(cfg, which: list[str]) -> int:
    """``brain classes PATH...``: the store of each path and its class, a store the brain does not declare shown at
    its default; exit 1 when the declared stores have an error."""
    declared, errs = stores(cfg)
    for e in errs:
        print(f"error: {e}")
    every = effective(declared)
    for p in which:
        s = store_of(every, p)
        if s is None:
            print(f"{p}: no store: no class")
        else:
            own = any(s is d for d in declared)
            print(f"{p}: {s.name} ({s.cls}" + (")" if own else ", by default: undeclared)"))
    return 1 if errs else 0


def main(root: Path | None, *, check_only: bool = False, as_json: bool = False, which: list[str] | None = None,
         suggest_: bool = False, matrix_: bool = False) -> int:
    """``brain classes``: the stores and their classes (exit 1 on an error), ``PATH...`` the store of each path,
    ``--suggest`` a starting block, ``--matrix`` the class by exit matrix."""
    cfg = config.load(root)
    if matrix_:
        print("\n".join(matrix()))
        return 0
    if suggest_:
        print(json.dumps({"classes": suggest(cfg)}, indent=2))
        return 0
    if which:
        return _show_paths(cfg, which)
    rep = check(root, cfg)
    if as_json:
        print(json.dumps(as_dict(rep), indent=2))
    elif check_only:
        for line in ([f"note: {n}" for n in rep.home_notes] + [f"waived: {w}" for w in rep.waived]
                     + [f"error: {e}" for e in rep.errors]):
            print(line)
        print(f"classes: {len(rep.stores)} store(s), " + (f"{len(rep.errors)} error(s)" if rep.errors else "OK"))
    else:
        print("\n".join(render(rep)))
    return 1 if rep.errors else 0
