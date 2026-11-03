"""``brain lint rules``: what the owner's rules cost each session, and which of them a script or a guard could replace,
at zero token (wi-brain-rules-linter; spec 2026-10-30 governance §3.10, spec 2026-11-02 learned harness §3.4).

It reads what a session in a project gets before its first prompt:

- the global rules the core plugin's hook injects (config.json's first ``rules``), against the 10,000 characters
  Claude Code keeps of a hook's output (spec plugin §5.5);
- the project's ``CLAUDE.md`` files (``CLAUDE.md``, ``.claude/CLAUDE.md``, ``CLAUDE.local.md``), ``~/.claude/CLAUDE.md``
  when it is still there, and the project's memory index (``~/.claude/projects/<folder>/memory/MEMORY.md``);
- the skill descriptions listed in the context: the skills of the owner's marketplace's plugins enabled at user or
  project scope (``enabledPlugins`` of the settings files; the names of config.json's adapters.claude), the user's and
  the project's own skills.

Then, over the rule texts (global and project, cut into units: a bullet with its sub-bullets, a numbered list with its
lead, a paragraph):

- **duplicates** between two files: the same words (exact), or close enough by content words (near: their Jaccard
  index, or the share of the shorter unit found in the other);
- **script candidates**: units phrased as procedures (numbered steps, commands, then / after / before);
- **guard candidates**: units that forbid or require an action a PreToolUse hook sees (an edit, a git or gh command,
  a file), with the core plugin's guards that already cover part of it;
- **the hard-rule ratio**: the active Rule nodes with an ``enforced_by`` edge (to the Hook, test or script that checks
  them; ``props.scope`` says what it covers) over all of them. A soft rule is a warning, never an error: many rules
  need judgement.

``--propose`` files one DDR per candidate through the decision queue (``decisions.ask``), the most useful first, so
that at most ``--max`` (8) lint DDRs wait on the owner at once and they answer a batch in one sitting. A candidate's
key (a hash of its kind and texts) is in its DDR id: a candidate asked once, whatever the answer, is not asked again
until its text changes. The report says which candidates are still undecided (milestone ms-brain-lean-rules).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config, decisions, graph, neutral, paths, projects, resume

HOOK_CAP = 10_000  # characters Claude Code keeps of a hook's additionalContext (spec plugin §5.5)
CAP_WARN = 0.8
CLAUDE_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")
NEAR = 0.5  # Jaccard index of two units' content words
CONTAIN = 0.75  # share of the shorter unit's content words found in the other
MIN_WORDS = 6  # containment counts from this many content words
SCRIPT_SCORE = 3
GUARD_SCORE = 3
MAX_PENDING = 8
QUOTE = 200  # characters of a rule quoted in a DDR's question
SLUG = "rules-lint"
ITEM = "wi-brain-rules-linter"
SPEC = "spec-brain-governance"
DECIDED = ("answered", "integrated", "archived")
RANK = {"size": 0, "guard": 1, "script": 2, "duplicate-exact": 3, "guard-covered": 4, "duplicate-near": 5}
# What the core plugin's guards (brain.guards.GUARDS) already refuse, as words a rule names them by.
GUARDED = {"production": re.compile(r"\bproduction checkouts?\b", re.I),
           "attribution": re.compile(r"\battribution\b", re.I),
           "secrets": re.compile(r"\bsecrets?\b", re.I),
           "public": re.compile(r"\bpublic repos?\b", re.I),
           "owner": re.compile(r"\b(?:the owner|\w+) decides\b|\b(?:the owner|\w+)'s alone\b|\b(?:repository )?visibility\b|"
                               r"\bscheduled tasks?\b|\barming\b|\blive orders?\b|install\.ps1 -Apply", re.I),
           "power": re.compile(r"\bshutdown\b|\breboot\b|\bwake-on-lan\b|\bpower actions?\b|\bkubectl\b|"
                               r"\bthe machines' power\b", re.I),
           "branches": re.compile(r"\bbranch names?\b|\bbranch(?:es)? (?:are |is )?named\b|\bnaming convention\b",
                                  re.I)}


def global_rules(cfg: config.Config | None = None) -> str:
    """The global rules the core plugin injects, relative to the brain's root: config.json's first ``rules``, else
    the core plugin's own copy (``plugins/<plugin>/rules/global.md``)."""
    cfg = cfg or config.load()
    rules = cfg.get("rules")
    if isinstance(rules, list) and rules and isinstance(rules[0], str) and rules[0]:
        return rules[0]
    return f"plugins/{config.claude(cfg)['plugin']}/rules/global.md"

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^[-*+]\s+")
_NUMBERED = re.compile(r"^\d+[.)]\s+")
_WORD = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
_CODE = re.compile(r"`([^`\n]+)`")
_COMMAND = re.compile(r"^(?:git|gh|python3?|py|pip|pytest|brain|research_graph|quant|docker|npm|npx|bash|pwsh|"
                      r"powershell|uv|make|claude)\b|\.(?:ps1|py|sh)\b", re.I)
