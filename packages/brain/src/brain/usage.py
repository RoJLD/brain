"""The token ledger (wi-brain-token-ledger; spec 2026-11-02 learned harness §3.5 and §3.16): what every session cost,
read from Claude Code's transcripts at zero token, standard library only.

Each main transcript (``~/.claude/projects/<folder>/<session>.jsonl``) and its subagents' are scanned once into one
row of ``$BRAIN_HOME/usage/sessions.json``, scanned again only when a file changed (its size, its time, its subagents).
The ledger keeps a row when Claude Code deletes the transcript (``cleanupPeriodDays``): it is the history. A row holds
metadata only: tokens, models, costs, times, tool names, the program and subcommand of a shell command (never its
arguments), item ids, hashes of the briefs; every row is secret-scanned before it is written.

Per session, from every API message (one per message id, as ``brain.transcript`` counts them):

  tokens      input, output (thinking included), cache read, cache write (1 h and 5 min), the main transcript's and
              the subagents' apart, by model, by UTC day and by UTC hour (the hours: what brain.quota converts into
              a share of the plan's quota windows);
  cost        the API-equivalent price in USD (``PRICES``: the price list of the claude-api reference, 2026-10-06,
              which reproduces Claude Code's own ``totalCostUSD``; fast mode at twice the price), whatever the plan;
              the plan (``PLANS``, config.json ``usage.plans``: Ultra since 2026-11-02, Pro before) is a label;
  phase       each message by the tool calls it makes, the strongest first: merge (git merge, rebase, pull,
              cherry-pick, gh pr merge), review (review skills and agents, gh pr view|diff|checks, git diff), test
              (pytest, linters, brain check), build (Edit, Write, sed -i, a redirect into a file), ship (commit, push,
              gh pr create, the brain record commands, the plan tools), wait (questions to the owner), explore
              (the rest: reads, searches, other commands); a message with no tool call keeps the phase before it;
              the cache written again by a message whose context is mostly rewritten (cache expired after a wait,
              a compaction) goes to ``reload``; each phase's cost, messages and active time;
  tool        each tool's calls, cost (a message's cost shared among its calls), result size and failures; each shell
              command's program and subcommand the same; each skill's calls and the cost of the turn it drove;
  sequences   the 3-step runs of tool calls and commands (``git add > git commit > git push``), counted with their
              cost: a run repeated across sessions is a script candidate;
  signals     token-free reasons for a cost: prompts, compactions, context reloads, review rounds (runs of review
              messages), merge commands and conflicts, failing command streaks (thrash: failures with no edit in
              between), files edited, the plan's steps at its first and last version, questions to the owner and
              the time waiting on a message, the first ``START_MESSAGES`` messages' cost (the cost of a resume);
  agents      the subagents' and the workflow agents' transcripts (``<session>/subagents/agent-<id>.jsonl``, and
              ``<session>/subagents/workflows/<run>/agent-<id>.jsonl``) read with the session that launched them: their
              tokens and cost are in its ``cost`` and its hours (what brain.quota and the governor read), not in its
              ``main_cost``; ``agents`` says whose they are: the plain subagents by label (the ``description`` of
              their ``.meta.json``), each workflow run by its id with its agents' count, days, phases and labels (the
              meta's, else the run's ``journal.jsonl``). A message a subagent's transcript holds is counted once, as
              the subagent's, should the parent's transcript carry a copy of it;
  brief       from the first prompt: a sub-session (started by another session), its task class and context budget
              (the owner's sub-session rule), the item ids it names, its size; the hash that links it to the
              session that started it (``start_session``).

``brain usage`` reads the ledger back (brain.cost joins it to the backlog: items, themes, milestones).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths, secretscan, stateio, transcript

SCAN_V = 3  # a row scanned by an older scanner is scanned again while its transcript exists (2: the hours; 3: the
#            subagents and workflow runs apart, ``agents``)
START_MESSAGES = 10
RELOAD_MIN = 20_000  # a context below this is not a reload
NGRAM = 3
NGRAM_KEEP = 60  # per session
SHELL_TOOLS = ("Bash", "PowerShell")
PHASES = ("explore", "build", "test", "review", "ship", "merge", "wait", "reload")
_STRENGTH = ("merge", "review", "test", "build", "ship", "wait", "explore")  # the strongest first

# USD per million tokens: input, output, cache read, cache write 5 min, cache write 1 h. The claude-api reference's
# price list (cached 2026-10-06; cache reads as listed, cache writes 1.25x and 2x the input), checked against Claude
# Code's totalCostUSD (cost-state records): Opus 5.5 sessions reproduce it to the cent.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5, 20.0),
    "claude-mythos-5-1": (10.0, 50.0, 0.25, 12.5, 20.0),
    "claude-fable-5": (10.0, 50.0, 1.0, 12.5, 20.0),
    "claude-opus-5-5": (4.0, 20.0, 0.2, 5.0, 8.0),
    "claude-opus-5": (5.0, 25.0, 0.5, 6.25, 10.0),
    "claude-opus-4-8": (5.0, 25.0, 0.5, 6.25, 10.0),
    "claude-opus-4-7": (5.0, 25.0, 0.5, 6.25, 10.0),
    "claude-opus-4-6": (5.0, 25.0, 0.5, 6.25, 10.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.2, 2.5, 4.0),
    "claude-sonnet-5": (2.0, 10.0, 0.2, 2.5, 4.0),
    "claude-sonnet-4-6": (3.0, 15.0, 0.3, 3.75, 6.0),
    "claude-haiku-5-5": (0.1, 0.5, 0.01, 0.125, 0.2),
    "claude-haiku-4-5": (1.0, 5.0, 0.1, 1.25, 2.0),
}
LONG_PROMPT = {"claude-haiku-5-5": (100_000, (0.5, 2.5, 0.05, 0.625, 1.0))}  # above that context, these prices
FAMILIES = ("fable", "mythos", "opus", "sonnet", "haiku")  # an unknown model: its family's latest price
FAST = 2.0  # fast mode (usage.speed "fast"): twice the price
PLANS = (("2026-11-02", "Ultra"), ("", "Pro"))  # (since, plan), newest first; config.json usage.plans overrides

_ID_RE = re.compile(r"\b(?:wi|ms|spec)-[a-z0-9]+(?:-[a-z0-9]+)*\b")
_CLOSE_RE = re.compile(r"\bbrain\s+item\s+close\s+((?:wi|ms|spec)-[a-z0-9-]+)")
_CLASS_RE = re.compile(r"task class\W{0,8}(trivial|standard|strategic)", re.I)
_BUDGET_RE = transcript._BUDGET_RE
_SIDE = "Background (from the session that started this one)"
_CMD_RE = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")
_SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")
_QUOTED_RE = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")  # a separator between quotes splits nothing
_SUB_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_TWO_LEVELS = {"gh", "brain"}
_SUBCOMMANDS = {"git", "gh", "brain", "npm", "pip", "docker", "uv", "cargo", "go", "kubectl", "claude", "winget",
                "choco", "schtasks", "systemctl", "pnpm", "yarn", "conda"}
_QUIET = {"cd", "echo", "true", "set", "export", "sleep", "pushd", "popd", "printf", "write-host", "write-output",
          "for", "done", "fi", "esac", "case", "foreach", "local", "function"}  # no program in that part
_PREFIXES = {"do", "then", "else", "elif", "if", "while", "until", "time", "!", "exec", "sudo", "nohup"}  # before one
_MERGE_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:merge|rebase|pull|cherry-pick|mergetool)\b|\bgh\s+pr\s+merge\b"
                       r"|--theirs|--ours")
_REVIEW_RE = re.compile(r"\bgh\s+pr\s+(?:view|diff|checks|review)\b|\bgh\s+api\b.*\b(?:comments|reviews)\b"
                        r"|\bgit\s+(?:-C\s+\S+\s+)?diff\b")
_TEST_RE = re.compile(r"\b(?:pytest|unittest|tox|nox|ruff|mypy|flake8|pyright|vitest|jest)\b|\bnpm\s+(?:run\s+)?test\b"
                      r"|\b(?:go|cargo)\s+test\b|\bbrain\s+(?:check|record\s+check|audit)\b")
_SHIP_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:add|commit|push|tag|worktree\s+remove)\b"
                      r"|\bgh\s+pr\s+(?:create|edit)\b"
                      r"|\bbrain\s+(?:item|journal|adr|decision|refresh|sync|features|milestone|record|cost)\b")
_BUILD_RE = re.compile(r"\bsed\s+-i\b|\bcat\s*>|>\s*\S+\.(?:py|md|ya?ml|json|toml|txt|ps1|sh|js|ts)\b|\btee\b"
                       r"|\bpip\s+install\b|\bSet-Content\b|\bOut-File\b")
_BUILD_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_SHIP_TOOLS = {"mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up", "TodoWrite", "mcp__ccd_pr__bind_pr"}
_WAIT_TOOLS = {"AskUserQuestion"}
_NO_STEP = _SHIP_TOOLS | {"ToolSearch"}  # bookkeeping between the steps of a sequence, not a step
_REVIEW_WORDS = re.compile(r"review|verif|audit|simplif|security|findings", re.I)


# --- prices ---

def _price_table(model: str, prices: dict | None = None) -> tuple | None:
    table = {**PRICES, **{k: tuple(v) for k, v in (prices or {}).items()}}
    if model in table:
        return table[model]
    for fam in FAMILIES:
        if fam in (model or ""):
            return next((v for k, v in table.items() if fam in k), None)
    return None


def message_cost(part: dict, model: str, speed: str = "", prices: dict | None = None) -> float | None:
    """The API price of one message's tokens (``transcript._usage_tokens``), None for an unknown model."""
    table = _price_table(model, prices)
    if table is None:
        return None
    long = LONG_PROMPT.get(model)
    if long and part.get("input", 0) + part.get("cache_read", 0) + part.get("cache_write", 0) > long[0]:
        table = long[1]
    p_in, p_out, p_read, p_w5, p_w1 = table
    w1, w5 = part.get("cache_write_1h", 0), part.get("cache_write_5m", 0)
    rest = max(0, part.get("cache_write", 0) - w1 - w5)  # a write with no TTL split: priced at 5 min
    usd = (part.get("input", 0) * p_in + part.get("output", 0) * p_out + part.get("cache_read", 0) * p_read
           + (w5 + rest) * p_w5 + w1 * p_w1) / 1e6
    return usd * (FAST if speed == "fast" else 1.0)


