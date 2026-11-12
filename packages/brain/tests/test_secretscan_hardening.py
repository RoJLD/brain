"""The secret scan hardened before the first machine snapshot (wi-brain-secretscan-hardening, spec-brain-one-brain
§10): whole PEM blocks, the fleet's token formats, a unit refused whole, gitleaks:allow ignored where the owner's own
text lives, a pointer only on ntfy for a decision about a rule or a note, and the private-text check."""

import json

import pytest
from brain import cli, config, guards, notify, privatetext, secretscan
from conftest import run_git

KIND = "OPENSSH " + "PRIVATE KEY"   # built here, so that this file holds no key's header line
PEM = f"""intro line
-----BEGIN {KIND}-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACDxEXAMPLExEXAMPLExEXAMPLExEXAMPLExEXAMPLExEXAMPLEAAAAJgAAAAA
-----END {KIND}-----
after the key"""


def test_a_pem_block_is_dropped_whole():
    text, n = secretscan.clean_text(PEM)
    assert n == 4 and text.splitlines() == ["intro line"] + [secretscan.DROPPED] * 4 + ["after the key"]
    assert [x for x in secretscan.scan_lines(PEM)] == [(i, "private-key") for i in range(2, 6)]


def test_a_pem_block_without_its_end_drops_to_the_end():
    cut = "\n".join(PEM.splitlines()[:3])
    assert secretscan.clean_text(cut + "\nmore base64")[1] == 3


@pytest.mark.parametrize("name, value", [
    ("ntfy-token", "tk_" + "a1B2c3D4e5" * 2 + "f6G7h8I9j"),
    ("tailscale-key", "tskey-auth-kAbCd1CNTRL-" + "Q" * 30),
    ("gitlab-token", "glpat-" + "x" * 20),
    ("pypi-token", "pypi-AgEIcHlwaS5vcmc" + "A" * 60),
    ("npm-token", "npm_" + "Z9" * 18),
])
def test_the_fleets_token_formats(name, value):
    assert name in secretscan.find(f"export X={value}")
    assert secretscan.clean_text(f"token {value}")[0] == secretscan.DROPPED


@pytest.mark.parametrize("value", ["tk_short", "tskey-auth", "glpat-short", "pypi-other", "npm_install"])
def test_their_near_misses_pass(value):
    assert secretscan.find(f"see {value} here") == []


def test_a_unit_is_refused_whole():
    note = "# A note\n\nThe server is up.\ntoken " + "ghp_" + "a" * 36 + "\nIt opens the deploy repo.\n"
    assert secretscan.clean_unit(note) == (secretscan.DROPPED_UNIT, 1)
    assert secretscan.clean_unit("# A note\n\nNothing secret.\n") == ("# A note\n\nNothing secret.\n", 0)
    hits = secretscan.unit_hits("k = 'x'  # gitleaks:allow\nsk-ant-" + "b" * 20)
    assert {line for line, _ in hits} == {2} and "anthropic-key" in {name for _, name in hits}


@pytest.mark.parametrize("path, strict", [("memory/x/note.md", True), ("machines/kestrel/settings.json", True),
                                          ("./memory/a.md", True), ("memory\\a.md", True), ("docs/memory/a.md", False),
                                          ("src/machines.py", False), ("", False)])
def test_gitleaks_allow_waives_nothing_under_machines_and_memory(path, strict):
    line = 'token = "ghp_' + "c" * 36 + '"  # gitleaks:allow'
    assert secretscan.strict(path) is strict
    assert bool(secretscan.find_in_line(line, path)) is strict


@pytest.fixture
def repo(make_repo, monkeypatch):
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setattr(guards, "gitleaks", lambda r: [])   # gitleaks present and silent: it honours the mark
    return make_repo("brainrepo", {"README.md": "# brain\n"})


