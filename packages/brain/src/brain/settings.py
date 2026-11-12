"""The settings, as data: the cockpit's Settings tab (the comma) and ``brain tui --once --tab settings``
(wi-brain-tui-settings; spec cockpit-ux §4.13, cockpit-ux-round2 §4.0.3 and §4.2).

Each setting is a :class:`Setting`: its page, its key, its value, where it comes from (a file and its key, or an
environment variable) and how it changes. The pages, on the left of the tab: Cockpit, Identity, Brain, Permissions,
Setup.

- **Cockpit**: the screen's own settings, per user in ``<BRAIN_HOME>/tui.json`` (``settings``): the theme, the
  timezone, the language, each panel's free title, how often the files are checked (``refresh``) and the probes run
  (``probe``; ``--refresh`` and ``--probe`` win for one launch). They are edited in the screen itself (:func:`parse`
  checks a value, :func:`edited` returns the settings with it); the project shown at the start is the one the
  selector last showed (``p``).
- **Identity**, **Brain**, **Permissions**: the brain's settings, each shown with its place and the command that
  changes it, and changed only through it: nothing here writes them. A secret is named, never shown.
- **Setup**: the setup wizards (brain.wizards, wi-brain-tui-setup), one per row: each chains the brain's own
  commands, a plan before an apply, run in the cockpit after the owner's confirmation and logged.

Read-only and at zero token: a page whose read fails gives one row that says why, never an exception.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import cockpit, config, paths, projects

PAGES = ("cockpit", "identity", "brain", "modules", "permissions", "setup")
PAGE_LABELS = {"cockpit": {"en": "Cockpit", "fr": "Cockpit"}, "identity": {"en": "Identity", "fr": "Identité"},
               "brain": {"en": "Brain", "fr": "Brain"}, "modules": {"en": "Modules", "fr": "Modules"},
               "permissions": {"en": "Permissions", "fr": "Permissions"},
               "setup": {"en": "Setup", "fr": "Mise en place"}}
HERE = "here: Enter"  # how a cockpit setting changes: in the screen itself
REFRESH_MIN = cockpit.INTERVAL_MIN
DEFAULT_THEME = "textual-dark"   # Textual's own
LANG_ENV = "BRAIN_LANG"
NO_COMMAND = ("no brain config set: brain init (the setup wizard), or a commit in the personal brain's repo "
              "(config.json)")


@dataclass
class Setting:
    page: str
    key: str                    # its key: tui.json settings' dotted key on the Cockpit page, else a name
    value: str                  # as shown; a secret's value never
    source: str                 # the file and its key, or the environment variable
    change: str                 # HERE, or the command that changes it
    edit: str = ""              # cockpit settings: choice, text or duration; the Setup page: wizard; '' read-only
    choices: tuple = field(default_factory=tuple)
    default: str = ""           # what applies when it is not set


def page_label(page: str) -> str:
    return PAGE_LABELS[page][cockpit.lang()]


def _seconds(s) -> str:
    return f"{s * 1000:.0f} ms" if s < 1 else f"{s:g} s" if s < 60 else f"{s / 60:g} min"


# --- the cockpit's own settings: tui.json ---

def cockpit_settings(state: dict | None = None, themes: tuple = (), running: dict | None = None) -> list[Setting]:
    """tui.json's settings as the cockpit reads them (``state``: :func:`brain.cockpit.load_state`'s answer, read when
    None); ``themes``: the theme names the app offers (the text view does not know them); ``running``: the intervals
    this launch runs, said beside the saved ones when they differ (--refresh, --probe, + and -)."""
    state = cockpit.load_state() if state is None else state
    got = state.get("settings") or {}
    where = f"{cockpit.state_path()} settings"
    env_lang = os.environ.get(LANG_ENV)
    out = [
        Setting("cockpit", "theme", got.get("theme") or DEFAULT_THEME, f"{where}.theme",
                f"{HERE}, or ctrl+p's theme picker", "choice", tuple(themes), DEFAULT_THEME),
        Setting("cockpit", "tz", got.get("tz") or "local", f"{where}.tz",
                f"{HERE}, or t; brain tui --tz for one launch", "choice", cockpit.TZS, "local"),
        Setting("cockpit", "lang", cockpit.lang(),
                f"${LANG_ENV} (it wins over {where}.lang)" if env_lang else f"{where}.lang",
                HERE + (f"; unset ${LANG_ENV} first" if env_lang else ""), "choice", cockpit.LANGS, "en"),
        Setting("cockpit", "refresh", _seconds(_number(got.get("refresh"), cockpit.REFRESH_S)), f"{where}.refresh",
                f"{HERE}; brain tui --refresh for one launch, + and - until it closes", "duration",
                default=_seconds(cockpit.REFRESH_S)),
        Setting("cockpit", "probe", _seconds(_number(got.get("probe"), cockpit.PROBE_S)), f"{where}.probe",
                f"{HERE}; brain tui --probe for one launch", "duration", default=_seconds(cockpit.PROBE_S)),
        Setting("cockpit", "scope", state.get("scope") or "(the folder's project)", f"{cockpit.state_path()} scope",
                "p, the project selector: the next start shows the last one"),
    ]
    _running(out, running or {})
    return out + _titles(got.get("titles") or {}, where)


def _running(rows: list[Setting], running: dict) -> None:
    """The interval this launch runs, said before how a row changes when it is not the saved one."""
    for s in rows:
        now = running.get(s.key)
        if now is not None and _seconds(now) != s.value:
            s.change = f"this launch runs {_seconds(now)}; " + s.change


def _titles(titles: dict, where: str) -> list[Setting]:
    """Each panel's free title, else its own (the queue's: the owner's name, in the language)."""
    out = []
    for name in (*cockpit.PANELS, *cockpit.FRAMES):
        default = cockpit.queue_title() if name == "queue" else cockpit.TITLES[name]
        out.append(Setting("cockpit", f"titles.{name}", titles.get(name) or default, f"{where}.titles.{name}", HERE,
                           "text", default=default))
    return out


