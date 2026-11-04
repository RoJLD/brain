"""``brain render --target <tool>``: the neutral source (brain.neutral) written as each agent's own files, by one
adapter per tool (wi-brain-neutral-source; spec-brain-plugin §2.7, adapter order AGENTS.md, Cursor, Gemini /
Antigravity, Grok / Hermes decided 2026-10-30; formats checked in each tool's documentation on 2026-11-02).

- **claude**: the owner's Claude marketplace in the brain's own repo: ``.claude-plugin/marketplace.json``, then per
  pack ``plugins/<plugin>/`` with ``.claude-plugin/plugin.json``, ``rules/<file>.md`` (the core plugin's hook injects
  them), ``skills/<procedure>/``, ``.mcp.json`` and the engine's Claude hooks (package data, copied when they live
  elsewhere). It reproduces the hand-written step 1 byte for byte, so its files carry no marker: ``brain check``
  re-renders and refuses a hand edit.
- **agents**: the common base, in the project's repo: ``AGENTS.md``, the project's chain flattened (the global rules,
  each ancestor's, then the project's own CLAUDE.md, nearest last: AGENTS.md readers take the nearest file), the
  memory and decisions pointers; ``.agents/skills/<procedure>/`` for the packs that apply to the project. Claude Code
  reads AGENTS.md only where no CLAUDE.md is (its default), so a Claude session does not get the rules twice.
- **cursor**: the base, then ``.cursor/mcp.json`` (``${env:NAME}``; no default syntax: a default is written as is).
- **gemini** (Gemini CLI): the base, then ``.gemini/settings.json``: ``context.fileName`` reads AGENTS.md, and
  ``mcpServers`` (``httpUrl`` for HTTP, ``url`` for SSE; ``${NAME:-default}`` kept).
- **antigravity**: the base (Antigravity reads AGENTS.md and ``.agents/skills``), then ``.agents/mcp_config.json``
  (``serverUrl``; no SSE; no documented interpolation: a default is written as is).
- **grok** (Grok Build): the base, ``.grok/skills/<procedure>/`` and ``.grok/config.toml`` (``[mcp_servers.<name>]``).
- **hermes** (Hermes Agent): the base; its MCP servers live in ``~/.hermes/config.yaml`` only, so the plan shows the
  ``mcp_servers:`` lines to add there by hand.

What a tool cannot carry is said in the plan, never simulated (hooks are Claude Code's). JSON settings files are
merged: only the entries the source names are written, the rest of the file is left alone. A file the render would
replace that it did not write (no marker) is ``foreign``: not written without ``--force``. ``--write`` writes into the
brain's repo and the project's repo (never a production checkout: render a worktree of it with ``--repo``) and never
into the home folder.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import neutral
from .neutral import Flow

TARGETS = ("claude", "agents", "cursor", "gemini", "antigravity", "grok", "hermes")
MARK = "Rendered by brain render from the neutral source: edit the source, then render again; never this file."
BASES = ("brain", "repo", "user")


@dataclass
class Output:
    rel: str                    # relative to its base
    text: str                   # LF text; for a merge, the JSON of the entries the source owns
    base: str = "repo"          # brain: the personal brain's repo; repo: the project's repo; user: the home folder
    what: str = ""
    merge: tuple[str, ...] = ()  # JSON key paths whose entries are the source's (the rest of the file is kept)
    marker: bool = False        # the text carries MARK: an existing file without it is foreign
    manual: bool = False        # never written: lines the owner adds by hand (a tool's own settings file)


@dataclass
class Render:
    target: str
    project: str | None
    outputs: list[Output] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # what the target cannot carry
    managed: list[tuple[str, str]] = field(default_factory=list)  # (base, folder): a file there not rendered is stray
    marked: list[tuple[str, str]] = field(default_factory=list)   # (base, folder): a marked file there not rendered


class RenderError(Exception):
    pass


# --- JSON written as the source says ------------------------------------------------------------------------------

def to_json(value, level: int = 0) -> str:
    """JSON with two-space indent, as ``json.dumps(indent=2)``, except a :class:`neutral.Flow` list on one line."""
    pad, end = "  " * (level + 1), "  " * level
    if isinstance(value, Flow) or (isinstance(value, list) and not value):
        return "[" + ", ".join(to_json(v, level + 1) for v in value) + "]"
    if isinstance(value, list):
        return "[\n" + ",\n".join(pad + to_json(v, level + 1) for v in value) + "\n" + end + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{\n" + ",\n".join(f"{pad}{json.dumps(str(k), ensure_ascii=False)}: {to_json(v, level + 1)}"
                                  for k, v in value.items()) + "\n" + end + "}"
    return json.dumps(value, ensure_ascii=False)


def _sub(value, fn):
    """``value`` with ``fn`` applied to each string, lists keeping their style."""
    if isinstance(value, dict):
        return {k: _sub(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        out = [_sub(v, fn) for v in value]
        return Flow(out) if isinstance(value, Flow) else out
    return fn(value) if isinstance(value, str) else value


def _vars(value, *, default: str, plain: str):
    """``${NAME:-d}`` and ``${NAME}`` rewritten for a tool: ``default`` for one with a default ("keep", or "value" to
    write the default itself), ``plain`` a template for one without ("${env:{name}}")."""
    def one(m):
        name, dflt = m.group(1), m.group(2)
        if dflt is not None:
            return m.group(0) if default == "keep" else dflt
        return plain.replace("{name}", name)
    return _sub(value, lambda s: neutral.VARIABLE.sub(one, s))


# --- the adapters -------------------------------------------------------------------------------------------------

def claude_hooks() -> Path:
    """The engine's Claude hooks (package data): adapters/claude/hooks beside the package once extracted, else the
    hooks folder of the plugin that holds the package."""
    pkg = Path(neutral.__file__).resolve().parent
    own = pkg / "adapters" / "claude" / "hooks"
    return own if own.is_dir() else pkg.parent / "hooks"


def _claude_names(src: neutral.Source) -> tuple[str, dict[str, str]]:
    """(the marketplace's name, {pack id: plugin name}): config.json adapters.claude names the marketplace and the core
    plugin, packs.yaml the others (its own names when config.json has none)."""
    from . import config
    cfg = config.load(src.root)
    mine = cfg.file is not None and cfg.root.resolve() == src.root.resolve()   # this brain's config.json, not another
    claude = ((cfg.data.get("adapters") or {}).get("claude") or {}) if mine else {}
    market = str(claude.get("marketplace") or src.marketplace.get("name") or "")
    names = {}
    for p in src.packs:
        names[p.id] = str((claude.get("plugin") if p.core else None) or p.target("claude").get("name") or p.id)
    return market, names


def name_errors(src: neutral.Source) -> list[str]:
    """packs.yaml's Claude names against config.json adapters.claude (the installer, the guards and the linter read
    config.json): one name each."""
    from . import config
    cfg = config.load(src.root)
    if cfg.file is None or cfg.root.resolve() != src.root.resolve():
        return []
    claude = (cfg.data.get("adapters") or {}).get("claude") or {}
    out = []
    if claude.get("marketplace") and src.marketplace.get("name") not in (None, claude["marketplace"]):
        out.append(f"{neutral.PACKS}: marketplace.name {src.marketplace['name']!r}, config.json adapters.claude "
                   f"says {claude['marketplace']!r}")
    core = src.core
    if core and claude.get("plugin") and core.target("claude").get("name") not in (None, claude["plugin"]):
        out.append(f"{neutral.PACKS}: pack {core.id} claude.name {core.target('claude')['name']!r}, config.json "
                   f"adapters.claude says {claude['plugin']!r}")
    return out


def render_claude(src: neutral.Source, project: str | None = None, project_root: Path | None = None) -> Render:
    r = Render("claude", None)
    market, names = _claude_names(src)
    if not market:
        raise RenderError("no marketplace name (config.json adapters.claude.marketplace, or packs.yaml "
                          "marketplace.name)")
    listing = {"name": market}
    listing.update({k: v for k, v in src.marketplace.items() if k != "name"})
    entries = []
    for p in src.packs:
        claude, name = p.target("claude"), names[p.id]
        entries.append({"name": name, "source": f"./plugins/{name}", **(claude.get("listing") or {})})
        base = f"plugins/{name}"
        r.outputs.append(Output(f"{base}/.claude-plugin/plugin.json",
                                to_json({"name": name, **(claude.get("plugin") or {})}) + "\n", "brain",
                                f"pack {p.id}: the plugin's manifest"))
        for rel in p.items("rules"):
            rf = src.rule_files[rel]
            if not rf.rules:   # a scope's file with its front matter only: nothing to inject
                continue
            r.outputs.append(Output(f"{base}/rules/{Path(rel).name}", rf.render("claude"), "brain",
                                    f"pack {p.id}: rules ({rf.scope}), injected by the core plugin's hook"))
        if p.items("rules"):
            r.managed.append(("brain", f"{base}/rules"))
        for proc in p.items("procedures"):
            for rel, f in src.procedures[proc].files.items():
                r.outputs.append(Output(f"{base}/skills/{proc}/{rel}", neutral.lf(f.read_text(encoding="utf-8")),
                                        "brain", f"pack {p.id}: procedure {proc}"))
        if p.items("procedures"):
            r.managed.append(("brain", f"{base}/skills"))
        servers = {s: _claude_server(src.servers[s]) for s in p.items("mcp")}
        if servers:
            r.outputs.append(Output(f"{base}/.mcp.json", to_json({"mcpServers": servers}) + "\n", "brain",
                                    f"pack {p.id}: MCP servers"))
        if p.spec.get("hooks"):
            hooks = claude_hooks()
            for f in sorted(hooks.rglob("*")) if hooks.is_dir() else []:
                if f.is_file() and "__pycache__" not in f.parts:
                    r.outputs.append(Output(f"{base}/hooks/{f.relative_to(hooks).as_posix()}",
                                            neutral.lf(f.read_text(encoding="utf-8")), "brain",
                                            f"pack {p.id}: the engine's Claude hooks"))
    listing["plugins"] = entries
    r.outputs.insert(0, Output(".claude-plugin/marketplace.json", to_json(listing) + "\n", "brain",
                               "the marketplace"))
    return r


def _claude_server(s: neutral.Server) -> dict:
    out = {"type": s.transport}
    out.update({k: v for k, v in s.spec.items() if k not in ("transport", "about")})
    return out


def _packs_for(src: neutral.Source, project: str | None) -> list[neutral.Pack]:
    """The packs a project gets: every pack without projects (the owner's scope) and those that name it."""
    return [p for p in src.packs if p.projects is None or (project and project in p.projects)]


def agents_md(src: neutral.Source, project: str | None, project_root: Path | None) -> str:
    """AGENTS.md: the chain flattened, broadest first, the pointers after the global rules, the project's own rules
    last."""
    files = neutral.chain(src, project, project_root)
    parts = [f"<!-- {MARK} -->\n"]
    pointers = _pointers(src)
    for i, rf in enumerate(files):
        if rf.rules or rf.project:   # a scope's file without a rule renders nothing
            parts.append(rf.render("agents").rstrip("\n") + "\n")
        last_global = rf.scope == neutral.GLOBAL and (i + 1 == len(files) or files[i + 1].scope != neutral.GLOBAL)
        if last_global and pointers:
            parts.append(pointers)
    if pointers and not any(rf.scope == neutral.GLOBAL for rf in files):
        parts.append(pointers)
    return "\n".join(parts)


def _pointers(src: neutral.Source) -> str:
    p = src.pointers
    if not p:
        return ""
    repo = f" (`{p['repo']}`)" if p.get("repo") else ""
    lines = [f"## Memory and decisions\n\nIn the brain's repo{repo}:\n"]
    for key, what in (("memory", "the memory notes"), ("decisions", "the decision log (ADR)"),
                      ("graph", "the backlog and rules graph"), ("why", "why a rule exists")):
        if p.get(key):
            lines.append(f"- {what}: `{p[key]}`")
    return "\n".join(lines) + "\n"


def _skill_text(rel: str, text: str, mark: bool) -> str:
    """A procedure's file for a tool other than Claude: the marker in its front matter (SKILL.md) or first line."""
    text = neutral.lf(text)
    if not mark or not rel.endswith(".md"):
        return text
    if text.startswith("---\n"):
        return f"---\n# {MARK}\n" + text[4:]
    return f"<!-- {MARK} -->\n" + text


def _base(src: neutral.Source, project: str | None, project_root: Path | None, target: str,
          skills: str = ".agents/skills") -> Render:
    """The common base: AGENTS.md and the packs' procedures under ``skills``."""
    r = Render(target, project)
    r.outputs.append(Output("AGENTS.md", agents_md(src, project, project_root), "repo",
                            "the rules: the chain flattened (global, ancestors, the project's own)", marker=True))
    r.marked.append(("repo", skills))
    seen = set()
    for p in _packs_for(src, project):
        for proc in p.items("procedures"):
            if proc in seen:
                continue
            seen.add(proc)
            for rel, f in src.procedures[proc].files.items():
                r.outputs.append(Output(f"{skills}/{proc}/{rel}",
                                        _skill_text(rel, f.read_text(encoding="utf-8"), True), "repo",
                                        f"procedure {proc} (pack {p.id})", marker=rel.endswith(".md")))
    if any(p.spec.get("hooks") for p in _packs_for(src, project)):
        r.notes.append("hooks (rules injection, guards, capture, announcements) are Claude Code's: not rendered; the "
                       "rules they inject are in AGENTS.md")
    return r


def _servers(src: neutral.Source, project: str | None) -> dict[str, neutral.Server]:
    out = {}
    for p in _packs_for(src, project):
        for s in p.items("mcp"):
            out[s] = src.servers[s]
    return out


def render_agents(src, project, project_root) -> Render:
    r = _base(src, project, project_root, "agents")
    if _servers(src, project):
        r.notes.append("MCP servers: AGENTS.md has no MCP section; the cursor, gemini, antigravity, grok and hermes "
                       "targets write each tool's MCP settings")
    return r


def render_cursor(src, project, project_root) -> Render:
    r = _base(src, project, project_root, "cursor")
    servers = {}
    for name, s in _servers(src, project).items():
        spec = _vars({k: v for k, v in s.spec.items() if k not in ("transport", "about")}, default="value",
                     plain="${env:{name}}")
        if s.transport == "stdio":
            spec = {"type": "stdio", **spec}
        servers[name] = spec
    if servers:
        r.outputs.append(Output(".cursor/mcp.json", to_json(servers), "repo", "MCP servers (merged)",
                                merge=("mcpServers",)))
        if any(d is not None for s in _servers(src, project).values() for _, d in neutral.variables(s.spec)):
            r.notes.append("Cursor has no default in ${env:NAME}: a variable's default is written as its value")
    return r


def render_gemini(src, project, project_root) -> Render:
    r = _base(src, project, project_root, "gemini")
    r.outputs.append(Output(".gemini/settings.json", to_json(["AGENTS.md", "GEMINI.md"]), "repo",
                            "Gemini CLI reads AGENTS.md (merged)", merge=("context", "fileName")))
    servers = {}
    for name, s in _servers(src, project).items():
        spec = {k: v for k, v in s.spec.items() if k not in ("transport", "about", "url")}
        if s.transport == "http":
            spec = {"httpUrl": s.spec["url"], **spec}
        elif s.transport == "sse":
            spec = {"url": s.spec["url"], **spec}
        servers[name] = spec
    if servers:
        r.outputs.append(Output(".gemini/settings.json", to_json(servers), "repo", "MCP servers (merged)",
                                merge=("mcpServers",)))
    return r


def render_antigravity(src, project, project_root) -> Render:
    r = _base(src, project, project_root, "antigravity")
    servers = {}
    for name, s in _servers(src, project).items():
        if s.transport == "sse":
            r.notes.append(f"MCP server {name}: Antigravity has no SSE transport (streamable HTTP only): not rendered")
            continue
        spec = _vars({k: v for k, v in s.spec.items() if k not in ("transport", "about", "url")}, default="value",
                     plain="${{name}}")
        if s.transport == "http":
            spec = {"serverUrl": _vars(s.spec["url"], default="value", plain="${{name}}"), **spec}
        servers[name] = spec
    if servers:
        r.outputs.append(Output(".agents/mcp_config.json", to_json(servers), "repo", "MCP servers (merged)",
                                merge=("mcpServers",)))
        r.notes.append("Antigravity documents no variable interpolation in mcp_config.json: a variable's default is "
                       "written as its value")
    return r


def _toml(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_toml_key(k)} = {_toml(v)}" for k, v in value.items()) + " }"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)   # a TOML basic string has JSON's escapes


