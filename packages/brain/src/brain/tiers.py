"""The tier registry and the profiles: Lite, Défaut, Recommandé, Personnalisable (wi-brain-tier-registry,
wi-brain-profile).

Every capability of the engine (``tiers.yaml`` next to this module) and every stack of projects.yaml declares its
class (core, extra, service), the profile that brings it in (lite, default, recommended, custom), what it provides,
its requirements, its cost, its fallback and, for recommended, its ``recommend_when`` rule (the keys are described at
the top of tiers.yaml). ``brain check --all`` refuses an entry without them (:func:`check`); a stack without them
still runs as before, in every profile.

The profiles (identifiers in English, names as the owner gave them):
  lite         the core entries: Python, git, bash and files, no dependency
  default      Lite plus the entries of profile default: the extras without any service (the cockpit's TUI)
  recommended  Default plus the entries of profile recommended whose requirements and rule hold on this machine
               (:func:`recommend`); a proposal: ``brain profile set recommended --apply`` freezes the chosen set into
               the machine's overrides, so the machine is rebuilt from that file, not from a new detection
  custom       the overrides (components: {id: true|false}) over any base; an entry of profile custom comes in only
               this way

The machine's choice is ``$BRAIN_HOME/profile.json`` (``brain profile set ... --apply``), else config.json's ``tier``
(the brain's default base, lite or default, and overrides for every machine), else the built-in base, default: what a
simple install gives. An auto entry (gitleaks, gh) is used whenever it is found, whatever the profile. A stack outside
the active profile is reported OFF by brain health, never as a failure (:func:`outside`). Nothing here installs or
starts anything: install.ps1 reads ``brain profile render --json`` (the pip extras) and applies, and the stacks start
on demand (brain up).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config, graph, paths, probe

FILE = Path(__file__).with_name("tiers.yaml")
INFRA_NODE = "infra-node"   # the switch of the agent report provider (brain.machine), off by default
MACHINE_FILE = "profile.json"
CLASSES = ("core", "extra", "service")
PROFILES = ("lite", "default", "recommended", "custom")
BASES = ("lite", "default", "recommended")
NAMES = {"lite": "Lite", "default": "Défaut", "recommended": "Recommandé", "custom": "Personnalisable"}
BUILT_IN = "default"
STACK_KEYS = ("class", "profile", "provides", "requires", "resources", "fallback", "recommend_when")
KEYS = set(STACK_KEYS) | {"title", "auto", "install", "status", "item"}
RESOURCES = ("ram_mb", "disk_mb", "disk_gb", "vram_gb")
CLAUSE = re.compile(r"^(not\s+)?([A-Za-z0-9_:.-]+)(?:\s*(>=|<=|==|!=|>|<)\s*(\S+))?$")
REQUIREMENT = re.compile(r"^(env:[A-Z_][A-Z0-9_]*|[a-z][a-z0-9_-]*)$")
OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}


class TierError(Exception):
    """A choice that cannot be made: an unknown, planned, core or auto entry asked for (exit code 2)."""


@dataclass
class Entry:
    id: str
    kind: str                  # capability (tiers.yaml) or stack (projects.yaml)
    title: str
    cls: str = ""
    profile: str = ""          # "" for a stack that declares nothing yet: in every profile, as before
    provides: list = field(default_factory=list)
    requires: list = field(default_factory=list)
    resources: dict = field(default_factory=dict)
    fallback: str = ""
    recommend_when: list = field(default_factory=list)
    auto: bool = False
    pip: str = ""
    status: str = "built"
    item: str = ""
    project: str = ""
    depends_on: list = field(default_factory=list)

    @property
    def declared(self) -> bool:
        return bool(self.profile)


@dataclass
class Choice:
    base: str
    components: dict = field(default_factory=dict)
    source: str = "built-in"   # machine ($BRAIN_HOME/profile.json), config (config.json tier), built-in
    machine: str = ""
    applied: str = ""
    computed_from: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    own: dict | None = None    # the machine file's own components (components holds them merged over config.json's)
    inherited: dict = field(default_factory=dict)   # config.json's components, the default a machine overrides


# The registry.

def _shape(eid: str, d: dict, where: str, stack: bool) -> list[str]:
    """What is wrong with one declaration (every key present for a capability; for a stack, brain check --all)."""
    errs = []
    unknown = set(d) - (set(STACK_KEYS) if stack else KEYS)
    if unknown:
        errs.append(f"{where}: unknown tier key(s) {', '.join(sorted(unknown))}")
    missing = [k for k in ("class", "profile", "provides", "requires", "resources") if k not in d]
    if d.get("class", "core") != "core" and "fallback" not in d:
        missing.append("fallback")
    if d.get("profile") == "recommended" and "recommend_when" not in d:
        missing.append("recommend_when")
    if missing:
        errs.append(f"{where}: missing {', '.join(missing)} (brain.tiers: class, profile, provides, requires, "
                    "resources; fallback unless core; recommend_when when recommended)")
    if "class" in d and d["class"] not in CLASSES:
        errs.append(f"{where}: class {d['class']!r} is not one of {', '.join(CLASSES)}")
    if "profile" in d and d["profile"] not in PROFILES:
        errs.append(f"{where}: profile {d['profile']!r} is not one of {', '.join(PROFILES)}")
    if d.get("class") == "core" and d.get("profile") not in (None, "lite"):
        errs.append(f"{where}: a core entry is in every profile (profile: lite)")
    if d.get("class") == "core" and d.get("fallback"):
        errs.append(f"{where}: a core entry has no fallback")
    if "recommend_when" in d and d.get("profile") != "recommended":
        errs.append(f"{where}: recommend_when is for profile recommended only")
    for k in ("provides", "requires", "recommend_when"):
        if k in d and not (isinstance(d[k], list) and all(isinstance(x, str) and x.strip() for x in d[k])):
            errs.append(f"{where}: {k} is a list of strings")
    for r in d.get("requires") or [] if isinstance(d.get("requires"), list) else []:
        if isinstance(r, str) and not REQUIREMENT.match(r):
            errs.append(f"{where}: requirement {r!r} is a fact name (git, docker, textual...) or env:NAME")
    for c in d.get("recommend_when") or [] if isinstance(d.get("recommend_when"), list) else []:
        if isinstance(c, str) and not CLAUSE.match(c.strip()):
            errs.append(f"{where}: recommend_when clause {c!r} is FACT, not FACT or FACT OP VALUE")
    res = d.get("resources")
    if "resources" in d and not (isinstance(res, dict) and all(k in RESOURCES and isinstance(v, (int, float))
                                                               for k, v in res.items())):
        errs.append(f"{where}: resources is a mapping of {', '.join(RESOURCES)} to numbers")
    if "fallback" in d and not (isinstance(d["fallback"], str) and d["fallback"].strip()):
        errs.append(f"{where}: fallback says what replaces it, in words")
    if not stack:
        if not (isinstance(d.get("title"), str) and d["title"].strip()):
            errs.append(f"{where}: no title")
        if d.get("status", "built") not in ("built", "planned"):
            errs.append(f"{where}: status is built or planned")
        if d.get("status") == "planned" and not d.get("item"):
            errs.append(f"{where}: a planned entry names the item that builds it")
        inst = d.get("install") or {}
        if not isinstance(inst, dict) or set(inst) - {"pip"}:
            errs.append(f"{where}: install is {{pip: EXTRA}}")
        if "auto" in d and not isinstance(d["auto"], bool):
            errs.append(f"{where}: auto is true or false")
    return errs


def _entry(eid: str, d: dict, kind: str, **extra) -> Entry:
    def lst(k):
        v = d.get(k)
        return [str(x) for x in v] if isinstance(v, list) else []
    inst = d.get("install") if isinstance(d.get("install"), dict) else {}
    return Entry(eid, kind, str(d.get("title") or ""), str(d.get("class") or ""), str(d.get("profile") or ""),
                 lst("provides"), lst("requires"), d.get("resources") if isinstance(d.get("resources"), dict) else {},
                 str(d.get("fallback") or ""), lst("recommend_when"), d.get("auto") is True, str(inst.get("pip") or ""),
                 str(d.get("status") or "built"), str(d.get("item") or ""), **extra)


def capabilities(path: Path = FILE) -> tuple[dict[str, Entry], list[str]]:
    """The engine's capabilities and what is wrong in their file."""
    data = graph.load_yaml_file(path) or {}
    caps = data.get("capabilities") if isinstance(data, dict) else None
    if not isinstance(caps, dict):
        return {}, [f"{path.name}: no capabilities mapping"]
    out, errs = {}, []
    for eid, d in caps.items():
        where = f"{path.name}: {eid}"
        if not isinstance(d, dict):
            errs.append(f"{where}: a capability is a mapping")
            continue
        errs += _shape(str(eid), d, where, stack=False)
        out[str(eid)] = _entry(str(eid), d, "capability")
    return out, errs


