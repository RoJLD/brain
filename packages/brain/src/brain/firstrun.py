"""brain init's three screens (wi-brain-modules-installer; spec sigma-modules §6.3, SIGMA-18): who you are, your
machine, adjust; then a plan and an apply. Offline and with no telemetry: everything is read on this machine (the
brain's catalogue, catalogue/v1, and the probe's facts), nothing is sent anywhere.

1. **Who you are**: a preset of the catalogue. The engine's catalogue offers Lite, Default and Recommended
   (``brain catalogue emit``); a private brain's catalogue (``--catalogue FILE``, a catalogue/v1 document) adds its
   personas, each built on a base preset (its base's modules, then its own).
2. **Your machine**: the probe's facts (``brain profile``'s, at zero token: no probe that starts a program) and, per
   module, whether it runs here (its ``requires`` hold, its RAM, VRAM and disk fit) and whether ``recommend_when``
   holds; a fact the probe could not read is unknown, never assumed.
3. **Adjust**: the catalogue with a box per module, its cost, its dependencies and what it pulls; a module the
   machine does not hold is refused, a module another needs cannot be removed, a planned one has no box.

The choice becomes brain commands, each shown in the plan and, with ``--apply``, run in order and logged as the
owner's step in ``<BRAIN_HOME>/ledger/setup-<month>.jsonl`` (its command, exit code, duration and the end of its
output): ``brain profile set BASE --apply`` (this machine's base), then ``brain mod disable ID --apply`` for each
module of the base left out (those that need it first), then ``brain mod enable ID --apply`` for each module added.
Nothing is written but through those commands; what must be downloaded (a distribution that is not bundled) is named,
never fetched.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import catalogue, config, paths, secretscan, tiers, timing

LOG = "setup"          # <BRAIN_HOME>/ledger/setup-<month>.jsonl
OUTPUT_MAX = 4000      # the end of a step's output kept in the log
GIB_MB = 1024


class SetupError(ValueError):
    """A choice the catalogue or the machine refuses (exit code 2)."""


# The catalogue.

def _private(extra: Path) -> dict:
    """A private catalogue/v1 file, read and validated; SetupError when it does not hold to the contract."""
    try:
        doc = catalogue.load(extra)
    except catalogue.CatalogueError as exc:
        raise SetupError(str(exc)) from exc
    errors, _ = catalogue.validate(doc, where=str(extra))
    if errors:
        raise SetupError("; ".join(errors[:3]) + (f" (+{len(errors) - 3})" if len(errors) > 3 else ""))
    return doc


def _persona(p: dict, have: set[str], bases: set[str], notes: list[str]) -> dict | None:
    """A persona kept on this brain's catalogue: its base one of the brain's, its modules the brain's (the others
    left out, said)."""
    if p.get("base") not in bases:
        notes.append(f"persona {p['id']}: base {p.get('base')!r} is not a base of this brain's catalogue: left out")
        return None
    mods = p.get("modules") or []
    gone = [m for m in mods if m not in have]
    if gone:
        notes.append(f"persona {p['id']}: {', '.join(gone)} not in this brain's catalogue: left out")
    return {**p, "modules": [m for m in mods if m in have]}


def catalogue_for(root: Path, extra: Path | None = None) -> tuple[dict, list[str]]:
    """The brain's catalogue (brain.catalogue.emit) with the personas of ``extra`` (a catalogue/v1 file), and the
    notes: a persona's module this brain does not have is left out, said. A file that does not hold to the contract
    is refused (SetupError)."""
    from . import __version__
    cat = catalogue.emit(root, f"brain {__version__}")
    if extra is None:
        return cat, []
    doc, notes = _private(extra), []
    have, bases = {m["id"] for m in cat["modules"]}, {p["id"] for p in cat["presets"]}
    personas = [_persona(p, have, bases, notes) for p in doc.get("presets") or [] if p.get("kind") == "persona"]
    return {**cat, "presets": cat["presets"] + [p for p in personas if p]}, notes


def _mods(cat: dict) -> dict[str, dict]:
    return {m["id"]: m for m in cat["modules"]}


def _preset(cat: dict, pid: str) -> dict:
    for p in cat["presets"]:
        if p["id"] == pid:
            return p
    raise SetupError(f"no preset {pid!r} (one of {', '.join(p['id'] for p in cat['presets'])})")


def switched(m: dict) -> bool:
    """A module a box turns on and off: built, not core, not auto."""
    return m.get("status", "built") == "built" and m.get("class") != "core" and not m.get("auto")


# The machine.

def facts_of(root: Path) -> dict:
    """This machine's facts, as brain profile reads them (the quick probe, then the declared and agent's layers)."""
    from . import probe
    reg, _ = tiers.registry(root)
    return tiers.machine_facts(root, probe.collect(quick=True, roots=[root]), reg, tiers.choice(root))


@dataclass
class Fit:
    runs: bool | None                              # True: it runs here; False: it does not; None: a fact is unknown
    why: list[str] = field(default_factory=list)   # what is missing, too small or unknown
    recommended: bool = False                      # every recommend_when clause holds


def _requirement(r: str, facts: dict) -> bool | None:
    if r.startswith("env:"):
        return bool(os.environ.get(r[4:]))
    v = facts.get(r)
    return None if v is None else bool(v)


def _room(m: dict, facts: dict) -> list[tuple[bool | None, str]]:
    """Each cost the machine is measured against: (fits, why)."""
    cost = m.get("cost") or {}
    out = []
    for key, fact, scale, unit in (("ram_mb", "memory_gb", GIB_MB, "MiB of RAM"),
                                   ("vram_gb", "gpu_vram_gb", 1, "GiB of VRAM"),
                                   ("disk_mb", "disk_free_gb", GIB_MB, "MiB of free disk")):
        need = cost.get(key) or 0
        if not need:
            continue
        have = facts.get(fact)
        if not isinstance(have, (int, float)) or isinstance(have, bool):
            out.append((None, f"{fact} unknown (needs {need} {unit})"))
        elif have * scale < need:
            out.append((False, f"needs {need} {unit}, has {round(have * scale, 1)}"))
    return out


def fit(m: dict, facts: dict) -> Fit:
    """Whether the module runs on a machine of these facts, and whether its recommend_when holds there."""
    checks = [(_requirement(r, facts), f"requires {r}" + ("" if _requirement(r, facts) is not None else " (unknown)"))
              for r in m.get("requires") or []] + _room(m, facts)
    states = [s for s, _ in checks]
    runs = False if False in states else None if None in states else True
    why = [w for s, w in checks if s is not True]
    return Fit(runs, why, all(tiers.holds(c, facts) for c in m.get("recommend_when") or []))


def machine(cat: dict, facts: dict) -> dict:
    """Screen 2: the machine's summary and each module's fit."""
    keys = ("os", "arch", "cpu_cores", "memory_gb", "gpu", "gpu_vram_gb", "disk_free_gb")
    return {"facts": {k: facts.get(k) for k in keys},
            "modules": [{"id": m["id"], "name": m["name"], "fit": fit(m, facts)} for m in cat["modules"]
                        if m.get("status", "built") == "built"]}


# Who you are and adjust.

def base_set(cat: dict, preset: dict, facts: dict) -> list[str]:
    """What a preset turns on here: its base's modules (a persona's), its own, and its when_fits that run here and
    whose recommend_when holds."""
    mods = _mods(cat)
    out: list[str] = []
    if preset.get("kind") == "persona" and preset.get("base"):
        out += base_set(cat, _preset(cat, preset["base"]), facts)
    out += preset.get("modules") or []
    for mid in preset.get("when_fits") or []:   # left out, as tiers.recommend does, when a dependency does not run
        if fit(mods[mid], facts).recommended and all(fit(mods[d], facts).runs is True for d in _closure([mid], mods)):
            out.append(mid)
    return list(dict.fromkeys(out))


def _closure(mids: list[str], mods: dict) -> list[str]:
    seen, todo = [], list(mids)
    while todo:
        mid = todo.pop(0)
        if mid in mods and mid not in seen:
            seen.append(mid)
            todo += mods[mid].get("depends_on") or []
    return seen


@dataclass
class Choice:
    preset: str
    base: str                          # the engine's base preset it starts from (brain profile set BASE)
    on: list[str]                      # the modules on, the hard dependencies pulled
    pulled: dict[str, str]             # {module: the module that pulls it}
    added: list[str]                   # switched modules on beyond the base
    removed: list[str]                 # switched modules of the base left out, those that need others first
    notes: list[str] = field(default_factory=list)
    fetch: list[str] = field(default_factory=list)   # the distributions to download (named, never fetched here)


def _check_with(mods: dict, mid: str, facts: dict, notes: list[str]) -> None:
    if mid not in mods:
        raise SetupError(f"--with {mid}: no module {mid!r} in the catalogue")
    m = mods[mid]
    if m.get("status") == "planned":
        raise SetupError(f"--with {mid}: planned, not built yet")
    if m.get("auto"):
        raise SetupError(f"--with {mid}: used whenever it is found (auto): no box turns it on")
    f = fit(m, facts)
    if f.runs is False:
        raise SetupError(f"--with {mid}: this machine does not hold it ({'; '.join(f.why)})")
    if f.runs is None:
        notes.append(f"{mid}: {'; '.join(f.why)}: chosen, not checked")


def _check_without(mods: dict, mid: str) -> None:
    if mid not in mods:
        raise SetupError(f"--without {mid}: no module {mid!r} in the catalogue")
    if mods[mid].get("class") == "core" or mods[mid].get("auto"):
        raise SetupError(f"--without {mid}: {'core' if mods[mid].get('class') == 'core' else 'auto'}, never off")


def _engine_base(cat: dict, preset: dict) -> str:
    return preset["base"] if preset.get("kind") == "persona" and preset.get("base") else preset["id"]


def _order_removed(removed: list[str], mods: dict) -> list[str]:
    """Those that need another removed one first (brain mod disable refuses a module a module that is on needs)."""
    out, left = [], list(removed)
    while left:
        ready = [m for m in left if not any(m in _closure([x], mods)[1:] for x in left if x != m)]
        nxt = ready[0] if ready else left[0]
        out.append(nxt)
        left.remove(nxt)
    return out


def _pulled(on: list[str], wanted: list[str], mods: dict) -> dict[str, str]:
    """{module: the module that pulls it} for the hard dependencies on that were not asked for."""
    pulled: dict[str, str] = {}
    for mid in on:
        for d in _closure([mid], mods)[1:]:
            if d not in wanted:
                pulled.setdefault(d, mid)
    return pulled


def _check_on(on: list[str], pulled: dict, without: list[str], mods: dict, facts: dict) -> None:
    """A box unticked that a module on needs, a dependency pulled that the machine does not hold: refused."""
    for mid in without:
        if mid in on:
            raise SetupError(f"--without {mid}: needed by {pulled.get(mid) or 'a module on'}")
    for d, by in pulled.items():
        f = fit(mods[d], facts)
        if f.runs is False:
            raise SetupError(f"{by} needs {d}, which this machine does not hold ({'; '.join(f.why)})")


def _check_persona(cat: dict, preset: dict, facts: dict, notes: list[str]) -> None:
    """A persona's own modules are measured against the machine like a box ticked: refused when it does not hold
    one, noted when a fact is unknown."""
    if preset.get("kind") != "persona":
        return
    mods = _mods(cat)
    for mid in preset.get("modules") or []:
        f = fit(mods[mid], facts)
        if f.runs is False:
            raise SetupError(f"persona {preset['id']}: {mid}: this machine does not hold it ({'; '.join(f.why)})")
        if f.runs is None:
            notes.append(f"{mid}: {'; '.join(f.why)}: chosen, not checked")


def choose(cat: dict, preset_id: str, facts: dict, with_: list[str] = (), without: list[str] = ()) -> Choice:
    """Screen 3: the preset's modules here, then the boxes ticked (--with) and unticked (--without), the hard
    dependencies pulled; SetupError for a module the catalogue or the machine refuses, or one a module on needs."""
    mods, notes = _mods(cat), []
    preset = _preset(cat, preset_id)
    _check_persona(cat, preset, facts, notes)
    for mid in with_:
        _check_with(mods, mid, facts, notes)
    for mid in without:
        _check_without(mods, mid)
    wanted = [m for m in base_set(cat, preset, facts) + list(with_) if m not in without]
    on = _closure(wanted, mods)
    pulled = _pulled(on, wanted, mods)
    _check_on(on, pulled, list(without), mods, facts)
    base = _preset(cat, _engine_base(cat, preset))
    start = base_set(cat, base, facts) + (base.get("when_fits") or [])
    added = [m for m in on if switched(mods[m]) and m not in base.get("modules", [])]
    removed = _order_removed([m for m in dict.fromkeys(start) if switched(mods[m]) and m not in on], mods)
    return Choice(preset_id, base["id"], on, pulled, added, removed, notes, cost(cat, on)["fetch"])


def _far(m: dict, dists: dict) -> list[dict]:
    """A module's distributions that are not bundled: adding it downloads them."""
    return [dists[d] for d in m.get("distributions") or [] if d in dists and not dists[d].get("bundled")]


