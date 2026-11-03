"""Read Claude Code transcripts (``~/.claude/projects/<project>/<session>.jsonl``), read only, at zero token.

The format is not a public API: every field is read with a default and an unknown record is skipped. Fields used,
checked on Claude Code 2.1.295 to 2.1.309 (2026-10-30):
- every record: ``type``, ``timestamp``, ``sessionId``; user and assistant records: ``cwd``, ``gitBranch``,
  ``version``, ``entrypoint``, ``isSidechain``;
- assistant: ``message.id``, ``message.model`` (``<synthetic>`` for local error messages), ``message.usage``
  (``input_tokens``, ``output_tokens``, ``output_tokens_details.thinking_tokens``, ``cache_read_input_tokens``,
  ``cache_creation_input_tokens``, ``cache_creation.ephemeral_1h_input_tokens`` / ``ephemeral_5m_input_tokens``,
  ``speed``), ``effort``, ``isApiErrorMessage``, and the ``tool_use`` blocks of ``message.content``. One API message
  is written as one record per content block, each repeating the same usage: tokens are summed once per message id;
- user: ``permissionMode``, ``isMeta``, ``toolUseResult`` (``gitOperation``: ``push.branch``,
  ``pr.number`` / ``pr.url`` / ``pr.action``, ``branch.ref`` / ``branch.action``);
- ``custom-title`` (``customTitle``), ``pr-link`` (``prNumber``, ``prUrl``, ``prRepository``), ``cost-state``
  (``totalCostUSD``), ``system`` with ``subtype`` ``compact_boundary``.
Subagents' transcripts, when there are any, are in ``<project>/<session>/subagents/agent-*.jsonl`` (a workflow's in
``subagents/workflows/<run>/``), each with an ``agent-*.meta.json`` (``agentType``); their records carry the parent
session's ``sessionId``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import paths, secretscan

TOKEN_KEYS = ("messages", "input", "output", "thinking", "cache_read", "cache_write", "cache_write_1h", "cache_write_5m")
GAP_S = 300  # a pause longer than this is not active time
# « Context budget: 600k », and in a Markdown brief « **Context budget:** 600k » (brain.usage reads it the same way)
_BUDGET_RE = re.compile(r"context budget\W{0,8}(\d+(?:[.,]\d+)?)\s*([km])\b", re.IGNORECASE)
_ITEM_CMD_RE = re.compile(r"\bbrain\s+item\s+(?:add|set|close)\s+((?:wi|ms|spec)-[a-z0-9-]+)")


def parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iter_records(path: str | Path, offset: int = 0):
    """(record, end offset) for each complete JSON line from ``offset``; a partial last line is left for later."""
    with open(path, "rb") as fh:
        fh.seek(offset)
        pos = offset
        for raw in fh:
            if not raw.endswith(b"\n"):
                break
            pos += len(raw)
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec, pos


def _usage_tokens(usage: dict) -> dict:
    cc = usage.get("cache_creation") or {}
    details = usage.get("output_tokens_details") or {}
    return {
        "messages": 1,
        "input": int(usage.get("input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
        "thinking": int(details.get("thinking_tokens") or 0),
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
        "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_write_1h": int(cc.get("ephemeral_1h_input_tokens") or 0),
        "cache_write_5m": int(cc.get("ephemeral_5m_input_tokens") or 0),
    }


def _add(total: dict, part: dict) -> None:
    for k in TOKEN_KEYS:
        total[k] = total.get(k, 0) + part.get(k, 0)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


class SessionStats:
    """Aggregates one session's transcript records; its state round-trips through JSON (incremental Stop hook)."""

    def __init__(self) -> None:
        self.session_id = ""
        self.offset = 0
        self.first_ts = ""
        self.last_ts = ""
        self.active_s = 0.0
        self.models: Counter = Counter()
        self.efforts: Counter = Counter()
        self.speeds: Counter = Counter()
        self.versions: list[str] = []
        self.permission_modes: list[str] = []
        self.folders: Counter = Counter()
        self.branches: Counter = Counter()
        self.surface = ""
        self.tokens: dict = {}
        self.tokens_by_model: dict[str, dict] = {}
        self.recent_ids: list[str] = []
        self.ctx_peak = 0
        self.ctx_last = 0
        self.compactions = 0
        self.budget: int | None = None
        self.user_texts_seen = 0
        self.title = ""
        self.cost_usd: float | None = None
        self.tools: Counter = Counter()
        self.prs: dict[str, dict] = {}
        self.items: list[str] = []
        self.api_errors = 0

    # --- state ---
    def to_state(self) -> dict:
        d = dict(self.__dict__)
        for k, v in d.items():
            if isinstance(v, Counter):
                d[k] = dict(v)
        return d

    @classmethod
    def from_state(cls, state: dict) -> "SessionStats":
        s = cls()
        for k, v in state.items():
            if hasattr(s, k):
                setattr(s, k, Counter(v) if isinstance(getattr(s, k), Counter) else v)
        return s

    # --- feeding ---
    def feed_file(self, path: str | Path) -> None:
        for rec, pos in iter_records(path, self.offset):
            self.feed(rec)
            self.offset = pos

    def _note_ts(self, ts: str | None) -> None:
        if not ts:
            return
        if not self.first_ts:
            self.first_ts = ts
        if self.last_ts:
            a, b = parse_ts(self.last_ts), parse_ts(ts)
            if a and b and b > a:
                gap = (b - a).total_seconds()
                self.active_s += gap if gap <= GAP_S else 0
        if ts > self.last_ts:
            self.last_ts = ts

    def _pr(self, repo: str, number: int, url: str = "", action: str = "") -> None:
        if not repo or not number:
            return
        key = f"{repo}#{number}"
        pr = self.prs.setdefault(key, {"repo": repo, "number": int(number), "url": url, "actions": []})
        if url and not pr["url"]:
            pr["url"] = url
        if action and action not in pr["actions"]:
            pr["actions"].append(action)

    def feed(self, rec: dict) -> None:
        t = rec.get("type")
        if not self.session_id and rec.get("sessionId"):
            self.session_id = rec["sessionId"]
        if t in ("user", "assistant", "attachment", "system"):
            self._note_ts(rec.get("timestamp"))
            if rec.get("cwd"):
                self.folders[rec["cwd"]] += 1
            if rec.get("gitBranch"):
                self.branches[rec["gitBranch"]] += 1
            v = rec.get("version")
            if v and v not in self.versions:
                self.versions.append(v)
            if rec.get("entrypoint") and not self.surface:
                self.surface = rec["entrypoint"]
        if t == "assistant":
            self._assistant(rec)
        elif t == "user":
            self._user(rec)
        elif t == "custom-title" and rec.get("customTitle"):
            self.title = rec["customTitle"]
        elif t == "pr-link":
            self._pr(rec.get("prRepository", ""), rec.get("prNumber") or 0, rec.get("prUrl", ""), "linked")
        elif t == "cost-state" and isinstance(rec.get("totalCostUSD"), (int, float)):
            self.cost_usd = float(rec["totalCostUSD"])
        elif t == "system" and rec.get("subtype") == "compact_boundary":
            self.compactions += 1

    def _assistant(self, rec: dict) -> None:
        msg = rec.get("message") or {}
        if rec.get("isApiErrorMessage"):
            self.api_errors += 1
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                self.tools[b.get("name", "?")] += 1
                cmd = (b.get("input") or {}).get("command")
                if isinstance(cmd, str):
                    for item in _ITEM_CMD_RE.findall(cmd):
                        if item not in self.items:
                            self.items.append(item)
        mid, model = msg.get("id"), msg.get("model")
        if not mid or model == "<synthetic>" or mid in self.recent_ids:
            return
        self.recent_ids = (self.recent_ids + [mid])[-64:]
        usage = msg.get("usage") or {}
        part = _usage_tokens(usage)
        _add(self.tokens, part)
        if model:
            self.models[model] += 1
            _add(self.tokens_by_model.setdefault(model, {}), part)
        if rec.get("effort"):
            self.efforts[rec["effort"]] += 1
        if usage.get("speed"):
            self.speeds[usage["speed"]] += 1
        ctx = part["input"] + part["cache_read"] + part["cache_write"]
        self.ctx_last = ctx
        self.ctx_peak = max(self.ctx_peak, ctx)

    def _user(self, rec: dict) -> None:
        pm = rec.get("permissionMode")
        if pm and pm not in self.permission_modes:
            self.permission_modes.append(pm)
        tur = rec.get("toolUseResult")
        if isinstance(tur, dict) and isinstance(tur.get("gitOperation"), dict):
            pr = tur["gitOperation"].get("pr")
            if isinstance(pr, dict) and pr.get("url"):
                m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", pr["url"])
                if m:
                    self._pr(m.group(1), int(m.group(2)), pr["url"], pr.get("action", ""))
        if self.budget is None and self.user_texts_seen < 5 and not rec.get("isMeta") and "toolUseResult" not in rec:
            text = _text_of((rec.get("message") or {}).get("content"))
            if text:
                self.user_texts_seen += 1
                m = _BUDGET_RE.search(text)
                if m:
                    n = float(m.group(1).replace(",", "."))
                    self.budget = int(n * (1_000 if m.group(2).lower() == "k" else 1_000_000))

    # --- output ---
    def record(self, transcript: str | Path | None = None, status: str = "open", summary: str = "",
               extra_items: list[str] | None = None, actions: list[str] | None = None,
               ddrs: list[str] | None = None, subagents: "SessionStats | None" = None,
               subagent_count: int = 0, end_reason: str = "") -> dict:
        """The SR for this session (schemas/sr.schema.json), after the secret scan."""
        sid = self.session_id or (Path(transcript).stem if transcript else "")
        start = self.first_ts or iso(datetime.now(timezone.utc))
        end = self.last_ts or start
        s, e = parse_ts(start), parse_ts(end)
        rec: dict = {
            "v": 1,
            "id": f"sr-{start[:10]}-{sid.replace('-', '')[:8].lower()}",
            "tool": "claude-code",
            "session_id": sid,
            "status": status,
        }
        if self.title:
            rec["title"] = self.title
        rec["summary"] = summary or self.title or ""
        if not rec["summary"]:
            del rec["summary"]
        if self.surface:
            rec["surface"] = self.surface
        if self.models:
            rec["model"] = self.models.most_common(1)[0][0]
            rec["models"] = dict(self.models.most_common())
        if self.versions:
            rec["versions"] = list(self.versions)
        if self.efforts:
            rec["effort"] = self.efforts.most_common(1)[0][0]
            rec["efforts"] = dict(self.efforts.most_common())
        if self.speeds:
            rec["speeds"] = dict(self.speeds.most_common())
        if self.permission_modes:
            rec["permission_modes"] = list(self.permission_modes)
        if self.folders:
            rec["folder"] = self.folders.most_common(1)[0][0]
            rec["folders"] = [f for f, _ in self.folders.most_common()]
        if self.branches:
            rec["branch"] = self.branches.most_common(1)[0][0]
            rec["branches"] = [b for b, _ in self.branches.most_common()]
        rec["start"], rec["end"] = start, end
        rec["duration_s"] = int((e - s).total_seconds()) if s and e else 0
        rec["active_s"] = int(self.active_s)
        rec["tokens"] = {k: self.tokens.get(k, 0) for k in TOKEN_KEYS}
        if self.tokens_by_model:
            rec["tokens_by_model"] = {m: {k: t.get(k, 0) for k in TOKEN_KEYS} for m, t in self.tokens_by_model.items()}
        rec["context"] = {"budget": self.budget, "peak": self.ctx_peak, "last": self.ctx_last,
                          "compactions": self.compactions}
        if self.cost_usd is not None:
            rec["cost_usd"] = round(self.cost_usd, 4)
        if self.tools:
            rec["tools"] = dict(self.tools.most_common())
        if self.prs:
            rec["prs"] = [{k: v for k, v in p.items() if v or k in ("repo", "number")} for p in self.prs.values()]
        if actions:
            rec["actions"] = sorted(set(actions))
        items = list(dict.fromkeys(self.items + (extra_items or [])))
        if items:
            rec["items"] = items
        if ddrs:
            rec["ddrs"] = sorted(set(ddrs))
        if subagents is not None and subagent_count:
            rec["subagents"] = {"count": subagent_count,
                                "tokens": {k: subagents.tokens.get(k, 0) for k in TOKEN_KEYS}}
        if self.api_errors:
            rec["api_errors"] = self.api_errors
        if end_reason:
            rec["end_reason"] = end_reason
        if transcript:
            rec["transcript"] = {"path": paths.relative_transcript(transcript), "archived": None}
        cleaned, _ = secretscan.clean(rec)
        return cleaned