def stack_entries(reg: dict) -> dict[str, Entry]:
    """brain.stacks' registry as entries (a stack's tier keys are kept by brain.stacks in Stack.tier)."""
    out = {}
    for name, s in (reg or {}).items():
        e = _entry(name, s.tier, "stack", project=s.project, depends_on=list(s.depends_on))
        e.title = f"the {name} stack of {s.project}" + (f": {', '.join(e.provides)}" if e.provides else "")
        out[name] = e
    return out


def registry(root: Path | None) -> tuple[dict[str, Entry], list[str]]:
    """Capabilities, then stacks (a stack's name may not be a capability's), and the errors found reading them."""
    from . import stacks
    reg, errs = capabilities()
    try:
        st = stacks.load(root)
    except stacks.StackError as exc:
        return reg, errs + [f"stacks: {exc}"]
    for name, e in stack_entries(st).items():
        if name in reg:
            errs.append(f"stack {name!r} ({e.project}): the name of a capability of {FILE.name}")
            continue
        reg[name] = e
    return reg, errs


def check(root: Path | None) -> list[str]:
    """brain check --all: the capabilities file, every stack's tier keys and config.json's tier (the files of the
    repo; this machine's profile.json is brain doctor's to report)."""
    from . import stacks
    reg, errs = registry(root)
    try:
        for name, s in stacks.load(root).items():
            errs += _shape(name, s.tier, f"stack {name!r} ({s.project})", stack=True)
    except stacks.StackError:
        pass
    tier = config.load(root).data.get("tier")
    for eid in (tier.get("components") or {}) if isinstance(tier, dict) else {}:
        if eid not in reg:
            errs.append(f"{config.FILE}: tier.components names {eid!r}, no capability or stack of that name")
    return errs


