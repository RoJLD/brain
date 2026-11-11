"""Zero-token capture, run by the brain's hooks: ``capture.py <event> [git|gh]`` with the hook's JSON on stdin.

It writes the machine-local ledger under $BRAIN_HOME (default ~/.brain), never the repo, never the network, never
stdout (a SessionStart hook's stdout would enter Claude's context). It always exits 0: a failure goes to
``ledger/errors.log`` and the session goes on. ``BRAIN_CAPTURE=0`` turns it off.

Events (hook payload fields checked against the Claude Code hooks reference, 2026-10-30):
- ``session-start`` (SessionStart: session_id, transcript_path, cwd, source, model when present): one event line,
  with the app's ``local_`` id (CLAUDE_CODE_HOST_SESSION_ID) and the parent, task and short name of the session's own
  app metadata file (brain.sessions: a closed list of keys);
- ``post-tool-use git|gh`` (PostToolUse on Bash or PowerShell: tool_input.command, tool_response.stdout / stderr /
  gitOperation, tool_use_id, cwd, permission_mode, effort.level): ARs for commits, pushes, tags, PRs and the ADRs
  a commit added; the model and version come from the transcript's last assistant record;
- ``post-tool-use`` on AskUserQuestion (tool_input.questions, tool_response.answers): one DDR per question, answered
  and read by the asking session, plus its AR;
- ``post-tool-use`` on a plan tool (``brain.plan.PLAN_TOOLS``: the desktop app's update_plan and wrap_up, TodoWrite;
  tool_input): the session's plan, ``sessions/<session_id>.plan.json``, its steps n/m for the cockpit;
- ``stop`` (Stop): the session's SR snapshot, ``sessions/<session_id>.json``, updated incrementally, with its place
  in the session tree (host_id, name, parent, children, role); and its end-of-turn report,
  ``sessions/<session_id>.report.json`` (brain.sessions.build_report: PRs, head, items, DDRs, what it waits on, what
  comes next, the recap), which brain sessions tree reads;
- ``session-end`` (SessionEnd: reason; 1.5 s budget): one event line.

Each payload is first compared with its event's keys (:data:`PAYLOAD_KEYS`), and the Stop hook's transcript records
with what brain.transcript reads: what differs is counted in ``ledger/contracts.json``, never refused
(wi-brain-external-contracts, docs/formats.md « External formats »).
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import actions, midsession, paths, plan, schema, secretscan, transcript
from . import answers as answers_lane

SR_V = 1     # sessions/<id>.json (schemas/sr.schema.json)
STATS_V = 1  # sessions/<id>.state.json, the transcript's offsets and counts (brain.transcript.SessionStats)


def _now() -> str:
    return transcript.iso(datetime.now(timezone.utc))


def _append(name: str, record: dict) -> None:
    d = paths.ledger_dir()
    d.mkdir(parents=True, exist_ok=True)
    month = (record.get("at") or _now())[:7]
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(d / f"{name}-{month}.jsonl", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)


def _recent_ids(name: str, n: int = 400) -> set[str]:
    f = paths.ledger_dir() / f"{name}-{_now()[:7]}.jsonl"
    if not f.exists():
        return set()
    try:
        tail = f.read_bytes()[-200_000:].decode("utf-8", "replace").splitlines()[-n:]
    except OSError:
        return set()
    ids = set()
    for line in tail:
        m = re.search(r'"id":"([^"]+)"', line)
        if m:
            ids.add(m.group(1))
    return ids


def _log_error(event: str, exc: BaseException) -> None:
    """The engine's error sink: a text line in ledger/errors.log (secrets dropped), and the error event of the
    engine's self-timing (its class and module:function, never its message: brain.selftime). The log of an earlier
    month, or one past 1 MB, moves aside first as errors-YYYY-MM.log, kept stateio.LOG_RETENTION["errors"] months."""
    from . import selftime

    selftime.error(exc)
    _log_line(event, "".join(traceback.format_exception_only(type(exc), exc)).strip())


def _log_line(event: str, text: str) -> None:
    """One line in ledger/errors.log (secrets dropped), the log rotated first (:func:`_log_error`)."""
    from . import stateio

    try:
        d = paths.ledger_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / "errors.log"
        stateio.rotate_log(f, keep=stateio.LOG_RETENTION["errors"])
        text, _ = secretscan.clean_text(text)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{_now()} {event}: {text}\n")
    except OSError:
        pass


# --- the external contracts (wi-brain-external-contracts, docs/formats.md « External formats ») ----------------------
# Claude Code's hook payloads: the keys every event may carry, then per capture event (required: what capture reads;
# known: the rest of the hooks reference's), checked against tests/fixtures/claude/hooks/. A key outside them, a
# required one missing, and what brain.transcript.SessionStats.contract counts in a transcript are counted in
# <BRAIN_HOME>/ledger/contracts.json; a first sighting is logged to errors.log and named once by the next SessionStart
# health (contract_notes). Nothing is refused: the readers keep their defaults.
# (Seen in Claude Code 2.1.321's payload builders, 2026-11-11.)
PAYLOAD_COMMON = frozenset({"session_id", "transcript_path", "cwd", "permission_mode", "hook_event_name", "agent_id",
                            "agent_type", "effort", "prompt_id", "scratchpad_dir"})
PAYLOAD_KEYS = {
    "session-start": (frozenset({"session_id", "source"}), frozenset({"model", "session_title"})),
    "session-end": (frozenset({"session_id", "reason"}), frozenset()),
    "stop": (frozenset({"session_id", "transcript_path"}),
             frozenset({"stop_hook_active", "last_assistant_message", "background_tasks", "session_crons"})),
    "post-tool-use": (frozenset({"session_id", "tool_name", "tool_input", "tool_response"}),
                      frozenset({"tool_use_id", "duration_ms", "mcp_server"})),
}
CONTRACTS = "contracts.json"   # under ledger/: {"v": 1, "keys": {"<source>: <what>": {count, first, last, shown}}}
CONTRACTS_V = 1
COUNT_EVERY_S = 3600   # a key already counted is counted again at most once an hour: no write per tool call


def payload_contract(event: str, payload: dict) -> list[str]:
    """What ``payload`` breaks of its event's keys: ``unknown K``, ``missing K`` (none for an event not listed)."""
    if event not in PAYLOAD_KEYS:
        return []
    required, known = PAYLOAD_KEYS[event]
    return [f"unknown {k}" for k in sorted(set(payload) - PAYLOAD_COMMON - required - known)] + \
        [f"missing {k}" for k in sorted(required - set(payload))]


