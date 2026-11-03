"""Docs, tests and CI in the graph (spec 2026-10-30 section 3.7, wi-brain-doc-test-links): Doc, Test and Workflow
nodes and their documented_in, tested_by, runs and part_of edges, derived from a repo's tree at zero token (paths, a
static pytest collection, workflow files and brain audit's test evidence; a repo's code is never imported or run).
``brain sync`` writes them into ``nodes/_generated_links.yaml`` and ``edges/_generated_links.yaml`` of a store whose
schema has the types, ``brain check`` warns when those files are stale, and ``brain audit`` measures its doc.links and
test.links checks from the same derivation.

Nodes:
- Doc: a section of a doc of the docs set (inventory.is_doc: READMEs, docs/** but specs and plans, runbooks), cut at
  its level-1 and level-2 headings, or of a spec (docs/specs/**.md), cut down to level 3; a doc with no heading is one
  node. Id ``doc:<repo>:<path>::<key>`` (a numbered heading's number, else its words in ASCII, 40 characters at
  most), anchor ``<path>#<GitHub slug>`` (``#user-content-<slug>`` for a slug that starts with a date);
  props.paths: the repo files the section names. A spec section is part_of the Spec node anchored at its file.
- Test: a test module (inventory.is_test), its cases from a static collection (pytest: the test* functions and the
  test* methods of Test* classes, by AST, parametrize not expanded; Pester: It blocks; JS: it and test calls), part_of
  the folder that holds it, itself a Test node (part_of its nearest parent folder node). props.covers: the repo's
  modules and scripts whose brain audit evidence names it ('indirect (unnamed)' left out).
- Workflow: a job of .github/workflows/*.yml|yaml; it runs the Test modules and folders its pytest (python -m pytest,
  uv or poetry run pytest) and Invoke-Pester steps name, or with no path pytest's testpaths, else every top test
  folder (Pester: every Pester test).

Edges from the store's other nodes (never from a Doc, Test or Workflow, nor from a CodeRef: research_graph refuses
any edge from a CodeRef, so the code of a CodeRef counts for the nodes implemented_by it, a Feature or an item):
- documented_in: to each Doc section that names the node's id, or the code it stands for: a Hook's scripts (the
  hooks.json commands of its event whose file name its title names, or whose stem is a part of its id), a Skill's
  SKILL.md or folder, a Plugin's folder or plugin.json, the files of the CodeRefs it is implemented_by (a folder
  from the repo's root or from the doc's own folder); every section of a doc inside a Plugin's or a Skill's folder
  documents it; never from a Spec to its own sections.
- tested_by: from a node with code (a Hook's scripts, the files of its CodeRefs) to each Test module that covers that
  code, with brain audit's evidence (so a hook's .sh that no test runs has none, as test.script says), and to each
  Python test that imports the module itself (``import``, ``from ... import``, ``-m``: the test's own statements, not
  their closure; wi-brain-test-links-auto). A CodeRef of a symbol (``path::name``) keeps, of its file's tests, those
  that name it (the symbol as a word, or each of its words, a cmd_ prefix left out: main(["record", "ddr"]) for
  cmd_record_ddr); when the store keeps a coverage summary of the repo (``coverage/<repo>.json``, brain coverage,
  brain.testcov), those its test contexts saw run the symbol, and those that name it outright. A whole file keeps
  every test of its file: a test that runs it only through another module (audit runs inventory) is not its test.

The project's other repos: a store's CodeRefs may name another registered repo of its project (code:<repo>:...), an
engine whose code the store describes, say. ``brain sync`` also derives that repo's Doc, Test and Workflow nodes,
from its committed state (the commit brain audit reads), into the same generated files; there a node stands for the
files of its CodeRefs of that repo and for a Hook's scripts found by their hooks/<name> (the store's repo renders them
from that repo); a Skill, a Plugin and the Spec anchors are the store's repo's alone. A Doc, Test or Workflow node of
that repo carries ``repo: <name>``: its anchor is a path of that repo, and brain check gives research_graph check
that repo's checkout (``--repo-path``, :func:`anchor_roots`), found as brain audit finds it (from the project's root,
else from its main checkout when the root is a worktree). A repo whose checkout is not on the machine is left out
(brain sync says so; brain check then warns that the files are stale). brain audit measures doc.links and test.links
of such a repo from the same derivation against the store.
"""

from __future__ import annotations

import ast
import json
import posixpath
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import graph, inventory, testcov