def cost(cat: dict, mids: list[str]) -> dict:
    """The modules' costs summed, and what adding them downloads (MiB): a module's download_mb, else the size of
    its distributions that are not bundled."""
    mods, dists = _mods(cat), {d["id"]: d for d in cat.get("distributions") or []}
    out = {k: 0.0 for k in ("ram_mb", "disk_mb", "vram_gb", "download_mb")}
    fetch: list[str] = []
    for mid in mids:
        c, far = mods[mid].get("cost") or {}, _far(mods[mid], dists)
        for k in ("ram_mb", "disk_mb", "vram_gb"):
            out[k] += c.get(k) or 0
        fetch += [d["id"] for d in far]
        out["download_mb"] += c.get("download_mb") or sum((d.get("source") or {}).get("size_mb") or 0 for d in far)
    return {**{k: round(v, 1) for k, v in out.items()}, "fetch": list(dict.fromkeys(fetch))}


# The plan and the apply.

def steps(root: Path, ch: Choice) -> list[list[str]]:
    """The brain commands the choice is made of: the base, then the modules left out, then those added."""
    at = ["brain", "--root", str(root)]
    return ([[*at, "profile", "set", ch.base, "--apply"]]
            + [[*at, "mod", "disable", m, "--apply"] for m in ch.removed]
            + [[*at, "mod", "enable", m, "--apply"] for m in ch.added])


