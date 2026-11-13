"""Where a session ran (wi-brain-session-provenance; spec-brain-multi-agent-connector § 9, MA-5): the model's
**provider** (anthropic, bedrock, vertex, foundry...), the **harness** that ran the session (claude-code, cursor...),
and the **account** it ran on, by an alias the owner chose, with its **plan**. Zero token, standard library only.

Where each value comes from, the first that gives one:

  provider  what the session captured (its snapshot, ``sessions/<id>.json``); in the Stop hook, the environment Claude
            Code runs with (``CLAUDE_CODE_USE_BEDROCK``, ``CLAUDE_CODE_USE_VERTEX``, ``CLAUDE_CODE_USE_FOUNDRY``); the
            account's ``provider`` in config.json; else the model's id (``us.anthropic.claude-...`` or an ARN: bedrock;
            ``claude-...@<date>``: vertex; ``claude-...``: anthropic).
  harness   the record's ``harness``, else its ``tool`` (the field it takes over, still written for older engines),
            else ``claude-code`` (the one harness whose transcripts the engine reads today; another harness's reader
            comes with its adapter).
  account   what the session captured; in the Stop hook, ``BRAIN_ACCOUNT`` (an alias, for an owner who runs two
            accounts on one machine); else the entry of config.json ``usage.accounts`` in force on the session's
            day (the latest ``since`` on or before it; an entry that names the session's harness first).
  plan      what the session captured; the account's ``plan``; else config.json ``usage.plans`` (the plan in force
            that day) when the owner set it.

An alias is a short name (``main``, ``team-2``), **never an e-mail address and never an account id**: an alias that
holds an ``@`` or looks like a UUID is never written (:func:`safe_alias` drops it) and an SR or a config.json that
holds one is refused by its schema. Nothing here reads Claude Code's account files or its telemetry: the alias is the
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
ACCOUNT_ENV = "BRAIN_ACCOUNT"
# Claude Code's switches to another provider (its third-party integrations), checked in this order.
PROVIDER_ENV = (("CLAUDE_CODE_USE_BEDROCK", "bedrock"), ("CLAUDE_CODE_USE_VERTEX", "vertex"),
                ("CLAUDE_CODE_USE_FOUNDRY", "foundry"))
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")   # a provider's or a harness's id (sr.schema.json)
# An alias: letters, digits, dot, dash, underscore; never an account id (a UUID); no '@', so never an e-mail address.
# The same pattern is in sr.schema.json (account) and config.schema.json (usage.accounts[].alias).
ALIAS_RE = re.compile(r"^(?![0-9A-Fa-f]{8}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4})[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
_BEDROCK_RE = re.compile(r"^(?:arn:aws[a-z-]*:bedrock|(?:[a-z]{2,4}\.)?anthropic\.)")


def safe_alias(value) -> str:
    """``value`` when it is an alias :data:`ALIAS_RE` takes, else '' (an e-mail address, an account id, anything
    else: never written)."""
    return value if isinstance(value, str) and ALIAS_RE.match(value) else ""


def _name(value) -> str:
    v = value.strip().lower() if isinstance(value, str) else ""
    return v if NAME_RE.match(v) else ""


def _plan(value) -> str:
    v = " ".join(value.split()) if isinstance(value, str) else ""
    return v[:40] if v and "@" not in v else ""


def _on(value) -> bool:
    return isinstance(value, str) and value.strip().lower() not in ("", "0", "false", "no", "off")


def provider_from_env(env: Mapping | None) -> str:
    """The provider Claude Code's environment switches to, '' when none is on (the first-party API)."""
    for var, provider in PROVIDER_ENV:
        if env and _on(env.get(var)):
            return provider
    return ""


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


def harness_of(record: Mapping) -> str:
    """A record's harness: ``harness``, else ``tool`` (read as a fallback), else :data:`HARNESS`."""
    return _name(record.get("harness")) or _name(record.get("tool")) or HARNESS


