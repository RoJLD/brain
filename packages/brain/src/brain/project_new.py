"""``brain project new``: the new-project wizard (wi-brain-project-wizard, spec-brain-client-standards §8, STD-5;
spec-brain-typology-packs: its kinds are the typology catalog's ids). What we produce (``--kind``, one or several ids
of the catalog), its stage (``--stage``), then, a plan then ``--apply``, the project's brain written by ``brain init``
from the profile template of its first kind that has one (``--template`` names another), with the answers recorded in
its registry entry: ``lifecycle: {typologies, stage}`` (brain item clauses reads its typologies).

STD-5: code products and research first. A kind whose entry is neither ``software`` nor ``research`` (creation,
strategy, marketing, hardware-cad, organisation, compliance) is named by the catalog but not offered yet: the plan
says so and writes nothing.

Slice 2 (wi-brain-project-wizard-tools, §8 questions 3 and 4):

- **the languages and tools**: ``--lang py|ts`` (the brain's own repo's ``lang``) and, per check's slot (lint,
  typecheck, test, coverage, format), its tool (``--tool SLOT=TOOL``, brain.langs.TOOLS); a slot not named takes
  the language's usual tool (brain.langs.DEFAULT_TOOLS), shown in the plan, and ``--tool SLOT=none`` leaves it out.
  A tool that writes a report is written to the repo's ``tools:`` (its report and format); one with an exit code
  only (``ruff format --check``, ``prettier --check .``) is named in the plan and not declared. The plan names the
  declared reports the template's CI does not write (:func:`ci_notes`);
- **the data**: ``--floor CLASS`` the project's class floor (``classes: {floor}``, brain classes), ``--residency``
  data under a residency clause (the floor ``resident``). ``brain check`` refuses a store under its project's floor,
  and the brain's own stores belong to its own entry: a floor above one of them is refused by the plan
  (:func:`floor_refused`), never written into a brain that would fail its own check. ``--personal-data``: the
  project handles personal data, the privacy rows of the standards (:data:`PERSONAL_DATA`) are added to its
  selection's ``include`` (merged into the template's own), required from its first stage;
- **the standards rows they select**: the plan shows the rows its selection makes required at its stage, those whose
  check runs through a slot it declares, and those whose check does not cover its language (brain.standards.gaps).

A later answer re-runs the same plan: in a folder that already holds the project's brain, the plan shows what the
answers change in its entry (its lifecycle, its standards' stage and include, its language and tools, its class
floor) and writes nothing: an existing registry changes by a branch and a PR, as the cockpit's wizards say.

Slice 3 (wi-brain-project-wizard-pack, brain.project_parts): the typology packs its kinds meet and their parts (the
procedures, the hooks, the guards and their permissions, the CI templates, the rules that need judgement written into
its CLAUDE.md), then its AGENTS.md: planned with the rest, and with ``--apply``, after brain init's files, each a brain
command run and logged; in a folder that holds its brain already, planned against it and never run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import classes, config, graph, init, langs, paths, project_parts, standards, typologies

OFFERED = ("software", "research")   # STD-5: the entries the wizard offers first
# The standards a project that handles personal data follows from its first stage (§8 question 4): privacy by design,
# a retention per class, erasure, crash reports without personal data. Those the engine's catalogs hold are included.
PERSONAL_DATA = ("sw-privacy-by-design", "sw-retention", "sw-erasure", "sw-crash-reports")
NONE = "none"   # --tool SLOT=none: no tool for that slot
MARK = "# brain project new"
CI = ".github/workflows/ci.yml"   # the code templates' CI (templates/_software/ci.yml)
CI_SETUP = {"py": "actions/setup-python", "ts": "actions/setup-node"}   # how a CI's language is told


class WizardError(ValueError):
    """An answer the wizard cannot take: nothing is planned (exit 2)."""


@dataclass
class Answers:
    kinds: list[str]
    stage: str                  # the standards' stage brain init takes
    lifecycle_stage: str        # the lifecycle's stage it reads as (brain typologies)
    template: str
    entries: list[str] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)   # the layers the kinds are proposed at the stage
    missing: list[str] = field(default_factory=list)  # those the template's graph does not hold
    lang: str = ""                                     # the brain's own repo's language ("" not asked)
    tools: dict = field(default_factory=dict)          # {slot: langs.Tool} written to its tools:
    unreported: list = field(default_factory=list)     # the tools named that write no report (not declared)
    specs: list[str] = field(default_factory=list)     # the --tool answers, as SLOT=TOOL
    floor: str = ""                                    # its class floor ("" none)
    residency: bool = False                            # asked as --residency (the floor resident)
    include: list[str] = field(default_factory=list)   # the standards rows added to its selection

    def lifecycle(self) -> dict:
        return {"typologies": list(self.kinds), "stage": self.lifecycle_stage}

    def repo_tools(self) -> dict:
        """Its ``tools:`` as written: {slot: {report, format, tool}}, in the slots' order."""
        return {s: self.tools[s].entry() for s in langs.SLOTS if s in self.tools}


