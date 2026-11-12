"""A brain's permissions as data, in a hierarchy like Claude Code's settings (wi-brain-permission-hierarchy, ADR "La
hiérarchie des permissions"): ``brain permissions [--project P | --all] [--machine H] [--session S] [--explain RULE]
[--json]``, ``brain permissions check``, ``brain permissions render`` and ``brain permissions grant``, at zero token.

The levels, from the broadest to the most specific, each with ``allow``, ``ask`` and ``deny`` rules:

- ``engine``: ``allow-rules.txt``, the brain commands' own narrow rules, the same for every user (install.ps1 reads it
  alone when the brain command cannot run);
- ``global``: every project on every machine;
- ``profile``: the machines that run a profile (lite, default, recommended: wi-brain-profile);
- ``machine``: every project on one machine, named by its host name;
- ``tenant``: every project of one tenant (wi-brain-hmaas-multitenant);
- ``project``: one registered project, in each of its repos;
- ``local``: one project on one machine;
- ``session``: one session or sub-session (a sub-session's parent's rules come first).

Every level but the engine's is ``permissions.yaml``, next to the registry (``$BRAIN_PERMISSIONS`` names another file):
``never`` (the categories no level may allow), ``profiles``, ``machines``, ``tenants``, ``sessions`` (each declared with
a title) and ``rules``, the file's last key, one flow mapping per line, which ``brain permissions grant`` appends to::

  - {allow: "Shell(docker inspect *)", project: quant, why: "...", by: "<who>, <date>", from: perm-60c75cdd84}

A rule's level is what it names: nothing (global), ``profile``, ``machine``, ``tenant``, ``project``, ``project`` with
``machine`` (local), or ``session``. Its text is Claude Code's syntax (``Tool`` or ``Tool(specifier)``), the reference
format the adapters translate; ``Shell(...)`` stands for both ``Bash(...)`` and ``PowerShell(...)``.

Precedence is Claude Code's, which merges the lists of every scope: deny, then ask, then allow, whatever the level. A
more specific level can tighten what a broader one allows (an ask or a deny over its allow) and never loosens a broader
ask or deny; the source shown for a rule is the most specific level that declares its winning verdict.

Never grantable: the categories of :data:`NEVER` (the ones ``brain.queue`` classes as the owner's actions), plus those
``never`` adds (a file adds categories, patterns and probes, never removes one). An allow rule falls in one by its
text (quotes and escapes dropped) or by its pattern, when it would match one of the category's commands
(:data:`PROBES`: Bash(gh repo edit *) covers gh repo edit --visibility public): such a rule is refused at every level,
the engine's included, by ``check``, ``render`` and ``grant`` (:func:`never_rule`); an ask or a deny there is fine, and
a category's ``deny`` rules are rendered at the global level. Broad allow rules are refused too (:func:`broad`): a
shell tool alone, a wildcard in or for the program's name, an interpreter or a shell with a wildcard (its :* form,
versioned or quoted names, VAR=1 before it), a package runner with a wildcard, Agent and Monitor (what Claude Code's
auto mode drops), a read, edit or fetch tool alone or for every path or domain (mcp__server__* passes). Loading never
raises: what a file gets wrong is in ``errors``.

The guards (brain.guards) stay the hard deny layer, apart from the rules: a PreToolUse hook whose deny no allow rule
lifts, which judges what a pattern cannot see (the folder a call runs in, its redirections, a commit's staged diff), in
every permission mode, with a ledger and the owner's override. A deny rule is a pattern Claude Code matches on a call's
text, per agent: it adds a refusal without a script, and a variant of the command passes it. A deny rule never replaces
a guard, and a guard is never written as a rule.

Rendering is an adapter's (:data:`ADAPTERS`, :class:`Adapter` the interface; only Claude Code's is built). Claude Code:
engine, global, profile and machine into the user settings (``~/.claude/settings.json``, written by ``install.ps1
-Apply``, the owner's, from ``render --level user --json``); tenant and project into each repo's ``.claude/settings.json``
(a PR in that repo; a production checkout is rendered into a worktree of it, ``--repo``); local into
``.claude/settings.local.json``; a session into a file for ``claude --settings``. A render adds the missing rules and
never removes one; ``brain permissions`` shows the rules a settings file holds that no level declares.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config, graph, paths, projects, schema, stateio

FILE = "permissions.yaml"
ENGINE_FILE = "allow-rules.txt"
ENV = "BRAIN_PERMISSIONS"
LEVELS = ("engine", "global", "profile", "machine", "tenant", "project", "local", "session")
VERDICTS = ("deny", "ask", "allow")   # Claude Code's order: the first verdict that matches wins
SECTIONS = ("v", "never", "profiles", "machines", "tenants", "sessions", "rules")
SELECTORS = ("profile", "machine", "tenant", "project", "session")
# A rule's provenance (from: the request it answers, asked_by: the session that asked, for: the items and milestones it
# unblocks) and its duration (until: a date, while: an item that is open; none: indefinite; the session level: one
# session): an expired rule leaves the effective list, and a render removes it from the settings it was rendered into.
RULE_KEYS = set(VERDICTS) | set(SELECTORS) | {"why", "by", "from", "date", "until", "while", "asked_by", "for"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CLOSED = {"done", "dropped", "reached", "superseded", "retired"}
WHY_MIN = 15
SHELLS = ("Bash", "PowerShell")
SHELL = "Shell"                       # the neutral form: Bash and PowerShell
RULE_RE = re.compile(r"^(?P<tool>[A-Za-z_][\w\-]*\*?)(?:\((?P<spec>.+)\))?$", re.S)

# What only the owner may do: (category, how the rules name it, what finds it in a text: a rule, a denied command, an item
# prop). The first four come from the rules' "<owner> decides" lists, legal reading from the harness (accepting terms is
# never the agent's). brain.queue classes a text in one as an action; no level may allow a rule in one.
NEVER = (
    ("keys", r"\bkeys?\b|\bsecrets?\b|\bcredentials?\b",
     r"\bsecrets?\b|\bpasswords?\b|\bcredentials?\b|\b(?:api|recovery|encryption|private|signing|exchange|ssh|"
     r"age|gpg)[ _-]?keys?\b|\b(?:access|auth|bot|telegram|ntfy|github|gh)[ _-]?(?:tokens?|keys?|topics?)\b|"
     r"\brotate\b|credential materialization|\bmots? de passe\b"),
    ("money", r"\bmoney\b", r"\bmoney\b|\bpay(?:ment|ing|s)?\b|\bbilling\b|\bbudget\b|\bpurchas|\binvoic|"
     r"\bsubscription|\bbank\b|\bargent\b|\bpayer\b"),
    ("arming", r"\barm(?:ing)?\b|\blive orders?\b", r"\barm(?:ing|ed)?\b|\blive (?:orders?|trading)\b|\barmer\b"),
    ("visibility", r"\bvisibility\b",
     r"\bvisibilit[yé]\b|--visibility\b|--public\b|\bmake (?:it |the repo )?public\b"),
    ("accounts", r"\baccounts?\b", r"\baccounts?\b|\bsign[ -]?up\b|\boauth\b|\bsupport (?:ticket|request)s?\b|"
     r"\bgithub support\b|\bcompte\b"),
    ("scheduled", r"\bscheduled tasks?\b|\bservices?\b",
     r"\bscheduled tasks?\b|\bschtasks\b|register-scheduledtask|\bcrontab\b|new-service|\bsystemctl enable\b|"
     r"\bnew service\b|\bt[âa]ches? planifi[ée]e"),
    ("legal", r"\blegal\b|\bterms\b|\blicen[cs]es?\b",
     r"\blegal\b|\blawyer\b|\bnotary\b|\bnotaire\b|\bterms of (?:service|use)\b|\btos\b|\bcgu\b|\bjuridique\b"),
    # A session's Remote Control and permission mode (wi-brain-guard-session-settings): the guards refuse the desktop
    # app's tools that change them, and BRAIN_GUARD_ALLOW cannot lift that refusal (brain.guards.UNLIFTED). No allow
    # rule grants it either: Remote Control's three exceptions are the guard's own checks (brain.guards.remote_control,
    # wi-brain-guard-rc-archive), never a permission.
    ("security-settings", r"\bsecurity[ -]settings?\b|(?<![a-z])remote[ _-]?control\b|\bpermission[ _-]?modes?\b",
     r"\bsecurity[ -]settings?\b|(?<![a-z])remote[ _-]?control(?![a-z])|(?<![a-z])permission[ _-]?modes?(?![a-z])|"
     r"set_session_permission_mode|\bbypass ?permissions\b|\bt[ée]l[ée]commande\b|\bmode de permission"),
)

# Commands of the never-grantable categories: an allow rule whose pattern matches one is refused like one whose text
# names the category (Bash(gh repo edit *) covers gh repo edit X --visibility public). permissions.yaml adds its own
# (never.<category>.probes).
PROBES = {
    "keys": ("gh secret set NAME", "gh secret delete NAME", "gh auth token", "ssh-keygen -t ed25519 -f KEY",
             "age-keygen -o KEY", "gpg --export-secret-keys ID", "cmdkey /add:HOST", "Set-Secret -Name NAME"),
    "visibility": ("gh repo create OWNER/NAME --public", "gh repo create --public OWNER/NAME",
                   "gh repo edit OWNER/NAME --visibility public", "gh repo edit --visibility public OWNER/NAME",
                   "gh repo edit --visibility public", "gh api -X PATCH repos/OWNER/NAME -f private=false",
                   "gh gist create --public FILE"),
    "accounts": ("gh auth login", "gh auth logout", "gh auth refresh -s SCOPE"),    "scheduled": ("schtasks /create /tn NAME /tr CMD", "Register-ScheduledTask -TaskName NAME", "crontab -e",
                  "New-Service -Name NAME", "sc.exe create NAME", "systemctl enable NAME"),
}

# Broad allow rules (:func:`broad`): what runs anything once allowed, and what Claude Code's auto mode drops.
INTERPRETERS = {"python", "python3", "py", "pythonw", "node", "deno", "bun", "ruby", "perl", "php", "lua", "bash",
                "sh", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd", "wsl", "env", "sudo", "su", "doas",
                "xargs", "eval", "exec", "source", ".", "npx", "bunx", "uvx", "pipx", "invoke-expression", "iex",
                "start-process", "saps", "start", "invoke-command", "icm", "start-job", "sajb", "invoke-item", "ii"}
INTERPRETER_RE = re.compile(r"^(?:python|pythonw|pypy|py|node|ruby|perl|php|lua|bash|zsh|pwsh|powershell)[\d.]*$")
RUNNERS = {"npm": {"run", "run-script", "exec", "x"}, "pnpm": {"run", "exec", "dlx"}, "yarn": {"run", "exec", "dlx"},
           "uv": {"run"}, "poetry": {"run"}, "cargo": {"run"}, "go": {"run"}}
PATH_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}
ALONE = {"Bash", "PowerShell", SHELL, "WebFetch"} | PATH_TOOLS
AUTO_DROPPED = {"Agent", "Task", "Monitor"}


class PermissionsError(Exception):
    """A grant or a render refused (the message says why and what to do)."""


# --- the never-grantable categories ----------------------------------------------------------------------------

class AnyOf:
    """Patterns searched in turn: a file's patterns are added to the engine's, never in place of them."""

    def __init__(self, *pats: re.Pattern):
        self.pats = [p for p in pats if p is not None]

    def search(self, text: str):
        return next((m for p in self.pats if (m := p.search(text))), None)

    @property
    def pattern(self) -> str:
        return "|".join(f"(?:{p.pattern})" for p in self.pats)


@dataclass
class Category:
    name: str
    find: AnyOf
    names: AnyOf | None = None        # how the rules name it (brain.queue's coverage of the "<owner> decides" lists)
    why: str = ""
    deny: list[str] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)   # commands of the category an allow rule must not match
    source: str = "engine"            # engine, file, or engine+file (patterns added)


NEVER_KEYS = {"why", "find", "names", "deny", "probes"}


def categories(data: dict | None = None) -> tuple[list[Category], list[str]]:
    """The categories no level may allow: :data:`NEVER`, extended by a file's ``never`` (more patterns, a why, deny
    rules, probes, or a new category with its find), and the errors of that section."""
    out = {name: Category(name, AnyOf(re.compile(find, re.I)), AnyOf(re.compile(rule, re.I)),
                          probes=list(PROBES.get(name, ()))) for name, rule, find in NEVER}
    errors: list[str] = []
    never = (data or {}).get("never")
    if never is None:
        return list(out.values()), errors
    if not isinstance(never, dict):
        return list(out.values()), [f"{FILE}: never is a mapping of category -> {{{', '.join(sorted(NEVER_KEYS))}}}"]
    for name, entry in never.items():
        name, where = str(name), f"{FILE}: never.{name}"
        entry = entry if entry is not None else {}
        if not isinstance(entry, dict) or set(map(str, entry)) - NEVER_KEYS:
            errors.append(f"{where}: a mapping of {', '.join(sorted(NEVER_KEYS))}")
            continue
        pats = {}
        for key in ("find", "names"):
            if entry.get(key) in (None, ""):   # an empty pattern would match every text
                continue
            try:
                pats[key] = re.compile(str(entry[key]), re.I)
            except re.error as exc:
                errors.append(f"{where}.{key}: not a regular expression ({exc})")
        lists = {}
        for key, ok in (("deny", parse), ("probes", lambda s: s.strip())):
            value = entry.get(key) or []
            if not isinstance(value, list) or not all(isinstance(d, str) and ok(d) for d in value):
                errors.append(f"{where}.{key}: a list of " + ("rules (Tool or Tool(specifier))" if key == "deny"
                                                              else "commands"))
                value = []
            lists[key] = list(value)
        cat = out.get(name)
        if cat is None:
            if "find" not in pats:
                errors.append(f"{where}: a new category needs its find pattern")
                continue
            cat = out[name] = Category(name, AnyOf(pats["find"]), AnyOf(pats["names"]) if "names" in pats else None,
                                       source="file")
        else:
            cat.find = AnyOf(*cat.find.pats, pats.get("find"))
            if "names" in pats:
                cat.names = AnyOf(*(cat.names.pats if cat.names else []), pats["names"])
            cat.source = "engine+file" if pats or lists["probes"] else cat.source
        cat.why = str(entry.get("why") or cat.why)
        cat.deny = lists["deny"]
        cat.probes += [p for p in lists["probes"] if p not in cat.probes]
    return list(out.values()), errors


_CACHE: dict = {}


def default_categories() -> list[Category]:
    """The categories of the personal brain's permissions.yaml (found like the registry), cached on its mtime: what
    brain.queue classes the owner's actions by. Never fails: an unreadable file leaves the engine's."""
    f = permissions_file()
    try:
        key = (str(f), f.stat().st_mtime) if f and f.is_file() else (str(f), None)
    except OSError:
        key = (str(f), None)
    if _CACHE.get("key") != key:
        cats = None
        if key[1] is not None:
            try:
                data = graph.load_yaml(f.read_text(encoding="utf-8")) or {}   # libyaml: read by the guards
                cats = categories(data if isinstance(data, dict) else {})[0]
            except Exception:
                cats = None
        _CACHE["key"], _CACHE["cats"] = key, cats if cats is not None else categories({})[0]
    return _CACHE["cats"]


def _plain(text: str) -> str:
    """``text`` without the quotes and escapes a shell drops (gh repo edit --visibi\\lity public)."""
    return re.sub(r"[\\`'\"]", "", text or "")


def never_category(text: str, cats: list[Category] | None = None) -> str:
    """The first never-grantable category ``text`` falls in, its quotes and escapes dropped too, else ''."""
    cats = cats if cats is not None else default_categories()
    for t in dict.fromkeys((text or "", _plain(text))):
        for c in cats:
            if c.find.search(t):
                return c.name
    return ""


def never_rule(text: str, cats: list[Category] | None = None) -> str:
    """The never-grantable category an allow rule falls in: its text names one, or its pattern matches one of a
    category's commands (Bash(gh repo edit *), PowerShell(Register-Scheduled*), Bash(schtask* *)); else ''."""
    cats = cats if cats is not None else default_categories()
    cat = never_category(text, cats)
    if cat:
        return cat
    for atom in atoms(text):
        p = parse(atom)
        if not p or p[0] not in SHELLS:
            continue
        for c in cats:
            if any(matches(atom, p[0], probe) for probe in c.probes):
                return c.name
    return ""


