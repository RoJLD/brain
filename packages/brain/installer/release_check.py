#!/usr/bin/env python3
"""The version PR's check (docs/release.md): CI's ``release-check`` job, or by hand from a checkout.

A pull request is a version PR when either distribution's ``__version__`` is not the last tag's. On any other, nothing
is checked. On a version PR, it fails when:

- a registered schema (:data:`SCHEMAS`) moved since the last tag (changed, except an additive change of a JSON schema
  of :data:`ADDITIVE`: :func:`additive`) and this version's section of
  ``packages/brain/CHANGELOG.md`` has no ``### Upgrade`` with something in it: an upgrade that needs a step and does
  not say so is how a brain breaks on its owner's machine (``brain update`` prints that section);
- the version is not coherent: both ``__version__``, the research-graph pin, the hooks' ``brain_version``, a dated
  section in both CHANGELOGs. CI's ``release-tag`` job checks part of this too, but only once the tag exists;
- the brain's section heading names no theme after its date (``## X.Y.Z — YYYY-MM-DD — theme``);
- its ``### Upgrade`` does not number each of the standard steps (:data:`STANDARD_STEPS`), which every release asks
  of an owner and ``brain update`` prints;
- the version policy (docs/release.md, « The version policy ») is broken by a patch, a version whose X.Y is the last
  tag's: a registered schema moved since that tag, or its ``### Upgrade`` numbers a step that is not one of the
  standard steps (:data:`STANDARD_STEPS`, by the bold title that opens the step). Such a release is a minor one;
- either CHANGELOG's section repeats an entry an earlier section of it released: a fix that cannot wait, released from
  ``release/X.Y``, and left in main's ``## Unreleased`` when that branch merged back (by its text; a « No change »
  line and the ``### Upgrade`` steps repeat by design and are not compared);
- with ``--store DIR`` (the graph store that plans the releases, a brain's ``notes/graph``): the closure rule, the
  wave this version names (a milestone of kind wave, ``props.release``) still holds an open item that is neither
  carried to a later wave (``props.carried_to``) nor dropped, or is not reached yet (``brain wave close``,
  brain.waves). That one check imports brain and research_graph from this checkout (``packages/brain/src``, ``src``)
  and needs PyYAML; a store with no wave of this version passes it.

Standard library only (``--store``'s check aside), and the working tree is what is read: the job runs before any
install, and it can be run before committing. Exit 0 when it passes or there is nothing to check, 1 when it fails, 2
when it cannot tell (no tag, no git, a --store that cannot be read: no ``nodes/``, YAML that does not parse, no
PyYAML; on any PR, a version PR or not).

    python packages/brain/installer/release_check.py [--repo DIR] [--against vX.Y.Z] [--store DIR]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # changelog.py beside it, whoever loads this file

BRAIN = "packages/brain"
SRC = f"{BRAIN}/src/brain"
FIXTURES = f"{BRAIN}/tests/fixtures/formats"

# What a format's shape is written in, per format; a folder of FIXTURES must be a key here
# (tests/test_release_check.py), so a format registered there is checked here. permissions.yaml has no file of its own:
# its keys are constants of brain.permissions, and a file's diff cannot tell them from the rest of the module
# (wi-brain-schema-diff compares keys).
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
# A numbered step of ### Upgrade: at the start of a line, not indented (a sub-step or a continuation line is part of
# the step above it); its title is the bold text that opens it.
STEP_RE = re.compile(r"^\d+[.)]\s+(.*)$")
TITLE_RE = re.compile(r"^\*\*(.+?)\*\*")
# The steps every release asks of an owner, whatever it changed (docs/release.md, « The standard steps »): the only ones
# a patch's ### Upgrade may number. Compared by title, case and a closing ``.`` or ``:`` aside.
STANDARD_STEPS = ("Install the engine", "Restart the Claude Code sessions", "Refresh the public stamp")


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
    """The registered schema files that differ between ``tag`` and the working tree, removed or renamed ones
    included."""
    paths = sorted({path for group in SCHEMAS.values() for path in group})
    return [line for line in git(repo, "diff", "--name-only", tag, "--", *paths).splitlines() if line]


# The formats whose JSON schema may grow by an optional key in a patch (the owner, 2026-11-10,
# wi-brain-release-schema-additive): every file an older engine wrote stays valid under the new schema, so an owner
# has nothing to do. Only config.json's: a record schema (ar, ddr, sr, event) is read by the engines of other machines,
# which would refuse the new key in a record this one writes.
ADDITIVE = ("config",)
# The keys of a JSON schema that only describe it: a change of them moves no format.
PROSE = ("description", "title", "$comment", "examples")


def additive(old, new) -> bool:
    """True when the JSON schema ``new`` only adds to ``old`` optional properties (in an object's ``properties``, none
    of them ``required``) or changes its prose (:data:`PROSE`): every document ``old`` accepts, ``new`` accepts.
    Any other change (a property removed, a keyword added, removed or changed: a type, an enum, a bound, a pattern,
    ``additionalProperties``, ``required``, a list reordered) is not additive: the comparison errs towards a minor
    version. A scalar keeps its type too (``false`` is not ``0``)."""
    if isinstance(old, dict) and isinstance(new, dict):
        keys = (set(old) | set(new)) - set(PROSE)
        return all(key in old and key in new and _key_additive(key, old[key], new[key], new) for key in keys)
    if isinstance(old, list) and isinstance(new, list):
        return len(old) == len(new) and all(additive(a, b) for a, b in zip(old, new))
    return type(old) is type(new) and old == new


def _key_additive(key: str, old, new, schema: dict) -> bool:
    """One key of a schema object, kept by both sides: ``properties`` may gain optional ones (none in ``schema``'s
    ``required``), every other key compares whole."""
    if key != "properties" or not (isinstance(old, dict) and isinstance(new, dict)):
        return additive(old, new)
    added = set(new) - set(old)
    return (set(old) <= set(new) and not added & set(schema.get("required") or [])
            and all(additive(old[k], new[k]) for k in old))


def _at_tag(repo: Path, tag: str, path: str) -> bool:
    """Whether ``path`` exists in ``tag``'s tree."""
    try:
        git(repo, "cat-file", "-e", f"{tag}:{path}")
        return True
    except CannotTell:
        return False