def shown(words: list[str]) -> str:
    """A command as the owner types it: a word with a space (or empty) in double quotes."""
    return " ".join(f'"{w}"' if " " in w or not w else w for w in words)


def log(row: dict) -> Path:
    d = paths.ledger_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{LOG}-{row['at'][:7]}.jsonl"
    timing.append(f, row)
    return f


def _call(runner, argv: list[str], buf: io.StringIO) -> int:
    """The step's exit code; a usage error (argparse's exit) its code, any other exception 1, its traceback in the
    output: a step that fails is logged, never a crash after the files are written."""
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return runner(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    except Exception:   # noqa: BLE001 - logged with its traceback as the step's failure (exit 1)
        buf.write(traceback.format_exc())
        return 1


def run(words: list[str], cwd: Path, runner=None, by: str = "") -> dict:
    """One step, run in this process as ``brain`` would run it (offline: the same engine), its output captured and
    printed, logged as the owner's step (``by``: the brain's owner); {command, exit, seconds, output}."""
    from . import cli
    runner = runner or (lambda argv: cli.main(argv))
    start, t0 = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), time.monotonic()
    buf = io.StringIO()
    code = _call(runner, words[1:], buf)
    text, _ = secretscan.clean_text(buf.getvalue().strip())
    res = {"command": shown(words), "exit": code, "seconds": round(time.monotonic() - t0, 2), "output": text}
    log({"at": start, "event": "setup-step", "via": "init", "by": by or config.owner_of(cwd), "command": res["command"],
         "cwd": str(cwd), "exit": code, "seconds": res["seconds"], "output": text[-OUTPUT_MAX:]})
    return res


