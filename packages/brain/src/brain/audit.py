"""``brain audit``: per repo and module, what misses the standard, measured at zero token (spec 2026-10-30 section
3.18, Q16 A: measure first; the answers Q1-Q4 of 2026-11-02 in the ADR "brain audit : mesurer la dette de
conformité à zéro token").

A full audit reads each repo of a project (``repos:`` in projects.yaml) at the tip of its default branch, or at HEAD
in a linked worktree, through git plumbing: committed state only, the same code path as the trend. The checks are
CHECKS (RULESET; a change of check or severity needs an ADR and a ruleset bump): P0 when the repo states something
false, P1 for a gap on a production path (a unit the static closure from the declared entries reaches, class entry
or prod), P2 elsewhere, info never counted. The checks a generator will own are PENDING: listed per repo as not
measured, never counted, never in an exit code, but they keep the milestone ms-brain-conformance from being met. A
generator turns its checks on by giving them a ``run`` (and a CHECKS entry): doc.links and test.links (brain.links)
are measured where the repo's own store has the Doc and Test types, features.md and feature.links (brain.features)
in a project whose store has the Feature type; else they are still listed as not measured, and still keep the
milestone from being met when they would carry P0 or P1. feature.coverage (brain.feature_coverage) lists, as info and
in a section of its own per repo, the commands and modules of a command registry that no feature names.

Outputs: text (every P0 and P1, a count and three examples per P2 check; -v for all), --json (stable keys, no
timestamp), --trend [N] (the last N completed ISO weeks re-measured at their end commit with today's rules),
--write (the view notes/audit.md, from a worktree), --items (one debt item per repo, priority proposed, never closed,
reopened or linked automatically). Exit codes: 0 the report was produced (debt alone never fails it); 1 --fail-on
and a finding at that severity or above, or a refused write; 2 a registry or usage error, or a git failure.
``brain audit --diff`` is the scout (brain.scout).
"""

from __future__ import annotations

import ast
import json
import os
import posixpath
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import config, feature_coverage, features, graph, inventory, links, paths, projects, public, readme, testcov
from .inventory import AuditError

RULESET = 7   # 2: doc.links and test.links measured (wi-brain-doc-test-links); 3: features.md and feature.links
#               (wi-brain-feature-matrix); 4: test.coverage measured (wi-brain-test-coverage) and feature.tests
#               (wi-brain-test-links-auto); 5: cmd.registry (wi-brain-cli-registry); 6: feature.coverage, info in
#               the full audit, NEW in the scout for an added command or module (wi-brain-audit-feature-coverage); 7: the scout's norm lints
#               (brain.norms: norm.timeout, norm.encoding, norm.naive-time, norm.secret-argv), info on what a change
#               adds, NEW under config.json audit.norm_lints_strict, DEFER for a touched file's old ones
#               (wi-brain-norm-lints)
# the scout's calibration (wi-brain-scout-rule, design section 8: fewer than 10 % wrong per check; the numbers are in
# the journal and on the item); a detection change that the numbers do not cover clears it until measured again
CALIBRATED = ("2026-11-02 (83 flagged units checked by hand over brain audit --all and --diff on 50 merges, 2 wrong; "
              "every check under 10 %)")
SEVERITIES = ("P0", "P1", "P2")
MILESTONE = "ms-brain-conformance"
VIEW = "notes/audit.md"
STREAK = 4
README_LINES = 10
COVERAGE_FLOOR = 50.0   # a module the tests run less of (percent of its statements) is a test.coverage finding
SECTIONS = {"install": ("install", "setup", "getting started"),
            "usage": ("usage", "quick start", "quickstart", "example", "commands"),
            "tests": ("test", "development", "contributing")}
DOC_PATH = re.compile(r"(?<![\w./\\-])((?:[\w.-]+/)+[\w.-]*[\w-]\.(?:py|ps1|sh|md|yaml|psd1))(?![\w-])")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
BACKTICK = re.compile(r"`([^`\s]+)`")
TICK_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
FILE_EXTS = {"py", "md", "yaml", "yml", "json", "jsonl", "toml", "txt", "csv", "parquet", "ps1", "psd1", "psm1",
             "sh", "bat", "cmd", "ipynb", "html", "log", "lock", "cfg", "ini", "exe"}
EXTERNAL = re.compile(r"https?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org)/[\w.-]+/([\w.-]+)")


@dataclass(frozen=True)
class Check:
    id: str
    severity: str     # P0, P2 or info; 'class': P1 on an entry or prod unit, P2 elsewhere
    scout: str        # in --diff: 'new+left', 'new' (added units only), 'new+defer' (NEW on an added unit, even an
    #                   info; DEFER on a touched one, LEFT under the owner's opt-in: brain.scout) or 'never'
    what: str


CHECKS = {c.id: c for c in (
    Check("readme.exists", "P0", "new+left", "a tracked root README.md with 10 non-blank lines or more"),
    Check("doc.dead-ref", "P0", "new+left", "a doc names a module (-m) or a repo file that does not exist"),
    Check("coderef.dangling", "P0", "new+left", "an active CodeRef points at a missing file or symbol"),
    Check("test.module", "class", "new+left", "a Python module with no test evidence"),
    Check("test.script", "class", "new+left", "a script no test runs"),
    Check("cmd.documented", "class", "new+left", "a console script or command module the docs never name"),
    Check("cmd.registry", "class", "new+left", "a command outside the command registry: a parser the cli.py beside a "
          "commands/ package that lists its modules adds itself, or a module of that package with no register"),
    Check("coderef.module", "P2", "new", "a module of a repo with a code layer has no CodeRef"),
    Check("readme.sections", "P2", "never", "README headings for install, usage and tests (until readme.generated)"),
    # opt-in (wi-brain-readme-sync): measured only in a repo whose tree holds readme.yaml (brain.readme)
    Check("readme.yaml", "P1", "new+left", "an opted-in repo's readme.yaml misses a required field or breaks its "
          "schema (schemas/readme.schema.json)"),
    Check("help.quoted", "P1", "new+left", "a command an opted-in repo's readme.yaml quotes is gone: its --help "
          "does not run"),
    Check("doc.links", "P2", "new+left", "a doc no section of which documents a graph node, or a spec no Spec node "
          "anchors"),
    Check("test.links", "P2", "never", "a test module no graph node is tested_by (no Hook, and no node implemented_by "
          "a CodeRef, stands for its code)"),
    Check("test.coverage", "P2", "never", f"a Python module the tests run under {COVERAGE_FLOOR:g} % of, by the "
          "store's coverage summary (brain coverage)"),
    Check("feature.tests", "P2", "never", "a have or partial feature with code that no test module is tested_by "
          "(no test imports, names or runs its code)"),
    # a generated view: the default branch's to hold fresh (brain check there, brain.views), never a branch's to fix
    Check("features.md", "P0", "never", "FEATURES.md is not the render of the graph (P0), or is missing (P1 on a "
                                        "production repo, P2 elsewhere)"),
    Check("feature.links", "class", "new+left", "a module or script no feature is implemented by, or a have or "
                                                "partial feature with no implemented_by"),
    # info in the full audit (its own section lists them), never counted: a shipped capability is listed, not a debt
    Check("feature.coverage", "info", "new+defer", "a command (a module of a command registry's commands/) or a "
          "module beside the registry's cli.py that no feature names: no implemented_by of its file, no title that "
          "says its command or its dotted name"),
)}


@dataclass(frozen=True)
class Pending:
    owner: str        # the item that will measure it
    blocks: bool      # it would carry P0 or P1: the milestone waits on it
    applies: str      # every, code, python, commands, ts, no-code-layer
    run: object = None   # a generator's PR sets it (its own ADR): the check is then measured; run(ctx) returns the
    #                      findings, or why this repo cannot be measured (listed as not measured)


# --- doc.links and test.links (brain.links, wi-brain-doc-test-links) ---

