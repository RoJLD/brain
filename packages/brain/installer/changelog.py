"""The engine's changelog fragments (wi-brain-changelog-unreleased-collisions; the owner's choice of 2026-11-10).

Every engine PR used to add its bullet at the same place, the CHANGELOG's ``## Unreleased``: once one merged, every
other open PR was CONFLICTING on GitHub, where no merge driver runs. A PR now writes its entry in a file of its own,
and the version PR compiles them into the dated section:

- ``packages/brain/changes/<name>.md`` for the ``brain`` command, ``changes/<name>.md`` for ``research-graph``;
  ``<name>`` is the item's id or a short slug, so two PRs never write one file;
- its first line names the section it goes to, ``section: Upgrade``, ``Added``, ``Fixes`` or ``Changes``, then a blank
  line, then the entry as it will read (bullets; for Upgrade, the step's text, which the version PR numbers);
- a ``README.md`` in the folder says this and is not a fragment.

``python changelog.py check`` (run by release_check.py on every PR) refuses a malformed fragment and a CHANGELOG that
holds a ``## Unreleased`` section again. ``python changelog.py compile X.Y.Z --theme T [--date D] [--write]`` writes
``## X.Y.Z — D — T`` in the brain's CHANGELOG and ``## X.Y.Z — D`` in research-graph's (« No change » when it has no
fragment), its sections in the order Upgrade, Added, Fixes, Changes, then deletes the fragments it compiled. The
CHANGELOGs keep ``merge=brain`` in ``.gitattributes`` as a net for a merge back from ``release/X.Y``.

Standard library only: CI runs it before anything is installed.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

BRAIN = "packages/brain"
DISTRIBUTIONS = {"brain": (f"{BRAIN}/changes", f"{BRAIN}/CHANGELOG.md"), "research-graph": ("changes", "CHANGELOG.md")}
SECTIONS = ("Upgrade", "Added", "Fixes", "Changes")
HEAD = re.compile(r"^section:\s*(\S+)\s*$")
UNRELEASED = re.compile(r"^## Unreleased\s*$", re.M)
NO_CHANGE = "- No change in `research-graph`: the version moves with the shared tag."


@dataclass(frozen=True)
class Fragment:
    path: Path
    section: str
    body: str


def fragment_files(repo: Path, dist: str) -> list[Path]:
    folder = repo / DISTRIBUTIONS[dist][0]
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.md") if p.name.lower() != "readme.md")


def parse(path: Path) -> tuple[Fragment | None, str]:
    """(the fragment, '') or (None, what is wrong with it)."""
    return parse_text(path, path.read_text(encoding="utf-8"))


def parse_text(path: Path, text: str) -> tuple[Fragment | None, str]:
    """:func:`parse` of a fragment's text read elsewhere (a commit's, by release_check.py --preview --ref)."""
    lines = text.replace("\r\n", "\n").split("\n")
    m = HEAD.match(lines[0]) if lines else None
    if not m:
        return None, f"{path.as_posix()}: its first line is 'section: {' | '.join(SECTIONS)}'"
    if m.group(1) not in SECTIONS:
        return None, f"{path.as_posix()}: section {m.group(1)!r} is one of {', '.join(SECTIONS)}"
    body = "\n".join(lines[1:]).strip("\n")
    if not body.strip():
        return None, f"{path.as_posix()}: no entry after its section line"
    return Fragment(path, m.group(1), body), ""


def load(repo: Path, dist: str) -> tuple[list[Fragment], list[str]]:
    frags, problems = [], []
    for p in fragment_files(repo, dist):
        f, why = parse(p)
        if f:
            frags.append(f)
        else:
            problems.append(why)
    return frags, problems


def check(repo: Path) -> list[str]:
    """What is wrong on any PR: a malformed fragment, or a CHANGELOG that holds ``## Unreleased`` again."""
    problems = []
    for dist, (folder, log) in DISTRIBUTIONS.items():
        problems += load(repo, dist)[1]
        f = repo / log
        if f.is_file() and UNRELEASED.search(f.read_text(encoding="utf-8")):
            problems.append(f"{log}: a '## Unreleased' section: write the entry as a fragment, {folder}/<item>.md "
                            f"(installer/changelog.py), so that parallel PRs never collide in the CHANGELOG")
    return problems


