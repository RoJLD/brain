#!/usr/bin/env python3
"""The version PR's check (docs/release.md): CI's ``release-check`` job, or by hand from a checkout.

A pull request is a version PR when either distribution's ``__version__`` is not the last tag's. On any other, nothing
is checked. On a version PR, it fails when:

- a registered schema (:data:`SCHEMAS`) changed since the last tag and this version's section of
  ``packages/brain/CHANGELOG.md`` has no ``### Upgrade`` with something in it: an upgrade that needs a step and does
  not say so is how a brain breaks on its owner's machine (``brain update`` prints that section);
- the version is not coherent: both ``__version__``, the research-graph pin, the hooks' ``brain_version``, a dated
  section in both CHANGELOGs. CI's ``release-tag`` job checks part of this too, but only once the tag exists.

Standard library only, and the working tree is what is read: the job runs before any install, and it can be run before
committing. Exit 0 when it passes or there is nothing to check, 1 when it fails, 2 when it cannot tell (no tag, no git).

    python packages/brain/installer/release_check.py [--repo DIR] [--against vX.Y.Z]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

BRAIN = "packages/brain"
SRC = f"{BRAIN}/src/brain"
FIXTURES = f"{BRAIN}/tests/fixtures/formats"

# What a format's shape is written in, per format; a folder of FIXTURES must be a key here (tests/test_release_check.py),
# so a format registered there is checked here. permissions.yaml has no file of its own: its keys are constants of
# brain.permissions, and a file's diff cannot tell them from the rest of the module (wi-brain-schema-diff compares keys).
# "store" is not a format with a fixture yet: what `brain init` wrote once and keeps afterwards, so that a brain never
# gets a change of these files by itself (0.2.5's Lesson type and merge=brain line).
SCHEMAS = {
    "ar": (f"{SRC}/schemas/ar.schema.json",),
    "config": (f"{SRC}/schemas/config.schema.json",),
    "ddr": (f"{SRC}/schemas/ddr.schema.json",),
    "event": (f"{SRC}/schemas/event.schema.json",),
    "sr": (f"{SRC}/schemas/sr.schema.json",),
    "packs": (f"{SRC}/templates/generic/packs.yaml",),
    "projects": (f"{SRC}/templates/generic/projects.yaml",),
    "template": (f"{SRC}/templates/generic/template.yaml",),
    "permissions": (),
    "store": ("src/research_graph/templates/schema.yaml", f"{SRC}/templates/schemas/default.yaml",
              f"{SRC}/templates/generic/boundary.yaml", f"{SRC}/templates/generic/gitattributes"),
}

VERSIONS = {"research-graph": "src/research_graph/__init__.py", "brain": f"{SRC}/__init__.py"}
VERSION_RE = re.compile(r'__version__ = "([^"]+)"')
TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
HEADING_RE = re.compile(r"^## (\d+\.\d+\.\d+)\b(.*)$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
UPGRADE_RE = re.compile(r"^### Upgrade\b")


class CannotTell(Exception):
    """git could not answer: the check neither passes nor fails on a guess."""


def git(repo: Path, *args: str) -> str:
    """git's stdout, stripped; :class:`CannotTell` on a failure."""
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", check=False)
    except OSError as exc:
        raise CannotTell(f"git cannot run: {exc}") from exc
    if done.returncode:
        raise CannotTell(f"git {' '.join(args)}: {done.stderr.strip() or f'exit {done.returncode}'}")
    return done.stdout.strip()


def last_tag(repo: Path) -> str:
    """The last tag before HEAD, as CI's compat-prev job finds it."""
    return git(repo, "describe", "--tags", "--abbrev=0", "--match", "v*", "HEAD")


def changed_schemas(repo: Path, tag: str) -> list[str]:
    """The registered schema files that differ between ``tag`` and the working tree, removed or renamed ones included."""
    paths = sorted({path for group in SCHEMAS.values() for path in group})
    return [line for line in git(repo, "diff", "--name-only", tag, "--", *paths).splitlines() if line]


