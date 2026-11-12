"""``brain mod``: the module face of ``brain profile`` (wi-brain-mod-command; spec sigma-modules §5): the modules of
the store's registry (``modules.yaml``, or the one ``config.json`` ``modules.store`` names) that list the engine's
``capabilities``, turned on and off on the same files with a plan, then an apply. Zero token.

- **The layers**, in this order (brain.tiers.choice): the base preset (Lite, Défaut, Recommandé), then ``config.json``
  ``tier.components`` (the brain's default, by a reviewed PR), then ``$BRAIN_HOME/profile.json`` (this machine), each
  layer's module ids expanded to their capabilities, a capability it names directly winning over its module; then the
  hard dependencies pulled; a core capability never goes off, an auto one serves when it is found.
- **Dependencies.** A capability declares ``depends_on`` (hard: pulled when it is on) and ``uses`` (soft: a provider
  it reads, its ``fallback`` otherwise) in tiers.yaml. A module depends on another when its registry entry says so
  (``depends_on``, ids of the registry) or when one of its capabilities depends on one of the other's (deduced).
  ``enable`` pulls the hard ones and the plan shows them; ``disable`` is refused while a module that is on needs it,
  unless ``--cascade``, which turns those off too.
- **Without a registry**, or with no entry listing capabilities, each capability is its own module: a brain without
  modules works as before.
- ``enable`` and ``disable`` write this machine's ``profile.json`` (``--apply``; a second apply changes nothing); the
  default of every machine is ``config.json``'s, changed by a PR. ``explain`` shows each layer for one module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config, modules, tiers


@dataclass
class Module:
    id: str
    name: str
    capabilities: list
    depends_on: list = field(default_factory=list)     # module ids, from the registry
    uses: list = field(default_factory=list)
    realized_by: list = field(default_factory=list)
    from_registry: bool = True


class ModError(Exception):
    """A module that cannot be turned on or off as asked (exit code 2)."""


def _store(root: Path | None) -> Path | None:
    if root is None:
        return None
    store = Path(root) / "notes" / "graph"
    return store if store.is_dir() else None


def _ids(v) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


def _from_registry(entries: list[dict], reg: dict) -> dict[str, Module]:
    """The registry's entries that list capabilities of tiers.yaml, as modules."""
    out = {}
    for m in entries:
        caps = [c for c in _ids(m.get("capabilities")) if c in reg]
        if caps:
            out[str(m["id"])] = Module(str(m["id"]), str(m.get("name") or m["id"]), caps, _ids(m.get("depends_on")),
                                       _ids(m.get("uses")), list(m.get("realized_by") or []))
    return out


def catalogue(root: Path | None, reg: dict | None = None, store: Path | None = None) -> dict[str, Module]:
    """The modules: the registry's entries that list capabilities (of tiers.yaml), else one per capability."""
    reg = reg if reg is not None else tiers.registry(root)[0]
    store = store or _store(root)
    out = _from_registry((modules.registry(store, root) or []) if store is not None else [], reg)
    if out:
        return out
    return {e.id: Module(e.id, e.title, [e.id], list(e.depends_on), list(e.uses), from_registry=False)
            for e in reg.values() if e.kind == "capability"}


def groups(root: Path | None) -> dict[str, list[str]]:
    """{module id: its capabilities} of the registry's modules (what tier.components and profile.json may name)."""
    return {m.id: m.capabilities for m in catalogue(root).values() if m.from_registry}


def resolve(cat: dict[str, Module], ref: str) -> Module:
    if ref in cat:
        return cat[ref]
    hit = [m for m in cat.values() if m.name == ref]
    if len(hit) == 1:
        return hit[0]
    raise ModError(f"no module {ref!r} (brain mod list shows them)")


def needs(cat: dict[str, Module], reg: dict) -> dict[str, set[str]]:
    """{module: the modules it depends on, hard}: the registry's, and those its capabilities' depends_on deduce."""
    owner = {c: m.id for m in cat.values() for c in m.capabilities}
    out = {}
    for m in cat.values():
        deps = {d for d in m.depends_on if d in cat}
        for c in m.capabilities:
            deps |= {owner[d] for d in getattr(reg.get(c), "depends_on", []) if d in owner}
        out[m.id] = deps - {m.id}
    return out


def _closure(start: str, edges: dict[str, set[str]]) -> list[str]:
    seen, todo = [], list(edges.get(start, ()))
    while todo:
        d = todo.pop(0)
        if d not in seen and d != start:
            seen.append(d)
            todo += sorted(edges.get(d, ()))
    return seen


