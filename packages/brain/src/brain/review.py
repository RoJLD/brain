"""The review before the report (wi-brain-review-step; the owner's RETRO-1, RETRO-2 and RETRO-9 of 2026-11-03).

A session that opens a PR carrying code, a procedure, a hook, the installer, a schema or the engine's docs reviews it
before it reports, with three or four lens agents and two skeptics per distinct finding (docs/review.md). What can be
gathered without a model is gathered here, at zero token:

- ``brain review prep [PR | BASE..HEAD]`` writes the packet: the diff, the touched files at the head, the scout's
  output (``brain audit --diff``), the lenses chosen from the touched surfaces, and a README that says how to run them;
- ``brain review stamp HEAD --findings N --fixed M [--contested K] [--note FILE]`` records that the review ran on that
  head, with its counts (the error score's record, wi-brain-review-error-score);
- ``brain review check HEAD`` says whether that head was reviewed: the merge gate's question (wi-brain-merge-gate);
  with ``--pr N`` (or ``--body FILE``), it also refuses while a pinned decision the change touches is neither kept
  nor overridden in the PR body (``pins_gate``, brain.pins, wi-brain-decision-pins).

A stamp is keyed by the head's full sha: a push after the review is a new head, reviewed again.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import paths

FOLDER = "reviews"
MAX_FILE = 400_000   # a touched file larger than this is listed, not copied

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


def stamp(head: str, findings: int, fixed: int, contested: int = 0, note: str = "", repo: Path | None = None) -> Path:
    """Record that the review of ``head`` ran, with its counts; a full sha only (a short one could name two)."""
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
           "note": note}
    f.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8", newline="\n")
    return f


def pins_gate(repo: Path, base: str, head: str, body: str | None) -> tuple[list[dict], list[str]]:
    """(the pinned decisions the change base..head touches, what blocks it: brain.pins.verdict on the PR body), at the
    file level; ([], []) for a repo in no registered project or without pins."""
    from types import SimpleNamespace

    from . import pins, scout
    from .inventory import AuditError
    try:
        p, _, c, top, registered = scout.resolve(SimpleNamespace(repo_dir=str(repo), project=None), None)
    except (AuditError, OSError, ValueError):
        return [], []
    if not registered:
        return [], []
    mb = _git(repo, "merge-base", base, head).strip()
    files = set()
    for line in _git(repo, "diff", "--name-status", "-M", mb, head).splitlines():
        files.update(x for x in line.split("\t")[1:] if x)
    touched = pins.touched(p, files, {c.name, top.name, (paths.main_checkout(top) or top).name})
    return touched, pins.verdict(p, touched, body)


def check(head: str, repo: Path | None = None) -> dict | None:
    """The stamp of ``head`` (a sha or a ref when ``repo`` is given), None when it was not reviewed."""
    if repo is not None and not re.fullmatch(r"[0-9a-f]{40}", head):
        head = _git(repo, "rev-parse", "--verify", f"{head}^{{commit}}").strip()
    f = stamp_file(head)
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