def already(root: Path, cat: dict, ch: Choice) -> bool:
    """This machine is already as the choice says: its base, and each switched module on or off as chosen (a second
    apply then runs nothing, and profile.json is not written again)."""
    from . import mod
    cur = tiers.choice(root)
    if cur.source != "machine" or cur.base != ch.base:
        return False
    reg, _ = tiers.registry(root)
    on, _ = tiers.active(reg, cur)
    have = mod.catalogue(root, reg)
    return all((mod.state(have[m["id"]], on, reg) == "on") == (m["id"] in ch.on)
               for m in cat["modules"] if switched(m) and m["id"] in have)


def apply(root: Path, plan: list[list[str]], runner=None, by: str = "") -> list[dict]:
    """Each step in order, the next only when the last exited 0."""
    out = []
    for words in plan:
        out.append(run(words, root, runner, by))
        if out[-1]["exit"] != 0:
            break
    return out


# The screens as text.

def _gb(mb: float) -> str:
    return f"{mb / GIB_MB:.1f} GiB" if mb >= GIB_MB else f"{mb:g} MiB"


def _cost_text(c: dict) -> str:
    parts = [f"RAM {_gb(c['ram_mb'])}" if c.get("ram_mb") else "", f"disk {_gb(c['disk_mb'])}" if c.get("disk_mb")
             else "", f"VRAM {c['vram_gb']:g} GiB" if c.get("vram_gb") else "",
             f"download {_gb(c['download_mb'])}" if c.get("download_mb") else ""]
    return ", ".join(p for p in parts if p) or "nothing worth counting"


