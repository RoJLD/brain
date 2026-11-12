"""``brain brief <item>``: a sub-session's brief written from the graph at zero token, so that the coordinator edits
only what needs judgement (wi-brain-brief-generate; the scale study's gaps 2, 4 and 20).

The brief holds, in this order:

- the item: its id, title, status, priority, milestones, then every prop as recorded (what was decided, validated,
  extended, found) and its open questions (``props.open``);
- the task class, its model and effort, and the context budget: config.json ``brief.classes`` (default
  :data:`CLASSES`: a trivial task on a small model at low effort, a strategic one on the strongest at high effort);
  ``--budget`` else the class's;
- the cost estimate of brain cost (wi-brain-brief-estimate) when the token ledger has a basis;
- the coordinator's app session id (``--coordinator``, else ``$CLAUDE_CODE_HOST_SESSION_ID``: the session that runs
  ``brain brief``) and the shared notes folder (``--notes``, else the desktop app's folder for that session when it
  exists);
- the item's subgraph: every edge in and out with the other node's type, status and title (a spec's anchor);
- its files and collisions (brain collisions' line for the item);
- how to start: the repo, a worktree from the default branch (a card cannot carry a source branch, so the brief says
  how to start from one);
- the invariants and failure modes to test (wi-brain-brief-failure-modes, brain.failuremodes): one line per surface
  kind the item touches (its predicted surface, title and props: a store, a procedure step, an external system, a
  multi-step write, a CLI, a heuristic, a guard, a counted set, a moved test, text into another format), the public
  engine when a repo it touches is public (config.json ``public.repos``), then its own ``props.invariants``; brain
  review prep --item writes the same lines for the review's agents;
- the invariants: the standards the project follows (projects.yaml ``standards:``, brain.standards), one line each
  with its domain and how it is enforced; no section for a project that declares none;
- a section the coordinator fills in (scope, order, what to read first);
- after the merge (wi-brain-archive-after-merge, close-item step 5): the session that merges its own PR archives itself
  once its after-merge steps are done, the coordinator archives a child whose report says merged and verified without
  asking again, never another running session or one with uncommitted or unmerged work, and the owner's app setting
  ``auto_archive_inactive_days = 7`` as the token-free net: :data:`AFTER_MERGE`, or config.json ``brief.after_merge``
  (a list of lines; ``[]`` drops the section);
- the definition of done and the never-list, copied from the owner's rules (config.json ``rules``, then the
  project's ``CLAUDE.md`` and ``AGENTS.md``): the section whose heading is ``brief.done`` (default "Definition of
  done"), and the ``brief.never`` section (default "Never") or, without one, the rules' sentences that start with
  "Never" and their "<owner> decides" lines. Nothing of them is written in the engine.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config, failuremodes, projects, resume, standards, tidy

CLASSES = {"trivial": {"model": "haiku", "effort": "low", "budget": "400k"},
           "standard": {"model": "", "effort": "", "budget": "400k"},
           "strategic": {"model": "opus", "effort": "high", "budget": "800k"}}
BUDGETS = ("400k", "600k", "800k", "1M")
DONE = "Definition of done"
# What a session does once its PR is merged (close-item step 5, wi-brain-archive-after-merge); brief.after_merge
# replaces it.
AFTER_MERGE = (
    "- You merge your own PR: once the main checkout is pulled, the backlog ticked, the journal note written and your "
    "report sent, archive this session (close-item step 5). The owner's standing authorization stands for their yes: "
    "ask no one. The archive is your last act.",
    "- The coordinator merges it: it archives you as soon as your report says merged and verified, without asking "
    "again; write those words only when both are true.",
    "- Never archived: a session with uncommitted changes or unmerged or unverified work (yours included), or another "
    "session that is running (mid-turn). Your own archive is the one mid-turn archive allowed: make it the final tool "
    "call of your turn. Finish, or report what is left.",
    "- The token-free net: the owner's app setting `auto_archive_inactive_days = 7` archives a session left inactive "
    "for 7 days. The owner sets it; no session changes the app's settings.",
    "- Waits and cleanup: wait in the foreground with a bound, or in the background with a deadline and an exit when "
    "the file or process you wait on is gone (`timeout`, `kill -0`, `[ -e log ] || exit 1`; never an unbounded "
    "`until` loop); stop your background tasks (TaskStop) before deleting their logs or venvs, and before the archive: "
    "the app refuses to archive a session with live work (wi-brain-stuck-waiters).",
)
NEVER = "Never"
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
SENTENCE = re.compile(r"(?<=[.;!?])\s+(?=[A-Z])")


class BriefError(ValueError):
    pass


@dataclass
class Brief:
    item: dict
    project: str
    task_class: str
    model: str
    effort: str
    budget: str
    coordinator: str
    notes: str
    estimate: str
    subgraph: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    start: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    after_merge: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    never: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# --- the owner's rules ---------------------------------------------------------------------------------------

def rules_files(p: projects.Project, cfg: config.Config) -> list[Path]:
    """The owner's rules (config.json ``rules``), then the project's CLAUDE.md and AGENTS.md, those that exist."""
    files = [*config.rules_files(cfg), p.root / "CLAUDE.md", p.root / "AGENTS.md"]
    out, seen = [], set()
    for f in files:
        key = os.path.normcase(str(f.resolve())) if f.exists() else ""
        if key and key not in seen and f.is_file():
            seen.add(key)
            out.append(f)
    return out


def section(text: str, title: str) -> list[str]:
    """The lines under the heading ``title`` (any level, case ignored), down to the next heading of its level or
    above; [] when there is none."""
    lines = text.splitlines()
    out: list[str] = []
    level = 0
    for line in lines:
        m = HEADING.match(line)
        if level:
            if m and len(m.group(1)) <= level:
                break
            out.append(line)
        elif m and m.group(2).strip().lower() == title.strip().lower():
            level = len(m.group(1))
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _sentences(text: str) -> list[str]:
    """The text's sentences, a bullet or a paragraph joined first."""
    paras, cur = [], []
    for line in text.splitlines():
        bare = line.strip()
        if not bare or HEADING.match(line) or bare.startswith(("- ", "* ")) or re.match(r"^\d+\.\s", bare):
            if cur:
                paras.append(" ".join(cur))
            cur = [re.sub(r"^([-*]|\d+\.)\s+", "", bare)] if bare and not HEADING.match(line) else []
        else:
            cur.append(bare)
    if cur:
        paras.append(" ".join(cur))
    return [s.strip() for p in paras for s in SENTENCE.split(p) if s.strip()]


