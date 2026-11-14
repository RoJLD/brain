"""Where a session ran (wi-brain-session-provenance; spec-brain-multi-agent-connector § 9, MA-5): the model's
**provider** (anthropic, bedrock, vertex, foundry...), the **harness** that ran the session (claude-code, cursor...),
and the **account** it ran on, by an alias the owner chose, with its **plan**. Zero token, standard library only.

Computed when a report is built (``brain usage``, ``brain status``), never written into a session record: the SR
keeps ``tool`` only (the SR fields come with wi-brain-sr-provenance-fields, a later item that moves the SR schema). For
a token-ledger row (:func:`of_row`), the first source that gives a value:

  provider  the row's own field (a newer scanner's, another harness's adapter); what the session's snapshot
            (``sessions/<id>.json``) holds; the account's ``provider`` in config.json; else the model's id
            (``us.anthropic.claude-...`` or an ARN: bedrock; ``claude-...@<date>``: vertex; ``claude-...``: anthropic).
  harness   the row's or the snapshot's ``harness``, else its ``tool`` (the SR's field today), else ``claude-code``
            (the one harness whose transcripts the engine reads today; another harness's reader comes with its
            adapter).
  account   the row's or the snapshot's; else the entry of config.json ``usage.accounts`` in force on the session's
            day (the latest ``since`` on or before it; an entry that names the session's harness first). The day is
            the UTC date the session started (YYYY-MM-DD): an account switched within a day takes that whole day
            (the entry whose ``since`` is that day), the sessions before the switch included.
  plan      the row's or the snapshot's; the account's ``plan``; else config.json ``usage.plans`` (the plan in force
            that day) when the owner set it.

An alias is a short name (``main``, ``team-2``), **never an e-mail address and never an account id**: an alias that
holds an ``@`` or looks like a UUID is never shown (:func:`safe_alias` drops it; a row that would carry one, from a
later scanner or another harness's adapter, shows as ``(masked)``) and a config.json that holds one is refused by its
schema. Nothing here reads Claude Code's account files or its telemetry: the alias is the
owner's configuration only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from . import usage

HARNESS = "claude-code"
FIELDS = ("provider", "harness", "account", "plan")
NONE = "(none)"
MASKED = "(masked)"
# The patterns of config.schema.json, matched whole (fullmatch: a trailing newline never passes;
# the schemas end on (?![\s\S]), which ECMA and Python read alike).
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")   # a provider's or a harness's id
_UUID = r"[0-9A-Fa-f]{8}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{12}"
# An alias: letters, digits, dot, dash, underscore; no account id (a UUID) anywhere in it; no '@', so never an e-mail
# address (config.schema.json usage.accounts[].alias).
ALIAS_RE = re.compile(rf"(?!.*{_UUID})[A-Za-z0-9][A-Za-z0-9._-]{{0,39}}", re.S)
PLAN_RE = re.compile(rf"(?!.*{_UUID})[^@\n\r]{{1,40}}", re.S)   # a plan's label: no '@', no UUID
DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")   # a since: the UTC day, YYYY-MM-DD
# Bedrock's model ids: an ARN, or anthropic.<model> with an inference profile's prefix (us., eu., apac., global.,
# us-gov....).
_BEDROCK_RE = re.compile(r"^(?:arn:aws[a-z-]*:bedrock|(?:[a-z]+(?:-[a-z]+)?\.)?anthropic\.)")


def safe_alias(value) -> str:
    """``value`` when it is an alias :data:`ALIAS_RE` takes whole, else '' (an e-mail address, an account id, anything
    else: never shown nor used)."""
    return value if isinstance(value, str) and ALIAS_RE.fullmatch(value) else ""


def _name(value) -> str:
    v = value.strip().lower() if isinstance(value, str) else ""
    return v if NAME_RE.fullmatch(v) else ""


def _plan(value) -> str:
    v = " ".join(value.split())[:40] if isinstance(value, str) else ""
    return v if v and PLAN_RE.fullmatch(v) else ""


def _absent(value) -> bool:
    """A value a report put in for what was unknown or hidden (:data:`NONE`, :data:`MASKED`): read as no value."""
    return value in (None, "", NONE, MASKED)


def provider_from_model(model) -> str:
    """The provider a model's id implies: bedrock (``us.anthropic.claude-...``, ``anthropic.claude-...``, an ARN),
    vertex (``claude-...@<date>``), anthropic (``claude-...``); '' for another id or none."""
    m = model.strip().lower() if isinstance(model, str) else ""
    if not m or m == "<synthetic>":
        return ""
    if _BEDROCK_RE.match(m):
        return "bedrock"
    if m.startswith("claude-"):
        return "vertex" if "@" in m else "anthropic"
    return ""


def accounts(cfg_usage) -> list[dict]:
    """config.json ``usage.accounts``, the entries usable here (an alias :func:`safe_alias` takes), oldest first."""
    rows = cfg_usage.get("accounts") if isinstance(cfg_usage, Mapping) else None
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, Mapping) or not safe_alias(r.get("alias")):
            continue
        since = r.get("since")
        if since is not None and not (isinstance(since, str) and DAY_RE.fullmatch(since)):
            continue   # a since that is not a UTC day (config.json --check says so): no day to compare
        out.append({"alias": r["alias"], "plan": _plan(r.get("plan")), "since": since or "",
                    "provider": _name(r.get("provider")), "harness": _name(r.get("harness"))})
    return sorted(out, key=lambda a: a["since"])


def account_on(day: str, accts: list[dict], harness: str = HARNESS, alias: str = "") -> dict:
    """The account ``alias`` names (its configured entry, else the alias alone), or the one in force on ``day``: the
    latest ``since`` on or before it among the entries that name ``harness``, else among those that name none; {}
    without one."""
    if alias:
        return next((a for a in accts if a["alias"] == alias), {"alias": alias})
    for want in (harness, ""):
        found: dict = {}
        for a in accts:   # oldest first: the last that matches wins
            if (not a["since"] or (day and a["since"] <= day)) and a["harness"] == want:
                found = a
        if found:
            return found
    return {}


def _plans(cfg_usage) -> tuple:
    """config.json ``usage.plans`` when the owner set it (never the engine's built-in default: a label it cannot know
    for another brain)."""
    rows = cfg_usage.get("plans") if isinstance(cfg_usage, Mapping) else None
    return tuple((str(r.get("since") or ""), str(r.get("plan") or "")) for r in rows if isinstance(r, Mapping)) \
        if isinstance(rows, list) else ()


def _plan_on(day: str, cfg_usage) -> str:
    plans = _plans(cfg_usage)
    return usage.plan_of(day, plans) if plans and day else ""


def _fill(given: Mapping, model: str, day: str, cfg_usage, accts: list[dict]) -> dict:
    """{provider, harness, account, plan}, '' where unknown: what ``given`` holds (a row's own fields, its snapshot's)
    first, then the account in force, the model's id."""
    h = _name(given.get("harness")) or HARNESS
    acct = account_on(day, accts, h, safe_alias(given.get("account")))
    return {"provider": _name(given.get("provider")) or acct.get("provider") or provider_from_model(model),
            "harness": h, "account": acct.get("alias") or "",
            "plan": _plan(given.get("plan")) or acct.get("plan") or _plan_on(day, cfg_usage)}


