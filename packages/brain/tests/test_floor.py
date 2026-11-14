"""The locked floor (brain.floor, wi-brain-unadopted-floor, the owner's R21): the rules marked locked, the guard's
refusals of a push to main and a forced push, and the floor-only machine (the locked rules alone, the floor's
refusals and the secrets check alone, no memory sync). Owner Ada, invented rules."""

import io
import json

import pytest
from brain import floor, guards, memory
from conftest import run_git
from test_guards import bash, decide, payload, pwsh
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
    ("git push origin @", "main"), ("git push origin +@:feat/x", "force"),
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


def edit(cwd, path, content):
    return decide(payload("Write", cwd, file_path=str(path), content=content))


# --- review of the PR: no session lifts its own floor (high) -------------------------------------------------------

@pytest.mark.parametrize("section", [{"only": True}, {"refuse": True}])
def test_a_session_cannot_lift_its_own_floor(repo, tmp_path, monkeypatch, section):
    f = config(tmp_path, monkeypatch, **section)
    settings = repo / ".claude" / "settings.json"
    assert "BRAIN_GUARD_ALLOW" in edit(repo, settings, '{"env": {"BRAIN_GUARD_ALLOW": "floor"}}')
    assert bash(repo, "setx BRAIN_GUARD_ALLOW floor")
    assert pwsh(repo, "[Environment]::SetEnvironmentVariable('BRAIN_GUARD_ALLOW', 'floor', 'User')")
    assert "sets the floor" in edit(repo, f, '{"v": 1}')                                   # the file it reads
    assert "sets the floor" in bash(repo, f"echo '{{}}' > '{f.as_posix()}'")
    assert "moves the floor's file" in bash(repo, "setx BRAIN_CONFIG C:/elsewhere/config.json")
    assert "moves the floor's file" in edit(repo, settings, '{"env": {"BRAIN_CONFIG": "x.json"}}')
    assert edit(repo, repo / "config.json", '{"v": 1}') is None                           # a worktree's own copy
    assert bash(repo, 'brain --project x check > "$BRAIN_HOME/out.txt"') is None           # the Brain's own commands