REGISTRY = f"{BRAIN}/installer/release_check.py"


def formats_at(repo: Path, tag: str) -> set[str] | None:
    """The format names ``tag`` registered: the keys of :data:`SCHEMAS` in that tag's own copy of this file; None
    when it cannot tell (no such file, or no literal SCHEMAS in it)."""
    try:
        tree = ast.parse(git(repo, "show", f"{tag}:{REGISTRY}"))
    except (CannotTell, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id == "SCHEMAS" for t in node.targets)):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return None


def new_formats(repo: Path, tag: str) -> set[str]:
    """The formats this version adds: a name ``tag`` did not register (:func:`formats_at`) none of whose files exists
    at ``tag``. No brain holds a file of one yet and an older engine never reads it, so adding one asks nothing of an
    owner (the owner's decision of 2026-11-10, wi-brain-release-schema-additive). A format the tag registered whose
    files are renamed is not new: it moves. When the tag's registry cannot be read, no format is new."""
    known = formats_at(repo, tag)
    if known is None:
        return set()
    return {name for name, group in SCHEMAS.items() if group and name not in known
            and all((repo / p).exists() and not _at_tag(repo, tag, p) for p in group)}


def moved_schemas(repo: Path, tag: str, changed: list[str]) -> tuple[list[str], list[str]]:
    """(moved, additive): the changed schema files split into those whose format moves and those that only grew:
    by optional keys (:data:`ADDITIVE`, :func:`additive`), or as a whole new format (:func:`new_formats`). Any other
    file new or gone since ``tag``, or unreadable as JSON, moves."""
    grows = {path for name in ADDITIVE for path in SCHEMAS[name] if path.endswith(".json")}
    added = {path for name in new_formats(repo, tag) for path in SCHEMAS[name]}
    moved, grown = [], []
    for path in changed:
        if path in added:
            grown.append(path)
            continue
        if path in grows:
            try:
                if additive(json.loads(git(repo, "show", f"{tag}:{path}")), json.loads(read(repo, path))):
                    grown.append(path)
                    continue
            except (CannotTell, ValueError):
                pass
        moved.append(path)
    return moved, grown


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