# --- rules: syntax, the neutral shell, narrowness, matching ----------------------------------------------------

def parse(text: str) -> tuple[str, str | None] | None:
    """(tool, specifier or None) of a rule in Claude Code's syntax, else None."""
    m = RULE_RE.match(str(text or "").strip())
    if not m or (m["spec"] is not None and not m["spec"].strip()):
        return None
    return m["tool"], m["spec"]


def atoms(text: str) -> list[str]:
    """The rule as Claude Code rules: Shell(x) is Bash(x) and PowerShell(x); a trailing :* is written ' *'."""
    p = parse(text)
    if not p:
        return [text]
    tool, spec = p
    if spec is not None and spec.endswith(":*"):
        spec = spec[:-2] + " *"
    tools = SHELLS if tool == SHELL else (tool,)
    return [t if spec is None else f"{t}({spec})" for t in tools]


def _prog(word: str) -> str:
    name = re.split(r"[\\/]", word)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def broad(text: str) -> str:
    """Why an allow rule is too broad to grant, else ''."""
    p = parse(text)
    if not p:
        return ""
    tool, spec = p
    if tool in AUTO_DROPPED:
        return f"Claude Code's auto mode drops {tool} allow rules"
    if spec is None:   # mcp__server__* (one server's tools) is narrow enough; mcp__* is every server's
        wide = tool in ALONE or (tool.endswith("*") and tool.count("__") < 2)
        return f"{tool} alone allows every call" if wide else ""
    s = spec.strip()
    if tool in PATH_TOOLS:   # Edit(**), Read(//**), Write(~/**), Edit(//c/**): every path
        rest = re.sub(r"^(?://|/|~/|\./)?(?:[A-Za-z]:?/)?", "", s.replace("\\", "/"))
        return f"{tool}({spec}) matches every path" if "*" in rest and re.fullmatch(r"[*/.]*", rest) else ""
    if tool == "WebFetch":
        return "every domain" if re.fullmatch(r"(?:domain:)?[*.]*", s) else ""
    if tool not in SHELLS + (SHELL,):
        return ""
    if s.endswith(":*"):
        s = s[:-2] + " *"
    words = s.split()
    while words and re.match(r"^\$?[A-Za-z_]\w*=", words[0]):   # VAR=1 python *
        words = words[1:]
    if not words:
        return "no program: the rule matches any command"
    w0 = words[0].strip("'\"")
    if "*" in w0:
        return "a wildcard in the program's name matches any command"
    wild = "*" in s
    first = _prog(w0)
    if wild and (first in INTERPRETERS or INTERPRETER_RE.match(first)):
        return f"{first} with a wildcard runs any code"
    if wild and first in RUNNERS and (len(words) == 1 or "*" in words[1] or words[1] in RUNNERS[first]):
        return f"{' '.join(words[:2])} covers {first}'s script runner, which runs any script (Claude Code's auto " \
               "mode drops it)"
    return ""