def _derived(ctx: dict) -> links.Links:
    """The repo's Doc and Test links at the tree measured, from the audit's own facts and test evidence; against the
    store of another repo of the project (its holder's tree) when the repo has none of its own."""
    if "links" not in ctx["cache"]:
        rf, (rel, _, holder) = ctx["rf"], ctx["store"]
        home = ctx["trees"][holder] if holder != rf.name else None
        hand = (links.store_nodes(home, rel), links.store_edges(home, rel)) if home is not None else (None, None)
        ctx["cache"]["links"] = links.derive(rf.tree, rf.name, rel, rf, ctx["idx"], ctx["mod_ev"], hand=hand[0],
                                             hand_edges=hand[1], home=home)
    return ctx["cache"]["links"]


def _no_store(ctx: dict, node_type: str) -> str:
    """Why the repo's links cannot be measured ('' when its store takes ``node_type``)."""
    if not ctx["store"]:
        return "no store of its own to hold the links, and no CodeRef of the project's store names it"
    rel, types, _ = ctx["store"]
    return "" if node_type in types else f"{rel} has no {node_type} type"


def doc_links(ctx: dict) -> list[dict] | str:
    """doc.links: a spec no Spec node anchors (its sections are part of nothing), a doc of the docs set none of
    whose sections documents a graph node."""
    why = _no_store(ctx, "Doc")
    if why:
        return why
    lk, name, rel = _derived(ctx), ctx["rf"].name, ctx["store"][0]
    out = [finding(name, "doc.links", p, "no Spec node anchors this spec: its sections are part of nothing",
                   f"add a Spec node anchored at {p} to {rel}") for p, s in sorted(lk.specs.items()) if not s]
    for p, ids in sorted(lk.docs.items()):
        if p not in lk.specs and not set(ids) & lk.documented:
            out.append(finding(name, "doc.links", p, "no section names a graph node (a node id, a hook script, a "
                               "skill or plugin folder, a CodeRef file)",
                               "name in it what it documents (items, hooks, code), then brain sync"))
    return out


def test_links(ctx: dict) -> list[dict] | str:
    """test.links: a test module no graph node is tested_by (no Hook stands for the code it covers, and no node is
    implemented_by a CodeRef of it)."""
    why = _no_store(ctx, "Test")
    if why:
        return why
    lk, name, out = _derived(ctx), ctx["rf"].name, []
    for p, tid in sorted(lk.tests.items()):
        if tid in lk.tested:
            continue
        cov = lk.covers.get(p) or []
        what = (f"it covers {', '.join(cov[:2])}{' and more' if len(cov) > 2 else ''}, which no Hook stands for and "
                "no node is implemented_by a CodeRef of" if cov else "it covers no module or script of the repo")
        out.append(finding(name, "test.links", p, f"no graph node is tested_by it: {what}",
                           "a CodeRef of the code it tests, implemented_by from its item or feature; brain sync "
                           "links it"))
    return out


def test_coverage(ctx: dict) -> list[dict] | str:
    """test.coverage: a Python module of the repo that its tests run under COVERAGE_FLOOR % of, by the coverage summary
    the store keeps (brain coverage --write, brain.testcov); a module the summary does not know (added since) is not
    counted. Not measured without a summary. The trend reads today's summary (``ctx["coverage"]``, from measure), so
    the week a summary is first committed is no rise of the debt."""
    if not ctx["store"]:
        return "no store to keep its coverage summary"
    rel, rf = ctx["store"][0], ctx["rf"]
    cov = ctx["coverage"]
    if cov is None:
        return f"no coverage summary in {rel} (brain coverage --run --write)"
    files, at, out = cov.get("files") or {}, str(cov.get("commit") or "?")[:7], []
    for u in rf.units:
        f = files.get(u.path) if u.kind == "module" else None
        if f and f.get("statements") and float(f.get("percent", 100)) < COVERAGE_FLOOR:
            out.append(finding(rf.name, "test.coverage", u.path, f"the tests run {f['percent']:g} % of its "
                               f"{f['statements']} statements (coverage at {at})",
                               "test its paths no test runs, then brain coverage --run --write", u))
    return out


def feature_tests(ctx: dict) -> list[dict] | str:
    """feature.tests: a have or partial feature with code in the repo (a module or a script its CodeRefs name, whichever
    repo owns the feature; a data file is no code a test imports) that no test module of the repo is tested_by (the
    links derived now: its CodeRefs' tests by brain audit's evidence, imports and coverage, brain.links)."""
    fm = ctx.get("features")
    if fm is None:
        return NO_FEATURES
    why = _no_store(ctx, "Test")
    if why:
        return why
    rf = ctx["rf"]
    lk, name, out = _derived(ctx), rf.name, []
    tested = {e["from"] for e in lk.edges if e["type"] == "tested_by"}
    units = {u.path for u in rf.units if u.kind in ("module", "script")}
    for fid in sorted(fm.features):
        status = fm.features[fid].get("status")
        if status not in ("have", "partial") or fid in tested:
            continue
        code = [c for c in fm.code(fid) if links.code_ref_file(rf.tree, name, c) in units]
        if code:
            out.append(finding(name, "feature.tests", fid, f"a {status} feature no test module is tested_by: no test "
                               f"imports, names or runs {', '.join(c.split(':', 2)[2] for c in code[:2])}"
                               f"{' and more' if len(code) > 2 else ''}",
                               "a test of its code (importing its module, naming its symbol), then brain sync"))
    return out


# --- features.md and feature.links (brain.features, wi-brain-feature-matrix) ---

NO_FEATURES = "no Feature type in the project's store"


def features_md(ctx: dict) -> list[dict] | str:
    """features.md: the repo's root FEATURES.md is the render of the committed graph's Feature nodes whose repo it is:
    the public render when the repo's checkout is a clone of a public repo (brain.features.public_checkout), the full
    render accepted too unless config.json features.public_strict (brain.features.also_accepted)."""
    fm, c = ctx.get("features"), ctx["cfg"]
    if fm is None:
        return NO_FEATURES
    t, name = ctx["rf"].tree, c.name
    pub = name in ctx.get("fpublic", set())
    why = features.check_view(t.text(features.VIEW) if t.has(features.VIEW) else None,
                              features.render(fm, name, ctx["flabel"], public=pub),
                              features.also_accepted(fm, name, ctx["flabel"], pub, ctx.get("fstrict", False)))
    fix = ("brain features render --write (run by brain sync), then commit it" if name in ctx.get("fhome", {name})
           else f"from the brain's worktree, brain features render --repo {name} --out <a worktree of {name}>/"
                f"{features.VIEW} --write{' (the public render)' if pub else ''}, then commit it there")
    if why == "missing":
        return [finding(name, "features.md", features.VIEW, "no FEATURES.md (the repo's feature matrix)", fix,
                        sev="P1" if c.production or c.entry is not None else "P2")]
    return [finding(name, "features.md", features.VIEW, f"FEATURES.md is {why}: it is not the render of the Feature "
                    "nodes", fix)] if why else []


def feature_links(ctx: dict) -> list[dict] | str:
    """feature.links: every module and script is implemented_by-linked from a feature (P1 on a production path), and
    every have or partial feature of the repo has code."""
    fm, rf = ctx.get("features"), ctx["rf"]
    if fm is None:
        return NO_FEATURES
    name, out = rf.name, []
    linked = feature_coverage.feature_paths(fm, name)
    for u in rf.units:
        if u.kind in ("module", "script") and u.path not in linked:
            out.append(finding(name, "feature.links", u.path, "no feature is implemented by it",
                               f"brain features link <feature> --code {u.path} (or brain features add)", u))
    for fid in sorted(fm.features):
        status = fm.features[fid].get("status")
        if fm.repo.get(fid) == name and status in ("have", "partial") and not fm.code(fid):
            out.append(finding(name, "feature.links", fid, f"a {status} feature with no implemented_by (no active "
                               "CodeRef)", f"brain features link {fid} --code <path>[::<symbol>]", sev="P1"))
    return out


def feature_cover(ctx: dict) -> list[dict] | str:
    """feature.coverage (brain.feature_coverage): a command or module of the repo's command registry that no feature
    names; its section ({units, named, unnamed}) is kept in ctx's cache for the repo's result."""
    fm, rf = ctx.get("features"), ctx["rf"]
    if fm is None:
        return NO_FEATURES
    found = feature_coverage.targets(rf, _registries(rf.tree))
    if not found:
        return []
    missing = feature_coverage.unnamed(fm, rf.name, found)
    ctx["cache"]["feature.coverage"] = feature_coverage.summary(found, missing)
    return [finding(rf.name, "feature.coverage", t.unit.path, f"no feature names this {t.kind} ({t.label}): no "
                    f"implemented_by of its file, no title that says {t.phrases[0]}",
                    f"brain features link <feature> --code {t.unit.path} (or brain features add)", t.unit)
            for t in missing]