def tokens_cost(by_model: dict, prices: dict | None = None) -> float:
    """The price of ``{model: tokens}`` (an SR's tokens_by_model): what the cockpit shows without a scan."""
    return sum(message_cost(t, m, prices=prices) or 0.0 for m, t in (by_model or {}).items())


def plan_of(day: str, plans=None) -> str:
    """The plan in force on ``day`` (YYYY-MM-DD)."""
    for since, name in sorted(plans or PLANS, key=lambda p: p[0], reverse=True):
        if day >= since:
            return name
    return ""


def plans_from(cfg_usage: dict | None) -> tuple:
    rows = (cfg_usage or {}).get("plans") or []
    return tuple((str(r.get("since") or ""), str(r.get("plan") or "")) for r in rows) or PLANS


# --- commands ---

def commands(cmd: str) -> list[str]:
    """The program and subcommand of each part of a shell command (``git push``, ``gh pr create``,
    ``python -m pytest``), never its arguments; a heredoc's body is not a command."""
    if not isinstance(cmd, str):
        return []
    first = cmd.split("\n", 1)[0]
    text = _QUOTED_RE.sub(lambda m: re.sub(r"[|;&\n]", " ", m.group(0)), first if "<<" in first else cmd)
    out = []
    for seg in _SPLIT_RE.split(text):
        words = [w for w in seg.strip().split() if w not in ("&", "(", ")", "{", "}")]
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in _PREFIXES):
            words.pop(0)  # VAR=value, do, then, if...: the command follows
        if words and words[0][:1] in ("'", '"') and words[0][-1:] == words[0][:1]:  # a quoted program path
            words[0] = words[0][1:-1]
        if not words or words[0].startswith(("#", "-", "$", "'", '"', "<", ">")):
            continue
        prog = re.split(r"[\\/]", words[0].strip("'\"&"))[-1].lower().removesuffix(".exe")
        if not prog or prog in _QUIET:
            continue
        rest = words[1:]
        if prog in ("git", "gh") and rest[:1] == ["-C"]:
            rest = rest[2:]
        if prog in ("python", "python3", "py") and rest[:1] == ["-m"] and len(rest) > 1:
            prog, rest = f"python -m {rest[1]}", rest[2:]
        if prog in _SUBCOMMANDS or prog.endswith(" brain"):
            subs = []
            for w in rest[:2 if prog in _TWO_LEVELS or prog.endswith(" brain") else 1]:
                if not _SUB_RE.match(w):
                    break
                subs.append(w)
            prog = " ".join([prog, *subs])
        out.append(prog)
    return out


