"""The review before the report (wi-brain-review-step; the owner's RETRO-1, RETRO-2 and RETRO-9 of 2026-11-03).

A session that opens a PR carrying code, a procedure, a hook, the installer, a schema or the engine's docs reviews it
before it reports, with three or four lens agents and two skeptics per distinct finding (docs/review.md). What can be
gathered without a model is gathered here, at zero token:

- ``brain review prep [PR | BASE..HEAD]`` writes the packet: the diff, the touched files at the head, the scout's
  output (``brain audit --diff``), the lenses chosen from the touched surfaces, and a README that says how to run them;
- ``brain review stamp HEAD --findings N --fixed M [--contested K] [--note FILE]`` records that the review ran on that
  head, with its counts (the error score's record, wi-brain-review-error-score);
- ``brain review check HEAD`` says whether that head was reviewed: the merge gate's question (wi-brain-merge-gate).

A stamp is keyed by the head's full sha: a push after the review is a new head, reviewed again.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import paths

FOLDER = "reviews"
MAX_FILE = 400_000   # a touched file larger than this is listed, not copied

# The error score (wi-brain-review-error-score): a review note's finding lines, « - high correctness A.b fixed: ... »
FINDING = re.compile(r"^\s*[-*]\s+([^:]+?):\s+(.*)$")
SEVERITIES = ("high", "medium", "low")
VOCABULARY = {"severity": SEVERITIES, "outcome": ("fixed", "contested", "open", "refuted"),
              "when": ("before", "after"), "covered": ("covered", "uncovered")}
# The root-cause families of the waves retro of 2026-11-03: A (the brief: a. data from before, b. failure and
# degraded paths, c. an invariant held in one path only, d. a contract assumed, e. text against code), B shared append
# points, C the environment, D the child-coordinator blind spots, E unsafe write defaults, F hand-typed facts.
CAUSE = re.compile(r"A(\.[a-e])?|[B-F]")
FIELDS = ("severity", "lens", "cause", "outcome", "when", "covered")
PLACES = ("pr", "item", "stream", "wave", "repo_slug")   # where a stamp is placed for the score
FALLS = 2   # the reviews lighten once the findings per PR fall over this many waves in a row

# The lenses, each chosen by the surfaces a diff touches: (name, what it asks, path patterns). "correctness" always.
LENSES = [
    ("correctness", "what input, state or timing makes a changed line wrong; what the diff removes and where the "
                    "invariant it kept is held now; every caller of a changed function", ()),
    ("security", "what a guard lets through that it refused, a secret or a private name that could leave, a command "
                 "built from data", (r"guards?\.py$", r"(^|/)hooks/", r"secret", r"public", r"permissions")),
    ("compatibility", "what an older engine reading the new data does, what a newer file does to this engine, a "
                      "format or schema that moves without its fixture, an upgrade step not said",
     (r"(^|/)schemas/", r"formats", r"stateio", r"projects\.py$", r"config\.py$", r"(^|/)templates/", r"fixtures/formats")),
    ("install and upgrade", "a step the installer, brain update or the version PR now needs, a machine on the older "
                            "engine, a rollback", (r"(^|/)installer/", r"update\.py$", r"install", r"release")),
    ("procedure", "an optional step written as a required one, a step that cannot fail safe, a rule a script could "
                  "hold instead", (r"(^|/)procedures/", r"rules", r"SKILL\.md$")),
    ("tests", "a test that cannot fail on what it claims, a test that reads the owner's data or the network, a "
              "behaviour changed with no test", (r"(^|/)tests/", r"conftest")),
    ("docs", "a doc that says what the code no longer does, a command or option undocumented, the CHANGELOG's "
             "fragment missing or in the wrong section", (r"\.md$", r"(^|/)docs/", r"(^|/)changes/")),
]


class ReviewError(Exception):
    """The target cannot be resolved (no such PR, no such commit)."""


@dataclass
class Packet:
    base: str
    head: str
    files: list[str]
    lenses: list[str]
    folder: str
    scout_rc: int | None = None
    notes: list[str] = field(default_factory=list)
    standards: list[str] = field(default_factory=list)   # the standards lens: the project's review-lens rows


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise ReviewError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def resolve(repo: Path, target: str) -> tuple[str, str]:
    """(base sha, head sha) of ``target``: a PR number (gh), ``BASE..HEAD``, or '' for origin/main..HEAD."""
    if target.isdigit():
        r = subprocess.run(["gh", "pr", "view", target, "--json", "baseRefName,headRefOid"], cwd=repo,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            raise ReviewError(f"PR {target}: {(r.stderr or r.stdout).strip()}")
        info = json.loads(r.stdout)
        base, head = f"origin/{info['baseRefName']}", info["headRefOid"]
    else:
        base, _, head = (target or "origin/main..HEAD").partition("..")
        head = head or "HEAD"
    try:
        head_sha = _git(repo, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
        base_sha = _git(repo, "merge-base", base, head_sha).strip()
    except ReviewError as exc:
        raise ReviewError(f"{target or 'origin/main..HEAD'}: {exc} (git fetch first)") from None
    return base_sha, head_sha


def lenses_for(files: list[str]) -> list[str]:
    """The lenses the touched ``files`` call for, in LENSES' order; correctness always."""
    out = []
    for name, _, patterns in LENSES:
        if not patterns or any(re.search(p, f) for p in patterns for f in files):
            out.append(name)
    return out