def templates_of(cat: typologies.Catalog) -> dict[str, str]:
    """{kind: the engine's profile template it takes}: a kind that names a template, else its entry's (trading:
    research)."""
    named = set(init.known_templates()) - {init.DEFAULT_TEMPLATE}
    out = {}
    for tid in cat.typologies:
        for k in cat.kinds(tid):
            if k in named:
                out[tid] = k
                break
    return out


def offered(cat: typologies.Catalog) -> list[str]:
    """The kinds the wizard offers with a template of their own (the cockpit's choices), in the catalog's order."""
    have = templates_of(cat)
    return [t for t in cat.typologies if t in have and cat.entry(t) in OFFERED]


def resolve(cat: typologies.Catalog, kinds: list[str], stage: str, template: str | None = None) -> Answers:
    """The answers checked: each kind an id of the catalog of an offered entry, the stage one of brain init's, the
    template the one given or the first kind's."""
    _check_kinds(cat, kinds)
    if stage not in init.STAGES:
        raise WizardError(f"--stage {stage}: one of {', '.join(init.STAGES)}")
    have = templates_of(cat)
    chosen = template or next((have[k] for k in kinds if k in have), None)
    if chosen is None:
        raise WizardError(f"--kind {', '.join(kinds)}: no profile template of its own yet; --template one of "
                          f"{', '.join(sorted(set(have.values())))}, or a folder holding a template.yaml")
    layers: list[str] = []
    for k in kinds:
        layers += [la for la in typologies.layers(cat, k, stage) if la not in layers]
    held = _held(chosen)
    return Answers(list(kinds), stage, cat.stage(stage), chosen, list(dict.fromkeys(cat.entry(k) for k in kinds)),
                   sorted(layers), sorted(set(layers) - held) if held else [])


def _check_kinds(cat: typologies.Catalog, kinds: list[str]) -> None:
    if not kinds:
        raise WizardError("--kind K: what the project produces, an id of the typology catalog (brain typologies)")
    for k in kinds:
        if not cat.known(k):
            raise WizardError(f"--kind {k}: not in the typology catalog (brain typologies lists the kinds)")
        if cat.entry(k) not in OFFERED:
            raise WizardError(f"--kind {k}: a kind of {cat.entry(k)}, named by the catalog and not offered yet "
                              "(STD-5: code products and research first; brain init DIR writes the generic brain)")


def _held(template: str) -> set[str]:
    """The layers the template's first graph holds."""
    try:
        graphs = init.load_template(template).graphs
    except init.InitError as exc:
        raise WizardError(f"--template {template}: {exc}") from None
    return set(graphs[0].get("layers") or []) if graphs else set()


def answer_tools(a: Answers, lang: str | None, specs: list[str] | None) -> Answers:
    """Question 3, the languages and tools: ``lang`` (py or ts) and ``specs`` (``SLOT=TOOL``, TOOL ``none`` for no
    tool), each slot not named taking the language's usual tool. Nothing asked (no --lang, no --tool): unchanged."""
    specs = list(specs or [])
    if not lang:
        if specs:
            raise WizardError("--tool SLOT=TOOL: with --lang py|ts, the language its tools read")
        return a
    if lang not in langs.LANGS:
        raise WizardError(f"--lang {lang}: one of {', '.join(langs.LANGS)}")
    named: dict[str, str] = {}
    for spec in specs:
        slot, name = _tool_spec(spec, lang)
        if named.get(slot, name) != name:
            raise WizardError(f"--tool {slot}: named twice ({named[slot]}, {name})")
        named[slot] = name
    a.lang, a.specs = lang, [f"{s}={n}" for s, n in named.items()]
    for slot in langs.SLOTS:
        t = langs.tool(lang, slot, named.get(slot, langs.DEFAULT_TOOLS.get(lang, {}).get(slot, NONE)))
        if t is not None and t.report:
            a.tools[slot] = t
        elif t is not None:
            a.unreported.append(t)
    return a


