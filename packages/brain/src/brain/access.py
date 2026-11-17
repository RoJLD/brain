"""Access, the doctrine (spec-brain-access, ACC-1 to ACC-4; slice 1, **read only**): who may do what, where, as
``members.yaml`` declares it. Nothing here refuses a command: the decision function that will (``access.decide``,
called by the CLI, the guards and the MCP server) is a later slice; this one makes the model readable and checked.

- **Grades** on nodes of the scope tree, ordered, each including the one below it (:data:`GRADES`): ``viewer`` (read),
  ``contributor`` (+ propose), ``maintainer`` (+ write), ``owner`` (+ administer). Their ids are fixed; their labels
  are renamed per brain by config.json ``grades`` (``{"contributor": {"en": "Researcher", "fr": "Chercheur"}}``).
- **Capability roles**, orthogonal to the grades, granted on a node (:data:`ROLES`): ``decider`` (decide: answers the
  node's DDRs, brain.identity verifies its signatures), ``releaser`` (signs release tags), ``auditor`` (reads the
  node's ledgers and access log, not its stores). Another role is kept and noted (a newer brain's).
- **Groups** (``groups: [{id, title, members}]``): people and other groups, nested; a cycle is an error.
- **Grants** are ``memberships`` entries: a person (``person_id``) **or** a group (``group``), a node (``scope``, a
  node id of the scope tree, ``project`` its synonym; absent: Global, the whole brain), a ``grade``, ``roles``, and
  optionally ``since`` and ``until`` (dates; an expired grant counts for nothing). A membership of an organization or
  a tenant is another identity domain and grants nothing here. A role that is a grade id (``owner``, ``viewer``...)
  reads as that grade; ``member`` reads as ``viewer`` (never above).
- **Inheritance**: down the tree, by union, the highest grade winning (a grant on a container holds in every node
  under it); the roles too.
- **An agent** acts for a person (ACC-4): its reach is the person's verbs intersected with its client's ceiling,
  read and propose by default (writes per client wait on wi-brain-agent-attribution); an owner's gesture and a
  decision are never an agent's.
- **The unknown**: a grade this engine does not know reads as none (never above), noted (strict, CI: an error); an
  unknown key in a grant is the schema's note.

:func:`errors` is what ``brain check`` and ``brain identity check`` add to members.yaml's (warnings, errors under
config.json ``identity.require_signed``, as every identity finding); :func:`explain` is ``brain access explain
PERSON [--scope REF] [--client C]``, with the grant behind each verb. A solo brain (no members.yaml, or one owner on
Global) changes nothing. Zero token, standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from . import schema

GRADES = ("viewer", "contributor", "maintainer", "owner")
VERBS = ("read", "propose", "write", "decide", "administer")
GRADE_VERBS = {"viewer": ("read",), "contributor": ("read", "propose"), "maintainer": ("read", "propose", "write"),
               "owner": ("read", "propose", "write", "administer")}
ROLES = {"decider": "decide: answers the node's DDRs (brain.identity verifies an owner-class answer's signature)",
         "releaser": "signs the engine's release tags (brain identity allowed-signers)",
         "auditor": "reads the node's ledgers and access log, not its stores"}
ROLE_VERBS = {"decider": ("decide",)}
LEGACY = {"member": "viewer"}   # identity's roles before the grades: read as the grade never above them
LABELS = {"viewer": {"en": "Viewer", "fr": "Lecteur"}, "contributor": {"en": "Contributor", "fr": "Contributeur"},
          "maintainer": {"en": "Maintainer", "fr": "Mainteneur"}, "owner": {"en": "Owner", "fr": "Propriétaire"}}
CEILING = ("read", "propose")   # an agent's client, by default (ACC-4; the ceiling per client: a later slice)
GLOBAL = "global"
ID = re.compile(r"[a-z0-9][a-z0-9-]*\Z")


@dataclass
class Grant:
    """One membership as a grant: who (a person or a group), where (a node, Global by default), what."""
    index: int
    person: str = ""
    group: str = ""
    node: str = GLOBAL
    grade: str = ""                    # one of GRADES, '' when none (a role alone), or an unknown one (kept, said)
    roles: list[str] = field(default_factory=list)
    since: str = ""
    until: str = ""

    @property
    def ref(self) -> str:
        who = f"group {self.group}" if self.group else self.person
        return f"memberships[{self.index}] ({who} on {self.node})"

    def active(self, today: str) -> bool:
        return (not self.since or self.since <= today) and (not self.until or today <= self.until)


# --- reading members.yaml ---

def _list(data: dict, key: str) -> list:
    items = data.get(key) if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _day(value) -> str:
    return value.isoformat() if isinstance(value, date) else _text(value)


def grants(data: dict) -> list[Grant]:
    """Every membership of the brain's own domain (not an organization's or a tenant's) as a grant, in file order."""
    out = []
    for i, m in enumerate(_list(data, "memberships")):
        if not isinstance(m, dict) or m.get("organization") or m.get("tenant"):
            continue
        roles = [r for r in m.get("roles") or [] if isinstance(r, str)] if isinstance(m.get("roles"), list) else []
        node = _text(m.get("scope")) or _text(m.get("project")) or GLOBAL
        grade = _text(m.get("grade"))
        legacy = [LEGACY.get(r, r) for r in roles if r in GRADES or r in LEGACY]
        grade = _highest([g for g in [grade, *legacy] if g])
        out.append(Grant(i, _text(m.get("person_id")), _text(m.get("group")), node, grade,
                         [r for r in roles if r not in GRADES and r not in LEGACY], _day(m.get("since")),
                         _day(m.get("until"))))
    return out


