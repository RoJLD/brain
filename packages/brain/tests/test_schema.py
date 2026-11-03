import copy

import pytest

from brain import schema, secretscan

SESSION = {"id": "aaaabbbb-1111", "tool": "claude-code", "model": "claude-opus-5-5"}
DDR = {
    "v": 1, "id": "ddr-2026-10-30-command-shape", "title": "Command shape",
    "question": "One command for everything, or one per project?",
    "options": [{"label": "brain", "consequences": "one name"}, {"label": "atlas"}, {"label": "one per project"}],
    "recommendation": {"option": "brain", "why": "everything is in brain"},
    "multi_select": False, "status": "pending", "asked": {"at": "2026-10-30T10:00:00Z", "via": "spec"},
}
SR = {"v": 1, "id": "sr-2026-10-30-aaaabbbb", "tool": "claude-code", "session_id": "aaaabbbb-1111", "status": "open",
      "start": "2026-10-30T10:00:00Z"}
AR = {"v": 1, "id": "ar-2026-10-30-commit-repo-abcdef1234", "kind": "commit", "at": "2026-10-30T10:00:00Z",
      "repo": "RoJLD/repo", "sha": "abcdef1234", "session": SESSION, "source": "hook"}


@pytest.mark.parametrize("kind,rec", [("ddr", DDR), ("sr", SR), ("ar", AR)])
def test_valid_examples(kind, rec):
    assert schema.check(kind, rec) == ([], [])


def test_ddr_needs_two_to_four_options_and_the_recommendation_first():
    d = copy.deepcopy(DDR)
    d["options"] = d["options"][:1]
    assert any("fewer than 2" in e for e in schema.check("ddr", d)[0])
    d = copy.deepcopy(DDR)
    d["options"] = d["options"] + [{"label": "a"}, {"label": "b"}]
    assert any("more than 4" in e for e in schema.check("ddr", d)[0])
    d = copy.deepcopy(DDR)
    d["recommendation"]["option"] = "atlas"
    assert any("must be the first option" in e for e in schema.check("ddr", d)[0])


def test_ddr_lifecycle_stamps():
    d = copy.deepcopy(DDR)
    d["status"] = "answered"
    assert any("missing 'answer'" in e for e in schema.check("ddr", d)[0])
    d["answer"] = {"at": "2026-10-30T11:00:00Z", "choices": ["brain"]}
    assert schema.check("ddr", d)[0] == []
    d["status"] = "integrated"
    errors = schema.check("ddr", d)[0]
    assert any("missing 'read'" in e for e in errors) and any("missing 'applied'" in e for e in errors)
    d["read"] = {"at": "2026-10-30T11:01:00Z"}
    d["applied"] = {"at": "2026-10-30T11:02:00Z", "in": ["adr-2026-10-30-x"]}
    assert schema.check("ddr", d)[0] == []


def test_ddr_answer_must_be_an_option_or_other():
    d = copy.deepcopy(DDR)
    d.update(status="answered", answer={"at": "2026-10-30T11:00:00Z", "choices": ["brain", "atlas"]})
    assert any("several choices" in e for e in schema.check("ddr", d)[0])
    d["answer"] = {"at": "2026-10-30T11:00:00Z", "choices": ["nope"]}
    assert any("not an option label" in e for e in schema.check("ddr", d)[0])
    d["answer"] = {"at": "2026-10-30T11:00:00Z", "other": "my own way"}
    assert schema.check("ddr", d)[0] == []


def test_captured_question_without_recommendation_is_a_warning_only():
    d = copy.deepcopy(DDR)
    d["recommendation"] = {"option": None, "why": "not given"}
    assert schema.check("ddr", d)[0]
    d["asked"]["via"] = "ask-tool"
    errors, warnings = schema.check("ddr", d)
    assert errors == [] and warnings


def test_ar_kind_fields_and_id():
    a = copy.deepcopy(AR)
    del a["sha"]
    assert any("missing 'sha'" in e for e in schema.check("ar", a)[0])
    a = copy.deepcopy(AR)
    a["id"] = "ar-2026-10-31-commit-repo-abcdef1234"
    assert any("must start with ar-2026-10-30-commit-" in e for e in schema.check("ar", a)[0])
    a = copy.deepcopy(AR)
    a["extra"] = 1
    assert any("unexpected field 'extra'" in e for e in schema.check("ar", a)[0])


def test_sr_id_follows_start_and_session():
    s = copy.deepcopy(SR)
    s["id"] = "sr-2026-10-29-aaaabbbb"
    assert any("sr-<start date>" in e for e in schema.check("sr", s)[0])
    s = copy.deepcopy(SR)
    s["status"] = "closed"
    assert any("missing 'end'" in e for e in schema.check("sr", s)[0])


def test_secret_lines_are_dropped():
    key = "sk-" + "ant-" + "a1B2" * 8
    token = "gh" + "p_" + "Z9y8" * 9
    text = f"first line\nexport ANTHROPIC_API_KEY={key}\nthird {token}\nlast"
    cleaned, n = secretscan.clean_text(text)
    assert n == 2 and key not in cleaned and token not in cleaned
    assert cleaned.splitlines()[0] == "first line" and cleaned.splitlines()[-1] == "last"
    obj, n = secretscan.clean({"a": [f"x {key}"], "b": 3, "c": "fine"})
    assert n == 1 and obj["a"] == [secretscan.DROPPED] and obj["b"] == 3 and obj["c"] == "fine"


def test_ordinary_text_is_kept():
    for text in ("Token ledger: tokens per session", "tokens: 12345", "brain item close wi-brain-token-ledger",
                 "https://github.com/acme/engine/pull/12", "password policy discussed"):
        assert secretscan.find(text) == [], text


def test_password_shapes_are_dropped():
    value = "Hunter" + "2024!xyz"  # built here, so this file holds no password-shaped line
    for line in (f"| admin | `root` (console, MDP `{value}` + key) |", f"mdp: {value}", f"| **Password** | {value} |",
                 f"the password is '{value}'", f"DB_PASSWORD={value}"):
        assert secretscan.find(line), line
    table = f"| user | mot de passe |\n|---|---|\n| ada | {value} |\n| ci | — |\n\nafter"
    cleaned, n = secretscan.clean_text(table)
    assert n == 1 and value not in cleaned
    assert cleaned.splitlines()[0] == "| user | mot de passe |" and cleaned.splitlines()[3] == "| ci | — |"
    assert secretscan.scan_lines(table) == [(3, "password-table")]
    assert secretscan.clean({"q": table})[0]["q"] == cleaned


def test_password_words_without_a_value_are_kept():
    for text in ("password policy discussed", r'r"(?:api[_\-]?key|secret|token|pwd|private[_\-]?key)"',
                 "password = os.environ['DB_PASSWORD']", "| user | password |", 'cd "$PWD" && ls',
                 "ran pwd `/d/work/brain`", "| Password | stored in Bitwarden |", "mdp: Ada types it",
                 "password: ${DB_PASSWORD}", "pwd: <redacted>"):
        assert secretscan.find(text) == [], text
    header_only = "| user | password |\n|---|---|\n| ada | - |\n| ci | n/a |"
    assert secretscan.scan_lines(header_only) == []


def test_url_credentials_are_stripped():
    assert secretscan.strip_url_credentials("https://user:" + "secret" + "@github.com/o/r.git") == \
        "https://github.com/o/r.git"
