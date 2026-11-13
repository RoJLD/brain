"""The setup wizards, as data: the Setup page of the cockpit's Settings tab (wi-brain-tui-setup; spec cockpit-ux §4.13,
cockpit-ux-round2 §4.0.3, UX-8).

Each :class:`Wizard` chains the brain's own commands, never a hidden edit: a choice when it has one (a profile, a stack,
a template), then its plan (a command that writes nothing, its output shown before anything runs), then its apply (the
same command with ``--apply``, or the step that writes), run only after the owner's confirmation of its exact words,
as the owner's, logged in ``<BRAIN_HOME>/ledger/cockpit-<month>.jsonl`` and refused in a Claude Code session's shell
(brain.detail's runner). A wizard that only reads runs its one command the same way.

What stays the owner's (spec §4.13, « La sûreté »): a change of Claude Code's settings or of install.ps1 stays a plan,
its exact command shown and run by the owner in their own terminal; adding a project to projects.yaml is a branch and a
PR in the personal brain; a permission is granted by PR. A secret is never typed here: the owner sets it as an
environment variable (or in the system keyring) and the wizards show its name, never its value (ddr-2026-11-02-cockpit-
secrets-entry).

**Local services** (wi-brain-wizard-local-services): the steps that wire the Brain's local services for any owner,
in their order (:data:`LOCAL`): the machine's token (``brain ipc token --init``, the owner's gesture); the collector's
token declared (``config.json ipc.require_token``, by a PR in the personal brain: it takes effect at the bundle's
apply, and it is what makes the next step's settings carry the header); Claude Code's OTLP export settings and their
``otelHeadersHelper`` (``brain ipc claude-settings``: the exact lines and the helper's export checked, HTTP on
loopback; written by the owner's ``install.ps1 -Apply``, never a session edit); the sovereign bundle applied (``brain
bundle plan``, then ``apply``); ``brain health ipc``; and Cursor's MCP server rendered (``brain render --target
cursor``; the home folder's file once brain render has a user-level target). They are optional (a machine without
the telemetry collector skips them), and each needs the ones before it: the cockpit runs one at a time, so the owner
stops at the first that fails. ``brain init`` prints the same steps among its next steps (:func:`local_lines`).

A plan writes nothing but a cache (``brain profile --quick`` refreshes ``$BRAIN_HOME/facts.json``); a plan that fails
keeps the apply off. The notification and code index wizards run for the project the cockpit shows (``--project``).
A new brain's folder is an absolute path (its quotes taken off; an option refused).

Read-only and at zero token: :func:`wizards` reads the profile's registry for the stacks it offers, and a read that fails
leaves that wizard's choices empty, never an exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

ASK_DIR = "{dir}"   # a word the owner types before the plan: the folder of a new brain


@dataclass
class Wizard:
    id: str
    title: str
    what: str                         # what it does, in one line
    plan: list[str] | None = None     # the command that writes nothing; {choice} and {dir} filled
    apply: list[str] | None = None    # the command that writes (None: a read, or a plan only)
    choices: tuple = ()               # what the owner picks first (empty: nothing to pick)
    ask: str = ""                     # a word typed before the plan ({dir}): what it is
    placeholder: str = ""             # how the text view names the choice when there are many (else they are listed)
    owner: str = ""                   # plan only: what the owner runs in their own terminal, and why
    scoped: bool = False              # run for the project the cockpit shows (brain --project P ...), when one
    notes: list[str] = field(default_factory=list)

    @property
    def reads(self) -> bool:
        """It only reads: its one command runs on the owner's yes, nothing to plan."""
        return self.apply is None and not self.owner

    def words(self, which: str, choice: str = "", typed: str = "", project: str = "") -> list[str] | None:
        """The plan's or the apply's words with the choice and the typed word filled in, for ``project`` when the wizard
        is scoped and one is given; None when it has none."""
        got = self.plan if which == "plan" else self.apply
        if got is None:
            return None
        if self.scoped and project:
            got = [got[0], "--project", project, *got[1:]]
        out = []
        for w in got:
            if w == "{choice}":
                out += choice.split() if choice else []
            else:
                out.append(w.replace(ASK_DIR, typed))
        return out

    def command(self) -> str:
        """Its commands as the text view shows them: the choice named (``lite|default|recommended``, ``[--find-chat]``,
        or its placeholder), the folder as DIR."""
        named = [c for c in self.choices if c]
        choice = self.placeholder or "|".join(named)
        if "" in self.choices and not self.placeholder:
            choice = f"[{choice}]"

        def text(words):
            return " ".join(choice if w == "{choice}" else w.replace(ASK_DIR, "DIR") for w in words)
        shown = text(self.plan or [])
        if self.apply:
            shown += f", then {text(self.apply)}"
        return shown


