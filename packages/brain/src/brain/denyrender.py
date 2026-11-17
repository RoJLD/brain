"""The deny list rendered for another scanner (wi-brain-deny-gitleaks-render): config.json ``public.deny`` (its groups
people, users, hosts, repos, paths), with the terms the brain derives from its registries (brain.denylist) and the
scope tree's (public.deny_from_tree), as one source for a repo's private-name scan instead of a second, hand-kept list.

``brain public deny render --format gitleaks`` prints the plan (the file, its rules and terms by category, whether it
would change); ``--apply`` writes it, atomically (a temporary file, then a rename), only when it changed, with mode 600
on POSIX (on Windows the folder's own ACL: the owner's profile), and only outside any git repository: the file names the private
terms, so it never sits in a checkout. Its default place is ``$XDG_CONFIG_HOME/brain/gitleaks-private-patterns.toml``
(``~/.config/brain/...``); ``--out`` names another.

The gitleaks configuration it renders stands alone by default: gitleaks' own default configuration carries global
allowlists (lock files, images, vendored folders, ``true``, ``false``, ``null`` and system paths) that would hide some
terms, so a repo runs it as a pass of its own. ``--extend PATH`` (a repo's ``.gitleaks.toml``, made absolute) extends
another configuration instead, whose global allowlists then apply to these rules too. Then one rule per category,
``brain-private-<category>``, whose regex holds every term of it the way brain.public matches them (case aside, ``/``
and ``\\`` alike, a separator ``-``, ``_`` or a space in every spelling, none included, whole words), written for
gitleaks' Go regexp engine (RE2: no lookaround, so the word's edges are matched and the term is the secret group), and
whose keywords are each term's longest part (gitleaks' fast prefilter). The owner then updates a CI secret from the
file themselves (docs/vault.md's rule: no session reads or writes a key).
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

from . import config

FORMATS = ("gitleaks",)
FILE_NAME = "gitleaks-private-patterns.toml"
RULE_PREFIX = "brain-private-"
SEPARATORS = re.compile(r"[-_ ]+")
RE2_SPECIAL = set("\\.+*?()|[]{}^$")


class RenderError(Exception):
    """The file cannot be rendered or written as asked; the message names the fix."""


def default_out(env=None) -> Path:
    """$XDG_CONFIG_HOME/brain/gitleaks-private-patterns.toml, else ~/.config/brain/..."""
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "brain" / FILE_NAME


def re2_escape(text: str) -> str:
    """``text`` as a literal in a Go (RE2) regexp: its special characters escaped, nothing else (RE2 refuses an
    escaped letter or space)."""
    return "".join("\\" + c if c in RE2_SPECIAL else c for c in text)


def term_re2(term: str) -> str:
    """A deny term's regexp body for RE2, as brain.boundary.term_body reads it: ``/`` and ``\\`` alike, its inner
    separators in every spelling (none included), its ends literal."""
    term = term.replace("\\", "/")
    m = re.match(r"^([-_ ]*)(.*?)([-_ ]*)$", term, re.S)
    lead, core, tail = m.groups()
    parts = [p for p in SEPARATORS.split(core) if p]
    if not parts:
        return _slashes(re2_escape(term))
    return _slashes(re2_escape(lead) + "[-_ ]*".join(re2_escape(p) for p in parts) + re2_escape(tail))


def _slashes(body: str) -> str:
    return body.replace("/", "[/\\\\]")


WORD = __import__("re").compile(r"[A-Za-z0-9_]")


def bounded(term: str) -> str:
    """The term's regexp with zero-width edges, as term_regex's lookarounds (no word character beside it): ``\\b``
    where its end is a word character, ``\\B`` where it is not (RE2's are ASCII, as brain.boundary's class); a match
    consumes no neighbour, so a term right after another is found too."""
    t = term.replace("\\", "/")
    edge = lambda c: "\\b" if WORD.match(c) else "\\B"
    return f"{edge(t[0])}{term_re2(term)}{edge(t[-1])}" if t else ""


def keyword(term: str) -> str:
    """The term's longest part between separators and slashes, lower case: in every spelling the term matches."""
    parts = [p for p in re.split(r"[-_ /\\]+", term) if p]
    return max(parts, key=len).lower() if parts else term.lower()


def toml_str(text: str) -> str:
    """``text`` as a TOML basic string: quotes, backslashes and control characters escaped."""
    out = []
    for c in text:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\t":
            out.append("\\t")
        elif c == "\r":
            out.append("\\r")
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\u{ord(c):04X}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