_SEQUENCE = re.compile(r"\b(?:then|after|afterwards|before|first|next|finally|once|in this order|followed by)\b", re.I)
_FORBID = re.compile(r"\b(?:never|no|not|don't|do not|must not|refuse[sd]?|only (?:through|via|with|by)|always|"
                     r"rather than|instead of)\b", re.I)
_ACTION = re.compile(r"\b(?:edit(?:s|ed|ing)?|commit(?:s|ted)?|push(?:ed|es)?|merge[sd]?|switch(?:es|ed)?|checkout|"
                     r"rebase|reset|delete[sd]?|remove[sd]?|rewrit(?:e|es|ten)|amend|typed?|writ(?:e|es|ten)|"
                     r"install(?:s|ed)?|attribution|secrets?|by hand|hand edits?)\b", re.I)
_OBJECT = re.compile(r"`[^`\n]+`|\b(?:git|gh|prs?|commits?|branch(?:es)?|checkouts?|worktrees?|files?|folders?|"
                     r"paths?|repos?|repository|hooks?|generated|yaml|json|configs?)\b", re.I)
_JUDGEMENT = re.compile(r"\b(?:when|unless|judge?ment|decides?|consider|prefer|should|may|enough|relevant|useful)\b",
                        re.I)
_CLAUSE = re.compile(r"(?<=[.;:])\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_STOP = frozenset("""a an the and or but if then than that this these those it its is are be been being was were of to
in on at by for from with without as into onto over under per via not no nor so such do does did done can could may
might must shall should will would each every any all some one two own same other their there they them we you your
our who whom which what when where why how also only just here his her itself""".split())


@dataclass
class Source:
    kind: str  # hook (injected by a hook, capped), claude-md, memory, skill
    owner: str  # the project the text belongs to (user: ~/.claude)
    rel: str  # relative to the owner's root (a skill: plugin:name)
    path: Path
    text: str  # what reaches the context

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass
class Unit:
    owner: str
    rel: str
    line: int
    section: str
    anchor: str  # the nearest heading's anchor
    top: str  # the anchor of its level-2 heading (Rule nodes point there)
    text: str
    steps: int = 0
    rule: str = ""  # the Rule node of its section, when the owner's store has one
    words: frozenset = field(default_factory=frozenset)

    @property
    def ref(self) -> str:
        return f"{self.owner}:{self.rel}:{self.line}"

    def excerpt(self, n: int = 90) -> str:
        text = " ".join(_NUMBERED.sub("", _BULLET.sub("", ln.strip())) for ln in self.text.splitlines())
        text = " ".join(text.split())
        return text if len(text) <= n else text[: n - 1] + "…"

    def as_dict(self) -> dict:
        return {"ref": self.ref, "owner": self.owner, "file": self.rel, "line": self.line, "section": self.section,
                "rule": self.rule or None, "text": self.excerpt(200)}


# --- reading ---

def anchor(heading: str) -> str:
    """GitHub's anchor of a heading: lower case, punctuation dropped, spaces to hyphens."""
    s = _CODE.sub(r"\1", heading.strip()).lower()
    return re.sub(r"[^\w\- ]", "", s).replace(" ", "-")


def units(text: str, owner: str, rel: str) -> list[Unit]:
    """The rule units of a Markdown text: a top-level bullet with its continuation and sub-bullets, a numbered list
    (with the paragraph ending in ':' that leads it), a paragraph. Headings are not units; code fences belong to the
    unit around them."""
    out: list[Unit] = []
    section = sect_anchor = top = ""
    block: list[str] = []
    kind, start, blank, fence = "", 0, False, False

    def flush() -> None:
        nonlocal block, kind
        body = "\n".join(block).strip()
        if body:
            steps = sum(1 for ln in block if _NUMBERED.match(ln))
            out.append(Unit(owner, rel, start + 1, section, sect_anchor, top, body, steps, words=words(body)))
        block, kind = [], ""

    for i, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if fence or stripped.startswith("```"):
            if not kind:
                kind, start = "para", i
            block.append(line)
            fence = fence != stripped.startswith("```")
            continue
        m = _HEADING.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2)
            if level >= 2:
                section, sect_anchor = title, anchor(title)
                if level == 2:
                    top = sect_anchor
            blank = False
            continue
        if not stripped:
            if kind == "para" and not block[-1].rstrip().endswith(":"):  # a lead waits for its list
                flush()
            blank = bool(kind)
            continue
        indented = line[:1] in (" ", "\t")
        if _BULLET.match(line):
            flush()
            kind, start = "bullet", i
        elif _NUMBERED.match(line):
            if kind == "para" and block[-1].rstrip().endswith(":"):
                kind = "steps"
            elif kind != "steps":
                flush()
                kind, start = "steps", i
        elif indented and kind in ("bullet", "steps"):
            pass  # continuation or a sub-list, even after a blank line
        elif not kind or blank:
            flush()
            kind, start = "para", i
        blank = False
        block.append(line)
    flush()
    return out


