"""Decisions by default, then reviewed (wi-brain-decision-default; the owner's DEF-1 and SCALE-4).

A session may mark a decision low-stakes when it asks it (``brain decision ask --low-stakes``): the DDR gets a
``default`` (its recommendation and the time it becomes final, 24 h after it was asked). Then:

- the asking session applies the recommendation at once, provisionally; the DDR stays pending, the owner may answer
  it as any other;
- 24 h without an answer make it final (:func:`finalize`, run by ``brain refresh`` and ``brain decision defaulted
  --apply``): the recommendation is recorded as its answer, ``by: default``, ``via: default``, at the deadline (the
  same record on every branch that writes it), and the hooks announce it like any answer not integrated yet; a DDR
  whose answer the question tool captured before the deadline (the machine's answer ledger, brain.answers) is left
  pending for ``brain decision answer --captured``, and that command replaces a default taken meanwhile by such an
  answer;
- every default lands in the review list the owner reads later to take note of it (``brain decision defaulted``, a
  line in the morning batch and in the cockpit); ``--seen`` marks it reviewed, from the owner's own terminal only;
  a low-stakes DDR answered otherwise than its default after the deadline is listed ``reversed`` until ``--seen``
  marks it reviewed after that answer;
- any default stays reversible: ``brain decision answer ID <option> --again``.

The mark is refused, at ``ask`` and by ``brain check`` (``brain record check``), on a decision whose text touches
money, keys, visibility, publication, accounts, arming, rules or scheduled tasks (:data:`REFUSED`, by words, also
inside hyphenated and snake_case compounds, and amounts with a currency sign: a false alarm only keeps the decision
with the owner). The text is the title, question, context, blocks, options, the recommendation's why and the linked
ids. Only the mark itself needs judgement.
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
             r"refunds?|euros?|eur|dollars?|usd|costs?|costing|coûts?|budgets?|spend\w*|spent|fees?|frais|"
             r"dépenses?|argent|prix|tarifs?|payer|paiements?|factures?|abonnements?|achats?|acheter|rembours\w*",
    "keys": r"secrets?|passwords?|passphrases?|credentials?|"
            r"(?:api|access|auth|bearer|github|gh|hf|deploy|oauth|refresh|pypi) ?tokens?|[a-z0-9]+_tokens?|"
            r"(?:private|ssh|age|gpg|pgp|recovery|device|api|signing|deploy|access) ?keys?|[a-z0-9]+_keys?|vault|"
            r"clés?|clefs?|mots? de passe|jetons? d'accès|identifiants?",
    "visibility": r"visibility|visibilité|public|publics|publique?s?|private|privée?s?|open ?source",
    "publication": r"publish\w*|publication|releases?|tags?|tagg\w*|publier|publi[ée]e?s?|diffus\w*|newsletter|"
                   r"blog|tweet\w*|pypi|npm",
    "accounts": r"accounts?|sign ?up|sign ?in|log ?in|comptes?|inscription",
    "arming": r"arm|arms|armed|arming|armer|armée?s?|wake-on-lan|wol|shut ?down|reboot|restart\w*|power ?off|"
              r"redémarr\w*|boot",
    "rules": r"rules?|règles?|global\.md|claude\.md|agents\.md|guards?|gardes?|polic(?:y|ies)|politiques?|"
             r"permissions\.yaml|settings(?:\.local)?\.json",
    "scheduled tasks": r"scheduled tasks?|task scheduler|tâches? planifiées?|cron\w*|schtasks|systemd|services?|"
                       r"daemons?|timers?",
}
# A word of REFUSED counts where it is not inside a longer word: '-' and '_' separate words here, so that 'ssh-key',
# 'API_KEY', 'cron-job' or an id such as 'wi-nightly-billing' are read; a space inside an alternative also matches '-'
# and '_' ('sign-in', 'deploy_key'). A currency sign next to an amount counts as it is ('40€', '$50', '€ 5').
_SEP = r"[ _-]"
_RE = {k: re.compile(rf"(?<![^\W_])(?:{v.replace(' ', _SEP)})(?![^\W_])", re.I) for k, v in REFUSED.items()}
_AMOUNT = re.compile(r"[€$£]\s?\d|\d\s?(?:k\s?)?[€$£]", re.I)


def _parse(stamp: str) -> datetime:
    """A stamp as an aware datetime: one without a zone (a hand edit, ``--at 2026-11-05T10:00``) is UTC."""
    when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def before(a: str, b: str) -> bool:
    """True when the stamp ``a`` is strictly earlier than ``b`` (compared as times, not strings)."""
    return _parse(a) < _parse(b)


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def deadline(asked_at: str, hours: int = HOURS) -> str:
    return _iso(_parse(asked_at) + timedelta(hours=hours))


def _text(ddr: dict) -> str:
    parts = [ddr.get(k) or "" for k in ("title", "question", "context", "blocks")]
    for o in ddr.get("options") or []:
        parts += [o.get("label") or "", o.get("consequences") or "", o.get("risks") or ""]
    rec = ddr.get("recommendation")
    parts.append((rec.get("why") or "") if isinstance(rec, dict) else "")
    links = ddr.get("links")
    for ids in (links.values() if isinstance(links, dict) else []):
        parts += [str(i) for i in ids] if isinstance(ids, list) else [str(ids)]
    return " ".join(str(p) for p in parts)


def topics(ddr: dict) -> list[tuple[str, str]]:
    """(topic, the word that names it) for each refused topic the DDR's text touches."""
    text = _text(ddr)
    out = []
    for topic, rx in _RE.items():
        m = rx.search(text) or (_AMOUNT.search(text) if topic == "money" else None)
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