NO_README = f"no {readme.FILE} (not opted in to a generated README: brain docs, wi-brain-readme-sync)"


def _readme_spec(ctx: dict) -> dict | str:
    """The repo's committed readme.yaml as a mapping, or why it is not measured (no readme.yaml: not opted in)."""
    t = ctx["rf"].tree
    if not t.has(readme.FILE):
        return NO_README
    try:
        data = graph.load_yaml(t.text(readme.FILE))
    except (ValueError, graph._yaml().YAMLError) as exc:
        return {"__error__": f"{readme.FILE} cannot be read ({exc})"}
    return data if isinstance(data, dict) else {"__error__": f"{readme.FILE} is not a mapping"}


def readme_yaml(ctx: dict) -> list[dict] | str:
    """readme.yaml (brain.readme): an opted-in repo's readme.yaml holds its required fields and fits its schema."""
    spec = _readme_spec(ctx)
    if isinstance(spec, str):
        return spec
    name = ctx["rf"].name
    errors = [spec["__error__"]] if "__error__" in spec else readme.spec_errors(spec)
    return [finding(name, "readme.yaml", readme.FILE, e, f"fix {readme.FILE} (schemas/readme.schema.json), then "
                    "brain docs render --write") for e in errors]


def help_quoted(ctx: dict) -> list[dict] | str:
    """help.quoted (brain.readme): every command an opted-in repo's readme.yaml quotes still answers --help (run in
    the repo's checkout)."""
    spec = _readme_spec(ctx)
    if isinstance(spec, str):
        return spec
    if "__error__" in spec:
        return []   # readme.yaml says why
    c = ctx["cfg"]
    return [finding(c.name, "help.quoted", readme.FILE, line.removeprefix(f"{readme.FILE}: "),
                    f"change or remove it in {readme.FILE}, then brain docs render --write")
            for line in readme.gone(spec, Path(c.path))]


PENDING = {
    "readme.yaml": Pending("wi-brain-readme-sync", True, "every", readme_yaml),
    # the README against its render: brain docs check and brain check (a generated view, the default branch's to hold)
    "readme.generated": Pending("wi-brain-readme-sync", True, "every"),
    "help.quoted": Pending("wi-brain-readme-sync", True, "every", help_quoted),
    "features.md": Pending("wi-brain-feature-matrix", True, "code", features_md),
    "feature.links": Pending("wi-brain-feature-matrix", True, "code", feature_links),
    "doc.links": Pending("wi-brain-doc-test-links", False, "every", doc_links),
    "test.links": Pending("wi-brain-doc-test-links", False, "code", test_links),
    "test.coverage": Pending("wi-brain-test-coverage", False, "python", test_coverage),
    "feature.tests": Pending("wi-brain-test-links-auto", False, "code", feature_tests),
    "feature.coverage": Pending("wi-brain-audit-feature-coverage", False, "commands", feature_cover),
    "module.ts": Pending("wi-brain-audit-ts", False, "ts"),
    "cmd.leaves": Pending("wi-brain-audit-commands", False, "commands"),
    "code.layer": Pending("wi-brain-brain-coderefs", False, "no-code-layer"),
}


def severity(check: str, cls: str) -> str:
    sev = CHECKS[check].severity
    return ("P1" if cls in ("entry", "prod") else "P2") if sev == "class" else sev


def finding(repo: str, check: str, unit: str, why: str, fix: str, u: inventory.Unit | None = None,
            via: str = "", sev: str = "") -> dict:
    """One finding; ``u`` gives the class (and how the closure reached it) of a unit-level check."""
    cls = u.cls if u else ""
    return {"key": f"{repo}:{check}:{unit}", "check": check, "severity": sev or severity(check, cls), "unit": unit,
            "class": cls, "chain": u.chain if u else "", "via": via, "why": why, "fix": fix}


# --- measuring a project ---

def _rel(path: Path, base: Path) -> str | None:
    try:
        rel = os.path.relpath(path, base)
    except ValueError:  # another drive
        return None
    return None if rel.startswith("..") else Path(rel).as_posix()


def _store_refs(p: projects.Project, cfgs: list[projects.Repo]) -> list[tuple[str, str]]:
    out = []
    for s in p.stores:
        for c in cfgs:
            rel = _rel(s, c.path)
            if rel is not None:
                out.append((c.name, rel))
                break
    return out


def _chain(depth_chain) -> str:
    depth, chain = depth_chain
    if not chain:
        return ""
    return " > ".join(("...",) + chain[-3:] if len(chain) > 4 else chain)


def _docs_index(rf: inventory.RepoFacts) -> dict:
    """What the docs set names: words, dotted names (a `make <target>` names the modules its recipe runs with -m),
    file paths (and their suffixes), backticked words and the leading parts of a backticked dotted name (a catalog's
    `stationarity.adf_test` names the module stationarity; `config.yaml` names no module), and the text itself."""
    words: set = set()
    dotted: set = set()
    ticks: set = set()
    files: dict = {}
    texts = []
    make = inventory.make_targets(rf.tree)
    for d in rf.docs:
        text = rf.tree.text(d) or ""
        texts.append(text)
        words.update(inventory.WORD.findall(text))
        dotted.update(inventory.DOTTED.findall(text))
        dotted.update(inventory.DASH_M.findall(text))   # python -m <package>
        for target in inventory.MAKE_CALL.findall(text):
            dotted.update(make.get(target, ()))
        for tok in BACKTICK.findall(text):
            ticks.add(tok)
            m = TICK_DOTTED.match(tok)
            if m and m.group(0).rsplit(".", 1)[1].lower() not in FILE_EXTS:
                parts = m.group(0).split(".")
                ticks.update(".".join(parts[:i]) for i in range(1, len(parts)))
        inventory.text_tokens(text, {}, files, d)
    return {"words": words, "dotted": dotted, "files": files, "ticks": ticks, "text": "\n".join(texts)}


def _named(files: dict, path: str) -> bool:
    """A doc names ``path``, or a path ending like it (hooks/capture.sh names plugins/x/hooks/capture.sh)."""
    segs = path.split("/")
    return any("/".join(segs[i:]) in files for i in range(len(segs)))


def _documented(u: inventory.Unit, rf: inventory.RepoFacts, docs: dict, shims: dict) -> bool:
    """cmd.documented: a console script named as a word, or its module, or its file (a package.json bin: also the
    README of its package); a command module by dotted path, -m, file path or backticked stem, or through a shim
    script of it that the docs name (the hook capture.sh runs capture.py, which runs brain.capture)."""
    t = rf.tree
    if u.name in rf.console:
        target = rf.console[u.name]
        if u.name in docs["words"] or target in docs["dotted"] or _named(docs["files"], target):
            return True
        base = target.rsplit("/", 1)[-1]
        if "." in base and re.search(rf"(?<![\w.-]){re.escape(base)}(?![\w-])", docs["text"]):
            return True
        pkg = posixpath.dirname(rf.bins.get(u.name, ""))
        return bool(pkg) and f"{pkg}/README.md" in rf.docs
    root = rf.root_of.get(u.path, "")
    if u.name in docs["dotted"] or _named(docs["files"], u.path) or u.name.split(".")[-1] in docs["ticks"] \
            or (root and _named(docs["files"], u.path[len(root) + 1:])):
        return True
    for s in shims.get(u.path, []):
        folder, stem_ = posixpath.dirname(s), posixpath.basename(s).rsplit(".", 1)[0]
        same = [p for p in t.files if posixpath.dirname(p) == folder and posixpath.basename(p).rsplit(".", 1)[0]
                == stem_]
        if any(_named(docs["files"], p) for p in same):
            return True
    return False