def captured(session_id: str) -> dict:
    """The provenance a session's snapshot (``<BRAIN_HOME>/sessions/<id>.json``, the Stop hook's SR) holds: its
    ``harness`` or ``tool`` today; its provider, account and plan once the SR carries them
    (wi-brain-sr-provenance-fields: the session's own environment, which a report cannot know). {} without one."""
    from . import paths

    if not session_id or not re.fullmatch(r"[A-Za-z0-9-]+", session_id):
        return {}
    try:
        data = json.loads((paths.sessions_dir() / f"{session_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {"provider": _name(data.get("provider")), "harness": _name(data.get("harness")) or _name(data.get("tool")),
           "account": safe_alias(data.get("account")), "plan": _plan(data.get("plan"))}
    return {k: v for k, v in out.items() if v}


def _model_of(row: Mapping) -> str:
    by_model = row.get("by_model")
    return row.get("model") or (next(iter(by_model), "") if isinstance(by_model, Mapping) else "")


def _own(row: Mapping) -> dict:
    """The provenance a row holds itself, :data:`NONE` and :data:`MASKED` read as absent (a row a report already
    annotated reads as the raw one); ``tool`` as the harness's fallback; an account as it is (checked by the caller)."""
    out = {k: _name(row.get(k)) for k in ("provider", "harness")}
    out["harness"] = out["harness"] or _name(row.get("tool"))
    out["plan"] = "" if _absent(row.get("plan")) else _plan(row.get("plan"))
    out["account"] = "" if _absent(row.get("account")) else row.get("account")
    return {k: v for k, v in out.items() if v}


def of_row(row: Mapping, cfg_usage=None, accts: list[dict] | None = None, snapshot: Mapping | None = None) -> dict:
    """{provider, harness, account, plan} of a token-ledger row (brain.usage) or a session record, read at report
    time: its own fields first (a newer scanner's, another harness's adapter), then ``snapshot``, what the session's
    Stop hook captured (:func:`captured`), then what config.json, its model
    and its day give; every key set (``(none)`` when unknown, ``(masked)`` for an account that is not an alias).
    Idempotent: a row it annotated reads the same again."""
    accts = accounts(cfg_usage) if accts is None else accts
    own = _own(row)
    masked = row.get("account") == MASKED or bool(own.get("account") and not safe_alias(own["account"]))
    given = {**(snapshot or {}), **own}
    if masked:   # never shown, nor taken for the day's account
        given.pop("account", None)
    out = _fill(given, _model_of(row), str(row.get("start") or "")[:10], cfg_usage, accts)
    if masked:
        out.update(account=MASKED, plan=own.get("plan", ""))
    return {k: out[k] or NONE for k in FIELDS}