def _number(v, default: float) -> float:
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and REFRESH_MIN <= v <= cockpit.INTERVAL_MAX
    return float(v) if ok else default


def parse(key: str, text: str, choices: tuple = ()) -> object:
    """A cockpit setting's new value from what the owner typed or picked: '' (or None) sets it back to its default
    (None returned: the key removed); ValueError says why a value is refused."""
    text = (text or "").strip()
    if not text:
        return None
    if key in ("refresh", "probe"):
        seconds = cockpit.duration(text)
        if seconds < REFRESH_MIN or seconds > cockpit.INTERVAL_MAX:
            raise ValueError(f"{text!r}: between {_seconds(REFRESH_MIN)} and {_seconds(cockpit.INTERVAL_MAX)}")
        return seconds
    allowed = {"tz": cockpit.TZS, "lang": cockpit.LANGS}.get(key, choices if key == "theme" else ())
    if allowed and text not in allowed:
        raise ValueError(f"{text!r}: one of {', '.join(allowed)}")
    if key in ("theme", "tz", "lang") or key.startswith("titles."):
        if key.startswith("titles.") and key.split(".", 1)[1] not in (*cockpit.PANELS, *cockpit.FRAMES):
            raise ValueError(f"{key}: no such panel")
        return text
    raise ValueError(f"{key}: not a setting of the cockpit")