def test_the_commit_guard_refuses_an_allowed_secret_in_memory_even_with_gitleaks(repo):
    line = 'token = "ghp_' + "d" * 36 + '"  # gitleaks:allow\n'
    (repo / "memory").mkdir()
    (repo / "memory" / "n.md").write_text(line, encoding="utf-8")
    (repo / "docs.md").write_text(line, encoding="utf-8")
    run_git(repo, "add", "-A")
    hits = guards.commit_secrets(str(repo), [], False)
    assert hits == ["memory/n.md:1 (github-token)"]   # docs.md: the mark waives it there


def test_a_rule_or_note_decision_sends_a_pointer_only():
    ddr = {"id": "ddr-2026-01-02-keep-rule", "title": "Keep the rule on kestrel?", "question": "Rule X says ...",
           "options": [{"label": "Keep"}, {"label": "Drop"}], "links": {"rules": ["global.md#git"]}}
    title, body = notify.decision_message("demo", ddr)
    assert (title, body) == notify.POINTER
    assert "kestrel" not in title + body and "Rule X" not in body and "ddr-" not in body
    ddr["links"] = {"notes": ["memory/x.md"]}
    assert notify.decision_message("demo", ddr) == notify.POINTER
    ddr["links"] = {"items": ["wi-x"]}
    assert notify.decision_message("demo", ddr)[0].startswith("Decision needed: ")


def test_decision_ask_records_its_rule_and_note_links(tmp_path, monkeypatch):
    from brain import decisions
    ddr, out = decisions.ask(tmp_path, title="Keep the rule?", question="Keep it?", options=["Keep", "Drop"],
                             why="it holds", at="2026-01-02T10:00:00Z", rules=["global.md#git"],
                             notes=["memory/x.md"], dry_run=True)
    assert out is None
    assert ddr["links"]["rules"] == ["global.md#git"] and ddr["links"]["notes"] == ["memory/x.md"]


@pytest.fixture
def private(tmp_path, monkeypatch, make_repo):
    brain = tmp_path / "ada-brain"
    (brain / "rules").mkdir(parents=True)
    (brain / "rules" / "global.md").write_text(
        "# Rules\n\nNever push to the shared branch on a Friday after six in the evening.\n", encoding="utf-8")
    (brain / "memory" / "proj").mkdir(parents=True)
    (brain / "memory" / "proj" / "n.md").write_text("The orchard keys sit in the blue drawer of the old desk.\n",
                                                    encoding="utf-8")
    (brain / config.FILE).write_text(json.dumps({"v": 1, "rules": ["rules/global.md"],
                                                 "public": {"repos": ["acme/engine"]}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / config.FILE))
    repo = make_repo("engine", {"README.md": "# engine\n\nA graph engine.\n",
                                "docs/x.md": "Ours: never PUSH to the shared\nbranch on a Friday, after six.\n",
                                "docs/y.md": "Where? The orchard keys sit in the blue drawer of the old desk!\n"})
    run_git(repo, "remote", "add", "origin", "https://github.com/acme/engine.git")
    return repo


def test_the_private_text_check_finds_eight_words_copied(private, capsys):
    cfg = config.load()
    assert [p.name for p in privatetext.sources(cfg)] == ["global.md", "n.md"]
    idx = privatetext.index(cfg)
    assert privatetext.scan((private / "docs" / "x.md").read_text(encoding="utf-8"), idx) == [
        (1, "rules/global.md")]   # case, punctuation and the line break do not hide it
    assert privatetext.scan("A graph engine, never pushed to a branch.", idx) == []
    assert cli.main(["check", "--public", "--repo", str(private), "--private-text"]) == 1
    out = capsys.readouterr().out
    assert "docs/x.md:1: text: 8 words or more of rules/global.md" in out
    assert "docs/y.md:1: text: 8 words or more of memory/proj/n.md" in out
    assert cli.main(["check", "--public", "--repo", str(private)]) == 0   # opt-in: before a tag