def _load_contracts(f: Path) -> dict | None:
    """The ledger's data; {} when absent or unreadable; None when a newer brain wrote it (left as it is)."""
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    v = data.get("v")
    return None if isinstance(v, int) and not isinstance(v, bool) and v > CONTRACTS_V else data


def _save_contracts(f: Path, data: dict) -> bool:
    """An atomic write; False when it failed (another process replacing or reading it on Windows): a count lost is
    acceptable, a capture stopped is not."""
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, f)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def note_contract(source: str, breaks) -> list[str]:
    """Count each of ``breaks`` (``unknown K``, ``missing K``, with a count: a Counter) under ``source`` in the contracts
    ledger; a first sighting goes to errors.log too. A key already counted is counted again at most once every
    :data:`COUNT_EVERY_S` (``count`` is then the sightings that were written). Returns the first sightings."""
    counts = breaks if isinstance(breaks, dict) else {b: 1 for b in breaks}
    if not counts:
        return []
    f = paths.ledger_dir() / CONTRACTS
    data = _load_contracts(f)
    if data is None:
        return []
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    now, new, due = _now(), [], False
    for what, n in counts.items():
        k = f"{source}: {what}"
        entry = keys.get(k) if isinstance(keys.get(k), dict) else None
        if entry is None:
            entry = {"count": 0, "first": now, "shown": False}
            new.append(k)
        else:
            last = transcript.parse_ts(entry.get("last") if isinstance(entry.get("last"), str) else None)
            if last and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last and (datetime.now(timezone.utc) - last).total_seconds() < COUNT_EVERY_S:
                continue
        entry["count"] = _int(entry.get("count")) + _int(n)
        entry["last"] = now
        keys[k] = entry
        due = True
    if not due:
        return []
    f.parent.mkdir(parents=True, exist_ok=True)
    if not _save_contracts(f, {**data, "v": CONTRACTS_V, "keys": keys}):
        return []
    for k in new:
        _log_line("contract", f"Claude Code's format changed: {k} (counted in ledger/{CONTRACTS})")
    return new


