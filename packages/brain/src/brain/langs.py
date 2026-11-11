"""The language adapters (wi-brain-lang-adapters, spec-brain-client-standards §5): how a repo's own tools plug in, so
that a TypeScript or Swift product is read through its tools instead of the Python-only checks.

A repo declares, in projects.yaml ``repos[].tools`` (a new optional key; ``repos[].lang`` is unchanged), one entry per
adapter slot (:data:`SLOTS`: lint, typecheck, test, coverage, format) naming the **report file** its tool writes, and
that report's format (:data:`FORMATS`)::

  repos:
    - path: ../web
      lang: ts
      tools:
        lint: {report: reports/eslint.sarif, format: sarif, tool: eslint}
        test: {report: reports/junit.xml, format: junit}
        coverage: {report: coverage/coverage-summary.json, format: istanbul-summary}

The engine **reads** these files and runs nothing: the project's own CI or its developer runs the tools and writes the
reports (running the declared commands under the guards is wi-brain-lang-adapters-exec, after a test phase). A report
is read from the repo's registered checkout, relative to it. ``brain audit`` measures ``lang.report`` for a repo that
declares ``tools:`` (a report missing or unreadable, failed tests, lint, type or format findings, coverage under the
floor); ``brain standards check`` counts a standard whose check runs through a slot the repo declares as covered on
that repo's language. :data:`DEFAULTS` names the usual tools of each language and how each writes its report, for
the docs and the messages only: nothing is assumed from them.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from . import schema

SLOTS = ("lint", "typecheck", "test", "coverage", "format")
FORMATS = {
    "sarif": "SARIF 2.1 (lint, type and format findings): every result counts, a level of note or none aside",
    "junit": "JUnit XML (tests, or findings a tool reports as failed cases): failures and errors count",
    "cobertura": "Cobertura XML coverage: the root's line-rate",
    "lcov": "an lcov trace: lines hit over lines found",
    "coverage-json": "coverage.py's JSON report: totals.percent_covered",
    "istanbul-summary": "istanbul's or c8's coverage-summary.json: total.lines.pct",
}
SLOT_FORMATS = {
    "lint": ("sarif", "junit"),
    "typecheck": ("sarif", "junit"),
    "format": ("sarif", "junit"),
    "test": ("junit",),
    "coverage": ("cobertura", "lcov", "coverage-json", "istanbul-summary"),
}
TOOL_KEYS = {"report": "the report file the tool writes, relative to the repo's checkout",
             "format": "its format (brain.langs.FORMATS)",
             "tool": "the tool's name, for the messages (optional)"}
# The usual tools of each language and how each writes a report the engine reads (docs and messages only).
DEFAULTS = {
    "py": {"lint": "ruff check --output-format sarif -o ruff.sarif",
           "typecheck": "mypy --junit-xml mypy.xml (or pyright --outputjson, converted to SARIF)",
           "test": "pytest --junitxml junit.xml",
           "coverage": "pytest --cov --cov-report json:coverage.json",
           "format": "ruff format --check (exit code; no report yet)"},
    "ts": {"lint": "eslint -f @microsoft/eslint-formatter-sarif -o eslint.sarif",
           "typecheck": "tsc --noEmit (exit code; a SARIF converter for a report)",
           "test": "vitest --reporter=junit --outputFile junit.xml (or jest-junit)",
           "coverage": "c8 --reporter=json-summary (coverage/coverage-summary.json) or --reporter=lcov",
           "format": "prettier --check (exit code; no report yet)"},
}


class ReportError(ValueError):
    """A report that cannot be read: no file, or not its declared format."""


@dataclass
class Result:
    """What a report says, in one slot of one repo."""
    slot: str
    report: str
    tool: str = ""
    count: int = 0            # findings (lint, typecheck, format) or failed tests (test)
    total: int = 0            # tests run (test)
    percent: float | None = None   # coverage
    error: str = ""           # why it could not be read ("" when it was)

    @property
    def read(self) -> bool:
        return not self.error


def tools_errors(where: str, value, strict: bool | None = None, notes: list[str] | None = None) -> list[str]:
    """What a repo's ``tools:`` breaks: not a mapping, a slot or a key this engine does not know (a note in read mode:
    a newer engine's), an entry without its report or with a format its slot does not read."""
    if not isinstance(value, dict):
        return [f"{where}: tools is a mapping of slot -> {{report, format}} (slots: {', '.join(SLOTS)})"]
    errors = []
    for slot, spec in value.items():
        if slot not in SLOTS:
            errors += schema.tolerate(f"{where}: tools: unknown slot {slot!r} (known: {', '.join(SLOTS)})",
                                      strict, notes)
            continue
        errors += _entry_errors(f"{where}: tools.{slot}", slot, spec, strict, notes)
    return errors


def _entry_errors(where: str, slot: str, spec, strict: bool | None, notes: list[str] | None) -> list[str]:
    if not isinstance(spec, dict):
        return [f"{where}: a mapping {{report, format}}"]
    unknown = sorted(set(map(str, spec)) - set(TOOL_KEYS))
    errors = schema.tolerate(f"{where}: unknown key(s) {', '.join(unknown)} (known: {', '.join(TOOL_KEYS)})",
                             strict, notes) if unknown else []
    if not isinstance(spec.get("report"), str) or not spec["report"]:
        errors.append(f"{where}: report is the path of the file the tool writes")
    elif Path(spec["report"]).anchor or ".." in Path(spec["report"]).parts:
        errors.append(f"{where}: report is a path inside the repo's checkout")
    fmt = spec.get("format")
    if not isinstance(fmt, str) or not fmt:
        errors.append(f"{where}: format is one of {', '.join(SLOT_FORMATS[slot])}")
    elif fmt not in SLOT_FORMATS[slot]:   # a newer engine may read it in this slot: a note in read mode
        errors += schema.tolerate(f"{where}: format {fmt!r} is not one of {', '.join(SLOT_FORMATS[slot])}",
                                  strict, notes)
    return errors


