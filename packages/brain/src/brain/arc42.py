"""The technical reference's arc42 skeleton (wi-brain-reference-arc42; spec-brain-architecture-docs 5.1): the twelve
sections of ``docs/reference/README.md``, each filled from its source in the graph, with the prose only a person
writes taken from ``docs/reference.yaml`` (``schemas/reference.schema.json``, the README YAML's mechanism: a required
field missing fails ``brain reference`` and ``brain check``).

| Section | From |
|---|---|
| 1 Introduction and goals | ``goals``; the pending milestones and their triggers |
| 2 Constraints | the Rule nodes, the decisions that set them and what enforces them |
| 3 Context and scope | the registry: this project's repos, the other projects and their access |
| 4 Solution strategy | ``strategy``; the decisions ``key_decisions`` names |
| 5 Building blocks | the modules (their pages, ``modules/<id>.md``) |
| 6 Runtime view | the hooks, workflows, skills, plugins and MCP servers of the graph |
| 7 Deployment view | the project's stacks |
| 8 Cross-cutting concepts | the active specs |
| 9 Architecture decisions | the decisions by module, newest first, and the unplaced ones |
| 10 Quality requirements | each milestone's trigger, its items and their tests; the goals with no test |
| 11 Risks and technical debt | blocked items, debt items, open lessons, open questions |
| 12 Glossary | ``glossary`` |

Every statement carries its status and its id (its source in the graph). Sections 2, 3, 5-11 open with the short intro
``sections.<key>`` when the YAML gives one. No date of its own: the same graph gives the same text.
"""

from __future__ import annotations

from pathlib import Path

from . import projects

RUNTIME_TYPES = (("Hook", "Hooks"), ("Workflow", "Workflows"), ("Skill", "Skills"), ("Plugin", "Plugins"),
                 ("McpServer", "MCP servers"))
OPEN_LESSON = ("open", "regressed")
NEWEST = 3   # the decisions per module section 9 shows (all are on the module's page)
SECTIONS = (("goals", "1. Introduction and goals"), ("constraints", "2. Constraints"),
            ("context", "3. Context and scope"), ("strategy", "4. Solution strategy"),
            ("building_blocks", "5. Building blocks"), ("runtime", "6. Runtime view"),
            ("deployment", "7. Deployment view"), ("concepts", "8. Cross-cutting concepts"),
            ("decisions", "9. Architecture decisions"), ("quality", "10. Quality requirements"),
            ("risks", "11. Risks and technical debt"), ("glossary", "12. Glossary"))


def _ref():
    from . import reference  # the reference imports this module: its helpers are read at call time
    return reference


def _of(m, ntype: str) -> list[str]:
    return sorted(nid for nid, n in m.nodes.items() if n.get("type") == ntype)


def _line(m, nid: str, extra: str = "") -> str:
    """A node as a statement: its id (its source), its status, its title."""
    r = _ref()
    st = m.nodes.get(nid, {}).get("status")
    return f"- `{nid}`{f' ({st})' if st else ''} {r._title(m, nid)}{extra}".rstrip()


def _out(m, nid: str, etype: str) -> list[str]:
    return sorted({str(e["to"]) for e in m.edges if e.get("type") == etype and str(e["from"]) == nid})


def _into(m, nid: str, etype: str) -> list[str]:
    return sorted({str(e["from"]) for e in m.edges if e.get("type") == etype and str(e["to"]) == nid})


def _ids(ids: list[str]) -> str:
    return ", ".join(f"`{x}`" for x in ids)


def _intro(prose: dict, key: str) -> list[str]:
    text = str((prose.get("sections") or {}).get(key) or "").strip() if isinstance(prose.get("sections"), dict) else ""
    return [text, ""] if text else []


def _missing(key: str) -> list[str]:
    return [f"_Not written yet: `{key}` in `docs/reference.yaml`._", ""]


# --- the sections -----------------------------------------------------------------------------------------------------

def goals(m, prose: dict, ctx: dict) -> list[str]:
    out = ([str(prose["goals"]).strip(), ""] if prose.get("goals") else _missing("goals"))
    pending = [x for x in _of(m, "Milestone") if m.nodes[x].get("status") == "pending"]
    reached = [x for x in _of(m, "Milestone") if m.nodes[x].get("status") == "reached"]
    lines = [_line(m, x, _trigger(m, x)) for x in pending]
    out += [f"Milestones ahead: {len(pending)} ({len(reached)} reached).", ""] + (lines or ["None."])
    return out


def _trigger(m, nid: str) -> str:
    t = _ref()._props(m.nodes.get(nid, {})).get("trigger")
    return f" — reached when: {_ref()._short(t, 160)}" if t else ""