def _tool_spec(spec: str, lang: str) -> tuple[str, str]:
    """One ``--tool SLOT=TOOL`` checked: (slot, tool), the tool one the wizard knows for that slot in ``lang`` or
    ``none``."""
    slot, sep, name = (x.strip() for x in spec.partition("="))
    if not sep or not slot or not name:
        raise WizardError(f"--tool {spec}: SLOT=TOOL (slots: {', '.join(langs.SLOTS)}; TOOL {NONE} for none)")
    if slot not in langs.SLOTS:
        raise WizardError(f"--tool {spec}: the slot is one of {', '.join(langs.SLOTS)}")
    if name != NONE and langs.tool(lang, slot, name) is None:
        known = ", ".join(langs.tools_for(lang, slot)) or "none known"
        raise WizardError(f"--tool {spec}: not a {slot} tool of {lang} the wizard knows ({known}; {NONE} for "
                          "none); another tool's report is declared by hand in projects.yaml repos[].tools")
    return slot, name


def answer_data(a: Answers, floor: str | None, residency: bool = False, personal: bool = False) -> Answers:
    """Question 4, the data: the class floor (``--residency``: ``resident``), and with personal data the privacy rows
    the engine's catalogs hold (:data:`PERSONAL_DATA`)."""
    if residency and floor and floor != "resident":
        raise WizardError(f"--residency is the floor resident; --floor {floor} says otherwise: one of the two")
    floor = "resident" if residency else (floor or "")
    if floor and floor not in classes.CLASSES:
        raise WizardError(f"--floor {floor}: one of {', '.join(classes.CLASSES)} (brain classes)")
    if floor == "secret":
        raise WizardError("--floor secret: a secret is never in the brain (a keystore holds it); its stores take a "
                          "class they may hold")
    a.floor, a.residency = floor, residency
    if personal:
        held = {r.id for r in standards.rows_of(standards.engine_catalogs())}
        a.include = [sid for sid in PERSONAL_DATA if sid in held]
    return a


def floor_refused(a: Answers, root: Path, entry: dict | None, name: str) -> None:
    """A floor the brain's own stores are under, refused at plan time: ``brain check`` (brain classes --check)
    refuses a store whose class is under its project's floor, and the brain's own stores (those of config.json's
    ``classes.stores`` that name no other project) belong to its own entry (``name``). Its stores: the config.json of
    the folder's brain when it holds one (``entry``), else those brain init writes from the template
    (brain.init.classes_block: with the engine's templates the repo private, memory and the decisions confidential,
    the machine's stores sealed). WizardError naming them and the floors they hold."""
    if not a.floor:
        return
    if entry is not None:
        cfg, where = config.load(root), str(root / config.FILE)
    else:
        block = init.classes_block(init.load_template(a.template))
        cfg, where = config.Config(None, Path("."), {"classes": block}), f"brain init's config.json for {a.template}"
    own = [s for s in classes.stores(cfg)[0] if s.project in ("", name)]
    under = [f"{s.name} ({s.cls})" for s in own if s.rank < classes.RANK[a.floor]]
    if not under:
        return
    held = [c for c in classes.CLASSES if c != "secret" and all(s.rank >= classes.RANK[c] for s in own)]
    asked = "--residency (the floor resident)" if a.residency else f"--floor {a.floor}"
    raise WizardError(f"{asked}: the brain's own stores {', '.join(under)} are under it ({where}), which brain check "
                      f"refuses (brain classes --check); they hold the floor {' or '.join(held) or 'of none'}: declare "
                      f"them at {a.floor} or stricter first (config.json classes.stores), then raise the floor in "
                      "projects.yaml by a PR")


def registry_edit(a: Answers, name: str):
    """What brain init's projects.yaml gains under the brain's own entry (``name``, the last), as a function of the
    rendered text (init.files_for's ``registry_edit``): the language and tools under its repo ``path: .``, its
    ``classes: {floor}``, and the rows its standards selection ``include`` (merged into an include the template
    writes already). Lines added, the template's comments kept; InitError when a line cannot land where it belongs
    (a template that writes its entry otherwise)."""
    def edit(text: str) -> str:
        held = _included(text, name, a.template)
        new = [i for i in a.include if i not in held]
        if a.lang:
            text = _repo_lines(text, name, a)
        if a.floor:
            text = text.rstrip("\n") + f"\n  classes: {{floor: {a.floor}}}   {MARK}: the data's class floor\n"
        if new:
            text = _include_line(text, new, name, held)
        _landed(text, name, a, held + new)
        return text
    return edit


