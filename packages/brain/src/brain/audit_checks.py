"""brain audit's checks (brain.audit): the catalogue CHECKS and its ruleset, the checks a generator measures (PENDING,
each with its ``run``), a finding and its severity. A change of check or severity needs an ADR and a ruleset bump."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import feature_coverage, features, graph, inventory, langs, links, projects, readme, standards
from .mergedriver import HEAD_LINES

RULESET = 13   # 2: doc.links and test.links measured (wi-brain-doc-test-links); 3: features.md and feature.links
#               (wi-brain-feature-matrix); 4: test.coverage measured (wi-brain-test-coverage) and feature.tests
#               (wi-brain-test-links-auto); 5: cmd.registry (wi-brain-cli-registry); 6: feature.coverage, info in
#               the full audit, NEW in the scout for an added command or module (wi-brain-audit-feature-coverage); 7: the scout's norm lints
#               (brain.norms: norm.timeout, norm.encoding, norm.naive-time, norm.secret-argv), info on what a change
#               adds, NEW under config.json audit.norm_lints_strict, DEFER for a touched file's old ones
#               (wi-brain-norm-lints); 8: lang.report, a repo's own tools' reports read where it declares
#               repos[].tools (wi-brain-lang-adapters); 9: doc.links and doc.dead-ref skip the technical
#               reference's generated pages (wi-brain-reference-scout); 10: standards.gap, an applicable standard
#               whose check covers neither a repo's language nor a tool it declares (wi-brain-standards-registry-
#               consumers), measured only for a project that declares standards:; 11: coderef.dangling for an
#               active CodeRef of a repo no project registers, P0 instead of not measured
#               (wi-brain-audit-unregistered-coderef)
#               12: doc.dead-ref for a doc line naming a prefix config.json moved: says moved
#               (wi-brain-moved-paths); 13: waive.stale, a repo's waive glob that matches no file of its tree
#               (wi-brain-engine-debt, batch 2)
# the scout's calibration (wi-brain-scout-rule, design section 8: fewer than 10 % wrong per check; the numbers are in
# the journal and on the item); a detection change that the numbers do not cover clears it until measured again
CALIBRATED = ("2026-11-02 (83 flagged units checked by hand over brain audit --all and --diff on 50 merges, 2 wrong; "
              "every check under 10 %)")
SEVERITIES = ("P0", "P1", "P2")
COVERAGE_FLOOR = 50.0   # a module the tests run less of (percent of its statements) is a test.coverage finding



@dataclass(frozen=True)
class Check:
    id: str
    severity: str     # P0, P2 or info; 'class': P1 on an entry or prod unit, P2 elsewhere
    scout: str        # in --diff: 'new+left', 'new' (added units only), 'new+defer' (NEW on an added unit, even an
    #                   info; DEFER on a touched one, LEFT under the owner's opt-in: brain.scout) or 'never'
    what: str


CHECKS = {c.id: c for c in (
    Check("readme.exists", "P0", "new+left", "a tracked root README.md with 10 non-blank lines or more"),
    Check("doc.dead-ref", "P0", "new+left", "a doc names a module (-m) or a repo file that does not exist (a "
          "page of the technical reference aside), or a prefix config.json's table of moves says moved"),
    Check("coderef.dangling", "P0", "new+left", "an active CodeRef points at a missing file or symbol, or at a repo "
          "no project of the registry registers"),
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
    # opt-in (wi-brain-lang-adapters): measured only for a repo that declares repos[].tools (brain.langs)
    Check("lang.report", "P2", "never", "a report a repo's own tool writes (repos[].tools) is missing or unreadable, "
          f"or says no test ran, failed tests, lint, type or format findings, or coverage under {COVERAGE_FLOOR:g} %"),
    # opt-in (wi-brain-standards-registry-consumers): measured only for a project that declares standards:
    Check("standards.gap", "P2", "never", "an applicable standard (projects.yaml standards:, brain.standards) whose "
          "check covers neither the repo's language nor an adapter slot its repos[].tools declares"),
    Check("doc.links", "P2", "new+left", "a doc no section of which documents a graph node, or a spec no Spec node "
          "anchors (a page of the technical reference aside)"),
    Check("test.links", "P2", "never", "a test module no graph node is tested_by (no Hook, and no node implemented_by "
          "a CodeRef, stands for its code)"),
    Check("test.coverage", "P2", "never", f"a Python module the tests run under {COVERAGE_FLOOR:g} % of, by the "
          "store's coverage summary (brain coverage)"),
    # projects.yaml's, not the repo's to fix: never in the scout of a change to the repo
    Check("waive.stale", "P2", "never", "a glob of the repo's waive: in projects.yaml that matches no file of its "
          "tree: it waives nothing, and would hide the next file that takes its name"),
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
    applies: str      # every, code, python, commands, ts, no-code-layer, tools (a repo that declares repos[].tools),
    #                   standards (a project that declares standards:)
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


# The technical reference's marker (brain.reference.MARKER, a test keeps them equal), at the start of a line of a
# page's first lines.
REFERENCE_PAGE = re.compile(r"(?m)^GENERATED by `brain reference`")


def generated_doc(tree: inventory.Tree, path: str) -> bool:
    """A page of the technical reference (``brain reference`` writes it: its marker opens a line of its first lines).
    Nothing in it is fixed by hand: a module page with no feature names no node, a quoted title may name another
    repo's path; its sources are the graph's, checked there. doc.links and doc.dead-ref skip it
    (wi-brain-reference-scout). A generated README is still checked: its text comes from the repo's readme.yaml."""
    return bool(REFERENCE_PAGE.search("\n".join((tree.text(path) or "").splitlines()[:HEAD_LINES])))


