"""wi-brain-session-provenance (spec-brain-multi-agent-connector § 9, MA-5): where a session ran, computed when a
report is built: brain usage and brain status break the cost down by provider, harness (the record's tool) and an
account alias with its plan (config.json usage.accounts), never an e-mail address nor an account id
(brain.provenance, brain.cost). The session record is unchanged: its fields come with wi-brain-sr-provenance-fields."""

import io
import json

import pytest

from brain import capture, cli, config, cost, projects, provenance, records, schema, status, usage

ADDRESS = "ada" + "@" + "example.org"   # an e-mail-shaped value (never a real one)
DOTLESS = "ada" + "@" + "corp"           # an address without a dot
UUID = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
ACCOUNTS = [{"alias": "solo", "plan": "Pro"},
            {"alias": "main", "plan": "Max", "since": "2026-11-05"},
            {"alias": "ide", "plan": "Team", "since": "2026-11-01", "harness": "cursor", "provider": "anthropic"}]


@pytest.fixture
def ada_config(tmp_path, monkeypatch):
    """Ada's config.json with her accounts (config.json usage.accounts); BRAIN_CONFIG points at it."""
    base = json.loads(open(config.config_file(), encoding="utf-8").read())
    base["usage"] = {"accounts": ACCOUNTS}
    f = tmp_path / "ada" / "config.json"
    f.parent.mkdir()
    f.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    return f


# --- the values ---

@pytest.mark.parametrize("model, provider", [
    ("claude-opus-5-5", "anthropic"),
    ("us.anthropic.claude-sonnet-5-5-v1:0", "bedrock"),
    ("anthropic.claude-haiku-5-5-v1:0", "bedrock"),
    ("global.anthropic.claude-opus-5-5-v1:0", "bedrock"),
    ("us-gov.anthropic.claude-sonnet-5-5-v1:0", "bedrock"),
    ("apac.anthropic.claude-sonnet-5-5-v1:0", "bedrock"),
    ("arn:aws:bedrock:us-east-1:123:inference-profile/x", "bedrock"),
    ("claude-opus-5-5@20261101", "vertex"),
    ("<synthetic>", ""), ("", ""), (None, ""), ("gpt-9", ""),
])
def test_the_provider_a_model_id_implies(model, provider):
    assert provenance.provider_from_model(model) == provider


def test_harness_takes_over_tool_read_as_its_fallback():
    assert provenance.harness_of({"harness": "cursor", "tool": "claude-code"}) == "cursor"
    assert provenance.harness_of({"tool": "claude-code"}) == "claude-code"   # an old record
    assert provenance.harness_of({}) == "claude-code"                         # a ledger row (Claude Code's reader)
    assert provenance.harness_of({"harness": "Not An Id!"}) == "claude-code"


def test_an_alias_is_never_an_email_address_nor_an_account_id():
    assert provenance.safe_alias("main") == "main" and provenance.safe_alias("team-2.b_x") == "team-2.b_x"
    for bad in (ADDRESS, DOTLESS, UUID, UUID.replace("-", ""), "a-" + UUID, "x" + UUID.replace("-", ""),
                "work\n", "work\r\n", "", " main", "a b", "x" * 41, None, 3):
        assert provenance.safe_alias(bad) == "", bad
    assert provenance._plan("Max 20x") == "Max 20x"
    for bad in (UUID, "plan " + UUID.replace("-", ""), "Max " + DOTLESS):
        assert provenance._plan(bad) == "", bad


def test_the_account_in_force_on_a_day_of_its_harness():
    bad_days = [{"alias": "late", "since": "2026-11-05T23:00"}, {"alias": "empty", "since": ""},
                {"alias": "slash", "since": "2026/11/05"}]
    accts = provenance.accounts({"accounts": ACCOUNTS + [{"alias": ADDRESS, "plan": "Max"}, "junk", {"plan": "x"}]
                                 + bad_days})
    assert [a["alias"] for a in accts] == ["solo", "ide", "main"]   # an e-mail-shaped alias or a bad day: never used
    assert provenance.account_on("2026-11-02", accts)["alias"] == "solo"
    assert provenance.account_on("2026-11-05", accts)["alias"] == "main"
    assert provenance.account_on("2026-11-02", accts, harness="cursor")["alias"] == "ide"
    assert provenance.account_on("2026-11-07", accts, alias="ide")["plan"] == "Team"
    assert provenance.account_on("2026-11-07", accts, alias="other") == {"alias": "other"}
    assert provenance.account_on("2026-11-07", []) == {}