def constraints(m, prose: dict, ctx: dict) -> list[str]:
    lines = []
    for r in _of(m, "Rule"):
        adrs = _out(m, r, "decided_by")
        by = _out(m, r, "enforced_by")
        source = f" — decided by {_ids(adrs)}" if adrs else " — without a decision"
        lines.append(_line(m, r, source + (f"; enforced by {_ids(by)}" if by else "; by judgement")))
    return _intro(prose, "constraints") + (lines or ["No rule in the graph."])


def context(m, prose: dict, ctx: dict) -> list[str]:
    out = _intro(prose, "context")
    reg = ctx.get("registry") or {}
    if not reg:
        return out + ["No project registry (`projects.yaml`) here."]
    out += ["| Project | Access | Repos | Title |", "|---|---|---|---|"]
    for name, row in reg.items():
        mark = " (this one)" if name == ctx.get("project") else ""
        out.append(f"| `{name}`{mark} | {row['access']} | {', '.join(row['repos']) or '-'} | "
                   f"{_ref()._cell(row['title'])} |")
    return out


def registry(root: Path) -> dict[str, dict]:
    """{project: {access, repos, title}} of the registry ``root`` reads, in its order; {} without one."""
    out: dict[str, dict] = {}
    try:
        loaded = projects.load(root)
        ro = projects.readonly(root)
        names = [str(n) for n in projects.raw(root)]
    except (SystemExit, OSError, ValueError):   # a registry that does not load: the section says there is none
        return {}
    for name in names:
        if name in loaded:
            p = loaded[name]
            try:
                repos = sorted(c.name for c in projects.repos_of(p))
            except projects.RepoError:
                repos = []
            out[name] = {"access": "write", "repos": repos, "title": p.title or ""}
        elif name in ro:
            out[name] = {"access": "read", "repos": [], "title": ro[name].title or ""}
    return out


def strategy(m, prose: dict, ctx: dict) -> list[str]:
    out = [str(prose["strategy"]).strip(), ""] if prose.get("strategy") else _missing("strategy")
    keys = [str(k) for k in prose.get("key_decisions") or [] if isinstance(k, str)]
    if not keys:
        return out
    units = {u.id: u for u in m.units}
    lines = []
    for k in keys:
        if k in units:
            lines.append(f"- {_ref()._unit_line(units[k])}")
        elif k in m.nodes:
            lines.append(_line(m, k))
        else:
            lines.append(f"- `{k}`: not in the graph")
    return out + ["Key decisions:", ""] + lines


def building_blocks(m, prose: dict, ctx: dict) -> list[str]:
    r = _ref()
    out = _intro(prose, "building_blocks")
    if not m.registry:
        return out + ["No module registry (`modules.yaml`) in this store: no module page."]
    placed = ctx["placed"]
    order = sorted(m.registry, key=lambda x: (str(x.get("brick") or "?"), len(str(x["id"])), str(x["id"])))
    out += ["| Module | Name | Brick | Features | Items done | Items open | Decisions |", "|---|---|---|---|---|---|---|"]
    return out + [r._index_row(m, mod, placed) for mod in order]


def runtime(m, prose: dict, ctx: dict) -> list[str]:
    out = _intro(prose, "runtime")
    found = False
    for ntype, title in RUNTIME_TYPES:
        ids = _of(m, ntype)
        if ids:
            found = True
            out += [f"### {title}: {len(ids)}", ""] + [_line(m, x) for x in ids] + [""]
    return out if found else out + ["No hook, workflow, skill, plugin or MCP server in the graph."]


def deployment(m, prose: dict, ctx: dict) -> list[str]:
    out = _intro(prose, "deployment")
    stacks = ctx.get("stacks") or []
    if not stacks:
        return out + ["No stack declared for this project (`projects.yaml` `stacks`)."]
    return out + [f"- `{s}`" for s in stacks] + ["", "`brain health` shows their state on a machine, `brain profile` "
                                                  "what the machine runs."]


def concepts(m, prose: dict, ctx: dict) -> list[str]:
    specs = [x for x in _of(m, "Spec") if m.nodes[x].get("status") == "active"]
    return _intro(prose, "concepts") + (["The specs in force:", ""] + [_line(m, s) for s in specs] if specs
                                        else ["No spec in force."])