GENERATED = "_generated_links.yaml"
TYPES = ("Doc", "Test", "Workflow")
SPECS = "docs/specs/"
WORKFLOWS = ".github/workflows/"
WEAK = ("", "indirect (unnamed)")   # module evidence that does not make a test cover the module
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
NUMBER = re.compile(r"(\d+(?:\.\d+)*)\.?(?=\s|$)")
DATED = re.compile(r"\d{4}-\d{2}-\d{2}")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
PATH_REF = re.compile(r"(?<![\w./\\-])((?:[\w.-]+/)*[\w.-]*[\w-]\.(?:py|ps1|psm1|psd1|sh|bat|cmd|md|ya?ml|json|toml))"
                      r"(?![\w-])")
TOKEN = re.compile(r"[\w.:/-]+")
PYTEST = re.compile(r"(?m)(?:^|[;&|(]|\brun\b|-m)[ \t]*(?:py\.test|pytest)(?![\w.-])([^\n;&|)]*)")
PESTER = re.compile(r"(?<![\w-])Invoke-Pester(?![\w-])([^\n;&|]*)", re.I)
PESTER_IT = re.compile(r"(?m)^\s*It\s+['\"]")
JS_CASE = re.compile(r"(?<![\w.])(?:it|test)\s*\(\s*['\"`]")
TESTPATHS = re.compile(r"(?m)^\s*testpaths\s*=\s*(.+)$")
HEAD = ("# GENERATED by `brain sync` (brain.links): Doc, Test and Workflow nodes from the docs, the tests and the "
        "workflow files.\n# Do not edit: change those files or the nodes they name, then run brain sync.\n")


# --- docs ---

@dataclass
class Section:
    path: str
    title: str
    slug: str     # GitHub's anchor ('' for a doc with no heading)
    key: str      # the last part of the node id ('' for a doc with no heading)
    text: str


def is_spec(path: str) -> bool:
    return path.startswith(SPECS) and path.endswith(".md") and not inventory.skipped(path)