def phase_of(uses: list[dict]) -> str:
    """The phase of a message from its tool calls, the strongest one ('' without a call)."""
    found = set()
    for u in uses:
        name, inp = u.get("name") or "", u.get("input") or {}
        if name in SHELL_TOOLS:
            cmd = str(inp.get("command") or "")
            for p, rx in (("merge", _MERGE_RE), ("review", _REVIEW_RE), ("test", _TEST_RE), ("build", _BUILD_RE),
                          ("ship", _SHIP_RE)):
                if rx.search(cmd):
                    found.add(p)
                    break
            else:
                found.add("explore")
        elif name in _BUILD_TOOLS:
            found.add("build")
        elif name in _SHIP_TOOLS:
            found.add("ship")
        elif name in _WAIT_TOOLS:
            found.add("wait")
        elif name == "mcp__ccd_host__sync_with_base_branch":
            found.add("merge")
        elif name == "ReportFindings":
            found.add("review")
        elif name == "Skill":
            skill = str(inp.get("skill") or "")
            found.add("review" if _REVIEW_WORDS.search(skill) else "ship" if "close" in skill else "explore")
        elif name in ("Agent", "Task"):
            what = f"{inp.get('subagent_type', '')} {inp.get('description', '')}"
            found.add("review" if _REVIEW_WORDS.search(what) else "explore")
        else:
            found.add("explore")
    return next((p for p in _STRENGTH if p in found), "")


def _short(name: str) -> str:
    return name.rsplit("__", 1)[-1] if name.startswith("mcp__") else name


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def brief_key(text: str) -> str:
    """The hash that links a sub-session's first prompt to the start_session call that wrote it: the first 200
    characters of the task (after ``Task:`` in a sub-session's prompt), whitespace collapsed."""
    t = str(text or "")
    if _SIDE in t and "\nTask:" in t:
        t = t.split("\nTask:", 1)[1]
    return hashlib.sha1(_norm(t)[:200].encode("utf-8")).hexdigest()[:16]