def _stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def words(text: str) -> frozenset:
    """The content words of a text: lower case, stop words and words under three letters dropped, lightly stemmed."""
    return frozenset(_stem(w) for w in _WORD.findall(_CODE.sub(r" \1 ", text).lower())
                     if len(w) >= 3 and w not in _STOP)


def _normal(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        data = graph._yaml().safe_load(text[3:end])
    except Exception:  # a malformed header is reported as no description, never a crash
        return {}
    return data if isinstance(data, dict) else {}


def claude_dir() -> Path:
    """Claude Code's user folder: $CLAUDE_CONFIG_DIR, else ~/.claude."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r", "")


def _settings_plugins(files: list[Path]) -> set[str]:
    """The plugins of the owner's marketplace (config.json adapters.claude) the settings files enable (later files
    win, like Claude Code's scopes)."""
    marketplace = config.claude(config.load())["marketplace"]
    enabled: dict[str, bool] = {}
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except (OSError, ValueError):
            continue
        for key, on in (data.get("enabledPlugins") or {}).items():
            name, _, market = str(key).partition("@")
            if market == marketplace:
                enabled[name] = bool(on)
    return {n for n, on in enabled.items() if on}


def _skills(folder: Path, prefix: str, owner: str, rel_base: str) -> list[Source]:
    out = []
    for f in sorted(folder.glob("*/SKILL.md")):
        meta = _frontmatter(_read(f))
        name = str(meta.get("name") or f.parent.name)
        listed = f"- {prefix}{name}: {' '.join(str(meta.get('description') or '').split())}"
        out.append(Source("skill", owner, f"{rel_base}/{f.parent.name}/SKILL.md", f, listed))
    return out


def memory_index(root: Path) -> Path:
    """The project's auto-memory index: ~/.claude/projects/<folder with every other character as '-'>/memory."""
    main = paths.main_checkout(root) or root
    return claude_dir() / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(main.resolve())) / "memory" / "MEMORY.md"


def sources(project: projects.Project, brain: projects.Project | None) -> list[Source]:
    """What a session in ``project`` gets before its first prompt, as far as files tell."""
    out: list[Source] = []
    brain_root = brain.root if brain else Path(__file__).resolve().parents[3]
    cfg = config.load()
    rel = global_rules(cfg)
    rules = brain_root / rel
    if not rules.is_file():
        rules = Path(__file__).resolve().parents[1] / "rules" / "global.md"  # the plugin's own copy
    if rules.is_file():  # inject-rules.sh drops CR and turns tabs to spaces
        out.append(Source("hook", brain.name if brain else "brain", rel, rules, _read(rules).replace("\t", " ")))
    user = claude_dir()
    if (user / "CLAUDE.md").is_file():
        out.append(Source("claude-md", "user", "~/.claude/CLAUDE.md", user / "CLAUDE.md", _read(user / "CLAUDE.md")))
    for rel in CLAUDE_FILES:
        f = project.root / rel
        if f.is_file():
            out.append(Source("claude-md", project.name, rel, f, _read(f)))
    mem = memory_index(project.root)
    if mem.is_file():  # Claude Code loads its first 200 lines
        out.append(Source("memory", project.name, "MEMORY.md", mem, "\n".join(_read(mem).splitlines()[:200])))
    enabled = {config.claude(cfg)["plugin"]} | _settings_plugins([user / "settings.json",
                                                                 project.root / ".claude" / "settings.json",
                                                 project.root / ".claude" / "settings.local.json"])
    for plugin in sorted(enabled):
        folder = brain_root / "plugins" / plugin / "skills"
        out += _skills(folder, f"{plugin}:", brain.name if brain else "brain", f"plugins/{plugin}/skills")
    out += _skills(user / "skills", "", "user", "~/.claude/skills")
    out += _skills(project.root / ".claude" / "skills", "", project.name, ".claude/skills")
    return out