def read(repo: Path, path: str) -> str:
    """A file of the checkout; empty when it cannot be read, which the checks that need it report as what is missing."""
    try:
        return (repo / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def version_in(repo: Path, path: str) -> str:
    """The ``__version__`` of that file, or ''."""
    match = VERSION_RE.search(read(repo, path))
    return match.group(1) if match else ""


def heading(changelog: str, version: str) -> str | None:
    """The rest of the line of ``version``'s section heading, or None without one."""
    for line in changelog.splitlines():
        match = HEADING_RE.match(line)
        if match and match.group(1) == version:
            return match.group(2)
    return None


def upgrade_section(changelog: str, version: str) -> str | None:
    """What ``version``'s ``### Upgrade`` says, up to the next heading of that level or above; None without one."""
    lines: list[str] = []
    in_version = in_upgrade = found = False
    for line in changelog.splitlines():
        if line.startswith("## "):
            match = HEADING_RE.match(line)
            in_version = bool(match and match.group(1) == version)
            in_upgrade = False
        elif line.startswith("### "):
            in_upgrade = in_version and bool(UPGRADE_RE.match(line))
            found = found or in_upgrade
        elif in_upgrade:
            lines.append(line)
    return "\n".join(lines).strip() if found else None


def coherence(repo: Path, tag: str, version: str) -> list[str]:
    """What the version PR left behind: every place that says the version, and that it moves forward."""
    problems = []
    now, before = TAG_RE.match(version), TAG_RE.match(tag)
    if not now:
        problems.append(f"the version {version!r} is not X.Y.Z")
    elif not before:
        problems.append(f"the last tag {tag!r} is not vX.Y.Z")
    elif tuple(map(int, now.groups())) <= tuple(map(int, before.groups())):
        problems.append(f"the version {version} is not after the last tag {tag}")
    pyproject = f"{BRAIN}/pyproject.toml"
    if f"research-graph @ git+https://github.com/RoJLD/brain.git@v{version}\"" not in read(repo, pyproject):
        problems.append(f"{pyproject} does not pin research-graph at v{version}")
    common = f"{SRC}/adapters/claude/hooks/common.sh"
    if not re.search(rf"^brain_version={re.escape(version)}\s*$", read(repo, common), re.M):
        problems.append(f"{common} does not say brain_version={version}")
    for path in ("CHANGELOG.md", f"{BRAIN}/CHANGELOG.md"):
        rest = heading(read(repo, path), version)
        if rest is None:
            problems.append(f"{path} has no section ## {version}")
        elif not DATE_RE.search(rest):
            problems.append(f"{path}: the section ## {version} has no date")
    return problems


def check(repo: Path, tag: str) -> tuple[list[str], list[str]]:
    """(what it says, what fails) for the checkout ``repo`` against the tag ``tag``."""
    versions = {name: version_in(repo, path) for name, path in VERSIONS.items()}
    for name, version in versions.items():
        if not version:
            return [], [f"{VERSIONS[name]}: no __version__ ({name})"]
    if all(version == tag.removeprefix("v") for version in versions.values()):
        return [f"not a version PR: both distributions are at {tag}; nothing to check"], []
    if len(set(versions.values())) > 1:
        return [], [f"the versions differ: {versions}; a tag is both distributions at one version"]
    version = versions["brain"]
    said = [f"version PR: {tag} -> {version}"]
    problems = coherence(repo, tag, version)
    changed = changed_schemas(repo, tag)
    changelog = f"{BRAIN}/CHANGELOG.md"
    if not changed:
        said.append(f"no registered schema changed since {tag}")
    else:
        said.append(f"registered schemas changed since {tag}: {', '.join(changed)}")
        if not upgrade_section(read(repo, changelog), version):
            problems.append(f"{changelog}: registered schemas changed since {tag} ({', '.join(changed)}) and the "
                            f"section ## {version} has no ### Upgrade with something in it: say what an owner does, "
                            f"or that there is nothing to run")
    return said, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The version PR's check (docs/release.md).")
    ap.add_argument("--repo", default=".", help="the checkout (default: here)")
    ap.add_argument("--against", default="", help="the tag to compare with (default: the last tag before HEAD)")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    try:
        said, problems = check(repo, args.against or last_tag(repo))
    except CannotTell as exc:
        print(f"release-check: cannot tell: {exc}", file=sys.stderr)
        return 2
    for line in said:
        print(f"release-check: {line}")
    for line in problems:
        print(f"release-check: FAILED: {line}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