def _glob(spec: str) -> re.Pattern:
    """A specifier as Claude Code matches it: * is any text, and a trailing ' *' also matches the bare command."""
    s = spec[:-2] + " *" if spec.endswith(":*") else spec
    tail = ""
    if s.endswith(" *"):
        s, tail = s[:-2], r"(?:\s.*)?"
    return re.compile(".*".join(re.escape(part) for part in s.split("*")) + tail, re.S)


def matches(rule: str, tool: str, text: str) -> bool:
    """Whether the Claude Code rule ``rule`` matches a call of ``tool`` whose text (command, path, url) is ``text``."""
    p = parse(rule)
    if not p or p[0] != tool:
        return False
    if p[1] is None:
        return True
    flags = re.I if tool == "PowerShell" else 0
    rx = _glob(p[1])
    return bool(re.fullmatch(rx.pattern, text.strip(), rx.flags | flags))


def parse_call(call: str) -> tuple[str, str]:
    """(tool, text) of a call written ``Bash: cmd`` (brain queue's form), ``Bash(cmd)``, or a bare command (Bash)."""
    m = re.match(r"^([A-Za-z_][\w\-]*):\s(.*)$", call, re.S)
    if m:
        return m[1], m[2]
    p = parse(call)
    if p and p[1] is not None:
        return p[0], p[1]
    return "Bash", call


def parts(tool: str, command: str) -> list[str]:
    """The simple commands of a shell call, as text (brain.guards' reader: quoting, ;, &&, |, subshells); Claude Code
    allows a compound command only when every part is allowed."""
    if tool not in SHELLS:
        return [command]
    from . import guards  # the hooks' module: standard library only
    out = []
    for words in guards.segments(command, powershell=tool == "PowerShell"):
        kept, skip = [], False
        for w in words:
            if skip:
                skip = False
                continue
            if w.startswith(guards.REDIRECT):
                skip = True
                continue
            if w in guards.SUBSHELL:
                continue
            kept.append(w)
        if kept:
            out.append(" ".join(kept))
    return out or [command]


# --- the model -------------------------------------------------------------------------------------------------

@dataclass
class Rule:
    text: str                 # as declared
    verdict: str
    level: str
    scope: str = ""           # the profile, machine, tenant, project, project@machine or session it applies to
    why: str = ""
    by: str = ""
    origin: str = ""          # 'from': the permission task it answers (perm-...)
    date: str = ""
    where: str = ""           # permissions.yaml rules[3], allow-rules.txt:12, permissions.yaml never.visibility
    until: str = ""           # the last day it holds (YYYY-MM-DD)
    while_: str = ""          # the item it holds for: it expires when the item is done or dropped
    asked_by: str = ""        # the session that asked for it
    for_: list = field(default_factory=list)   # the items and milestones it unblocks

    def label(self) -> str:
        return self.level + (f" {self.scope}" if self.scope else "")

    def duration(self) -> str:
        if self.until:
            return f"until {self.until}"
        if self.while_:
            return f"while {self.while_} is open"
        return f"session {self.scope}" if self.level == "session" else "indefinite"


@dataclass
class Model:
    file: Path | None
    engine_file: Path | None
    data: dict = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # read mode: a newer brain's keys, kept (brain.schema.tolerate)
    registry: dict = field(default_factory=dict)   # name -> projects.Project
    today: date = field(default_factory=date.today)
    statuses: dict | None = None                   # item id -> status, read from the stores when a rule has a while

    def section(self, name: str) -> dict:
        value = self.data.get(name)
        return value if isinstance(value, dict) else {}

    def status(self, nid: str) -> str | None:
        """An item's status in any registered project's stores (None: no such node)."""
        if self.statuses is None:
            self.statuses = {}
            for p in self.registry.values():
                for store in p.stores:
                    if (store / "schema.yaml").is_file():
                        try:
                            idx = graph.node_index(store)
                        except Exception:
                            continue
                        self.statuses.update({k: str(n.get("status") or "") for k, (_, n) in idx.items()})
        return self.statuses.get(nid)

    def expired(self, r: Rule) -> str:
        """Why a rule no longer holds, else '': its until is past, or the item it holds for is closed."""
        if r.until and DATE_RE.match(r.until) and r.until < self.today.isoformat():
            return f"until {r.until}"
        if r.while_ and self.status(r.while_) in CLOSED:
            return f"while {r.while_} (now {self.status(r.while_)})"
        return ""

    def live(self) -> list[Rule]:
        return [r for r in self.rules if not self.expired(r)]


def permissions_file(root: Path | None = None) -> Path | None:
    """``$BRAIN_PERMISSIONS``, else permissions.yaml in ``root`` (the checkout acted on: a PR's worktree checks its own
    file), else next to the registry (brain.projects), else in the other places of :func:`brain.paths.bases` (the
    personal brain)."""
    env = os.environ.get(ENV)
    if env:
        return Path(env).expanduser()
    if root and (Path(root) / FILE).is_file():
        return Path(root) / FILE
    reg = projects.registry_file(root)
    if reg and (reg.parent / FILE).is_file():
        return reg.parent / FILE
    for base in paths.bases(root):
        if (base / FILE).is_file():
            return base / FILE
    return None


def engine_file(pfile: Path | None) -> Path | None:
    """allow-rules.txt next to the permissions file (a personal brain that still holds the engine's copy), else the
    engine's own (package data, adapters/claude/allow-rules.txt)."""
    for base in ((pfile.parent if pfile else None), Path(__file__).resolve().parent / "adapters" / "claude"):
        if base and (Path(base) / ENGINE_FILE).is_file():
            return Path(base) / ENGINE_FILE
    return None


def read_engine(f: Path | None) -> list[Rule]:
    """allow-rules.txt: one allow rule per line, '#' a comment (the format install.ps1 reads); a rule's why is the
    comment block above it."""
    if not f or not f.is_file():
        return []
    out, block, after_rule = [], [], False
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            block, after_rule = [], False
        elif line.startswith("#"):
            block = [] if after_rule else block
            block.append(line.lstrip("#").strip())
            after_rule = False
        else:
            out.append(Rule(line, "allow", "engine", why=" ".join(block), where=f"{f.name}:{n}"))
            after_rule = True
    return out


def _level(entry: dict) -> tuple[str, str] | str:
    """(level, scope) from a rule's selectors, or why they do not name one level."""
    named = [k for k in SELECTORS if entry.get(k) not in (None, "")]
    if not named:
        return "global", ""
    if set(named) == {"project", "machine"}:
        return "local", f"{entry['project']}@{entry['machine']}"
    if len(named) > 1:
        return f"{' and '.join(named)}: one level at a time (project with machine is the local level)"
    return named[0], str(entry[named[0]])


def _declared(model: Model) -> dict[str, set[str]]:
    out = {k: {str(n) for n in model.section(k)} for k in ("profiles", "machines", "tenants", "sessions")}
    out["machines_lower"] = {m.lower() for m in out["machines"]}
    return out


def _entry_errors(entry, where: str, model: Model, decl: dict) -> tuple[Rule | None, list[str]]:
    """The rule an entry of ``rules`` declares, and what is wrong with it."""
    if not isinstance(entry, dict):
        return None, [f"{where}: a mapping {{allow|ask|deny: RULE, <level>, why}}"]
    errors = []
    unknown = sorted(set(map(str, entry)) - RULE_KEYS)
    if unknown:
        errors += schema.tolerate(f"{where}: unknown key(s) {', '.join(unknown)} (known: {', '.join(sorted(RULE_KEYS))})",
                                  notes=model.notes)
        if not errors and next((v for v in VERDICTS if v in entry), None) == "allow":
            # read mode: a newer brain's key may narrow this grant; applied without it, it would grant more
            model.notes.append(f"{where}: allow rule left out: its key(s) {', '.join(unknown)} are a newer brain's")
            return None, []
    verdicts = [v for v in VERDICTS if v in entry]
    if len(verdicts) != 1:
        return None, errors + [f"{where}: exactly one of allow, ask or deny"]
    verdict = verdicts[0]
    text = entry[verdict]
    if not isinstance(text, str) or not parse(text):
        return None, errors + [f"{where}: {verdict} {text!r} is not a rule (Tool or Tool(specifier))"]
    level = _level(entry)
    if isinstance(level, str):
        return None, errors + [f"{where}: {level}"]
    lvl, scope = level
    why = entry.get("why")
    if not isinstance(why, str) or len(why.strip()) < WHY_MIN:
        errors.append(f"{where}: why, a reason of {WHY_MIN} characters at least")
    if lvl in ("project", "local") and str(entry["project"]) not in model.registry:
        errors.append(f"{where}: project {entry['project']!r} is not registered (projects.yaml)")
    for key, section in (("profile", "profiles"), ("tenant", "tenants"), ("session", "sessions")):
        if entry.get(key) not in (None, "") and str(entry[key]) not in decl[section]:
            errors.append(f"{where}: {key} {entry[key]!r} is not declared under {section}:")
    if entry.get("machine") not in (None, "") and str(entry["machine"]).lower() not in decl["machines_lower"]:
        errors.append(f"{where}: machine {entry['machine']!r} is not declared under machines:")
    until = str(entry.get("until") or "")   # an unquoted YAML date reads as a date: its text is the same
    if until and not DATE_RE.match(until):
        errors.append(f"{where}: until is a date, YYYY-MM-DD ({until!r})")
    for key in ("while", "asked_by"):
        if entry.get(key) is not None and not (isinstance(entry[key], str) and entry[key].strip()):
            errors.append(f"{where}: {key} is " + ("an item id" if key == "while" else "a session id"))
    if entry.get("while") and until:
        errors.append(f"{where}: until or while, not both")
    fors = entry.get("for") or []
    fors = [fors] if isinstance(fors, str) else fors
    if not isinstance(fors, list) or not all(isinstance(x, str) for x in fors):
        errors.append(f"{where}: for is an item or milestone id, or a list of them")
        fors = []
    rule = Rule(text.strip(), verdict, lvl, scope, why=str(why or "").strip(), by=str(entry.get("by") or ""),
                origin=str(entry.get("from") or ""), date=str(entry.get("date") or ""), where=where, until=until,
                while_=_name(entry.get("while")) or "", asked_by=_name(entry.get("asked_by")) or "", for_=list(fors))
    return rule, errors