# Facts and rules.

def truth(clause: str, facts: dict) -> bool | None:
    """One recommend_when clause on the facts, in three states: FACT (true), not FACT, or FACT OP VALUE (numbers,
    else text); None when the fact is unknown (absent, or None: never probed, or the probe could not say), so that
    neither ``ecc`` nor ``not ecc`` holds on a machine whose memory was never read (wi-brain-machine-facts)."""
    m = CLAUSE.match(clause.strip())
    if not m:
        return False
    neg, name, op, value = m.groups()
    have = facts.get(name)
    if have is None:
        return None
    if op is None:
        ok = bool(have)
    else:
        try:
            ok = OPS[op](float(have), float(value))
        except (TypeError, ValueError):
            ok = OPS[op](str(have), value) if op in ("==", "!=") else False
    return not ok if neg else ok


def holds(clause: str, facts: dict) -> bool:
    """The clause is known to hold (:func:`truth` is True): an unknown fact holds neither way."""
    return truth(clause, facts) is True


def missing(e: Entry, facts: dict) -> list[str]:
    """The requirements of ``e`` this machine lacks."""
    out = []
    for r in e.requires:
        ok = bool(os.environ.get(r[4:])) if r.startswith("env:") else bool(facts.get(r))
        if not ok:
            out.append(r)
    return out


def _installable(e: Entry, lack: list[str]) -> bool:
    """True when every missing requirement is the module of the entry's pip extra (install.ps1 brings it)."""
    return bool(e.pip) and all(r in probe.MODULES for r in lack)


def recommend(reg: dict[str, Entry], facts: dict) -> dict[str, str]:
    """{id: why} of the built entries of profile recommended that this machine allows: requirements met (or brought
    by install.ps1) and every recommend_when clause true; a stack only when its dependencies are in too."""
    base = preset(reg, "default")
    out = {}
    for e in reg.values():
        if e.profile != "recommended" or e.status != "built" or e.auto:
            continue
        lack = missing(e, facts)
        if (lack and not _installable(e, lack)) or not all(holds(c, facts) for c in e.recommend_when):
            continue
        out[e.id] = ", ".join(e.recommend_when) or "always"
    changed = True
    while changed:  # a stack whose dependency is not in leaves too
        changed = False
        for eid in list(out):
            if any(d not in out and d not in base for d in reg[eid].depends_on):
                del out[eid]
                changed = True
    return out


def machine_facts(root: Path | None, doc: dict, reg: dict[str, Entry], ch: Choice) -> dict:
    """The flat facts with every source layered (brain.machine.facts): what list, show and set read."""
    from . import machine

    return machine.facts(probe.facts(doc), config.load(root).data, infra_node=INFRA_NODE in active(reg, ch)[0])[0]


def would_fit(reg: dict[str, Entry], facts: dict) -> list[str]:
    """The planned entries of profile recommended this machine would allow once built (shown, never chosen)."""
    return [e.id for e in reg.values() if e.status == "planned" and e.profile == "recommended"
            and not missing(e, facts) and all(holds(c, facts) for c in e.recommend_when)]


# Profiles and the machine's choice.