def _entry_start(lines: list[str], name: str) -> int:
    starts = [i for i, ln in enumerate(lines) if ln.startswith(f"{name}:")]
    return starts[-1] if starts else len(lines)


def _code(line: str) -> str:
    """A line without its comment and its end."""
    return line.split("#", 1)[0].rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _end(line: str) -> str:
    return "\r\n" if line.endswith("\r\n") else "\n"


def _flow(value) -> str:
    """A list or a mapping in YAML's flow style, on one line."""
    return yaml.safe_dump(value, default_flow_style=True, sort_keys=False, width=10 ** 6).strip()


def _repo_lines(text: str, name: str, a: Answers) -> str:
    """The language and tools under the entry's repo ``- path: .`` (the brain's own repo)."""
    lines = text.splitlines(keepends=True)
    start = _entry_start(lines, name)
    at = next((i for i in range(start, len(lines)) if lines[i].split("#")[0].strip() == "- path: ."), None)
    if at is None:
        raise init.InitError(f"--template {a.template}: projects.yaml: no repo '- path: .' under {name}: the language "
                             "and tools go in its repos[].lang and tools by hand")
    pad = " " * (len(lines[at]) - len(lines[at].lstrip()) + 2)
    add = [f"{pad}lang: {a.lang}   {MARK}: its language\n"]
    if a.tools:
        add.append(f"{pad}tools:   {MARK}: each check's tool and the report it writes (brain audit reads them)\n")
        add += [f"{pad}  {slot}: {{report: {e['report']}, format: {e['format']}, tool: {e['tool']}}}\n"
                for slot, e in a.repo_tools().items()]
    return "".join(lines[:at + 1] + add + lines[at + 1:])


def _included(text: str, name: str, template: str) -> list[str]:
    """The ids the entry's standards selection includes already ([] none); InitError when its include is not a list
    of ids (the rows cannot merge into it)."""
    try:
        data = graph.load_yaml(text)
    except yaml.YAMLError:
        return []   # _landed says why
    inc = _dict(_dict(data.get(name) if isinstance(data, dict) else None).get("standards")).get("include")
    if inc is None:
        return []
    if not isinstance(inc, list) or not all(isinstance(x, str) for x in inc):
        raise init.InitError(f"--template {template}: projects.yaml: {name}'s standards include is not a list of ids: "
                             "the privacy rows go in by hand")
    return list(inc)


def _include_line(text: str, new: list[str], name: str, held: list[str]) -> str:
    """The rows added to the entry's ``standards: include``: into its include list (flow or block), into a one-line
    ``standards: {..}``, under a ``standards:`` block without one, or a ``standards:`` of their own."""
    lines = text.splitlines(keepends=True)
    at = next((i for i in range(_entry_start(lines, name), len(lines)) if _code(lines[i]).startswith("  standards:")),
              None)
    if at is None:
        return text.rstrip("\n") + f"\n  standards: {{include: {_flow(new)}}}   {MARK}: personal data's rows\n"
    value = _code(lines[at])[len("  standards:"):].strip()
    if value:
        lines[at] = _flow_standards(lines[at], value, held + new)
        return "".join(lines)
    return "".join(_block_include(lines, at, new, held))


def _flow_standards(line: str, value: str, merged: list[str]) -> str:
    """A one-line ``standards: {..}`` with its include merged; InitError when it is not one mapping on its line."""
    try:
        std = graph.load_yaml(value)
    except yaml.YAMLError:
        std = None
    if not isinstance(std, dict):
        raise init.InitError(f"projects.yaml: its 'standards: {value}' spans lines or is not a mapping: the privacy "
                             "rows go in its include by hand")
    std["include"] = merged
    comment = "#" + line.split("#", 1)[1].rstrip() if "#" in line else f"{MARK}: personal data's rows"
    return f"  standards: {_flow(std)}   {comment}{_end(line)}"