def subagent_files(transcript: str | Path) -> list[Path]:
    """The session's subagents' transcripts: ``subagents/agent-*.jsonl``, and a workflow's under
    ``subagents/workflows/<run>/`` (its ``journal.jsonl`` is not a transcript)."""
    p = Path(transcript)
    d = p.with_suffix("") / "subagents"
    return sorted(d.rglob("agent-*.jsonl")) if d.is_dir() else []


def agent_type(subagent: str | Path) -> str:
    """A subagent's type, from the ``agent-<id>.meta.json`` beside its transcript ('' when there is none)."""
    p = Path(subagent)
    try:
        meta = json.loads(p.with_name(f"{p.stem}.meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(meta.get("agentType") or "") if isinstance(meta, dict) else ""


def session_stats(transcript: str | Path) -> tuple[SessionStats, SessionStats, int]:
    """(main stats, subagents' stats, number of subagent transcripts) from a full read."""
    main = SessionStats()
    main.feed_file(transcript)
    subs = SessionStats()
    files = subagent_files(transcript)
    for f in files:
        subs.offset = 0
        subs.feed_file(f)
    return main, subs, len(files)


def last_assistant(path: str | Path, max_bytes: int = 1 << 20) -> dict:
    """Model metadata of the latest assistant record (model, version, effort, cwd, branch, surface), from the
    file's tail only."""
    p = Path(path)
    try:
        size = p.stat().st_size
        with open(p, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            chunk = fh.read()
    except OSError:
        return {}
    for raw in reversed(chunk.split(b"\n")):
        if b'"assistant"' not in raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if rec.get("type") != "assistant":
            continue
        model = (rec.get("message") or {}).get("model")
        if model == "<synthetic>":
            continue
        out = {"model": model, "version": rec.get("version"), "effort": rec.get("effort"),
               "cwd": rec.get("cwd"), "branch": rec.get("gitBranch"), "surface": rec.get("entrypoint")}
        return {k: v for k, v in out.items() if v}
    return {}