def accounts(cfg_usage) -> list[dict]:
    """config.json ``usage.accounts``, the entries usable here (an alias :func:`safe_alias` takes), oldest first."""
    rows = cfg_usage.get("accounts") if isinstance(cfg_usage, Mapping) else None
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, Mapping) or not safe_alias(r.get("alias")):
            continue
        out.append({"alias": r["alias"], "plan": _plan(r.get("plan")), "since": str(r.get("since") or ""),
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


def resolve(model: str, day: str, cfg_usage=None, env: Mapping | None = None, captured: Mapping | None = None,
            harness: str = "") -> dict:
    """{provider, harness, account, plan} for one session, each key only when known (the module's docstring says from
    where). ``env`` is the session's own environment (the Stop hook's), None elsewhere; ``captured`` what its snapshot
    holds."""
    captured = captured or {}
    accts = accounts(cfg_usage)
    h = _name(captured.get("harness")) or _name(harness) or HARNESS
    alias = safe_alias(captured.get("account")) or (safe_alias((env or {}).get(ACCOUNT_ENV)) if env else "")
    acct = account_on(day, accts, h, alias)
    out = {"provider": _name(captured.get("provider")) or provider_from_env(env) or acct.get("provider") or
           provider_from_model(model),
           "harness": h, "account": acct.get("alias") or ""}
    plans = _plans(cfg_usage)
    out["plan"] = _plan(captured.get("plan")) or acct.get("plan") or (usage.plan_of(day, plans) if plans and day
                                                                       else "")
    return {k: v for k, v in out.items() if v}


def captured(session_id: str) -> dict:
    """The provenance a session's snapshot (``<BRAIN_HOME>/sessions/<id>.json``, the Stop hook's) holds: what the
    session's own environment said, which a later rebuild from the transcript cannot know. {} without one."""
    from . import paths

    if not session_id or not re.match(r"^[A-Za-z0-9-]+$", session_id):
        return {}
    try:
        data = json.loads((paths.sessions_dir() / f"{session_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {"provider": _name(data.get("provider")), "harness": _name(data.get("harness")),
           "account": safe_alias(data.get("account")), "plan": _plan(data.get("plan"))}
    return {k: v for k, v in out.items() if v}


def for_session(model: str, day: str, root=None, env: Mapping | None = None, session_id: str = "") -> dict:
    """:func:`resolve` with config.json's ``usage`` (brain.config) and the session's snapshot; never raises (a
    configuration that does not load gives what the model says)."""
    try:
        from . import config

        cfg_usage = config.load(root).data.get("usage")
    except Exception:  # noqa: BLE001 - a bad configuration never costs a record its provenance
        cfg_usage = None
    return resolve(model, day, cfg_usage, env=env, captured=captured(session_id))


def of_row(row: Mapping, cfg_usage=None, accts: list[dict] | None = None) -> dict:
    """{provider, harness, account, plan} of a token-ledger row (brain.usage) or a session record, read at report
    time: its own fields first (a newer scanner's, another harness's adapter), else what its model and day give;
    every key set (``(none)`` when unknown, ``(masked)`` for an account that is not an alias)."""
    accts = accounts(cfg_usage) if accts is None else accts
    h = harness_of(row)
    day = str(row.get("start") or "")[:10]
    model = row.get("model") or ""
    if not model and isinstance(row.get("by_model"), Mapping) and row["by_model"]:
        model = next(iter(row["by_model"]))
    raw = row.get("account")
    alias = safe_alias(raw)
    acct = {"alias": alias} if alias else account_on(day, accts, h)
    if alias:
        acct = next((a for a in accts if a["alias"] == alias), acct)
    plans = _plans(cfg_usage)
    plan = _plan(row.get("plan")) or acct.get("plan") or (usage.plan_of(day, plans) if plans and day else "")
    return {"provider": _name(row.get("provider")) or acct.get("provider") or provider_from_model(model) or NONE,
            "harness": h,
            "account": MASKED if raw and not alias else acct.get("alias") or NONE,
            "plan": plan or NONE}