def pending(repo: Path) -> list[str]:
    """The fragments a version PR has not compiled yet."""
    return [p.as_posix() for dist in DISTRIBUTIONS for p in fragment_files(repo, dist)]


def section_text(frags: list[Fragment], version: str, day: str, theme: str, dist: str) -> str:
    title = f"## {version} — {day}" + (f" — {theme}" if dist == "brain" and theme else "")
    out = [title, ""]
    if not frags:
        return "\n".join(out + ([NO_CHANGE] if dist == "research-graph" else ["- No change."]) + [""])
    for sec in SECTIONS:
        bodies = [f.body for f in frags if f.section == sec]
        if bodies:
            out += [f"### {sec}", ""] + [join_bodies(bodies), ""]
    return "\n".join(out)


# A list item opening a line: a bullet or a numbered step (release_check.py's STEP_RE numbers the latter).
LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s")


def join_bodies(bodies: list[str]) -> str:
    """A section's fragment bodies in order: a list after a list continues it (one newline, so the bullets or the
    numbered steps stay one list); anything else gets a blank line before it, so a closing paragraph after the
    Upgrade steps is a paragraph of its own, not the last step's continuation (wi-brain-changelog-prose-fragment)."""
    text = bodies[0] if bodies else ""
    for before, body in zip(bodies, bodies[1:]):
        text += ("\n" if _ends_in_list(before) and LIST_ITEM.match(body) else "\n\n") + body
    return text


def _ends_in_list(body: str) -> bool:
    """Whether the body ends in a list: its last line that is not indented (a list item's continuation is) opens a
    list item."""
    for line in reversed(body.split("\n")):
        if line.strip() and not line[:1].isspace():
            return bool(LIST_ITEM.match(line))
    return False


def insert(changelog: str, section: str) -> str:
    """The changelog with ``section`` before its first ``## `` heading (after its title and intro)."""
    m = re.search(r"^## ", changelog, re.M)
    at = m.start() if m else len(changelog)
    return changelog[:at] + section + "\n" + changelog[at:]


def compile_release(repo: Path, version: str, theme: str, day: str = "", write: bool = False) -> dict[str, str]:
    """{the CHANGELOG path: the section it gains}; with ``write``, written and the fragments deleted."""
    day = day or date.today().isoformat()
    out = {}
    for dist, (folder, log) in DISTRIBUTIONS.items():
        frags, problems = load(repo, dist)
        if problems:
            raise ValueError("; ".join(problems))
        text = section_text(frags, version, day, theme, dist)
        out[log] = text
        if write:
            f = repo / log
            f.write_text(insert(f.read_text(encoding="utf-8"), text), encoding="utf-8", newline="\n")
            for frag in frags:
                frag.path.unlink()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The engine's changelog fragments (packages/brain/changes, changes).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="a malformed fragment, or a CHANGELOG with a '## Unreleased' section")
    c = sub.add_parser("compile", help="the version PR: fragments into the dated sections, then deleted")
    c.add_argument("version")
    c.add_argument("--theme", required=True, help="the release's theme (the brain's heading)")
    c.add_argument("--date", default="", help="YYYY-MM-DD (default: today)")
    c.add_argument("--write", action="store_true")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    repo = Path(args.repo)
    if args.cmd == "check":
        problems = check(repo)
        for p in problems:
            print(f"changelog: FAILED: {p}", file=sys.stderr)
        return 1 if problems else 0
    try:
        sections = compile_release(repo, args.version, args.theme, args.date, args.write)
    except ValueError as exc:
        print(f"changelog: {exc}", file=sys.stderr)
        return 1
    for log, text in sections.items():
        print(f"== {log}\n{text}")
    print("written; the fragments deleted" if args.write else "not written: --write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