def _parsers_added(text: str) -> list[str]:
    """The parsers a Python file adds itself: the name of each add_parser call ("?" when it is not a literal)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "add_parser"), key=lambda n: (n.func.end_lineno, n.func.end_col_offset))
    return [str(n.args[0].value) if n.args and isinstance(n.args[0], ast.Constant) else "?" for n in calls]


def _registries(t: inventory.Tree) -> list[str]:
    """The prefix of each package of the tree whose commands/ lists its own modules (a command registry)."""
    inits = [p for p in sorted(t.files) if p == "commands/__init__.py" or p.endswith("/commands/__init__.py")]
    return [p[:-len("commands/__init__.py")] for p in inits if inventory.facts(t, p).discovers]


def _imports_register(text: str) -> bool:
    """A module-level import binds the name register (from ._impl import register; inventory.has_symbol reads
    definitions only)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return any((a.asname or a.name) == "register" for s in tree.body if isinstance(s, ast.ImportFrom) for a in s.names)


def _unregistered(t: inventory.Tree, pkg: str) -> list[str]:
    """The modules of ``pkg``commands/ (not the ``_`` helpers) that define or import no register."""
    mods = [p for p in sorted(t.files) if posixpath.dirname(p) == f"{pkg}commands" and p.endswith(".py")]
    return [p for p in mods if not posixpath.basename(p).startswith("_")
            and inventory.has_symbol(t, p, "register") is False and not _imports_register(t.text(p) or "")]


def registry_findings(repo: str, rf: inventory.RepoFacts) -> list[dict]:
    """cmd.registry (wi-brain-cli-registry): in a package whose commands/ lists its own modules (a command registry,
    brain.commands), the cli.py beside it adds no parser itself, and every module of commands/ but the ``_`` ones
    (helpers) defines register: a command is a module of the registry, never a line of a shared file."""
    t = rf.tree
    units = {u.path: u for u in rf.units if u.kind == "module"}
    out = []
    for pkg in _registries(t):
        cli = f"{pkg}cli.py"
        names = _parsers_added(t.text(cli) or "") if t.has(cli) else []
        if names:
            shown = ", ".join(names[:5]) + ("..." if len(names) > 5 else "")
            out.append(finding(repo, "cmd.registry", cli, f"{cli} adds {len(names)} parser(s) itself, outside the "
                               f"command registry: {shown}", f"make each command a module of {pkg}commands/ (its "
                               "register, run or early)", units.get(cli)))
        out += [finding(repo, "cmd.registry", path, f"{path} is a command module with no register: brain never adds "
                        "its command", "define register(sub, ctx), or name it _<name>.py (a helper, not a command)",
                        units.get(path)) for path in _unregistered(t, pkg)]
    return out


def _readme(rf: inventory.RepoFacts) -> str:
    return next((p for p in sorted(rf.tree.files) if "/" not in p and p.lower() == "readme.md"), "")


def _headings(text: str) -> list[str]:
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence:
            m = HEADING.match(line)
            if m:
                out.append(m.group(1).strip().lower())
    return out


def _test_dir(rf: inventory.RepoFacts) -> str:
    dirs = sorted({t.split("/", 1)[0] for t in rf.tests if "/" in t})
    return "tests" if "tests" in dirs or not dirs else dirs[0]


def measure(p: projects.Project, cfgs: list[projects.Repo], trees: dict[str, inventory.Tree],
            only: set[str] | None = None, layered: set[str] | None = None,
            extra_dirs: dict[str, set] | None = None, linked: dict | None = None,
            featured: bool | None = None, coverage: dict | None = None) -> dict:
    """Every check on every repo of ``p`` that has a tree (its findings only for the repos in ``only`` when given):
    the project's result, as the JSON output carries it. ``layered``: the repos whose store has a code layer, given
    by the trend from today's measure (a layer added since then is a rule of today, not a rise of the debt);
    ``linked``, likewise, the repos whose own store takes the Doc and Test links (doc.links, test.links), and
    ``featured``, whether the project's store has the Feature type (then a week before it has no feature), and
    ``coverage``, each repo's coverage summary (test.coverage: a summary committed since is a rule of today).
    ``extra_dirs``: more top-level folders whose paths a doc names are checked (the scout passes the base tree's, so
    a folder a change empties still has its dead references)."""
    cfgs = [c for c in cfgs if c.name in trees]
    fm, flabel, fhome = _feature_model(p, cfgs, trees)
    fpublic, fstrict = _public_repos(p, cfgs) if fm is not None else (set(), False)
    if featured is None:
        featured = fm is not None
    fm = (fm or features.Model()) if featured else None
    facts = {c.name: inventory.collect(trees[c.name], c.name, c.lang, c.roots, c.waive) for c in cfgs}
    idx = inventory.Index.build(facts)
    tops = idx.top_packages()
    seeds = {}
    for c in cfgs:
        if c.entry is not None:
            seeds[c.name] = list(c.entry)
        elif c.production:
            seeds[c.name] = [f"script:{n}" for n in facts[c.name].console]
    reached, missing = inventory.closure(facts, seeds, idx)
    hit_repos = {r for r, _ in reached}
    for c in cfgs:
        seeded = len(missing.get(c.name, [])) < len(seeds.get(c.name, []))
        rf = facts[c.name]
        # conservative: a production repo (listed, or with declared entries) that no entry reaches is all production
        rf.no_entry = (c.production or c.entry is not None) and not seeded and c.name not in hit_repos
        for u in rf.units:
            got = reached.get((c.name, u.path))
            if rf.no_entry:
                u.cls, u.chain = "prod", "no entry declared"
            elif got:
                u.cls, u.chain = ("entry" if got[0] <= 1 else "prod"), _chain(got)
    stores = inventory.code_stores(facts, _store_refs(p, cfgs))
    mod_evidence: dict[tuple[str, str], tuple[str, list]] = {}
    for c in cfgs:
        for path, got in inventory.unit_evidence(facts[c.name], idx, tops).items():
            mod_evidence[(c.name, path)] = got
    covered: dict[str, set] = {}
    unregistered: dict[str, list] = {}
    dangling: dict[str, list] = {}
    for st in stores:
        for cid, status in st.code_refs:
            if status != "active":
                continue
            try:
                repo, path, sym = inventory.parse_code_ref(cid)
            except ValueError as exc:
                dangling.setdefault(st.repo, []).append(finding(st.repo, "coderef.dangling", cid,
                                                                f"malformed CodeRef id: {exc}", "fix the id"))
                continue
            target = facts.get(repo.lower())
            if target is None:
                unregistered.setdefault(st.repo, []).append(repo)
                continue
            t = target.tree
            file = f"src/{path}" if t.has(f"src/{path}") else path
            covered.setdefault(target.name, set()).add(file)
            why = ""
            if not t.has(file):
                why = f"neither src/{path} nor {path} in {target.name}"
            elif sym:
                ok = inventory.has_symbol(t, file, sym)
                why = "" if ok else f"{file} does not parse" if ok is None else f"{sym} is not defined in {file}"
            if why:
                dangling.setdefault(st.repo, []).append(finding(
                    st.repo, "coderef.dangling", cid, why,
                    f"point it at the moved code, or retire it (status: retired) in {st.repo}/{st.path}"))
    if layered is None:
        layered = {name for st in stores if st.code_layer for name in facts if f"repo-{name}" in st.repo_nodes}
    if linked is None:
        linked = _linked_stores(p, cfgs, trees)
    if coverage is None:
        coverage = {c.name: testcov.load(trees[linked[c.name][2]], linked[c.name][0], c.name)
                    for c in cfgs if c.name in linked and linked[c.name][2] in trees}
    out_repos = []
    for c in cfgs:
        rf = facts[c.name]
        if only is not None and c.name not in only:
            continue
        ctx = {"rf": rf, "idx": idx, "store": linked.get(c.name), "cache": {}, "cfg": c, "features": fm, "trees": trees,
               "flabel": flabel, "fhome": fhome, "fpublic": fpublic, "fstrict": fstrict, "coverage": coverage.get(c.name),
               "mod_ev": {path: v for (r, path), v in mod_evidence.items() if r == c.name}}
        out_repos.append(_repo_result(c, rf, idx, tops, mod_evidence, facts, dangling.get(c.name, []),
                                      sorted(set(unregistered.get(c.name, []))), covered, layered,
                                      missing.get(c.name, []), (extra_dirs or {}).get(c.name, set()), ctx))
    return {"name": p.name, "root": str(p.root), "repos": out_repos, "counts": _sum(out_repos), "facts": facts,
            "mod_evidence": mod_evidence, "layered": layered, "linked": linked, "featured": featured,
            "coverage": coverage}