def entries(changelog: str) -> dict[str, list[str]]:
    """The bullets of each version's section, by version: a bullet is a line opening with ``- `` and its indented
    continuation lines, its whitespace collapsed. ``## Unreleased`` is not a version and is left out, and so is each
    ``### Upgrade``, which numbers the standard steps every time."""
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    bullet: list[str] | None = None
    in_upgrade = False
    for line in changelog.splitlines():
        if line.startswith("## "):
            match = HEADING_RE.match(line)
            current = found.setdefault(match.group(1), []) if match else None
            bullet, in_upgrade = None, False
        elif line.startswith("### "):
            bullet, in_upgrade = None, bool(UPGRADE_RE.match(line))
        elif current is not None and not in_upgrade and line.startswith("- "):
            bullet = [line[2:]]
            current.append("")
        elif bullet is not None and line[:1] in (" ", "\t") and line.strip():
            bullet.append(line)
        else:
            bullet = None
        if bullet is not None and current is not None:
            current[-1] = " ".join(" ".join(bullet).split())
    return found


def entries_already_released(changelog: str, version: str) -> list[tuple[str, str]]:
    """(entry, the version that released it) for each bullet of ``version``'s section that an earlier section holds:
    a fix released by a patch from ``release/X.Y`` and left in main's ``## Unreleased`` by the merge back.

    Compared by their text, whitespace aside: an entry reworded on the way is the version PR's author to see. A line
    opening with « No change » is the one-line section of a distribution with nothing new, the same each time, and is
    never a repeat."""
    sections = entries(changelog)
    earlier = {entry: other for other, bullets in sections.items() if other != version for entry in bullets}
    return [(entry, earlier[entry]) for entry in sections.get(version, [])
            if entry in earlier and not entry.casefold().startswith("no change")]


def theme(rest: str) -> str:
    """The theme a section heading names after its date (``## X.Y.Z — YYYY-MM-DD — theme``), or '': what follows the
    date, the punctuation around it left out, and only when it has a letter or a digit (``(2026-11-16)`` names none)."""
    match = DATE_RE.search(rest)
    said = rest[match.end():].strip(" \t—–-:,;.…()[]«»\"'") if match else ""
    return said if re.search(r"\w", said) else ""


def _title(text: str) -> str:
    return text.strip().rstrip(".:").strip().casefold()


def _step_titles(upgrade: str) -> list[str]:
    """The bold titles of an ``### Upgrade``'s numbered steps, compared form; '' for a step without one."""
    titles = []
    for line in upgrade.splitlines():
        step = STEP_RE.match(line)
        if step:
            title = TITLE_RE.match(step.group(1))
            titles.append(_title(title.group(1)) if title else "")
    return titles


def standard_steps_missing(upgrade: str) -> list[str]:
    """The standard steps an ``### Upgrade`` does not number, in their order; [] when it numbers each."""
    found = set(_step_titles(upgrade))
    return [step for step in STANDARD_STEPS if _title(step) not in found]


def steps_beyond_standard(upgrade: str) -> list[str]:
    """The numbered steps of an ``### Upgrade`` that are not standard steps, as their lines; [] when there are none."""
    standard = {_title(step) for step in STANDARD_STEPS}
    beyond = []
    for line in upgrade.splitlines():
        step = STEP_RE.match(line)
        if not step:
            continue
        title = TITLE_RE.match(step.group(1))
        if not title or _title(title.group(1)) not in standard:
            beyond.append(line.strip())
    return beyond