def gh_slug(title: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped (letters of any script kept), spaces to -."""
    t = re.sub(r"<[^>]+>", "", LINK.sub(r"\1", title)).lower()
    return re.sub(r"[^\w\- ]", "", t).replace(" ", "-")


def anchor(path: str, sec: Section) -> str:
    """The node's anchor. research_graph checks a fragment that starts with a date against the file's '## <date>'
    headings (the ADR anchors), so such a slug takes GitHub's own id form, user-content-<slug>."""
    if not sec.slug:
        return f"{path}#top"
    return f"{path}#{'user-content-' if DATED.match(sec.slug) else ''}{sec.slug}"


def short_key(title: str) -> str:
    """A heading's number (3.7), else its words in ASCII joined by -, 40 characters at most."""
    m = NUMBER.match(title.strip())
    if m:
        return m.group(1)
    ascii_ = unicodedata.normalize("NFKD", LINK.sub(r"\1", title)).encode("ascii", "ignore").decode().lower()
    out = ""
    for w in re.findall(r"[a-z0-9]+", ascii_):
        if out and len(out) + 1 + len(w) > 40:
            break
        out = f"{out}-{w}" if out else w[:40]
    return out or "section"


def sections(path: str, text: str) -> list[Section]:
    """The sections of a doc: cut at its headings of level 1 and 2 (3 for a spec), outside code fences; what precedes
    the first heading belongs to the first section. GitHub's anchors count every heading for their -1, -2 suffixes."""
    depth = 3 if is_spec(path) else 2
    lines = text.splitlines()
    cut, slugs, keys, fence = [], {}, {}, False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        m = None if fence else HEADING.match(line)
        if not m:
            continue
        title = m.group(2).strip()
        slug = gh_slug(title)
        n = slugs.get(slug, 0)
        slugs[slug] = n + 1
        if len(m.group(1)) <= depth:
            key = short_key(title)
            k = keys.get(key, 0)
            keys[key] = k + 1
            cut.append((i, title, f"{slug}-{n}" if n else slug, f"{key}-{k + 1}" if k else key))
    if not cut:
        return [Section(path, path, "", "", text)]
    out = []
    for j, (i, title, slug, key) in enumerate(cut):
        end = cut[j + 1][0] if j + 1 < len(cut) else len(lines)
        out.append(Section(path, title, slug, key, "\n".join(lines[0 if j == 0 else i:end])))
    return out


def resolve(tree: inventory.Tree, token: str, doc: str = "") -> list[str]:
    """The repo files a path written in a doc stands for: itself, the file next to the doc, else the files whose path
    ends with it (three at most); a bare file name only when one file has it (never __init__.py or conftest.py)."""
    tok = token.replace("\\", "/")
    tok = tok[2:] if tok.startswith("./") else tok
    if tree.has(tok):
        return [tok]
    if "/" in doc:
        here = inventory._norm(f"{posixpath.dirname(doc)}/{tok}")
        if tree.has(here):
            return [here]
    base = tok.rsplit("/", 1)[-1]
    if "/" in tok:
        cands = [p for p in tree.by_base(base) if p.endswith("/" + tok)]
        return cands if len(cands) <= 3 else []
    if base.startswith("__") or base == "conftest.py":   # a kind of file in prose (an __init__.py), not one file
        return []
    cands = tree.by_base(base)
    return cands if len(cands) == 1 and cands[0].rsplit("/", 1)[-1] == base else []


def _tokens(text: str) -> set[str]:
    out = set()
    for t in TOKEN.findall(text):
        t = t.rstrip(".:/-")
        out.add(t)
        out.update(x.rstrip(".:-") for x in t.split("/"))
    return out


def _folder_named(folder: str, text: str) -> bool:
    return re.search(rf"(?<![\w./-]){re.escape(folder)}/?(?![\w./-])", text) is not None


# --- what a graph node stands for in the repo ---

@dataclass
class Code:
    files: set = field(default_factory=set)
    folders: set = field(default_factory=set)
    symbols: dict = field(default_factory=dict)   # a file only symbol CodeRefs name -> those symbols


def _anchor_file(node: dict) -> str:
    return str(node.get("anchor") or "").split("#", 1)[0]


def hook_scripts(tree: inventory.Tree, node: dict) -> set[str]:
    """A Hook node's scripts: the commands of the hooks.json event its anchor names (hooks.json#<event>) whose file
    name its title names or whose stem is a part of its id; the event's one script when none is named."""
    path, _, event = str(node.get("anchor") or "").partition("#")
    if not path.endswith("hooks.json") or not tree.has(path):
        return set()
    try:
        data = json.loads(tree.text(path) or "{}")
    except ValueError:
        return set()
    root = posixpath.dirname(posixpath.dirname(path))
    scripts = set()
    for ev, groups in ((data.get("hooks") or {}) if isinstance(data, dict) else {}).items():
        if ev.lower() != event.lower() or not isinstance(groups, list):
            continue
        for g in groups:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                for tok in inventory.FILE_REF.findall(str(h.get("command", "")) if isinstance(h, dict) else ""):
                    tok = tok.replace("\\", "/")
                    full = f"{root}/{tok}" if root else tok
                    scripts.update([full] if tree.has(full) else resolve(tree, tok))
    title, nid = str(node.get("title", "")), f"-{node.get('id', '')}-"
    named = {s for s in scripts if re.search(rf"(?<![\w.-]){re.escape(s.rsplit('/', 1)[-1])}(?![\w-])", title)
             or f"-{s.rsplit('/', 1)[-1].rsplit('.', 1)[0]}-" in nid}
    return named or (scripts if len(scripts) == 1 else set())


def code_ref_target(tree: inventory.Tree, repo: str, cid: str) -> tuple[str, str]:
    """(file, symbol) of a CodeRef of this repo (src/<path>, else <path>; symbol '' for a whole file), ('', '') for
    another repo's or a malformed id."""
    try:
        r, path, sym = inventory.parse_code_ref(cid)
    except ValueError:
        return "", ""
    if r.lower() != repo.lower():
        return "", ""
    return (f"src/{path}" if tree.has(f"src/{path}") else path), sym


def code_ref_file(tree: inventory.Tree, repo: str, cid: str) -> str:
    """The file of a CodeRef of this repo (src/<path>, else <path>), '' for another repo's or a malformed id."""
    return code_ref_target(tree, repo, cid)[0]


def refs_code(tree: inventory.Tree, repo: str, refs: set[str]) -> Code:
    """The files of a node's CodeRefs of this repo; ``symbols``: a file only symbol CodeRefs name -> those symbols."""
    out, whole = Code(), set()
    for f, sym in (code_ref_target(tree, repo, r) for r in refs):
        if not f:
            continue
        out.files.add(f)
        if sym:
            out.symbols.setdefault(f, set()).add(sym)
        else:
            whole.add(f)
    out.symbols = {f: s for f, s in out.symbols.items() if f not in whole}
    return out


def node_code(tree: inventory.Tree, repo: str, node: dict, refs: set[str] = frozenset(),
              home: inventory.Tree | None = None) -> Code:
    """What a node stands for in the repo: a Hook's scripts, a Skill's or a Plugin's files and folder, and the files of
    the CodeRefs it is implemented_by (``refs``). A CodeRef stands for nothing itself: research_graph refuses any edge
    from it, and any edge into it but implemented_by. ``home``: the tree of the repo that holds the store, when
    ``tree`` is another repo's; an anchor names a file of ``home``, so a Hook's scripts are found in ``tree`` by their
    hooks/<name> (the store's repo renders them from that repo's sources), and a Skill or a Plugin stands for nothing
    there."""
    t, af = node.get("type"), _anchor_file(node)
    out = refs_code(tree, repo, refs)
    if home is not None:
        if t == "Hook":
            out.files |= {f for s in hook_scripts(home, node) for f in resolve(tree, "hooks/" + s.rsplit("/", 1)[-1])}
        return out
    if t == "Hook":
        out.files |= hook_scripts(tree, node)
    elif t == "Skill" and af and tree.has(af):
        out.files.add(af)
        out.folders.add(posixpath.dirname(af))
    elif t == "Plugin" and af and tree.has(af):
        folder = posixpath.dirname(af)
        out.files.add(af)
        out.folders |= {posixpath.dirname(folder) if folder.endswith(".claude-plugin") else folder} - {""}
    return out


# --- tests ---

def cases(tree: inventory.Tree, path: str) -> tuple[str, int, str]:
    """(framework, cases, first docstring line) of a test module, read statically."""
    text = tree.text(path) or ""
    if path.endswith(".py"):
        mod = inventory._parse(tree.key(path) or f"{tree.repo}:{path}", text)
        if mod is None:
            return "pytest", 0, ""
        n = 0
        for s in mod.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name.startswith("test"):
                n += 1
            elif isinstance(s, ast.ClassDef) and s.name.startswith("Test") \
                    and not any(isinstance(b, ast.FunctionDef) and b.name == "__init__" for b in s.body):
                n += sum(1 for b in s.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and b.name.startswith("test"))
        return "pytest", n, (ast.get_docstring(mod) or "").strip().split("\n", 1)[0]
    if path.endswith(".ps1"):
        return ("pester" if path.endswith(".Tests.ps1") else "powershell"), len(PESTER_IT.findall(text)), ""
    if path.endswith(".sh"):
        return "shell", 0, ""
    return "js", len(JS_CASE.findall(text)), ""


def testpaths(tree: inventory.Tree) -> list[str]:
    """pytest's testpaths: [tool.pytest.ini_options] of pyproject.toml, else pytest.ini, setup.cfg or tox.ini."""
    if tree.has("pyproject.toml") and inventory.tomllib is not None:
        try:
            got = (((inventory.tomllib.loads(tree.text("pyproject.toml") or "").get("tool") or {}).get("pytest")
                    or {}).get("ini_options") or {}).get("testpaths")
        except inventory.tomllib.TOMLDecodeError:
            got = None
        if got:
            return [inventory._norm(x) for x in ([got] if isinstance(got, str) else got)]
    for f in ("pytest.ini", "setup.cfg", "tox.ini"):
        m = TESTPATHS.search(tree.text(f) or "") if tree.has(f) else None
        if m:
            return [inventory._norm(x) for x in m.group(1).split()]
    return []


RUN_M = re.compile(r"""(?:(?<![\w-])-m[ \t]+|["']-m["'][ \t]*,[ \t]*["']|run_module\([ \t]*["'])"""
                   r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")


def _module(dotted: str, idx: inventory.Index) -> str:
    """The longest prefix of a dotted name that is a module of the index ('' when none)."""
    parts = dotted.split(".")
    return next((".".join(parts[:k]) for k in range(len(parts), 0, -1) if ".".join(parts[:k]) in idx.modules), "")


def imports_of(rf: inventory.RepoFacts, idx: inventory.Index | None) -> dict[str, set]:
    """Module path -> the Python tests that import it (their own import statements, fixtures left out: ``import
    p.m``, ``from p import m``, ``from p.m import x``) or run it (``-m p.m``, ``"-m", "p.m"``, ``run_module("p.m")``);
    not their closure, and not a dotted name a string or a comment holds."""
    out: dict[str, set] = {}
    if rf.evidence is None or idx is None:
        return out
    for t, (imps, _, _) in rf.evidence.per_test.items():
        mods = set()
        for mod, names in imps:
            explicit = [f"{mod}.{n}" for n in names if f"{mod}.{n}" in idx.modules]
            mods.update(explicit or [_module(mod, idx)])
        mods.update(_module(m, idx) for m in RUN_M.findall(inventory.without_fixtures(rf.tree.text(t) or "")))
        for d in mods - {""}:
            repo, path = idx.modules[d]
            if repo == rf.name:
                out.setdefault(path, set()).add(t)
    return out


def names_symbol(rf: inventory.RepoFacts, test: str, symbols: set[str], exact: bool = False) -> bool:
    """A test of a file counts for a CodeRef of one of its symbols when its text names the symbol (its last part, as
    a word, any case) or, unless ``exact``, each word of it, a cmd_ prefix (a subcommand's handler) left out:
    main(["record", "ddr"]) for cmd_record_ddr, a "production" path for check_production. A test that is not Python
    passes: what runs the file runs its symbols."""
    per = rf.evidence.per_test.get(test) if rf.evidence is not None else None
    if per is None:
        return True
    words = per[2] | {w for x in per[2] for w in re.split(r"[_-]+", x) if w}
    for sym in symbols:
        last = sym.rsplit(".", 1)[-1].lower()
        parts = [w for w in last.split("_") if w]
        if last in words or not exact and all(w in words for w in parts[parts[:1] == ["cmd"]:]):
            return True
    return False


def code_tests(rf: inventory.RepoFacts, c: Code, tests_of: dict, imported: dict, cov: dict | None) -> set[str]:
    """The test modules of a node's code: per file, brain audit's evidence and the tests that import it. A symbol
    CodeRef keeps those that name it; when the coverage summary knows the symbol (it measured it, with test contexts),
    those of its tests the contexts saw run it, those that name it outright, and those the summary never saw (added
    since), by the names rule. A symbol the summary does not know (added or renamed since) keeps the names rule."""
    got: set[str] = set()
    seen = set((cov or {}).get("test_modules") or ())
    for p in c.files:
        ts = tests_of.get(p, set()) | imported.get(p, set())
        if p not in c.symbols:
            got |= ts
            continue
        for sym in c.symbols[p]:
            if not testcov.known(cov, p, sym):
                got |= {t for t in ts if names_symbol(rf, t, {sym})}
                continue
            ran = testcov.ran(cov, p, sym)
            got |= {t for t in ts if t in ran or names_symbol(rf, t, {sym}, exact=True)
                    or (t not in seen and names_symbol(rf, t, {sym}))}
    return got


def script_tests(u: inventory.Unit, rf: inventory.RepoFacts, idx: inventory.Index, mod_ev: dict) -> set[str]:
    """The tests of a script, as brain audit's test.script finds them: those named after it or that run it, else
    those of the module it is a shim of (a .py of 20 lines or fewer)."""
    via, tests = inventory.script_evidence(u, rf.evidence)
    if via:
        return set(tests)
    shim = inventory.shim_target(u, rf, idx)
    if shim and shim[0] == rf.name and mod_ev.get(shim[1], ("", []))[0] not in WEAK:
        return set(mod_ev[shim[1]][1])
    return set()


# --- workflows ---

def _args(text: str) -> list[str]:
    return [a.strip("'\"") for a in text.split() if not a.startswith("-")]


# --- the derivation ---

@dataclass
class Links:
    nodes: list[dict]
    edges: list[dict]
    docs: dict[str, list[str]]       # doc or spec path -> its Doc node ids
    specs: dict[str, str]            # spec path -> the Spec node anchored at it ('' when none)
    tests: dict[str, str]            # test module path -> its Test node id
    covers: dict[str, list[str]]     # test module path -> the units it covers
    documented: set[str]             # the Doc ids some node is documented_in
    tested: set[str]                 # the Test ids some node is tested_by
    missing: list[str] = field(default_factory=list)   # the project's repos a CodeRef names, not on this machine


def store_nodes(tree: inventory.Tree, store: str) -> list[dict]:
    """The nodes of a store held in a tree (``store``: its folder in the repo), this generator's own left out."""
    pre = f"{store}/nodes/"
    files = sorted(p for p in tree.files if p.startswith(pre) and p.endswith(".yaml") and "/" not in p[len(pre):]
                   and p[len(pre):] != GENERATED)
    tree.prefetch(files)
    out = []
    for f in files:
        data = inventory._load_yaml(tree, f)
        out += [n for n in data if isinstance(n, dict) and n.get("id")] if isinstance(data, list) else []
    return out


def store_edges(tree: inventory.Tree, store: str) -> list[dict]:
    """The edges of a store held in a tree (edges.yaml and edges/*.yaml), this generator's own left out."""
    pre = f"{store}/edges/"
    files = [f"{store}/edges.yaml"] * tree.has(f"{store}/edges.yaml") + sorted(
        p for p in tree.files if p.startswith(pre) and p.endswith(".yaml") and "/" not in p[len(pre):]
        and p[len(pre):] != GENERATED)
    tree.prefetch(files)
    out = []
    for f in files:
        data = inventory._load_yaml(tree, f)
        out += [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    return out


def _title(text: str, n: int = 100) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def derive(tree: inventory.Tree, repo: str, store: str = "notes/graph", rf: inventory.RepoFacts | None = None,
           idx: inventory.Index | None = None, mod_ev: dict | None = None, cfg=None,
           hand: list[dict] | None = None, hand_edges: list[dict] | None = None,
           home: inventory.Tree | None = None) -> Links:
    """The Doc, Test and Workflow nodes of a repo and their edges. ``rf``, ``idx`` and ``mod_ev`` (module path ->
    (via, tests)) are brain audit's when it calls; else they are collected for this repo alone (``cfg``: its
    projects.Repo, for its package roots and waivers). ``hand`` and ``hand_edges``: the store's other nodes and
    edges (default: read from the tree). ``home``: the tree of another repo of the project that holds the store
    (``hand`` and ``hand_edges`` read from it): the nodes stand for this repo's code through their CodeRefs and a
    Hook's rendered scripts (node_code), and no Spec node anchors this repo's specs."""
    if rf is None:
        rf = inventory.collect(tree, repo, getattr(cfg, "lang", "py"), getattr(cfg, "roots", None),
                               getattr(cfg, "waive", None))
        idx = inventory.Index.build({repo: rf})
        mod_ev = inventory.unit_evidence(rf, idx, idx.top_packages())
    mod_ev = mod_ev or {}
    at = {} if home is None else {"repo": repo}   # another repo's node: its anchor is a path of that repo
    hand = store_nodes(tree, store) if hand is None else hand
    hand = [n for n in hand if n.get("type") not in TYPES]
    refs: dict[str, set] = {}
    for e in store_edges(tree, store) if hand_edges is None else hand_edges:
        if e.get("type") == "implemented_by":
            refs.setdefault(str(e.get("from")), set()).add(str(e.get("to")))
    nodes: list[dict] = []
    edges: list[dict] = []

    def edge(src: str, dst: str, etype: str) -> None:
        edges.append({"from": src, "to": dst, "type": etype})

    # docs and specs
    spec_of = {_anchor_file(n): str(n["id"]) for n in hand
               if home is None and n.get("type") == "Spec" and _anchor_file(n)}
    doc_paths = sorted(p for p in tree.files if inventory.is_doc(p) or is_spec(p))
    tree.prefetch(doc_paths)
    docs: dict[str, list[str]] = {}
    specs = {p: spec_of.get(p, "") for p in doc_paths if is_spec(p) and home is None}   # elsewhere: a doc
    code = {str(n["id"]): node_code(tree, repo, n, refs.get(str(n["id"]), set()), home) for n in hand
            if n.get("type") != "CodeRef"}
    ids = {str(n["id"]) for n in hand if "-" in str(n["id"]) or ":" in str(n["id"])}
    documented: set[str] = set()
    for path in doc_paths:
        for sec in sections(path, tree.text(path) or ""):
            did = f"doc:{repo}:{path}" + (f"::{sec.key}" if sec.key else "")
            docs.setdefault(path, []).append(did)
            named = sorted({f for tok in PATH_REF.findall(sec.text) for f in resolve(tree, tok, path)})
            props = {"paths": named} if named else {}
            nodes.append({"id": did, "type": "Doc", "status": "active",
                          "title": _title(f"{path} § {sec.title}" if sec.key else path), **at,
                          "anchor": anchor(path, sec), **({"props": props} if props else {})})
            own = specs.get(path, "")
            if own:
                edge(did, own, "part_of")
            toks, files, here = _tokens(sec.text), set(named), posixpath.dirname(path)
            for nid, c in code.items():
                if nid == own:
                    continue
                if (nid in ids and nid in toks) or c.files & files or any(
                        path.startswith(f + "/") or _folder_named(f, sec.text)
                        or (here and f.startswith(here + "/") and _folder_named(f[len(here) + 1:], sec.text))
                        for f in c.folders):
                    edge(nid, did, "documented_in")
                    documented.add(did)
    # tests
    covers: dict[str, set] = {t: set() for t in rf.tests}
    tests_of: dict[str, set] = {}
    imported = imports_of(rf, idx)
    for u in rf.units:
        if u.kind == "module":
            via, ts = mod_ev.get(u.path, ("", []))
            got = set(ts) if via not in WEAK else set()
        elif u.kind == "script":
            got = script_tests(u, rf, idx, mod_ev) if rf.evidence is not None else set()
        else:
            continue
        tests_of.setdefault(u.path, set()).update(got)
        for t in got:
            covers.setdefault(t, set()).add(u.path)
    folders = sorted({posixpath.dirname(t) for t in rf.tests} - {""})   # the folders that hold test modules
    tests = {t: f"test:{repo}:{t}" for t in rf.tests}

    def parent(path: str) -> str:
        """The nearest folder above ``path`` that holds test modules ('' when none)."""
        d = posixpath.dirname(path)
        while d:
            if d in folders:
                return d
            d = posixpath.dirname(d)
        return ""

    stats: dict[str, list] = {f: [0, 0] for f in folders}
    for t in rf.tests:
        fw, n, doc = cases(tree, t)
        props = {"framework": fw, "cases": n}
        if covers.get(t):
            props["covers"] = sorted(covers[t])
        nodes.append({"id": tests[t], "type": "Test", "status": "active",
                      "title": _title(f"{t}: {doc}" if doc else t), **at, "anchor": f"{t}#tests", "props": props})
        f = posixpath.dirname(t)
        if f:
            edge(tests[t], f"test:{repo}:{f}", "part_of")
            d = f
            while d:
                if d in stats:
                    stats[d][0] += 1
                    stats[d][1] += n
                d = posixpath.dirname(d)
    for f in folders:
        nodes.append({"id": f"test:{repo}:{f}", "type": "Test", "status": "active",
                      "title": f"{f}/: {stats[f][0]} test module(s), {stats[f][1]} test(s)", **at,
                      "anchor": f"{f}#tests", "props": {"modules": stats[f][0], "cases": stats[f][1]}})
        up = parent(f)
        if up:
            edge(f"test:{repo}:{f}", f"test:{repo}:{up}", "part_of")
    tested: set[str] = set()
    cov = testcov.load(home if home is not None else tree, store, repo)
    for nid, c in code.items():
        for t in sorted(code_tests(rf, c, tests_of, imported, cov)):
            if t in tests:
                edge(nid, tests[t], "tested_by")
                tested.add(tests[t])
    # workflows
    tops = [f for f in folders if not parent(f)] + [t for t in rf.tests if "/" not in t and t.endswith(".py")]
    default = testpaths(tree)

    def targets(args: list[str], wd: str, pester: bool) -> set[str]:
        out = set()
        for a in args:
            a = inventory._norm(posixpath.join(wd, a.split("::", 1)[0].split("[", 1)[0])) if a else ""
            if a in tests:
                out.add(tests[a])
            elif a in folders:
                out.add(f"test:{repo}:{a}")
            elif a:
                out.update(tests[t] for t in rf.tests if t.startswith(a + "/")
                           and (t.endswith(".Tests.ps1") or not pester))
        return out

    for wf in sorted(p for p in tree.files if p.startswith(WORKFLOWS) and p.endswith((".yml", ".yaml"))
                     and "/" not in p[len(WORKFLOWS):]):
        data = inventory._load_yaml(tree, wf)
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
            continue
        on = data.get("on", data.get(True))
        triggers = [on] if isinstance(on, str) else list(on) if isinstance(on, (list, dict)) else []
        name = str(data.get("name") or posixpath.basename(wf).rsplit(".", 1)[0])
        wd0 = str((((data.get("defaults") or {}).get("run") or {}).get("working-directory")) or "")
        for job_id, job in data["jobs"].items():
            if not isinstance(job, dict):
                continue
            wid = f"workflow:{repo}:{wf}::{job_id}"
            props = {k: v for k, v in (("triggers", ", ".join(map(str, triggers))),
                                       ("runs_on", str(job.get("runs-on") or ""))) if v}
            nodes.append({"id": wid, "type": "Workflow", "status": "active",
                          "title": _title(f"{name}: {job.get('name') or job_id}"), **at,
                          "anchor": f"{wf}#{job_id}", **({"props": props} if props else {})})
            wd1 = str((((job.get("defaults") or {}).get("run") or {}).get("working-directory")) or wd0)
            runs: set[str] = set()
            for step in job.get("steps") or []:
                run = step.get("run") if isinstance(step, dict) else None
                if not isinstance(run, str):
                    continue
                wd = inventory._norm(str(step.get("working-directory") or wd1))
                for m in PYTEST.finditer(run):
                    got = targets(_args(m.group(1)), wd, False)
                    runs |= got or targets(default, "", False) or {f"test:{repo}:{t}" if t in folders else tests[t]
                                                                   for t in tops}
                for m in PESTER.finditer(run):
                    got = targets(_args(m.group(1)), wd, True)
                    runs |= got or {tests[t] for t in rf.tests if t.endswith(".Tests.ps1")}
            for t in sorted(runs):
                edge(wid, t, "runs")
    seen, unique = set(), []
    for e in sorted(edges, key=lambda e: (e["from"], e["to"], e["type"])):   # one edge per node pair
        if (e["from"], e["to"]) not in seen:
            seen.add((e["from"], e["to"]))
            unique.append(e)
    nodes.sort(key=lambda n: n["id"])
    return Links(nodes, unique, docs, specs, tests, {t: sorted(c) for t, c in covers.items()}, documented, tested)


# --- the store ---

def applies(store: Path) -> bool:
    """A store whose schema has a Doc, Test or Workflow type takes the generated links."""
    try:
        return bool(set(graph.load_schema(store).get("node_types") or []) & set(TYPES))
    except (OSError, ValueError):
        return False


def render(lk: Links) -> tuple[str, str]:
    nodes = HEAD + ("".join(graph.render_node(n) for n in lk.nodes) if lk.nodes else "[]\n")
    edges = HEAD + ("".join(graph.render_edge(e) for e in lk.edges) if lk.edges else "[]\n")
    return nodes, edges


def _where(root: Path, store: Path) -> tuple[Path, str]:
    """(the repo's top folder, the store's folder in it) for a store inside ``root``'s git checkout."""
    top = Path(inventory.git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    try:
        rel = store.resolve().relative_to(top).as_posix()
    except ValueError as exc:
        raise inventory.AuditError(f"{store} is not inside the checkout {top}") from exc
    return top, rel


def coded_repos(hand: list[dict]) -> set[str]:
    """The repos the store's active CodeRefs name (lowercase)."""
    out = set()
    for n in hand:
        if n.get("type") == "CodeRef" and n.get("status", "active") == "active":
            try:
                out.add(inventory.parse_code_ref(str(n["id"]))[0].lower())
            except ValueError:
                continue
    return out


def other_trees(cfgs: list, own: str, named: set[str]) -> tuple[list[tuple[str, inventory.Tree, object]], list[str]]:
    """The project's other repos (``cfgs``: projects.Repo) that a CodeRef of the store names, each at the commit
    brain audit reads (its default branch's tip, HEAD in a linked worktree), and the names of those whose checkout
    is not on this machine (left out of the derivation)."""
    got, missing = [], []
    for c in cfgs:
        if c.name == own or c.name not in named:
            continue
        if not (c.path / ".git").exists():
            missing.append(c.name)
            continue
        ref, branch = inventory.reading_ref(c.path)
        got.append((c.name, inventory.git_tree(c.path, ref, branch), c))
    return got, missing


def anchor_roots(cfgs: list, own: str) -> dict[str, Path]:
    """The checkouts of the project's other repos (``cfgs``: projects.Repo, their paths read from the root, else from
    its main checkout) that are on this machine: where research_graph check reads the anchors of their nodes."""
    return {c.name: c.path for c in cfgs if c.name != own and (c.path / ".git").exists()}


def merge(parts: list[Links]) -> Links:
    """The links of several repos as one (node ids carry their repo, so they never collide)."""
    seen, edges = set(), []
    for e in sorted((e for lk in parts for e in lk.edges), key=lambda e: (e["from"], e["to"], e["type"])):
        if (e["from"], e["to"]) not in seen:
            seen.add((e["from"], e["to"]))
            edges.append(e)
    out = Links(sorted((n for lk in parts for n in lk.nodes), key=lambda n: n["id"]), edges, {}, {}, {}, {}, set(),
                set())
    for lk in parts:
        out.docs.update(lk.docs)
        out.specs.update(lk.specs)
        out.tests.update(lk.tests)
        out.covers.update(lk.covers)
        out.documented |= lk.documented
        out.tested |= lk.tested
    return out


def for_store(root: Path, store: Path, repo: str, cfg=None, cfgs: list | None = None) -> Links:
    """The derivation from the working tree (tracked and untracked files, not ignored) of the checkout that holds
    ``store``; with ``cfgs`` (the project's repos), also of each other repo a CodeRef of the store names, at its
    committed state (their Doc, Test and Workflow nodes, the tested_by and documented_in edges from the nodes that
    stand for their code). A repo whose checkout is missing here is left out (``missing``)."""
    top, rel = _where(root, store)
    tree = inventory.work_tree(top)
    lk = derive(tree, repo, rel, cfg=cfg)
    if not cfgs:
        return lk
    hand, hand_edges = store_nodes(tree, rel), store_edges(tree, rel)
    others, missing = other_trees(cfgs, repo, coded_repos(hand))
    out = merge([lk] + [derive(t, name, rel, cfg=c, hand=hand, hand_edges=hand_edges, home=tree)
                        for name, t, c in others])
    out.missing = missing
    return out


def files(store: Path) -> tuple[Path, Path]:
    return store / "nodes" / GENERATED, store / "edges" / GENERATED


def write(root: Path, store: Path, repo: str, cfg=None, cfgs: list | None = None) -> tuple[int, int, list[str]]:
    """Write the generated files: (nodes, edges, the repos left out because their checkout is not here)."""
    lk = for_store(root, store, repo, cfg, cfgs)
    nf, ef = files(store)
    nodes, edges = render(lk)
    ef.parent.mkdir(exist_ok=True)
    for f, text in ((nf, nodes), (ef, edges)):
        if not f.is_file() or f.read_text(encoding="utf-8") != text:
            f.write_text(text, encoding="utf-8", newline="\n")
    return len(lk.nodes), len(lk.edges), lk.missing


def stale(root: Path, store: Path, repo: str, cfg=None, cfgs: list | None = None) -> list[str]:
    """The generated files that differ from a derivation now (brain check warns: brain sync)."""
    nodes, edges = render(for_store(root, store, repo, cfg, cfgs))
    out = []
    for f, text in zip(files(store), (nodes, edges)):
        if not f.is_file() or f.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
            out.append(f.relative_to(store).as_posix())
    return out