def contract_notes(limit: int = 8) -> list[str]:
    """The SessionStart health's line on what the contracts ledger counted and has not shown yet; marks it shown."""
    f = paths.ledger_dir() / CONTRACTS
    data = _load_contracts(f)
    keys = (data or {}).get("keys")
    if not isinstance(keys, dict):
        return []
    fresh = [k for k, e in keys.items() if isinstance(e, dict) and not e.get("shown")]
    if not fresh:
        return []
    for k in fresh:
        keys[k]["shown"] = True
    _save_contracts(f, data)
    names = ", ".join(f"{k} ({keys[k].get('count', 0)}x)" for k in fresh[:limit])
    more = f" and {len(fresh) - limit} more" if len(fresh) > limit else ""
    return [f"Claude Code's hook payloads or transcripts no longer match what brain reads: {names}{more}. Nothing "
            f"is refused (the readers keep their defaults), but usage, costs or captures may be off until brain "
            f"knows them: brain update, else report it (ledger/{CONTRACTS} keeps the counts)."]


def _meta(payload: dict) -> dict:
    meta = {"session_id": payload.get("session_id"), "tool": "claude-code",
            "permission_mode": payload.get("permission_mode"), "agent": payload.get("agent_type")}
    effort = payload.get("effort")
    if isinstance(effort, dict) and effort.get("level"):
        meta["effort"] = effort["level"]
    tail = transcript.last_assistant(payload["transcript_path"]) if payload.get("transcript_path") else {}
    for k in ("model", "version", "surface"):
        if tail.get(k):
            meta[k] = tail[k]
    if not meta.get("effort") and tail.get("effort"):
        meta["effort"] = tail["effort"]
    return meta


def _write_ars(ars: list[dict]) -> int:
    seen = _recent_ids("ar")
    n = 0
    for ar in ars:
        if ar["id"] in seen:
            continue
        errors, _ = schema.check("ar", ar)
        if errors:
            raise ValueError(f"invalid AR {ar['id']}: {errors[:3]}")
        _append("ar", ar)
        seen.add(ar["id"])
        n += 1
    return n


def session_start(payload: dict) -> None:
    """Its event, with both ids (ST-1): the app's ``local_`` id from the environment, and the parent, task and short
    name its own app metadata file holds (brain.sessions: a closed list of keys, that file only)."""
    from . import sessions

    host = sessions.host_for(str(payload.get("session_id") or ""))  # not one a nested CLI inherited
    app = sessions.app_meta(host) if host else {}
    event = {"at": _now(), "event": "session_start", "session_id": payload.get("session_id"),
             "host_id": host, "parent": app.get("parent"), "task": app.get("task"), "name": app.get("name"),
             "source": payload.get("source"), "model": payload.get("model"), "cwd": payload.get("cwd"),
             "permission_mode": payload.get("permission_mode"), "agent": payload.get("agent_type"),
             "transcript": paths.relative_transcript(payload["transcript_path"]) if payload.get("transcript_path") else None}
    _append("events", secretscan.clean({k: v for k, v in event.items() if v})[0])


def session_end(payload: dict) -> None:
    event = {"at": _now(), "event": "session_end", "session_id": payload.get("session_id"),
             "reason": payload.get("reason")}
    _append("events", {k: v for k, v in event.items() if v})