# --- the graph: Rule nodes and enforced_by ---

def _store_lists(store: Path) -> tuple[list, list]:
    nodes = [n for f in sorted((store / "nodes").glob("*.yaml")) for n in resume._load_list(f)]
    edges = resume._load_list(store / "edges.yaml")
    edges += [e for f in sorted((store / "edges").glob("*.yaml")) for e in resume._load_list(f)]
    return ([n for n in nodes if isinstance(n, dict)], [e for e in edges if isinstance(e, dict)])


def hard_rules(store: Path) -> dict | None:
    """The store's active Rule nodes, the ones an ``enforced_by`` edge makes hard (with what checks them and the
    edge's scope) and the soft ones; None when the store has no Rule type."""
    if not (store / "schema.yaml").is_file():
        return None
    schema = graph.load_schema(store)
    if "Rule" not in (schema.get("node_types") or []):
        return None
    nodes, edges = _store_lists(store)
    rules = {n["id"]: n for n in nodes if n.get("type") == "Rule" and n.get("status", "active") == "active"}
    by: dict[str, list[dict]] = {}
    for e in edges:
        if e.get("type") == "enforced_by" and e.get("from") in rules:
            by.setdefault(e["from"], []).append({"by": e.get("to"), "scope": (e.get("props") or {}).get("scope", "")})
    hard = [{"rule": r, "enforced_by": by[r]} for r in rules if r in by]
    soft = [r for r in rules if r not in by]
    return {"store": store.as_posix(), "edge_type": "enforced_by" in (schema.get("edge_types") or []),
            "rules": len(rules), "hard": hard, "soft": soft,
            "ratio": round(len(hard) / len(rules), 3) if rules else None,
            "anchors": {r: str(n.get("anchor") or "") for r, n in rules.items()}}


def render_hard(h: dict) -> list[str]:
    if not h["rules"]:
        return [f"rules: no active Rule node in {h['store']}"]
    lines = [f"rules: {len(h['hard'])} of {h['rules']} hard ({h['ratio']:.0%}), an enforced_by edge to what checks "
             f"them"]
    for x in h["hard"]:
        lines.append(f"  {x['rule']}: " + "; ".join(f"{e['by']}" + (f" ({e['scope']})" if e["scope"] else "")
                                                    for e in x["enforced_by"]))
    if not h["edge_type"]:
        lines.append(f"  enforced_by is not an edge type of {h['store']}/schema.yaml")
    if h["soft"]:
        lines.append(f"warning: {len(h['soft'])} soft rule(s), no enforced_by edge: {', '.join(h['soft'])}")
    return lines


def _map_rules(us: list[Unit], hard: dict[str, dict]) -> None:
    """Each unit's Rule node: the owner's store has a Rule whose anchor is the unit's file and section."""
    for u in us:
        h = hard.get(u.owner)
        if not h:
            continue
        for rid, a in h["anchors"].items():
            path, _, frag = a.partition("#")
            if path == u.rel and frag in (u.anchor, u.top):
                u.rule = rid
                if frag == u.anchor:
                    break


# --- the checks ---

def duplicates(us: list[Unit]) -> list[dict]:
    """Pairs of units from two different files that say the same: exact (the same words) or near."""
    out = []
    for i, a in enumerate(us):
        for b in us[i + 1:]:
            if (a.owner, a.rel) == (b.owner, b.rel) or not a.words or not b.words:
                continue
            inter = len(a.words & b.words)
            if not inter:
                continue
            jac = inter / len(a.words | b.words)
            small = min(len(a.words), len(b.words))
            cont = inter / small
            if _normal(a.text) == _normal(b.text) and len(a.words) >= 3:
                kind = "exact"
            elif jac >= NEAR or (cont >= CONTAIN and small >= MIN_WORDS):
                kind = "near"
            else:
                continue
            out.append({"kind": kind, "jaccard": round(jac, 2), "containment": round(cont, 2), "a": a, "b": b})
    return sorted(out, key=lambda d: (d["kind"] != "exact", -max(d["jaccard"], d["containment"])))