def never_list(texts: list[str], owner_names: list[str]) -> list[str]:
    """The rules' sentences that start with Never, and their '<owner> decides' lines, once each, in order."""
    out: list[str] = []
    who = [re.escape(n) for n in owner_names if n]
    decides = re.compile(rf"^(?:{'|'.join(who)})\s+decides\b", re.I) if who else None
    for text in texts:
        for s in _sentences(text):
            if (s.startswith("Never ") or (decides and decides.match(s))) and s not in out:
                out.append(s)
    return out


def owner_rules(p: projects.Project, cfg: config.Config) -> tuple[list[str], list[str], list[str]]:
    """(the definition of done, the never-list, the files read) from the owner's rules."""
    opts = cfg.data.get("brief") if isinstance(cfg.data.get("brief"), dict) else {}
    done_title, never_title = str(opts.get("done") or DONE), str(opts.get("never") or NEVER)
    files = rules_files(p, cfg)
    texts = []
    for f in files:
        try:
            texts.append(f.read_text(encoding="utf-8"))
        except OSError:
            texts.append("")
    done = next((s for s in (section(t, done_title) for t in texts) if s), [])
    never = [x for t in texts for x in section(t, never_title)]
    if not never:
        never = [f"- {s}" for s in never_list(texts, [config.owner(cfg), config.display_name(cfg)])]
    return done, never, [str(f) for f in files]


# --- the graph ---------------------------------------------------------------------------------------------------

def _short(text: str, n: int = 150) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _node_text(st: resume.Store, nid: str) -> str:
    n = st.nodes.get(nid)
    if not n:
        return f"{nid} (not in this store)"
    bits = [str(n.get("type") or ""), str(n.get("status") or "")]
    anchor = f"; {n['anchor']}" if n.get("anchor") else ""
    return f"{nid} ({', '.join(b for b in bits if b)}{anchor}): {_short(n.get('title') or '')}"


def subgraph(st: resume.Store, nid: str, limit: int = 40) -> list[str]:
    """Every edge in and out of ``nid``, the other node described; the generated documented_in edges last."""
    out = [e for e in st.edges if e["from"] == nid]
    into = [e for e in st.edges if e.get("to") == nid]
    rank = (lambda e: (e.get("type") == "documented_in", e.get("type") or "", e.get("to") or ""))  # noqa: E731
    lines = [f"- {e.get('type')} -> {_node_text(st, e['to'])}" for e in sorted(out, key=rank)]
    lines += [f"- <- {e.get('type')} from {_node_text(st, e['from'])}"
              for e in sorted(into, key=lambda e: (e.get("type") or "", e["from"]))]
    if len(lines) > limit:
        lines = lines[:limit] + [f"- ... {len(lines) - limit} more edge(s): brain item show {nid}"]
    return lines


def _find(p: projects.Project, nid: str) -> tuple[resume.Store, dict, Path]:
    for store in p.stores or [p.root / "notes" / "graph"]:
        if (store / "schema.yaml").is_file():
            st = resume.Store.load(store)
            if nid in st.nodes:
                return st, st.nodes[nid], store
    raise BriefError(f"{nid}: no such node in {p.name}'s stores")