def _ask_question(payload: dict) -> None:
    questions = (payload.get("tool_input") or {}).get("questions") or []
    response = payload.get("tool_response") or {}
    answers = response.get("answers") or {} if isinstance(response, dict) else {}
    annotations = response.get("annotations") or {} if isinstance(response, dict) else {}
    answers = answers if isinstance(answers, dict) else {}   # another shape: no answer rather than a lost call
    annotations = annotations if isinstance(annotations, dict) else {}
    meta = _meta(payload)
    now = _now()
    tuid = payload.get("tool_use_id") or ""
    seen = _recent_ids("ddr")
    asked = answers_lane.read(answers_lane.ASKED)
    for i, q in enumerate(questions):
        if not isinstance(q, dict) or not q.get("question"):
            continue
        notes = (annotations.get(q["question"]) or {}).get("notes") \
            if isinstance(annotations.get(q["question"]), dict) else None
        tied = answers_lane.capture(q, answers.get(q["question"]), notes, at=now, tool_use_id=tuid, index=i,
                                    session=meta.get("session_id") or "", asked=asked)
        if tied is not None:  # a question brain decision batch printed: its answer goes to its own DDR
            if tied:
                _write_ars([actions.make_ar("ddr", tied["id"], now, meta, "hook", tuid, ddr=tied["ddr"])])
            continue
        ddr = ddr_from_question(q, answers.get(q["question"]), now, meta, tuid, i, notes=notes)
        if ddr["id"] in seen:
            continue
        errors, _ = schema.check("ddr", ddr)
        if errors:
            raise ValueError(f"invalid DDR {ddr['id']}: {errors[:3]}")
        _append("ddr", ddr)
        _write_ars([actions.make_ar("ddr", ddr["id"][15:], now, meta, "hook", tuid, ddr=ddr["id"])])


def _ids(meta: dict) -> dict:
    """The app's id of the session the hook runs in (and its machine), when it is the payload's session."""
    from . import sessions

    me = sessions.here()
    if not me["host_id"] or me["session"] not in ("", meta.get("session_id")):
        return {}
    return sessions.stamp(session=meta.get("session_id") or "")


def _asker(meta: dict, tool_use_id: str = "") -> str:
    """asked.by, never unknown (wi-brain-identity): the hook's session, else the app id of the session it runs in,
    else the question tool's call."""
    from . import sessions
    return (meta.get("session_id") or sessions.here()["host_id"]
            or (f"tool-use:{tool_use_id}" if tool_use_id else "ask-tool"))