def folder(typed: str) -> str:
    """A new brain's folder as typed: its quotes taken off (a path copied from Windows comes quoted); ValueError for an
    option (a word that starts with -) or a relative path, which would land in the cockpit's own folder."""
    text = typed.strip().strip('"').strip("'").strip()
    if not text or text.startswith("-"):
        raise ValueError(f"{typed!r}: a folder, not an option")
    if not (PureWindowsPath(text).is_absolute() or PurePosixPath(text).is_absolute()):
        raise ValueError(f"{typed!r}: an absolute path (a relative one would land in the cockpit's own folder)")
    return str(PurePath(text))


def _stacks(root: Path | None) -> tuple:
    """The stacks and extra capabilities a profile can turn on, as `--with ID` choices; () when unreadable."""
    try:
        from . import tiers
        reg, _ = tiers.registry(root)
    except Exception:  # an unreadable registry leaves the wizard without choices, never an error
        return ()
    return tuple(f"--with {e.id}" for e in sorted(reg.values(), key=lambda e: e.id)
                 if e.status == "built" and not e.auto and e.cls != "core")


def _templates() -> tuple:
    try:
        from . import init
        return tuple(sorted(t.name for t in init.TEMPLATES.iterdir()
                            if t.is_dir() and not t.name.startswith("_") and (t / "template.yaml").is_file()))
    except Exception:  # the engine's templates unreadable: the default alone
        return ("generic",)


def _kinds() -> tuple:
    """The kinds brain project new offers with a template (brain.project_new.offered); () when unreadable."""
    try:
        from . import project_new, typologies
        return tuple(project_new.offered(typologies.engine()))
    except Exception:  # the catalog or the templates unreadable: the wizard without choices, never an error
        return ()


LOCAL_WHY = ("optional, where the telemetry collector runs; each step needs the ones before it: stop at the first "
             "that fails")
LOCAL = [
    Wizard("local-token", "Local services 1: the machine's token",
           "the token of the Brain's local services (the collector, the MCP server over HTTP): its state, then --init "
           "makes it (an unusable file is replaced); it is never shown",
           plan=["brain", "ipc", "token", "--plan"], apply=["brain", "ipc", "token", "--init"], notes=[LOCAL_WHY]),
    # The key before the settings: brain ipc claude-settings adds the otelHeadersHelper line only once
    # ipc.require_token names the collector (headers_helper auto), and the collector requires the token only from
    # the bundle's apply (step 4), so the export carries its header before any refusal.
    Wizard("local-require-token", "Local services 2: the collector's token, declared",
           "config.json ipc.require_token: [otel-collector]: the collector requires the token from step 4's apply on, "
           "and Claude Code's settings (step 3) gain the header; the services' state now",
           plan=["brain", "health", "ipc"],
           owner="a branch and a PR in the personal brain: config.json ipc.require_token: [otel-collector]",
           notes=[LOCAL_WHY]),
    Wizard("local-claude-export", "Local services 3: Claude Code's export and its token header",
           "the settings Claude Code's OTLP export needs (env, and otelHeadersHelper: brain ipc otel-headers, once "
           "step 2 is merged), their exact lines, and the helper's export checked (HTTP, on loopback)",
           plan=["brain", "ipc", "claude-settings"],
           owner="install.ps1 -Apply, in the owner's own terminal: it adds these lines to ~/.claude/settings.json "
                 "(never a session edit)", notes=[LOCAL_WHY]),
    Wizard("local-bundle", "Local services 4: the sovereign bundle",
           "the collector and its stack rendered and started with the token required: the bundle's plan, then its "
           "apply (a second apply changes nothing)",
           plan=["brain", "bundle", "plan", "sovereign"], apply=["brain", "bundle", "apply", "sovereign"],
           notes=[LOCAL_WHY]),
    Wizard("local-health", "Local services 5: the services checked",
           "the token file, each service on loopback and refusing a request without the token",
           plan=["brain", "health", "ipc"], notes=[LOCAL_WHY]),
    Wizard("local-cursor", "Local services 6: Cursor's MCP server",
           "Cursor connects to the Brain's MCP server over stdio: the files brain render writes for it, as a plan",
           plan=["brain", "render", "--target", "cursor"],
           owner="brain render --target cursor --write renders it into the brain's and the project's repos, by a PR; "
                 "the home folder's ~/.cursor/mcp.json once brain render has a user-level target",
           notes=["optional: only when Cursor is used"]),
]


def local_lines() -> list[str]:
    """The Local services steps as ``brain init``'s next steps print them: each a command, in their order."""
    out = [f"      local services, in this order ({LOCAL_WHY}; the cockpit's Setup page runs them):"]
    for i, w in enumerate(LOCAL, 1):
        out.append(f"        {i}. {w.title.split(': ', 1)[1]}: " + (f"{w.owner}; see {w.command()}" if w.owner
                                                                     else w.command()))
    return out