def _feature_model(p: projects.Project, cfgs: list[projects.Repo],
                   trees: dict[str, inventory.Tree]) -> tuple[features.Model | None, str, set[str]]:
    """The Feature nodes of the project's stores with the Feature type, read from the trees (committed state), the
    first such store's folder (FEATURES.md names it) and the repos that hold them (brain sync renders their
    FEATURES.md; another repo's is rendered into its checkout); None when no store has the type."""
    models, label, home = [], "", set()
    for repo, rel in _store_refs(p, cfgs):
        if repo not in trees:
            continue
        try:
            m = features.load_tree(trees[repo], rel, repo)
        except features.FeatureError as exc:
            raise AuditError(f"{repo}/{rel}: {exc}") from exc
        if m is not None:
            models.append(m)
            label = label or rel
            home.add(repo)
    return (features.merge(models) if models else None), label or "notes/graph", home


def _public_repos(p: projects.Project, cfgs: list[projects.Repo]) -> tuple[set[str], bool]:
    """(the project's repos whose checkout is a clone of a public repo (config.json public.repos): their FEATURES.md
    is the public render; whether only that render passes, config.json features.public_strict)."""
    cfg = config.load(p.root)
    repos = {c.name for c in cfgs if features.public_checkout(c.path, cfg)} if public.public_repos(cfg) else set()
    return repos, features.public_strict(cfg)


def _store_types(t: inventory.Tree, rel: str) -> list[str]:
    schema = inventory._load_yaml(t, f"{rel}/schema.yaml")
    types = set(schema.get("node_types") or []) if isinstance(schema, dict) else set()
    return sorted(types & set(links.TYPES))


def _linked_stores(p: projects.Project, cfgs: list[projects.Repo], trees: dict[str, inventory.Tree]) -> dict:
    """Repo -> (the folder of the store that takes its links, the Doc, Test and Workflow types its schema has, the
    repo that holds it): its own store (a declared store of the project inside the repo, else its notes/graph), else
    the first store of the project, held by another repo, that takes the links and whose CodeRefs name it (brain sync
    derives its links there, brain.links)."""
    refs = _store_refs(p, cfgs)
    out = {}
    for c in cfgs:
        t = trees[c.name]
        cands = [r for n, r in refs if n == c.name] + ["notes/graph"]
        rel = next((x for x in cands if t.has(f"{x}/schema.yaml")), "")
        if rel:
            out[c.name] = (rel, _store_types(t, rel), c.name)
    for c in cfgs:
        if c.name in out:
            continue
        for holder, rel in refs:
            h = trees.get(holder)
            if holder == c.name or h is None or not h.has(f"{rel}/schema.yaml"):
                continue
            types = _store_types(h, rel)
            if {"Doc", "Test"} & set(types) and c.name in links.coded_repos(links.store_nodes(h, rel)):
                out[c.name] = (rel, types, holder)
                break
    return out


def _sum(repos: list[dict]) -> dict:
    return {s: sum(r.get("counts", {}).get(s, 0) for r in repos) for s in SEVERITIES + ("info",)}


def _repo_result(c: projects.Repo, rf: inventory.RepoFacts, idx: inventory.Index, tops: set, mod_evidence: dict,
                 facts: dict, dangling: list, unregistered: list, covered: dict, layered: set,
                 missing: list, extra_dirs: set = frozenset(), ctx: dict | None = None) -> dict:
    t, name = rf.tree, c.name
    found: list[dict] = []
    # readme.exists, readme.sections
    readme = _readme(rf)
    text = t.text(readme) if readme else ""
    n = sum(1 for ln in (text or "").splitlines() if ln.strip())
    if n < README_LINES:
        found.append(finding(name, "readme.exists", "README.md",
                             f"README.md has {n} non-blank line(s) ({README_LINES} at least)" if readme
                             else "no README.md at the root", "write README.md: what it is, install, usage, tests"))
    has_code = bool(rf.units or rf.console)
    if readme and has_code:
        heads = _headings(text or "")
        for group, words in SECTIONS.items():
            if not any(re.search(rf"\b{w}", h) for h in heads for w in words):
                found.append(finding(name, "readme.sections", f"README.md#{group}",
                                     f"no heading for {group} ({', '.join(words)})", f"add a {group} section"))
    # doc.dead-ref
    top_dirs = {p.split("/")[0] for p in t.files if "/" in p} | set(extra_dirs)
    owners: dict[str, str] = {}   # top-level package -> the repo that holds it
    for other, f in facts.items():
        for d in list(f.modules) + list(f.packages):
            owners.setdefault(d.split(".")[0], other)
    own = {d.split(".")[0] for d in list(rf.modules) + list(rf.packages)}
    known = {x.lower() for x in facts} | {getattr(c, "folder", "").lower()}
    for d in rf.docs:
        seen = set()
        for line in (t.text(d) or "").splitlines():
            for mod in inventory.DASH_M.findall(line):
                if mod.split(".")[0] in tops and not idx.module_file(mod, main=True) and mod not in seen:
                    seen.add(mod)
                    what = "a package with no __main__.py" if mod in idx.packages else "no such module"
                    found.append(finding(name, "doc.dead-ref", f"{d}#-m {mod}", f"{d} runs -m {mod}: {what}",
                                         "fix or remove the reference"))
            ext = EXTERNAL.search(line)
            if ext and ext.group(1).lower().removesuffix(".git") not in known:
                continue   # a row about another project's repository: its paths are that repo's
            for m in DOC_PATH.finditer(line):
                ref, before = m.group(1), line[m.start() - 1] if m.start() else ""
                if ref in seen or ref.split("/")[0] not in top_dirs or (before and before in "<*{$"):
                    continue
                here = inventory._norm(f"{d.rsplit('/', 1)[0]}/{ref}") if "/" in d else ref
                if t.has(ref) or t.has(here) or any(o.tree.has(ref) for o in facts.values()):
                    continue
                seen.add(ref)
                segs = ref.split("/")
                pkg = segs[1] if segs[0] == "src" and len(segs) > 2 else segs[0]
                owner = owners.get(pkg, name) if pkg not in own else name
                if owner != name:
                    found.append(finding(name, "doc.dead-ref", f"{d}#{ref}", f"{d} names {ref}, a path of {owner}: "
                                         f"not there either (a stale cross-repo reference)",
                                         "fix or remove the reference", sev="P2"))
                else:
                    found.append(finding(name, "doc.dead-ref", f"{d}#{ref}", f"{d} names {ref}: no such file",
                                         "fix or remove the reference"))
    found += dangling
    # test.module, test.script
    ev = rf.evidence
    tdir = _test_dir(rf)
    shims: dict[str, list] = {}
    for u in rf.units:
        if u.kind == "module":
            via, tests = mod_evidence[(name, u.path)]
            s = inventory.stem(u)
            if not via:
                found.append(finding(name, "test.module", u.path, f"no test_{s}.py or test_*_{s}.py, no test imports "
                                     f"{u.name}", f"add {tdir}/test_{s}.py", u))
            elif via == "indirect (unnamed)":
                found.append(finding(name, "test.module", u.path, f"no direct test: only reached through what "
                                     f"{', '.join(tests[:2])} import", f"add {tdir}/test_{s}.py", u, via, "P2"))
            elif via != "name":
                found.append(finding(name, "test.module", u.path, f"tested by {', '.join(tests[:3])}", "", u, via,
                                     "info"))
        elif u.kind == "script":
            via, tests = inventory.script_evidence(u, ev)
            shim = inventory.shim_target(u, rf, idx)
            if shim and shim[0] == name:
                shims.setdefault(shim[1], []).append(u.path)
            if not via and shim and mod_evidence.get(shim, ("", []))[0] not in ("", "indirect (unnamed)"):
                via, tests = f"shim of {idx.dotted_of.get(shim, shim[1])}", mod_evidence[shim][1]
            s = u.name.rsplit(".", 1)[0]
            if not via:
                pester = f" or {s}.Tests.ps1 (Pester)" if u.name.endswith((".ps1", ".psm1")) else ""
                why = f"no test runs {u.name} (named in {', '.join(tests[:2])}, never run)" if tests \
                    else f"no test names {u.name}"
                found.append(finding(name, "test.script", u.path, why,
                                     f"add {tdir}/test_{s.replace('-', '_')}.py{pester} that runs it", u))
            elif via != "name":
                found.append(finding(name, "test.script", u.path, f"tested by {', '.join(tests[:3])}", "", u, via,
                                     "info"))
    # cmd.documented
    docs = _docs_index(rf)
    for u in rf.units:
        if u.kind == "command" and not _documented(u, rf, docs, shims):
            found.append(finding(name, "cmd.documented", u.name, f"no doc of the docs set names {u.name}",
                                 f"document {u.name} in README.md or docs/ (what it does, its options)", u))
    # cmd.registry
    found += registry_findings(name, rf)
    # coderef.module
    modules = [u for u in rf.units if u.kind == "module"]
    if name in layered:
        token = getattr(c, "folder", "") or name   # a project's code-check finds the repo folder by its exact case
        for u in modules:
            if u.path not in covered.get(name, set()):
                found.append(finding(name, "coderef.module", u.path, "no CodeRef names this module",
                                     f"add code:{token}:{u.path[4:] if u.path.startswith('src/') else u.path} to a "
                                     "code store (implemented_by from its node)", u))
    # not measured
    applies = {"every": True, "code": has_code, "python": bool(modules), "commands": any(
        u.kind == "command" for u in rf.units), "ts": c.lang == "ts", "no-code-layer": bool(modules)
        and name not in layered}
    pending = []
    for k, v in PENDING.items():
        if not applies[v.applies]:
            continue
        got = v.owner if v.run is None or ctx is None else v.run(ctx)
        if isinstance(got, str):
            pending.append({"check": k, "owner": got})
        else:
            found += got
    if rf.layout.roots is None:
        pending.insert(0, {"check": "test.module", "owner": rf.layout.why})
    if unregistered:
        pending.append({"check": "coderef.dangling", "owner": f"CodeRefs of unregistered repos: "
                                                              f"{', '.join(unregistered)}"})
    found.sort(key=lambda f: (f["severity"] if f["severity"] != "info" else "P9", f["check"], f["unit"]))
    counts = {s: sum(1 for f in found if f["severity"] == s) for s in SEVERITIES + ("info",)}
    classes = {k: sum(1 for u in rf.units if u.cls == k) for k in ("entry", "prod", "other")}
    cov = (ctx or {}).get("cache", {}).get("feature.coverage")   # feature.coverage's section (feature_cover)
    return {"name": name, "path": str(c.path), "production": c.production or c.entry is not None,
            "commit": t.label, "date": t.date, "counts": counts, "classes": classes,
            "no_entry": rf.no_entry, "missing_entries": missing, "findings": found,
            "not_measured": pending, "waived": [{"unit": u, "reason": r} for u, r in rf.waived],
            "exempt": rf.exempt, **({"feature_coverage": cov} if cov else {})}


