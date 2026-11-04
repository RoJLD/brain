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
- the machine's pointer ``<BRAIN_HOME>/personal.json`` when the machine has none (the installer writes it too, and
  ``install.ps1 -Personal`` moves it).

The templates name no person, repo or host: the owner is the name given. A template is data and its manifest
(``name``, ``version``, ``engine``: the brain versions that can render it, ``title``, ``files``: {the brain's path:
the template's file, or "" for an empty one}, ``graphs``: the graph stores it starts, a list of {name, store, schema}
whose first is the brain's main store; ``schema: default``, the brain's base of work, decisions and records
(``templates/schemas/default.yaml``), is the only one for now), never code (wi-brain-domain-templates). The plan is
a list of steps, local only: a later step (the owner's repos and data store, created on their keystroke:
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

from . import __version__, classes, config, graph, neutral, paths, render, vault

ENGINE_REPO = "RoJLD/brain"   # where this package is published: config.json engine.repo
TEMPLATES = files(__package__) / "templates"
DEFAULT_TEMPLATE = "generic"
MANIFEST = "template.yaml"
TEMPLATE_KEYS = {"name", "version", "engine", "title", "files", "graphs", "classes"}
GRAPH_KEYS = {"name", "store", "schema"}
SCHEMAS = ("default",)   # templates/schemas/<name>.yaml; a catalogue of graph types comes later
# what config.json names, so every template writes it (a folder through its .gitkeep)
REQUIRED = ("projects.yaml", "rules/global.md", "source/packs.yaml", "memory/.gitkeep", "records/.gitkeep")
TIERS = ("lite", "default")
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

    def read(self, source: str) -> str:
        return (self.folder / source).read_text(encoding="utf-8") if source else ""


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


def load_template(spec: str = DEFAULT_TEMPLATE) -> Template:
    """The template ``spec`` names: one of the package's (``templates/<name>``), else a folder holding a
    template.yaml. Its manifest is checked, and the engine it asks for."""
    spec = spec or DEFAULT_TEMPLATE
    folder = TEMPLATES / spec if NAME_RE.fullmatch(spec) else None
    if folder is None or not (folder / MANIFEST).is_file():
        folder = Path(spec).expanduser()
        if not (folder / MANIFEST).is_file():
            known = sorted(d.name for d in TEMPLATES.iterdir() if (d / MANIFEST).is_file())
            raise InitError(f"--template {spec!r}: not one of the engine's ({', '.join(known)}) nor a folder with a "
                            f"{MANIFEST}")
    try:
        data = graph.load_yaml_file((folder / MANIFEST)) or {}
    except Exception as exc:   # a YAML error: the manifest may be the owner's or a domain's
        raise InitError(f"--template {spec}: {MANIFEST} is not readable YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise InitError(f"--template {spec}: {MANIFEST} is a mapping")
    unknown = set(data) - TEMPLATE_KEYS
    if unknown:
        raise InitError(f"--template {spec}: {MANIFEST}: unknown key(s) {', '.join(sorted(unknown))} (known: "
                        f"{', '.join(sorted(TEMPLATE_KEYS))})")
    name, version, fs = data.get("name"), data.get("version"), data.get("files")
    if not (isinstance(name, str) and NAME_RE.fullmatch(name)):
        raise InitError(f"--template {spec}: {MANIFEST}: name is lower case letters, digits, '.', '_' and '-'")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise InitError(f"--template {spec}: {MANIFEST}: version is a whole number, 1 or more")
    engine = str(data.get("engine") or "")
    if not engine_fits(engine):
        raise InitError(f"--template {spec}: it needs brain {engine}, this is {__version__} (install the engine at a "
                        "tag that fits)")
    if not isinstance(fs, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in fs.items()):
        raise InitError(f"--template {spec}: {MANIFEST}: files maps the brain's path to the template's file")
    for rel, source in fs.items():
        if rel == config.FILE or rel.startswith("/") or ".." in rel.replace("\\", "/").split("/"):
            raise InitError(f"--template {spec}: {MANIFEST}: {rel!r}: a path inside the brain, not config.json")
        if source and not (folder / source).is_file():
            raise InitError(f"--template {spec}: {MANIFEST}: {rel}: no file {source!r} in the template")
    missing = [r for r in REQUIRED if r not in fs]
    if missing:
        raise InitError(f"--template {spec}: {MANIFEST}: files misses what config.json names: {', '.join(missing)}")
    declared = data.get("classes") or {}
    _, errors = classes.stores(config.Config(None, Path("."), {"classes": {"stores": declared}}))
    if not isinstance(declared, dict) or errors:
        raise InitError(f"--template {spec}: {MANIFEST}: classes: " + ("; ".join(errors) or "{store: {class, paths}}"))
    return Template(name, version, str(data.get("title") or ""), folder, engine, dict(fs),
                    graphs_of(spec, data.get("graphs")), dict(declared))


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
    """The manifest's ``graphs``, checked: a list of {name, store, schema}, names and stores unique, a store inside the
    brain; none declared: one, ``work`` at notes/graph."""
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
        if schema not in SCHEMAS:
            raise InitError(f"{where}[{i}] ({name}): schema {schema!r}: only {', '.join(SCHEMAS)} for now "
                            "(the brain's base: work, decisions, records)")
        names.add(name)
        stores.add(store)
        out.append({"name": name, "store": store, "schema": schema})
    return out


def schema_text(name: str, owner: str) -> str:
    """A store's schema.yaml from the engine's ``templates/schemas/<name>.yaml``, with its owner. ``default``, the
    brain's base: the work, the decisions and the records layers (DDR, Session, Action: what brain sync generates
    from records/), so that a new brain's decisions and sessions are nodes of its graph from the first sync."""
    text = (TEMPLATES / "schemas" / f"{name}.yaml").read_text(encoding="utf-8")
    return text.replace("{owner_line}", f"owner: {json.dumps(owner, ensure_ascii=False)}\n")


def schema_layers(name: str) -> list[str]:
    data = graph.load_yaml(schema_text(name, "x")) or {}
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
            "engine": {"repo": ENGINE_REPO, "pin": f"v{__version__}"}, "tier": {"base": tier},
            "adapters": {"claude": claude}, "public": {"repos": [], "deny": {"people": [owner], **machine_terms()}},
            "classes": classes_block(tpl)}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def files_for(owner: str, kind: str, tenant: str | None, tier: str, name: str,
              tpl: Template | None = None) -> dict[str, str]:
    """{path relative to the brain: text} for every file brain init writes but the store and the Claude files:
    config.json, then the template's files with their variables rendered."""
    tpl = tpl or load_template()
    values = {"owner": owner, "owner_q": json.dumps(owner, ensure_ascii=False), "name": name,
              "title_q": json.dumps(f"{owner}'s brain: rules, decisions, backlog and journal", ensure_ascii=False)}
    out = {config.FILE: config_text(owner, kind, tenant, tier, tpl)}
    for rel, source in tpl.files.items():
        out[rel] = re.sub(r"\{(owner|owner_q|name|title_q)\}", lambda m: values[m.group(1)], tpl.read(source))
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


def plan(root: Path, owner: str, *, kind: str = "person", tenant: str | None = None, tier: str = "lite",
         name: str = "brain", template_spec: str = DEFAULT_TEMPLATE) -> list[Step]:
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
    tpl = load_template(template_spec)
    root = Path(root).resolve()
    steps, created = [], set()
    for rel, text in files_for(owner, kind, tenant, tier, name, tpl).items():
        p = root / rel
        if p.exists():
            steps.append(Step("keep", p, why="exists"))
        else:
            steps.append(Step("create", p, text))
            created.add(rel)
    for g in tpl.graphs:
        schema = root / g["store"] / "schema.yaml"
        steps.append(Step("keep", schema.parent, why="a graph store already") if schema.exists() else
                     Step("store", schema.parent, schema_text(g["schema"], owner),
                          why=f"research_graph init --owner {owner}, layers {', '.join(schema_layers(g['schema']))}"))
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
        elif s.action == "store":
            rc = graph.research_graph(root, s.path, "init", "--owner", " ".join(owner.split()))
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


def git_identity_missing(root: Path) -> list[str]:
    """The keys of git's identity (``user.name``, ``user.email``) that no git config read from ``root`` sets: without
    them a first commit stops at "Author identity unknown" (a fresh Git for Windows). Empty when both are set, and
    when git is not found or fails otherwise (no hint rather than a wrong one)."""
    missing = []
    for key in ("user.name", "user.email"):
        try:
            done = subprocess.run(["git", "config", "--get", key], cwd=root, capture_output=True, text=True,
                                  timeout=10)
        except (OSError, subprocess.SubprocessError):
            return []
        if done.returncode == 1 or (done.returncode == 0 and not done.stdout.strip()):
            missing.append(key)
        elif done.returncode:
            return []
    return missing


def identity_hint(missing: list[str], owner: str, kind: str = "person") -> str:
    """The line ``brain init --apply`` adds to its next steps when git has no identity yet: the commands to set it,
    once, before the first commit; '' when nothing is missing. The owner's name for a person, a placeholder else."""
    if not missing:
        return ""
    name = owner if kind == "person" and owner and '"' not in owner else "Your Name"
    cmds = {"user.name": f'git config --global user.name "{name}"',
            "user.email": 'git config --global user.email "you@example.com"'}
    return ("      git's identity first, once (none on this machine yet: the first commit would stop at \"Author "
            "identity unknown\"): " + "; ".join(cmds[k] for k in missing if k in cmds))


def main(args) -> int:
    root = Path(args.dir or ".").resolve()
    spec = getattr(args, "template", None) or DEFAULT_TEMPLATE
    try:
        steps = plan(root, args.owner or "", kind=args.kind, tenant=args.tenant, tier=args.tier, name=args.name,
                     template_spec=spec)
        tpl = load_template(spec)
    except InitError as exc:
        print(f"brain init: {exc}")
        return 2
    owner = " ".join((args.owner or owner_in(root)).split())
    print(f"brain init: {root} for {owner} ({args.kind}, {args.tier}), template {tpl.name} v{tpl.version}, engine "
          f"{ENGINE_REPO}@v{__version__}")
    print("\n".join(show(root, steps)))
    if not args.apply:
        print("(plan only: brain init --apply writes it)")
        return 0
    code = apply(root, steps, owner)
    errors = config.check(root)
    for e in errors:
        print(f"error: {e}")
    if code or errors:
        return code or 1
    print("next: git init and commit (a private repo of your own, never a public one); brain check; brain profile "
          "(this machine's profile); brain item add --help (your first item); brain journal add --title ...; "
          "brain sync after an edit (brain refresh --on-main: sync and check, in this checkout)")
    hint = identity_hint(git_identity_missing(root), owner, args.kind)
    if hint:
        print(hint)
    names = claude_names(root)
    folder = f'"{root}"' if " " in str(root) else str(root)
    print(f"      Claude Code, once: claude plugin marketplace add {folder}, then claude plugin install "
          f"{names['plugin']}@{names['marketplace']} (brain sync renders the plugin again after an engine upgrade)")
    print(f"      the vault, before anything leaves this machine: brain classes (each store's class), brain vault "
          f"status (your device key, your recovery key, the daily canary); the runbook: {vault.RUNBOOK}")
    return 0