def rule_errors(rule: Rule, cats: list[Category]) -> list[str]:
    """What no level may hold: a text that is not a rule (an allow-rules.txt line), an allow rule in a never-grantable
    category (by its text or by a command of the category its pattern matches), or a broad one."""
    if not parse(rule.text):
        return [f"{rule.where}: {rule.text!r} is not a rule (Tool or Tool(specifier))"]
    if rule.verdict != "allow":
        return []
    out = []
    cat = never_rule(rule.text, cats)
    if cat:
        out.append(f"{rule.where}: allow {rule.text} falls in {cat}, which only the owner does: never grantable "
                   "(ask or deny it instead)")
    why = broad(rule.text)
    if why:
        out.append(f"{rule.where}: allow {rule.text} is too broad ({why}): grant a narrow rule")
    return out


def _sections_errors(model: Model) -> list[str]:
    errors = []
    data = model.data
    refused = schema.newer(FILE, data.get("v"))
    if refused:          # a newer brain's hierarchy: refused whole, its sections may mean something else now
        return [refused]
    unknown = sorted(set(map(str, data)) - set(SECTIONS))
    if unknown:
        errors += schema.tolerate(f"{FILE}: unknown key(s) {', '.join(unknown)} (known: {', '.join(SECTIONS)})",
                                  notes=model.notes)
    if data and data.get("v") != 1:
        errors.append(f"{FILE}: v is 1")
    for name in ("profiles", "machines", "tenants", "sessions"):
        sec = data.get(name)
        if sec is None:
            continue
        if not isinstance(sec, dict):
            errors.append(f"{FILE}: {name} is a mapping of name -> {{title, ...}}")
            continue
        for key, entry in sec.items():
            where = f"{FILE}: {name}.{key}"
            if not isinstance(entry, dict) or not isinstance(entry.get("title"), str) or not entry["title"].strip():
                errors.append(f"{where}: a mapping with a title")
                continue
            allowed = {"title"} | {"machines": {"profile"}, "tenants": {"projects"},
                                   "sessions": {"project", "parent"}}.get(name, set())
            extra = sorted(set(map(str, entry)) - allowed)
            if extra:
                errors += schema.tolerate(f"{where}: unknown key(s) {', '.join(extra)} "
                                          f"(known: {', '.join(sorted(allowed))})", notes=model.notes)
            for k in ("profile", "project", "parent"):
                if entry.get(k) is not None and not isinstance(entry[k], str):
                    errors.append(f"{where}.{k}: a name")
            if entry.get("projects") is not None and not _names(entry["projects"]):
                errors.append(f"{where}.projects: a list of project names")
    machines, profiles = model.section("machines"), model.section("profiles")
    for m, entry in machines.items():
        prof = entry.get("profile") if isinstance(entry, dict) else None
        if isinstance(prof, str) and prof and prof not in profiles:
            errors.append(f"{FILE}: machines.{m}.profile {prof!r} is not declared under profiles:")
    seen: dict[str, str] = {}
    for t, entry in model.section("tenants").items():
        for p in _names(entry.get("projects")) if isinstance(entry, dict) else []:
            if p not in model.registry:
                errors.append(f"{FILE}: tenants.{t}.projects: {p!r} is not registered (projects.yaml)")
            if p in seen:
                errors.append(f"{FILE}: project {p!r} is in two tenants ({seen[p]}, {t})")
            seen[p] = str(t)
    sessions = model.section("sessions")
    for s, entry in sessions.items():
        if not isinstance(entry, dict):
            continue
        proj = entry.get("project")
        if isinstance(proj, str) and proj and proj not in model.registry:
            errors.append(f"{FILE}: sessions.{s}.project {proj!r} is not registered (projects.yaml)")
        chain, cur = [str(s)], _name(entry.get("parent"))
        while cur not in (None, ""):
            if cur not in sessions:
                errors.append(f"{FILE}: sessions.{s}.parent {cur!r} is not declared under sessions:")
                break
            if cur in chain:
                errors.append(f"{FILE}: sessions.{s}: its parents loop ({' -> '.join(chain + [str(cur)])})")
                break
            chain.append(str(cur))
            nxt = sessions.get(cur)
            cur = _name(nxt.get("parent")) if isinstance(nxt, dict) else None
    return errors


def _name(value) -> str | None:
    """A declared name, or None for anything else (a list, a number: check reports it)."""
    return value if isinstance(value, str) else None


def _names(value) -> list[str]:
    """A declared list of names, or [] for anything else (check reports it)."""
    return list(value) if isinstance(value, list) and all(isinstance(v, str) for v in value) else []


def _last_key(text: str) -> str:
    keys = re.findall(r"^([A-Za-z_]\w*)\s*:", text, re.M)
    return keys[-1] if keys else ""


def load(root: Path | None = None, *, path: Path | None = None, today: date | None = None) -> Model:
    """The hierarchy: allow-rules.txt, then permissions.yaml (``path``, else :func:`permissions_file`), checked. Loading
    never fails: what is wrong is in ``errors``."""
    f = path or permissions_file(root)
    model = Model(f, engine_file(f), registry=projects.load(root), today=today or date.today())
    try:
        _load_into(model, f)
    except Exception as exc:   # a shape no check foresaw: reported, never raised
        model.errors.append(f"{FILE}: cannot be read as a hierarchy ({type(exc).__name__}: {exc})")
    return model


def _load_into(model: Model, f: Path | None) -> None:
    text = ""
    if f and f.is_file():
        try:
            text = f.read_text(encoding="utf-8")
            data = graph.load_yaml(text) or {}
        except Exception as exc:
            model.errors.append(f"{f.name}: not readable YAML ({exc})")
            data = {}
        if not isinstance(data, dict):
            model.errors.append(f"{f.name}: a mapping of {', '.join(SECTIONS)}")
            data = {}
        model.data = data
    model.categories, errs = categories(model.data)
    model.errors += errs + _sections_errors(model)
    if text and "rules" in model.data and _last_key(text) != "rules":
        model.errors.append(f"{FILE}: rules is the file's last key (brain permissions grant appends to it)")
    model.rules = read_engine(model.engine_file)
    for c in model.categories:
        model.rules += [Rule(d, "deny", "global", why=c.why or f"never grantable: {c.name}",
                             where=f"{FILE} never.{c.name}") for d in c.deny]
    decl = _declared(model)
    entries = model.data.get("rules")
    if entries is not None and not isinstance(entries, list):
        model.errors.append(f"{FILE}: rules is a list, one {{allow|ask|deny: RULE, ...}} per line")
        entries = []
    for i, entry in enumerate(entries or []):
        rule, errs = _entry_errors(entry, f"{FILE} rules[{i}]", model, decl)
        model.errors += errs
        if rule is not None:
            model.rules.append(rule)
    seen: dict[tuple, str] = {}
    for r in model.rules:
        model.errors += rule_errors(r, model.categories)
        keys = [(r.verdict, r.level, r.scope.lower(), a) for a in atoms(r.text)]
        dup = next((seen[k] for k in keys if k in seen), "")
        if dup:
            model.errors.append(f"{r.where}: {r.verdict} {r.text} is already declared at {dup}")
        for k in keys:
            seen.setdefault(k, r.where)
        if r.while_ and model.status(r.while_) is None:
            model.errors.append(f"{r.where}: while {r.while_}: no such item in the registered projects' stores")


def check(root: Path | None = None) -> list[str]:
    """What is wrong in the hierarchy (brain check --all, brain permissions check): [] when there is no file and
    allow-rules.txt is clean. In read mode a newer brain's keys are notes on stderr, not errors."""
    model = load(root)
    for note in model.notes:
        print(f"brain: note: {note}", file=sys.stderr)
    return model.errors


# --- a context: the levels that apply to one project, machine and session --------------------------------------

def this_machine() -> str:
    import socket  # here, not at the top: it costs the owner guard's hook ~9 ms to import
    return os.environ.get("COMPUTERNAME") or socket.gethostname() or ""


@dataclass
class Context:
    project: str = ""
    machine: str = ""
    profile: str = ""
    tenant: str = ""
    sessions: list[str] = field(default_factory=list)   # a sub-session's chain, the root session first

    def applies(self, r: Rule) -> bool:
        if r.level in ("engine", "global"):
            return True
        if r.level == "machine":
            return r.scope.lower() == self.machine.lower()
        if r.level == "local":
            return r.scope.lower() == f"{self.project}@{self.machine}".lower()
        if r.level == "session":
            return r.scope in self.sessions
        return r.scope == {"profile": self.profile, "tenant": self.tenant, "project": self.project}[r.level]