def _block_include(lines: list[str], at: int, new: list[str], held: list[str]) -> list[str]:
    """A ``standards:`` block's lines with the rows in its include: a flow ``include: [..]`` merged on its line, a
    block list extended, or an ``include:`` line of their own under its header."""
    end = at + 1
    while end < len(lines) and (not _code(lines[end]).strip() or _indent(lines[end]) > 2):
        end += 1
    children = [i for i in range(at + 1, end) if _code(lines[i]).strip()]
    pad = _indent(lines[children[0]]) if children else 4
    inc = next((i for i in children if _indent(lines[i]) == pad and _code(lines[i]).strip().startswith("include:")),
               None)
    if inc is None:
        return lines[:at + 1] + [f"{' ' * pad}include: {_flow(new)}   {MARK}: personal data's rows\n"] + lines[at + 1:]
    items = _items_under(lines, inc, pad, end)
    if _code(lines[inc]).strip() != "include:" or not items:   # a flow list (or an empty include): merged on its line
        comment = "   #" + lines[inc].split("#", 1)[1].rstrip() if "#" in lines[inc] else ""
        merged = f"{' ' * pad}include: {_flow(held + new)}{comment}{_end(lines[inc])}"
        return lines[:inc] + [merged] + lines[inc + 1:]
    head = lines[items[0]][:_indent(lines[items[0]])]
    add = [f"{head}- {i}   {MARK}: personal data's row{_end(lines[items[0]])}" for i in new]
    return lines[:items[-1] + 1] + add + lines[items[-1] + 1:]


def _items_under(lines: list[str], inc: int, pad: int, end: int) -> list[int]:
    """The lines of the block list right under ``include:`` (deeper, or ``- `` at its own indent), comments and
    blank lines between its items skipped."""
    out = []
    for i in range(inc + 1, end):
        code = _code(lines[i]).strip()
        if not code:
            continue
        if _indent(lines[i]) > pad or (_indent(lines[i]) == pad and code.startswith("- ")):
            out.append(i)
        else:
            break
    return out


def _twice(node) -> list[str]:
    """The keys written twice in one mapping of a composed YAML tree: a line the answers add beside the template's own
    key (a second ``standards:``, ``classes:`` or ``lang:``) would otherwise win silently."""
    if isinstance(node, yaml.MappingNode):
        keys = [k.value for k, _ in node.value if isinstance(k, yaml.ScalarNode)]
        out = sorted({k for k in keys if keys.count(k) > 1})
        return out + [k for _, v in node.value for k in _twice(v)]
    if isinstance(node, yaml.SequenceNode):
        return [k for v in node.value for k in _twice(v)]
    return []


def _landed(text: str, name: str, a: Answers, include: list[str]) -> None:
    """The answers' lines read back: under the brain's own entry (the registry's last), each key once, each value
    the one asked (``include``: its selection's include once merged); InitError otherwise."""
    try:
        twice = _twice(yaml.compose(text, Loader=yaml.SafeLoader))
        data = graph.load_yaml(text)
    except yaml.YAMLError as exc:   # the template's registry with the answers' lines
        raise init.InitError(f"--template {a.template}: projects.yaml with the answers is not YAML ({exc}): the "
                             "answers' lines go in by hand") from exc
    if twice:
        raise init.InitError(f"--template {a.template}: projects.yaml with the answers holds {', '.join(twice)} twice "
                             "(the template writes it already): the answers' lines go in by hand")
    entry = _dict(data.get(name) if isinstance(data, dict) else None)
    repo = _own_repo(entry)
    got = {"lang": repo.get("lang"), "tools": repo.get("tools") or {}, "floor": _dict(entry.get("classes")).get(
        "floor"), "include": _dict(entry.get("standards")).get("include")}
    want = {"lang": a.lang or None, "tools": a.repo_tools(), "floor": a.floor or None, "include": include}
    asked = {"lang": a.lang, "tools": a.lang, "floor": a.floor, "include": a.include}
    if list(data or {})[-1:] != [name] or any(got[k] != want[k] for k in want if asked[k]):
        raise init.InitError(f"--template {a.template}: projects.yaml: the answers' lines go under the brain's own "
                             f"entry ({name}), the registry's last: its repo '- path: .' and its standards block")


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _own_repo(entry: dict) -> dict:
    """The entry's repo at ``path: .`` (the brain's own); {} when it has none."""
    repos = entry.get("repos") if isinstance(entry.get("repos"), list) else []
    return next((r for r in repos if isinstance(r, dict) and str(r.get("path")) == "."), {})


def selected(a: Answers, text: str, name: str) -> dict:
    """The standards rows the answers select, from the registry as brain init would write it (``text``): {required:
    the rows its selection makes required at its stage, run: those whose check runs through a slot it declares,
    gaps: those whose check does not cover its language}."""
    data = graph.load_yaml(text) or {}
    entry = data.get(name) if isinstance(data, dict) else None
    entry = entry if isinstance(entry, dict) else {}
    chosen = standards.applicable(standards.rows_of(standards.engine_catalogs()),
                                  standards.selection(entry.get("standards")))
    slots = set(a.tools)
    return {"required": [r.id for r, _ in chosen],
            "run": [f"{r.id} ({r.adapter}: {a.tools[r.adapter].name})" for r, _ in chosen if r.adapter in slots],
            "gaps": standards.gaps(chosen, {name: a.lang}, {name: slots}) if a.lang else []}