def folder_for(head: str) -> Path:
    return paths.brain_home() / FOLDER / head[:12]


def _scout(repo: Path, base: str, head: str) -> tuple[int | None, str]:
    """``brain audit --diff BASE..HEAD``'s output, run from the repo (its rc; None when it could not run)."""
    try:
        r = subprocess.run([sys.executable, "-m", "brain", "--root", str(repo), "audit", "--diff", f"{base}..{head}"],
                           cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"the scout could not run: {exc}"
    return r.returncode, (r.stdout + r.stderr).strip()


def _readme(p: Packet) -> str:
    asks = {name: ask for name, ask, _ in LENSES}
    lines = [f"# Review packet: {p.head[:12]} (base {p.base[:12]})", "",
             "Written by `brain review prep` at zero token. The procedure is the engine's docs/review.md:", "",
             "1. One agent per lens below, in parallel, each given `diff.patch`, `files/` and `scout.txt`, asked "
             "for findings with a file, a line and a concrete failure scenario.",
             "2. Deduplicate the findings (same defect, same place).",
             "3. Two skeptics per distinct finding, each asked to refute it; keep what neither refutes.",
             "4. Fix each kept finding with a test that fails before the fix, or contest it with evidence in the PR.",
             f"5. `brain review stamp {p.head} --findings N --fixed M --contested K --note review.md`.", "",
             f"## Lenses ({len(p.lenses)})", ""]
    lines += [f"- **{name}**: {asks[name]}" for name in p.lenses if name in asks]
    if p.standards:   # wi-brain-standards-registry-consumers: brain standards lenses
        lines += [f"- **standards**: does the change keep each of the project's review-lens standards "
                  f"({len(p.standards)}, brain standards lenses)?"] + [f"  - {s}" for s in p.standards]
    lines += ["", f"## Files ({len(p.files)})", ""] + [f"- `{f}`" for f in p.files]
    if p.scout_rc is not None:
        lines += ["", f"## Scout: exit {p.scout_rc} (`scout.txt`)"]
    lines += [f"- {n}" for n in p.notes]
    return "\n".join(lines) + "\n"


def prep(repo: Path, target: str = "", out: Path | None = None, scout: bool = True,
         standards: list[str] | None = None) -> Packet:
    """Write the packet of ``target`` into ``out`` (default: <BRAIN_HOME>/reviews/<head>); ``standards``, the
    project's review-lens rows (brain.standards.lenses), make the standards lens."""
    base, head = resolve(repo, target)
    files = [f for f in _git(repo, "diff", "--name-only", f"{base}..{head}").splitlines() if f]
    folder = out or folder_for(head)
    if (folder / "files").is_dir():   # a packet prepared again: no file left from a diff it no longer holds
        shutil.rmtree(folder / "files")
    (folder / "files").mkdir(parents=True, exist_ok=True)
    (folder / "diff.patch").write_text(_git(repo, "diff", f"{base}..{head}"), encoding="utf-8", newline="\n")
    p = Packet(base, head, files, lenses_for(files), str(folder), standards=list(standards or []))
    if p.standards:
        p.lenses.append("standards")
    for f in files:
        r = subprocess.run(["git", "show", f"{head}:{f}"], cwd=repo, capture_output=True)
        if r.returncode:   # deleted at the head
            continue
        if len(r.stdout) > MAX_FILE or b"\0" in r.stdout[:8000]:
            p.notes.append(f"`{f}`: not copied (binary or over {MAX_FILE} bytes)")
            continue
        dest = folder / "files" / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.stdout)
    if scout:
        p.scout_rc, text = _scout(repo, base, head)
        (folder / "scout.txt").write_text(text + "\n", encoding="utf-8", newline="\n")
    (folder / "packet.json").write_text(json.dumps(asdict(p), indent=2), encoding="utf-8", newline="\n")
    (folder / "README.md").write_text(_readme(p), encoding="utf-8", newline="\n")
    return p