def procedure(u: Unit) -> tuple[int, list[str]]:
    """How much a unit reads as a procedure: numbered steps, commands, sequence words."""
    score, why = 0, []
    if u.steps >= 3:
        score += 2
        why.append(f"{u.steps} steps")
    cmds = [c for c in _CODE.findall(u.text) if _COMMAND.search(c.strip())]
    if cmds:
        score += min(len(cmds), 3)
        why.append(f"{len(cmds)} command(s)")
    seq = len(_SEQUENCE.findall(u.text))
    if seq >= 2:
        score += 1
        why.append(f"{seq} sequence words")
    return score, why


def clauses(text: str, cut: re.Pattern = _CLAUSE) -> list[str]:
    """A text's lines joined, then cut at '.', ';' or ':' followed by a space (``_SENTENCE``: at '.' only), never
    inside inline code; list markers dropped."""
    spans: list[str] = []

    def keep(m: re.Match) -> str:
        spans.append(m.group(0))
        return f"\0{len(spans) - 1}\0"
    masked = _CODE.sub(keep, " ".join(_NUMBERED.sub("", _BULLET.sub("", ln.strip())) for ln in text.splitlines()))
    return [re.sub(r"\0(\d+)\0", lambda m: spans[int(m.group(1))], c).strip() for c in cut.split(masked)]


def guardable(u: Unit) -> tuple[int, list[str], str]:
    """How much a unit reads as something a PreToolUse hook could check: in one clause, a word that forbids or
    requires governs an action the hook sees (within six words after it), +1 when the unit names an object the hook
    sees (a file, a git or gh object, code), -1 when the clause leaves it to judgement (when, unless, prefer...).
    The score, its reasons and the sentence that holds the clause (the clause alone past QUOTE characters)."""
    best, why, said = 0, [], ""
    for clause in clauses(u.text):
        for m in _FORBID.finditer(clause):
            act = _ACTION.search(" ".join(clause[m.end():].split()[:6]))
            if not act:
                continue
            score = 2
            reasons = [f"{m.group(0).lower()} ... {act.group(0).lower()}"]
            obj = _OBJECT.search(u.text)
            if obj:
                score += 1
                reasons.append(f"on {obj.group(0).strip('`')[:30]}")
            judged = _JUDGEMENT.search(clause)
            if judged:
                score -= 1
                reasons.append(f"judgement ({judged.group(0).lower()})")
            if score > best:
                best, why, said = score, reasons, clause
    sentence = next((s for s in clauses(u.text, _SENTENCE) if said and said in s), said)
    return best, why, sentence if len(sentence) <= QUOTE else "…" + said


def covered(u: Unit) -> list[str]:
    """The core plugin's guards a unit names (in its text or its section's title): they already check part of it."""
    return [g for g, rx in GUARDED.items() if rx.search(u.text) or rx.search(u.section)]


# --- the report ---

def _brain(scope: list[projects.Project]) -> projects.Project | None:
    """The project that holds the global rules: the one in scope with rules/global.md, else this package's checkout."""
    rel = global_rules()
    for p in scope:
        if (p.root / rel).is_file():
            return p
    repo = paths.package_repo()
    return resume.project_for(repo) if repo and (repo / rel).is_file() else None


def _hard_by_owner(owners: list[projects.Project]) -> dict[str, dict]:
    out = {}
    for p in owners:
        for store in p.stores:
            h = hard_rules(store)
            if h is not None:
                h["owner"] = p.name
                out[p.name] = h
                break
    return out


def _key(kind: str, *texts: str) -> str:
    return hashlib.sha1("\n".join([kind, *sorted(_normal(t) for t in texts)]).encode("utf-8")).hexdigest()[:8]


def _group_of(u: Unit) -> str:
    return u.rule or f"{u.owner}:{u.rel}#{u.top}"


def _groups(cands: list[dict]) -> dict[str, list[dict]]:
    """Candidates by rule: their Rule node, else their file's level-2 section."""
    out: dict[str, list[dict]] = {}
    for c in cands:
        out.setdefault(_group_of(c["unit"]), []).append(c)
    return out