def is_patch(tag: str, version: str) -> bool:
    """Whether ``version`` moves only the last number of ``tag``: X.Y the same, Z after it."""
    now, before = TAG_RE.match(version), TAG_RE.match(tag)
    if not (now and before):
        return False
    (x, y, z), (px, py, pz) = map(int, now.groups()), map(int, before.groups())
    return (x, y) == (px, py) and z > pz


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
        elif path == f"{BRAIN}/CHANGELOG.md" and not theme(rest):
            problems.append(f"{path}: the section ## {version} names no theme: ## {version} — YYYY-MM-DD — what this "
                            f"release is about (docs/release.md, « The version policy »)")
    return problems


def policy(tag: str, version: str, changed: list[str], upgrade: str | None) -> list[str]:
    """What a patch may not hold (docs/release.md, « The version policy »); nothing for any other version."""
    if not is_patch(tag, version):
        return []
    problems = []
    rule = f"{version} is a patch of {tag}"
    if changed:
        problems.append(f"{rule} and registered schemas changed since {tag} ({', '.join(changed)}): a format that "
                        f"moves is a minor version, not a patch")
    beyond = steps_beyond_standard(upgrade or "")
    if beyond:
        problems.append(f"{rule} and its ### Upgrade asks more than the standard steps "
                        f"({', '.join(STANDARD_STEPS)}): {' | '.join(beyond)}; a change an owner must act on is a "
                        f"minor version, not a patch")
    return problems


def sections(repo: Path, version: str, upgrade: str | None) -> list[str]:
    """What ``version``'s CHANGELOG sections miss, whatever the version: a standard step its ``### Upgrade`` does not
    number, an entry either section repeats from an earlier one."""
    changelog = f"{BRAIN}/CHANGELOG.md"
    problems = []
    missing = standard_steps_missing(upgrade or "")
    if missing:
        problems.append(f"{changelog}: the section ## {version} does not number the standard steps "
                        f"{', '.join(f'**{step}**' for step in missing)} in its ### Upgrade: every release asks them "
                        f"of an owner, each opening with its title in bold (docs/release.md, « The standard steps »)")
    for log in ("CHANGELOG.md", changelog):
        for entry, other in entries_already_released(read(repo, log), version):
            problems.append(f"{log}: the section ## {version} repeats an entry that {other} released: "
                            f"{entry[:100]}{'...' if len(entry) > 100 else ''}; take it out of ## Unreleased when "
                            f"release/X.Y merges back into main (docs/release.md, « 3. The tag »)")
    return problems


def wave_closure(repo: Path, store: Path, version: str) -> list[str]:
    """The closure rule (docs/release.md, « 1. Before the version PR »): what the wave named by ``version`` in
    ``store`` still holds open, by brain.waves of this checkout. :class:`CannotTell` when it cannot be read."""
    readable_store(store)
    try:
        import yaml   # before brain.graph, which exits on its own without it
        waves = _waves(repo)
    except ImportError as exc:
        raise CannotTell(f"--store needs PyYAML and this checkout's engine: {exc}") from exc
    try:
        plan = waves.load(store)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:   # research_graph.yamlio.load's errors
        raise CannotTell(f"--store {store}: cannot be read: {type(exc).__name__}: {exc}") from exc
    return waves.closure_problems(plan, version)


def _waves(repo: Path):
    """brain.waves: the installed engine's when it has it (CI installs this checkout), else this checkout's source
    (``packages/brain/src`` and ``src`` for research_graph), added at the end of sys.path so that an engine already
    imported is never shadowed by another ``src`` folder."""
    try:
        from brain import waves
        return waves
    except ImportError:
        for src in (repo / "src", (repo / SRC).parent):
            src = str(src.resolve())
            if src not in sys.path:
                sys.path.append(src)
        from brain import waves
        return waves