def render_presets(cat: dict, facts: dict) -> list[str]:
    out = ["1. Who you are: a preset"]
    for i, p in enumerate(cat["presets"], 1):
        on = base_set(cat, p, facts)
        kind = f"persona on {p.get('base')}" if p.get("kind") == "persona" else "base"
        desc = f": {p['description']}" if p.get("description") else ""
        out.append(f"  {i}. {p['id']} ({p['name']}, {kind}){desc}: {len(on)} module(s), {_cost_text(cost(cat, on))}")
    return out


def render_machine(cat: dict, facts: dict) -> list[str]:
    data, rows = machine(cat, facts), _mods(cat)
    f = data["facts"]
    out = ["2. Your machine (probed here, nothing sent)",
           "  " + ", ".join(f"{k} {'unknown' if v is None else v}" for k, v in f.items())]
    for r in data["modules"]:
        fi = r["fit"]
        state = {True: "runs here", False: "does not run here", None: "unknown here"}[fi.runs]
        rec = ", recommended" if fi.recommended and fi.runs and rows[r["id"]].get("recommend_when") else ""
        out.append(f"  {r['id']:<16} {state}{rec}" + (f" ({'; '.join(fi.why)})" if fi.why else ""))
    return out


def _box(m: dict, ch: Choice) -> str:
    if m.get("auto"):
        return "(auto)"
    return "[*]" if m.get("class") == "core" else "[x]" if m["id"] in ch.on else "[ ]"


def _said_of(m: dict, ch: Choice, c: dict, f: Fit) -> list[str]:
    """What a box's line says beside its cost: who pulls it, what it needs, what it downloads, why it does not fit."""
    extra = ([f"pulled by {ch.pulled[m['id']]}"] if m["id"] in ch.pulled else []) + (
        [f"needs {', '.join(m['depends_on'])}"] if m.get("depends_on") else []) + (
        [f"download: {', '.join(c['fetch'])}"] if c["fetch"] else [])
    if f.runs is not True and f.why:
        word = ("not found here, its fallback serves" if m.get("auto")
                else "does not fit" if f.runs is False else "unknown")
        extra.append(f"{word}: {'; '.join(f.why)}")
    return extra