def _toml_key(k: str) -> str:
    return k if k.replace("_", "").replace("-", "").isalnum() else json.dumps(k)


def render_grok(src, project, project_root) -> Render:
    r = _base(src, project, project_root, "grok", skills=".grok/skills")
    r.notes.append("Grok Build reads CLAUDE.md beside AGENTS.md: the project's own rules come twice (the deeper file "
                   "wins, same text)")
    lines = [f"# {MARK}"]
    for name, s in _servers(src, project).items():
        lines.append(f"\n[mcp_servers.{_toml_key(name)}]")
        for k, v in s.spec.items():
            if k not in ("transport", "about"):
                lines.append(f"{_toml_key(k)} = {_toml(v)}")
    if len(lines) > 1:
        r.outputs.append(Output(".grok/config.toml", "\n".join(lines) + "\n", "repo", "MCP servers", marker=True))
    return r


def render_hermes(src, project, project_root) -> Render:
    r = _base(src, project, project_root, "hermes")
    r.notes.append("Hermes reads project skills from .agents/skills once trusted: hermes skills trust")
    servers = _servers(src, project)
    if servers:
        r.notes.append("Hermes documents ${NAME} but no default: a variable's default is written as its value")
        import yaml
        plain = {n: _vars({k: (list(v) if isinstance(v, list) else v) for k, v in s.spec.items()
                           if k not in ("transport", "about")}, default="value", plain="${{name}}")
                 for n, s in servers.items()}
        block = {"mcp_servers": {n: {k: (list(v) if isinstance(v, list) else v) for k, v in spec.items()}
                                 | ({"transport": "sse"} if servers[n].transport == "sse" else {})
                                 for n, spec in plain.items()}}
        r.outputs.append(Output(".hermes/config.yaml", yaml.safe_dump(block, sort_keys=False, allow_unicode=True),
                                "user", "MCP servers: add these lines to ~/.hermes/config.yaml by hand", manual=True))
    return r


