"""``brain init``: a new personal brain from the package's templates, for a person or a team starting their own (the
first half of the setup wizard; spec-brain-personal-brain §5).

    brain init [DIR] --owner NAME [--kind person|team] [--tenant ID] [--tier lite|default] [--name NAME] [--apply]

A plan by default; ``--apply`` writes it. Nothing is overwritten: a file or a store that exists is kept, so a second
apply changes nothing. In DIR (default: the current folder), which becomes the owner's private repo:

- ``config.json`` (v1): ``identity`` (the owner, a person or a team, a tenant), the registry, the rules, memory and
  records, the engine that runs it (``engine``: this package's repo and tag), the machine profile it starts from
  (``tier``, Lite by default) and the names of its Claude Code marketplace and core plugin (``adapters.claude``, the
  engine's defaults: no ``source``, so the installer's marketplace steps stay off);
- ``projects.yaml``: one project, the brain itself (``root: .``);
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

The templates name no person, repo or host: the owner is the name given.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from . import __version__, config, graph, neutral, paths, render

ENGINE_REPO = "RoJLD/brain"   # where this package is published: config.json engine.repo
TEMPLATES = files(__package__) / "templates"
TIERS = ("lite", "default")
KINDS = ("person", "team")
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*")
STORE = "notes/graph"
PACKS = f"{neutral.FOLDER}/{neutral.PACKS}"
MARKETPLACE = ".claude-plugin/marketplace.json"


class InitError(ValueError):
    """A bad argument: nothing is planned."""


@dataclass
class Step:
    action: str            # create (a file), keep (exists), store (research_graph init), render (the Claude files),
    path: Path             # point (the pointer)
    text: str | None = None
    why: str = ""


def template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def config_text(owner: str, kind: str = "person", tenant: str | None = None, tier: str = "lite") -> str:
    ident = {"owner": owner, "kind": kind, **({"tenant": tenant} if tenant else {})}
    claude = {k: config.CLAUDE[k] for k in ("marketplace", "plugin")}   # no source: a local marketplace
    data = {"v": 1, "identity": ident, "registry": "projects.yaml", "rules": ["rules/global.md"], "memory": "memory",
            "records": "records", "engine": {"repo": ENGINE_REPO, "pin": f"v{__version__}"}, "tier": {"base": tier},
            "adapters": {"claude": claude}}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def files_for(owner: str, kind: str, tenant: str | None, tier: str, name: str) -> dict[str, str]:
    """{path relative to the brain: text} for every file brain init writes but the store and the Claude files."""
    title = json.dumps(f"{owner}'s brain: rules, decisions, backlog and journal", ensure_ascii=False)
    return {
        "config.json": config_text(owner, kind, tenant, tier),
        "projects.yaml": template("projects.yaml").replace("{name}", name).replace("{title}", title),
        PACKS: template("packs.yaml").replace("{owner}", json.dumps(owner, ensure_ascii=False)),
        "notes/journal.md": template("journal.md"),
        "rules/global.md": template("rules.md").replace("{owner}", owner),
        "CLAUDE.md": template("CLAUDE.md").replace("{owner}", owner),
        ".gitignore": template("gitignore"),
        "memory/.gitkeep": "",
        "records/.gitkeep": "",
    }


def claude_names(root: Path) -> dict[str, str]:
    """The marketplace and core plugin names of the brain at ``root`` (its own config.json adapters.claude, else the
    engine's defaults)."""
    f = Path(root) / config.FILE
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return config.claude(config.Config(f, Path(root), data if isinstance(data, dict) else {}))


def _render_step(root: Path, created: set[str], plugin: str) -> Step:
    """The Claude files: ``keep`` when the brain's source, config.json and store exist and the render is current, else
    ``render`` (done by apply, after the store)."""
    dest = root / MARKETPLACE
    if not created & {"config.json", "projects.yaml", PACKS} and (root / STORE / "schema.yaml").is_file():
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
         name: str = "brain") -> list[Step]:
    """What brain init would do in ``root``, file by file, in order."""
    owner = " ".join((owner or "").split())
    if not owner:
        raise InitError("--owner NAME: the person or team who decides for this brain")
    if kind not in KINDS:
        raise InitError(f"--kind {kind!r}: one of {', '.join(KINDS)}")
    if tier not in TIERS:
        raise InitError(f"--tier {tier!r}: one of {', '.join(TIERS)} (Recommended is computed per machine: brain "
                        "profile set recommended)")
    if not NAME_RE.fullmatch(name):
        raise InitError(f"--name {name!r}: lower case letters, digits, '.', '_' and '-'")
    root = Path(root).resolve()
    steps, created = [], set()
    for rel, text in files_for(owner, kind, tenant, tier, name).items():
        p = root / rel
        if p.exists():
            steps.append(Step("keep", p, why="exists"))
        else:
            steps.append(Step("create", p, text))
            created.add(rel)
    schema = root / STORE / "schema.yaml"
    steps.append(Step("keep", schema.parent, why="a graph store already") if schema.exists() else
                 Step("store", schema.parent, why=f"research_graph init --owner {owner}"))
    steps.append(_render_step(root, created, claude_names(root)["plugin"]))
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
            code = graph.research_graph(root, s.path, "init", "--owner", " ".join(owner.split())) or code
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


def main(args) -> int:
    root = Path(args.dir or ".").resolve()
    try:
        steps = plan(root, args.owner or "", kind=args.kind, tenant=args.tenant, tier=args.tier, name=args.name)
    except InitError as exc:
        print(f"brain init: {exc}")
        return 2
    print(f"brain init: {root} for {' '.join(args.owner.split())} ({args.kind}, {args.tier}), engine "
          f"{ENGINE_REPO}@v{__version__}")
    print("\n".join(show(root, steps)))
    if not args.apply:
        print("(plan only: brain init --apply writes it)")
        return 0
    code = apply(root, steps, args.owner)
    errors = config.check(root)
    for e in errors:
        print(f"error: {e}")
    if code or errors:
        return code or 1
    print("next: git init and commit (a private repo of your own, never a public one); brain check; brain profile "
          "(this machine's profile); brain item add --help (your first item); brain journal add --title ...")
    names = claude_names(root)
    folder = f'"{root}"' if " " in str(root) else str(root)
    print(f"      Claude Code, once: claude plugin marketplace add {folder}, then claude plugin install "
          f"{names['plugin']}@{names['marketplace']} (brain sync renders the plugin again after an engine upgrade)")
    return 0