def declared(tools) -> dict[str, dict]:
    """The slots a repo declares that this engine can read: {slot: {report, format, tool}}."""
    if not isinstance(tools, dict):
        return {}
    return {slot: spec for slot, spec in tools.items() if slot in SLOTS and isinstance(spec, dict)
            and isinstance(spec.get("report"), str) and spec.get("format") in SLOT_FORMATS[slot]}


# --- the readers ------------------------------------------------------------------------------------------------

def _xml(path: Path) -> ET.Element:
    try:
        return ET.fromstring(path.read_bytes())
    except ET.ParseError as exc:
        raise ReportError(f"not XML ({exc})") from exc


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def read_junit(path: Path) -> tuple[int, int]:
    """(failed, run) of a JUnit XML report: the cases with a failure or an error, over the cases (a skipped case is
    run, never failed). Each suite counts its own cases, nested suites theirs; a suite that lists no case and holds
    no suite gives its tests, failures and errors attributes instead."""
    root = _xml(path)
    if root.tag not in ("testsuite", "testsuites"):
        raise ReportError(f"not JUnit XML (root <{root.tag}>)")
    failed = run = 0
    for s in root.iter("testsuite"):   # the root itself first when it is a suite
        cases = s.findall("testcase")
        if cases:
            run += len(cases)
            failed += sum(1 for c in cases if c.find("failure") is not None or c.find("error") is not None)
        elif s.find("testsuite") is None:
            run += _int(s.get("tests"))
            failed += _int(s.get("failures")) + _int(s.get("errors"))
    return failed, run


def read_sarif(path: Path) -> int:
    """The findings of a SARIF log: every result of every run, a level of none or note left out."""
    data = _json(path)
    runs = data.get("runs") if isinstance(data, dict) else None
    if not isinstance(runs, list):
        raise ReportError("not SARIF (no runs)")
    return sum(1 for r in runs if isinstance(r, dict) for res in (r.get("results") or [])
               if isinstance(res, dict) and res.get("level") not in ("none", "note"))


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ReportError(f"not JSON ({type(exc).__name__})") from exc


def read_coverage(path: Path, fmt: str) -> float:
    """The line coverage, in percent, of a coverage report of format ``fmt``."""
    if fmt == "cobertura":
        root = _xml(path)
        if root.tag != "coverage" or root.get("line-rate") is None:
            raise ReportError("not Cobertura XML (no <coverage line-rate>)")
        return _percent(root.get("line-rate"), "Cobertura XML (line-rate)", 100)
    if fmt == "lcov":
        found = hit = 0
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("LF:"):
                found += _int(line[3:])
            elif line.startswith("LH:"):
                hit += _int(line[3:])
        if not found:
            raise ReportError("not an lcov trace (no LF: line)")
        return round(100 * hit / found, 2)
    data = _json(path)
    key = "totals.percent_covered" if fmt == "coverage-json" else "total.lines.pct"
    try:
        value = data["totals"]["percent_covered"] if fmt == "coverage-json" else data["total"]["lines"]["pct"]
    except (KeyError, TypeError) as exc:
        raise ReportError(f"not {fmt} (no {key})") from exc
    return _percent(value, f"{fmt} ({key})")


def _percent(value, what: str, scale: float = 1) -> float:
    """A coverage value as a percent of 0 to 100; :class:`ReportError` for anything else (text, NaN, out of range)."""
    try:
        pct = float(value) * scale
    except (TypeError, ValueError) as exc:
        raise ReportError(f"not {what}: {value!r} is not a number") from exc
    if not math.isfinite(pct) or not 0 <= pct <= 100:
        raise ReportError(f"not {what}: {value!r} is not a coverage")
    return round(pct, 2)


def read(checkout: Path, slot: str, spec: dict) -> Result:
    """What the report of ``slot`` says, read from the repo's ``checkout``; ``error`` says why it cannot be read."""
    out = Result(slot, spec["report"], str(spec.get("tool") or ""))
    path = checkout / spec["report"]
    if not path.is_file():
        out.error = f"no report at {spec['report']}"
        return out
    fmt = spec["format"]
    try:
        if slot == "coverage":
            out.percent = read_coverage(path, fmt)
        elif fmt == "junit":
            out.count, out.total = read_junit(path)
        else:
            out.count = read_sarif(path)
    except (ReportError, OSError) as exc:
        out.error = f"{spec['report']}: {exc}"
    else:
        if slot == "test" and not out.total:
            out.error = f"{spec['report']}: no test ran"
    return out


def results(checkout: Path, tools) -> list[Result]:
    """Every declared slot's result, in :data:`SLOTS` order."""
    decl = declared(tools)
    return [read(checkout, slot, decl[slot]) for slot in SLOTS if slot in decl]


def how(lang: str, slot: str) -> str:
    """How the usual tool of ``lang`` writes the report of ``slot`` (:data:`DEFAULTS`), or ''."""
    return DEFAULTS.get(lang, {}).get(slot, "")