def edited(settings: dict, key: str, value) -> dict:
    """``settings`` (tui.json's) with ``key`` set to ``value`` (:func:`parse`'s), or removed when it is None."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in settings.items()}
    if key.startswith("titles."):
        titles = out.get("titles") or {}
        name = key.split(".", 1)[1]
        if value is None:
            titles.pop(name, None)
        else:
            titles[name] = value
        if titles:
            out["titles"] = titles
        else:
            out.pop("titles", None)
    elif value is None:
        out.pop(key, None)
    else:
        out[key] = value
    return out


# --- the brain's settings: shown with their place, changed by their own command ---

def identity_settings(root: Path | None = None) -> list[Setting]:
    cfg = config.load(root)
    where = str(cfg.file) if cfg.file else f"no {config.FILE} (the defaults)"
    ident = cfg.data.get("identity") if isinstance(cfg.data.get("identity"), dict) else {}
    broken = [Setting("identity", "config.json", f"not readable: {cfg.error}; the defaults apply", where,
                      "fix the file by hand; brain config --check says what is wrong")] if cfg.error else []
    return broken + [
        Setting("identity", "identity.owner", config.owner(cfg), f"{where} identity.owner"
                + ("" if ident.get("owner") else " (unset: its first store's owner)"),
                f"{NO_COMMAND}; it is the id every answer records (--by): a record never changes for display"),
        Setting("identity", "identity.display_name", config.display_name(cfg), f"{where} identity.display_name"
                + ("" if ident.get("display_name") else " (unset: the owner)"),
                f"{NO_COMMAND}; the queue's title and the help texts show it"),
        Setting("identity", "identity.kind", str(ident.get("kind") or "person"), f"{where} identity.kind", NO_COMMAND),
        Setting("identity", "identity.tenant", str(ident.get("tenant") or "-"), f"{where} identity.tenant", NO_COMMAND),
    ]


def brain_settings(root: Path | None = None) -> list[Setting]:
    cfg = config.load(root)
    cfile = str(cfg.file) if cfg.file else f"no {config.FILE}"
    reg = projects.registry_file(root)
    engine = cfg.data.get("engine") if isinstance(cfg.data.get("engine"), dict) else {}
    out = [
        Setting("brain", "BRAIN_HOME", str(paths.brain_home()),
                "$BRAIN_HOME" if os.environ.get("BRAIN_HOME") else "the default (~/.brain; $BRAIN_HOME names another)",
                "an environment variable of the owner's (the installer sets it)"),
        Setting("brain", "personal", str(paths.personal_root() or "-"), str(paths.personal_file()),
                "install.ps1 -Personal (the installer writes the pointer)"),
        Setting("brain", "config.json", cfile, "$BRAIN_CONFIG, else config.json beside the registry",
                "brain config (its keys: brain config --keys; checked by brain config --check)"),
        Setting("brain", "registry", str(reg or "-"), "$BRAIN_PROJECTS, else " + str(cfg.get("registry")),
                "a branch and a PR in the personal brain's repo (projects.yaml); brain projects lists it"),
        Setting("brain", "engine.pin", str(engine.get("pin") or "-"), f"{cfile} engine.pin",
                "brain update (it writes the pin), or a PR that moves it when the brain declares its installer"),
        Setting("brain", "engine.installer", str(engine.get("installer") or "-"), f"{cfile} engine.installer",
                NO_COMMAND),
    ]
    out += _profile(root)
    out += _registry_settings(root)
    types = cfg.data.get("scope_types")
    out.append(Setting("brain", "scope_types", f"{len(types)} renamed or added" if isinstance(types, dict) and types
                       else "the built-in catalogue", f"{cfile} scope_types",
                       f"brain scopes --types shows them; {NO_COMMAND}"))
    from . import permissions
    out.append(Setting("brain", "claude settings", str(permissions.claude_home() / "settings.json"),
                       "$CLAUDE_CONFIG_DIR, else ~/.claude",
                       "a plan only: brain permissions render --level user shows it; install.ps1 -Apply, the owner's, "
                       "writes it"))
    return out


def _profile(root: Path | None) -> list[Setting]:
    from . import tiers
    ch = tiers.choice(root)
    where = {"machine": str(tiers.machine_file()), "config": f"{config.FILE} tier", "built-in": "built-in"}[ch.source]
    return [Setting("brain", "profile", tiers.label(ch), where,
                    "brain profile set lite|default|recommended (a plan, then --apply); brain mod enable|disable "
                    "MODULE for one module")]


def _registry_settings(root: Path | None) -> list[Setting]:
    """What projects.yaml declares per project: the stacks, the notification routes, the code index."""
    try:
        reg = projects.load(root)
    except Exception as exc:  # shown, never raised: the other settings still read
        return [Setting("brain", "projects.yaml", f"not readable: {type(exc).__name__}: {exc}", "projects.yaml",
                        "brain check")]
    where = str(projects.registry_file(root) or "projects.yaml")

    def having(attr: str) -> list[str]:
        return sorted(p.name for p in reg.values() if getattr(p, attr))

    stacks, notify, index = having("stacks"), having("notify"), having("code_index")
    return [
        Setting("brain", "stacks", ", ".join(stacks) or "-", f"{where} <project>.stacks",
                "brain health shows them; a PR on projects.yaml declares them, brain profile turns them on"),
        Setting("brain", "notify routes", ", ".join(notify) or "-", f"{where} <project>.notify",
                "brain notify status (channels by their variables' names, never their values); brain notify setup "
                "CHANNEL"),
        Setting("brain", "code index", ", ".join(index) or "-", f"{where} <project>.code_index; "
                f"{paths.brain_home() / 'code-index.json'}", "brain index (each repo's state; --stale)"),
    ]


def permission_settings(root: Path | None = None) -> list[Setting]:
    from . import permissions
    f = permissions.permissions_file(root)
    return [
        Setting("permissions", "permissions.yaml", str(f or "-"),
                f"${permissions.ENV}, else permissions.yaml beside the registry",
                "brain permissions (the effective rules and where each comes from); brain permissions grant: a rule "
                "appended in a branch, reviewed by PR"),
        Setting("permissions", "engine rules", permissions.ENGINE_FILE, "the engine's own allow-rules.txt",
                "brain update (it ships with the engine)"),
        Setting("permissions", "claude settings", str(permissions.claude_home() / "settings.json"),
                "the user level: engine, global, profile, machine",
                "a plan only: brain permissions render --level user; install.ps1 -Apply, the owner's, writes it"),
    ]


def setup_settings(root: Path | None = None) -> list[Setting]:
    """The setup wizards (brain.wizards), one per row: Enter in the cockpit runs one, its commands logged."""
    from . import wizards
    return [Setting("setup", w.id, f"{w.title}: {w.what}", "brain.wizards: run here after a confirmation",
                    w.command() + (f"; yours: {w.owner}" if w.owner else ""), "wizard") for w in wizards.wizards(root)]


COST_WORDS = {"ram_mb": ("RAM", "MB"), "disk_mb": ("disk", "MB"), "vram_gb": ("VRAM", "GB"),
              "download_mb": ("download", "MB")}


def _cost_text(cost: dict) -> str:
    return ", ".join(f"{COST_WORDS[k][0]} {v:g} {COST_WORDS[k][1]}" for k, v in cost.items() if k in COST_WORDS)


FIXED = {"core": "always on (a core capability): brain mod show {id}",
         "auto": "used whenever it is found, never switched: brain mod show {id}",
         "planned": "planned, not built yet: brain mod show {id}"}


def _module_row(m: dict, r: dict, fixed: str) -> Setting:
    """One module of the catalogue (``m``) with its state on this machine (``r``, brain mod list's row); ``fixed``: why
    it cannot be switched (core, auto, planned), '' when it can."""
    what = [x for x in (_cost_text(m.get("cost") or {}),
                        f"needs {', '.join(m['depends_on'])}" if m.get("depends_on") else "",
                        f"requires {', '.join(m['requires'])}" if m.get("requires") else "",
                        f"else: {m['fallback']}" if m.get("fallback") else "") if x]
    state = "planned" if fixed == "planned" else r.get("state", "?")
    return Setting("modules", m["id"], f"{state} ({r.get('source', '-')})",
                   "; ".join(what) or str(m.get("description") or m.get("name") or ""),
                   FIXED[fixed].format(id=m["id"]) if fixed
                   else f"brain mod enable|disable {m['id']} (a plan, then --apply)", "" if fixed else "module")


def _fixed(m, reg: dict) -> str:
    """Why brain mod would refuse to switch a module (brain.mod's own checks): a core capability, nothing it can
    switch (auto), a capability not built yet; '' when it can be switched."""
    from . import mod
    caps = [reg[c] for c in m.capabilities if c in reg]
    if any(c.cls == "core" for c in caps):
        return "core"
    if any(c.status != "built" for c in caps):
        return "planned"
    return "" if mod.switched(m, reg) else "auto"


def module_settings(root: Path | None = None) -> list[Setting]:
    """The Modules page (wi-brain-modules-tab, SIGMA-15): each module of the brain's catalogue (catalogue/v1, brain
    catalogue emit) with its state on this machine and where it comes from (brain mod list), its cost, what it needs and
    its fallback; then the distributions, read-only. Enter on a module: turn it on or off (brain.wizards'
    module wizard: brain mod enable|disable, a plan then --apply)."""
    from . import catalogue, mod, tiers
    doc = catalogue.emit(root, by="brain tui")
    states = {r["id"]: r for r in mod.rows(root)}
    reg, _ = tiers.registry(root)
    cat = mod.catalogue(root, reg)
    out = [] if any(m.from_registry for m in cat.values()) else [
        Setting("modules", "registry", "none: each capability is its own module", "modules.yaml (brain modules)",
                "a modules registry groups the capabilities into modules (brain modules --check)")]
    out += [_module_row(m, states.get(m["id"], {}), _fixed(cat[m["id"]], reg) if m["id"] in cat else "core")
            for m in doc["modules"]]
    for x in doc["distributions"]:
        out.append(Setting("modules", f"distribution {x['id']}", f"{x.get('name', '')} ({x.get('kind', '')}"
                           + (", bundled)" if x.get("bundled") else ", downloaded when a module needs it)"),
                           "brain catalogue emit", "the engine's install: brain update; an extra by brain profile "
                           "set and the installer (adding or removing a distribution from here arrives later)"))
    return out


READERS = {"cockpit": None, "identity": identity_settings, "brain": brain_settings, "modules": module_settings,
           "permissions": permission_settings, "setup": setup_settings}


def collect(root: Path | None = None, state: dict | None = None, themes: tuple = (),
            pages: tuple = PAGES, running: dict | None = None) -> dict[str, list[Setting]]:
    """Each page's settings; a page whose read fails gives one row that says why."""
    out: dict[str, list[Setting]] = {}
    for page in pages:
        try:
            out[page] = cockpit_settings(state, themes, running) if page == "cockpit" else READERS[page](root)
        except Exception as exc:  # one page never stops the others
            out[page] = [Setting(page, "read failed", f"{type(exc).__name__}: {exc}", "", "brain check --all")]
    return out


def lines(pages: dict[str, list[Setting]], width: int = cockpit.WIDTH) -> list[str]:
    """The text view: each page, then each setting, its value, where it comes from and how it changes."""
    out = []
    for page, rows in pages.items():
        out += ["", f"{page_label(page)} ({len(rows)})"]
        for s in rows:
            out.append(cockpit._line("  ", f"{s.key}: {s.value}", width))
            if s.source:
                out.append(cockpit._line("      ", f"from {s.source}", width))
            out.append(cockpit._line("      ", f"change: {s.change}", width))
    return out