def lint(scope: list[projects.Project]) -> dict:
    """The report for the projects in scope: sizes per project, then duplicates, script and guard candidates over
    the rule texts of all of them (the global rules once), and the hard-rule ratio of each store with Rule nodes."""
    brain = _brain(scope)
    owners = list(scope) + ([brain] if brain and brain.name not in {p.name for p in scope} else [])
    sizes, rule_sources = [], {}
    for p in scope:
        srcs = sources(p, brain)
        rows = []
        for s in srcs:
            row = {"kind": s.kind, "owner": s.owner, "file": s.rel, "chars": s.chars, "tokens": resume.tokens(s.text)}
            if s.kind == "hook":
                row["cap"] = HOOK_CAP
                row["share"] = round(s.chars / HOOK_CAP, 3)
            rows.append(row)
            if s.kind in ("hook", "claude-md"):
                rule_sources[(s.owner, s.rel)] = s
        sizes.append({"project": p.name, "root": p.root.as_posix(), "sources": rows,
                      "chars": sum(r["chars"] for r in rows), "tokens": sum(r["tokens"] for r in rows)})
    us = [u for s in rule_sources.values() for u in units(s.text, s.owner, s.rel)]
    hard = _hard_by_owner(owners)
    _map_rules(us, hard)
    soft = {r for h in hard.values() for r in h["soft"]}
    scripts, guards = [], []
    for u in us:
        score, why = procedure(u)
        if score >= SCRIPT_SCORE:
            scripts.append({"unit": u, "score": score, "why": why})
        score, why, clause = guardable(u)
        if score >= GUARD_SCORE:
            enforced = u.rule and u.rule not in soft
            guards.append({"unit": u, "score": score, "why": why, "clause": clause, "covered": covered(u),
                           "enforced": bool(enforced)})
    for kind, cands in (("script", scripts), ("guard", guards)):  # one proposal per rule (or section)
        for group in _groups(cands).values():
            key = _key(kind, *(c["unit"].text for c in group))
            for c in group:
                c["key"] = key
    dups = duplicates(us)
    for d in dups:
        d["key"] = _key("duplicate", d["a"].text, d["b"].text)
    locks = []   # spec-brain-scope-tree 3.7: a lower rule that overrides a rule locked higher in its chain
    if brain and neutral.applies(brain.root):
        locks = neutral.lock_findings(neutral.load(brain.root), {p.name: p.root for p in scope})
    return {"projects": [p.name for p in scope], "sizes": sizes, "hard": list(hard.values()), "duplicates": dups,
            "scripts": sorted(scripts, key=lambda c: -c["score"]), "guards": sorted(guards, key=lambda c: -c["score"]),
            "units": len(us), "locks": locks}


# --- proposals ---

def _label(u: Unit) -> str:
    if u.rule:
        return u.rule
    where = Path(u.rel).name if u.owner != "user" else u.rel
    section = re.sub(r"^[\d.]+\s+|\s+[—–-]+\s.*$", "", u.section)  # "6. Backlog — Ada, 2026-10-30": Backlog
    return f"{u.owner} {where} §{section or 'preamble'}"


def _title(kind: str, u: Unit) -> str:
    head = {"guard": "Rules lint: a guard for", "script": "Rules lint: a script for",
            "duplicate": "Rules lint: duplicate in"}[kind]
    return decisions._short(f"{head} {_label(u)}?", 100)


def _said(c: dict, n: int) -> str:
    """A candidate's words: the sentence a guard would check, else the unit's start."""
    text = c.get("clause") or c["unit"].excerpt(n)
    return text if len(text) <= n else text[: n - 1] + "…"


def _quote(group: list[dict], n: int) -> str:
    return " ".join(f"{c['unit'].ref}: \"{_said(c, n)}\"" for c in group)