def context(model: Model, project: str = "", machine: str = "", session: str = "") -> Context:
    machine = machine or this_machine()
    entry = next((e for m, e in model.section("machines").items() if str(m).lower() == machine.lower()), None)
    profile = (_name(entry.get("profile")) or "") if isinstance(entry, dict) else ""
    sessions, cur = [], session
    while cur and cur not in sessions:
        sessions.insert(0, cur)
        s = model.section("sessions").get(cur)
        if not project and isinstance(s, dict) and _name(s.get("project")):
            project = s["project"]
        cur = _name(s.get("parent")) if isinstance(s, dict) else None
    tenant = next((str(t) for t, e in model.section("tenants").items()
                   if isinstance(e, dict) and project in _names(e.get("projects"))), "")
    return Context(project, machine, profile, tenant, sessions)


def _specific(r: Rule) -> int:
    return LEVELS.index(r.level)


def effective(model: Model, ctx: Context) -> list[dict]:
    """Each Claude Code rule that applies in ``ctx``: its winning verdict (deny, then ask, then allow), the levels that
    declare it (the most specific first), the declarations it overrides, and the deny or ask rules that shadow an
    allow."""
    by_atom: dict[str, list[Rule]] = {}
    order: dict[str, int] = {}
    for i, r in enumerate(model.rules):
        if ctx.applies(r) and not model.expired(r):
            for a in atoms(r.text):
                by_atom.setdefault(a, []).append(r)
                order.setdefault(a, i)
    out = []
    for atom, rs in by_atom.items():
        verdict = min((r.verdict for r in rs), key=VERDICTS.index)
        win = sorted((r for r in rs if r.verdict == verdict), key=_specific, reverse=True)
        out.append({"rule": atom, "verdict": verdict, "sources": [_src(r) for r in win],
                    "overridden": [_src(r) for r in sorted(rs, key=_specific, reverse=True) if r.verdict != verdict],
                    "shadowed_by": []})
    stricter = [e for e in out if e["verdict"] != "allow"]
    for e in out:
        if e["verdict"] == "allow":
            tool, spec = parse(e["rule"]) or (e["rule"], None)
            probe = (spec or "").removesuffix(" *").replace("*", "x")
            e["shadowed_by"] = [s["rule"] for s in stricter if matches(s["rule"], tool, probe)]
    return sorted(out, key=lambda e: (VERDICTS.index(e["verdict"]), -LEVELS.index(e["sources"][0]["level"]),
                                      order[e["rule"]]))


def _src(r: Rule) -> dict:
    d = {"level": r.level, "scope": r.scope, "rule": r.text, "verdict": r.verdict, "where": r.where}
    for k, v in (("why", r.why), ("by", r.by), ("from", r.origin), ("date", r.date), ("asked_by", r.asked_by),
                 ("for", r.for_), ("until", r.until), ("while", r.while_)):
        if v:
            d[k] = v
    d["duration"] = r.duration()
    return d


def decide(model: Model, ctx: Context, call: str) -> dict:
    """What a call gets in ``ctx``, as Claude Code decides it: deny when one part matches a deny rule, ask when one
    matches an ask rule, allow only when every part matches an allow rule, else no rule (the permission mode decides:
    a prompt, or the auto mode classifier)."""
    tool, text = parse_call(call)
    rules = [(a, r) for r in model.live() if ctx.applies(r) for a in atoms(r.text)]
    verdicts, detail = [], []
    for part in parts(tool, text):
        hits = [(a, r) for a, r in rules if matches(a, tool, part)]
        v = next((v for v in VERDICTS if any(r.verdict == v for _, r in hits)), "")
        if v == "allow" and tool in SHELLS and ("`" in part or "$(" in part):
            v = ""   # a command substitution runs a command no rule here was matched against
        verdicts.append(v)
        detail.append({"part": part, "verdict": v or "none",
                       "rules": [{"rule": a, **_src(r)} for a, r in sorted(hits, key=lambda h: _specific(h[1]),
                                                                            reverse=True)]})
    if "deny" in verdicts:
        verdict = "deny"
    elif "ask" in verdicts:
        verdict = "ask"
    elif verdicts and all(v == "allow" for v in verdicts):
        verdict = "allow"
    else:
        verdict = "none"
    return {"call": call, "tool": tool, "verdict": verdict, "parts": detail,
            "never": never_category(text, model.categories)}


# --- adapters: rendering the levels into an agent's settings ---------------------------------------------------

class Adapter:
    """What an agent's adapter implements to render the hierarchy into the agent's own settings. Only Claude Code's
    is built; another agent (Codex, Gemini CLI, an MCP client...) declares its scopes and translates the reference
    rules into its own, and a rule it cannot express is reported as not rendered, never widened into a broader one.

    - ``scopes``: {scope: the model levels it holds}, from the broadest; :meth:`targets` gives each scope's files;
    - :meth:`translate`: a reference rule -> the agent's rules ([] when it cannot say it);
    - :meth:`read` and :meth:`write`: the rules a target holds, by verdict, and adding the missing ones (never
      removing one: a rule the user added through the agent's own interface stays)."""
    name = ""
    scopes: dict[str, tuple[str, ...]] = {}

    def translate(self, text: str) -> list[str]:
        raise NotImplementedError

    def targets(self, scope: str, model: Model, ctx: Context, repo: Path | None = None) -> list[Path]:
        raise NotImplementedError

    def read(self, path: Path) -> dict[str, list[str]]:
        raise NotImplementedError

    def write(self, path: Path, missing: dict[str, list[str]]) -> None:
        raise NotImplementedError


def claude_home() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