def by_category(cfg: config.Config) -> dict[str, list[str]]:
    """{category: [terms]} in public.deny's order, derived terms included (config.deny_terms); a derivation that
    cannot be read raises RenderError (the file is never shorter than the list the guards hold)."""
    from . import denylist
    why = config.unexpected(cfg)   # a configuration the guards cannot trust renders nothing (never a shorter file)
    if why:
        raise RenderError(f"the configuration cannot be trusted: {why}")
    try:
        denylist.terms(cfg)
    except denylist.DeriveError as exc:
        raise RenderError(f"the deny terms cannot be derived: {exc}") from exc
    out: dict[str, list[str]] = {}
    for cat, term in config.deny_terms(cfg):
        out.setdefault(cat, []).append(term)
    return out


def gitleaks(terms: dict[str, list[str]], extend: str | None = None) -> str:
    """The gitleaks configuration for ``terms`` ({category: [terms]})."""
    lines = ["# Rendered by brain public deny render --format gitleaks from config.json public.deny (and the terms",
             "# the brain derives): the private names a commit must not hold. Do not edit: render it again.",
             "# It names private terms: keep it outside any repository, readable by its owner only.",
             'title = "brain private patterns"']
    if extend:   # its global allowlists then apply to these rules too (docs: a pass of its own is the safe use)
        lines += ["", "[extend]", f"path = {toml_str(extend)}"]
    for cat in sorted(terms, key=lambda c: list(config.DENY).index(c) if c in config.DENY else 99):
        uniq = sorted({t for t in terms[cat] if t}, key=lambda t: (-len(t), t.lower()))
        if not uniq:
            continue
        body = "|".join(bounded(t) for t in uniq)
        regex = f"(?i)({body})"
        kws = sorted({keyword(t) for t in uniq})
        if not all(k.isascii() for k in kws):   # Go lower-cases otherwise than Python: no keyword, the rule always runs
            kws = []
        lines += ["", "[[rules]]", f"id = {toml_str(RULE_PREFIX + cat)}",
                  f"description = {toml_str(f'a private name of config.json public.deny {cat}')}",
                  f"regex = {toml_str(regex)}", "secretGroup = 1",
                  *(["keywords = [" + ", ".join(toml_str(k) for k in kws) + "]"] if kws else []),
                  f"tags = [{toml_str('brain')}, {toml_str('private-name')}, {toml_str(cat)}]"]
    return "\n".join(lines) + "\n"


def in_repo(path: Path) -> Path | None:
    """The git repository (its top folder) that holds ``path``, else None: a .git, folder or file, above it."""
    for d in [path.parent, *path.parent.parents]:
        if (d / ".git").exists():
            return d
    return None


def plan(cfg: config.Config, out: Path, extend: str | None = None, fmt: str = "gitleaks") -> dict:
    """{out, format, rules: {category: count}, terms, text, state: new|changed|unchanged, refused: ''|why}."""
    if fmt not in FORMATS:
        raise RenderError(f"unknown format {fmt!r} (one of {', '.join(FORMATS)})")
    terms = by_category(cfg)
    text = gitleaks(terms, extend)
    try:
        current = out.read_text(encoding="utf-8") if out.is_file() else None
    except OSError:
        current = None
    repo = in_repo(out.resolve())
    return {"out": str(out), "format": fmt, "rules": {c: len(set(v)) for c, v in terms.items() if v},
            "terms": sum(len(set(v)) for v in terms.values()), "text": text,
            "state": "new" if current is None else "unchanged" if current == text else "changed",
            "refused": f"{out} is inside the git repository {repo}: the file names private terms" if repo else ""}


def apply(p: dict) -> str:
    """Write the planned file (atomic, mode 600 on POSIX) unless it is unchanged or refused; what was done."""
    if p["refused"]:
        raise RenderError(p["refused"])
    out = Path(p["out"])
    if p["state"] == "unchanged":
        if os.name != "nt" and stat.S_IMODE(out.stat().st_mode) != 0o600:
            os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)
            return "unchanged, its mode set to 600"
        return "unchanged"
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".brain-deny-", dir=str(out.parent))
    try:
        if os.name != "nt":
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(p["text"])
        os.replace(tmp, out)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if os.name != "nt":
        os.chmod(out, stat.S_IRUSR | stat.S_IWUSR)
    return "written"


def render_plan(p: dict) -> list[str]:
    """The plan in words: never the terms themselves (a session's transcript would keep them)."""
    rules = ", ".join(f"{c} {n}" for c, n in p["rules"].items()) or "none"
    lines = [f"deny render ({p['format']}): {p['out']}",
             f"  rules     {len(p['rules'])} ({rules}), {p['terms']} terms",
             f"  file      {p['state']}" + ("" if p["state"] == "unchanged" else
                                               " (--apply writes it" + (", mode 600)" if os.name != "nt" else
                                                                       " in your profile's folder)"))]
    if p["refused"]:
        lines.append(f"  refused   {p['refused']}: --out a path outside any repository")
    return lines