def kind_of(*texts: str) -> str:
    """The kind of work a session's title, branch and brief say: spec, review, fix or build."""
    t = " ".join(texts).lower()
    if re.search(r"brainstorm|\bspec\b|specs/", t):
        return "spec"
    if re.search(r"\breview\b", t):
        return "review"
    if re.search(r"\bfix\b|\bbug\b|\bhotfix\b", t):
        return "fix"
    return "build"


def _day(ts: str) -> str:
    return ts[:10] if ts else ""


def _hour(ts: str) -> str:
    """``2026-11-02T21``: a UTC hour's bucket."""
    return ts[:13] if len(ts) >= 13 else ""


def _secs(a: str, b: str) -> float:
    x, y = transcript.parse_ts(a), transcript.parse_ts(b)
    return (y - x).total_seconds() if x and y else 0.0


def _bucket() -> dict:
    return {"cost": 0.0, "messages": 0, "output": 0, "active_s": 0.0}


def _add_to(d: dict, key: str, **vals) -> None:
    row = d.setdefault(key, {})
    for k, v in vals.items():
        row[k] = row.get(k, 0) + v


# --- the scan ---

class Scan:
    """One transcript's records into a ledger row; a subagent's transcript is scanned apart and merged."""

    def __init__(self, prices: dict | None = None, skip: set | None = None) -> None:
        self.prices = prices
        self.skip = skip or set()  # the message ids a subagent's transcript holds: its, not this one's
        self.st = transcript.SessionStats()
        self.cost = 0.0
        self.unpriced = 0
        self.by_model: dict[str, dict] = {}
        self.days: dict[str, dict] = {}
        self.hours: dict[str, dict] = {}
        self.phases: dict[str, dict] = {}
        self.tools: dict[str, dict] = {}
        self.cmds: dict[str, dict] = {}
        self.skills: dict[str, dict] = {}
        self.ngrams: dict[str, list] = {}
        self.window: list[tuple[str, float]] = []
        self.sig = Counter()
        self.start = {"messages": 0, "cost": 0.0, "cache_read": 0, "cache_write": 0, "tool_calls": 0}
        self.uses: dict[str, tuple] = {}
        self.msg: dict | None = None
        self.seen: set[str] = set()
        self.last_ts = ""
        self.phase = "explore"
        self.prev_phase = ""
        self.skill_turn = ""
        self.first_prompt = ""
        self.spawned: list[str] = []
        self.closed: list[str] = []
        self.plan_steps: list[int] = []
        self.edited: set[str] = set()
        self.streak = 0
        self.max_streak = 0
        self.wait_s = 0.0

    # --- records ---
    def feed_file(self, path: str | Path) -> None:
        for rec, _ in transcript.iter_records(path):
            self.feed(rec)
        self._flush()

    def feed(self, rec: dict) -> None:
        t, ts = rec.get("type"), rec.get("timestamp") or ""
        if t == "assistant" and self.skip and (rec.get("message") or {}).get("id") in self.skip:
            return  # a subagent's message copied into its parent's transcript: counted once, as the subagent's
        self.st.feed(rec)
        if t == "assistant":
            self._assistant(rec, ts)
        elif t == "user":
            self._flush()
            self._user(rec, ts)
        elif t == "system" and rec.get("subtype") == "compact_boundary":
            self._flush()
        if ts and t in ("user", "assistant", "attachment", "system"):
            if self.last_ts:
                gap = _secs(self.last_ts, ts)
                if 0 < gap <= transcript.GAP_S:
                    _add_to(self.phases, self.phase, active_s=gap)
            if ts > self.last_ts:
                self.last_ts = ts

    def _assistant(self, rec: dict, ts: str) -> None:
        msg = rec.get("message") or {}
        mid, model = msg.get("id") or "", msg.get("model") or ""
        if self.msg and self.msg["id"] != mid:
            self._flush()
        if not self.msg:
            self.msg = {"id": mid, "ts": ts, "uses": [], "cost": 0.0, "part": {}, "model": model}
            if mid and model != "<synthetic>" and mid not in self.seen:
                self.seen.add(mid)
                part = transcript._usage_tokens(msg.get("usage") or {})
                usd = message_cost(part, model, (msg.get("usage") or {}).get("speed") or "", self.prices)
                if usd is None:
                    self.unpriced += 1
                    usd = 0.0
                self.msg.update(cost=usd, part=part)
        self.msg["uses"] += [b for b in msg.get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]

    def _flush(self) -> None:
        m, self.msg = self.msg, None
        if not m:
            return
        uses, usd, part, ts = m["uses"], m["cost"], m["part"], m["ts"]
        phase = phase_of(uses) or self.phase
        n = self.sig["messages"]
        if part:
            self.sig["messages"] += 1
            self.cost += usd
            model = m["model"]
            row = self.by_model.setdefault(model, {k: 0 for k in transcript.TOKEN_KEYS} | {"cost": 0.0})
            for k in transcript.TOKEN_KEYS:
                row[k] += part.get(k, 0)
            row["cost"] += usd
            total = part["input"] + part["output"] + part["cache_read"] + part["cache_write"]
            _add_to(self.days, _day(ts), cost=usd, messages=1, output=part["output"], tokens=total)
            _add_to(self.hours, _hour(ts), cost=usd, messages=1, tokens=total)
            ctx = part["input"] + part["cache_read"] + part["cache_write"]
            reload_usd = 0.0
            if n and ctx > RELOAD_MIN and part["cache_write"] > 0.5 * ctx:
                reload_usd = message_cost({"cache_write": part["cache_write"],
                                           "cache_write_1h": part["cache_write_1h"],
                                           "cache_write_5m": part["cache_write_5m"]}, model, prices=self.prices) or 0.0
                self.sig["reloads"] += 1
                self.sig["reload_tokens"] += part["cache_write"]
                _add_to(self.phases, "reload", cost=reload_usd)
            _add_to(self.phases, phase, cost=usd - reload_usd, messages=1, output=part["output"])
            if n < START_MESSAGES:
                self.start["messages"] += 1
                self.start["cost"] += usd
                self.start["cache_read"] += part["cache_read"]
                self.start["cache_write"] += part["cache_write"]
                self.start["tool_calls"] += len(uses)
            if self.skill_turn:
                _add_to(self.skills, self.skill_turn, cost=usd)
        if phase == "review" and self.prev_phase != "review":
            self.sig["review_rounds"] += 1
        self.prev_phase = self.phase = phase
        share = usd / len(uses) if uses else usd
        if not uses and part:
            _add_to(self.tools, "(text)", calls=0, cost=usd)
        for u in uses:
            self._use(u, share, ts)

    def _use(self, u: dict, share: float, ts: str) -> None:
        name, inp = u.get("name") or "?", u.get("input") or {}
        _add_to(self.tools, name, calls=1, cost=share)
        self.sig["tool_calls"] += 1
        keys: list[str] = []
        if name in SHELL_TOOLS:
            cmd = str(inp.get("command") or "")
            keys = commands(cmd)
            for k in keys:
                _add_to(self.cmds, k, calls=1, cost=share / len(keys))
            for item in _CLOSE_RE.findall(cmd):
                if item not in self.closed:
                    self.closed.append(item)
            if _MERGE_RE.search(cmd):
                self.sig["merges"] += 1
            if re.search(r"\bgit\s+(?:-C\s+\S+\s+)?rebase\b", cmd):
                self.sig["rebases"] += 1
        elif name in _BUILD_TOOLS:
            fp = inp.get("file_path") or inp.get("notebook_path")
            if fp:
                self.edited.add(str(fp))
            self.streak = 0
        elif name == "Skill" and inp.get("skill"):
            self.skill_turn = str(inp["skill"])
            _add_to(self.skills, self.skill_turn, calls=1)
        elif name in ("mcp__ccd_turn__update_plan",) and isinstance(inp.get("items"), list):
            self.plan_steps.append(len(inp["items"]))
        elif name == "mcp__ccd_session__start_session" and inp.get("prompt"):
            self.spawned.append(brief_key(inp["prompt"]))
        elif name in _WAIT_TOOLS:
            self.sig["asks"] += 1
        elif name == "mcp__ccd_turn__wrap_up" and inp.get("blocked"):
            self.sig["blocked"] += 1
        steps = keys if name in SHELL_TOOLS else [] if name in _NO_STEP else [_short(name)]
        for s in steps:
            self._step(s, share / max(len(steps), 1))
        if u.get("id"):
            self.uses[u["id"]] = (name, keys, ts)

    def _step(self, step: str, usd: float) -> None:
        self.window = (self.window + [(step, usd)])[-NGRAM:]
        if len(self.window) == NGRAM and len({s for s, _ in self.window}) > 1:
            key = " > ".join(s for s, _ in self.window)
            row = self.ngrams.setdefault(key, [0, 0.0])
            row[0] += 1
            row[1] += sum(c for _, c in self.window)

    def _user(self, rec: dict, ts: str) -> None:
        content = (rec.get("message") or {}).get("content")
        blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        results = [b for b in blocks if b.get("type") == "tool_result"]
        if results:
            for b in results:
                self._result(b, ts)
            return
        if rec.get("isMeta"):
            return
        text = content if isinstance(content, str) else "\n".join(b.get("text", "") for b in blocks
                                                                  if b.get("type") == "text")
        if not text.strip():
            return
        self.sig["prompts"] += 1
        if self.last_ts:
            self.wait_s += max(0.0, _secs(self.last_ts, ts))
        m = _CMD_RE.search(text)
        self.skill_turn = m.group(1) if m else ""
        if self.skill_turn:
            _add_to(self.skills, self.skill_turn, calls=1)
        if not self.first_prompt:
            self.first_prompt = text

    def _result(self, b: dict, ts: str) -> None:
        name, keys, at = self.uses.pop(b.get("tool_use_id") or "", ("?", [], ""))
        c = b.get("content")
        text = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c if isinstance(x, dict)) \
            if isinstance(c, list) else ""
        _add_to(self.tools, name, result_chars=len(text))
        if name in _WAIT_TOOLS and at:
            self.sig["ask_wait_s"] += int(max(0.0, _secs(at, ts)))
        if name not in SHELL_TOOLS:
            return
        if b.get("is_error"):
            _add_to(self.tools, name, fails=1)
            for k in keys:
                _add_to(self.cmds, k, fails=1)
            self.streak += 1
            self.max_streak = max(self.max_streak, self.streak)
            if self.streak == 3:
                self.sig["thrash"] += 1
        else:
            self.streak = 0
        if "CONFLICT" in text and any(k.startswith("git") for k in keys):
            self.sig["conflicts"] += 1

    # --- merge and row ---
    def merge(self, sub: "Scan") -> None:
        """A subagent's scan into its session's."""
        self.cost += sub.cost
        self.unpriced += sub.unpriced
        for src, dst in ((sub.by_model, self.by_model), (sub.days, self.days), (sub.hours, self.hours),
                         (sub.phases, self.phases),
                         (sub.tools, self.tools), (sub.cmds, self.cmds), (sub.skills, self.skills)):
            for k, vals in src.items():
                _add_to(dst, k, **vals)
        for k, (n, usd) in sub.ngrams.items():
            row = self.ngrams.setdefault(k, [0, 0.0])
            row[0] += n
            row[1] += usd
        for k in ("reloads", "reload_tokens", "review_rounds", "merges", "rebases", "conflicts", "thrash",
                  "tool_calls"):
            self.sig[k] += sub.sig[k]
        self.edited |= sub.edited
        self.max_streak = max(self.max_streak, sub.max_streak)

    def row(self, path: Path, sig: list, subs: list[tuple[dict, "Scan"]]) -> dict:
        st = self.st
        first = self.first_prompt
        title = st.title or ""
        branch = st.branches.most_common(1)[0][0] if st.branches else ""
        named = list(dict.fromkeys(_ID_RE.findall(first)))
        m_class, m_budget = _CLASS_RE.search(first), _BUDGET_RE.search(first)
        budget = (int(float(m_budget.group(1).replace(",", ".")) * (1e3 if m_budget.group(2).lower() == "k" else 1e6))
                  if m_budget else st.budget)
        main_cost = self.cost - sum(s.cost for _, s in subs)
        sub_types: dict[str, dict] = {}
        for info, s in subs:
            _add_to(sub_types, info.get("type") or "?", count=1, cost=s.cost)
        signals = dict(self.sig)
        signals.update(compactions=st.compactions, files_edited=len(self.edited), max_fail_streak=self.max_streak,
                       wait_s=int(self.wait_s), plan_first=self.plan_steps[0] if self.plan_steps else 0,
                       plan_last=self.plan_steps[-1] if self.plan_steps else 0, plan_versions=len(self.plan_steps),
                       api_errors=st.api_errors)
        top = sorted(self.ngrams.items(), key=lambda kv: (-kv[1][0], kv[0]))[:NGRAM_KEEP]
        row = {
            "v": SCAN_V, "sig": sig,
            "session_id": st.session_id or path.stem, "transcript": paths.relative_transcript(path),
            "title": title, "folder": st.folders.most_common(1)[0][0] if st.folders else "", "branch": branch,
            "start": st.first_ts, "end": st.last_ts, "active_s": int(st.active_s),
            "model": st.models.most_common(1)[0][0] if st.models else "",
            "effort": st.efforts.most_common(1)[0][0] if st.efforts else "",
            "brief": {"side": _SIDE in first, "key": brief_key(first) if first else "",
                      "class": m_class.group(1).lower() if m_class else "", "budget": budget,
                      "items": named[:20], "chars": len(first)},
            "spawned": list(dict.fromkeys(self.spawned)), "closed": self.closed,
            "title_items": list(dict.fromkeys(_ID_RE.findall(title))), "items": list(st.items),
            "prs": [f"{p['repo']}#{p['number']}" for p in st.prs.values()],
            "kind": kind_of(title, branch, first[:400]),
            "cost": round(self.cost, 4), "main_cost": round(main_cost, 4), "unpriced": self.unpriced,
            "tokens": {k: st.tokens.get(k, 0) for k in transcript.TOKEN_KEYS},
            "sub_tokens": _sum_tokens(s.st for _, s in subs), "subagents": _rounded(sub_types),
            "agents": agents_of(subs),
            "by_model": _rounded(self.by_model), "days": _rounded(self.days), "hours": _rounded(self.hours),
            "phases": _rounded(self.phases),
            "tools": _rounded(self.tools), "commands": _rounded(self.cmds), "skills": _rounded(self.skills),
            "ngrams": {k: [n, round(c, 4)] for k, (n, c) in top},
            "context": {"peak": st.ctx_peak, "compactions": st.compactions},
            "start_cost": {k: round(v, 4) if isinstance(v, float) else v for k, v in self.start.items()},
            "signals": signals,
        }
        cleaned, _ = secretscan.clean(row)
        return cleaned