def preset(reg: dict[str, Entry], base: str) -> set[str]:
    """The entries a base brings without overrides (recommended's own set is frozen in the overrides at apply); a
    stack that declares nothing yet is in every profile."""
    levels = {"lite": ("lite",), "default": ("lite", "default"), "recommended": ("lite", "default")}[base]
    return {e.id for e in reg.values() if e.status == "built" and not e.auto
            and (not e.declared or e.profile in levels)}


def machine_file() -> Path:
    return paths.brain_home() / MACHINE_FILE


def _config_components(root: Path | None) -> dict:
    tier = config.load(root).data.get("tier")
    comps = tier.get("components") if isinstance(tier, dict) else None
    return {str(k): bool(v) for k, v in comps.items()} if isinstance(comps, dict) else {}


def choice(root: Path | None) -> Choice:
    """This machine's choice: $BRAIN_HOME/profile.json (written for this machine), else config.json's tier, else the
    built-in base."""
    name = probe.machine()
    warnings = []
    f = machine_file()
    if f.is_file():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            data = None
            warnings.append(f"{f} is not readable JSON ({exc}): ignored")
        if isinstance(data, dict):
            if data.get("machine") not in (None, name):
                warnings.append(f"{f} was written for {data.get('machine')}, not {name}: ignored "
                                "(brain profile set on this machine)")
            elif data.get("base") not in BASES or not isinstance(data.get("components") or {}, dict):
                warnings.append(f"{f}: base is one of {', '.join(BASES)} and components a mapping: ignored")
            else:
                # the machine's override merged key by key over config.json's components (a key it names wins;
                # one it does not name keeps the brain's default, the infra-node switch say: R25)
                own = {str(k): bool(v) for k, v in (data.get("components") or {}).items()}
                inherited = _config_components(root)
                return Choice(data["base"], {**inherited, **own}, "machine", name, str(data.get("applied") or ""),
                              data.get("computed_from") or {}, warnings, own, inherited)
    tier = config.load(root).data.get("tier")
    if isinstance(tier, dict) and tier.get("base", BUILT_IN) in ("lite", "default"):
        comps = _config_components(root)
        return Choice(tier.get("base", BUILT_IN), comps, "config", name, warnings=warnings, own={}, inherited=comps)
    return Choice(BUILT_IN, {}, "built-in", name, warnings=warnings, own={})


def active(reg: dict[str, Entry], ch: Choice) -> tuple[set[str], list[str]]:
    """The entries the choice turns on, with the dependencies of its stacks, and what is wrong in it."""
    on = preset(reg, ch.base)
    warnings = []
    for eid, want in ch.components.items():
        e = reg.get(eid)
        if not e:
            warnings.append(f"unknown component {eid!r} in the overrides (ignored)")
        elif e.status != "built" or e.auto:
            continue
        elif want:
            on.add(eid)
        elif e.cls != "core":
            on.discard(eid)
    for eid in sorted(on):
        for d in reg[eid].depends_on:
            if d in reg and d not in on:
                if ch.components.get(d) is False:
                    warnings.append(f"{eid} needs {d}, which the overrides turn off")
                else:
                    on.add(d)
    return on, warnings


def state(e: Entry, on: set[str], facts: dict | None) -> tuple[str, str]:
    """(state, detail): on, to install, fallback, missing, off, unavailable, planned, auto (used when found) or
    undeclared (a stack without its tier keys). ``facts`` None: by the choice alone (no probe)."""
    if e.status == "planned":
        return "planned", e.item
    lack = missing(e, facts) if facts is not None else []
    if e.auto:
        if lack:
            return "fallback", f"{', '.join(lack)} not found: {e.fallback}"
        return ("on", "used when found") if e.requires else ("auto", "used once configured")
    if not e.declared:
        return "undeclared", "no tier keys (brain check --all)"
    if e.id in on:
        if not lack:
            return "on", ""
        if _installable(e, lack):
            return "to install", f"pip extra {e.pip} (install.ps1 -Apply)"
        return ("fallback", f"{', '.join(lack)} missing: {e.fallback}") if e.fallback else \
            ("missing", ", ".join(lack))
    if lack and not _installable(e, lack):
        return "unavailable", f"{', '.join(lack)} missing"
    return "off", "available"


