"""One privacy scrub for what leaves the machine (wi-brain-privacy-scrub, brain.scrub): its corpus, and where it runs
(errors.log, the notifications, the outbox)."""

import json
from pathlib import Path

import pytest
from brain import capture, config, outbox, paths, scrub

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "scrub" / "corpus.json").read_text(encoding="utf-8"))
# built here, so that no file of this public repo holds a token, a home folder or an address
WIN, LINUX, EMAIL = "C:\\Users\\" + "bob", "/home/" + "alice", "ada" + "@" + "corp.io"
VALUES = {"win": WIN, "winfwd": WIN.replace("\\", "/"), "linux": LINUX, "email": EMAIL,
          "ghp": "ghp_" + "a" * 36, "hf": "hf_" + "a1b2c3d4e5" * 3 + "f6g7", "pw": "pass" + "word=Hunter2!",
          "creds": "u:" + "p4ss", "pem": "-----BEGIN OPENSSH " + "PRIVATE KEY-----"}
NAMES = {"host_names": CORPUS["hosts"], "user_names": CORPUS["users"]}


def _fill(text: str) -> str:
    for k, v in VALUES.items():
        text = text.replace("{" + k + "}", v)
    return text


@pytest.mark.parametrize("case", CORPUS["cases"], ids=[c["why"] for c in CORPUS["cases"]])
def test_the_corpus(case):
    assert scrub.text(_fill(case["in"]), **NAMES) == case["out"]


def test_every_case_of_the_corpus_is_idempotent():
    for case in CORPUS["cases"]:
        once = scrub.text(_fill(case["in"]), **NAMES)
        assert scrub.text(once, **NAMES) == once, case["why"]


def test_objects_keep_their_keys_and_scrub_their_strings():
    got = scrub.obj({"user": "bob", "lines": [f"at {WIN}\\x.py", 3], "n": 1}, host_names=[], user_names=["bob"])
    assert got == {"user": "<user>", "lines": ["at ~\\x.py", 3], "n": 1}


def test_the_names_come_from_the_machine_and_the_fleet(tmp_path, monkeypatch):
    cfg = tmp_path / config.FILE
    cfg.write_text(json.dumps({"v": 1, "hosts": {"kestrel": {"aliases": ["kestrel-wsl"]}, "x1": {}}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    monkeypatch.setenv("BRAIN_MACHINE", "orchard-01")
    names = scrub.hosts()
    assert {"kestrel", "kestrel-wsl", "orchard-01"} <= set(names) and "x1" not in names   # 3 characters at least
    assert names.index("kestrel-wsl") < names.index("kestrel")   # longest first
    monkeypatch.setenv("USERNAME", "zelda-q")
    assert "zelda-q" in scrub.users()


def test_errors_log_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRAIN_MACHINE", "orchard-01")
    try:
        raise OSError(f"cannot open {WIN}\\notes.md on orchard-01 for {EMAIL}")
    except OSError as exc:
        capture._log_error("hook", exc)
    log = (paths.ledger_dir() / "errors.log").read_text(encoding="utf-8")
    assert "~\\notes.md" in log and "<host>" in log and "<email>" in log
    assert WIN not in log and "orchard-01" not in log and EMAIL not in log


def test_the_outbox_keeps_a_scrubbed_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BRAIN_MACHINE", "orchard-01")
    outbox.put("notify", "k1", {"body": f"on orchard-01 at {LINUX}", "host": "orchard-01"})
    assert outbox.pending()["k1"]["payload"] == {"body": "on <host> at ~", "host": "orchard-01"}