def _rounded(d: dict) -> dict:
    return {k: {kk: round(vv, 4) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in d.items()}


NO_LABEL = "(no label)"


def agents_of(subs: list[tuple[dict, "Scan"]]) -> dict:
    """A session's subagents apart (wi-brain-usage-workflow-agents): ``subagents``, the plain ones by label
    ({count, cost, output, tokens}); ``workflows``, each run by its id ({cost, agents, output, tokens, start, end,
    days: {day: cost}, phases: {phase: {count, cost}}, labels: {label: {count, cost}}}). Their cost is already in the
    session's ``cost`` (not in its ``main_cost``): this says whose it is."""
    plain: dict[str, dict] = {}
    runs: dict[str, dict] = {}
    for info, s in subs:
        tokens = sum(s.st.tokens.get(k, 0) for k in ("input", "output", "cache_read", "cache_write"))
        out = s.st.tokens.get("output", 0)
        label = info.get("label") or NO_LABEL
        if not info.get("run"):
            _add_to(plain, label, count=1, cost=s.cost, output=out, tokens=tokens)
            continue
        r = runs.setdefault(info["run"], {"cost": 0.0, "agents": 0, "output": 0, "tokens": 0, "start": "", "end": "",
                                          "days": {}, "phases": {}, "labels": {}})
        r["cost"] += s.cost
        r["agents"] += 1
        r["output"] += out
        r["tokens"] += tokens
        if s.st.first_ts and (not r["start"] or s.st.first_ts < r["start"]):
            r["start"] = s.st.first_ts
        if s.st.last_ts > r["end"]:
            r["end"] = s.st.last_ts
        for day, b in s.days.items():
            r["days"][day] = r["days"].get(day, 0.0) + (b.get("cost") or 0.0)
        _add_to(r["phases"], info.get("phase") or "-", count=1, cost=s.cost)
        _add_to(r["labels"], label, count=1, cost=s.cost)
    for r in runs.values():
        r["cost"] = round(r["cost"], 4)
        r["days"] = {d: round(c, 4) for d, c in r["days"].items()}
        r["phases"], r["labels"] = _rounded(r["phases"]), _rounded(r["labels"])
    return {"subagents": _rounded(plain), "workflows": runs}


def _sum_tokens(stats) -> dict:
    out = {k: 0 for k in transcript.TOKEN_KEYS}
    for s in stats:
        for k in transcript.TOKEN_KEYS:
            out[k] += s.tokens.get(k, 0)
    return out


def sig_of(path: Path) -> tuple:
    """What tells that a session's files changed: the transcript's size and time, its subagents' count and sizes."""
    st = path.stat()
    subs = transcript.subagent_files(path)
    return st.st_size, st.st_mtime_ns, len(subs), sum(f.stat().st_size for f in subs)


def sig_list(sig: tuple) -> list:
    return list(sig)


def scan(path: str | Path, prices: dict | None = None) -> dict:
    """The ledger row of one main transcript and its subagents' (plain ones and workflow agents, each with its
    ``transcript.agent_info``). The subagents are read first: a message one of them holds is theirs, never also its
    parent's, should the main transcript carry a copy of it (a sidechain record)."""
    p = Path(path)
    sig = sig_list(sig_of(p))
    subs, owned, journals = [], set(), {}
    for f in transcript.subagent_files(p):
        s = Scan(prices, skip=owned)
        s.feed_file(f)
        owned |= s.seen
        subs.append((transcript.agent_info(f, journals), s))
    main = Scan(prices, skip=owned)
    main.feed_file(p)
    for _, s in subs:
        main.merge(s)
    return main.row(p, sig, subs)


# --- the ledger ---

def ledger_file() -> Path:
    return paths.brain_home() / "usage" / "sessions.json"


def _ledger_shape(data: dict) -> str:
    rows = data.get("rows", {})
    if not isinstance(rows, dict):
        return "rows not an object"
    bad = sorted(k for k, r in rows.items() if not isinstance(r, dict))
    return f"row {bad[0]} not an object" if bad else ""


LEDGER_V = 2   # the ledger file's format (brain.stateio), apart from SCAN_V: a better scanner rescans rows, it does
#                not make the ledger read-only for the engine before it


def ledger(write: bool = False) -> stateio.State:
    """The ledger under brain.stateio's policy (truth-local: the rows of deleted transcripts live only here; set
    aside only to write)."""
    return stateio.load(ledger_file(), known=LEDGER_V, check=_ledger_shape, aside=write)


def load() -> dict:
    """{transcript (relative): row}; {} without a ledger."""
    return ledger().data.get("rows") or {}


def save(rows: dict, state: stateio.State | None = None) -> None:
    stateio.save(state or ledger(write=True), {"rows": rows}, indent=None, separators=(",", ":"), sort_keys=False)


def main_transcripts() -> list[Path]:
    root = paths.projects_dir()
    return sorted(root.glob("*/*.jsonl")) if root.is_dir() else []


def update(prices: dict | None = None, rescan: bool = False) -> tuple[dict, int]:
    """The ledger brought up to date with the transcripts on this machine: (rows, sessions scanned). A row whose
    transcript is gone is kept. A ledger a newer brain wrote is read, brought up to date in memory, never saved."""
    st = ledger(write=True)
    rows = st.data.get("rows") or {}
    scanned = 0
    for f in main_transcripts():
        key = paths.relative_transcript(f)
        try:
            sig = sig_list(sig_of(f))
        except OSError:
            continue
        old = rows.get(key)
        if old and not rescan and old.get("sig") == sig and old.get("v") == SCAN_V:
            continue
        try:
            rows[key] = scan(f, prices)
        except OSError:
            continue
        scanned += 1
    if scanned and st.writable:
        try:
            save(rows, st)
        except (stateio.StateError, OSError) as exc:   # a newer brain wrote it meanwhile: the rows stay in memory
            print(f"brain usage: {exc}", file=sys.stderr)
    elif scanned:
        print(f"brain usage: {st.refusal()}", file=sys.stderr)
    return rows, scanned


def link_families(rows: list[dict]) -> dict[str, str]:
    """{child session: parent session}: a sub-session whose first prompt is the task a start_session call wrote."""
    by_key: dict[str, str] = {}
    for r in sorted(rows, key=lambda r: r.get("start") or ""):
        for k in r.get("spawned") or []:
            by_key.setdefault(k, r["session_id"])
    out = {}
    for r in rows:
        b = r.get("brief") or {}
        parent = by_key.get(b.get("key") or "") if b.get("side") else None
        if parent and parent != r["session_id"]:
            out[r["session_id"]] = parent
    return out


# --- windows and distributions ---

def parse_when(text: str | None, today: datetime) -> str:
    """``Nd``, ``Nw``, ``today``, ``yesterday``, ``last-week`` (7 days), ``last-month`` (30) or YYYY-MM-DD: a UTC
    day."""
    t = (text or "").strip().lower()
    d = today.date()
    if not t:
        return ""
    m = re.fullmatch(r"(\d+)([dw])", t)
    if m:
        return str(d - timedelta(days=int(m.group(1)) * (7 if m.group(2) == "w" else 1)))
    named = {"today": 0, "yesterday": 1, "last-week": 7, "last-month": 30}
    if t in named:
        return str(d - timedelta(days=named[t]))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t
    raise ValueError(f"{text!r}: Nd, Nw, today, yesterday, last-week, last-month or YYYY-MM-DD")


def in_window(row: dict, since: str, until: str) -> bool:
    """A session belongs to [since, until) when one of its days does."""
    return any((not since or d >= since) and (not until or d < until) for d in row.get("days") or {})


def cost_between(rows, start: datetime, end: datetime) -> float:
    """The API-price cost the sessions spent in [start, end), from their hourly buckets, a bucket cut at either end
    counted pro rata (its cost spread over its hour); a row scanned before the hours (SCAN_V 1, its transcript gone)
    from its days, spread over 24 h."""
    total = 0.0
    for r in rows:
        buckets, span = (r.get("hours"), 3600) if r.get("hours") is not None else (r.get("days"), 86400)
        for key, b in (buckets or {}).items():
            try:
                at = datetime.fromisoformat(key + (":00:00" if span == 3600 else "T00:00:00")).replace(
                    tzinfo=timezone.utc)
            except ValueError:
                continue
            lo, hi = max(at, start), min(at + timedelta(seconds=span), end)
            if hi > lo:
                total += (b.get("cost") or 0.0) * (hi - lo).total_seconds() / span
    return total


def quantiles(xs: list[float]) -> dict:
    """n, total, min, p25, median, p75, p90, max: the distribution, not only the mean."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {"n": 0, "total": 0.0}

    def q(p: float) -> float:
        if len(xs) == 1:
            return xs[0]
        k = (len(xs) - 1) * p
        lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)

    return {"n": len(xs), "total": round(sum(xs), 4), "min": round(xs[0], 4), "p25": round(q(0.25), 4),
            "median": round(statistics.median(xs), 4), "p75": round(q(0.75), 4), "p90": round(q(0.9), 4),
            "max": round(xs[-1], 4)}


def usd(x) -> str:
    if not isinstance(x, (int, float)):
        return "-"
    return f"${x:,.0f}" if x >= 100 else f"${x:,.2f}"


def ktok(n) -> str:
    if not isinstance(n, (int, float)):
        return "-"
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(int(n))


def hours(s) -> str:
    return f"{(s or 0) / 3600:.1f} h"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