ADAPTERS = {"claude": render_claude, "agents": render_agents, "cursor": render_cursor, "gemini": render_gemini,
            "antigravity": render_antigravity, "grok": render_grok, "hermes": render_hermes}


# --- plan, write, check -------------------------------------------------------------------------------------------

def render(root: Path, target: str, project: str | None = None, project_root: Path | None = None) -> Render:
    """The outputs of ``target`` for ``project`` (claude: the brain's marketplace, whatever the project). Raises
    RenderError when the source has errors."""
    if target not in ADAPTERS:
        raise RenderError(f"unknown target {target!r} ({', '.join(TARGETS)})")
    src = neutral.load(root)
    errors = neutral.check(src) + name_errors(src)
    if errors:
        raise RenderError(f"{len(errors)} error(s) in the neutral source ({src.folder}):\n  " + "\n  ".join(errors))
    return ADAPTERS[target](src, project, project_root)


def _read(path: Path) -> str | None:
    try:
        return neutral.lf(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _dig(data, keys: tuple[str, ...]):
    for k in keys:
        if not isinstance(data, dict) or k not in data:
            return None
        data = data[k]
    return data


def _merged(existing: str | None, out: Output) -> tuple[str, bool]:
    """(the file with the source's entries set under out.merge, whether they were already there and equal)."""
    try:
        data = json.loads(existing) if existing and existing.strip() else {}
    except ValueError:
        raise RenderError(f"{out.rel}: not readable JSON, not merged (fix it or remove it)")
    if not isinstance(data, dict):
        raise RenderError(f"{out.rel}: not a JSON object, not merged")
    want = json.loads(out.text)
    have = _dig(data, out.merge)
    node = data
    for k in out.merge[:-1]:
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            raise RenderError(f"{out.rel}: {'.'.join(out.merge[:-1])} is not an object, not merged")
    if isinstance(want, dict):   # the source's entries; the file's others stay
        same = isinstance(have, dict) and all(have.get(k) == v for k, v in want.items())
        node[out.merge[-1]] = {**(have if isinstance(have, dict) else {}), **want}
    else:
        same = have == want
        node[out.merge[-1]] = want
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", same


def plan(r: Render, bases: dict[str, Path]) -> list[dict]:
    """Each output with its destination and its state: same, differs, new, foreign (a file the render did not write),
    manual (lines the owner adds by hand), then each stray file (in a folder the render owns, not rendered)."""
    rows = []
    written: set[Path] = set()
    for out in r.outputs:
        dest = bases[out.base] / out.rel
        written.add(dest.resolve())
        have = _read(dest)
        if out.manual:
            state = "manual"
        elif out.merge:
            state = "new" if have is None else ("same" if _merged(have, out)[1] else "differs")
        elif have is None:
            state = "new"
        elif have == out.text:
            state = "same"
        elif out.marker and MARK not in have:
            state = "foreign"
        else:
            state = "differs"
        rows.append({"file": str(dest), "rel": out.rel, "base": out.base, "state": state, "what": out.what,
                     "merge": ".".join(out.merge)})
    for base, folder, marked in [(b, f, False) for b, f in r.managed] + [(b, f, True) for b, f in r.marked]:
        d = bases[base] / folder
        for f in sorted(d.rglob("*")) if d.is_dir() else []:
            if not f.is_file() or "__pycache__" in f.parts or f.resolve() in written:
                continue
            if marked and MARK not in (_read(f) or ""):
                continue   # a file of the tool's own, or the owner's: not the render's
            rows.append({"file": str(f), "rel": f.relative_to(bases[base]).as_posix(), "base": base,
                         "state": "stray", "what": f"in {folder}, not in the source", "merge": ""})
    return rows


def write(r: Render, bases: dict[str, Path], *, force: bool = False, user: bool = False) -> list[dict]:
    """The plan, then each new, differing (and with ``force``, foreign) output written and each stray removed; home
    folder outputs only with ``user`` (``--out``), manual ones never."""
    rows = plan(r, bases)
    by_file = {(o.base, o.rel, ".".join(o.merge)): o for o in r.outputs}
    for row in rows:
        row["written"] = False
        if row["base"] == "user" and not user:
            continue
        if row["state"] == "stray":
            Path(row["file"]).unlink()
            for d in Path(row["file"]).parents:   # the folders it leaves empty go too, up to the base
                if d == bases[row["base"]] or any(d.iterdir()):
                    break
                d.rmdir()
            row["written"] = True
            continue
        out = by_file.get((row["base"], row["rel"], row["merge"]))
        if out is None or row["state"] == "same" or (row["state"] == "foreign" and not force):
            continue
        if row["state"] == "manual" and not user:   # a tool's own settings: the owner adds the lines
            continue
        dest = Path(row["file"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = _merged(_read(dest), out)[0] if out.merge else out.text
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        row["written"] = True
    return rows


def stale(rows: list[dict], *, bases: tuple[str, ...] = ("brain", "repo")) -> list[dict]:
    """The rows a check fails on: an output not current or a stray file, in the given bases."""
    return [r for r in rows if r["base"] in bases and r["state"] in ("differs", "new", "foreign", "stray")]


def rendered_before(rows: list[dict], r: Render, only: set[str] | None = None) -> bool:
    """Whether a target was rendered into this repo already (among the outputs ``only`` names): one of its marked
    files is there and carries the marker, or a merged file holds one of the source's entries."""
    by = {(o.rel, ".".join(o.merge)): o for o in r.outputs}
    for row in rows:
        out = by.get((row["rel"], row["merge"]))
        if out is None or row["base"] != "repo" or (only is not None and row["rel"] not in only):
            continue
        if out.marker and row["state"] in ("same", "differs"):
            return True
        if out.merge and row["state"] in ("same", "differs"):
            try:
                have = _dig(json.loads(_read(Path(row["file"])) or "{}"), out.merge)
            except ValueError:
                continue
            want = json.loads(out.text)
            if isinstance(want, (dict, list)) and isinstance(have, type(want)) and set(want) & set(have):
                return True
    return False


def rendered(root: Path, project: str, project_root: Path) -> list[tuple[str, Render, list[dict], set[str]]]:
    """The targets other than claude already rendered into a project's repo, each with its render, its plan and the
    files it alone writes (agents: the base; another target: what it adds to the base). A repo opts in by holding
    them (NS-1, the owner 2026-11-02: the brain first, then each project on request)."""
    src = neutral.load(root)
    if not src.data or neutral.check(src):
        return []   # the brain's own check reports the source's errors
    out, base = [], set()
    for t in TARGETS[1:]:
        r = ADAPTERS[t](src, project, project_root)
        rows = plan(r, bases_for(root, project_root, None))
        own = {o.rel for o in r.outputs if o.base == "repo"} - (base if t != "agents" else set())
        if t == "agents":
            base = own
        if own and rendered_before(rows, r, own):
            out.append((t, r, rows, own))
    return out


def keep_current(project_root: Path, project: str, *, fix: bool) -> list[str]:
    """The targets rendered into a project's repo, kept current: with ``fix`` (brain sync) each one is rendered
    again, a production checkout left alone; without (brain check), one line per file not current."""
    root = neutral.brain_root(project_root)
    if not neutral.applies(root):
        return []
    lines = []
    for t, r, rows, own in rendered(root, project, project_root):
        if fix:
            prod = _production(project_root)
            if prod:
                lines.append(f"render {t}: {project_root} is a production checkout, not written")
                continue
            for row in write(r, bases_for(root, project_root, None)):
                if row["written"]:
                    lines.append(f"render {t}: {row['rel']} written")
            continue
        for row in stale(rows, bases=("repo",)):
            if row["rel"] in own:
                lines.append(f"render {t} for {project}: {row['rel']} {row['state']} (brain sync, or brain render "
                             f"--target {t} --project {project} --write)")
    return lines


def registry_warnings(root: Path, projs) -> list[str]:
    """The overrides of locked rules across the projects here (brain.neutral.lock_findings); a stale render in a
    project's repo is that project's check (keep_current)."""
    if not neutral.applies(root):
        return []
    src = neutral.load(root)
    if neutral.check(src):
        return []
    return [f"rules: {x}" for x in neutral.lock_findings(src, {p.name: p.root for p in projs if p.root.is_dir()})]


def _production(path: Path) -> str | None:
    from . import guards
    import os
    roots = guards.production_roots()
    return guards.in_production(str(path), roots) or guards.in_production(os.path.realpath(str(path)),
                                                                           [os.path.realpath(x) for x in roots])


def bases_for(root: Path, project_root: Path | None, out: Path | None) -> dict[str, Path]:
    if out is not None:
        return {"brain": out, "repo": out, "user": out / "home"}
    return {"brain": Path(root), "repo": Path(project_root or root), "user": Path.home()}


def text_lines(r: Render, rows: list[dict], *, mode: str) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    head = (f"render {r.target}" + (f" for {r.project}" if r.project and r.target != "claude" else "") + ": "
            + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    out = [head]
    for row in rows:
        if mode == "plan" or row["state"] != "same" or row.get("written"):
            flag = "written" if row.get("written") else row["state"]
            where = row["file"] if row["base"] == "user" else row["rel"]
            out.append(f"  {flag:<8} {where}" + (f"  [{row['merge']}]" if row["merge"] else "")
                       + (f"  ({row['what']})" if row["what"] and mode == "plan" else ""))
    for note in r.notes:
        out.append(f"  not rendered: {note}")
    return out


def main(root: Path, target: str, *, project: str | None = None, project_root: Path | None = None,
         out: Path | None = None, do_write: bool = False, check: bool = False, force: bool = False,
         as_json: bool = False) -> int:
    """``brain render``: the plan, or ``--write``, or ``--check`` (exit 1 when an output is not current)."""
    try:
        r = render(root, target, project, project_root)
    except RenderError as exc:
        print(f"brain render: {exc}")
        return 1
    bases = bases_for(root, project_root, out)
    if do_write and out is None:
        for base in {o.base for o in r.outputs} - {"user"}:
            prod = _production(bases[base])
            if prod:
                print(f"brain render: {bases[base]} is a production checkout ({prod}): render into a worktree of it "
                      "(--repo DIR), then a PR there")
                return 1
    try:
        rows = write(r, bases, force=force, user=out is not None) if do_write else plan(r, bases)
    except RenderError as exc:
        print(f"brain render: {exc}")
        return 1
    if as_json:
        print(json.dumps({"target": r.target, "project": r.project, "files": rows, "notes": r.notes,
                          "manual": {o.rel: o.text for o in r.outputs if o.manual}}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(text_lines(r, rows, mode="write" if do_write else "check" if check else "plan")))
        for o in r.outputs:
            if o.manual and not do_write:
                print(f"  add to ~/{o.rel}:\n" + "".join(f"    {ln}\n" for ln in o.text.splitlines()), end="")
    if check:
        bad = stale(rows)
        if bad:
            print(f"brain render: {len(bad)} file(s) not current: brain render --target {target}"
                  + (f" --project {project}" if project and target != "claude" else "") + " --write")
            return 1
    if do_write:
        left = [x for x in rows if x["state"] == "foreign" and not x["written"]]
        if left:
            print(f"brain render: {len(left)} foreign file(s) left (not written by brain render): --force replaces "
                  "them")
            return 1
    return 0
