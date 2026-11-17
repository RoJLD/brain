"""``brain project new``, slice 3 (wi-brain-project-wizard-pack, spec-brain-client-standards §8): what the answers
propose beyond the registry, by plan. The typology packs the project's kinds meet (brain.typology_packs, TYPO-4: the
engine's packs taken ``from: engine`` in ``source/packs.yaml``, TYPO-7) and their parts, then the project's CLAUDE.md
and AGENTS.md:

- **the packs**: each pack a kind meets, the step that gives it (``brain typologies propose NAME --apply``), its
  procedures and MCP servers, the guards it turns on (the core plugin's guard hook runs the engine's guards; ``brain
  permissions`` lists the effective allow / ask / deny list), the standards profiles its project does not meet;
- **the rules that need judgement**: a pack's clauses of done, one-way doors, roles and gates are what no script
  checks; brain init writes them into the project's CLAUDE.md, a section « What it produces » (:func:`claude_edit`),
  which AGENTS.md flattens last;
- **the hooks**: the core pack's (the engine's Claude hooks), rendered with the packs' plugins into the brain's
  marketplace (``brain render --target claude --write``);
- **the CI templates**: the template's workflows (brain init writes them; slice 2 says which declared reports they
  do not write);
- **AGENTS.md**: the rules' chain flattened (``brain render --target agents --write``).

With ``--apply``, after brain init's files, each step is a brain command run in this process and logged as the
owner's step in ``<BRAIN_HOME>/ledger/setup-<month>.jsonl`` (brain.firstrun, ``via: project-new``); a step that fails
does not stop the next (each re-reads the brain), the run exits 1 and names the command that re-runs it; a step with
nothing to do is skipped and says why. Nothing is written but by brain init's plan and those commands.

In a folder that already holds the project's brain, the same parts are planned against it (its packs.yaml, its
rendered files) and nothing runs: the commands are the owner's, by a branch and a PR of that brain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import firstrun, neutral, typologies, typology_packs

VIA = "project-new"
CLAUDE = "CLAUDE.md"
AGENTS = "AGENTS.md"
SECTION = "## What it produces"
WORKFLOWS = ".github/workflows/"


@dataclass
class Step:
    part: str              # packs, claude, agents
    words: list[str]       # the brain command, as the owner types it
    what: str              # what it writes
    skip: str = ""         # why it does not run ("": it runs)


@dataclass
class Parts:
    props: list = field(default_factory=list)       # typology_packs.Proposal, the packs the kinds meet
    steps: list[Step] = field(default_factory=list)
    claude: bool = False                             # the template writes a CLAUDE.md (it gains the section)
    workflows: list[str] = field(default_factory=list)


def md(text) -> str:
    """A pack's text on one Markdown line: its whitespace (a newline) folded to one space, ``&`` and ``<`` as
    entities (an HTML comment or tag would hide what follows), the rest as written."""
    return " ".join(str(text).split()).replace("&", "&amp;").replace("<", "&lt;")


def plan_new(cat: typologies.Catalog, kinds: list[str], profiles, files: dict, root: Path, name: str) -> Parts:
    """The parts of a new brain: the engine's packs the kinds meet (brain init's packs.yaml holds the core only),
    against its standards profiles (``profiles``, the template's ``standards.profiles``); ``files``: brain init's
    files (its CLAUDE.md, its workflows). The layers are slice 1's (the summary names those the graph lacks)."""
    props = typology_packs.proposals(typology_packs.engine_candidates(), kinds, cat, None, profiles)
    p = Parts(props, claude=CLAUDE in files, workflows=sorted(f for f in files if f.startswith(WORKFLOWS)))
    p.steps = steps(root, name, props, packs_pending=bool(props), claude_stale=bool(props), agents_stale=True)
    return p


def plan_existing(cat: typologies.Catalog, kinds: list[str], root: Path, name: str, entry: dict) -> Parts:
    """The parts of a brain that holds the project already: its packs.yaml's packs the answers' kinds meet, and
    whether its rendered files (the marketplace, AGENTS.md) are current; nothing runs (a branch and a PR of it)."""
    from . import project_add
    with project_add.this_brain(root / "projects.yaml"):
        cands = typology_packs._candidates(neutral.load(root), name)   # neutral.load never raises: check says why
        std = entry.get("standards") if isinstance(entry.get("standards"), dict) else {}
        props = typology_packs.proposals(cands, kinds, cat, None, std.get("profiles"))
        pending = any(pr.step in ("add", "extend") for pr in props)
        p = Parts(props, claude=(root / CLAUDE).is_file())
        p.steps = steps(root, name, props, packs_pending=pending, claude_stale=pending or _stale(root, "claude"),
                        agents_stale=pending or _stale(root, "agents", name))
    return p


def _stale(root: Path, target: str, project: str | None = None) -> bool:
    """Whether ``brain render --target T [--project P] --check`` would fail: an output not current (an unreadable
    source counts as stale: its render says why)."""
    from . import projects, render
    try:
        obj = projects.load(root).get(project) if project else None
        r = render.render(root, target, project, obj.root if obj else None)
        return bool(render.stale(render.plan(r, render.bases_for(root, obj.root if obj else None, None))))
    except (render.RenderError, projects.RepoError, OSError):   # the step's own render says why
        return True


def steps(root: Path, name: str, props: list, *, packs_pending: bool, claude_stale: bool,
          agents_stale: bool) -> list[Step]:
    """The parts' commands in order: the packs, the marketplace that renders them, AGENTS.md; each skipped with its
    reason when it has nothing to write."""
    at = ["brain", "--root", str(root)]
    taken = ", ".join(pr.pack for pr in props if pr.step in ("add", "extend"))
    return [
        Step("packs", [*at, "typologies", "propose", name, "--apply"],
             f"{neutral.FOLDER}/{neutral.PACKS} takes {taken}" if taken else "",
             "" if packs_pending else ("no typology pack meets its kinds" if not props else
                                       "its packs are taken already")),
        Step("claude", [*at, "render", "--target", "claude", "--write"],
             "the marketplace: the core's hooks and each pack's plugin, procedures and MCP servers",
             "" if claude_stale else "the marketplace is current"),
        Step("agents", [*at, "--project", name, "render", "--target", "agents", "--write"],
             f"{AGENTS}: the rules' chain flattened, the project's {CLAUDE} last",
             "" if agents_stale else f"{AGENTS} is current"),
    ]


def plan_lines(p: Parts, name: str, new: bool) -> list[str]:
    """The plan's lines of the parts: each pack and what it brings, the hooks, the CI templates, CLAUDE.md and
    AGENTS.md, then the steps (``new``: run by --apply; else the owner's, by a PR of that brain)."""
    out = ["  its parts (the typology packs' and the agent files, each written by a brain command"
           + (", run and logged by --apply):" if new else "):")]
    if not p.props:
        out.append("    no typology pack meets its kinds (brain typologies packs lists the packs and their typologies)")
    for pr in p.props:
        out += _pack_lines(pr, name, new and p.claude)
    return out + _file_lines(p, new) + _step_lines(p, new)


def _file_lines(p: Parts, new: bool) -> list[str]:
    """The plan's lines of the hooks, the CI templates (a new brain's), CLAUDE.md and AGENTS.md."""
    out = ["    hooks: the core pack's, the engine's Claude hooks (rules injection, guards, capture, announcements), "
           "rendered into the brain's marketplace"]
    if new:
        out.append(f"    CI templates: {', '.join(p.workflows)} (the template's, brain init writes them)" if p.workflows
                   else "    CI templates: none (the template writes no workflow: the project's CI is its own)")
    if not p.claude:
        claude = "none (the template writes none; brain typologies packs shows the packs' judgement)"
    elif not new:
        claude = "its own (a PR of that brain edits it)"
    elif p.props:
        claude = "the template's, with « What it produces »: the packs' judgement (clauses of done, one-way doors, " \
                 "roles, gates)"
    else:
        claude = "the template's"
    return out + [f"    {CLAUDE}: {claude}", f"    {AGENTS}: the rules' chain flattened (global, ancestors, its "
                  f"{CLAUDE} last)"]


def _step_lines(p: Parts, new: bool) -> list[str]:
    """The plan's lines of the steps that run (``new``: by --apply; else the owner's) and of the packs' step skipped."""
    run = [s for s in p.steps if not s.skip]
    out = []
    if run:
        out.append("  --apply runs, after brain init's files, each logged in <BRAIN_HOME>/ledger/setup-<month>.jsonl:"
                   if new else "  its parts' steps, by a branch and a PR of that brain (never here):")
        out += [f"    {i}. {firstrun.shown(s.words)}   ({s.what})" for i, s in enumerate(run, 1)]
    return out + [f"    skipped: {firstrun.shown(s.words)} ({s.skip})" for s in p.steps if s.skip and s.part == "packs"]


def _pack_lines(pr, name: str, written: bool) -> list[str]:
    """One pack's lines: its state, its judgement (``written``: into the new CLAUDE.md), its guards, its tools, the
    profiles its project does not meet."""
    spec = _spec(pr)
    state = {"add": f"{neutral.PACKS} takes it (from: engine, projects: [{name}])",
             "extend": f"{name} added to its projects", "shadowed": f"hidden by {neutral.PACKS}'s own pack of its id "
             "(not from: engine): nothing is written"}.get(pr.step, "taken")
    out = [f"    pack {pr.pack} ({'the engine' if pr.origin == typology_packs.ENGINE else pr.origin}'s, for "
           f"{', '.join(pr.meets)}): {state}"]
    judged = [f"{len(spec.get(k) or [])} {w}" for k, w in (("done", "clause(s) of done"), ("doors", "one-way door(s)"),
                                                          ("roles", "role(s)")) if spec.get(k)]
    stages = spec.get("stages") if isinstance(spec.get("stages"), dict) else {}
    if stages:
        judged.append(f"gates at {', '.join(map(str, stages))}")
    if judged:
        where = f", in {CLAUDE} « What it produces »" if written else ""
        out.append(f"      its judgement{where}: {', '.join(judged)}")
    guards = typology_packs._list(spec.get("guards"))
    if guards:
        out.append(f"      guards it turns on: {', '.join(guards)} (the core's guard hook runs them; brain permissions "
                   f"--project {name}: the effective allow / ask / deny list)")
    tools = [f"{w}: {', '.join(typology_packs._list(spec.get(k)))}" for k, w in (("procedures", "procedures"),
                                                                              ("mcp", "MCP servers"))
             if typology_packs._list(spec.get(k))]
    out.append(f"      {'; '.join(tools) if tools else 'procedures and MCP servers: none'}")
    if pr.standards:
        out.append(f"      standards profiles it does not meet: {', '.join(pr.standards)} (projects.yaml {name}: "
                   "standards.profiles, by a PR of the registry; brain standards)")
    return out


def _spec(pr) -> dict:
    """The pack's parts as it applies (an engine pack's, or the brain's own as loaded)."""
    return pr.spec if isinstance(pr.spec, dict) else {}


def claude_section(cat: typologies.Catalog, kinds: list[str], stage: str, lifecycle_stage: str, props: list) -> str:
    """CLAUDE.md's section « What it produces »: the kinds and the stage, then each pack's judgement (its clauses of
    done, one-way doors, roles and gates by stage), each text on one line (:func:`md`)."""
    what = ", ".join(f"{k} ({md(cat.typologies[k].label())})" for k in kinds)
    out = ["", SECTION, "",
           f"{what}, at {stage} (the lifecycle's {lifecycle_stage}); `brain project new` wrote this section from its "
           "typology packs (`brain typologies packs`). What they add to the rules above is the judgement no script "
           "checks; `brain item clauses <id>` lists an item's clauses of done."]
    for pr in props:
        spec = _spec(pr)
        out += ["", f"### {md(spec.get('title') or pr.pack)} (pack {pr.pack})"]
        for key, head, text in JUDGEMENT:
            out += _list(head, [text(x) for x in spec.get(key) or [] if isinstance(x, dict)])
        stages = spec.get("stages") if isinstance(spec.get("stages"), dict) else {}
        out += _list("Gates by stage:", [f"{s}: {'; '.join(map(str, g or []))}" for s, g in stages.items()])
    return "\n".join(out) + "\n"


# A pack's judgement in CLAUDE.md: (its part, the list's head, the line of one entry).
JUDGEMENT = (("done", "Done, after the generic sentence:", lambda c: c.get("text")),
             ("doors", "One-way doors (an ADR before crossing one):", lambda d: d.get("text")),
             ("roles", "Roles:", lambda r: f"{r.get('id')}: {r.get('text')}"))


def _list(head: str, items: list) -> list[str]:
    items = [md(x) for x in items if x]
    return ["", head, "", *[f"- {x}" for x in items]] if items else []


def claude_edit(section: str):
    """brain init's edit of CLAUDE.md (init.files_for's ``edits``): the section appended after the template's
    text."""
    return lambda text: text.rstrip("\n") + "\n" + section


def run(p: Parts, root: Path, by: str) -> int:
    """The steps that run, in order, each logged; one that fails does not stop the next. 0, else 1 with the commands
    that re-run what failed."""
    from . import project_add
    failed = []
    with project_add.this_brain(root / "projects.yaml"):
        for s in p.steps:
            if s.skip:
                print(f"skipped: {firstrun.shown(s.words)} ({s.skip})")
                continue
            res = firstrun.run(s.words, root, by=by, via=VIA)
            print(f"$ {res['command']}\n{res['output']}" if res["output"] else f"$ {res['command']}")
            if res["exit"] != 0:
                failed.append(res["command"])
    if failed:
        print(f"brain project new: {len(failed)} step(s) failed (the brain is written; each re-runs alone): "
              + "; ".join(failed))
        return 1
    return 0


def log_init(root: Path, words: list[str], code: int, by: str) -> None:
    """brain init's files, the first step, logged like the others."""
    firstrun.log_init(root, words, code, by=by, via=VIA)