def _parallel(fn, items: list) -> list:
    """``fn`` over ``items`` in threads (git calls dominate: each costs a process start)."""
    if len(items) < 2:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        return list(pool.map(fn, items))


def trees_now(cfgs: list[projects.Repo]) -> tuple[dict[str, inventory.Tree], dict[str, str], dict[str, str]]:
    """(trees, the ref each was read at, why a repo was not audited)."""
    errors = {c.name: f"{c.path} not found" for c in cfgs if not c.path.is_dir()}
    live = [c for c in cfgs if c.name not in errors]

    def read(c: projects.Repo):
        ref, branch = inventory.reading_ref(c.path)
        return ref, inventory.git_tree(c.path, ref, branch)

    got = dict(zip([c.name for c in live], _parallel(read, live)))
    return {k: v[1] for k, v in got.items()}, {k: v[0] for k, v in got.items()}, errors


# --- the trend ---

def week_ends(n: int, today: date) -> list[tuple[str, str]]:
    """The last ``n`` completed ISO weeks: (YYYY-Www, the Monday after it, 00:00 UTC)."""
    monday = today - timedelta(days=today.weekday())
    out = []
    for k in range(n, 0, -1):
        end = monday - timedelta(weeks=k - 1)
        y, w, _ = (end - timedelta(days=7)).isocalendar()
        out.append((f"{y}-W{w:02d}", f"{end.isoformat()}T00:00:00Z"))
    return out


def falling(debts: list[int]) -> int:
    """Week-on-week falls in a row ending at the last week: strictly lower, or zero; a flat week breaks it."""
    k = 0
    for i in range(len(debts) - 1, 0, -1):
        if debts[i] < debts[i - 1] or debts[i] == 0:
            k += 1
        else:
            break
    return k


def trend(p: projects.Project, cfgs: list[projects.Repo], refs: dict[str, str], n: int, today: date,
          only: set[str] | None = None, layered: set[str] | None = None, linked: dict | None = None,
          featured: bool | None = None, coverage: dict | None = None) -> dict:
    """Each of the last ``n`` completed weeks re-measured at its end commit with today's rules and registry (and
    today's code layers, ``layered``, the stores that take today's Doc and Test links, ``linked``, and today's
    Feature type, ``featured``, and today's coverage summaries, ``coverage``); a repo with no commit at some week end leaves the whole window (like-for-like)."""
    weeks = week_ends(n, today)
    live = [c for c in cfgs if c.name in refs]
    commits = dict(zip([c.name for c in live], _parallel(
        lambda c: inventory.week_commits(c.path, refs[c.name], [end for _, end in weeks]), live)))
    scope = [c for c in cfgs if c.name in commits and all(commits[c.name])]
    out = []
    for i, (label, end) in enumerate(weeks if scope else []):
        trees = dict(zip([c.name for c in scope], _parallel(
            lambda c, i=i: inventory.git_tree(c.path, commits[c.name][i]), scope)))
        res = measure(p, scope, trees, only, layered, linked=linked, featured=featured, coverage=coverage)
        out.append({"week": label, "end": end[:10], "debt": {s: res["counts"][s] for s in SEVERITIES}})
    return {"weeks": out, "repos": [c.name for c in scope],
            "left": sorted(c.name for c in cfgs if c not in scope)}


def _total(w: dict) -> int:
    return sum(w["debt"][s] for s in SEVERITIES)


def merge_trends(trends: dict[str, dict]) -> dict:
    """Projects' trends summed week by week, with each project's debt."""
    trends = {k: t for k, t in trends.items() if t["weeks"]}   # a project with no repo over the window: out
    first = next(iter(trends.values()), {"weeks": []})
    weeks = []
    for i, w in enumerate(first["weeks"]):
        debt = {s: sum(t["weeks"][i]["debt"][s] for t in trends.values()) for s in SEVERITIES}
        weeks.append({"week": w["week"], "end": w["end"], "debt": debt,
                      "by_project": {name: _total(t["weeks"][i]) for name, t in trends.items()}})
    return {"weeks": weeks, "falling": falling([_total(w) for w in weeks]), "projects": sorted(trends)}


def trend_line(t: dict) -> str:
    if not t["weeks"]:
        return "trend: not measured (no repo has a commit at the end of every week of the window)"
    parts = []
    for i, w in enumerate(t["weeks"]):
        if i:
            prev, cur = _total(t["weeks"][i - 1]), _total(w)
            parts.append(">" if cur < prev else "=" if cur == prev else "<")
        parts.append(f"W{w['week'][-2:]} {_total(w)}")
    k = falling([_total(w) for w in t["weeks"]])
    return f"trend (like-for-like debt): {' '.join(parts)}  falling {min(k, STREAK)} of {STREAK}"