def answered_in_time() -> dict[str, str]:
    """The DDRs whose answer the question tool captured on this machine (brain.answers' ledger), each with its
    earliest capture: an answer, a label that names an option (not the placeholder of a question the owner did not
    answer, nor a label that names none)."""
    from . import answers

    out: dict[str, str] = {}
    for c in answers.read(answers.CAPTURED):
        if c.get("ddr") and c.get("at") and not answers.refused(c):
            out[c["ddr"]] = min(out.get(c["ddr"]) or c["at"], c["at"])
    return out


def finalize(root: Path, now: str) -> list[str]:
    """The pending low-stakes DDRs past their deadline, answered by default with their recommendation (at the
    deadline); their ids. A DDR the owner answered through the question tool before the deadline is left pending:
    ``brain decision answer --captured`` records that answer."""
    from . import decisions, records

    done = []
    captured = None
    for _, ddr in decisions.load(root):
        if not is_due(ddr, now):
            continue
        captured = answered_in_time() if captured is None else captured
        if ddr["id"] in captured and before(captured[ddr["id"]], ddr["default"]["after"]):
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
        elif reversed_(ddr):
            e["answer"] = list(ans.get("choices") or []) + ([f"other: {ans['other']}"] if ans.get("other") else [])
            out["reversed"].append(e)
    for k in ("defaulted", "provisional", "reversed"):
        out[k].sort(key=lambda e: (e.get("after") or "", e["id"]))
    return out


def reversed_(ddr: dict) -> bool:
    """A low-stakes DDR answered otherwise than its default once the deadline had passed (the default reversed),
    not reviewed since that answer: by what it holds and with stamps compared as times, never as strings. An answer
    before the deadline (the question tool's capture included) is the owner's in time, not a reversal."""
    d, ans = ddr.get("default"), ddr.get("answer") or {}
    if not isinstance(d, dict) or ddr.get("status") == "pending" or not ans or by_default(ddr):
        return False
    if not (ans.get("at") and d.get("after")) or before(ans["at"], d["after"]):
        return False
    if list(ans.get("choices") or []) == [d.get("option")] and not ans.get("other"):
        return False   # the owner answered what the default would have taken: nothing was reversed
    seen_at = (d.get("reviewed") or {}).get("at") if isinstance(d.get("reviewed"), dict) else None
    return not (seen_at and ans.get("at") and not before(seen_at, ans["at"]))


def seen(root: Path, ids: list[str], *, at: str, session: str = "") -> list[str]:
    """Mark defaults reviewed (the ones named, else every one not reviewed yet), and the reversed ones; their ids.
    Every id named is checked before anything is written."""
    from . import decisions, records

    def pending_review(d: dict) -> bool:
        return isinstance(d.get("default"), dict) and ((by_default(d) and not d["default"].get("reviewed"))
                                                       or reversed_(d))

    targets = [decisions.find(root, i)[1] for i in ids] if ids else \
        [d for _, d in decisions.load(root) if pending_review(d)]
    wrong = [d["id"] for d in targets if not isinstance(d.get("default"), dict) or
             not (by_default(d) or reversed_(d))]
    if wrong:
        raise decisions.QueueError(f"{', '.join(wrong)}: not decided by default (nor reversed): nothing marked")
    done = []
    for ddr in targets:
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


def total_line(roots, now: str) -> str:
    """The cockpit's line for several projects (their roots): the defaults to review and the provisional ones."""
    data = {"defaulted": [], "provisional": []}
    for root in roots:
        if (Path(root) / "records" / "ddr").is_dir():
            got = review(Path(root), now)
            data["defaulted"] += got["defaulted"]
            data["provisional"] += got["provisional"]
    return line(data)


def line(data: dict) -> str:
    """The one line of the morning batch and the cockpit ('' when nothing waits)."""
    n, p = len(data["defaulted"]), len(data["provisional"])
    if not n and not p:
        return ""
    return (f"Taken by default, to review: {n}" + (f" ({p} provisional)" if p else "")
            + " — brain decision defaulted")