def test_a_floor_only_machine_keeps_the_override_protection_alone(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    hit = bash(repo, "brain usage allow --hours 2")
    assert hit and "brain.gestures" in hit                                             # a gesture of category override
    assert bash(repo, "brain vault open") is None                                      # keys: not the floor's
    assert edit(repo, repo / "notes.md", "BRAIN_GUARD_ALLOW=floor") is None             # not a settings file


def test_guard_sh_starts_python_for_what_lifts_the_floor():
    from test_guards import _needs_python
    assert _needs_python(["[Environment]::SetEnvironmentVariable('BRAIN_CONFIG', 'x', 'User')",
                          "setx BRAIN_CONFIG x", "git push origin @", "git -c push.default=matching push",
                          "echo {} > config.json"]) == [True] * 5


def test_the_floor_off_lets_config_json_be_edited(repo, tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch)
    assert edit(repo, f, '{"v": 1}') is None and bash(repo, "setx BRAIN_CONFIG x") is None


# --- review of the PR: what git sends, read as git reads it (medium) -----------------------------------------------

@pytest.mark.parametrize("command", [
    "git push origin :", "git push origin 'refs/heads/*:refs/heads/*'", "git push origin '*'",
    "git push origin x:heads/main", "git -c push.default=matching push", "git -c push.default=matching push origin",
    "git push --al origin", "git push --branc origin",
])
def test_every_way_to_main_is_refused(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    run_git(repo, "switch", "-q", "-c", "feat/x")
    assert "breaks the locked floor" in (bash(repo, command) or "")


def test_the_remote_push_refspecs_and_the_upstream(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    run_git(repo, "switch", "-q", "-c", "feat/x")
    assert bash(repo, "git push") is None and bash(repo, "git push origin") is None   # simple: feat/x to feat/x
    run_git(repo, "config", "branch.feat/x.merge", "refs/heads/main")
    assert "a push of main" in bash(repo, "git -c push.default=upstream push origin")
    run_git(repo, "config", "push.default", "upstream")
    assert "a push of main" in bash(repo, "git push")
    run_git(repo, "config", "push.default", "nothing")
    assert bash(repo, "git push") is None
    run_git(repo, "config", "remote.origin.push", "HEAD:refs/heads/master")
    assert "a push of master" in bash(repo, "git push origin")


@pytest.mark.parametrize("refspec", ["'refs/tags/*'", "'refs/heads/feat/*:refs/heads/feat/*'", "'^refs/heads/main'",
                                     "feat/x:feat/main-fix"])
def test_what_does_not_write_main_passes(repo, tmp_path, monkeypatch, refspec):
    config(tmp_path, monkeypatch, refuse=True)
    assert bash(repo, f"git push origin {refspec}") is None


@pytest.mark.parametrize("command", ["git push --force-w origin feat/x", "git push --mirr origin",
                                     "git push -4f origin feat/x", "git push --force-if origin feat/x"])
def test_every_spelling_of_force_is_refused(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    assert "breaks the locked floor" in (bash(repo, command) or "")


# --- review of the PR: a push option is not a force (low) ----------------------------------------------------------

@pytest.mark.parametrize("command", ["git push -oforce origin feat/x", "git push -uo force origin feat/x",
                                     "git push --push-o force origin feat/x"])
def test_a_push_option_named_force_passes(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    assert bash(repo, command) is None


def test_git_config_reads_the_listing_and_the_commands_own():
    conf = floor.git_config("push.default\nsimple\0remote.Origin.push\nHEAD:main\0Branch.feat/x.y.Merge\nrefs/heads/a\0",
                            ["push.default=matching", "core.bare"])
    assert conf == {"push.default": ["simple", "matching"], "remote.Origin.push": ["HEAD:main"],
                    "branch.feat/x.y.merge": ["refs/heads/a"], "core.bare": ["true"]}
    assert floor.default_refspecs(conf, "origin", "feat/x") == [":"]
    assert floor.default_remote({"remote.pushdefault": ["up"]}, "x") == "up"
    assert floor.default_refspecs({}, "origin", "HEAD") == []                      # no branch checked out


# --- review of the PR: bash and Python read the same floor (low) ---------------------------------------------------

def test_bash_and_python_read_the_same_locked_lines(tmp_path, monkeypatch):
    rules = ("- A\t<!-- lock: adr-a --> twice <!-- lock -->\n- B <!-- lock: adr-\u00e9 -->\n"
             "- C <!--lock:x.y_z-1-->\n")
    f = config(tmp_path, monkeypatch, only=True)
    (tmp_path / "rules.md").write_text(rules, encoding="utf-8")
    assert floor.locked(rules) == ["- A twice", "- C"]
    assert _run({"BRAIN_CONFIG": str(f)})["additionalContext"] == "\n".join([floor.ONLY_LINE, "- A twice", "- C"]) + "\n"


@pytest.mark.parametrize("data, only", [
    ({"projects": {"floor": {"only": True}}}, False), ({"floor": {"x": {"only": True}}}, False),
    ({"floor": {"only": True}, "z": "\"floor\": {\"only\": true}"}, True), ({"floor": {"only": "true"}}, False),
    ({"z": "{\"floor\": {\"only\": true}}"}, False), ({"floor": {"refuse": True, "only": True}}, True),
])
def test_floor_only_is_read_at_the_top_level_alone(tmp_path, monkeypatch, data, only):
    f = config(tmp_path, monkeypatch)
    f.write_text(json.dumps({"v": 1, "rules": ["rules.md"], **data}), encoding="utf-8")
    assert floor.settings(data)["only"] is only
    text = _run({"BRAIN_CONFIG": str(f)})["additionalContext"]
    assert (text.split("\n")[0] == floor.ONLY_LINE) is only


def test_the_last_of_two_keys_wins_in_bash_too(tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch)
    f.write_text('{"v": 1, "rules": ["rules.md"], "floor": {"only": true}, "floor": {"only": false}}',
                 encoding="utf-8")
    assert not floor.settings(json.loads(f.read_text(encoding="utf-8")))["only"]
    assert _run({"BRAIN_CONFIG": str(f)})["additionalContext"] == RULES


# --- review of the PR: the docs say what runs on a floor-only machine (low) ----------------------------------------

def test_the_docs_and_the_hook_say_what_runs_there():
    from pathlib import Path
    hook = Path(floor.__file__).parent / "adapters" / "claude" / "hooks" / "inject-rules.sh"
    assert floor.ONLY_LINE in hook.read_text(encoding="utf-8")
    docs = (Path(floor.__file__).parents[2] / "docs" / "guards.md").read_text(encoding="utf-8")
    assert "check_override" in docs and "the override protection" in docs


# --- review of the PR: what the floor costs a call (low) -----------------------------------------------------------

def test_one_config_read_and_no_rev_parse_for_explicit_refspecs(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    loads, gits = [], []
    real_load, real_git = guards.config.load, guards._git_out
    monkeypatch.setattr(guards.config, "load", lambda *a, **k: loads.append(1) or real_load(*a, **k))
    monkeypatch.setattr(guards, "_git_out", lambda d, *a, **k: gits.append(a) or real_git(d, *a, **k))
    assert list(guards.refusals(payload("Bash", repo, command="git push origin feat/x:feat/x"))) == []
    assert not [a for a in gits if a[:2] == ("rev-parse", "--abbrev-ref")]
    loads.clear()
    fl = floor.settings({"floor": {"refuse": True}})
    cmds = guards.calls("git push -f origin feat/x", str(repo), False)
    assert guards.check_floor(cmds, fl)[0] == "force" and not loads              # the floor reads none of its own
    assert guards.check_floor_files("Bash", {}, cmds, str(repo), fl, None, "git push -f origin feat/x") is None


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