def milestone(projs: list[dict], tr: dict | None) -> dict:
    """ms-brain-conformance is met when every registered repo was audited, P0 = P1 = 0, no pending check that would
    carry P0 or P1 remains and the last four completed weeks all fell. Never set here: the evidence is printed."""
    p0 = sum(p["counts"]["P0"] for p in projs)
    p1 = sum(p["counts"]["P1"] for p in projs)
    lost = [r["name"] for p in projs for r in p["repos"] if r.get("error")]
    lost += [f"{r['name']} ({x['owner']})" for p in projs for r in p["repos"] for x in r.get("not_measured", [])
             if x["check"] == "test.module"]   # its modules could not be read (a layout error, Python < 3.11)
    pend = sorted({k for k, v in PENDING.items() if v.blocks and v.run is None}
                  | {x["check"] for p in projs for r in p["repos"] for x in r.get("not_measured", [])
                     if x["check"] in PENDING and PENDING[x["check"]].blocks})   # a generator's check not run there
    k = tr["falling"] if tr and tr["weeks"] else None
    reasons = ([f"not audited: {', '.join(lost)}"] if lost else []) + [f"P0 {p0}, P1 {p1}"]
    reasons += [f"{len(pend)} P0/P1 checks not measured"] if pend else []
    reasons += [f"falling {min(k, STREAK)} of {STREAK}" if k is not None else "trend not measured (--trend)"]
    met = not lost and p0 == p1 == 0 and not pend and k is not None and k >= STREAK
    return {"id": MILESTONE, "met": met, "reasons": reasons, "pending": pend}


# --- output ---

def _line(f: dict) -> str:
    cls = f["class"] + (f" ({f['chain']})" if f["chain"] else "") if f["class"] else ""
    return (f"  {f['severity']} {f['check']:<16} {f['unit']}" + (f"  {cls}" if cls else "") + f": {f['why']}"
            + (f" -> {f['fix']}" if f["fix"] else "") + (f" [{f['via']}]" if f["via"] else ""))


def _not_measured(r: dict) -> str:
    by: dict[str, list] = {}
    for x in r["not_measured"]:
        by.setdefault(x["owner"], []).append(x["check"])
    return "  not measured: " + "; ".join(f"{', '.join(v)} ({k})" for k, v in by.items())


def render_text(data: dict, verbose: bool = False) -> list[str]:
    out = []
    for p in data["projects"]:
        out.append(f"== {p['name']}: {p['root']}  (rules {data['ruleset']})")
        for r in p["repos"]:
            if r.get("error"):
                out.append(f"{r['name']:<17} not audited: {r['error']}")
                continue
            c = r["counts"]
            role = "production" if r["production"] else "other"
            out.append(f"{r['name']:<17} {r['commit']} {r['date']}  {role}  P0 {c['P0']}  P1 {c['P1']}  "
                       f"P2 {c['P2']}  info {c['info']}  waived {len(r['waived'])}")
            if r["missing_entries"]:
                out.append(f"  warning: entry not found: {', '.join(r['missing_entries'])}")
            if r["no_entry"]:
                out.append("  no entry declared: every unit of this production repo counts as production")
            p2: dict[str, list] = {}
            for f in r["findings"]:
                if f["severity"] in ("P0", "P1") or verbose:
                    out.append(_line(f))
                elif f["severity"] == "P2":
                    p2.setdefault(f["check"], []).append(f["unit"])
            for check, units in p2.items():
                more = f", e.g. {', '.join(units[:3])}" + (" (-v: all)" if len(units) > 3 else "")
                out.append(f"  P2 {check:<16} {len(units)} unit(s){more}")
            if r.get("feature_coverage"):
                out.append(feature_coverage.text_line(r["feature_coverage"]))
            if r["not_measured"]:
                out.append(_not_measured(r))
        c = p["counts"]
        out.append(f"{p['name']}: P0 {c['P0']}  P1 {c['P1']}  P2 {c['P2']} in "
                   f"{sum(1 for r in p['repos'] if not r.get('error'))} repo(s)"
                   + (f" (calibrated {CALIBRATED.split(' ', 1)[0]})" if CALIBRATED
                      else " (uncalibrated: wi-brain-scout-rule measures each check's error rate)"))
        if p.get("trend"):
            out.append(trend_line(p["trend"]) + (f" (left out: {', '.join(p['trend']['left'])})"
                                                 if p["trend"]["left"] else ""))
    if data.get("milestone"):
        m = data["milestone"]
        out.append(f"{m['id']}: {'met' if m['met'] else 'not met'} ({'; '.join(m['reasons'])})")
        if m["met"]:
            out.append(f'evidence: brain item set {m["id"]} status=reached reached="{date.today()} brain audit --all '
                       f'--trend: P0 0, P1 0, every check measured, falling {STREAK} weeks"')
    return out


def _public(p: dict) -> dict:
    return {k: v for k, v in p.items() if k not in ("facts", "cfgs", "project", "mod_evidence", "layered",
                                                    "linked", "featured", "coverage")}


def render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)


def _cell(f: dict) -> str:
    cls = f" ({f['class']}{', ' + f['chain'] if f['chain'] else ''})" if f["class"] else ""
    return f"`{f['unit']}`{cls}: {f['why']}" + (f" → {f['fix']}" if f["fix"] else "")