def plan(reg: dict[str, Entry], current: Choice, base: str | None, with_: list[str], without: list[str],
         facts: dict | None) -> Choice:
    """The choice ``brain profile set`` would write: a base (recommended: the set this machine allows, frozen into
    the overrides) and the overrides, kept only where they differ from the base. No base: the current choice, with
    these overrides. Raises TierError for an entry that cannot be asked for."""
    if base is None:   # the machine's own overrides only: config.json's stay the brain's default, never copied
        own = current.own if current.own is not None else current.components   # a Choice made by hand
        base, comps, frozen = current.base, dict(own), dict(current.computed_from)
    elif base == "recommended":
        rec = recommend(reg, facts or {})
        base, comps = "recommended", {eid: True for eid in rec}
        frozen = {k: (facts or {}).get(k) for k in ("memory_gb", "gpu_vram_gb", "cpu_cores", "container_runtime",
                                                    "os")}
    else:
        comps, frozen = {}, {}
    if base not in BASES:
        raise TierError(f"base {base!r} is not one of {', '.join(BASES)}")
    wanted = [e.id for e in reg.values() if e.status == "built" and not e.auto] if "all" in with_ else with_
    for eid, value in [(x, True) for x in wanted if x != "all"] + [(x, False) for x in without]:
        e = reg.get(eid)
        if not e:
            raise TierError(f"no capability or stack {eid!r} (brain profile list shows them)")
        if e.status != "built":
            raise TierError(f"{eid} is planned ({e.item}), not built yet")
        if e.auto:
            raise TierError(f"{eid} is used whenever it is found ({e.fallback} otherwise): a profile does not turn "
                            "it on or off")
        if not value and e.cls == "core":
            raise TierError(f"{eid} is core: every profile has it")
        comps[eid] = value
    keep = preset(reg, base)   # an override is kept where it differs from the default: the base, then config.json
    comps = {k: v for k, v in sorted(comps.items()) if v != current.inherited.get(k, k in keep)}
    return Choice(base, comps, "machine", current.machine or probe.machine(), computed_from=frozen,
                  own=comps, inherited=current.inherited)


