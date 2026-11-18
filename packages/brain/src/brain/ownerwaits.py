"""A wait on the owner said only in prose (wi-brain-owner-waits-check): brain check warns of an open work item whose
text says it waits on the owner while nothing the owner's queue reads carries it.

``brain next`` and ``brain queue`` list what waits on the owner from fields: an item's ``props.open`` (a question),
its ``props.external_blocker`` (a gesture of theirs) and the pending DDRs that name it (a choice with options),
:meth:`brain.waves.Plan.owner_waits`. A sentence such as « waits on <owner>'s install » in a progress note reaches
neither, so the wait falls through. This check reads an open item's title and its text props for the phrasings of a
wait, in English and French, and warns, never fails, with the ``brain item set`` command that records it.

The owner's names come from config.json (``identity.owner``, ``identity.display_name``), and « the owner » always
counts. What it leaves out, as history or the source of an idea rather than a wait:

- a closed item (done, dropped), and one whose wait is already a field;
- the props that record a past call: :data:`HISTORY_KEYS` and the keys that start with :data:`HISTORY_PREFIXES`;
- quoted text (« », “ ”, "", backticks): a phrase quoted is named, not said;
- a noun, « a wait on the owner », and a hyphenated compound, « waiting-on-the-owner time »;
- the owner named as a source (« <owner>, 2026-11-14: ... »), or as who decides in general (« <owner> decides »,
  « with <owner>'s go »): only the phrasings of :data:`PATTERNS` count.

A sentence that matches and is no wait (history, a condition to come) is marked once with
``props.owner_wait_checked`` (« DATE: why »): the check then leaves the item alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import config, waves

CHECKED = "owner_wait_checked"
HISTORY_KEYS = ("idea", "validated", "priority_reason", "size_reason", "created", CHECKED)
HISTORY_PREFIXES = ("decided", "answered", "split", "reframed")
_QUOTED = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"|`[^`]*`")
_VERBS_EN = ("runs|installs|answers|decides|approves|signs|tags|pushes|merges|confirms|chooses|reviews|adds|buys|"
             "creates|enables|restarts|replies|validates")
_TO_EN = ("run|install|answer|decide|approve|sign|tag|push|merge|confirm|choose|review|add|buy|create|enable|restart|"
          "reply|validate|move|rename")

# {N} and {N_FR}: the owner's names as one alternation, with « the owner » or « le propriétaire ».
PATTERNS = (
    r"(?<![Aa] )(?<![Tt]he )(?<!-)\b(?:waits?|waiting|awaits?|awaiting)\s+(?:on|for)\s+{N}\b(?!-)",
    r"\bblocked\s+(?:on|by)\s+{N}\b",
    r"\b(?:pending|awaiting|until|till)\s+{N}'s\s+\w+",
    r"\b(?:until|till|once)\s+{N}\s+(?:" + _VERBS_EN + r")\b",
    r"\b{N}\s+(?:still\s+)?(?:has|needs)\s+to\s+(?:" + _TO_EN + r")\b",
    r"\bsession\s+{N}\s+runs\b",
    r"\b{N}\s+runs\s+it\b",
    r"\b(?:left|next|remaining)\s*:\s*{N}\b",
    r"\b(?:attend(?:ent)?|en\s+attente)\b[^.;\n]{0,40}?\b{N_FR}\b",
    r"\bbloqu\w*\s+(?:par|sur)\b[^.;\n]{0,30}?\b{N_FR}\b",
    r"\b(?:jusqu'à\s+ce\s+que|dès\s+que)\s+{N_FR}\b",
    r"\b{N_FR}\s+(?:doit|devra)\b",
)


def names(root: Path | None = None) -> list[str]:
    """The owner's names in config.json (identity.owner, identity.display_name), « the owner » left out."""
    cfg = config.load(root)
    out = []
    for n in (config.owner(cfg), config.display_name(cfg)):
        if n and n != config.NO_OWNER and n not in out:
            out.append(n)
    return out


def compile_patterns(owner_names: list[str]) -> list[re.Pattern]:
    esc = [re.escape(n) for n in owner_names]
    en = "(?:" + "|".join(esc + [r"the\s+owner"]) + ")"
    fr = "(?:" + "|".join(esc + [r"(?:le|du)\s+propriétaire"]) + ")"
    return [re.compile(p.replace("{N}", en).replace("{N_FR}", fr), re.I) for p in PATTERNS]


def _texts(node: dict) -> list[tuple[str, str]]:
    """(where, text) of the item's title and its string props, the history ones left out."""
    out = [("title", str(node.get("title") or ""))]
    for k, v in (node.get("props") or {}).items():
        if isinstance(v, str) and k not in HISTORY_KEYS and not str(k).startswith(HISTORY_PREFIXES):
            out.append((f"props.{k}", v))
    return out


def _excerpt(text: str, start: int, end: int, around: int = 30) -> str:
    """The match with up to ``around`` characters each side, cut at words, an ellipsis where it was cut."""
    a, b = max(0, start - around), min(len(text), end + around)
    while a > 0 and not text[a - 1].isspace() and a < start:
        a += 1
    while b < len(text) and not text[b].isspace() and b > end:
        b -= 1
    out = " ".join(text[a:b].split())
    return ("…" if a > 0 else "") + out + ("…" if b < len(text) else "")


def said_wait(node: dict, pats: list[re.Pattern]) -> tuple[str, str] | None:
    """(where, an excerpt around the phrase) of the first wait on the owner the item's text says, None when it says
    none."""
    for where, text in _texts(node):
        bare = _QUOTED.sub(lambda m: " " * len(m.group(0)), text)   # same length: the excerpt's offsets hold
        for p in pats:
            m = p.search(bare)
            if m:
                return where, _excerpt(text, m.start(), m.end())
    return None


def findings(plan: waves.Plan, owner_names: list[str]) -> list[tuple[str, str, str]]:
    """(item, where, phrase) of each open item whose text says it waits on the owner while nothing the owner's
    queue reads carries it."""
    pats = compile_patterns(owner_names)
    out = []
    for nid in sorted(k for k in plan.nodes if plan.is_item(k)):
        node = plan.nodes[nid]
        if plan.status(nid) not in waves.OPEN or plan.owner_waits(nid) or (node.get("props") or {}).get(CHECKED):
            continue
        hit = said_wait(node, pats)
        if hit:
            out.append((nid, *hit))
    return out


def check_lines(store: Path, root: Path | None = None) -> list[str]:
    """brain check's warnings: one line per open item that says in prose only that it waits on the owner, with the
    command that records the wait."""
    who = names(root)
    owner = who[-1] if who else config.NO_OWNER
    return [f"warning: owner wait in prose only: {nid}: its {where} says « {phrase} », which brain next and brain "
            f"queue do not read: brain item set {nid} external_blocker=\"...\" (a gesture of {owner}'s) or "
            f"open=\"...\" (a question), or brain decision ask (a choice); history or a condition to come: brain "
            f"item set {nid} {CHECKED}=\"DATE: why\""
            for nid, where, phrase in findings(waves.load(store, root), who)]