def switched(m: Module, reg: dict) -> list[str]:
    """The module's capabilities a profile turns on and off (an auto one is used whenever it is found)."""
    return [c for c in m.capabilities if c in reg and not reg[c].auto]


def state(m: Module, on: set[str], reg: dict | None = None) -> str:
    caps = switched(m, reg) if reg is not None else m.capabilities
    if not caps:
        return "auto"
    n = sum(c in on for c in caps)
    return "on" if n == len(caps) else "off" if n == 0 else f"partly on ({n}/{len(caps)})"


def _layer(m: Module, comps: dict) -> bool | None:
    """What one layer says of the module: its capabilities named directly win over its id."""
    vals = [comps[c] for c in m.capabilities if c in comps]
    if vals:
        return all(vals) if all(vals) or not any(vals) else None
    return comps.get(m.id)


def rows(root: Path | None) -> list[dict]:
    """brain mod list: each module, its state, where its state comes from, its fallback."""
    reg, _ = tiers.registry(root)
    cat, ch = catalogue(root, reg), tiers.choice(root)
    on, _ = tiers.active(reg, ch)
    keep = tiers.preset(reg, ch.base)
    out = []
    for m in cat.values():
        source = ("profile.json" if _layer(m, ch.own or {}) is not None
                  else "config.json" if _layer(m, ch.inherited) is not None
                  else "preset" if any(c in keep for c in m.capabilities)
                  else "pulled" if any(c in on for c in m.capabilities) else "-")
        out.append({"id": m.id, "name": m.name, "state": state(m, on, reg), "source": source,
                    "capabilities": m.capabilities,
                    "fallback": "; ".join(sorted({reg[c].fallback for c in m.capabilities if reg[c].fallback}))})
    return out


def show(root: Path | None, ref: str) -> dict:
    reg, _ = tiers.registry(root)
    cat = catalogue(root, reg)
    m = resolve(cat, ref)
    on, _ = tiers.active(reg, tiers.choice(root))
    caps = [{"id": c, "class": reg[c].cls, "profile": reg[c].profile, "requires": reg[c].requires,
             "resources": reg[c].resources, "fallback": reg[c].fallback, "depends_on": reg[c].depends_on,
             "uses": reg[c].uses, "on": c in on} for c in m.capabilities]
    return {"id": m.id, "name": m.name, "state": state(m, on, reg), "capabilities": caps,
            "depends_on": sorted(needs(cat, reg)[m.id]), "uses": m.uses,
            "realized_by": [{k: r.get(k) for k in ("project", "kind", "state") if isinstance(r, dict)}
                            for r in m.realized_by]}


def _check_enable(m: Module, reg: dict) -> None:
    if not switched(m, reg):
        raise ModError(f"{m.id} is used whenever it is found (auto): no profile turns it on or off")
    for c in m.capabilities:
        if reg[c].status != "built":
            raise ModError(f"{m.id}: {c} is planned ({reg[c].item}), not built yet")


def _fallbacks(m: Module, reg: dict) -> str:
    return "; ".join(sorted({reg[c].fallback for c in m.capabilities if reg[c].fallback}))


def _set(own: dict, cat: dict, mids: list[str], value: bool) -> None:
    """The modules set in the machine's overrides, their capabilities named directly there dropped (a capability named
    directly wins over its module: left, it would undo the switch)."""
    for mid in mids:
        for c in cat[mid].capabilities:
            own.pop(c, None)
        own[mid] = value


def _enable(m: Module, cat: dict, edges: dict, on: set[str], own: dict, reg: dict) -> list[str]:
    pulled = [d for d in _closure(m.id, edges) if state(cat[d], on, reg) not in ("on", "auto")]
    _set(own, cat, [m.id, *pulled], True)
    return ([f"enable {m.id} ({', '.join(m.capabilities)})"]
            + [f"  pulls {d} ({', '.join(cat[d].capabilities)}): {m.id} needs it" for d in pulled]
            + [f"  uses {u} when it is on, its fallback otherwise" for u in m.uses])


def _disable(m: Module, cat: dict, edges: dict, on: set[str], own: dict, reg: dict, cascade: bool) -> list[str]:
    if any(reg[c].cls == "core" for c in m.capabilities):
        raise ModError(f"{m.id} is core: every profile has it")
    if not switched(m, reg):
        raise ModError(f"{m.id} is used whenever it is found (auto): no profile turns it on or off")
    users = [x for x in cat if x != m.id and m.id in _closure(x, edges)
             and state(cat[x], on, reg) not in ("off", "auto")]
    if users and not cascade:
        raise ModError(f"{m.id} is needed by {', '.join(users)}, which are on: --cascade turns them off too")
    _set(own, cat, [m.id, *users], False)
    return ([f"disable {m.id} ({', '.join(m.capabilities)}): {_fallbacks(m, reg) or 'nothing replaces it'}"]
            + [f"  cascade: disable {u}, which needs it" for u in users])


