"""The standards registry (wi-brain-standards-registry, spec-brain-client-standards §5 and §9; STD-1, STD-4): standards
as data, one row per standard, each with the check that enforces it.

A **catalog** is a YAML file of rows (``schemas/standards.schema.json``, docs/standards.md): the engine's own under
``brain/catalogs/`` (generic rows, in English, nothing private), and a brain's local ones that a project names in
projects.yaml ``standards.catalogs`` (paths relative to the registry's folder, as ``root`` is): a discipline's rows
that stay in the owner's private brain. A row says:

  id           unique across every catalog loaded, never reused
  domain       its domain within the catalog (persistence, security, testing...)
  statement    what a project that follows it does, checkable
  profiles     the kinds of project it applies to (:data:`PROFILES`), or ``any``
  stage        the stage from which it is required (:data:`STAGES`, in order)
  enforcement  how it is enforced, from the cheapest (:data:`ENFORCEMENT`)
  check        what enforces it; ``adapter`` the language adapter's slot that carries its results (:data:`ADAPTERS`)
  languages    the languages its check covers, or ``any``
  coverage     how the Brain itself meets it ({status: :data:`COVERAGE`, by})
  status       proposed (curated, not validated) or validated (the owner validated it, STD-6)

**Opt-in.** A row binds no project. A project opts in with projects.yaml ``standards:`` (:data:`SELECTION_KEYS`):
its ``profiles`` and ``stage`` select the rows whose profiles meet its own (or ``any``) and whose stage is at or
before its own; ``include`` adds rows by id whatever their profile and stage, ``exclude`` waives rows by id with a
reason (``{id: reason}``, 15 characters or more). A project without the key is not concerned: nothing it does is
checked against the registry, so nothing that passed before is refused.

``brain standards list|show|check`` read it (brain.commands.standards); ``brain brief`` lists a project's rows as the
invariants of its sessions. The other consumers (review lenses, the audit's standards check, the rules text, CI
templates) come with wi-brain-standards-registry-consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import graph, schema

KIND = "standards"   # its schema: schemas/standards.schema.json (brain.schema)
ENGINE_DIR = Path(__file__).with_name("catalogs")
# The vocabularies. A value outside them is a note in read mode (a newer engine's), an error in strict mode (CI).
PROFILES = {
    "any": "every kind of project",
    "library": "a library other code imports",
    "cli": "a command-line tool",
    "local-client": "a program on the user's machine that owns local data (a desktop or mobile client)",
    "service": "a resident process others call over the network",
    "data-pipeline": "a job that moves or transforms data on a schedule",
    "embedded": "an embedded or low-level system",
    "research": "a research project: hypotheses, tests and documents",
    "strategy": "a strategy project: decisions, assumptions, KPIs",
    "marketing": "a marketing project: claims, campaigns, consent",
    "engineering-product": "a physical or hardware product: requirements, verification, validation",
}
STAGES = ("prototype", "mvp", "v1", "scale")
ENFORCEMENT = {
    "check": "a machine check that blocks (a lint, a type checker, a schema diff, a scan)",
    "measure": "a number that trends (coverage, mutation score, a benchmark, a latency)",
    "test-template": "a test the brief asks for (property-based, fuzzing, fault injection)",
    "review-lens": "a question of the review",
    "rule": "judgement only, in the rules text",
}
ADAPTERS = ("lint", "typecheck", "test", "coverage", "format")
COVERAGE = ("have", "partial", "none", "n/a")
STATUSES = ("proposed", "validated")
SELECTION_KEYS = {
    "profiles": "the kinds of project it is (brain.standards.PROFILES)",
    "stage": "its stage: prototype, mvp, v1 or scale; a row is required from its own stage on",
    "include": "ids taken whatever their profile and stage",
    "exclude": "{id: reason of 15 characters or more}: rows waived",
    "catalogs": "the brain's local catalogs, relative to the registry's folder",
}
REASON = 15


class StandardsError(ValueError):
    """A catalog that cannot be read (no file, YAML that does not parse, not a mapping): exit code 2."""


@dataclass
class Row:
    id: str
    catalog: str
    domain: str
    statement: str
    profiles: list[str]
    stage: str
    enforcement: str
    check: str
    languages: list[str]
    status: str
    title: str = ""
    why: str = ""
    adapter: str = ""
    coverage: dict = field(default_factory=dict)
    source: str = ""
    refs: list[str] = field(default_factory=list)
    file: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "catalog": self.catalog, "domain": self.domain, "title": self.title,
                "statement": self.statement, "why": self.why, "profiles": list(self.profiles), "stage": self.stage,
                "enforcement": self.enforcement, "check": self.check, "adapter": self.adapter,
                "languages": list(self.languages), "coverage": dict(self.coverage), "status": self.status,
                "source": self.source, "refs": list(self.refs), "file": self.file}

    def covers(self, lang: str) -> bool:
        """Whether its check covers a repo of language ``lang``."""
        return "any" in self.languages or lang in self.languages


@dataclass
class Catalog:
    name: str
    title: str
    path: Path
    engine: bool
    source: str = ""
    rows: list[Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Selection:
    """A project's projects.yaml standards:, as declared (a value of the wrong shape is :func:`selection_errors`')."""
    profiles: list[str] = field(default_factory=list)
    stage: str = ""
    include: list[str] = field(default_factory=list)
    exclude: dict[str, str] = field(default_factory=dict)
    catalogs: list[str] = field(default_factory=list)


def _strings(value) -> list[str]:
    value = [value] if isinstance(value, str) else value
    return [str(v) for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _vocab(where: str, what: str, value: str, known, strict: bool | None, notes: list[str]) -> list[str]:
    if value in known:
        return []
    return schema.tolerate(f"{where}: {what} {value!r} is not one of {', '.join(known)}", strict, notes)


def row_errors(where: str, row: dict, strict: bool | None = None, notes: list[str] | None = None) -> list[str]:
    """What a row breaks that its schema cannot say: a profile, stage, enforcement, adapter, coverage or status this
    engine does not know (a note in read mode: a newer engine's value; an error in strict mode)."""
    notes = notes if notes is not None else []
    errors = []
    for p in _strings(row.get("profiles")):
        errors += _vocab(where, "profile", p, PROFILES, strict, notes)
    if isinstance(row.get("stage"), str):
        errors += _vocab(where, "stage", row["stage"], STAGES, strict, notes)
    if isinstance(row.get("enforcement"), str):
        errors += _vocab(where, "enforcement", row["enforcement"], ENFORCEMENT, strict, notes)
    if isinstance(row.get("adapter"), str):
        errors += _vocab(where, "adapter", row["adapter"], ADAPTERS, strict, notes)
    if isinstance(row.get("status"), str):
        errors += _vocab(where, "status", row["status"], STATUSES, strict, notes)
    cov = row.get("coverage")
    if isinstance(cov, dict) and isinstance(cov.get("status"), str):
        errors += _vocab(where, "coverage", cov["status"], COVERAGE, strict, notes)
    return errors


def parse(data, path: Path, engine: bool = False, strict: bool | None = None) -> Catalog:
    """A catalog's data read into rows; what it breaks goes to ``errors`` (its schema, then the vocabularies), what a
    newer engine may have written to ``notes``. A row without an id or a statement is left out (an error)."""
    if not isinstance(data, dict):
        raise StandardsError(f"{path}: a catalog is a mapping (docs/standards.md)")
    mode = schema.mode() if strict is None else (schema.STRICT if strict else schema.READ)
    cat = Catalog(str(data.get("catalog") or path.stem), str(data.get("title") or ""), path, engine,
                  str(data.get("source") or ""))
    errors, unknown = schema.validate(KIND, data, mode)
    cat.errors += [f"{path.name}: {e}" for e in errors]
    cat.notes += [f"{path.name}: {u} (kept: a newer brain's key?)" for u in unknown]
    if errors and any("written by brain >" in e for e in errors):
        return cat   # a higher v: its rows may mean something else
    for i, row in enumerate(data.get("rows") if isinstance(data.get("rows"), list) else []):
        where = f"{path.name}: rows[{i}]" + (f" {row.get('id')}" if isinstance(row, dict) and row.get("id") else "")
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row.get("statement"):
            continue   # its schema error says why
        cat.errors += row_errors(where, row, mode == schema.STRICT, cat.notes)
        cov = row.get("coverage")
        cat.rows.append(Row(row["id"], cat.name, str(row.get("domain") or ""), str(row["statement"]),
                            _strings(row.get("profiles")), str(row.get("stage") or ""),
                            str(row.get("enforcement") or ""), str(row.get("check") or ""),
                            _strings(row.get("languages")), str(row.get("status") or ""),
                            title=str(row.get("title") or ""), why=str(row.get("why") or ""),
                            adapter=str(row.get("adapter") or ""), coverage=dict(cov) if isinstance(cov, dict) else {},
                            source=str(row.get("source") or ""), refs=_strings(row.get("refs")),
                            file=path.as_posix()))
    return cat


def load_file(path: Path, engine: bool = False, strict: bool | None = None) -> Catalog:
    """The catalog in ``path``; :class:`StandardsError` when it cannot be read."""
    if not path.is_file():
        raise StandardsError(f"{path}: no such catalog")
    try:
        data = graph.load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise StandardsError(f"{path}: {exc}") from exc
    except Exception as exc:   # a YAML error, whichever loader parsed it
        raise StandardsError(f"{path}: not YAML ({type(exc).__name__})") from exc
    return parse(data, path, engine, strict)


def engine_catalogs(strict: bool | None = None, folder: Path | None = None) -> list[Catalog]:
    """The engine's own catalogs (``brain/catalogs/*.yaml``), by name."""
    folder = folder or ENGINE_DIR
    return [load_file(f, True, strict) for f in sorted(folder.glob("*.yaml"))] if folder.is_dir() else []


def selection(value) -> Selection | None:
    """A project's ``standards:`` value as a :class:`Selection`; None when it declares none (not concerned)."""
    if value is None:
        return None
    value = value if isinstance(value, dict) else {}
    exclude = value.get("exclude") if isinstance(value.get("exclude"), dict) else {}
    return Selection(_strings(value.get("profiles")), str(value.get("stage") or ""), _strings(value.get("include")),
                     {str(k): str(v) for k, v in exclude.items()}, _strings(value.get("catalogs")))


def local_catalogs(sel: Selection | None, registry_dir: Path | None,
                   strict: bool | None = None) -> tuple[list[Catalog], list[str]]:
    """(the local catalogs a selection names, the errors of those that cannot be read)."""
    out, errors = [], []
    for rel in (sel.catalogs if sel else []):
        if registry_dir is None:
            errors.append(f"standards catalog {rel}: no registry folder to read it from")
            continue
        try:
            out.append(load_file(registry_dir / rel, False, strict))
        except StandardsError as exc:
            errors.append(str(exc))
    return out, errors


def duplicates(catalogs: list[Catalog]) -> list[str]:
    """An id found twice, in one catalog or across them: an error (an id names one standard)."""
    seen: dict[str, str] = {}
    errors = []
    for cat in catalogs:
        for row in cat.rows:
            if row.id in seen:
                errors.append(f"standard {row.id}: in {seen[row.id]} and {cat.path.name} (an id names one standard)")
            else:
                seen[row.id] = cat.path.name
    return errors


def rows_of(catalogs: list[Catalog]) -> list[Row]:
    """Every row, the first of an id kept, in catalog then file order."""
    seen: set[str] = set()
    out = []
    for cat in catalogs:
        for row in cat.rows:
            if row.id not in seen:
                seen.add(row.id)
                out.append(row)
    return out


def selection_errors(where: str, value, ids: set[str] | None = None, strict: bool | None = None,
                     notes: list[str] | None = None) -> list[str]:
    """What a project's ``standards:`` breaks: not a mapping, an unknown key (a note in read mode), a profile or stage
    this engine does not know, an include or exclude that is not a list or mapping, an exclude without its reason;
    with ``ids`` (every id the catalogs hold), an include or exclude that names no standard."""
    where = f"{where}: standards"
    if not isinstance(value, dict):
        return [f"{where} is a mapping of {', '.join(SELECTION_KEYS)} (docs/standards.md)"]
    notes = notes if notes is not None else []
    errors = []
    unknown = sorted(set(map(str, value)) - set(SELECTION_KEYS))
    if unknown:
        errors += schema.tolerate(f"{where}: unknown key(s) {', '.join(unknown)} (known: {', '.join(SELECTION_KEYS)})",
                                  strict, notes)
    for key in ("profiles", "include", "catalogs"):
        if key in value and not (isinstance(value[key], list) and all(isinstance(v, str) and v for v in value[key])):
            errors.append(f"{where}: {key} is a list of names")
    for p in _strings(value.get("profiles")):
        errors += _vocab(where, "profile", p, PROFILES, strict, notes)
    if "stage" in value:
        if not isinstance(value["stage"], str):
            errors.append(f"{where}: stage is one of {', '.join(STAGES)}")
        else:
            errors += _vocab(where, "stage", value["stage"], STAGES, strict, notes)
    if (value.get("profiles") or value.get("stage")) and not (value.get("profiles") and value.get("stage")):
        errors.append(f"{where}: profiles and stage go together (a profile selects rows from a stage on)")
    exclude = value.get("exclude")
    if exclude is not None and not isinstance(exclude, dict):
        errors.append(f"{where}: exclude is a mapping of id -> reason")
    for sid, reason in (exclude if isinstance(exclude, dict) else {}).items():
        if not isinstance(reason, str) or len(reason.strip()) < REASON:
            errors.append(f"{where}: exclude {sid!r}: a reason of {REASON} characters at least")
    if ids is not None:
        named = _strings(value.get("include")) + [str(k) for k in (exclude if isinstance(exclude, dict) else {})]
        errors += [f"{where}: {sid!r} is no standard of the catalogs (brain standards list)" for sid in named
                   if sid not in ids]
    return errors


def applicable(rows: list[Row], sel: Selection | None) -> list[tuple[Row, str]]:
    """The rows a selection makes required, each with why: its profile and stage, or ``include``; ``exclude`` drops
    them. None (no standards: key): nothing."""
    if sel is None:
        return []
    at = STAGES.index(sel.stage) if sel.stage in STAGES else -1
    mine = set(sel.profiles)
    out = []
    for row in rows:
        if row.id in sel.exclude:
            continue
        meets = sorted(mine & set(row.profiles)) or (["any"] if "any" in row.profiles and mine else [])
        if meets and row.stage in STAGES and STAGES.index(row.stage) <= at:
            out.append((row, f"profile {', '.join(meets)}, from {row.stage}"))
        elif row.id in sel.include:
            out.append((row, "included"))
    return out


def gaps(chosen: list[tuple[Row, str]], langs: dict[str, str]) -> list[str]:
    """The applicable rows whose check does not cover a repo's language ({repo: lang}): a gap to report, never an
    error (the language adapters close them, wi-brain-lang-adapters)."""
    out = []
    for row, _ in chosen:
        missing = sorted(f"{name} ({lang})" for name, lang in langs.items() if not row.covers(lang))
        if missing:
            out.append(f"{row.id}: its check covers {', '.join(row.languages)}, not {', '.join(missing)}")
    return out


def counts(rows: list[Row]) -> dict[str, int]:
    """{enforcement level: how many rows}, in :data:`ENFORCEMENT`'s order then any other."""
    out: dict[str, int] = {}
    for key in list(ENFORCEMENT) + sorted({r.enforcement for r in rows} - set(ENFORCEMENT)):
        n = sum(1 for r in rows if r.enforcement == key)
        if n:
            out[key] = n
    return out


def for_project(p, strict: bool | None = None) -> tuple[list[Catalog], Selection | None, list[str]]:
    """(the engine's catalogs then the project's local ones, its selection, the errors of the local catalogs that
    cannot be read) of a :class:`brain.projects.Project`."""
    sel = selection(getattr(p, "standards", None))
    local, errors = local_catalogs(sel, getattr(p, "registry_dir", None), strict)
    return engine_catalogs(strict) + local, sel, errors


def invariants(p, limit: int = 60) -> list[str]:
    """The brief's lines (brain brief): the project's applicable standards, one each, by domain; [] when it declares
    none or its catalogs cannot be read (brain standards check says why)."""
    try:
        catalogs, sel, _ = for_project(p)
    except StandardsError:
        return []
    chosen = applicable(rows_of(catalogs), sel)
    if not chosen:
        return []
    chosen.sort(key=lambda rw: (rw[0].catalog, rw[0].domain, rw[0].id))
    lines = [f"- `{row.id}` ({row.domain}, {row.enforcement}{', proposed' if row.status != 'validated' else ''}): "
             f"{' '.join(row.statement.split())}" for row, _ in chosen[:limit]]
    if len(chosen) > limit:
        lines.append(f"- and {len(chosen) - limit} more: brain --project {p.name} standards list --applicable")
    return lines
