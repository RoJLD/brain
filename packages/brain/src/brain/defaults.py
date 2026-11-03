"""Decisions by default, then reviewed (wi-brain-decision-default; the owner's DEF-1 and SCALE-4).

A session may mark a decision low-stakes when it asks it (``brain decision ask --low-stakes``): the DDR gets a
``default`` (its recommendation and the time it becomes final, 24 h after it was asked). Then:

- the asking session applies the recommendation at once, provisionally; the DDR stays pending, the owner may answer
  it as any other;
- 24 h without an answer make it final (:func:`finalize`, run by ``brain refresh`` and ``brain decision defaulted
  --apply``): the recommendation is recorded as its answer, ``by: default``, ``via: default``, at the deadline (the
  same record on every branch that writes it), and the hooks announce it like any answer not integrated yet;
- every default lands in the review list the owner reads later to take note of it (``brain decision defaulted``, a
  line in the morning batch and in the cockpit); ``--seen`` marks it reviewed, from the owner's own terminal only;
- any default stays reversible: ``brain decision answer ID <option> --again``.

The mark is refused, at ``ask`` and by ``brain check`` (``brain record check``), on a decision whose text touches
money, keys, visibility, publication, accounts, arming, rules or scheduled tasks (:data:`REFUSED`, by words: a false
alarm only keeps the decision with the owner). Only the mark itself needs judgement.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOURS = 24
BY = VIA = "default"

# The topics a default never decides, by the words that name them (English and French).
REFUSED = {
    "money": r"money|price[sd]?|pricing|payments?|pay|paid|billing|invoices?|subscriptions?|purchases?|buy|bought|"
             r"refunds?|euros?|dollars?|€|\$\d|argent|prix|tarifs?|payer|paiements?|factures?|abonnements?|achats?|"
             r"acheter|rembours\w*",
    "keys": r"secrets?|passwords?|passphrases?|credentials?|(?:api|access|auth|bearer|github|gh) tokens?|"
            r"(?:private|ssh|age|gpg|pgp|recovery|device|api|signing) keys?|vault|clés?|clefs?|mots? de passe|"
            r"jetons? d'accès|identifiants?",
    "visibility": r"visibility|visibilité|public|publics|publique?s?|private|privée?s?",
    "publication": r"publish\w*|publication|releases?|tags?|tagg\w*|publier|publi[ée]e?s?|diffus\w*|newsletter|"
                   r"blog|tweet\w*",
    "accounts": r"accounts?|sign[ -]?up|log[ -]?in|comptes?|inscription",
    "arming": r"arm|arms|armed|arming|armer|armée?s?|wake-on-lan|wol|shutdown|reboot|redémarr\w*|boot",
    "rules": r"rules?|règles?|global\.md|claude\.md|agents\.md|guards?|gardes?|polic(?:y|ies)|politiques?",
    "scheduled tasks": r"scheduled[ -]tasks?|tâches? planifiées?|cron\w*|schtasks|systemd|services?|daemons?|"
                       r"timers?",
}
_RE = {k: re.compile(rf"(?<![\w-])(?:{v})(?![\w-])", re.I) for k, v in REFUSED.items()}


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def deadline(asked_at: str, hours: int = HOURS) -> str:
    return _iso(_parse(asked_at) + timedelta(hours=hours))


def _text(ddr: dict) -> str:
    parts = [ddr.get(k) or "" for k in ("title", "question", "context", "blocks")]
    for o in ddr.get("options") or []:
        parts += [o.get("label") or "", o.get("consequences") or "", o.get("risks") or ""]
    return " ".join(str(p) for p in parts)


def topics(ddr: dict) -> list[tuple[str, str]]:
    """(topic, the word that names it) for each refused topic the DDR's text touches."""
    text = _text(ddr)
    out = []
    for topic, rx in _RE.items():
        m = rx.search(text)
        if m:
            out.append((topic, m.group(0)))
    return out


def refusal(ddr: dict) -> str:
    """Why the DDR may not be marked low-stakes ('' when it may)."""
    hits = topics(ddr)
    if not hits:
        return ""
    return ("a decision on " + ", ".join(f"{t} ({w!r})" for t, w in hits) + " is never decided by default (DEF-1): "
            "ask it without --low-stakes")


def check(ddr: dict) -> list[str]:
    """brain check's errors for one DDR: the low-stakes mark where it is refused, or without its recommendation."""
    d = ddr.get("default")
    if not isinstance(d, dict):
        return []
    errors = []
    why = refusal(ddr)
    if why:
        errors.append(f"low-stakes mark refused: {why}")
    if d.get("option") != (ddr.get("recommendation") or {}).get("option"):
        errors.append(f"default.option {d.get('option')!r} is not the recommendation")
    return errors


