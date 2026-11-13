"""The locked floor (brain.floor, wi-brain-unadopted-floor, the owner's R21): the rules marked locked, the guard's
refusals of a push to main and a forced push, and the floor-only machine (the locked rules alone, the floor's
refusals and the secrets check alone, no memory sync). Owner Ada, invented rules."""

import io
import json

import pytest
from brain import floor, guards, memory
from conftest import run_git
from test_guards import bash, payload
from test_inject_rules import _run

RULES = """# Rules

- Never push to main: merge by a pull request. <!-- lock: adr-floor -->
- Never force-push.<!--lock-->
- Prefer short functions.
- Never write a secret in a commit. <!-- lock -->
"""


def config(tmp_path, monkeypatch, **section):
    (tmp_path / "rules.md").write_text(RULES, encoding="utf-8")
    data = {"v": 1, "identity": {"owner": "Ada"}, "rules": ["rules.md"]}
    if section:
        data["floor"] = section
    f = tmp_path / "config.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    return f


@pytest.fixture
def repo(git_repo):
    run_git(git_repo, "remote", "add", "origin", "https://code.example/ada/lab.git")
    return git_repo


def test_the_locked_lines():
    assert floor.locked(RULES) == ["- Never push to main: merge by a pull request.", "- Never force-push.",
                                   "- Never write a secret in a commit."]
    assert floor.settings({"floor": {"refuse": True, "only": "yes"}}) == {"refuse": True, "only": False}
    assert floor.settings({"floor": []}) == floor.settings(None) == {"refuse": False, "only": False}


@pytest.mark.parametrize("refspecs, flags, current, check", [
    (["main"], set(), "feat/x", "main"), (["HEAD:refs/heads/master"], set(), "x", "master"), ([], set(), "main", "main"),
    (["x:main"], set(), "x", "main"), (["main"], {"--delete"}, "x", "main"), ([":main"], set(), "x", "main"),
    ([], {"--all"}, "x", "main"), (["x"], {"--force"}, "x", "force"), (["x"], {"-fu"}, "x", "force"),
    (["+x"], set(), "x", "force"), (["x"], {"--force-with-lease"}, "x", "force"), ([], {"--mirror"}, "x", "force"),
    (["feat/x"], set(), "main", None), ([], set(), "feat/x", None), (["mainline"], set(), "x", None),
    ([], {"--tags"}, "feat/x", None), (["feat/x"], {"-u"}, "x", None),
])
def test_push_refusal(refspecs, flags, current, check):
    hit = floor.push_refusal(refspecs, flags, current)
    assert (hit[0] if hit else None) == (None if check is None else "force" if check == "force" else "main")


@pytest.mark.parametrize("command, check", [
    ("git push origin main", "main"), ("git push", "main"), ("git push origin HEAD", "main"),
    ("git push -f origin feat/x", "force"), ("git push origin +feat/x", "force"), ("git push origin :main", "main"),
    ("git push --force-with-lease origin feat/x", "force"), ("git -C . push origin HEAD:master", "main"),
])
def test_the_guard_refuses_a_push_to_main_and_a_forced_push(repo, tmp_path, monkeypatch, command, check):
    config(tmp_path, monkeypatch, refuse=True)
    reason = bash(repo, command)   # git_repo is on main
    assert reason and "breaks the locked floor" in reason and f"{guards.ALLOW_ENV}=floor (or floor:{check})" in reason


def test_a_branch_push_passes_and_the_floor_is_off_by_default(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    assert bash(repo, "git push -u origin feat/x") is None and bash(repo, "git push origin --tags") is None
    config(tmp_path, monkeypatch)
    assert bash(repo, "git push origin main") is None and bash(repo, "git push -f origin x") is None


def test_the_owner_lifts_it(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    monkeypatch.setenv(guards.ALLOW_ENV, "floor:force")
    assert bash(repo, "git push -f origin x") is None and bash(repo, "git push origin main")


def test_a_floor_only_machine_runs_the_floor_and_the_secrets_check_only(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    assert "breaks the locked floor" in bash(repo, "git push -f origin x")      # refuse not needed
    assert bash(repo, "schtasks /create /tn x /tr y") is None                   # the owner guard is not the floor
    assert bash(repo, "shutdown /s /t 0") is None                               # nor the power guard
    assert guards.main(io.StringIO(json.dumps(payload("Write", repo, file_path=str(repo / "x.md"), content="x"))),
                       io.StringIO()) == 0


def test_a_floor_only_machine_syncs_no_memory(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    monkeypatch.setenv("BRAIN_MEMORY_SYNC", "1")
    assert memory.mode() == "off"
    config(tmp_path, monkeypatch, only=False)
    assert memory.mode() == "both"


def test_a_floor_only_machine_is_injected_the_locked_rules_alone(tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch, only=True)
    text = _run({"BRAIN_CONFIG": str(f)})["additionalContext"]
    assert text == "\n".join([floor.ONLY_LINE, *floor.locked(RULES)]) + "\n"
    f = config(tmp_path, monkeypatch, refuse=True)
    assert _run({"BRAIN_CONFIG": str(f)})["additionalContext"] == RULES