def ddr_from_question(q: dict, answer: str | list | None, at: str, meta: dict, tool_use_id: str = "", index: int = 0,
                      notes: str | None = None) -> dict:
    """A DDR from one question of Claude Code's question tool, and its answer when there is one. The tool returns a
    multiple choice as a list of labels (or, in a transcript, joined by ', '); a question the owner did not answer
    (the tool's placeholder when they sent a message instead) leaves the DDR pending, as an empty answer does."""
    options = []
    recommended = None
    for o in q.get("options") or []:
        if not isinstance(o, dict) or not o.get("label"):
            continue
        label = o["label"]
        if answers_lane.MARK_RE.search(label):  # (Recommended), (Recommandé)
            label = answers_lane.MARK_RE.sub("", label)
            recommended = recommended or label
        opt = {"label": label}
        if o.get("description"):
            opt["consequences"] = o["description"]
        options.append(opt)
    if recommended:  # the recommended option first, as rule R1 wants
        options.sort(key=lambda o: o["label"] != recommended)
    header = q.get("header") or q["question"][:60]
    suffix = actions.slug(f"{tool_use_id[-6:]}-{index}" if tool_use_id else str(index), 12)
    ddr: dict = {
        "v": 1,
        "id": f"ddr-{at[:10]}-{actions.slug(header, 40)}-{suffix}",
        "title": header[:100],
        "question": q["question"],
        "options": options[:4],
        "recommendation": {"option": recommended, "why": "" if recommended else "not given"},
        "multi_select": bool(q.get("multiSelect")),
        "other_allowed": True,
        "status": "pending",
        "asked": {"at": at, "by": _asker(meta, tool_use_id), **_ids(meta), "via": "ask-tool"},
    }
    if meta.get("model"):
        ddr["asked"]["model"] = meta["model"]
    if not answers_lane.unanswered(answer):
        labels = [o["label"] for o in ddr["options"]]
        if isinstance(answer, (list, tuple)):   # the tool's shape for a multiple choice: one label per item
            items = [str(a) for a in answer if not answers_lane.unanswered(a)]
            picked = [answers_lane.MARK_RE.sub("", a) for a in items]
            choices = [lab for lab in labels if lab in picked]
            rest = [a for a, p in zip(items, picked, strict=True) if p not in labels]
            text = ", ".join(items)
        else:   # a string: one label, or (a multiple choice) the labels joined with ", ", longest label first
            text = str(answer)
            norm = re.sub(r"\s*\((?:recommandée?|recommended)\)", "", text, flags=re.I)
            if norm in labels or not ddr["multi_select"]:   # a single choice is a label exactly, else the owner's text
                choices, rest = [norm] if norm in labels else [], [] if norm in labels else [text]
            else:
                choices, rest = _split_labels(norm, labels)
        ans: dict = {"at": at, "by": "user", "via": "ask-tool"}
        if choices:
            ans["choices"] = choices if ddr["multi_select"] else choices[:1]
        if rest or not choices:
            ans["other"] = ", ".join(rest) or text
        if notes:
            ans["notes"] = notes
        ddr["answer"] = ans
        ddr["status"] = "answered"
        ddr["read"] = {"at": at, "session": meta.get("session_id") or "unknown", **_ids(meta)}
    return secretscan.clean(ddr)[0]


def _split_labels(text: str, labels: list[str]) -> tuple[list[str], list[str]]:
    """(the labels, the rest) of a multiple choice joined with ", ": the longest label that matches at each place
    (a label may hold ", ")."""
    tokens, picked, rest, i = text.split(", "), [], [], 0
    while i < len(tokens):
        for j in range(len(tokens), i, -1):
            if ", ".join(tokens[i:j]) in labels:
                picked.append(", ".join(tokens[i:j]))
                i = j
                break
        else:
            rest.append(tokens[i])
            i += 1
    return [lab for lab in labels if lab in picked], ([", ".join(rest)] if rest else [])


def post_tool_use(payload: dict, family: str = "") -> None:
    tool = payload.get("tool_name")
    if tool == "AskUserQuestion":
        _ask_question(payload)
        return
    if tool in plan.PLAN_TOOLS:
        plan.capture(payload, _now())
        return
    if tool not in ("Bash", "PowerShell"):
        return
    command = (payload.get("tool_input") or {}).get("command") or ""
    ars = actions.from_tool_call(command, payload.get("cwd") or ".", payload.get("tool_response"), _meta(payload),
                                 tool_use_id=payload.get("tool_use_id") or "", source="hook", family=family)
    _write_ars(ars)


def stop(payload: dict) -> None:
    sid, path = payload.get("session_id"), payload.get("transcript_path")
    if not sid or not path or not Path(path).exists():
        return
    from . import stateio

    d = paths.sessions_dir()
    # both truth-local (brain.stateio): a newer brain's is its own (nothing written), an unreadable one set aside
    srs, sst = stateio.load(d / f"{sid}.json", known=SR_V), stateio.load(d / f"{sid}.state.json", known=STATS_V)
    if not (srs.writable and sst.writable):
        return
    stats = transcript.SessionStats.from_state(sst.data) if sst.status == "ok" else transcript.SessionStats()
    if stats.offset > Path(path).stat().st_size:  # the file was rewritten: start over
        stats = transcript.SessionStats()
    stats.feed_file(path)
    if stats.contract:
        try:
            note_contract("transcript", stats.contract)
        except Exception as exc:  # noqa: BLE001 - the count never costs the turn its snapshot
            _log_error("stop contract", exc)
    ar_ids, ddr_ids = _session_ids("ar", sid), _session_ids("ddr", sid)
    sr = stats.record(path, status="open", actions=ar_ids, ddrs=ddr_ids)
    tree = _tree_fields(sid)
    sr.update(tree)
    try:
        stateio.save(srs, sr, indent=1, sort_keys=False)
        stateio.save(sst, stats.to_state(), indent=None, sort_keys=False)
    except stateio.StateError:   # a newer brain wrote one since the load: its own
        return
    _child_report(sid, Path(path), sr, tree)