def doc_links(ctx: dict) -> list[dict] | str:
    """doc.links: a spec no Spec node anchors (its sections are part of nothing), a doc of the docs set none of
    whose sections documents a graph node (a generated doc aside: generated_doc)."""
    why = _no_store(ctx, "Doc")
    if why:
        return why
    lk, name, rel = _derived(ctx), ctx["rf"].name, ctx["store"][0]
    out = [finding(name, "doc.links", p, "no Spec node anchors this spec: its sections are part of nothing",
                   f"add a Spec node anchored at {p} to {rel}") for p, s in sorted(lk.specs.items()) if not s]
    for p, ids in sorted(lk.docs.items()):
        if p not in lk.specs and not set(ids) & lk.documented and not generated_doc(ctx["rf"].tree, p):
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


def _registries(t: inventory.Tree) -> list[str]:
    """The prefix of each package of the tree whose commands/ lists its own modules (a command registry)."""
    inits = [p for p in sorted(t.files) if p == "commands/__init__.py" or p.endswith("/commands/__init__.py")]
    return [p[:-len("commands/__init__.py")] for p in inits if inventory.facts(t, p).discovers]


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


NO_TOOLS = "no tools: declared (not opted in to the language adapters: brain.langs, wi-brain-lang-adapters)"


def _lang_finding(c: projects.Repo, r: langs.Result) -> dict | None:
    unit, tool = f"{r.slot}:{r.report}", f" ({r.tool})" if r.tool else ""
    if r.error:
        made = langs.how(c.lang, r.slot)
        return finding(c.name, "lang.report", unit, f"the {r.slot} report{tool} cannot be read: {r.error}",
                       "run the tool so it writes its report" + (f" (e.g. {made})" if made else "")
                       + ", or fix repos[].tools")
    if r.slot == "coverage":
        if r.percent is not None and r.percent < COVERAGE_FLOOR:
            return finding(c.name, "lang.report", unit, f"coverage{tool} {r.percent:g} % (under "
                           f"{COVERAGE_FLOOR:g} %)", "add tests for the least covered files")
        return None
    if r.count:
        what = f"{r.count} of {r.total} test(s) failed" if r.slot == "test" else f"{r.count} {r.slot} finding(s)"
        return finding(c.name, "lang.report", unit, f"{what}{tool}", f"fix them, then rerun the {r.slot} tool")
    return None


def lang_report(ctx: dict) -> list[dict] | str:
    """lang.report (brain.langs): what the reports a repo's own tools write say, read from its checkout (the engine
    runs no tool)."""
    c = ctx["cfg"]
    if not c.tools:
        return NO_TOOLS
    out = [_lang_finding(c, r) for r in langs.results(Path(c.path), c.tools)]
    return [f for f in out if f]


def standards_gap(ctx: dict) -> list[dict] | str:
    """standards.gap (brain.standards): the project's applicable standards whose check covers neither this repo's
    language nor a slot of its own tools (the same gaps as brain standards check, one finding per row)."""
    c = ctx["cfg"]
    try:
        chosen = standards.chosen_for(ctx.get("project"))
    except standards.StandardsError as exc:
        return f"its standards cannot be measured: {exc}"
    if not chosen:
        return ("no applicable standard (projects.yaml standards:, or its catalogs cannot be read: brain standards "
                "check)")
    return [finding(c.name, "standards.gap", gap.split(":", 1)[0], gap,
                    "declare the repo's own tool for the row's adapter slot (projects.yaml repos[].tools, "
                    "brain.langs), or waive the row with its reason (standards.exclude)")
            for gap in standards.gaps(chosen, {c.name: c.lang}, {c.name: set(c.tools)})]


PENDING = {
    "readme.yaml": Pending("wi-brain-readme-sync", True, "every", readme_yaml),
    "lang.report": Pending("wi-brain-lang-adapters", False, "tools", lang_report),
    "standards.gap": Pending("wi-brain-standards-registry-consumers", False, "standards", standards_gap),
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