def mark(ddr: dict, hours: int = HOURS) -> dict:
    """The DDR marked low-stakes (``ask --low-stakes``), or a QueueError-worthy ValueError with the refusal."""
    why = refusal(ddr)
    if why:
        raise ValueError(why)
    ddr["default"] = {"option": ddr["recommendation"]["option"], "after": deadline(ddr["asked"]["at"], hours)}
    return ddr


def is_due(ddr: dict, now: str) -> bool:
    d = ddr.get("default")
    return ddr.get("status") == "pending" and isinstance(d, dict) and bool(d.get("after")) and \
        _parse(d["after"]) <= _parse(now) and not refusal(ddr)


def finalize(root: Path, now: str) -> list[str]:
    """The pending low-stakes DDRs past their deadline, answered by default with their recommendation (at the
    deadline); their ids."""
    from . import decisions, records

    done = []
    for _, ddr in decisions.load(root):
        if not is_due(ddr, now):
            continue
        d = ddr["default"]
        ddr["answer"] = {"at": d["after"], "by": BY, "choices": [d["option"]], "via": VIA}
        ddr["status"] = "answered"
        records.write(root, "ddr", ddr, replace=True)
        done.append(ddr["id"])
    return done


def by_default(ddr: dict) -> bool:
    return (ddr.get("answer") or {}).get("via") == VIA


def _hours_left(after: str, now: str) -> int:
    return max(0, round((_parse(after) - _parse(now)).total_seconds() / 3600))


def review(root: Path, now: str) -> dict:
    """The review list: the defaults the owner has not reviewed yet, the ones still provisional, the ones reversed."""
    from . import decisions

    out = {"defaulted": [], "provisional": [], "reversed": [], "reviewed": 0}
    for _, ddr in decisions.load(root):
        d = ddr.get("default")
        if not isinstance(d, dict):
            continue
        e = {"id": ddr["id"], "title": ddr.get("title", ""), "option": d.get("option"), "after": d.get("after"),
             "status": ddr.get("status"), "options": [o.get("label") for o in ddr.get("options") or []]}
        ans = ddr.get("answer") or {}
        if ddr.get("status") == "pending":
            e["due"] = is_due(ddr, now)
            e["hours_left"] = _hours_left(d["after"], now) if d.get("after") else None
            out["provisional"].append(e)
        elif by_default(ddr):
            if d.get("reviewed"):
                out["reviewed"] += 1
            else:
                out["defaulted"].append(e)
        elif ans.get("at") and d.get("after") and ans["at"] > d["after"]:
            e["answer"] = list(ans.get("choices") or []) + ([f"other: {ans['other']}"] if ans.get("other") else [])
            out["reversed"].append(e)
    for k in ("defaulted", "provisional", "reversed"):
        out[k].sort(key=lambda e: (e.get("after") or "", e["id"]))
    return out


def seen(root: Path, ids: list[str], *, at: str, session: str = "") -> list[str]:
    """Mark defaults reviewed (the ones named, else every one not reviewed yet); their ids."""
    from . import decisions, records

    targets = [decisions.find(root, i)[1] for i in ids] if ids else \
        [d for _, d in decisions.load(root) if isinstance(d.get("default"), dict) and by_default(d)
         and not d["default"].get("reviewed")]
    done = []
    for ddr in targets:
        if not isinstance(ddr.get("default"), dict) or not by_default(ddr):
            raise decisions.QueueError(f"{ddr['id']} was not decided by default")
        ddr["default"]["reviewed"] = {"at": at, **({"session": session} if session else {})}
        records.write(root, "ddr", ddr, replace=True)
        done.append(ddr["id"])
    return done


def render(project: str, data: dict, width: int = 118) -> list[str]:
    from .queue import _cut

    lines = [f"{project}: {len(data['defaulted'])} decision(s) taken by default to review, "
             f"{len(data['provisional'])} provisional, {len(data['reversed'])} reversed"
             + (f", {data['reviewed']} reviewed" if data["reviewed"] else "")
             + ("; reverse one: brain decision answer ID <option> --again; read them all: --seen"
                if data["defaulted"] else "")]
    for e in data["defaulted"]:
        lines.append(_cut(f"  {e['id']}: {e['title']} -> {e['option']} (final {e['after']})", width))
    for e in data["provisional"]:
        when = "due now: brain refresh or --apply" if e.get("due") else f"final in {e.get('hours_left')} h"
        lines.append(_cut(f"  provisional {e['id']}: {e['title']} -> {e['option']} ({when}, unless answered)", width))
    for e in data["reversed"]:
        lines.append(_cut(f"  reversed {e['id']}: {e['title']}: {e['option']} -> {', '.join(e['answer'])}", width))
    return lines


def line(data: dict) -> str:
    """The one line of the morning batch and the cockpit ('' when nothing waits)."""
    n, p = len(data["defaulted"]), len(data["provisional"])
    if not n and not p:
        return ""
    return (f"Taken by default, to review: {n}" + (f" ({p} provisional)" if p else "")
            + " — brain decision defaulted")