def _tree_fields(sid: str) -> dict:
    """The SR's place in the session tree (wi-brain-session-tree): host_id, name, parent, children (the app's ids of
    the sessions it started, from the app's files and the ledger) and role; {} without the app's id."""
    from . import sessions

    host = sessions.host_for(sid)  # not one a nested CLI inherited
    if not host:
        return {}
    tree = sessions.Tree(sessions.app_index(), sessions.ledger_events()[0])
    key = tree.key_of(host) or tree.key_of(sid)
    node = tree.nodes.get(key) or {}
    out = {"host_id": host, "role": tree.role(key) if key else "solo"}
    for k in ("name", "parent"):
        if node.get(k):
            out[k] = node[k]
    kids = [tree.nodes[k].get("host_id") or tree.nodes[k].get("session") for k in tree.children.get(key, [])]
    if kids:
        out["children"] = kids
    return out


def _child_report(sid: str, path: Path, sr: dict, tree: dict) -> None:
    """The child's end-of-turn report (wi-brain-child-report): written for every session, read by brain sessions
    tree; never fails the snapshot."""
    from . import cockpit, sessions

    try:
        records = cockpit.tail(path)
        hook = plan.read(sid)
        steps = (hook or {}).get("steps") or []
        head = actions.git(sr["folder"], "rev-parse", "--short", "HEAD") if sr.get("folder") else ""
        rep = sessions.build_report(sid, records, sr, tree, steps, _pending_ddrs(sid), head, _now(),
                                    brief_items=sessions.watch_state(sid).get("items"))
        sessions.write_report(sid, rep)
    except (OSError, ValueError) as exc:
        _log_error("child-report", exc)


def _pending_ddrs(sid: str) -> list[str]:
    """The ledger's DDRs this session asked that are still pending (the last record of each id wins)."""
    last = {}
    for rec in answers_lane.read("ddr"):
        if (rec.get("asked") or {}).get("by") == sid and rec.get("id"):
            last[rec["id"]] = rec.get("status")
    return [i for i, s in last.items() if s == "pending"]


def _session_ids(name: str, sid: str) -> list[str]:
    out = []
    for f in sorted(paths.ledger_dir().glob(f"{name}-*.jsonl"))[-2:]:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if sid in line:
                    rec = json.loads(line)
                    owner = (rec.get("session") or {}).get("id") or (rec.get("asked") or {}).get("by")
                    if owner == sid:
                        out.append(rec["id"])
        except (OSError, ValueError):
            continue
    return out


HANDLERS = {"session-start": session_start, "session-end": session_end, "stop": stop}


def main(argv: list[str] | None = None, stdin=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get("BRAIN_CAPTURE", "1") == "0" or not argv:
        return 0
    event = argv[0]
    try:
        payload = midsession.read_payload(stdin)   # UTF-8 bytes, whatever the console's codepage
        try:
            note_contract(f"hook {event}", payload_contract(event, payload))
        except Exception as exc:  # noqa: BLE001 - the count never stops the capture
            _log_error(f"{event} contract", exc)
        if event == "post-tool-use":
            post_tool_use(payload, argv[1] if len(argv) > 1 else "")
        elif event in HANDLERS:
            HANDLERS[event](payload)
    except Exception as exc:  # never break the session
        _log_error(event, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