def wizards(root: Path | None = None) -> list[Wizard]:
    """The setup wizards, in the order a new brain walks them."""
    return [
        Wizard("first-run", "First run: the profile",
               "this machine's profile: Lite, Default or Recommended (computed for this machine); then its plan, "
               "then --apply writes $BRAIN_HOME/profile.json",
               plan=["brain", "profile", "set", "{choice}"], apply=["brain", "profile", "set", "{choice}", "--apply"],
               choices=("lite", "default", "recommended"),
               notes=["Custom (Personnalisable): brain profile set --with ID / --without ID, or the stacks wizard"]),
        Wizard("stacks", "The stacks to enable",
               "a stack or an extra capability turned on for this machine: its plan, then --apply",
               plan=["brain", "profile", "set", "{choice}"], apply=["brain", "profile", "set", "{choice}", "--apply"],
               choices=_stacks(root), placeholder="--with ID"),
        Wizard("modules", "The modules", "the modules of the registry, on or off: brain mod enable|disable MODULE "
               "(a plan, then --apply)", plan=["brain", "mod", "list"]),
        Wizard("project", "Add a project",
               "a project's entry in projects.yaml: a branch and a PR in the personal brain, never an edit here",
               plan=["brain", "projects"], owner="a branch in the personal brain's repo, the project's entry added to "
               "projects.yaml, a PR; brain check --all before it merges"),
        Wizard("project-new", "A new project",
               "a new project's brain from what it produces (a kind of the typology catalog: code products and "
               "research first) and its stage: the plan in the folder typed, then --apply (brain init, its registry "
               "entry recording lifecycle: {typologies, stage})",
               plan=["brain", "project", "new", ASK_DIR, "--kind", "{choice}"],
               apply=["brain", "project", "new", ASK_DIR, "--kind", "{choice}", "--apply"],
               choices=_kinds(), placeholder="KIND", ask="the new project's folder (a path; it must not hold a brain "
                                                       "yet)",
               notes=["--stage prototype|mvp|v1|scale and more --kind: brain project new in a terminal"]),
        Wizard("notify-ntfy", "Notifications: ntfy",
               "the ntfy channel's steps: its topic set by the owner as an environment variable, named in "
               "projects.yaml, never typed here", plan=["brain", "notify", "setup", "ntfy"], scoped=True),
        Wizard("notify-telegram", "Notifications: Telegram",
               "the Telegram channel's steps, then the chats that wrote to the bot (it sends nothing); the token set "
               "by the owner, shown by its name only",
               plan=["brain", "notify", "setup", "telegram", "{choice}"], choices=("", "--find-chat"), scoped=True),
        Wizard("notify-status", "Notifications: the routes", "the channels (their variables set or missing, never "
               "their values), the routes and the outbox", plan=["brain", "notify", "status"], scoped=True),
        Wizard("permissions", "Permissions", "the effective rules and where each comes from; a rule granted by a "
               "PR (brain permissions grant)", plan=["brain", "permissions"],
               owner="brain permissions grant --rule R --why W: a rule appended in a branch, reviewed by PR"),
        Wizard("machines", "Machines and inventory", "this machine's facts and their source (agent, probed, nodes "
               "file, declared), the active profile and what Recommended would add (it refreshes the facts' cache, "
               "$BRAIN_HOME/facts.json, and nothing else)",
               plan=["brain", "profile", "--quick"]),
        Wizard("code-index", "The code index", "each repo's index state, then the repos not indexed at their branch "
               "head indexed again", plan=["brain", "index"], apply=["brain", "index", "--stale"], scoped=True),
        Wizard("instance", "A new brain from a template",
               "a new personal brain from a domain template: its plan in the folder typed, then --apply writes it "
               "(it never overwrites)",
               plan=["brain", "init", ASK_DIR, "--template", "{choice}"],
               apply=["brain", "init", ASK_DIR, "--template", "{choice}", "--apply"],
               choices=_templates(), placeholder="TEMPLATE",
               ask="the new brain's folder (a path; it must not hold a brain yet)"),
        Wizard("claude-settings", "Claude Code's settings",
               "the rules the user settings would gain: a plan only", plan=["brain", "permissions", "render",
                                                                             "--level", "user"],
               owner="install.ps1 -Apply, in the owner's own terminal: it writes ~/.claude/settings.json"),
        *LOCAL,
        Wizard("checks", "Checks", "the configuration, the registry and the stores checked",
               plan=["brain", "check", "--all"]),
    ]


def module_wizard(mid: str, state: str) -> Wizard:
    """A module turned on or off for this machine (wi-brain-modules-tab): brain mod's plan (what it pulls, what turns
    on and off, its cost), then --apply, which writes $BRAIN_HOME/profile.json. Off keeps the module's data and
    configuration (SIGMA-17): only the profile changes; --cascade also turns off what needs it."""
    choices = (("disable", "disable --cascade") if state.startswith("on")
               else ("enable",) if state.startswith("off") else ("enable", "disable", "disable --cascade"))
    return Wizard(f"module {mid}", f"Module {mid}", f"turn {mid} on or off for this machine: brain mod's plan, then "
                  "--apply writes $BRAIN_HOME/profile.json; off keeps its data and configuration",
                  plan=["brain", "mod", "{choice}", mid], apply=["brain", "mod", "{choice}", mid, "--apply"],
                  choices=choices, placeholder="enable|disable")


def by_id(root: Path | None = None) -> dict[str, Wizard]:
    return {w.id: w for w in wizards(root)}