def summary(cat: typologies.Catalog, a: Answers, rows: dict | None = None) -> list[str]:
    """The answers as the plan shows them, before brain init's own plan; ``rows``: the standards they select."""
    kinds = ", ".join(f"{k} ({cat.typologies[k].label()}, {cat.entry(k)} "
                      f"[{', '.join(cat.typologies[cat.entry(k)].vision)}])" for k in a.kinds)
    out = [f"brain project new: what it produces: {kinds}",
           f"  stage: {a.stage} (the lifecycle's {a.lifecycle_stage}); template: {a.template}",
           f"  layers its kinds are proposed at {a.lifecycle_stage}: {', '.join(a.layers) or 'none'}"
           + (f"; not in the template's graph: {', '.join(a.missing)} (research_graph layers add, once written)"
              if a.missing else ""),
           f"  its registry entry records lifecycle: {{typologies: [{', '.join(a.kinds)}], "
           f"stage: {a.lifecycle_stage}}} (brain item clauses reads its typologies)"]
    return out + _tool_lines(a) + (rows or {}).get("ci", []) + _data_lines(a, rows)


def ci_notes(a: Answers, files: dict[str, str]) -> list[str]:
    """What the template's CI (``files``: brain init's files) leaves of the declared reports: a template without a
    CI, a CI that runs another language (the code templates' runs Python), or the reports its steps do not write
    (``brain audit`` reads them as missing until a step does)."""
    if not a.tools:
        return []
    ci = files.get(CI)
    if ci is None:
        return [f"    the template writes no CI ({CI}): the project's CI or its developer writes these reports"]
    runs = [lg for lg, step in CI_SETUP.items() if step in ci]
    if a.lang not in runs:
        return [f"    the template's CI ({CI}) runs {', '.join(runs) or 'no language'} only, not {a.lang}: none of "
                "these reports is written until its steps run the commands above"]
    unwritten = [t.report for t in a.tools.values() if t.report not in ci]
    return [f"    not written by the template's CI ({CI}): {', '.join(unwritten)} (add its command to a step, or "
            "--tool SLOT=none)"] if unwritten else []


def _tool_lines(a: Answers) -> list[str]:
    """The plan's lines of the languages and tools (none when not asked)."""
    if not a.lang:
        return []
    out = [f"  language: {a.lang}; its tools (repos[].tools: the reports the project's CI writes, brain audit reads "
           "them):"]
    out += [f"    {slot}: {t.name} -> {t.report} ({t.format}): {t.command}" for slot, t in a.tools.items()]
    out += [f"    {t.slot}: {t.name}, an exit code only ({t.command}): named, not declared" for t in a.unreported]
    missing = [s for s in langs.SLOTS if s not in set(a.tools) | {t.slot for t in a.unreported}]
    return out + ([f"    no tool: {', '.join(missing)} (--tool SLOT=TOOL names one)"] if missing else [])


def _data_lines(a: Answers, rows: dict | None) -> list[str]:
    """The plan's lines of the data and of the standards rows the answers select."""
    out = []
    if a.floor:
        out.append(f"  data: class floor {a.floor} ({classes.CLASS_TEXT.get(a.floor, '')}): classes: {{floor: "
                   f"{a.floor}}}")
    if a.include:
        out.append(f"  personal data: its standards include {', '.join(a.include)} (required from its first stage)")
    if rows is not None:
        out.append(f"  standards it follows at {a.stage}: {len(rows['required'])} row(s) (brain standards list "
                   "--applicable, once written)")
        if rows["run"]:
            out.append(f"    run by its tools: {', '.join(rows['run'])}")
        if rows["gaps"]:
            out.append(f"    not covered on {a.lang}: " + "; ".join(rows["gaps"]))
    return out