def test_a_row_reads_its_own_fields_then_its_snapshot_then_the_configuration_and_its_model():
    cfg = {"accounts": ACCOUNTS}
    row = {"model": "claude-opus-5-5", "start": "2026-11-07T10:00:00Z"}
    assert provenance.of_row(row, cfg) == {"provider": "anthropic", "harness": "claude-code", "account": "main",
                                           "plan": "Max"}
    snap = {"provider": "bedrock", "account": "solo", "plan": "Pro"}
    assert provenance.of_row(row, cfg, snapshot=snap) == {"provider": "bedrock", "harness": "claude-code",
                                                          "account": "solo", "plan": "Pro"}
    assert provenance.of_row({**row, "provider": "vertex"}, cfg, snapshot=snap)["provider"] == "vertex"
    assert provenance.of_row({**row, "tool": "cursor"}, cfg)["account"] == "ide"   # the harness's entry first
    # no accounts: the plan only from usage.plans the owner set, never the engine's built-in default
    assert provenance.of_row(row, None) == {"provider": "anthropic", "harness": "claude-code", "account": "(none)",
                                            "plan": "(none)"}
    plans = {"plans": [{"since": "", "plan": "Pro"}, {"since": "2026-11-05", "plan": "Max"}]}
    assert provenance.of_row(row, plans)["plan"] == "Max"


def test_a_configuration_or_a_snapshot_that_is_garbage_costs_nothing(tmp_path, monkeypatch, brain_home):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(bad))
    (brain_home / "sessions").mkdir(parents=True)
    (brain_home / "sessions" / "s-1.json").write_text("[1, 2", encoding="utf-8")
    assert provenance.captured("s-1") == {} and provenance.captured("../x") == {} and provenance.captured("") == {}
    (brain_home / "sessions" / "s-2.json").write_text(json.dumps(
        {"provider": "vertex", "account": ADDRESS, "plan": "Max"}), encoding="utf-8")
    assert provenance.captured("s-2") == {"provider": "vertex", "plan": "Max"}   # the e-mail-shaped account left out
    (brain_home / "sessions" / "s-3.json").write_text(json.dumps({"v": 1, "tool": "cursor"}), encoding="utf-8")
    assert provenance.captured("s-3") == {"harness": "cursor"}   # today's snapshot: its tool


# --- the session record ---

def _old_sr():
    """An SR as brain 0.5.0 wrote it: tool, no provider, harness or account."""
    return {"v": 1, "id": "sr-2026-11-01-aaaabbbb", "tool": "claude-code",
            "session_id": "aaaabbbb-1111-2222-3333-444455556666", "status": "closed", "model": "claude-opus-5-5",
            "start": "2026-11-01T10:00:00Z", "end": "2026-11-01T11:00:00Z"}


def test_an_old_record_stays_valid_and_reads_alike():
    old = _old_sr()
    assert schema.check("sr", old)[0] == []
    assert provenance.of_row(old) == {"provider": "anthropic", "harness": "claude-code", "account": "(none)",
                                      "plan": "(none)"}
    assert provenance.of_row(old, {"accounts": ACCOUNTS})["account"] == "solo"


def test_the_session_record_is_unchanged(fixture_transcript, ada_config, brain_home, monkeypatch, tmp_path):
    """The SR keeps tool only: no provider, harness, account or plan in what a transcript builds nor in what the Stop
    hook writes, whatever the session's environment; its schema still refuses them (wi-brain-sr-provenance-fields)."""
    main, _, _ = __import__("brain").transcript.session_stats(fixture_transcript)
    sr = main.record(fixture_transcript)
    assert sr["tool"] == "claude-code" and not set(sr) & set(provenance.FIELDS)
    t = tmp_path / "s.jsonl"
    t.write_bytes(fixture_transcript.read_bytes())
    payload = {"session_id": "aaaabbbb-1111-2222-3333-444455556666", "transcript_path": str(t)}
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    assert capture.main(["stop"], stdin=io.StringIO(json.dumps(payload))) == 0
    snap = json.loads((brain_home / "sessions" / f"{payload['session_id']}.json").read_text(encoding="utf-8"))
    assert not set(snap) & set(provenance.FIELDS) and schema.check("sr", snap)[0] == []
    assert schema.check("sr", {**_old_sr(), "account": "main"})[0]


