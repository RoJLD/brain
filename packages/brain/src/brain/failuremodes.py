"""The invariants and failure modes to test, from what a change touches (wi-brain-brief-failure-modes; the waves
retro of 2026-11-03, root cause A: the brief said what to build, not how it breaks).

One table, :data:`SURFACES`, read by two commands so that the author's tests and the review ask the same questions:

- ``brain brief <item>`` writes the section « Invariants and failure modes to test » from the item's predicted
  surface (brain.collisions: the CodeRefs of its features and modules, the files it names), its title and its props;
- ``brain review prep [--item ID]`` writes the same section into the packet's README, from the diff's files and
  lines, plus the item's when ``--item`` names it.

Each surface kind is matched by path patterns (on a file) or text patterns (on the item's title and props, or a
diff's lines); what matched is said beside it, so a reader can drop a false match. The item's own invariants
(``props.invariants``: a line or a list) come last, as recorded. A surface the table cannot see (a state machine, the
order of two events) is the review's to read: the section is a floor, not a ceiling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TITLE = "Invariants and failure modes to test"


@dataclass(frozen=True)
class Surface:
    key: str
    name: str
    test: str
    paths: tuple[str, ...] = ()    # regexes searched in a touched file's path (/ separators)
    words: tuple[str, ...] = ()    # regexes searched (case ignored) in the item's text
    on_diff: bool = False          # its words are searched in a diff's changed lines too


def _py(*names: str) -> tuple[str, ...]:
    """The path patterns of modules by name: the whole file name (a test named after the module is not it)."""
    return tuple(rf"(^|/){n}\.py$" for n in names)


SURFACES = (
    Surface("store", "a store, a schema or a persisted format",
            "the store as the previous release wrote it, as a fixture: every command that reads it runs on it; the "
            "format's class, v, window and round trip (an older engine reading the new file, this engine reading "
            "an older and a newer one), and the fixture to add (docs/formats.md)",
            (r"(^|/)schemas?/", r"\.schema\.json$", r"(^|/)fixtures/formats/",
             *_py("stateio", "formats?", "records", "store")),
            (r"\bschema\b", r"\bstores?\b", r"\bpersisted\b", r"\bformat(s)? (v\d|version)", r"\bjsonl\b",
             r"\bledger\b")),
    Surface("procedure", "a procedure step",
            "the step fails without blocking the others (an optional step never stops the procedure, and says why "
            "it was skipped); its order with the steps before and after it",
            (r"(^|/)procedures/", r"SKILL\.md$", r"(^|/)rules/"),
            (r"\bprocedure\b", r"\bclose-item\b", r"\bskill\b", r"\bstep \d")),
    Surface("external", "an external system (a service, an API, a tool on the PATH)",
            "the system down, slow (a timeout that ends) and answering garbage; its real payload copied as a "
            "fixture, never one the code under test made",
            (r"(^|/)adapters/", r"(^|/)mcp\w*(\.py$|/)", *_py("net", "codeindex", "notify", "probe")),
            (r"\bAPI\b", r"\bHTTPS?\b", r"\bgh (pr|api|run)\b", r"\bGitHub\b", r"\bnetwork\b", r"\bMCP\b",
             r"\bGitNexus\b", r"\bwebhook\b", r"\bexternal\b")),
    Surface("multiwrite", "a write in several steps",
            "the run cut between two writes (killed, a full disk): atomic (a temporary file then a rename) or "
            "resumable, never a half state another command trusts; the default of a write is the safe one",
            _py("stateio", "keystore", "vault", "rotation", "outbox", "spool", "update"),
            (r"\batomic", r"\brotat", r"\brewrit", r"\bmigrat", r"\breseal\b", r"\bblue-green\b")),
    Surface("cli", "a command line",
            "the parent's flags after the subcommand, --json where the command reads data, a non-zero exit on "
            "failure; every `brain ...` line of the docs and procedures passes the real parser",
            (r"(^|/)commands/", *_py("cli")),
            (r"`brain [a-z][\w-]*", r"\bbrain [a-z][\w-]+ --", r"\bsubcommand\b", r"\bflag\b")),
    Surface("heuristic", "a heuristic or a metric",
            "a replay on the real data (the ledger, the graph, the transcripts) before it ships, its misses "
            "counted; the same input in two forms (a list or a string, 0- or 1-based lines) read alike",
            _py("cost", "forecast", "sizing", "ranking", "perf", "usage", "budget"),
            (r"\bheuristic", r"\bmetric", r"\bscore\b", r"\bestimat", r"\bthreshold", r"\bcalibrat", r"\bforecast",
             r"\bbacktest", r"\bsimilarity\b")),
    Surface("guard", "a guard or a gate",
            "every sibling path through it: each writer passes the same door, and a test makes the door refuse and "
            "checks that each path is refused (the mode that tolerates and the one that refuses agree)",
            (r"(^|/)hooks/", *_py("guards?", "mergeready", "mergecheck", "governor", "permissions", "public",
                                  "secretscan", "mcpguards")),
            (r"\bguards?\b", r"\bgates?\b", r"\brefuses?\b", r"\bhook\b")),
    Surface("counted", "a counted or guarded set",
            "its scope said and tested: per store, per project, per tenant (two of them in the fixture, the count "
            "of one never reaching the other)",
            _py("quota", "slots", "collisions"),
            (r"\bper (store|project|tenant|wave|session)\b", r"\bquota\b", r"\bcap\b", r"\bat most \d", r"\bdedup",
             r"\bunique\b")),
    Surface("moved", "a test removed or a check moved",
            "each assertion the old test or check made, and its new home (a test that still fails when the "
            "behaviour breaks)",
            (),
            (r"^-def test\w*\(", r"\bsupersed", r"\bmoves? (the|a) (check|test)", r"\bremoves? (the|a) (check|test)"),
            on_diff=True),
    Surface("escaped", "text written into another format",
            "an escaping helper per target (Markdown, YAML, JSON, XML or HTML, a shell, CSV), tested with a newline, "
            "quotes, %, $ and XML entities",
            (r"(^|/)templates/", r"(^|/)export\w*(\.py$|/)", *_py("render", "views", "digest", "readme")),
            (r"\brender", r"\bescap", r"\bexport", r"\bXML\b", r"\bHTML\b", r"\bCSV\b")),
)
PUBLIC = ("public", "the public engine",
          "no private id or name in the code, the docs, the tests or a commit message: brain check --public "
          "--history before the push")


def _hit(patterns: tuple[str, ...], texts: list[str], flags: int = 0) -> str:
    """The first text a pattern matches, shortened: what matched, for the reader to judge."""
    for p in patterns:
        rx = re.compile(p, flags | re.M)
        for t in texts:
            m = rx.search(t)
            if m:
                return m.group(0).strip().lstrip("-").strip()[:60]
    return ""


TEST_DEF = re.compile(r"^([+-])\s*def (test\w*)\(")


def removed_tests(diff: list[str]) -> list[str]:
    """The tests a diff removes for good, as ``-def NAME(`` lines: a test whose ``def`` line is removed and not added
    back under its name (an edited signature or body is not a removal)."""
    gone, back = [], set()
    for line in diff:
        m = TEST_DEF.match(line)
        if m and m.group(1) == "-":
            gone.append(m.group(2))
        elif m:
            back.add(m.group(2))
    return [f"-def {n}(" for n in dict.fromkeys(gone) if n not in back]


def _source(path: str) -> bool:
    """Whether a path's surface counts: a test or a doc is not the module it names (the format fixtures are a
    store's)."""
    return not {"tests", "docs"} & set(path.split("/")[:-1]) or "/fixtures/formats/" in f"/{path}"


def match(files: list[str] | None = None, texts: list[str] | None = None,
          diff: list[str] | None = None) -> list[tuple[Surface, str]]:
    """The surfaces ``files`` (paths, the tests and docs left out), ``texts`` (an item's title and props) and ``diff``
    (a diff's changed lines, read only by the surfaces marked ``on_diff``, as the tests it removes for good: code
    mentions a store or a guard everywhere) touch, in the table's order, each with what matched it (a path, or the
    matching words)."""
    files = [f for f in (f.replace("\\", "/") for f in files or []) if _source(f)]
    texts = [t for t in texts or [] if t]
    gone = removed_tests(list(diff or []))
    found = [(s, _why(s, files, texts + (gone if s.on_diff else []))) for s in SURFACES]
    return [(s, why) for s, why in found if why]


def _why(s: Surface, files: list[str], texts: list[str]) -> str:
    """What calls surface ``s``: the first file its paths match, else the words its patterns find, else ''."""
    path = next((f for f in files if any(re.search(p, f) for p in s.paths)), "")
    words = "" if path else _hit(s.words, texts, re.I)
    return path or (f"« {words} »" if words else "")


def own(props: dict | None) -> list[str]:
    """The item's own invariants (``props.invariants``: a line or a list of lines)."""
    v = (props or {}).get("invariants")
    if isinstance(v, str):
        v = [v]
    return [" ".join(str(x).split()) for x in v or [] if str(x).strip()] if isinstance(v, (list, tuple)) else []


def lines(found: list[tuple[Surface, str]], invariants: list[str] | None = None, public: bool = False) -> list[str]:
    """The section's bullet lines: one per surface touched, the public engine, then the item's own invariants."""
    out = [f"- **{s.name}** ({why}): {s.test}." for s, why in found]
    if public:
        out.append(f"- **{PUBLIC[1]}**: {PUBLIC[2]}.")
    out += [f"- **the item's own** (props.invariants): {x}" for x in invariants or []]
    return out


def item_texts(node: dict) -> list[str]:
    """The item's title and every text of its props (props.invariants apart: they are listed as they are)."""
    props = {k: v for k, v in (node.get("props") or {}).items() if k != "invariants"}
    out, stack = [str(node.get("title") or "")], [props]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            stack += list(v.values())
        elif isinstance(v, list):
            stack += v
        elif isinstance(v, str):
            out.append(v)
    return out


def changed_lines(patch: str) -> list[str]:
    """A unified diff's added and removed lines, their ``+`` or ``-`` kept (the file headers left out)."""
    return [x for x in patch.splitlines() if x[:1] in "+-" and not x.startswith(("+++ ", "--- "))]


def for_item(node: dict, paths: list[str], public: bool = False, extra_files: list[str] | None = None,
             diff: list[str] | None = None) -> list[str]:
    """The section of an item: its predicted ``paths`` (and ``extra_files``, a diff's), its texts, ``diff``'s
    changed lines, the public engine when ``public``, then its own invariants."""
    found = match([*paths, *(extra_files or [])], item_texts(node), diff)
    return lines(found, own(node.get("props")), public)