# --- the session ---------------------------------------------------------------------------------------------

def notes_folder(coordinator: str) -> str:
    """The desktop app's shared notes folder for the coordinator's session, when it exists."""
    base = os.environ.get("LOCALAPPDATA")
    if not base or not coordinator:
        return ""
    for d in sorted(Path(base).glob(f"Claude-Data/*/side-session-notes/{coordinator}")):
        if d.is_dir():
            return str(d)
    return ""


def _estimate(p: projects.Project, nid: str, task_class: str) -> str:
    try:
        from . import cost, usage
        led = cost.load([p], p.root)
        target = cost.target_of(led, nid, task_class)
        est = cost.estimate(led, target, usage.now_utc().date().isoformat())
        return cost.estimate_text(est) if est.get("n") else "no basis yet (no finished item like it in the ledger)"
    except Exception as exc:  # noqa: BLE001 - the estimate is a hint: its absence never stops a brief
        return f"none ({type(exc).__name__}: {_short(exc, 80)})"


def _start(p: projects.Project, node: dict) -> list[str]:
    """Where the session starts: each repo's main checkout and default branch."""
    lines = []
    for name, path, _ in tidy._repos(p):
        default, refs = tidy.default_branch(path)
        if refs:
            lines.append(f"- {name}: cwd {path}, use_worktree true, source_branch {default}; a card cannot carry a "
                         f"source branch: in a worktree on another branch, `git switch -c <yours> origin/{default}`")
    slug = node["id"].removeprefix("wi-")
    lines.append(f"- the branch: claude/{slug} (a short slug is fine); refresh this brief with `brain brief "
                 f"{node['id']}`, the project with `brain resume --project {p.name}`")
    lines.append(f"- read the brain through its commands, not its files (graph YAML, decision log, journal, views): "
                 f"`brain --project {p.name} item show {node['id']}` (props, edges, ADRs, DDRs), `brain items "
                 "--text WORDS` (filters), `brain adr show <adr-id|rule-id>`, `brain spec show <spec-id> --section N` "
                 "(--toc), `brain journal last [N]`")
    return lines


def touches_public(p: projects.Project, cfg: config.Config, repos: set[str]) -> bool:
    """Whether a repo of ``p`` that ``repos`` names (a CodeRef's token: the repo's folder or its name, case ignored)
    is public (config.json ``public.repos``). No repo named, no answer: False (the review of the repo says it)."""
    from . import public
    want = {r.lower() for r in repos if r}
    if not want or not public.public_repos(cfg):
        return False
    for name, path, _ in tidy._repos(p):
        if {name.lower(), path.name.lower()} & want and public.is_public(public.remote_of(path, cfg)[1], cfg):
            return True
    return False


def failure_modes(p: projects.Project, st: resume.Store, node: dict, cfg: config.Config,
                  extra_files: list[str] | None = None, diff: list[str] | None = None,
                  public: bool = False) -> list[str]:
    """The section « Invariants and failure modes to test » of item ``node`` (brain.failuremodes), from its predicted
    surface (brain.collisions.surface), its texts, and ``extra_files`` and ``diff`` (a diff's files and changed lines,
    for brain review prep --item); ``public`` (the reviewed repo is public) adds the public line whatever the item's
    CodeRefs say; a line saying none matched when the table sees nothing."""
    from . import collisions
    paths, names = collisions.surface(node, st)
    try:
        pub = public or touches_public(p, cfg, {r for r, _ in paths if r})
    except Exception:  # noqa: BLE001 - a remote that cannot be read never stops a brief
        pub = public
    lines = failuremodes.for_item(node, [path for _, path in paths] + names, pub, extra_files, diff)
    return lines or ["- no surface of the table matched (brain.failuremodes): the review reads the state logic; "
                     "record the item's own in props.invariants (brain item set)"]


def after_merge(opts: dict) -> list[str]:
    """The brief's after-the-merge lines: config.json ``brief.after_merge`` when it is a list, else AFTER_MERGE."""
    lines = opts.get("after_merge")
    return [str(x) for x in lines] if isinstance(lines, list) else list(AFTER_MERGE)