def _highest(grades: list[str]) -> str:
    """The highest known grade of ``grades``; an unknown one only when no known one is there (it gives nothing)."""
    known = [g for g in grades if g in GRADES]
    if known:
        return max(known, key=GRADES.index)
    return grades[0] if grades else ""


def groups(data: dict) -> dict[str, list[str]]:
    """{group id: its members as declared (people and groups)}."""
    out = {}
    for g in _list(data, "groups"):
        if isinstance(g, dict) and isinstance(g.get("id"), str):
            members = g.get("members")
            out.setdefault(g["id"], [x for x in members if isinstance(x, str)] if isinstance(members, list) else [])
    return out


def memberships_of(person: str, data: dict) -> dict[str, list[str]]:
    """{each group ``person`` belongs to, nested ones included: the path from the person up to it}. A cycle ends a
    path (errors() reports it)."""
    gs = groups(data)
    out: dict[str, list[str]] = {}
    frontier = [(g, [g]) for g, members in gs.items() if person in members]
    while frontier:
        g, path = frontier.pop(0)
        if g in out:
            continue
        out[g] = path
        frontier += [(h, path + [h]) for h, members in gs.items() if g in members and h not in out]
    return out


def labels(cfg_data: dict) -> dict[str, dict[str, str]]:
    """The grades' labels: :data:`LABELS`, config.json ``grades`` merged over them (a rename; the id stays)."""
    out = {g: dict(v) for g, v in LABELS.items()}
    given = cfg_data.get("grades") if isinstance(cfg_data, dict) else None
    for gid, spec in (given.items() if isinstance(given, dict) else []):
        if gid in out and isinstance(spec, dict):
            out[gid].update({k: v for k, v in spec.items() if isinstance(v, str) and v})
    return out


# --- the reference checks ---

def errors(data: dict, tree, cfg_data: dict | None = None) -> list[str]:
    """What members.yaml's access fields break that its schema cannot say: a group's id (unique, not a person's), its
    members (a person or a group), a cycle among groups; a grant naming a person or a group (exactly one) that exists,
    a node of the scope tree by its id (an alias is named as one), a grade (an unknown one noted, strict an error), a
    grant that grants nothing, ``until`` before ``since``; config.json ``grades`` naming no grade."""
    people = {p.get("person_id") for p in _list(data, "people") if isinstance(p, dict)}
    out = _group_errors(data, people)
    gs = groups(data)
    for i, m in enumerate(_list(data, "memberships")):
        if not isinstance(m, dict) or m.get("organization") or m.get("tenant"):
            continue
        out += _grant_errors(f"memberships[{i}]", m, people, gs, tree)
    given = (cfg_data or {}).get("grades")
    if given is not None and not isinstance(given, dict):
        out.append("config.json grades is a mapping of grade id -> {en, fr}")
    for gid in sorted(given) if isinstance(given, dict) else []:
        if gid not in GRADES:
            out += schema.tolerate(f"config.json grades: {gid!r} is no grade ({', '.join(GRADES)}): a brain's own "
                                   "grade is an extension point, not built")
    return out


def _group_errors(data: dict, people: set) -> list[str]:
    out = []
    seen: set[str] = set()
    gs = groups(data)
    for i, g in enumerate(_list(data, "groups")):
        where = f"groups[{i}]"
        if not isinstance(g, dict) or not isinstance(g.get("id"), str):
            out.append(f"{where}: a mapping with an id, a title and members")
            continue
        gid = g["id"]
        if gid in seen:
            out.append(f"{where}: group {gid!r} is declared twice")
        seen.add(gid)
        if gid in people:
            out.append(f"{where}: group {gid!r} is a person_id too (a member names one or the other)")
        for x in gs.get(gid, []) if isinstance(g.get("members"), list) else []:
            if x not in people and x not in gs:
                out.append(f"{where}: member {x!r} is neither a person_id nor a group")
            elif x == gid:
                out.append(f"{where}: group {gid!r} lists itself")
    out += [f"groups: a cycle: {' -> '.join(c)}" for c in _cycles(gs)]
    return out