def existing(root: Path, name: str) -> dict | None:
    """The project's entry in the folder's projects.yaml when it already holds a brain (its config.json's template
    under ``_template``), else None; WizardError for a registry that cannot be read, or one without config.json."""
    f = root / "projects.yaml"
    if not f.is_file():
        return None
    if not (root / config.FILE).is_file():
        raise WizardError(f"{root} holds a projects.yaml and no config.json: not a new project's folder, nor a brain")
    try:
        data = graph.load_yaml(f.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - unreadable or not YAML: said, never written over
        raise WizardError(f"{f}: not readable YAML ({exc}); brain check says why") from None
    entry = data.get(name) if isinstance(data, dict) else None
    entry = dict(entry) if isinstance(entry, dict) else {}
    tpl = config.load(root).data.get("template")
    entry["_template"] = tpl.get("name") if isinstance(tpl, dict) else None
    return entry


def changes(entry: dict, a: Answers) -> list[str]:
    """What the answers change in an existing entry: its lifecycle's typologies and stage, its standards' stage, and
    what was asked of the rest: its repo's language and tools, its class floor, its standards' include."""
    lc = entry.get("lifecycle") if isinstance(entry.get("lifecycle"), dict) else {}
    std = entry.get("standards") if isinstance(entry.get("standards"), dict) else {}
    pairs = [("lifecycle.typologies", lc.get("typologies"), a.kinds),
             ("lifecycle.stage", lc.get("stage"), a.lifecycle_stage),
             ("template", entry.get("_template"), a.template)]
    if std:
        pairs.append(("standards.stage", std.get("stage"), a.stage))
    pairs += _asked_pairs(entry, std, a)
    return [f"  {key}: {_shown(old)} -> {_shown(new)}" for key, old, new in pairs
            if (list(old) if isinstance(old, list) else old) != new]


def _asked_pairs(entry: dict, std: dict, a: Answers) -> list[tuple]:
    """(key, what the entry holds, what the answers write) for what slice 2 asked: the language and tools (each
    slot's tool, report and format), the class floor, the standards' include."""
    pairs = []
    if a.lang:
        repo = _own_repo(entry)
        tools = _dict(repo.get("tools"))
        pairs.append(("repos[path: .].lang", repo.get("lang"), a.lang))
        pairs += [(f"repos[path: .].tools.{s}", _declared(tools.get(s)), _answered(a, s))
                  for s in langs.SLOTS if s in tools or s in a.tools]
    if a.floor:
        pairs.append(("classes.floor", _dict(entry.get("classes")).get("floor"), a.floor))
    if a.include:
        have = [str(x) for x in std.get("include")] if isinstance(std.get("include"), list) else []
        pairs.append(("standards.include", have or None, have + [i for i in a.include if i not in have]))
    return pairs


def _declared(spec) -> str | None:
    """A ``tools.<slot>`` as the diff shows it: its tool, then its report and format (the report alone when it names
    no tool); None when the slot is not declared."""
    if not isinstance(spec, dict):
        return None
    where = ", ".join(str(spec[k]) for k in ("report", "format") if spec.get(k))
    tool = str(spec.get("tool") or "")
    return f"{tool} ({where})" if tool and where else (tool or where or str(spec))


def _answered(a: Answers, slot: str) -> str | None:
    """What the answers write in a slot: its tool's entry, a tool with an exit code only (named, not declared), or
    None (no tool)."""
    if slot in a.tools:
        return _declared(a.tools[slot].entry())
    quiet = next((t for t in a.unreported if t.slot == slot), None)
    return f"{quiet.name}, an exit code only (not declared)" if quiet else None


def _shown(value) -> str:
    return "(none)" if value is None else str(list(value) if isinstance(value, list) else value)


def main(args) -> int:
    root = Path(args.dir).resolve()
    try:
        cat = typologies.load(config.load(root))
        a = resolve(cat, list(dict.fromkeys(args.kinds or [])), args.stage, args.template)
        answer_tools(a, getattr(args, "lang", None), getattr(args, "tools", None))
        answer_data(a, getattr(args, "floor", None), getattr(args, "residency", False),
                    getattr(args, "personal_data", False))
        entry = existing(root, args.name)
        floor_refused(a, root, entry, args.name)
        rows, refused = _rows(a, args.name) if entry is None and _asked(a) else (None, "")
        if refused and args.apply:
            raise WizardError(refused)
        parts, section = _parts(cat, a, root, args.name, entry)
    except (WizardError, typologies.CatalogError, standards.StandardsError, init.InitError) as exc:
        print(f"brain project new: {exc}")
        return 2
    print("\n".join(summary(cat, a, rows)))
    if refused:
        print(f"  --apply refuses: {refused}")
    print("\n".join(project_parts.plan_lines(parts, args.name, entry is None)))
    if entry is not None:
        diff = changes(entry, a)
        pending = [s for s in parts.steps if not s.skip]
        print(f"{root} already holds the brain of {args.name}: " + ("the answers change its entry in projects.yaml:"
                                                                   if diff else "the answers change nothing there"))
        print("\n".join(diff) + ("\n(written by a branch and a PR of that brain, never here)" if diff else ""))
        return 2 if args.apply and (diff or pending) else 0
    code = init.main(_init_args(args, a, refused, section))
    if code or not args.apply:
        return code
    owner = owner_of(args)
    project_parts.log_init(root, [*_words(args, a), "--apply"], code, owner)
    return project_parts.run(parts, root, owner)


def _parts(cat: typologies.Catalog, a: Answers, root: Path, name: str, entry: dict | None):
    """(the parts the answers propose, CLAUDE.md's section or ""): against the folder's brain when it holds one,
    else against what brain init would write (its files without the answers' registry lines: the profiles and the
    files they do not change)."""
    if entry is not None:
        return project_parts.plan_existing(cat, a.kinds, root, name, entry), ""
    tpl = init.load_template(a.template)
    files = init.files_for("owner", "person", None, "lite", name, tpl, a.stage, a.lifecycle())
    data = graph.load_yaml(files.get("projects.yaml") or "") or {}
    std = _dict(_dict(data.get(name) if isinstance(data, dict) else None).get("standards"))
    parts = project_parts.plan_new(cat, a.kinds, std.get("profiles"), files, root, name)
    section = (project_parts.claude_section(cat, a.kinds, a.stage, a.lifecycle_stage, parts.props)
               if parts.claude and parts.props else "")
    return parts, section


def _asked(a: Answers) -> bool:
    """Something of slice 2 was asked: the registry gains lines."""
    return bool(a.lang or a.floor or a.include)


def _rows(a: Answers, name: str) -> tuple[dict | None, str]:
    """(the standards rows the answers select, from the registry brain init would write (its owner aside), with the
    notes of the template's CI; why --apply refuses the answers' lines, or '')."""
    tpl = init.load_template(a.template)
    try:
        files = init.files_for("owner", "person", None, "lite", name, tpl, a.stage, a.lifecycle(),
                               registry_edit(a, name))
    except init.InitError as exc:   # the template's registry cannot take them: said by the plan, refused by --apply
        return None, str(exc)
    return {**selected(a, files["projects.yaml"], name), "ci": ci_notes(a, files)}, ""


def owner_of(args) -> str:
    """--owner, else the owner of this machine's personal brain (its pointer's config.json): the cockpit's wizard
    gives no --owner."""
    if args.owner:
        return args.owner
    there = paths.pointer_root()
    return init.owner_in(there) if there is not None else ""


def _words(args, a: Answers) -> list[str]:
    """The answers as the command the owner types (the plan's apply line, the ledger's)."""
    return ["brain", "project", "new", str(args.dir), *[w for k in a.kinds for w in ("--kind", k)], "--stage",
            a.stage, *(["--template", args.template] if args.template else []),
            *(["--name", args.name] if args.name != "brain" else []), *_answer_words(a)]


def _init_args(args, a: Answers, refused: str = "", section: str = ""):
    """brain init's arguments for the answers: the template, the stage, the name, the owner, the lifecycle and the
    registry's other answers (the language and tools, the data); ``refused``: the plan shows the template's registry
    without them, --apply having been refused before; ``section``: CLAUDE.md's « What it produces » (slice 3)."""
    import argparse
    words = _words(args, a)
    edit = registry_edit(a, args.name) if _asked(a) and not refused else None
    hint = (f"(plan only: {' '.join(words)} --apply refuses it, as said above: its projects.yaml is shown without "
            "the answers' lines)" if refused else f"(plan only: {' '.join(words)} --apply writes it)")
    return argparse.Namespace(dir=args.dir, owner=owner_of(args), template=a.template, kind="person", tenant=None,
                              tier=None, name=args.name, stage=a.stage, preset=None, with_=None, without=None,
                              catalogue=None, interactive=False, apply=args.apply, lifecycle=a.lifecycle(),
                              registry_edit=edit, plan_hint=hint, file_edits={
                                  project_parts.CLAUDE: project_parts.claude_edit(section)} if section else None)


def _answer_words(a: Answers) -> list[str]:
    """The slice 2 answers as the plan's apply line repeats them: each checked, a --tool as SLOT=TOOL (no spaces)."""
    out = ["--lang", a.lang] if a.lang else []
    for spec in a.specs:
        out += ["--tool", spec]
    if a.residency:
        out += ["--residency"]
    elif a.floor:
        out += ["--floor", a.floor]
    return out + (["--personal-data"] if a.include else [])