def stamp_file(head: str) -> Path:
    return paths.brain_home() / FOLDER / "stamps" / f"{head}.json"


def stamp(head: str, findings: int, fixed: int, contested: int = 0, note: str = "", repo: Path | None = None,
          **where: str) -> Path:
    """Record that the review of ``head`` ran, with its counts; a full sha only (a short one could name two).
    ``where`` (pr, item, stream, wave, repo_slug) places it for the error score; the note's finding lines
    (:func:`parse_note`) are kept as its rows."""
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        if repo is None:
            raise ReviewError(f"{head}: a stamp is keyed by a full commit sha")
        head = _git(repo, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    if min(findings, fixed, contested) < 0 or fixed + contested > findings:
        raise ReviewError(f"findings {findings}, fixed {fixed}, contested {contested}: fixed and contested are among "
                          "the findings")
    f = stamp_file(head)
    f.parent.mkdir(parents=True, exist_ok=True)
    rec = {"v": 1, "head": head, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "findings": findings, "fixed": fixed, "contested": contested, "open": findings - fixed - contested,
           "note": note, **{k: str(v) for k, v in where.items() if k in PLACES and v}, "rows": parse_note(note)}
    f.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8", newline="\n")
    return f


def _lens_words() -> dict[str, str]:
    """A lens by its first word (``install`` for « install and upgrade »), the standards and scope lenses too."""
    words = {name.split()[0]: name for name, _, _ in LENSES}
    return {**words, "scope": words.get("scope", "scope"), "standards": "standards"}


def _token(tok: str, lenses: dict[str, str]) -> tuple[str, str] | None:
    """(field, value) of one token of a finding line, None when it is no known token."""
    if "=" in tok:
        k, _, v = tok.partition("=")
        return (k, v) if k in FIELDS and v else None
    low = tok.lower()
    for name, words in VOCABULARY.items():
        if low in words:
            return name, low
    if CAUSE.fullmatch(tok):
        return "cause", tok
    return ("lens", lenses[low]) if low in lenses else None


def parse_note(note: str) -> list[dict]:
    """The note's finding lines: ``- <severity> [lens] [cause] [outcome] [before|after] [covered|uncovered]: text``,
    the tokens in any order (``key=value`` too), the severity required; a line with a word that is no token is prose,
    not a finding. Each row: severity, lens, cause, outcome, when (default before), covered, text."""
    lenses, rows = _lens_words(), []
    for line in (note or "").splitlines():
        m = FINDING.match(line)
        got = [_token(t, lenses) for t in m.group(1).split()] if m else [None]
        row = dict(x for x in got if x)
        if None in got or row.get("severity") not in SEVERITIES:
            continue
        rows.append({"severity": row["severity"], "lens": row.get("lens", ""), "cause": row.get("cause", ""),
                     "outcome": row.get("outcome", ""), "when": row.get("when", "before"),
                     "covered": row.get("covered", ""), "text": m.group(2).strip()})
    return rows


def confirmed(rows: list[dict]) -> list[dict]:
    """The rows a skeptic did not refute: the confirmed findings, the error score's unit."""
    return [r for r in rows if r.get("outcome") != "refuted"]


def stamps() -> list[dict]:
    """Every stamp recorded, oldest first."""
    folder = paths.brain_home() / FOLDER / "stamps"
    out = []
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and isinstance(rec.get("findings"), int) and rec.get("head"):
            out.append(rec)
    return sorted(out, key=lambda r: str(r.get("at") or ""))


def _pr_key(rec: dict) -> str:
    """A PR's key: its repo and number, else its item, else its head (one review per head, a push reviewed again)."""
    if rec.get("pr"):
        return f"{rec.get('repo_slug') or ''}#{rec['pr']}"
    return rec.get("item") or rec["head"]


def per_pr(recs: list[dict]) -> list[dict]:
    """The latest stamp of each PR: a head stamped again after a fix carries the PR's whole review."""
    latest: dict[str, dict] = {}
    for r in recs:
        latest[_pr_key(r)] = r
    return list(latest.values())


def _tally(recs: list[dict]) -> dict:
    rows = [x for r in recs for x in confirmed(r.get("rows") or [])]
    n, found = len(recs), sum(r["findings"] for r in recs)
    return {"prs": n, "findings": found, "per_pr": round(found / n, 2) if n else None,
            "open": sum(r.get("open", 0) for r in recs), "rows": len(rows),
            **{k: dict(Counter(x[k] or "-" for x in rows).most_common()) for k in ("severity", "lens", "cause")},
            "after": sum(1 for x in rows if x["when"] == "after"),
            "covered": sum(1 for x in rows if x["covered"] == "covered")}


def _wave_order(wave: str) -> tuple:
    nums = re.findall(r"\d+", wave)
    return (0, tuple(int(x) for x in nums), wave) if nums else (1, (), wave)


def score(recs: list[dict] | None = None) -> dict:
    """The error score (wi-brain-review-error-score): each PR's latest stamp, the totals and, per wave in order, the
    PRs, confirmed findings, findings per PR and the rows' severity, lens, root-cause family, found after the merge
    and covered by a script; then the owner's rule: the reviews lighten only once the findings per PR fall over two
    waves in a row."""
    prs = per_pr(stamps() if recs is None else recs)
    waves: dict[str, list[dict]] = {}
    for r in prs:
        waves.setdefault(r.get("wave") or "", []).append(r)
    trend = [{"wave": w, **_tally(waves[w])} for w in sorted((w for w in waves if w), key=_wave_order)]
    return {"total": _tally(prs), "waves": trend, "unplaced": len(waves.get("", [])), "lighten": lighten(trend)}


def lighten(trend: list[dict]) -> dict:
    """The owner's rule of 2026-11-03: the reviews stay complete until the findings per PR fall over two waves in a
    row (the last three scored waves, each lower than the one before)."""
    last = [t for t in trend if t["per_pr"] is not None][-(FALLS + 1):]
    if len(last) <= FALLS:
        return {"ok": False, "why": f"{len(last)} wave(s) scored, {FALLS + 1} needed"}
    ok = all(b["per_pr"] < a["per_pr"] for a, b in zip(last, last[1:]))
    seq = " -> ".join(f"{t['wave']} {t['per_pr']}" for t in last)
    return {"ok": ok, "why": f"findings per PR {seq}: {'fell' if ok else 'did not fall'} over two waves"}


def _tally_lines(t: dict) -> list[str]:
    lines = [f"{t['prs']} PR(s) reviewed, {t['findings']} confirmed finding(s), {t['per_pr']} per PR, {t['open']} open"
             + (f"; {t['rows']} described: " + ", ".join(f"{k} {v}" for k, v in t["severity"].items())
                if t["rows"] else "")]
    if t["rows"]:
        lines += ["  by lens: " + ", ".join(f"{k} {v}" for k, v in t["lens"].items()),
                  "  by root cause: " + ", ".join(f"{k} {v}" for k, v in t["cause"].items())
                  + f"; {t['after']} found after the merge, {t['covered']} a script now covers"]
    return lines


def score_lines(sc: dict, wave: str = "") -> list[str]:
    """The error score as text: the totals (or one wave's), the trend per wave, the rule's verdict."""
    t = next((w for w in sc["waves"] if w["wave"] == wave), None) if wave else sc["total"]
    head = f"review error score{f', wave {wave}' if wave else ''}: "
    if t and t["prs"]:
        body = _tally_lines(t)
        lines = [head + body[0], *body[1:]]
    else:
        lines = [head + "no reviewed PR recorded" + (" for it (brain review stamp --item or --wave)" if wave else "")]
    if sc["waves"]:
        lines.append("  per wave: " + ", ".join(f"{w['wave']} {w['per_pr']} ({w['prs']} PR)" for w in sc["waves"]))
    if sc["unplaced"]:
        lines.append(f"  {sc['unplaced']} stamp(s) placed in no wave (stamped without --item or --wave; one without "
                     "--pr counts once per head)")
    verdict = "the reviews may lighten" if sc["lighten"]["ok"] else "the reviews stay complete"
    return lines + [f"  {verdict}: {sc['lighten']['why']}"]


def check(head: str, repo: Path | None = None) -> dict | None:
    """The stamp of ``head`` (a sha or a ref when ``repo`` is given), None when it was not reviewed."""
    if repo is not None and not re.fullmatch(r"[0-9a-f]{40}", head):
        head = _git(repo, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    f = stamp_file(head)
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