def readable_store(store: Path) -> None:
    """:class:`CannotTell` unless ``store`` is a graph store (its ``nodes/``)."""
    if not (store / "nodes").is_dir():
        raise CannotTell(f"--store {store}: not a graph store (no nodes/)")


def check(repo: Path, tag: str, store: Path | None = None) -> tuple[list[str], list[str]]:
    """(what it says, what fails) for the checkout ``repo`` against the tag ``tag``; ``store``: the graph store whose
    wave of this version must be closed."""
    versions = {name: version_in(repo, path) for name, path in VERSIONS.items()}
    for name, version in versions.items():
        if not version:
            return [], [f"{VERSIONS[name]}: no __version__ ({name})"]
    import changelog as frag   # beside this file (sys.path above): wi-brain-changelog-unreleased-collisions
    fragments = frag.check(repo)   # every PR: a malformed fragment, or a '## Unreleased' section again
    if all(version == tag.removeprefix("v") for version in versions.values()):
        return [f"not a version PR: both distributions are at {tag}; the changelog fragments checked"], fragments
    if len(set(versions.values())) > 1:
        return [], [f"the versions differ: {versions}; a tag is both distributions at one version"]
    version = versions["brain"]
    said = [f"version PR: {tag} -> {version}"]
    problems = fragments + coherence(repo, tag, version)
    problems += [f"{p}: a fragment not compiled into ## {version} (python {BRAIN}/installer/changelog.py compile "
                 f"{version} --theme T --write)" for p in frag.pending(repo)]
    changed, grown = moved_schemas(repo, tag, changed_schemas(repo, tag))
    added = {path for name in new_formats(repo, tag) for path in SCHEMAS[name]}
    if [p for p in grown if p in added]:
        said.append(f"new registered formats since {tag}, held by no brain yet (compatible with a patch): "
                    f"{', '.join(p for p in grown if p in added)}")
    if [p for p in grown if p not in added]:
        said.append(f"registered schemas grown by optional keys only since {tag} (compatible with a patch): "
                    f"{', '.join(p for p in grown if p not in added)}")
    changelog = f"{BRAIN}/CHANGELOG.md"
    upgrade = upgrade_section(read(repo, changelog), version)
    if not changed:
        said.append(f"no registered schema changed since {tag}")
    else:
        said.append(f"registered schemas changed since {tag}: {', '.join(changed)}")
        if not upgrade:
            problems.append(f"{changelog}: registered schemas changed since {tag} ({', '.join(changed)}) and the "
                            f"section ## {version} has no ### Upgrade with something in it: number the standard "
                            f"steps and what an owner does beyond them (docs/release.md, « The standard steps »)")
    problems += sections(repo, version, upgrade)
    if is_patch(tag, version):
        said.append(f"a patch of {tag}: it may hold no schema that moves and no Upgrade step beyond the standard ones")
    problems += policy(tag, version, changed, upgrade)
    if store is not None:
        closure = wave_closure(repo, store, version)
        said.append(f"the wave {version} in {store}: " + ("open items left" if closure else "closed or none"))
        problems += closure
    return said, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The version PR's check (docs/release.md).")
    ap.add_argument("--repo", default=".", help="the checkout (default: here)")
    ap.add_argument("--against", default="", help="the tag to compare with (default: the last tag before HEAD)")
    ap.add_argument("--store", default="", help="the graph store that plans the releases: its wave of this version "
                                                "must be closed (brain wave close)")
    args = ap.parse_args(argv)
    # Its messages quote docs/release.md's « » titles: a pipe on Windows is in the ANSI code page, and a reader of
    # UTF-8 (CI, a test) would fail on them. A console is written in UTF-16 whatever this says.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    repo = Path(args.repo)
    try:
        if args.store:   # on any PR: a --store that is no store is said, not skipped with the rest
            readable_store(Path(args.store))
        said, problems = check(repo, args.against or last_tag(repo), Path(args.store) if args.store else None)
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