def write(ch: Choice) -> tuple[Path, bool]:
    """Write the choice to $BRAIN_HOME/profile.json; (path, written): nothing is written when it holds that choice
    already (a second apply changes nothing)."""
    f = machine_file()
    body = {"v": 1, "machine": ch.machine, "base": ch.base, "components": dict(sorted(ch.components.items()))}
    if ch.computed_from:
        body["computed_from"] = ch.computed_from
    try:
        old = json.loads(f.read_text(encoding="utf-8"))
        if {k: old.get(k) for k in body} == body:
            return f, False
    except (OSError, ValueError):
        pass
    body["applied"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return f, True


def label(ch: Choice) -> str:
    """'default (Défaut, built-in)' and its overrides: '+gitnexus -tui'."""
    src = {"machine": f"{MACHINE_FILE}", "config": f"{config.FILE} tier", "built-in": "built-in"}[ch.source]
    over = " ".join(("+" if v else "-") + k for k, v in sorted(ch.components.items()))
    return f"{ch.base} ({NAMES[ch.base]}, {src})" + (f" {over}" if over else "")


# What other commands read.

def render(reg: dict[str, Entry], ch: Choice) -> dict:
    """What install.ps1 reads (brain profile render --json): the pip extras the profile wants, the extras installed
    outside it, the stacks on and off."""
    on, warnings = active(reg, ch)
    extras = sorted({reg[e].pip for e in on if reg[e].pip})
    outside = sorted({e.pip for e in reg.values() if e.pip and e.id not in on and e.status == "built"
                      and all(probe._module(r) for r in e.requires if r in probe.MODULES)
                      and any(r in probe.MODULES for r in e.requires)})
    stacks = [e for e in reg.values() if e.kind == "stack"]
    return {"machine": ch.machine, "base": ch.base, "name": NAMES[ch.base], "source": ch.source,
            "label": label(ch), "components": dict(sorted(ch.components.items())), "extras": extras,
            "extras_outside": [x for x in outside if x not in extras],
            "stacks": {"on": sorted(e.id for e in stacks if e.id in on),
                       "off": sorted(e.id for e in stacks if e.id not in on)},
            "warnings": ch.warnings + warnings}


def outside(root: Path | None, reg: dict) -> dict[str, str]:
    """{stack: why} for brain.stacks' stacks outside this machine's profile: brain health reports them OFF, not
    DOWN. Never raises: on any error, every stack counts as in the profile (as before profiles)."""
    try:
        entries = stack_entries(reg)
        ch = choice(root)
        on, _ = active(entries, ch)
    except Exception:  # noqa: BLE001 - the profile never stops a health check
        return {}
    return {name: f"outside this machine's profile, {ch.base}; brain profile set --with {name} adds it"
            for name, e in entries.items() if e.declared and name not in on}


def doctor(root: Path | None, quick: bool = False, doc: dict | None = None) -> dict:
    """brain doctor: the probe's report with, in its brain block, the profile: the choice, each entry's state, the
    Recommended profile computed for this machine, and the drift between the two (a proposal, never applied)."""
    from . import machine

    doc = doc or probe.collect(quick=quick, roots=[root] if root else None)
    reg, errors = registry(root)
    ch = choice(root)
    on, warnings = active(reg, ch)
    cfg = config.load(root).data
    facts, sourced, provider_errors = machine.facts(probe.facts(doc), cfg, infra_node=INFRA_NODE in on)
    machine.save_facts(sourced)
    ident = machine.identity(cfg)
    rec = recommend(reg, facts)
    rec_set = preset(reg, "default") | set(rec)
    rows = []
    for e in reg.values():
        st, detail = state(e, on, facts)
        rows.append({"id": e.id, "kind": e.kind, "class": e.cls, "profile": e.profile, "auto": e.auto,
                     "status": e.status, "state": st, "detail": detail, "title": e.title, "provides": e.provides,
                     "requires": e.requires, "missing": missing(e, facts), "fallback": e.fallback,
                     "resources": e.resources, "item": e.item, "project": e.project, "pip": e.pip,
                     "recommended": e.id in rec_set})
    gain = sorted(set(rec) - on)
    loss = sorted(e for e in on if reg[e].profile == "recommended" and e not in rec)
    estimate = {k: sum((reg[e].resources or {}).get(k, 0) for e in on) for k in RESOURCES}
    doc["brain"]["profile"] = {
        "active": {"base": ch.base, "name": NAMES[ch.base], "source": ch.source, "label": label(ch),
                   "components": ch.components, "applied": ch.applied, "computed_from": ch.computed_from,
                   "entries": sorted(on), "estimate": {k: v for k, v in estimate.items() if v}},
        "recommended": {"entries": sorted(rec_set), "adds": {k: rec[k] for k in sorted(rec)},
                        "planned_fit": would_fit(reg, facts)},
        "drift": {"allows": gain, "lost": loss},
        "capabilities": rows,
        "inventory": {"providers": ["local"], "nodes": [doc["brain"]["machine"]],
                      "note": "this machine alone: no inventory provider is declared (wi-brain-inventory-providers)"},
        "facts": facts,
        "sources": sourced,
        "identity": ident,
        "warnings": ch.warnings + warnings + provider_errors,
        "errors": errors,
    }
    return doc


# Text views.

def _gb(n) -> str:
    return f"{n / probe.GIB:.1f} GiB" if isinstance(n, (int, float)) and n else "?"


def _cost(res: dict) -> str:
    units = {"ram_mb": "MB RAM", "disk_mb": "MB disk", "disk_gb": "GB disk", "vram_gb": "GB VRAM"}
    return ", ".join(f"{v:g} {units[k]}" for k, v in res.items() if v)


def _fact(v) -> str:
    return "unknown" if v is None else "yes" if v is True else "no" if v is False else \
        ",".join(map(str, v)) if isinstance(v, list) else str(v)


def render_doctor(doc: dict) -> list[str]:
    """brain doctor's text: the machine, the probes, the active profile, each entry's state, Recommended and the
    drift."""
    inv, b = doc["inventory"], doc["brain"]
    prof = b["profile"]
    cpu, mem, plat = inv["cpu"], inv["memory"], inv["platform"]
    tools = b.get("tools") or {}
    distro = f" {plat['distro']}" if plat["distro"] else ""
    ident = prof.get("identity") or {}
    lines = [f"machine   {b['machine']} ({plat['os']} {plat['version']}{distro}, {plat['arch']}), report "
             f"{doc['health']}",
             f"identity  {ident.get('state', '?')}" + (f", anchor {ident['anchor'][:12]} ({ident['anchor_source']})"
                                                     if ident.get("anchor") else "")
             + (f": {ident['doubt']}" if ident.get("doubt") else "")
             + (f"; declare it in config.json: {ident['declare']}" if ident.get("declare") else ""),
             f"cpu       {cpu.get('model') or '?'}, {cpu.get('cores')} logical cores (avx2 "
             f"{'yes' if cpu.get('avx2') else 'no'}, avx512 {'yes' if cpu.get('avx512') else 'no'})",
             f"memory    {_gb(mem.get('total_bytes'))}"
             + (f" ({_gb(mem['free_bytes'])} free)" if mem.get("free_bytes") else "")]
    for g in inv["gpus"]:
        vram = f"{_gb(g['vram_bytes'])} VRAM" if g.get("vram_bytes") else "VRAM unknown"
        lines.append(f"gpu       {g.get('name')}, {vram} ({g.get('source')})")
    if not inv["gpus"]:
        lines.append("gpu       none found")
    inf = inv["inference"]
    lines.append(f"backend   {inf['backend']} (available: {', '.join(inf['available'])})")
    for d in b.get("disks") or []:
        lines.append(f"disk      {d['path']}: {_gb(d['free_bytes'])} free of {_gb(d['total_bytes'])} ({d['for']})")
    if b.get("brain_home"):
        h = b["brain_home"]
        lines.append(f"home      {h['path']}: {h['bytes'] / 1e6:.0f} MB" + ("" if h["complete"] else " at least"))
    found = [t for t in probe.TOOLS + probe.MODULES if tools.get(t) and t != "git"]
    lines.append(f"tools     python {tools.get('python', '?')}"
                 + (f", git {tools['git_version']}" if tools.get("git_version") else "")
                 + "".join(f", {t}" for t in found))
    c = b.get("container")
    if c is not None:
        if c.get("runtime"):
            server = f", server {c['server']} up" if c.get("server") else ", server not answering"
            lines.append(f"container {c['runtime']} {c.get('client') or ''}".rstrip() + server)
        else:
            lines.append("container no runtime found")
    k = b.get("kube")
    if k is not None:
        lines.append(f"kube      {'context ' + k['context'] if k.get('context') else 'no context'}"
                     + ("" if k.get("kubectl") else " (no kubectl)"))
    enc = b.get("encryption")
    if enc is not None:
        lines.append("encrypted " + (", ".join(f"{e['volume']} {e['state']}" for e in enc) or "no volume read")
                     + (f" ({enc[0]['source']})" if enc else ""))
    srcs = prof.get("sources") or {}
    shown = [k for k in ("ecc", "battery", "encrypted", "gpu", "type", "cluster", "roles") if k in srcs]
    if shown:
        lines.append("facts     " + ", ".join(
            f"{k} {_fact(srcs[k]['value'])} ({srcs[k]['source']})" for k in shown))
    failed = [f"{n} {p['error']}" for n, p in b["probes"].items() if not p["ok"]]
    lines.append("probes    " + ", ".join(f"{n} {p['seconds']:g} s" for n, p in b["probes"].items() if p["ok"])
                 + (f"; {'; '.join(failed)}" if failed else ""))
    act = prof["active"]
    lines += ["", f"profile   {act['label']}" + (f", applied {act['applied']}" if act.get("applied") else "")]
    if act.get("estimate"):
        lines.append(f"estimate  {_cost(act['estimate'])} for what the profile turns on (declared, not measured)")
    lines.append("")
    rows = prof["capabilities"]
    w = max([len(r["id"]) for r in rows] + [5])
    lines.append(f"{'entry':<{w}}  {'class':<7}  {'profile':<16}  state")
    for r in rows:
        col = (r["profile"] + (" auto" if r["auto"] else "")) if r["profile"] else "-"
        tail = f" ({r['detail']})" if r["detail"] else ""
        kind = f" [stack of {r['project']}]" if r["kind"] == "stack" else ""
        lines.append(f"{r['id']:<{w}}  {r['class'] or '-':<7}  {col:<16}  {r['state']}{tail}{kind}")
    rec = prof["recommended"]
    adds = ", ".join(f"{k} ({why})" for k, why in rec["adds"].items())
    lines += ["", f"recommended for {b['machine']}: default" + (f" + {adds}" if adds else ", nothing more")]
    if rec["planned_fit"]:
        lines.append(f"  planned, would fit here once built: {', '.join(rec['planned_fit'])}")
    drift = prof["drift"]
    if drift["allows"]:
        lines.append(f"proposal  this machine allows {', '.join(drift['allows'])}, not in the active profile: "
                     "brain profile set recommended (the plan; --apply writes it)")
    if drift["lost"]:
        lines.append(f"note      {', '.join(drift['lost'])} on, though this machine no longer meets its rule")
    lines.append(f"inventory {prof['inventory']['note']}")
    lines += [f"warning   {m}" for m in prof["warnings"]] + [f"error     {e}" for e in prof["errors"]]
    return lines


def profiles(reg: dict[str, Entry], ch: Choice, facts: dict | None) -> dict:
    """brain profile list: each profile's entries (recommended computed for this machine when ``facts`` is given)."""
    return {"lite": sorted(preset(reg, "lite")), "default": sorted(preset(reg, "default")),
            "recommended": sorted(preset(reg, "default") | set(recommend(reg, facts))) if facts is not None else None,
            "custom": dict(sorted(ch.components.items())), "active": label(ch), "machine": ch.machine,
            "custom_only": sorted(e.id for e in reg.values() if e.profile == "custom" and e.status == "built"
                                  and not e.auto),
            "planned": sorted(e.id for e in reg.values() if e.status == "planned")}


def render_list(data: dict) -> list[str]:
    lite, default = set(data["lite"]), set(data["default"])
    lines = [f"lite         Lite: {', '.join(data['lite'])}",
             f"default      Défaut: Lite + {', '.join(e for e in data['default'] if e not in lite) or 'nothing'}"]
    if data["recommended"] is not None:
        adds = [e for e in data["recommended"] if e not in default]
        lines.append(f"recommended  Recommandé for {data['machine']}: Défaut + {', '.join(adds) or 'nothing'}")
    custom = " ".join(("+" if v else "-") + k for k, v in data["custom"].items())
    lines.append(f"custom       Personnalisable: {custom or 'no override on this machine'}")
    if data["custom_only"]:
        lines.append(f"             only by an override: {', '.join(data['custom_only'])}")
    lines += [f"planned      {', '.join(data['planned']) or 'none'}", f"active       {data['active']}"]
    return lines


def show(reg: dict[str, Entry], name: str, ch: Choice, facts: dict | None) -> list[dict]:
    """brain profile show NAME: the entries of that profile (custom: this machine's overrides), each with its keys
    and its state on this machine."""
    if name == "custom":
        ids = list(ch.components)
    elif name == "recommended":
        ids = sorted(preset(reg, "default") | set(recommend(reg, facts or {})))
    else:
        ids = sorted(preset(reg, name))
    on, _ = active(reg, ch)
    out = []
    for eid in ids:
        e = reg.get(eid)
        if not e:
            out.append({"id": eid, "state": "unknown"})
            continue
        st, detail = state(e, on, facts)
        out.append({"id": e.id, "kind": e.kind, "class": e.cls, "profile": e.profile, "title": e.title,
                    "requires": e.requires, "resources": e.resources, "fallback": e.fallback,
                    "recommend_when": e.recommend_when, "pip": e.pip, "state": st, "detail": detail,
                    "override": ch.components.get(eid) if name == "custom" else None})
    return out


def render_show(name: str, rows: list[dict]) -> list[str]:
    lines = [f"{name} ({NAMES[name]}): {len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"]
    for r in rows:
        if r.get("state") == "unknown":
            lines.append(f"- {r['id']}: unknown entry")
            continue
        head = f"- {r['id']} ({r['class'] or '-'}, {r['kind']}): {r['title'] or '-'}"
        if r.get("override") is not None:
            head += f" [{'on' if r['override'] else 'off'} by override]"
        bits = [f"state {r['state']}" + (f" ({r['detail']})" if r["detail"] else "")]
        bits += [f"requires {', '.join(r['requires'])}"] if r["requires"] else []
        bits += [f"when {', '.join(r['recommend_when'])}"] if r["recommend_when"] else []
        bits += [_cost(r["resources"])] if _cost(r["resources"] or {}) else []
        bits += [f"fallback: {r['fallback']}"] if r["fallback"] else []
        lines += [head, "    " + "; ".join(bits)]
    return lines


def render_plan(reg: dict[str, Entry], old: Choice, new: Choice, apply: bool, written: bool, path: Path) -> list[str]:
    """brain profile set's lines, in install.ps1's columns: what turns on and off, the extras install.ps1 adds, and
    whether the file is written."""
    before, _ = active(reg, old)
    after, warnings = active(reg, new)

    def what(eid: str) -> str:
        e = reg[eid]
        return f"{eid} ({e.cls}{', stack' if e.kind == 'stack' else ''})"

    lines = [f"profile  {new.machine}: {label(old)} -> {label(new)}"]
    lines += [f"on       {what(e)}: {reg[e].title}" for e in sorted(after - before)]
    lines += [f"off      {what(e)}" + (f", replaced by {reg[e].fallback}" if reg[e].fallback else "")
              for e in sorted(before - after)]
    adds = sorted({reg[e].pip for e in after - before if reg[e].pip})
    if adds:
        lines.append(f"extras   {', '.join(adds)}: install.ps1 -Apply installs them")
    drops = sorted({reg[e].pip for e in before - after if reg[e].pip})
    if drops:
        lines.append(f"extras   {', '.join(drops)} no longer wanted: left installed (pip uninstall removes them)")
    lines += [f"warning  {m}" for m in warnings]
    if old.source == "machine" and (old.base, old.components) == (new.base, new.components):
        lines.append(f"same     {path}: nothing to change")
    elif not apply:
        lines.append(f"plan     {path} is written by --apply (plan only)")
    else:
        lines.append(f"write    {path}" if written else f"same     {path}: already holds it")
    return lines