def decisions(m, prose: dict, ctx: dict) -> list[str]:
    r = _ref()
    out = _intro(prose, "decisions")
    placed = ctx["placed"]
    for mod in m.registry:
        mid = str(mod["id"])
        us = sorted(placed.get(mid, []), key=lambda u: (u.date, u.id), reverse=True)
        if not us:
            continue
        more = f" ({len(us) - NEWEST} more on [its page]({r.MODULES_DIR}/{r.page_name(mid)}))" if len(us) > NEWEST \
            else ""
        out += [f"### {mid} {r._cell(mod.get('name'))}: {len(us)}{more}".rstrip(), ""]
        out += [f"- {r._unit_line(u)}" for u in us[:NEWEST]] + [""]
    left = sorted(placed.get(r.UNPLACED, []), key=lambda u: (u.date, u.id), reverse=True)
    out += [f"### Unplaced decisions: {len(left)}", "",
            "Decisions about no node of a module (no item, spec or feature with a module): a debt line, placed by "
            "giving their nodes a module (`brain item set <id> props.module=<module>`).", ""]
    return out + ([f"- {r._unit_line(u)}" for u in left] or ["None."])


def _tests_of(m, items: list[str]) -> list[str]:
    """The tests that check ``items``: theirs (tested_by), and those of the features they deliver."""
    feats = {f for i in items for f in _out(m, i, "delivers")}
    return sorted({t for x in [*items, *feats] for t in _out(m, x, "tested_by")
                   if m.nodes.get(t, {}).get("type") == "Test"})


def quality(m, prose: dict, ctx: dict) -> list[str]:
    out = _intro(prose, "quality")
    goals_, untested = [], 0
    for ms in _of(m, "Milestone"):
        if not _ref()._props(m.nodes[ms]).get("trigger"):
            continue
        items = [i for i in _into(m, ms, "part_of") if m.nodes.get(i, {}).get("type") == "WorkItem"]
        done = sum(1 for i in items if m.nodes[i].get("status") == "done")
        tests = _tests_of(m, items)
        untested += not tests
        shown = _ids(tests[:5]) + (f" (+{len(tests) - 5})" if len(tests) > 5 else "")
        goals_.append(_line(m, ms, f"{_trigger(m, ms)}; items {done} done of {len(items)}; tests: "
                                   f"{shown or '**none**'}"))
    if not goals_:
        return out + ["No milestone with a trigger in the graph."]
    return out + [f"Each goal (a milestone's trigger), its items and their tests; goals with no test: {untested}.",
                  ""] + goals_


def risks(m, prose: dict, ctx: dict) -> list[str]:
    r = _ref()
    items = _of(m, "WorkItem")
    blocked = [i for i in items if m.nodes[i].get("status") == "blocked"]
    debt = [i for i in items if "debt" in i.split("-") and m.nodes[i].get("status") in r.OPEN]
    lessons = [x for x in _of(m, "Lesson") if m.nodes[x].get("status") in OPEN_LESSON]
    pending = sorted(m.pending, key=lambda d: str(d["id"]))
    out = _intro(prose, "risks")
    out += [f"### Blocked items: {len(blocked)}", ""] + ([_line(m, i) for i in blocked] or ["None."]) + [""]
    out += [f"### Debt items: {len(debt)}", ""] + ([_line(m, i) for i in debt] or ["None."]) + [""]
    out += [f"### Open lessons: {len(lessons)}", ""] + ([_line(m, x) for x in lessons] or ["None."]) + [""]
    out += [f"### Open questions: {len(pending)}", ""]
    return out + ([f"- `{d['id']}` (pending) {r._short(d.get('question') or d.get('title'), 140)}" for d in pending]
                  or ["None."])


def glossary(m, prose: dict, ctx: dict) -> list[str]:
    terms = [g for g in prose.get("glossary") or [] if isinstance(g, dict) and g.get("term")]
    if "glossary" not in prose:
        return _missing("glossary")
    if not terms:
        return ["No term yet."]
    r = _ref()
    return ["| Term | Means |", "|---|---|"] + [f"| {r._cell(g['term'])} | {r._cell(g.get('means'))} |"
                                               for g in sorted(terms, key=lambda g: str(g["term"]).lower())]


RENDER = {"goals": goals, "constraints": constraints, "context": context, "strategy": strategy,
          "building_blocks": building_blocks, "runtime": runtime, "deployment": deployment, "concepts": concepts,
          "decisions": decisions, "quality": quality, "risks": risks, "glossary": glossary}


def sections(m, prose: dict, ctx: dict) -> list[str]:
    """The twelve sections, in order: a heading each, then its lines."""
    out: list[str] = []
    for key, title in SECTIONS:
        body = RENDER[key](m, prose, ctx)
        while body and body[-1] == "":
            body.pop()
        out += ["", f"## {title}", ""] + body
    return out