def render_adjust(cat: dict, ch: Choice, facts: dict) -> list[str]:
    out = [f"3. Adjust (preset {ch.preset}): [x] on, [ ] off, [*] core, (auto) used whenever found"]
    for m in cat["modules"]:
        if m.get("status") == "planned":
            out.append(f"      {m['id']:<16} planned, not built yet")
            continue
        c = cost(cat, [m["id"]])
        extra = _said_of(m, ch, c, fit(m, facts))
        out.append(f"  {_box(m, ch):<6} {m['id']:<16} {_cost_text(c)}" + (f" ({'; '.join(extra)})" if extra else ""))
    mods = _mods(cat)
    total = cost(cat, [m for m in ch.on if not mods[m].get("auto")])
    fetch = f"; to download (not here: offline): {', '.join(total['fetch'])}" if total["fetch"] else ""
    return out + [f"  total: {_cost_text(total)}{fetch}"] + [f"  note: {n}" for n in ch.notes]


def render_plan(plan: list[list[str]]) -> list[str]:
    return ["the plan, each step a brain command logged in <BRAIN_HOME>/ledger/setup-<month>.jsonl:"] + [
        f"  {shown(w)}" for w in plan]


# --interactive: the same screens, asked.

ASK = input   # the prompt (a test replaces it)


def tty() -> bool:
    return sys.stdin.isatty()


def _pick(cat: dict, answer: str, default: str) -> str:
    """A preset by its number or its id; the default for an empty answer."""
    a = answer.strip()
    if not a:
        return default
    ids = [p["id"] for p in cat["presets"]]
    if a.isdigit() and 1 <= int(a) <= len(ids):
        return ids[int(a) - 1]
    if a in ids:
        return a
    raise SetupError(f"no preset {a!r}: a number from 1 to {len(ids)}, or an id")


def _toggle(words: list[str], with_: list[str], without: list[str]) -> tuple[list[str], list[str]]:
    """+ID ticks a box, -ID unticks it (a bare ID ticks it)."""
    w, wo = list(with_), list(without)
    for t in words:
        on, mid = t[:1] != "-", t[1:] if t[:1] in ("+", "-") else t
        if not mid:
            continue
        w, wo = [x for x in w if x != mid], [x for x in wo if x != mid]
        (w if on else wo).append(mid)
    return w, wo


def interactive(cat: dict, facts: dict, preset: str, with_: list[str], without: list[str],
                out=print) -> tuple[str, list[str], list[str]]:
    """The three screens, one after the other: a preset (its number or its id), the machine (read only), then the
    boxes (+ID, -ID) until an empty answer; a choice the catalogue or the machine refuses is said and undone."""
    while True:
        for line in render_presets(cat, facts):
            out(line)
        try:
            preset = _pick(cat, ASK(f"preset (a number or an id; Enter: {preset}): "), preset)
            break
        except SetupError as exc:
            out(f"refused: {exc}")
    for line in render_machine(cat, facts):
        out(line)
    ASK("Enter to adjust: ")
    ch = choose(cat, preset, facts, with_, without)
    while True:
        for line in render_adjust(cat, ch, facts):
            out(line)
        answer = ASK("+ID ticks, -ID unticks (several at once); Enter when done: ").split()
        if not answer:
            return preset, with_, without
        w, wo = _toggle(answer, with_, without)
        try:
            ch = choose(cat, preset, facts, w, wo)
            with_, without = w, wo
        except SetupError as exc:
            out(f"refused: {exc}")


def log_init(root: Path, words: list[str], code: int, by: str = "") -> Path:
    """brain init's own step, logged like the others (its files were written by its plan, shown before)."""
    return log({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "event": "setup-step",
                "via": "init", "by": by or config.owner_of(root), "command": shown(words), "cwd": str(root),
                "exit": code, "seconds": 0.0, "output": ""})