def render_view(p: dict) -> str:
    """notes/audit.md: no run date, so it changes only when the code, the graph, the rules or the weeks do."""
    out = [f"# Conformance audit — {p['name']}", "",
           "GENERATED by `brain audit --write`. Do not edit: fix the code, docs, tests or graph, then rerun it "
           "from a worktree.", f"Ruleset {RULESET}; each repo is read at the commit shown (committed state). Checks, "
           "severities and classes: README.md, section Audit.", "",
           f"Calibrated {CALIBRATED}." if CALIBRATED else "Uncalibrated: the counts are measured, but each check's "
           "error rate is not yet (wi-brain-scout-rule measures it before R8); read a finding before acting on it.",
           "",
           "| Repo | Commit | Role | P0 | P1 | P2 | info | waived | exempt | not measured |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in p["repos"]:
        if r.get("error"):
            out.append(f"| {r['name']} | not audited: {r['error']} |  |  |  |  |  |  |  |  |")
            continue
        c = r["counts"]
        out.append(f"| [{r['name']}](#{r['name']}) | {r['commit']} ({r['date']}) | "
                   f"{'production' if r['production'] else 'other'} | {c['P0']} | {c['P1']} | {c['P2']} | "
                   f"{c['info']} | {len(r['waived'])} | {len(r['exempt'])} | {len(r['not_measured'])} |")
    c = p["counts"]
    out += ["", f"**{p['name']}: P0 {c['P0']}, P1 {c['P1']}, P2 {c['P2']}.**", ""]
    if p.get("trend"):
        out += ["## Trend", "", trend_line(p["trend"]).replace("trend (like-for-like debt): ", "Like-for-like debt "
                "(P0 + P1 + P2) at the end of each completed ISO week, today's rules: "), ""]
    first = [(r["name"], f) for r in p["repos"] for f in r.get("findings", []) if f["severity"] == "P0"]
    for cls in ("entry", "prod"):
        first += [(r["name"], f) for r in p["repos"] for f in r.get("findings", [])
                  if f["severity"] == "P1" and f["class"] == cls]
    out += ["## First batch", "", "Production first (Q16): every P0, then P1 on entry units, then P1 on production "
            "units.", ""]
    out += [f"- {f['severity']} {name} {f['check']} {_cell(f)}" for name, f in first] or ["Nothing."]
    for r in p["repos"]:
        if r.get("error"):
            continue
        out += ["", f"## {r['name']}", ""]
        by: dict[tuple, list] = {}
        for f in r["findings"]:
            if f["severity"] != "info":
                by.setdefault((f["severity"], f["check"]), []).append(f)
        for (sev, check), fs in by.items():
            out += [f"### {sev} {check} ({len(fs)})", "", f"_{CHECKS[check].what}._", ""]                 + [f"- {_cell(f)}" for f in fs] + [""]
        if not by:
            out += ["No measured debt.", ""]
        if r.get("feature_coverage"):
            out += feature_coverage.view_lines(r["feature_coverage"])
        if r["waived"]:
            out += ["Waived: " + "; ".join(f"`{w['unit']}` ({w['reason']})" for w in r["waived"]), ""]
        if r["exempt"]:
            out += ["Exempt (trivial modules): " + ", ".join(f"`{e}`" for e in r["exempt"]), ""]
        if r["not_measured"]:
            out += [_not_measured(r).strip().replace("not measured:", "Not measured:"), ""]
    return "\n".join(out).rstrip() + "\n"


def write_view(root: Path, text: str) -> tuple[Path, bool]:
    f = root / VIEW
    if f.is_file() and f.read_text(encoding="utf-8") == text:
        return f, False
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8", newline="\n")
    return f, True


# --- backlog sync ---

def item_id(c: projects.Repo) -> str:
    return c.item or f"wi-debt-{c.name}"


def sync_items(p: projects.Project, cfgs: list[projects.Repo], result: dict, store: Path, out=None) -> int:
    """One item per repo with measured debt: created with its priority proposed; afterwards a missing audit_repo or
    report is filled in and priority_proposed changes when the measure moves; a validated priority is never touched.
    Never closed, reopened or linked."""
    out = out or sys.stdout
    if "WorkItem" not in (graph.load_schema(store).get("node_types") or []):
        print(f"warning: {store} has no WorkItem type: the audit stays report-only for {p.name}", file=out)
        return 0
    spec = (p.audit or {}).get("spec", "")
    by = {c.name: c for c in cfgs}
    for r in result["repos"]:
        if r.get("error"):
            continue
        c, counts = by[r["name"]], r["counts"]
        nid = item_id(c)
        debt = counts["P0"] + counts["P1"] + counts["P2"]
        want = "P1" if counts["P0"] or counts["P1"] else "P2"
        index = graph.node_index(store)
        node = index[nid][1] if nid in index else None
        if node is None:
            if not debt:
                continue
            props = {"priority_proposed": want, "theme": "3.18", "audit_repo": c.name,
                     "report": f"{VIEW}#{c.name}"}
            graph.add_item(store, nid, f"{c.name} up to the standard (brain audit debt): by batches, production "
                           "first", props=props, spec=spec if spec in index else "")
            print(f"item: {nid} added (priority_proposed {want}); proposal, never automatic: link it to a "
                  f"milestone and to what depends on it (brain item link {nid} part_of <milestone>)", file=out)
            continue
        props = node.get("props") or {}
        if node.get("status") in ("done", "dropped"):
            if debt:
                print(f"warning: {nid} is {node['status']} and {c.name} has debt again (P0 {counts['P0']}, P1 "
                      f"{counts['P1']}, P2 {counts['P2']}): reopen it or add an item (not automatic)", file=out)
            continue
        if not debt:
            print(f"{nid}: no debt left in {c.name}: close it (close-item)", file=out)
            continue
        sets = [f"{k}={v}" for k, v in (("audit_repo", c.name), ("report", f"{VIEW}#{c.name}"))
                if k not in props]
        if props.get("priority_proposed") != want:
            sets.append(f"priority_proposed={want}")
        if sets:
            graph.set_item(store, nid, sets)
            print(f"item: {nid} set {', '.join(sets)}", file=out)
        if props.get("priority") and props["priority"] != want:
            print(f"note: {nid} has the validated priority {props['priority']}; the measure suggests {want} "
                  f"(left to {config.owner_of()})", file=out)
    return 0


# --- the command ---

def _registered(root: Path | None) -> dict[str, projects.Project]:
    reg = projects.load(root)
    if not reg:
        raise AuditError(f"the project registry is needed ({projects.REGISTRY}; $BRAIN_PROJECTS or "
                         "$CLAUDE_BRAIN_DIR)")
    return reg


def _not_registered(name: str, root: Path | None, reg) -> str:
    """Why --project ``name`` is not one to audit: what --project says (read only, a mount, not loaded), else
    unknown."""
    return projects.unloaded(name, root) or f"unknown project {name!r} (known: {', '.join(reg)})"


def scope(args, root: Path | None) -> list[projects.Project]:
    """--all: every registered project; --project; else the project whose root (or one of whose repos) is the main
    checkout of --root or the current folder; else the project of the nearest graph store."""
    if args.all:
        if args.project:
            raise AuditError("--project or --all, not both")
        return list(_registered(root).values())
    if args.project:
        reg = _registered(root)
        if args.project not in reg:
            raise AuditError(_not_registered(args.project, root, reg))
        return [projects.get(args.project, root)]
    here = root or Path.cwd()
    main = paths.main_checkout(here)
    reg = projects.load(root)
    if main:
        for p in reg.values():
            if p.root.resolve() == main.resolve():
                return [projects.get(p.name, root) if root else p]
        if root is None:
            for p in reg.values():
                if any(r.path.resolve() == main.resolve() for r in projects.repos_of(p)):
                    return [p]
    return [projects.for_root(root or paths.find_root())]


def run(args, root: Path | None, today: date | None = None) -> dict:
    """The data of a full run: {audit, ruleset, projects: [...], trend, milestone}."""
    today = today or date.today()
    projs = scope(args, root)
    if (args.write or args.items) and (len(projs) > 1 or args.all):
        raise SystemExit("brain: --write and --items take one project (not --all)")
    if args.write and args.repo:
        raise SystemExit("brain: --write writes the whole project's view (not --repo)")
    if args.write and projs and projs[0].shares_root_with:
        owner = projs[0].shares_root_with
        raise SystemExit(f"brain: {projs[0].name} shares its root with {owner}: {VIEW} is {owner}'s (brain --project "
                         f"{owner} audit --write)")
    data = {"audit": 1, "ruleset": RULESET, "projects": []}
    trends = {}
    n = args.trend if args.trend else (5 if args.write else 0)
    if args.repo:
        names = {c.name for p in projs for c in projects.repos_of(p)}
        unknown = sorted(set(args.repo) - names)
        if unknown:
            raise AuditError(f"unknown repo(s) {', '.join(unknown)} (repos: {', '.join(sorted(names))})")
    for p in projs:
        cfgs = projects.repos_of(p)
        only = None
        if args.repo:   # every repo is still read: the closure and cross-repo references span them all
            only = set(args.repo)
            if not only & {c.name for c in cfgs}:
                continue
        trees, refs, errors = trees_now(cfgs)
        res = measure(p, cfgs, trees, only)
        res["repos"] += [{"name": k, "path": str(next(c.path for c in cfgs if c.name == k)), "error": v}
                         for k, v in errors.items() if only is None or k in only]
        res["cfgs"], res["project"] = cfgs, p
        if n:
            res["trend"] = trend(p, cfgs, refs, n, today, only, res["layered"], res["linked"], res["featured"],
                                 res["coverage"])
            res["trend"]["falling"] = falling([_total(w) for w in res["trend"]["weeks"]])
            trends[p.name] = res["trend"]
        data["projects"].append(res)
    if trends:
        data["trend"] = merge_trends(trends)
    if args.all:
        data["milestone"] = milestone(data["projects"], data.get("trend")) if not args.repo else             {"id": MILESTONE, "met": False, "reasons": ["not evaluated: --repo narrows the scope"], "pending": []}
    return data


def _worst(data: dict) -> int:
    sevs = [f["severity"] for p in data["projects"] for r in p["repos"] for f in r.get("findings", [])
            if f["severity"] in SEVERITIES]
    return min((SEVERITIES.index(s) for s in sevs), default=len(SEVERITIES))


def main(args, root: Path | None) -> int:
    try:
        if args.diff is not None:
            from . import scout
            return scout.main(args, root)
        data = run(args, root)
        projs = data["projects"]
        if args.write or args.items:
            p = projs[0]
            proj = p["project"]
            from .commands._common import _on_main
            branch = _on_main(proj.root)
            if branch:
                raise SystemExit(f"brain: {proj.root} is a main checkout on {branch}: write from a worktree "
                                 f"(brain --project {proj.name} --root <worktree> audit --write)")
            if args.write:
                f, changed = write_view(proj.root, render_view(_public(p)))
                print(f"view: {f.relative_to(proj.root).as_posix()} {'written' if changed else 'unchanged'}")
            if args.items:
                store = proj.stores[0] if proj.stores else proj.root / "notes" / "graph"
                try:
                    sync_items(proj, p["cfgs"], p, store)
                except graph.GraphError as exc:
                    print(f"brain: {exc}", file=sys.stderr)
                    return 1
        public = {**data, "projects": [_public(p) for p in projs]}
        if args.json:
            print(render_json(public))
        else:
            print("\n".join(render_text(public, args.verbose)))
        if args.fail_on and _worst(data) <= SEVERITIES.index(args.fail_on):
            return 1
        return 0
    except (AuditError, projects.RepoError) as exc:
        print(f"brain audit: {exc}", file=sys.stderr)
        return 2