def proposals(report: dict) -> list[dict]:
    """One proposal per candidate rule (a Rule node, else a section) or duplicate pair, the most useful first (RANK):
    the hook over its cap, guards on rules nothing enforces, procedures, exact duplicates, guards on rules a guard of
    the core plugin covers in part, near duplicates; within a rank, the highest score first."""
    out = []
    for size in report["sizes"]:
        for s in size["sources"]:
            if s.get("cap") and s["chars"] > s["cap"]:
                out.append({"kind": "size", "rank": (RANK["size"], 0), "key": _key("size", s["file"]), "owner": s["owner"],
                            "title": decisions._short(f"Rules lint: {s['file']} over the hook cap", 100),
                            "question": f"{s['file']} is {s['chars']:,} characters; Claude Code keeps {s['cap']:,} of a "
                                        "hook's output and replaces the rest by a file and a 2,000-character preview. "
                                        "What leaves the injected rules?",
                            "options": ["Move procedures out: the script and skill candidates of brain lint rules "
                                        "first, until under 80% of the cap",
                                        "Split the injection: two hooks, each under the cap",
                                        "Shorten the wording: same rules, fewer words"],
                            "why": "Past the cap the rules are cut; procedures are the cheapest to move, and R2 "
                                   "wants them as scripts anyway."})
    for group in _groups([g for g in report["guards"] if not g["enforced"]]).values():
        u = group[0]["unit"]
        cov = sorted({x for g in group for x in g["covered"]})
        part = (f" The {config.claude(config.load())['plugin']} guards already check part of it: {', '.join(cov)}."
                if cov else "")
        bare = any(not g["covered"] for g in group)
        out.append({"kind": "guard", "rank": (RANK["guard"] if bare else RANK["guard-covered"],
                                              -max(g["score"] for g in group)),
                    "key": group[0]["key"], "owner": u.owner, "unit": u, "title": _title("guard", u),
                    "question": f"{u.rule or 'No Rule node'}, {len(group)} unit(s) a PreToolUse hook could check at "
                                f"zero token: {_quote(group, QUOTE)}{part} Turn it into a guard?",
                    "options": ["Guard it: an item for a PreToolUse guard (tested on real cases, override "
                                "BRAIN_GUARD_ALLOW), the rule text shortened, an enforced_by edge with its scope",
                                "Keep it soft: it needs judgement; the rule stays as it is",
                                "Later: an item in the backlog, not planned now"],
                    "why": "R2 and spec 2026-11-02 §3.4: a rule a machine can check costs tokens in every session and "
                           "can be forgotten; a guard costs none and cannot."})
    for d in report["duplicates"]:
        a, b = d["a"], d["b"]
        rel = global_rules()
        glob = a if a.rel == rel else b if b.rel == rel else None
        other = b if glob is a else a
        out.append({"kind": "duplicate", "rank": (RANK["duplicate-" + d["kind"]], -max(d["jaccard"], d["containment"])),
                    "key": d["key"], "owner": other.owner, "unit": other, "title": _title("duplicate", other),
                    "question": f"{d['kind'].capitalize()} duplicate (Jaccard {d['jaccard']}, containment "
                                f"{d['containment']}): {a.ref} \"{a.excerpt(150)}\" and {b.ref} \"{b.excerpt(150)}\". "
                                "Keep which?",
                    "options": (["Keep the global one: the project's text goes or points to it",
                                 "Keep both: the project's rule narrows the global one (its text says how)",
                                 "Keep the project's: the global one moves to the project"] if glob else
                                [f"Keep {a.owner}'s: the other points to it",
                                 f"Keep {b.owner}'s: the other points to it",
                                 "Keep both: they differ on purpose (their texts say how)"]),
                    "why": "A rule said twice is paid twice in each session and drifts apart; the global rules are "
                           "injected everywhere already, and a project rule wins over them where they differ."})
    for group in _groups(report["scripts"]).values():
        u = group[0]["unit"]
        out.append({"kind": "script", "rank": (RANK["script"], -max(c["score"] for c in group)), "key": group[0]["key"],
                    "owner": u.owner, "unit": u, "title": _title("script", u),
                    "question": f"{u.rule or 'No Rule node'}, {len(group)} unit(s) that read as a procedure ("
                                f"{'; '.join(', '.join(c['why']) for c in group)}): {_quote(group, QUOTE)} Script it?",
                    "options": ["Script it: a brain command (or a skill's script) runs the steps; the rule shrinks to "
                                "one line naming the command",
                                "Make it a skill: loaded when the task matches, not in every session",
                                "Keep the rule: the steps need judgement"],
                    "why": "R2 (scripts before rules): a procedure in the rules costs tokens in every session and its "
                           "steps drift; a command runs them the same way each time."})
    return sorted(out, key=lambda p: p["rank"])


def _asked(root: Path) -> dict[str, dict]:
    """The lint DDRs already in the queue, by candidate key."""
    out = {}
    for _, d in decisions.load(root):
        m = re.search(rf"-{SLUG}-[a-z]+-([0-9a-f]{{8}})$", str(d.get("id", "")))
        if m:
            out[m.group(1)] = d
    return out


def mark_asked(report: dict, root: Path) -> None:
    """Each candidate's DDR (its id and status) when one was filed; the count of undecided candidates."""
    asked = _asked(root)
    undecided = set()
    for c in report["guards"] + report["scripts"] + report["duplicates"]:
        d = asked.get(c["key"])
        c["ddr"] = {"id": d["id"], "status": d.get("status")} if d else None
        if (not d or d.get("status") not in DECIDED) and not c.get("enforced"):
            undecided.add(c["key"])
    report["undecided"] = len(undecided)


