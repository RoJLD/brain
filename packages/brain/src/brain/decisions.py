"""The owner's decision queue: ``brain decision ask|answer|ack|archive|pending|view|announce``. The owner is
config.json's ``identity.owner`` (brain.config): the views name them and ``answer --by`` defaults to them.

An entry is a DDR (``records/ddr/<id>.yaml``) whose ``kind`` is ``decision``; the kinds ``action`` (what only the
owner may do) and ``permission`` (what the agent may do once the owner grants it) share the record and its lifecycle,
without options: ``brain queue add`` puts them, ``brain queue done`` answers them, and ``brain queue`` lists the three
kinds with what else waits on the owner (brain.queue). The lifecycle (rule "Decisions"):

  pending (asked, 2 to 4 options, the recommended one first, with its reason)
  -> answered (the owner's choice: one option, several when multi_select, or "other" with free text)
  -> integrated (the model in charge applied it: ADR, item props, spec; read and applied stamps)
  -> archived.

``pending`` lists what waits on the owner per project and for all registered projects: the queue's DDRs, and what
``research_graph pending`` reads in each store (items' ``props.open``, unanswered spec questions, items blocked on the
owner, specs still proposed). ``view`` writes the generated board ``notes/decision_queue.md``.
``announce`` (standard library only) is the SessionStart hook's line about answers not integrated yet; the hook then
sets the session's mark for the mid-session announcement (``brain.midsession``, UserPromptSubmit).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from . import actions, config, defaults, graph, midsession, records, selftime, sessions

KINDS = ("decision", "action", "permission")
VIEW = "notes/decision_queue.md"
_GRAPH_ID_RE = re.compile(r"^(adr|sdr|wi|ms|spec)-[a-z0-9-]+$")


class QueueError(Exception):
    pass


def _short(text, n: int = 100) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _day(stamp) -> str:
    return str((stamp or {}).get("at", ""))[:10]


def kind_of(ddr: dict) -> str:
    return ddr.get("kind") or "decision"


# --- ask, answer, ack, archive ---

def who(session: str = "", env=None) -> dict:
    """The ids a stamp carries (scale study gap 19): ``session`` (a transcript id, or an app ``local_`` id) else this
    session's own, read from its environment, both when known, with the machine an app id belongs to; {} outside a
    session and without ``session``."""
    me = sessions.here(env)
    if session.startswith("local_"):
        sid, host = (me["session"] if session == me["host_id"] else ""), session
    else:
        sid = session or me["session"]
        host = me["host_id"] if not session or session == me["session"] else ""
    out = {"session": sid} if sid else {}
    if host:
        out.update({"host_id": host, "machine": sessions.stamp({sessions.HOST_ENV: host}).get("machine", "")})
    return out


def _stamp(at: str, session: str) -> dict:
    w = who(session)
    return {"at": at, "session": w.pop("session", "") or "unknown", **w}


def parse_option(text: str) -> dict:
    """'label: consequences' or 'label:: consequences' (when the label has ': ' in it)."""
    label, _, consequences = text.partition("::")
    if not consequences and ": " in text:
        label, _, consequences = text.partition(": ")
    opt = {"label": label.strip()}
    if consequences.strip():
        opt["consequences"] = consequences.strip()
    return opt


def ask(root: Path, *, title: str, question: str, options: list[str], why: str, at: str, context: str = "",
        blocks: str = "", multi: bool = False, blocking: bool = False, due: str = "", recommend: str = "",
        items: list[str] | None = None, specs: list[str] | None = None, adrs: list[str] | None = None,
        project: str = "", session: str = "", slug: str = "", dry_run: bool = False,
        low_stakes: bool = False) -> tuple[dict, Path | None]:
    """Write a pending decision. Refused without 2 to 4 options, without the reason of the recommendation, or when
    the recommended option is not the first. ``low_stakes``: decided by default 24 h later without an answer
    (brain.defaults), refused on the topics a default never decides."""
    opts = [parse_option(o) for o in options or []]
    if not 2 <= len(opts) <= 4:
        raise QueueError(f"a decision needs 2 to 4 --option, the recommended one first (got {len(opts)})")
    if not (why or "").strip():
        raise QueueError("a decision needs --why: the reason of the recommendation (the first option)")
    if recommend and recommend != opts[0]["label"]:
        raise QueueError(f"the recommended option {recommend!r} must come first (first is {opts[0]['label']!r})")
    ddr = {"v": 1, "id": f"ddr-{at[:10]}-{actions.slug(slug or title, 48)}", "kind": "decision", "title": title,
           "question": question}
    for k, v in (("context", context), ("blocks", blocks)):
        if v:
            ddr[k] = v
    ddr.update({"options": opts, "recommendation": {"option": opts[0]["label"], "why": why.strip()},
                "multi_select": multi, "other_allowed": True, "blocking": blocking})
    if due:
        ddr["due"] = due
    ddr["status"] = "pending"
    w = who(session)
    ddr["asked"] = {"at": at, "by": w.pop("session", "") or "unknown", **w, "via": "cli"}
    links = {k: v for k, v in {"adrs": adrs, "items": items, "specs": specs}.items() if v}
    if project:
        links["project"] = project
    if links:
        ddr["links"] = links
    if low_stakes:
        try:
            defaults.mark(ddr)
        except ValueError as exc:
            raise QueueError(f"--low-stakes refused: {exc}") from exc
    if dry_run:
        return records.validate("ddr", ddr), None
    return ddr, records.write(root, "ddr", ddr)


def load(root: Path) -> list[tuple[Path, dict]]:
    return [(f, d) for f, d in records.load(root)["ddr"] if isinstance(d, dict)]


def find(root: Path, ref: str) -> tuple[Path, dict]:
    """A DDR by its id, else by a part of its id that only one DDR has."""
    entries = load(root)
    for f, d in entries:
        if d.get("id") == ref:
            return f, d
    hits = [(f, d) for f, d in entries if ref and ref in str(d.get("id", ""))]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise QueueError(f"{ref}: no DDR in {root / records.RECORDS_DIR / 'ddr'}")
    raise QueueError(f"{ref}: several DDRs match ({', '.join(d['id'] for _, d in hits)})")


def _choice(ddr: dict, text: str) -> str:
    """An option label from its label (any case), its number (1-based) or the start of its label."""
    labels = [o["label"] for o in ddr.get("options", [])]
    for lab in labels:
        if text == lab or text.lower() == lab.lower():
            return lab
    if text.isdigit() and 1 <= int(text) <= len(labels):
        return labels[int(text) - 1]
    starts = [lab for lab in labels if lab.lower().startswith(text.lower())]
    if len(starts) == 1:
        return starts[0]
    raise QueueError(f"{text!r} is not one of the options ({'; '.join(labels)}); free text goes in --other")


def answer(root: Path, ref: str, choices: list[str], *, other: str = "", notes: str = "", by: str = "",
           via: str = "cli", at: str, again: bool = False, check=None) -> dict:
    """Record an answer to the DDR ``ref``, by ``by`` (config.json's owner by default); ``check(ddr_id, choices,
    other)`` returns a refusal ('' when it may be recorded: brain.answers.refusal)."""
    by = by or config.owner_of()
    _, ddr = find(root, ref)
    if ddr.get("status") != "pending" and not again:
        raise QueueError(f"{ddr['id']} is {ddr.get('status')}, not pending (--again replaces the answer)")
    picked = [_choice(ddr, c) for c in choices or []]
    if not picked and not other:
        raise QueueError("an answer needs an option (label, number or start of its label) or --other TEXT")
    if len(picked) > 1 and not ddr.get("multi_select"):
        raise QueueError(f"{ddr['id']} takes one choice (it is not multi_select)")
    refused = check(ddr["id"], picked, other) if check else ""
    if refused:
        raise QueueError(refused)
    ans = {"at": at, "by": by, **who()}   # the session that recorded it, when there is one
    if picked:
        ans["choices"] = picked
    if other:
        ans["other"] = other
    if notes:
        ans["notes"] = notes
    ans["via"] = via
    ddr["answer"] = ans
    ddr["status"] = "answered"
    for k in ("read", "applied", "archived"):
        ddr.pop(k, None)
    records.write(root, "ddr", ddr, replace=True)
    return ddr


def ack(root: Path, ref: str, applied: list[str], *, session: str = "", at: str, archive: bool = True,
        store: Path | None = None) -> tuple[dict, list[str]]:
    """Mark an answer read and applied (where: ADR ids, item ids, spec sections), then archive it. Returns the DDR
    and the graph ids named that the store does not have (yet: an ADR before its sync, say)."""
    _, ddr = find(root, ref)
    if ddr.get("status") != "answered":
        raise QueueError(f"{ddr['id']} is {ddr.get('status')}: only an answered decision is acknowledged")
    if not applied:
        raise QueueError("ack needs --applied WHERE (an ADR id, an item id or a spec section), once per place")
    stamp = _stamp(at, session)
    ddr["read"] = ddr.get("read") or stamp
    ddr["applied"] = {**stamp, "in": list(applied)}
    links = ddr.setdefault("links", {})
    for where in applied:
        key = {"adr": "adrs", "sdr": "adrs", "wi": "items", "ms": "items", "spec": "specs"}.get(where.split("-")[0])
        if key and _GRAPH_ID_RE.match(where) and where not in links.get(key, []):
            links.setdefault(key, []).append(where)
    ddr["status"] = "integrated"
    if archive:
        ddr["archived"] = stamp
        ddr["status"] = "archived"
    records.write(root, "ddr", ddr, replace=True)
    known = set(graph.node_index(store)) if store and store.is_dir() else set()
    unknown = [w for w in applied if _GRAPH_ID_RE.match(w) and known and w not in known]
    return ddr, unknown


def archive(root: Path, refs: list[str], *, session: str = "", at: str) -> list[str]:
    """Archive integrated decisions: the ones named, else every integrated one."""
    targets = [find(root, r)[1] for r in refs] if refs else [d for _, d in load(root) if d.get("status") ==
                                                              "integrated"]
    done = []
    for ddr in targets:
        if ddr.get("status") != "integrated":
            raise QueueError(f"{ddr['id']} is {ddr.get('status')}: only an integrated decision is archived")
        ddr["archived"] = _stamp(at, session)
        ddr["status"] = "archived"
        records.write(root, "ddr", ddr, replace=True)
        done.append(ddr["id"])
    return done


# --- pending ---

def _entry(ddr: dict, today: date) -> dict:
    asked = _day(ddr.get("asked"))
    try:
        age = (today - date.fromisoformat(asked)).days
    except ValueError:
        age = None
    e = {"id": ddr["id"], "kind": kind_of(ddr), "status": ddr.get("status"), "title": ddr.get("title", ""),
         "question": ddr.get("question", ""), "asked": asked, "age_days": age,
         "blocking": bool(ddr.get("blocking")), "recommended": (ddr.get("recommendation") or {}).get("option"),
         "options": [o.get("label") for o in ddr.get("options", [])]}
    if ddr.get("due"):
        e["due"] = ddr["due"]
    if ddr.get("answer"):
        e["answer"] = ddr["answer"].get("choices") or []
        if ddr["answer"].get("other"):
            e["other"] = ddr["answer"]["other"]
    return e


def pending(project, kinds: tuple[str, ...] = KINDS, with_graph: bool = True, today: date | None = None) -> dict:
    """What waits on the owner (and on the model) in one project: its queue's DDRs, then each store's research_graph
    pending lists."""
    today = today or date.today()
    ddrs = [d for _, d in load(project.root) if kind_of(d) in kinds] if (project.root / "records").is_dir() else []
    out = {"project": project.name, "root": str(project.root), "owner": config.owner_of(),
           "pending": [_entry(d, today) for d in ddrs if d.get("status") == "pending"],
           "answered": [_entry(d, today) for d in ddrs if d.get("status") == "answered"],
           "integrated": [_entry(d, today) for d in ddrs if d.get("status") == "integrated"], "stores": []}
    out["pending"].sort(key=lambda e: (not e["blocking"], e["asked"], e["id"]))
    if with_graph and "decision" in kinds:
        for store in project.stores:
            if not (store / "schema.yaml").is_file():
                continue
            data = graph.research_graph_json(project.root, store, "pending")
            if isinstance(data, dict) and "blocked_on_robin" in data:  # the engine's key before research-graph 0.1.0
                data["blocked_on_owner"] = data.pop("blocked_on_robin")
            rel = store.relative_to(project.root).as_posix() if store.is_relative_to(project.root) else str(store)
            out["stores"].append({"store": rel, **(data if isinstance(data, dict) else {"error": "research_graph "
                                                                                          "pending did not run"})})
    out["waiting_on_owner"] = len(out["pending"]) + sum(
        len(s.get("open_questions", [])) + sum(len(x["questions"]) for x in s.get("spec_questions", []))
        + len(s.get("blocked_on_owner", [])) + len(s.get("proposed_specs", [])) for s in out["stores"])
    return out


def render_pending(data: dict, width: int = 118) -> list[str]:
    owner = data.get("owner") or config.NO_OWNER
    lines = [f"{data['project']} ({data['root']}): {data['waiting_on_owner']} waiting on {owner}, "
             f"{len(data['answered'])} answer(s) to integrate"]

    def add(head: str, rows: list[str]) -> None:
        if rows:
            lines.append(f"  {head} ({len(rows)})")
            lines.extend("    " + _short(r, width - 4) for r in rows)

    add("decisions to answer (records/ddr)", [
        f"{e['id']}{' [blocking]' if e['blocking'] else ''} {e['age_days']} d: {e['title']}"
        + (f" -> recommended: {e['recommended']}" if e["recommended"] else f" ({e['kind']}: brain queue done ID)")
        for e in data["pending"]])
    add("answered, to integrate (brain decision ack ID --applied WHERE)", [
        f"{e['id']}: {', '.join(e.get('answer', [])) or e.get('other', '')} ({e['title']})"
        for e in data["answered"]])
    add("integrated, to archive (brain decision archive)", [f"{e['id']}: {e['title']}" for e in data["integrated"]])
    for s in data["stores"]:
        tag = f" [{s['store']}]" if len(data["stores"]) > 1 else ""
        if s.get("error"):
            lines.append(f"  {s['store']}: {s['error']} (only the DDRs are listed)")
            continue
        add(f"open questions on items, props.open{tag}", [f"{q['id']}: {q['open']}" for q in s["open_questions"]])
        add(f"spec questions without an answer{tag}", [
            f"{x['id']} {q['label']}: {q['question']}" for x in s["spec_questions"] for q in x["questions"]])
        add(f"blocked on {s.get('owner') or owner}{tag}",
            [f"{b['id']}: {b['external_blocker']}" for b in s["blocked_on_owner"]])
        add(f"specs still proposed{tag}", [f"{p['id']} ({p['age_days']} d): {p['title']}" for p in
                                           s["proposed_specs"]])
    return lines


# --- generated view ---

def view(root: Path, name: str) -> str:
    """The queue as a board (``notes/decision_queue.md``): what waits on the owner with its options, what waits on the
    model, what is archived. Dates only (no ages), so it changes only when the records do."""
    ddrs = sorted((d for _, d in load(root)), key=lambda d: (_day(d.get("asked")), d["id"]))
    by = {s: [d for d in ddrs if d.get("status") == s] for s in ("pending", "answered", "integrated", "archived")}
    out = [f"# Decision queue — {name}", "",
           "GENERATED by `brain decision view --write` (and `brain sync`) from `records/ddr/`. Do not edit: ask,",
           "answer and acknowledge with `brain decision ask|answer|ack`. The items' open questions (`props.open`)",
           "and the unanswered spec questions are listed by `brain decision pending`.", ""]
    out += [f"## Waiting on {config.name_of()} ({len(by['pending'])})", ""]
    for d in sorted(by["pending"], key=lambda d: (not d.get("blocking"), _day(d.get("asked")), d["id"])):
        meta = [f"asked {_day(d.get('asked'))}", kind_of(d)]
        if d.get("blocking"):
            meta.append("**blocking**")
        if d.get("due"):
            meta.append(f"due {d['due']}")
        if d.get("multi_select"):
            meta.append("several choices possible")
        out += [f"### {d['title']}", "", f"`{d['id']}` — {', '.join(meta)}", "", " ".join(d["question"].split())]
        if d.get("context"):
            out += ["", f"Context: {' '.join(d['context'].split())}"]
        if d.get("blocks"):
            out += ["", f"Blocks: {' '.join(d['blocks'].split())}"]
        out.append("")
        if kind_of(d) != "decision":  # an action or a permission: no options, the owner does it or grants it
            what = "do it" if kind_of(d) == "action" else "grant a narrow allow rule, or do it once"
            out += [f"Done: {what}, then `brain queue done {d['id']}`", ""]
            continue
        for i, o in enumerate(d.get("options", [])):
            rec = " (recommended)" if i == 0 and (d.get("recommendation") or {}).get("option") else ""
            cons = f": {' '.join(o['consequences'].split())}" if o.get("consequences") else ""
            out.append(f"- [ ] **{o['label']}**{rec}{cons}")
        out.append("- [ ] Other: free text")
        why = (d.get("recommendation") or {}).get("why")
        if why:
            out += ["", f"Why the recommendation: {' '.join(why.split())}"]
        out += ["", f"Answer: `brain decision answer {d['id']} <option>` (or `--other \"...\"`)", ""]
    out += [f"## Answered, to integrate ({len(by['answered'])})", ""]
    out += [f"- `{d['id']}` {d['title']}: **{_answer_text(d)}** ({_day(d.get('answer'))}); then "
            f"`brain decision ack {d['id']} --applied <ADR, item or spec>`" for d in by["answered"]]
    out += ([""] if by["answered"] else []) + [f"## Integrated, to archive ({len(by['integrated'])})", ""]
    out += [f"- `{d['id']}` {d['title']}: {_answer_text(d)}; applied in {', '.join(d['applied'].get('in', []))}"
            for d in by["integrated"]]
    out += ([""] if by["integrated"] else []) + [f"## Archived ({len(by['archived'])})", ""]
    if by["archived"]:
        out += ["| DDR | Question | Answer | Applied in | Archived |", "|---|---|---|---|---|"]
        out += [f"| `{d['id']}` | {_cell(d['title'])} | {_cell(_answer_text(d))} | "
                f"{_cell(', '.join(d['applied'].get('in', [])))} | {_day(d.get('archived'))} |"
                for d in reversed(by["archived"])]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _answer_text(d: dict) -> str:
    a = d.get("answer") or {}
    parts = list(a.get("choices") or [])
    if a.get("other"):
        parts.append(f"other: {' '.join(a['other'].split())}")
    return "; ".join(parts) or "?"


def _cell(text: str) -> str:
    return _short(text, 120).replace("|", "\\|")


def write_view(root: Path, name: str) -> Path:
    f = root / VIEW
    f.write_text(view(root, name), encoding="utf-8", newline="\n")
    return f


def view_stale(root: Path, name: str) -> bool:
    f = root / VIEW
    return f.is_file() and f.read_text(encoding="utf-8") != view(root, name)


# --- the SessionStart announcement (standard library only) ---

def _scalar(v: str) -> str:
    v = v.strip()
    if v[:1] == "'" and v[-1:] == "'":
        return v[1:-1].replace("''", "'")
    if v[:1] == '"':
        try:
            return json.loads(v)
        except ValueError:
            return v.strip('"')
    return v


def _top(text: str) -> dict:
    """id, title, status, who asked (``asked_by``) and the answer's choices of a DDR file, read line by line (no YAML
    parser in a hook)."""
    out: dict = {"choices": []}
    key = sub = ""
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace() and not line.startswith("- "):
            key, _, v = line.partition(":")
            sub = ""
            if key in ("id", "title", "status", "kind"):
                out[key] = _scalar(v)
        elif key == "asked" and line.strip().startswith("by:"):
            out["asked_by"] = _scalar(line.strip()[3:])
        elif key == "answer":
            s = line.strip()
            if s.startswith("- ") and sub == "choices":
                out["choices"].append(_scalar(s[2:]))
            elif ":" in s:
                sub, _, v = s.partition(":")
                if sub in ("other", "via") and v.strip():
                    out[sub] = _scalar(v)
    return out


def announce(cwd: str | Path) -> str:
    """One line per decision the owner answered that the project at ``cwd`` has not integrated yet; '' when none. The
    queue read is the project's main checkout's (a worktree's copy lags it), the one the mid-session hook watches."""
    queue = midsession.queue_dir(cwd)
    if queue is None:
        return ""
    root = queue.parents[1]
    rows = []
    for f in sorted(queue.glob("*.yaml")):
        try:
            top = _top(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if top.get("status") == "answered":
            choice = "; ".join(top["choices"]) or (f"other: {top['other']}" if top.get("other") else "answered")
            tag = " (by default: brain decision defaulted)" if top.get("via") == "default" else ""
            rows.append(f"- {top.get('id', f.stem)}: {_short(choice, 80)}{tag} ({_short(top.get('title', ''), 80)})")
    if not rows:
        return ""
    return (f"{config.name_of()} answered {len(rows)} decision(s) that {root.name} has not integrated yet. Apply "
            "each answer "
            "(ADR, item props, spec), then `brain decision ack <id> --applied <where>`; the queue: "
            "`brain decision pending`.\n" + "\n".join(rows))


def hook_main(argv: list[str], stdin=None) -> int:
    """SessionStart hook: the hook JSON on stdin, the announcement as additionalContext on stdout, then the session's
    mark for the mid-session announcement (brain.midsession). Never fails."""
    data: dict = {}
    try:
        data = midsession.read_payload(stdin)
        text = announce(data.get("cwd") or ".")
        if text:
            event = argv[0] if argv else "SessionStart"
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
                             ensure_ascii=True))
    except Exception as exc:  # noqa: BLE001 - a hook never breaks a session start
        selftime.error(exc)
    try:
        if data.get("session_id"):
            midsession.baseline(data)
    except Exception as exc:  # noqa: BLE001
        selftime.error(exc)
    return 0