def _cycles(gs: dict[str, list[str]]) -> list[list[str]]:
    """Each cycle among groups once (a group listing itself is said apart), as the path that closes it."""
    found: list[list[str]] = []
    keys: set[frozenset] = set()

    def walk(g: str, path: list[str]) -> None:
        for x in gs.get(g, []):
            if x not in gs or x == g:
                continue
            if x in path:
                cycle = path[path.index(x):] + [x]
                key = frozenset(cycle)
                if key not in keys:
                    keys.add(key)
                    found.append(cycle)
                continue
            walk(x, path + [x])

    for g in gs:
        walk(g, [g])
    return found


def _grant_errors(where: str, m: dict, people: set, gs: dict, tree) -> list[str]:
    out = []
    person, group = m.get("person_id"), m.get("group")
    if (person is None) == (group is None):
        out.append(f"{where}: names a person_id or a group, exactly one")
    elif group is not None and group not in gs:
        out.append(f"{where}: group {group!r} is not in groups")
    scope, project = m.get("scope"), m.get("project")
    if scope is not None and project is not None and scope != project:
        out.append(f"{where}: scope and project name two nodes ({scope!r}, {project!r}): project is scope's synonym")
    node = scope if scope is not None else project
    if node is not None:
        out += _node_errors(where, node, tree)
    grade = m.get("grade")
    if grade is not None and grade not in GRADES:
        out += schema.tolerate(f"{where}: grade {grade!r} is not one of {', '.join(GRADES)} (read as none, never "
                               "above)")
    since, until = _day(m.get("since")), _day(m.get("until"))
    if since and until and until < since:
        out.append(f"{where}: until {until} is before since {since}")
    return out


def _node_errors(where: str, node, tree) -> list[str]:
    if not isinstance(node, str) or not node:
        return [f"{where}: scope is a node id of the scope tree"]
    if node == GLOBAL or node in tree.nodes:
        return []
    alias = getattr(tree, "aliases", {}).get(node)
    if alias:
        return [f"{where}: scope {node!r} is an alias of {alias}: a grant names a node by its id (frozen)"]
    return [f"{where}: scope {node!r} is no node of the scope tree (brain scopes lists them)"]


# --- the effective right, explained ---

def chain(tree, node: str) -> list[str]:
    """``node`` and its ancestors, nearest first, then Global."""
    return [GLOBAL] if node == GLOBAL else [node, *tree.chain(node), GLOBAL]


def explain(data: dict, person: str, tree, node: str = GLOBAL, client: str = "", today: str = "") -> dict:
    """``person``'s effective right on ``node``: the grade (the highest along the node's chain, by union of the
    person's own grants and their groups'), the verbs it gives with the grants behind each, the roles likewise; with
    ``client``, the agent's reach (the verbs within its ceiling, never administer nor decide); the grants that do not
    count today (expired, not yet started) apart."""
    today = today or date.today().isoformat()
    via = memberships_of(person, data)
    on = set(chain(tree, node))
    mine = [g for g in grants(data) if (g.person == person and not g.group) or (g.group and g.group in via)]
    live = [g for g in mine if g.node in on and g.active(today)]
    verbs: dict[str, list[str]] = {v: [] for v in VERBS}
    roles: dict[str, list[str]] = {}
    unknown = []
    for g in live:
        source = _source(g, via)
        if g.grade and g.grade not in GRADES:
            unknown.append(f"{g.grade} ({source})")
        for v in GRADE_VERBS.get(g.grade, ()):
            verbs[v].append(source)
        for r in g.roles:
            roles.setdefault(r, []).append(source)
            for v in ROLE_VERBS.get(r, ()):
                verbs[v].append(source)
    grade = _highest([g.grade for g in live if g.grade in GRADES])
    out = {"person": person, "node": node, "chain": chain(tree, node), "groups": {g: p for g, p in via.items()},
           "grade": grade, "verbs": {v: s for v, s in verbs.items() if s}, "roles": roles,
           "unknown_grades": unknown,
           "not_counted": [_source(g, via) + (f", until {g.until}" if g.until and g.until < today
                                              else f", since {g.since}") for g in mine
                           if g.node in on and not g.active(today)]}
    if client:
        reach = [v for v in out["verbs"] if v in CEILING]
        out["client"] = {"name": client, "ceiling": list(CEILING), "verbs": reach,
                         "never": ["administer", "decide"]}
    return out


def _source(g: Grant, via: dict[str, list[str]]) -> str:
    what = g.grade or "+".join(g.roles) or "nothing"
    how = f"via group {' -> '.join(via[g.group])}" if g.group else "direct"
    return f"{what} on {g.node}, memberships[{g.index}], {how}"


def nodes_with_grants(data: dict, person: str, tree) -> list[str]:
    """Global, then each node a grant of ``person`` (or of one of their groups) names, in tree order."""
    via = memberships_of(person, data)
    named = {g.node for g in grants(data) if (g.person == person and not g.group) or (g.group and g.group in via)}
    return [GLOBAL] + [n for n in tree.subtree(GLOBAL) if n in named]


def people(data: dict) -> list[str]:
    return [p["person_id"] for p in _list(data, "people") if isinstance(p, dict) and isinstance(p.get("person_id"),
                                                                                                 str)]