def propose(root: Path, report: dict, *, at: str, limit: int = MAX_PENDING, session: str = "",
            dry_run: bool = False) -> dict:
    """File the next batch of proposals as DDRs in ``root``'s queue: no more than ``limit`` lint DDRs pending at
    once, none asked twice."""
    asked = _asked(root)
    pending = sum(1 for d in asked.values() if d.get("status") == "pending")
    fresh = [p for p in proposals(report) if p["key"] not in asked]
    batch = fresh[: max(0, limit - pending)]
    filed = []
    for i, p in enumerate(batch, 1):
        ddr, out = decisions.ask(
            root, title=p["title"], question=p["question"], options=p["options"], why=p["why"], at=at,
            context=f"Rules lint batch of {at[:10]}, {i} of {len(batch)}: answered together in one sitting. "
                    "brain lint rules shows the evidence.",
            items=[ITEM], specs=[SPEC], project=p["owner"], session=session, slug=f"{SLUG}-{p['kind']}-{p['key']}",
            dry_run=dry_run)
        filed.append({"id": ddr["id"], "kind": p["kind"], "title": p["title"],
                      "file": out.relative_to(root).as_posix() if out else None})
    return {"filed": filed, "pending_before": pending, "already_asked": len(asked), "left": len(fresh) - len(batch),
            "limit": limit, "dry_run": dry_run}


# --- rendering ---

def _pct(x: float) -> str:
    return f"{x:.0%}"


def render(report: dict) -> list[str]:
    lines = [f"== rules lint: {', '.join(report['projects'])} ({report['units']} rule units, zero token)"]
    for size in report["sizes"]:
        lines.append(f"injected per session in {size['project']}: ~{size['tokens']:,} tokens "
                     f"({size['chars']:,} characters)")
        for s in size["sources"]:
            cap = (f"  {_pct(s['share'])} of the {s['cap']:,}-character hook cap"
                   + (" OVER" if s["chars"] > s["cap"] else " (near)" if s["share"] >= CAP_WARN else "")
                   if s.get("cap") else "")
            lines.append(f"  {s['kind']:<9} {s['owner'] + ':' + s['file']:<58} {s['chars']:>6,} ch ~{s['tokens']:>5,} tk"
                         f"{cap}")
    for h in report["hard"]:
        lines += [f"{h['owner']}: " + ln if not ln.startswith(("  ", "warning")) else ln for ln in render_hard(h)]
    lines.append(f"duplicates: {len(report['duplicates'])} "
                 f"({sum(d['kind'] == 'exact' for d in report['duplicates'])} exact)")
    for d in report["duplicates"]:
        lines.append(f"  {d['kind']:<5} J {d['jaccard']:.2f} C {d['containment']:.2f}  {d['a'].ref}  ~  {d['b'].ref}"
                     + _ddr(d))
        lines.append(f"        \"{d['a'].excerpt(100)}\"")
        lines.append(f"        \"{d['b'].excerpt(100)}\"")
    lines.append(f"script candidates (procedures): {len(report['scripts'])}")
    for c in report["scripts"]:
        lines.append(f"  {c['unit'].ref} [{', '.join(c['why'])}]" + _ddr(c))
        lines.append(f"        \"{c['unit'].excerpt(100)}\"")
    lines.append(f"guard candidates (a hook could check): {len(report['guards'])}")
    for c in report["guards"]:
        state = ("enforced: " + c["unit"].rule if c["enforced"] else
                 "partly guarded: " + ", ".join(c["covered"]) if c["covered"] else "soft")
        lines.append(f"  {c['unit'].ref} ({c['unit'].rule or 'no Rule node'}; {state})" + _ddr(c))
        lines.append(f"        \"{_said(c, 100)}\"")
    lines.append(f"locked rules overridden: {len(report.get('locks') or [])}")
    lines += [f"  {line}" for line in report.get("locks") or []]
    if "undecided" in report:
        lines.append(f"undecided: {report['undecided']} candidate rule(s) or pair(s) without an answered rules-lint "
                     "DDR")
    return lines


def _ddr(c: dict) -> str:
    d = c.get("ddr")
    return f"  [{d['id']}: {d['status']}]" if d else ""


def to_json(report: dict) -> dict:
    def conv(x):
        if isinstance(x, Unit):
            return x.as_dict()
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items() if k != "anchors"}
        if isinstance(x, (list, tuple)):
            return [conv(v) for v in x]
        return x
    return conv(report)


def over_cap(report: dict) -> bool:
    return any(s.get("cap") and s["chars"] > s["cap"] for size in report["sizes"] for s in size["sources"])