def _keep_differences(own: dict, cat: dict, reg: dict, cur: tiers.Choice, grp: dict) -> dict:
    """The machine's overrides kept where they differ from the default (the preset, then config.json's)."""
    keep = tiers.preset(reg, cur.base)
    return {k: v for k, v in sorted(own.items()) if v != tiers.default_of(k, keep, cur.inherited, grp)}


def plan(root: Path | None, ref: str, enable: bool, cascade: bool = False) -> tuple[tiers.Choice, list[str]]:
    """The choice ``brain mod enable|disable`` would write to profile.json, and the plan's lines."""
    reg, _ = tiers.registry(root)
    cat, cur, grp = catalogue(root, reg), tiers.choice(root), groups(root)
    m = resolve(cat, ref)
    on, _ = tiers.active(reg, cur)
    edges = needs(cat, reg)
    own = dict(cur.own if cur.own is not None else cur.components)
    if enable:
        _check_enable(m, reg)
        lines = _enable(m, cat, edges, on, own, reg)
    else:
        lines = _disable(m, cat, edges, on, own, reg, cascade)
    own = _keep_differences(own, cat, reg, cur, grp)
    new = tiers.Choice(cur.base, own, "machine", cur.machine, computed_from=dict(cur.computed_from), own=own,
                       inherited=cur.inherited, groups=grp)
    after, _ = tiers.active(reg, tiers.Choice(cur.base, {**tiers.expand(cur.inherited, grp), **tiers.expand(own, grp)}))
    gain, loss = sorted(after - on), sorted(on - after)
    cost = {k: v for k in tiers.RESOURCES if (v := sum((reg[e].resources or {}).get(k, 0) for e in gain))}
    lines.append(f"  capabilities on: {', '.join(gain) or 'none'}; off: {', '.join(loss) or 'none'}"
                 + (f"; cost {tiers._cost(cost)}" if cost else ""))
    return new, lines


def _layer_line(label: str, m: Module, comps: dict) -> str:
    v = _layer(m, comps)
    named = v is not None or m.id in comps or any(c in comps for c in m.capabilities)
    return f"  {label}: " + ({True: "on", False: "off", None: "mixed"}[v] if named else "says nothing")


def _notes(m: Module, reg: dict) -> list[str]:
    return ([f"  note       {c} is core: never off" for c in m.capabilities if reg[c].cls == "core"]
            + [f"  note       {c} is auto: used whenever it is found ({reg[c].fallback} otherwise)"
               for c in m.capabilities if reg[c].auto])


def explain(root: Path | None, ref: str) -> list[str]:
    """Each layer for one module: the engine's preset, config.json, profile.json, the dependencies pulled, a scope's
    capabilities (declared)."""
    reg, _ = tiers.registry(root)
    cat, ch = catalogue(root, reg), tiers.choice(root)
    m = resolve(cat, ref)
    on, _ = tiers.active(reg, ch)
    keep = tiers.preset(reg, ch.base)
    pulled = [c for c in m.capabilities if c in on and c not in keep and ch.components.get(c) is not True]
    return ([f"{m.id} ({m.name}): {state(m, on, reg)}",
             f"  engine     base {ch.base}: "
             + ", ".join(f"{c} {'on' if c in keep else 'off'}" for c in m.capabilities),
             _layer_line("config     config.json tier.components", m, ch.inherited),
             _layer_line("machine    profile.json", m, ch.own or {}),
             "  pulled     " + (", ".join(f"{c} (a dependency of what is on)" for c in pulled) or "nothing")]
            + ([f"  scope      {s}" for s in _scopes(root, m)] or ["  scope      no scope says anything of it"])
            + _notes(m, reg))


def _scopes(root: Path | None, m: Module) -> list[str]:
    """The scopes whose capabilities (require, forbid) name the module or one of its capabilities: declared (the
    scope tree reserves the key; its enforcement is a later item)."""
    from . import scopes

    names = {m.id, *m.capabilities}
    out = []
    try:
        nodes = scopes.nodes_of(config.load(root))
    except (OSError, ValueError, KeyError, TypeError):
        return []
    for nid, spec in sorted(nodes.items()):
        caps = spec.get("capabilities") if isinstance(spec, dict) else None
        if not isinstance(caps, dict):
            continue
        for key in ("require", "forbid"):
            hit = names & {str(x) for x in caps.get(key) or []}
            if hit:
                out.append(f"{nid} {key}s {', '.join(sorted(hit))} (declared, not enforced yet)")
    return out