def test_a_pattern_error_never_prints_the_value_back():
    for bad in (ADDRESS, DOTLESS, UUID.upper()):   # none matches the tool's pattern (^[a-z0-9-]+$)
        errors = schema.check("sr", {**_old_sr(), "tool": bad})[0]
        assert any(e.startswith("sr.tool") and "does not match" in e for e in errors), bad
        assert bad not in " ".join(errors)
        with pytest.raises(SystemExit) as exc:
            records.validate("sr", {**_old_sr(), "tool": bad})
        assert bad not in str(exc.value)


def test_brain_config_check_refuses_an_email_shaped_alias(tmp_path, monkeypatch):
    base = json.loads(open(config.config_file(), encoding="utf-8").read())
    base["usage"] = {"accounts": [{"alias": ADDRESS, "plan": "Max"}, {"alias": DOTLESS}, {"alias": UUID},
                                  {"alias": "ok", "plan": UUID}, {"alias": "late", "since": "2026-11-05T23:00"},
                                  {"alias": "empty", "since": ""}]}
    f = tmp_path / "config.json"
    f.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    errors = config.check()
    text = " ".join(errors)
    for i, k in enumerate(("alias", "alias", "alias", "plan", "since", "since")):
        assert f"usage.accounts[{i}].{k}" in text, (i, k)
    for bad in (ADDRESS, DOTLESS, UUID):
        assert bad not in text
    base["usage"] = {"accounts": ACCOUNTS}
    f.write_text(json.dumps(base), encoding="utf-8")
    assert not [e for e in config.check() if "usage" in e]


# --- brain usage and brain status ---

def _row(sid, day, usd, model="claude-opus-5-5", **kw):
    return {"session_id": sid, "folder": "", "start": f"{day}T10:00:00Z", "end": f"{day}T11:00:00Z", "title": "",
            "branch": "b", "kind": "build", "cost": usd, "active_s": 600, "model": model, "tokens": {"output": 10},
            "sub_tokens": {}, "days": {day: {"cost": usd, "messages": 1, "output": 10}}, "brief": {}, "spawned": [],
            "closed": [], "title_items": [], "prs": [], "context": {"peak": 1}, "phases": {}, "signals": {},
            "ngrams": {}, "tools": {}, "commands": {}, "skills": {}, "start_cost": {"cost": 0.1}, **kw}


@pytest.fixture
def lab(store):
    return projects.Project(name="lab", root=store.parents[1], stores=[store])


def _rows(lab):
    rows = [_row("s1", "2026-11-02", 2.0), _row("s2", "2026-11-07", 6.0),
            _row("s3", "2026-11-07", 1.0, model="us.anthropic.claude-opus-5-5-v1:0"),
            _row("s4", "2026-11-07", 1.0, harness="cursor", provider="anthropic"),
            _row("s5", "2026-11-07", 0.5, account=ADDRESS)]
    for r in rows:
        r["folder"] = str(lab.root)
    return rows


def test_usage_breaks_the_cost_down_by_provider_harness_and_account(lab):
    led = cost.Ledger(_rows(lab), [lab], cfg_usage={"accounts": ACCOUNTS})
    rep = cost.report(led, "2026-11-01", "", "summary")
    src = {d: {r["key"]: r for r in rows} for d, rows in rep["sources"].items()}
    assert set(src) == {"provider", "harness", "account"}
    assert src["provider"]["anthropic"]["cost"] == pytest.approx(9.5) and src["provider"]["bedrock"]["sessions"] == 1
    assert src["harness"]["claude-code"]["sessions"] == 4 and src["harness"]["cursor"]["cost"] == pytest.approx(1.0)
    assert src["account"]["main"]["cost"] == pytest.approx(7.0) and src["account"]["main"]["plans"] == ["Max"]
    assert src["account"]["solo"]["sessions"] == 1 and src["account"]["ide"]["plans"] == ["Team"]
    assert src["account"]["(masked)"]["sessions"] == 1
    text = "\n".join(cost.render_report(rep))
    assert "where: provider anthropic" in text and "account main (Max) $7.00" in text and ADDRESS not in text
    for dim in cost.SOURCE_DIMS:
        table = cost.report(led, "2026-11-01", "", dim)["tables"][dim]
        assert sum(r["total"] for r in table) == pytest.approx(10.5)
    assert ADDRESS not in cost.as_json(rep)