class ClaudeCode(Adapter):
    """Claude Code's settings: the user file, each repo's shared and local project files, a --settings file."""
    name = "claude"
    scopes = {"user": ("engine", "global", "profile", "machine"), "project": ("tenant", "project"),
              "local": ("local",), "session": ("session",)}

    def translate(self, text: str) -> list[str]:
        p = parse(text)
        if p and p[0] == SHELL:
            return [t if p[1] is None else f"{t}({p[1]})" for t in SHELLS]
        return [text]

    def targets(self, scope: str, model: Model, ctx: Context, repo: Path | None = None) -> list[Path]:
        if scope == "user":
            return [claude_home() / "settings.json"]
        if scope == "session":
            return []
        name = "settings.json" if scope == "project" else "settings.local.json"
        if repo is not None:
            return [Path(repo) / ".claude" / name]
        proj = model.registry.get(ctx.project)
        if proj is None:
            return []
        try:   # a project that shares its root spans no repo: its sessions read the root's settings
            folders = [r.path for r in projects.repos_of(proj)] or [proj.root]
        except projects.RepoError:
            folders = [proj.root]
        return [Path(f) / ".claude" / name for f in folders]

    def read(self, path: Path) -> dict[str, list[str]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {v: [] for v in VERDICTS}
        perms = data.get("permissions") if isinstance(data, dict) else None
        perms = perms if isinstance(perms, dict) else {}
        return {v: [x for x in perms[v] if isinstance(x, str)] if isinstance(perms.get(v), list) else []
                for v in VERDICTS}

    def write(self, path: Path, missing: dict[str, list[str]], expired: dict[str, list[str]] | None = None) -> None:
        """Add the missing rules; take out the expired ones (rules the hierarchy declared, and only those). The file
        is Claude Code's (a foreign file, brain.stateio): one that cannot be read, is not JSON or not an object is
        refused, never replaced; one Claude Code wrote meanwhile is refused (run again); its other keys are kept; it
        is backed up first: a file of a git work tree (a project's ``.claude/settings.json``, its untracked
        ``settings.local.json``) under ``$BRAIN_HOME/backup/<project>-<key>/`` (:func:`home_backup_dir`, the last
        ``stateio.HOME_BACKUPS`` copies), so that git status stays clean; an untracked ``.bak`` an older engine left
        beside it moves there first, as an older copy (:func:`adopt_old_backup`; a tracked one stays where it is); any
        other file (``~/.claude/settings.json``) beside itself (``settings.json.bak``). Then it is written
        atomically."""
        try:
            data, seen = stateio.read_foreign(path)
        except stateio.StateError as exc:
            raise PermissionsError(str(exc)) from None
        perms = data.setdefault("permissions", {})
        if not isinstance(perms, dict):
            raise PermissionsError(f"{path}: permissions is not an object: fix it by hand first")
        for v in ("allow", "ask", "deny"):
            if perms.get(v) is not None and not isinstance(perms[v], list):
                raise PermissionsError(f"{path}: permissions.{v} is not a list: fix it by hand first")
        for v in ("allow", "ask", "deny"):
            if missing.get(v):
                perms[v] = list(perms.get(v) or []) + missing[v]
            if (expired or {}).get(v) and perms.get(v):
                perms[v] = [x for x in perms[v] if x not in expired[v]]
        write_backed_up(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", seen)


def write_backed_up(path: Path, text: str, seen: bytes | None) -> None:
    """A settings file written through brain.stateio, backed up first: under ``$BRAIN_HOME/backup`` for a file of a
    git work tree (an old ``.bak`` beside it adopted first, so this write's copy is the newest and the prune keeps
    the last 10), beside itself otherwise. UTF-8 without BOM, as Claude Code writes it."""
    home = home_backup_dir(path)
    if home is not None:
        adopt_old_backup(path, home)
    try:
        stateio.write_foreign(path, text, seen, backup_dir=home)
    except stateio.StateError as exc:
        raise PermissionsError(str(exc)) from None


def work_tree(path: Path) -> Path | None:
    """The top of the git work tree ``path`` lies in (the nearest parent with a ``.git`` folder or file), else None."""
    return next((p for p in Path(path).resolve().parents if (p / ".git").exists()), None)


def in_work_tree(path: Path) -> bool:
    """Whether ``path`` lies in a git work tree (a ``.git`` folder or file in one of its parents)."""
    return work_tree(path) is not None


def _safe(name: str, default: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-") or default


def _key(p: Path) -> str:
    """Eight hex digits of a folder's resolved path (its case folded where the system folds it): two repos of the same
    folder name never share a backup folder."""
    return hashlib.sha256(os.path.normcase(str(p.resolve())).encode("utf-8")).hexdigest()[:8]


def _git_dirs(top: Path) -> tuple[Path, Path]:
    """(the work tree's git dir, the repo's common dir), absolute; both ``top/.git`` when git cannot say."""
    try:
        out = subprocess.run(["git", "-C", str(top), "rev-parse", "--path-format=absolute", "--git-dir",
                              "--git-common-dir"], capture_output=True, text=True, timeout=10,
                             stdin=subprocess.DEVNULL).stdout.split("\n")
    except (OSError, subprocess.SubprocessError):
        out = []
    if len(out) >= 2 and out[0].strip() and out[1].strip():
        return Path(out[0].strip()), Path(out[1].strip())
    return top / ".git", top / ".git"


def home_backup_dir(path: Path) -> Path | None:
    """Where a file of a git work tree is backed up before a write: ``$BRAIN_HOME/backup/<project>-<key>/<its folder
    in the work tree>``. The project is named by its main checkout's folder (a bare repo's ``<name>.git``, else the
    work tree's own folder: a submodule's) and keyed by eight hex digits of its git common dir's path, so two repos of
    the same name never share one; a linked worktree's copies go under ``worktrees/<folder>-<key>``. None outside a
    work tree: the file is backed up beside itself."""
    top = work_tree(path)
    if top is None:
        return None
    git_dir, common = (p.resolve() for p in _git_dirs(top))
    label = common.parent.name if common.name == ".git" else common.stem if common.suffix == ".git" else top.name
    base = paths.backup_dir() / f"{_safe(label, 'repo')}-{_key(common)}"
    if git_dir != common:   # a linked worktree (of a checkout or of a bare repo)
        base = base / "worktrees" / f"{_safe(top.name, 'worktree')}-{_key(top)}"
    return base / Path(path).resolve().parent.relative_to(top)


def adopt_old_backup(path: Path, home: Path) -> Path | None:
    """The ``<name>.bak`` an older engine left beside a work tree's file, moved under ``home`` as a copy (its time as
    its stamp, so it sorts before the copy the write takes next), so that git status stays clean; left where it is
    when git tracks it (or cannot say). The copy made, None when nothing moved."""
    old = Path(path).with_name(Path(path).name + stateio.BACKUP)
    if not old.is_file():
        return None
    try:
        tracked = subprocess.run(["git", "-C", str(old.parent), "ls-files", "--error-unmatch", "--", old.name],
                                 capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if tracked.returncode != 1:   # tracked (0), or git cannot say (another code): left as it is
        return None
    try:
        stamp = datetime.fromtimestamp(old.stat().st_mtime, timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        home.mkdir(parents=True, exist_ok=True)
        dst = home / f"{Path(path).name}.{stamp}{stateio.BACKUP}"
        if not dst.exists():
            os.replace(old, dst)
            return dst
        old.unlink()
    except OSError:
        return None
    return None


ADAPTERS: dict[str, Adapter] = {"claude": ClaudeCode()}


def wanted(model: Model, ctx: Context, scope: str, adapter: Adapter | None = None) -> dict[str, list[str]]:
    """The rules a scope of the adapter renders in ``ctx``, by verdict, translated, in declaration order."""
    adapter = adapter or ADAPTERS["claude"]
    out: dict[str, list[str]] = {v: [] for v in VERDICTS}
    for r in model.live():
        if r.level in adapter.scopes[scope] and ctx.applies(r):
            for t in adapter.translate(r.text):
                if t not in out[r.verdict]:
                    out[r.verdict].append(t)
    return out


def expired_rules(model: Model, ctx: Context, scope: str, adapter: Adapter | None = None) -> dict[str, list[str]]:
    """The rules of a scope that expired in ``ctx`` (until past, while closed), translated, minus those a live
    declaration still wants: what a render takes out of the settings it wrote them into."""
    adapter = adapter or ADAPTERS["claude"]
    want = wanted(model, ctx, scope, adapter)
    out: dict[str, list[str]] = {v: [] for v in VERDICTS}
    for r in model.rules:
        if r.level in adapter.scopes[scope] and ctx.applies(r) and model.expired(r):
            out[r.verdict] += [t for t in adapter.translate(r.text) if t not in want[r.verdict] and t not in out[r.verdict]]
    return out


def _production(path: Path) -> str | None:
    """The production checkout that holds ``path``, the path and the roots compared as written and resolved (a
    junction or a link to a checkout is the checkout)."""
    from . import guards
    roots = guards.production_roots()
    real = [os.path.realpath(r) for r in roots]
    return guards.in_production(str(path), roots) or guards.in_production(os.path.realpath(str(path)), real)


def plan(model: Model, ctx: Context, scope: str, *, repo: Path | None = None, adapter: Adapter | None = None) -> list[dict]:
    """For each target file of the scope: the rules it should hold, the missing ones, the ones no level declares
    (``unmanaged``), and why it cannot be written here (``refused``)."""
    adapter = adapter or ADAPTERS["claude"]
    want, gone = wanted(model, ctx, scope, adapter), expired_rules(model, ctx, scope, adapter)
    out = []
    for path in adapter.targets(scope, model, ctx, repo):
        have = adapter.read(path)
        missing = {v: [x for x in want[v] if x not in have[v]] for v in VERDICTS}
        expired = {v: [x for x in have[v] if x in gone[v]] for v in VERDICTS}
        unmanaged = {v: [x for x in have[v] if x not in want[v] and x not in gone[v]] for v in VERDICTS}
        refused = ""
        if scope == "user":
            refused = "install.ps1 -Apply writes the user settings (the owner's)"
        elif _production(path.parent.parent):   # --repo included: the guards do not see what this command writes
            refused = (f"{path.parent.parent} is a production checkout: render into a worktree of it (--repo), then "
                       "a PR there")
        out.append({"file": str(path), "scope": scope, "levels": list(adapter.scopes[scope]),
                    "wanted": want, "missing": missing, "expired": expired, "unmanaged": unmanaged,
                    "present": sum(len(want[v]) - len(missing[v]) for v in VERDICTS),
                    "total": sum(len(want[v]) for v in VERDICTS), "refused": refused})
    return out


def render(model: Model, ctx: Context, scope: str, *, repo: Path | None = None, write: bool = False,
           adapter: Adapter | None = None) -> list[dict]:
    """:func:`plan`, then, with ``write``, the missing rules added to each file that may be written here and the
    expired ones taken out."""
    adapter = adapter or ADAPTERS["claude"]
    plans = plan(model, ctx, scope, repo=repo, adapter=adapter)
    if not write:
        return plans
    if model.errors:
        raise PermissionsError(f"{len(model.errors)} error(s) in the hierarchy (brain permissions check): "
                               "nothing is rendered")
    for p in plans:
        p["written"] = False
        if p["refused"] or not (any(p["missing"].values()) or any(p["expired"].values())):
            continue
        adapter.write(Path(p["file"]), p["missing"], p["expired"])
        p["written"] = True
    return plans


def session_settings(model: Model, ctx: Context) -> dict:
    """A session's rules as a file for ``claude --settings`` (above the user and project files, below managed)."""
    want = wanted(model, ctx, "session")
    return {"permissions": {v: want[v] for v in ("allow", "ask", "deny") if want[v]}}


def write_session(model: Model, ctx: Context, out: Path, adapter: Adapter | None = None) -> int:
    """A session's rules added to the file ``out`` (created when missing, never emptied: like every render, it only
    adds), refused when the hierarchy has errors, for the user settings file, and in a production checkout. The number
    of rules added."""
    adapter = adapter or ADAPTERS["claude"]
    if model.errors:
        raise PermissionsError(f"{len(model.errors)} error(s) in the hierarchy (brain permissions check): nothing is "
                               "rendered")
    target = Path(os.path.realpath(out))
    if target == Path(os.path.realpath(claude_home() / "settings.json")):
        raise PermissionsError(f"{out} is the user settings file: install.ps1 -Apply writes it (the owner's)")
    if _production(target.parent):
        raise PermissionsError(f"{out} is in a production checkout: write it elsewhere")
    want, have = wanted(model, ctx, "session", adapter), adapter.read(target)
    gone = expired_rules(model, ctx, "session", adapter)
    missing = {v: [x for x in want[v] if x not in have[v]] for v in VERDICTS}
    expired = {v: [x for x in have[v] if x in gone[v]] for v in VERDICTS}
    if any(missing.values()) or any(expired.values()) or not target.is_file():
        adapter.write(target, missing, expired)
    return sum(len(v) for v in missing.values())


# --- the view --------------------------------------------------------------------------------------------------

GUARD_TEXT = {"production": "no tool edit, git change or shell write in a production checkout",
              "attribution": "no AI attribution line in a commit or PR text",
              "secrets": "no key in what a commit records",
              "owner": "no command of a never-grantable category (its deny rules, and the shapes the engine knows); "
                       "a refusal goes to the owner's queue with its exact command",
              "power": "no machine power, boot, Wake-on-LAN or node action, no cluster write outside the brain "
                       "namespace, locally or over ssh"}


def show(model: Model, ctx: Context) -> dict:
    """The effective list of ``ctx``, its sources, the guards, the never-grantable categories, and how each target
    file stands (rules present, missing, and held but declared by no level)."""
    from . import guards
    proj = model.registry.get(ctx.project)
    prod = [str(p) for p in proj.production] if proj else []
    files = []
    for scope in ("user", "project", "local"):
        if scope != "user" and proj is None:
            continue
        for p in plan(model, ctx, scope):
            if scope != "user" and not p["total"] and not any(p["unmanaged"].values()):
                continue
            files.append({k: p[k] for k in ("file", "scope", "missing", "expired", "unmanaged", "present", "total")})
    for f in files:
        f["unmanaged_notes"] = {x: n for v in VERDICTS for x in f["unmanaged"][v]
                                if v == "allow" and (n := _note(x, model.categories))}
    entries = effective(model, ctx)
    return {"project": ctx.project, "machine": ctx.machine, "profile": ctx.profile, "tenant": ctx.tenant,
            "sessions": ctx.sessions, "file": str(model.file) if model.file else None,
            "engine_file": str(model.engine_file) if model.engine_file else None,
            "counts": {v: sum(1 for e in entries if e["verdict"] == v) for v in VERDICTS},
            "rules": entries, "files": files,
            "expired": [dict(_src(r), reason=model.expired(r)) for r in model.rules
                        if ctx.applies(r) and model.expired(r)],
            "guards": [{"guard": g, "what": GUARD_TEXT.get(g, ""), **({"checkouts": prod} if g == "production"
                                                                     else {})} for g in guards.GUARDS],
            "never": [{"category": c.name, "why": c.why, "source": c.source, "deny": c.deny}
                      for c in model.categories],
            "errors": model.errors}


def _note(rule: str, cats: list[Category]) -> str:
    bits = []
    cat = never_rule(rule, cats)
    if cat:
        bits.append(f"never grantable: {cat}")
    why = broad(rule)
    if why:
        bits.append(f"broad: {why}")
    return "; ".join(bits)


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def render_text(data: dict, width: int = 118) -> list[str]:
    where = data["project"] or "no project"
    head = (f"permissions of {where} on {data['machine'] or '?'} (profile {data['profile'] or '-'}, tenant "
            f"{data['tenant'] or '-'}" + (f", session {' > '.join(data['sessions'])}" if data["sessions"] else "")
            + f"): {data['counts']['deny']} deny, {data['counts']['ask']} ask, {data['counts']['allow']} allow")
    lines = [head]
    for g in data["guards"]:
        extra = f" ({len(g['checkouts'])} production checkout(s) of {where})" if g.get("checkouts") else ""
        lines.append(_cut(f"  hard deny  guard {g['guard']}: {g['what']}{extra}; no rule lifts it", width))
    lines.append(_cut("  never      " + ", ".join(n["category"] for n in data["never"])
                      + ": no level may allow them (the owner's alone)", width))
    for e in data["rules"]:
        src = e["sources"][0]
        label = src["level"] + (f" {src['scope']}" if src["scope"] else "")
        more = f" (+{len(e['sources']) - 1})" if len(e["sources"]) > 1 else ""
        flag = ""
        if e["overridden"]:
            flag += f"; overrides {', '.join(o['verdict'] + ' at ' + o['level'] for o in e['overridden'])}"
        if e["shadowed_by"]:
            flag += f"; shadowed by {', '.join(e['shadowed_by'])}"
        lines.append(_cut(f"  {e['verdict']:<6} {e['rule']:<44} {label}{more}  {src['where']}{flag}", width))
    if not data["rules"]:
        lines.append("  (no rule: every call follows the permission mode, a prompt or the auto mode classifier)")
    for x in data.get("expired", []):
        label = x["level"] + (f" {x['scope']}" if x["scope"] else "")
        lines.append(_cut(f"  expired {x['verdict']} {x['rule']} at {label} ({x['reason']}): taken out at the next "
                          "render", width))
    for f in data["files"]:
        miss = sum(len(v) for v in f["missing"].values())
        unm = [x for v in VERDICTS for x in f["unmanaged"][v]]
        text = f"  {f['scope']:<7} {f['file']}: {f['present']} of {f['total']} rule(s) present"
        how = "install.ps1 -Apply" if f["scope"] == "user" else "brain permissions render --write"
        text += f", {miss} missing ({how})" if miss else ""
        gone = sum(len(v) for v in f.get("expired", {}).values())
        text += f", {gone} expired to take out ({how})" if gone else ""
        lines.append(text)   # a path is never cut
        for x in unm:
            note = f["unmanaged_notes"].get(x, "")
            lines.append(_cut("           held, declared by no level" + (f" [{note}]" if note else "") + f": {x}",
                              width))
    for e in data["errors"]:
        lines.append(f"  error: {e}")
    return lines


def explain(model: Model, ctx: Context, text: str) -> dict:
    """Where a rule comes from at every level (not only the ones of ``ctx``), what it falls in, and what a call
    written that way gets in ``ctx``."""
    keys = set(atoms(text)) if parse(text) else set()
    decls = [dict(_src(r), applies=ctx.applies(r), expired=model.expired(r)) for r in model.rules
             if keys & set(atoms(r.text))]
    plugin = config.claude(config.load())["plugin"]   # the core plugin, whose guards these are
    return {"rule": text, "declared": sorted(decls, key=lambda d: LEVELS.index(d["level"])),
            "never": never_category(text, model.categories), "broad": broad(text) if parse(text) else "",
            "call": decide(model, ctx, text), "guards": f"the {plugin} guards judge the call apart from the rules: "
            "no allow rule lifts their deny (brain.guards)"}


def explain_text(d: dict, width: int = 118) -> list[str]:
    lines = [f"{d['rule']}:"]
    for x in d["declared"]:
        label = x["level"] + (f" {x['scope']}" if x["scope"] else "")
        lines.append(_cut(f"  {x['verdict']:<6} at {label} ({x['where']})" + ("" if x["applies"] else
                                                                            ", not in this context"), width))
        for k in ("why", "by", "from", "date"):
            if x.get(k):
                lines.append(_cut(f"         {k}: {x[k]}", width))
    if not d["declared"]:
        lines.append("  declared at no level" if parse(d["rule"]) else "  not a rule: read as a call")
    if d["never"]:
        lines.append(f"  never grantable: {d['never']} (the owner's alone; an allow rule is refused at every level)")
    if d["broad"]:
        lines.append(f"  broad: {d['broad']}")
    c = d["call"]
    lines.append(_cut(f"  as a call ({c['tool']}): {c['verdict']}" + ("" if c["verdict"] != "none" else
                      " (the permission mode decides: a prompt, or the auto mode classifier)"), width))
    if len(c["parts"]) > 1:
        lines.append("  a compound command: allowed only when every part is")
    for p in c["parts"]:
        rules = ", ".join(f"{r['verdict']} {r['rule']} at {r['level']}" for r in p["rules"]) or "no rule"
        lines.append(_cut(f"    {p['verdict']:<5} {p['part']}: {rules}", width))
    lines.append(f"  guards: {d['guards']}")
    return lines


# --- grants: a permission task becomes a proposed rule, in a branch, reviewed by PR ----------------------------

SHELL_WORDS = {"for", "do", "done", "while", "until", "if", "then", "elif", "else", "fi", "case", "esac", "in",
               "!", "{", "}", "foreach", "time"}


def propose(call: str) -> list[dict]:
    """Narrow rules for a denied call (each part of a compound command its own): the program and its first word that is
    not an option, with a trailing wildcard; a part that is only a cd needs none."""
    tool, text = parse_call(call)
    if tool == "WebFetch":
        m = re.match(r"^\w+://([^/:?#]+)", text.strip())
        return [{"part": text, "rule": f"WebFetch(domain:{m[1]})" if m else "", "note": "" if m else "no host"}]
    if tool not in SHELLS:
        return [{"part": text, "rule": tool, "note": f"no narrower form: {tool} alone allows every {tool} call"}]
    out = []
    ps = parts(tool, text)
    for part in ps:
        words = part.split()
        while words and (re.match(r"^\$?[A-Za-z_]\w*=", words[0]) or words[0] in SHELL_WORDS):
            words = words[1:]
        if not words:
            continue
        prog = words[0]
        if _prog(prog) in ("cd", "chdir", "pushd", "popd", "set-location", "sl", "push-location", "pop-location"):
            out.append({"part": part, "rule": "", "note": "a cd: run the command with -C or from its folder"})
            continue
        sub = next((w for w in words[1:2] if not w.startswith("-") and not re.search(r"[\\/$\"'*]", w)), "")
        rule = f"{tool}({prog} {sub} *)" if sub else f"{tool}({prog} *)"
        note = broad(rule)
        if not note and len(words) > 1 and not sub:
            note = "narrow it by hand: its first argument is an option or a path"
        out.append({"part": part, "rule": rule, "note": note})
    if len(ps) > 1:
        for p in out:
            p["note"] = (p["note"] + "; " if p["note"] else "") + \
                "a compound command asks unless every part is allowed: run the parts apart, or grant each"
    return out


def _flow(entry: dict) -> str:
    return "  - {" + ", ".join(f"{k}: {graph.fmt(v)}" for k, v in entry.items()) + "}"


def grant(root: Path | None, *, rule: str, verdict: str = "allow", selectors: dict | None = None, why: str,
          by: str = "", origin: str = "", denial: str = "", today: str | None = None, dry_run: bool = False,
          path: Path | None = None, until: str = "", days: int = 0, while_: str = "", asked_by: str = "",
          for_: list | None = None) -> tuple[str, Path]:
    """Append a rule to permissions.yaml's ``rules``, checked as every level is: never a rule in a never-grantable
    category (nor one for a denied call that falls in one, ``denial``), never a broad allow, never twice. The line
    and the file; the PR that carries it is its review."""
    model = load(root, path=path)
    if model.file is None:
        raise PermissionsError(f"no {FILE} (next to the registry, or ${ENV}): create it first")
    if model.errors:
        raise PermissionsError(f"{len(model.errors)} error(s) in the hierarchy first (brain permissions check)")
    if verdict not in VERDICTS:
        raise PermissionsError(f"a verdict is allow, ask or deny ({verdict!r})")
    if verdict == "allow" and denial:
        cat = never_category(denial, model.categories)
        if cat:
            raise PermissionsError(f"the denied call falls in {cat}, which only the owner does: never granted (the "
                                   "owner does it, then brain queue done)")
    entry = {verdict: rule.strip()}
    entry.update({k: v for k, v in (selectors or {}).items() if v})
    entry["why"] = why.strip()
    day = today or date.today().isoformat()
    if days:
        until = (date.fromisoformat(day) + timedelta(days=days)).isoformat()
    for k, v in (("by", by), ("from", origin), ("asked_by", asked_by), ("for", list(for_ or [])), ("until", until),
                 ("while", while_), ("date", day)):
        if v:
            entry[k] = v
    decl = _declared(model)
    new, errors = _entry_errors(entry, f"{FILE} rules[{len(model.data.get('rules') or [])}]", model, decl)
    if new is not None:
        errors += rule_errors(new, model.categories)
        mine = set(atoms(new.text))
        for r in model.rules:   # the same rule at its level, or at one that applies everywhere
            same = r.level in ("engine", "global") or (r.level, r.scope.lower()) == (new.level, new.scope.lower())
            if r.verdict == new.verdict and same and mine & set(atoms(r.text)):
                errors.append(f"{new.verdict} {new.text} is already declared at {r.where}")
                break
    if errors:
        raise PermissionsError("; ".join(errors))
    line = _flow(entry)
    if dry_run:
        return line, model.file
    raw = model.file.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    if "rules" not in model.data:
        raw = raw.rstrip("\r\n") + nl + "rules:" + nl
    text = raw if raw.endswith(("\n", "\r")) else raw + nl
    text += line + nl
    try:
        after = graph.load_yaml(text) or {}
    except Exception:
        after = {}
    before = model.data.get("rules") or []
    if (after.get("rules") or [])[:-1] != before or (after.get("rules") or [None])[-1] != entry:
        raise PermissionsError(f"{FILE}: appending the rule would change more than its line (is rules the last key, "
                               "in block style?)")
    model.file.write_bytes(text.encode("utf-8"))
    return line, model.file


def find_denial(perm: str, days: int = 30) -> dict | None:
    """A permission task of brain queue (a denied call of the last ``days`` days), by its perm-... id."""
    from . import queue
    return next((d for d in queue.scan(days)["denials"] if d["id"] == perm), None)


# --- requests: what agents asked for, and what was granted (the cockpit's permissions panel reads them) ----------

REQUEST_SORTS = ("unblocks", "age", "project", "status")


def requests(model: Model, projects_list=None, *, only=None, days: int = 7, today: date | None = None,
             scanned: dict | None = None, transcripts: bool = True) -> list[dict]:
    """Every permission request with its scope, reason, items and milestones, what it unblocks, the sessions that
    asked, its evidence (the denied call), the narrow rules proposed, its duration and its status: the permission
    entries of brain queue (denied calls of the last ``days`` days, DDRs of kind permission, item props naming an
    approval), then the rules granted for a request that left the queue (their provenance). pending: no rule answers
    it; granted: a live rule's ``from`` names it; expired: only expired rules do. ``only``: one project (its group
    alone); ``scanned``: a brain queue scan already made (the cockpit's)."""
    from . import queue
    plist = list(projects_list if projects_list is not None else model.registry.values())
    data = queue.collect(plist, only=only, kinds=("permission",), days=days, today=today, with_graph=False,
                         transcripts=transcripts, scanned=scanned)
    granted: dict[str, list[Rule]] = {}
    for r in model.rules:
        if r.origin:
            granted.setdefault(r.origin, []).append(r)
    out, seen = [], set()
    for d in data:
        project = "" if d["project"] == queue.OUTSIDE else d["project"]
        if only is not None and not project:
            continue
        for e in d["entries"]:
            unblocked = list(e.get("unblocked") or [])
            denial = e.get("source") == "denial"
            out.append(_request(model, granted.get(e["id"], []), id=e["id"], source=e.get("source", ""),
                                project=project, reason=e.get("detail") or e.get("title", ""),
                                evidence=e.get("title", "") if denial else "",
                                items=[i for i in unblocked if not i.startswith("ms-")],
                                milestones=[i for i in unblocked if i.startswith("ms-")],
                                unblocks=e.get("unblocks", 0), sessions=list(e.get("sessions") or []),
                                since=e.get("since", ""), age_days=e.get("age_days"), count=e.get("count", 1),
                                proposals=propose(e["title"]) if denial else [], how=e.get("how", "")))
            seen.add(e["id"])
    pname = getattr(only, "name", "") if only is not None else ""
    for origin, rules in granted.items():
        if origin in seen:
            continue
        r = rules[0]
        rproject = r.scope.split("@")[0] if r.level in ("project", "local") else ""
        if pname and rproject not in ("", pname):
            continue
        fors = [x for rr in rules for x in rr.for_]
        out.append(_request(model, rules, id=origin, source="rule", project=rproject, reason=r.why, evidence="",
                            items=[i for i in fors if not i.startswith("ms-")],
                            milestones=[i for i in fors if i.startswith("ms-")], unblocks=len(fors),
                            sessions=[x.asked_by for x in rules if x.asked_by], since=r.date, age_days=None, count=0,
                            proposals=[], how=""))
    return out


def _request(model: Model, rules: list[Rule], **fields) -> dict:
    live = [r for r in rules if not model.expired(r)]
    status = "granted" if live else "expired" if rules else "pending"
    scope = ("project " + fields["project"]) if fields["project"] else "global"
    if rules:
        r = (live or rules)[0]
        scope = r.label()
    return {**fields, "scope": scope, "status": status,
            "duration": "; ".join(dict.fromkeys(r.duration() for r in rules)) if rules else
            "set at the grant: indefinite, --until DATE, --days N, --while ITEM, or the session level",
            "rules": [dict(_src(r), expired=model.expired(r)) for r in rules]}


def select(reqs: list[dict], *, status: str = "", scope: str = "", item: str = "", search: str = "",
           sort: str = "unblocks") -> list[dict]:
    """The requests filtered (status, a scope's start: global, project, project quant, machine...; an item or
    milestone they unblock; a text in their reason, evidence or id) and sorted: unblocks (most first, then oldest),
    age (oldest first), project, status (pending, granted, expired)."""
    out = [r for r in reqs if (not status or r["status"] == status) and (not scope or r["scope"].startswith(scope))
           and (not item or item in r["items"] + r["milestones"])
           and (not search or search.lower() in f"{r['id']} {r['reason']} {r['evidence']}".lower())]
    order = {"pending": 0, "granted": 1, "expired": 2}
    keys = {"unblocks": lambda r: (-r["unblocks"], r["since"] or "9999", r["id"]),
            "age": lambda r: (r["since"] or "9999", r["id"]),
            "project": lambda r: (r["project"] or "~", -r["unblocks"], r["id"]),
            "status": lambda r: (order.get(r["status"], 3), -r["unblocks"], r["id"])}
    return sorted(out, key=keys.get(sort, keys["unblocks"]))


def requests_text(reqs: list[dict], width: int = 118, title: str = "") -> list[str]:
    counts = {s: sum(1 for r in reqs if r["status"] == s) for s in ("pending", "granted", "expired")}
    lines = [f"permission requests{(' of ' + title) if title else ''}: {len(reqs)} ("
             + ", ".join(f"{n} {s}" for s, n in counts.items() if n) + ")" if reqs else
             f"permission requests{(' of ' + title) if title else ''}: none"]
    for r in reqs:
        age = f"{r['age_days']} d" if r["age_days"] is not None else (r["since"] or "-")
        lines.append(_cut(f"  {r['status']:<8} {r['unblocks']:>2}  {age:>5}  {r['scope']:<20} {r['id']}: "
                          f"{r['reason']}", width))
        bits = []
        if r["evidence"]:
            bits.append(r["evidence"])
        if r["items"] or r["milestones"]:
            bits.append("unblocks " + ", ".join(r["items"] + r["milestones"]))
        if r["sessions"]:
            bits.append("asked by " + ", ".join(s[:8] for s in r["sessions"]))
        bits.append("duration: " + r["duration"])
        lines.append(_cut("           " + "; ".join(bits), width))
        rules = list(dict.fromkeys(p["rule"] for p in r["proposals"] if p["rule"] and not broad(p["rule"])))
        if rules:
            more = f" (+{len(rules) - 3})" if len(rules) > 3 else ""
            compound = "; a compound command: every part needs its rule" if len(r["proposals"]) > 1 else ""
            lines.append(_cut(f"           proposals: {', '.join(rules[:3])}{more}{compound}", width))
    return lines