def build(p: projects.Project, nid: str, *, task_class: str = "standard", budget: str = "", coordinator: str = "",
          notes: str = "", collisions_report=None) -> Brief:
    """The brief of item ``nid`` of project ``p``."""
    cfg = config.load(p.root)
    opts = cfg.data.get("brief") if isinstance(cfg.data.get("brief"), dict) else {}
    classes = {**CLASSES, **{k: {**CLASSES.get(k, {}), **v} for k, v in (opts.get("classes") or {}).items()
                             if isinstance(v, dict)}}
    if task_class not in classes:
        raise BriefError(f"class {task_class!r}: one of {', '.join(classes)}")
    st, node, _store = _find(p, nid)
    warnings = []
    if node.get("type") != "WorkItem":
        warnings.append(f"{nid} is a {node.get('type')}, not a WorkItem")
    if node.get("status") not in ("todo", "doing", "blocked"):
        warnings.append(f"{nid} is {node.get('status')}: not open")
    blockers = st.blockers(nid)
    if blockers:
        warnings.append(f"it depends on open item(s): {', '.join(blockers)}")
    cls = classes[task_class]
    budget = budget or cls.get("budget") or "400k"
    if budget not in BUDGETS:
        warnings.append(f"budget {budget}: the steps are {', '.join(BUDGETS)}")
    coordinator = coordinator or os.environ.get("CLAUDE_CODE_HOST_SESSION_ID", "")
    if not coordinator:
        warnings.append("no coordinator id: pass --coordinator (the app's local_ id of the session that reviews)")
    notes = notes or notes_folder(coordinator)
    from . import collisions
    rep = collisions_report if collisions_report is not None else collisions.report([p], frontier=True)
    done, never, sources = owner_rules(p, cfg)
    if not done:
        warnings.append(f"no '{opts.get('done') or DONE}' section in the rules read")
    return Brief(item=node, project=p.name, task_class=task_class, model=cls.get("model") or "",
                 effort=cls.get("effort") or "", budget=budget, coordinator=coordinator, notes=notes,
                 estimate=_estimate(p, nid, task_class), subgraph=subgraph(st, nid),
                 collisions=collisions.item_line(rep, nid), start=_start(p, node),
                 failure_modes=failure_modes(p, st, node, cfg),
                 invariants=standards.invariants(p), after_merge=after_merge(opts),
                 done=done, never=never,
                 sources=sources, warnings=warnings,
                 generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))


def _prop(key: str, value) -> str:
    if isinstance(value, (list, dict)):
        import json
        value = json.dumps(value, ensure_ascii=False)
    return f"- {key}: {' '.join(str(value).split())}"


def _section(title: str, lines: list[str]) -> list[str]:
    """An optional section: its heading and lines, nothing when it has none."""
    return ["", f"## {title}", ""] + lines if lines else []


def render(b: Brief) -> str:
    n = b.item
    props = dict(n.get("props") or {})
    opened = props.pop("open", None)
    who = lambda x, d: x or d  # noqa: E731
    lines = [f"# Brief — {n['id']}", "",
             f"Generated by `brain brief` from {b.project}'s graph at {b.generated} (zero token). The coordinator "
             "edits only the section « To decide »; everything else is the graph's and the rules'.", "",
             "## The task", "",
             f"- **Item:** `{n['id']}` ({n.get('status')}, {props.get('priority') or 'no priority'}): "
             f"{' '.join(str(n.get('title') or '').split())}",
             f"- **Task class:** {b.task_class}: model {who(b.model, 'the coordinator’s')}, effort "
             f"{who(b.effort, 'the coordinator’s')}. **Context budget:** {b.budget}; at ~80 %, commit, write a "
             "hand-over note in the shared notes folder and report.",
             f"- **Cost estimate:** {b.estimate}",
             f"- **Coordinator:** {who(b.coordinator, 'unknown (--coordinator)')}: report to it by SendMessage, "
             "signed with your own `local_` id; give your PR numbers and head shas.",
             f"- **Shared notes folder:** {who(b.notes, 'none found (--notes)')}"]
    if b.warnings:
        lines += ["", "**Check:** " + "; ".join(b.warnings) + "."]
    lines += ["", "## What is recorded on the item", ""]
    lines += [_prop(k, v) for k, v in props.items()] or ["- no props"]
    if opened:
        lines += ["", "**Open questions (props.open):**", _prop("open", opened)]
    lines += ["", "## Its subgraph", ""] + (b.subgraph or ["- no edge"])
    lines += ["", "## Files and collisions (brain collisions)", ""] + [f"- {x}" for x in b.collisions]
    lines += ["", "## How to start", ""] + b.start
    lines += _section(failuremodes.TITLE, b.failure_modes)
    lines += _section("Invariants: the project's standards (brain standards list --applicable)", b.invariants)
    lines += ["", "## To decide (the coordinator)", "",
              "- Scope and order: <edit>", "- What is decided, and by which ADR: <edit>", "- Read first: <edit>"]
    lines += _section("After the merge (close-item step 5)", b.after_merge)
    lines += ["", "## Definition of done (the owner's rules)", ""] + (b.done or ["- none found in the rules"])
    lines += ["", "## Never (the owner's rules)", ""] + (b.never or ["- none found in the rules"])
    if b.sources:
        lines += ["", "Rules read: " + ", ".join(b.sources)]
    return "\n".join(lines)