def test_usage_reads_what_the_snapshot_holds_before_the_configuration(lab, brain_home):
    """A snapshot that carries the session's provenance (wi-brain-sr-provenance-fields will write it: foundry, solo,
    Pro) wins over what the ledger row (its model, its day) alone would say: anthropic, main, Max."""
    snaps = brain_home / "sessions"
    snaps.mkdir(parents=True)
    (snaps / "s2.json").write_text(json.dumps({"v": 1, "provider": "foundry", "harness": "claude-code",
                                               "account": "solo", "plan": "Pro"}), encoding="utf-8")
    led = cost.Ledger(_rows(lab)[:2], [lab], cfg_usage={"accounts": ACCOUNTS})
    s2 = next(r for r in led.rows if r["session_id"] == "s2")
    assert (s2["provider"], s2["harness"], s2["account"], s2["plan"]) == ("foundry", "claude-code", "solo", "Pro")
    s1 = next(r for r in led.rows if r["session_id"] == "s1")   # no snapshot: the configuration and the model
    assert (s1["provider"], s1["account"], s1["plan"]) == ("anthropic", "solo", "Pro")
    by = {r["key"]: r for r in cost.report(led, "", "", "account")["tables"]["account"]}
    assert set(by) == {"solo"} and by["solo"]["n"] == 2
    row = {**_rows(lab)[1], "provider": "bedrock"}   # the row's own field wins over the snapshot
    assert provenance.of_row(row, {"accounts": ACCOUNTS}, snapshot=provenance.captured("s2"))["provider"] == "bedrock"


def test_a_row_read_twice_reads_the_same(lab):
    """A Ledger built again from annotated rows (brain.forecast does) keeps (none) and (masked) as they were."""
    cfg = {"accounts": [{"alias": "late", "plan": "Max", "since": "2026-11-05"}]}
    rows = _rows(lab)
    first = cost.Ledger(rows, [lab], cfg_usage=cfg).rows
    again = cost.Ledger([dict(r) for r in first], [lab], cfg_usage=cfg).rows
    pick = ("provider", "harness", "account", "plan")
    assert [[r[k] for k in pick] for r in again] == [[r[k] for k in pick] for r in first]
    assert [r["account"] for r in first] == ["(none)", "late", "late", "late", "(masked)"]
    for r in first:
        assert provenance.of_row(r, cfg) == {k: r[k] for k in pick}


def test_usage_without_accounts_reads_old_rows_alike(lab):
    led = cost.Ledger(_rows(lab)[:2], [lab])
    rep = cost.report(led, "", "", "summary")
    assert rep["sources"]["account"] == [{"key": "(none)", "cost": 8.0, "share": 1.0, "sessions": 2, "plans": []}]
    assert rep["sources"]["harness"][0]["key"] == "claude-code"


def test_cli_usage_and_status_json_keys(lab, ada_config, capsys):
    usage.save({f"p/{r['session_id']}.jsonl": r for r in _rows(lab)})
    root = str(lab.root)
    assert cli.main(["--root", root, "usage", "--since", "2026-11-01", "--json", "--no-scan"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert set(rep["sources"]) == {"provider", "harness", "account"}
    assert set(rep["sources"]["account"][0]) == {"key", "cost", "share", "sessions", "plans"}
    assert set(rep["sources"]["provider"][0]) == {"key", "cost", "share", "sessions"}
    assert cli.main(["--root", root, "usage", "--since", "2026-11-01", "--by", "account", "--no-scan"]) == 0
    out = capsys.readouterr().out
    assert "By account" in out and "main" in out and ADDRESS not in out
    s = cost.summary_of(cost.load([lab], refresh=False), "lab", "2026-11-01")
    assert {r["key"] for r in s["sources"]["account"]} == {"solo", "main", "ide", "(masked)"}
    assert "provider anthropic" in cost.summary_line(s) and "account main (Max)" in cost.summary_line(s)
    data = status.collect(lab, quick=True)
    assert "sources" in json.loads(status.render_json({"projects": {"lab": data}}))["projects"]["lab"]["tokens"]
