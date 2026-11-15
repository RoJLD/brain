"""The locked floor (brain.floor, wi-brain-unadopted-floor, the owner's R21): the rules marked locked, the guard's
refusals of a push to main and a forced push, and the floor-only machine (the locked rules alone, the floor's
refusals and the secrets check alone, no memory sync). Owner Ada, invented rules."""

import io
import json

import pytest
from brain import floor, floorguard, guards, memory
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


@pytest.fixture(autouse=True)
def held(request, monkeypatch):
    """The parser's tests run on a floor-only machine whose lock holds (brain.floor.unlocked says ''); the lock's own
    tests (the ``unheld`` fixture) read the real check."""
    if "unheld" not in request.fixturenames:
        monkeypatch.setattr(floor, "unlocked", lambda *a, **k: "")


@pytest.fixture
def unheld():
    """brain.floor.unlocked as it is (no fake lock)."""
    return floor.unlocked


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
    assert "moves or stops the floor" in bash(repo, "setx BRAIN_CONFIG C:/elsewhere/config.json")
    assert "moves or stops the floor" in edit(repo, settings, '{"env": {"BRAIN_CONFIG": "x.json"}}')
    assert edit(repo, repo / "config.json", '{"v": 1}') is None                           # a worktree's own copy
    assert bash(repo, 'brain --project x check > "$BRAIN_HOME/src/out.txt"') is None       # the Brain's own commands


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
    assert "floor:config" in bash(repo, "git -c push.default=upstream push origin")    # set by -c: refused
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
    assert floorguard.check_floor(cmds, fl)[0] == "force" and not loads              # the floor reads none of its own
    assert floorguard.check_files("Bash", {}, cmds, str(repo), fl, None, "git push -f origin feat/x") is None


# --- review round 2: what stops the guards, how a path is spelled, what else pushes ----------------------------------

@pytest.mark.parametrize("command", [
    "setx BRAIN_PYTHON C:/x/true.exe", "setx PYTEST_CURRENT_TEST x", "setx USERPROFILE C:/tmp/u",
])
def test_what_stops_the_guards_is_refused_under_the_floor(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "moves or stops the floor" in (bash(repo, command) or "")


@pytest.mark.parametrize("content", ['{"env": {"BRAIN_PYTHON": "C:/x/true.exe"}}', '{"disableAllHooks": true}',
                                     '{"env": {"USERPROFILE": "C:/tmp/u"}}', '{"env": {"HOME": "/tmp/u"}}'])
def test_settings_that_stop_the_guards_are_refused_under_the_floor(repo, tmp_path, monkeypatch, content):
    config(tmp_path, monkeypatch, refuse=True)
    assert edit(repo, repo / ".claude" / "settings.json", content)
    assert pwsh(repo, "[Environment]::SetEnvironmentVariable('BRAIN_PYTHON', 'x', 'User')")
    assert bash(repo, "echo 'export PATH=$HOME/bin:$PATH' >> ~/.bashrc") is None          # $HOME read, not set


def test_the_owner_guard_refuses_them_under_owner_strict(repo, tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch)
    settings = repo / ".claude" / "settings.json"
    assert edit(repo, settings, '{"disableAllHooks": true}') is None and bash(repo, "setx BRAIN_PYTHON x") is None
    data = json.loads(f.read_text(encoding="utf-8"))
    f.write_text(json.dumps({**data, "guards": {"owner_strict": True}}), encoding="utf-8")
    assert "turns the guards off" in edit(repo, settings, '{"disableAllHooks": true}')
    assert "turns the guards off" in bash(repo, "setx BRAIN_PYTHON x")


def test_the_guard_fails_closed_while_the_floor_is_on_or_unknown(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    with monkeypatch.context() as m:
        m.setattr(guards, "check_secrets", lambda cmds: 1 / 0)
        assert "could not judge" in bash(repo, "git commit -m x")
        m.setattr(guards, "refusals", lambda *a, **k: 1 / 0)
        assert "the guard failed, so it refuses" in bash(repo, "ls")
        config(tmp_path, monkeypatch)
        assert bash(repo, "ls") is None                                               # the floor off: fail open
    config(tmp_path, monkeypatch, only=True)
    with monkeypatch.context() as m:
        m.setattr(guards.config, "load", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert "refuses" in bash(repo, "ls")                                          # config.json unreadable


def test_guard_sh_runs_no_interpreter_that_is_not_a_python(tmp_path):
    import os
    import shutil
    import subprocess
    sh = shutil.which("bash")
    if not sh:
        pytest.skip("no bash")
    fake = tmp_path / "true.exe"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "BRAIN_PYTHON"}
    env.update(BRAIN_HOME=str(tmp_path / "home"), BRAIN_SELFTIME="0", PATH=str(tmp_path / "no-python"),
               BRAIN_PYTHON=fake.as_posix())
    from test_guards import PLUGIN
    out = subprocess.run([sh, str(PLUGIN / "hooks" / "guard.sh"), "shell"],
                         input=json.dumps(payload("Bash", tmp_path, command="git push origin main")),
                         capture_output=True, text=True, env=env, timeout=60).stdout
    assert "the guards cannot run" in out                                            # true.exe was not run


def test_a_stream_name_or_a_junction_is_the_file_itself(repo, tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch, only=True)
    assert "sets the floor" in edit(repo, f"{f}::$DATA", '{"v": 1}')
    settings = tmp_path / "home" / ".claude" / "settings.json"
    assert "BRAIN_GUARD_ALLOW" in edit(repo, f"{settings}::$DATA", '{"env": {"BRAIN_GUARD_ALLOW": "all"}}')
    config(tmp_path, monkeypatch)                                                     # the owner guard, floor off
    assert "BRAIN_GUARD_ALLOW" in edit(repo, f"{settings}::$DATA", '{"env": {"BRAIN_GUARD_ALLOW": "all"}}')
    settings.parent.mkdir(parents=True)
    link = tmp_path / "cl"
    try:
        import _winapi
        _winapi.CreateJunction(str(settings.parent), str(link))
    except (ImportError, OSError):
        try:
            link.symlink_to(settings.parent, target_is_directory=True)
        except OSError:
            pytest.skip("no junction nor symbolic link here")
    assert "BRAIN_GUARD_ALLOW" in edit(repo, link / "settings.json", '{"env": {"BRAIN_GUARD_ALLOW": "all"}}')


@pytest.mark.parametrize("command, check", [
    ("git -c alias.p=push p origin feat/x:main", "config"), ("git config alias.ship push", "config"),
    ("git config --global alias.ship push", "config"), ("git -c remote.origin.mirror=true push origin", "config"),
    ("git config remote.origin.push HEAD:main", "config"), ("git config set push.default matching", "config"),
    ("git send-pack origin +x:main", "main"), ("git symbolic-ref refs/heads/alias refs/heads/main", "main"),
    ("gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc -F force=true", "main"),
])
def test_other_writers_of_main_are_refused(repo, tmp_path, monkeypatch, command, check):
    config(tmp_path, monkeypatch, refuse=True)
    reason = bash(repo, command) or ""
    assert "breaks the locked floor" in reason and f"floor:{check}" in reason


@pytest.mark.parametrize("command", ["git config --get alias.ship", "git config alias.ship", "git config user.name x",
                                     "gh api repos/o/r/pulls", "gh api -X PATCH repos/o/r/git/refs/heads/feat -f sha=a",
                                     "git push --help", "git config --unset alias.ship"])
def test_reads_and_other_keys_pass(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    assert bash(repo, command) is None


def test_aliases_mirrors_and_symbolic_branches_are_read(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    run_git(repo, "switch", "-q", "-c", "feat/x")
    run_git(repo, "config", "alias.ship", "push")
    assert "a push of main" in bash(repo, "git ship origin main") and bash(repo, "git ship origin feat/x") is None
    run_git(repo, "config", "alias.sp", "!git push origin main")
    assert "floor's reading" in bash(repo, "git sp")
    run_git(repo, "symbolic-ref", "refs/heads/alias", "refs/heads/main")
    assert "a push of main" in bash(repo, "git push origin alias")
    run_git(repo, "config", "remote.origin.mirror", "true")
    assert "a mirror push" in bash(repo, "git push")
    run_git(repo, "switch", "-q", "main")
    run_git(repo, "config", "--unset", "remote.origin.mirror")
    assert "a push of main" in bash(repo, "git push --recurse-submodules no origin")


def test_the_checkout_that_holds_config_json_is_not_rewritten(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)
    f = repo / "config.json"
    f.write_text(json.dumps({"v": 1, "rules": [], "floor": {"refuse": True}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    for command in ("git checkout HEAD~1 -- config.json", "git stash", "git restore config.json", "git reset --hard",
                    "git switch feat/x", f"rm -rf '{repo.as_posix()}'", f"mv '{repo.as_posix()}' /tmp/x"):
        assert "floor" in (bash(repo, command) or ""), command
    assert "git's configuration" in edit(repo, repo / ".git" / "config", "[alias]\n  ship = push\n")
    assert "git's configuration" in bash(repo, "echo '[alias]' >> .git/config")
    for command in ("git status", "git pull --ff-only", "git log -1"):
        assert bash(repo, command) is None, command


# --- review round 3: classes, not spellings ------------------------------------------------------------------------

def _floor_in(repo, monkeypatch, **section):
    """config.json inside the git checkout ``repo``, the floor set by ``section``."""
    f = repo / "config.json"
    f.write_text(json.dumps({"v": 1, "rules": [], "floor": section}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    return f


@pytest.mark.parametrize("command", [
    "P=push git --config-env=alias.p=P p origin feat/x:main", "M=true git --config-env=remote.origin.mirror=M push origin",
    "git --config-env alias.p=P p origin x", "git -c core.quotepath=off push origin feat/x",
    "GIT_DIR=x/.git GIT_WORK_TREE=x git checkout HEAD~1 -- config.json", "export GIT_DIR=x/.git; git status",
    "GIT_CONFIG_COUNT=1 git push", "git config include.path /tmp/inc.cfg", "git config --global includeIf.x.path y",
    "git config remote.origin.url https://code.example/x", "git remote add --mirror=push m https://code.example/m",
])
def test_git_configuration_from_the_command_line_or_the_environment_is_refused(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    assert "floor:config" in (bash(repo, command) or ""), command


def test_alias_chains_and_shell_aliases(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    run_git(repo, "switch", "-q", "-c", "feat/x")
    run_git(repo, "config", "alias.a1", "a2")
    run_git(repo, "config", "alias.a2", "push")
    assert "a push of main" in bash(repo, "git a1 origin feat/x:main") and bash(repo, "git a1 origin feat/x") is None
    run_git(repo, "config", "alias.sp", "!git pu''sh origin feat/x:main")
    assert "floor's reading" in bash(repo, "git sp")
    run_git(repo, "config", "alias.lg", "!git log")
    assert "floor's reading" in bash(repo, "git lg")                                         # any shell alias
    run_git(repo, "config", "alias.loop", "loop")
    assert "floor's reading" in bash(repo, "git loop")


@pytest.mark.parametrize("command", [
    "git sparse-checkout set --no-cone /nothing", "git bisect start", "git stash list",
    "git filter-branch --tree-filter 'rm -f config.json' HEAD", "git commit -m x", "git pull origin feat/x",
])
def test_only_reads_run_in_the_checkout_that_holds_config_json(repo, monkeypatch, command):
    _floor_in(repo, monkeypatch, refuse=True)
    assert "only reads change nothing" in (bash(repo, command) or ""), command


def test_robocopy_mir_onto_the_checkout_is_a_removal(repo, tmp_path, monkeypatch):
    _floor_in(repo, monkeypatch, refuse=True)
    empty = tmp_path / "empty"
    assert "removes or moves" in bash(tmp_path, f"robocopy '{empty.as_posix()}' '{repo.as_posix()}' /MIR")
    assert bash(tmp_path, f"robocopy '{repo.as_posix()}' '{empty.as_posix()}' /E") is None   # a copy from it


@pytest.mark.parametrize("command", [
    "setx BRAIN_GUARD''_ALLOW floor", 'setx BRAIN_GUARD"_"ALLOW floor', "cmd //c setx BRAIN_GUARD^_ALLOW floor",
])
def test_a_name_spelled_otherwise_is_the_name(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch)                                                       # the owner guard, floor off
    assert "BRAIN_GUARD_ALLOW" in (bash(repo, command) or ""), command


def test_a_name_spelled_otherwise_in_powershell_and_json(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)
    assert pwsh(repo, "[Environment]::SetEnvironmentVariable('BRAIN_GUARD'+'_ALLOW','floor','User')")
    assert edit(repo, repo / ".claude" / "settings.json", '{"env": {"BRAIN_GUARD\\u005fALLOW": "floor"}}')
    config(tmp_path, monkeypatch, only=True)
    for command in ("[Environment]::SetEnvironmentVariable('BRAIN_'+'PYTHON','x','User')",
                    "Set-ItemProperty HKCU:/Environment -Name ('BRAIN_'+'PYTHON') -Value x",
                    "[Environment]::SetEnvironmentVariable($n, 'x', 'User')"):
        assert pwsh(repo, command), command
    for content in ('{"env": {"BRAIN\\u005fPYTHON": "x"}}', '{"env": {"BRAIN\\u005fCONFIG": "x"}}',
                    '{"disable\\u0041llHooks": true}', '{"enabledPlugins": {"brain-core@brain": false}}',
                    '{"env": {"CLAUDE_CONFIG_DIR": "C:/tmp/cc"}}', '{"env": {"PATH": "C:/tmp/fake"}}'):
        assert edit(repo, repo / ".claude" / "settings.json", content), content
    assert edit(repo, repo / ".claude" / "settings.json", '{"enabledPlugins": {"other@m": false}}') is None
    for command in ("setx CLAUDE_CONFIG_DIR C:/tmp/cc", "setx PATH C:/tmp/fake", "setx $n x"):
        assert bash(repo, command), command
    assert pwsh(repo, "[Environment]::SetEnvironmentVariable('Path', 'C:/tmp/fake', 'User')")


def test_the_interpreter_is_kept_and_a_removal_is_not_a_write(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    assert "removes or moves" in bash(repo, 'rm -rf "$BRAIN_HOME/venv"')
    assert "removes or moves" in bash(repo, 'mv "$BRAIN_HOME/venv" /tmp/v')
    assert "removes or moves" in bash(repo, 'rm -rf "$BRAIN_HOME"')
    assert "runs the guard" in bash(repo, 'cp x "$BRAIN_HOME/venv/Scripts/python.exe"')
    assert "floor" in bash(repo, "chmod 600 ~")   # round 6: a mode or an ACL above a kept path
    for command in ('cp notes.txt "$BRAIN_HOME/"', "tar -xzf x.tgz -C ~", "cp notes.txt ~/",
                    "find ~ -name '*.tmp' -delete", "unzip x.zip -d ~"):
        assert bash(repo, command) is None, command
    assert pwsh(repo, "Copy-Item notes.txt ~") is None


@pytest.mark.parametrize("command, refused", [
    ("echo 'export PATH=${HOME}/bin:$PATH' >> ~/.bashrc", False), ("echo 'cd $USERPROFILE/work' >> ~/.bashrc", False),
    ("echo 'export HOME=/x' >> ~/.bashrc", True),
])
def test_home_is_watched_where_it_is_set_only(repo, tmp_path, monkeypatch, command, refused):
    config(tmp_path, monkeypatch, only=True)
    assert bool(bash(repo, command)) is refused
    assert pwsh(repo, "Add-Content $PROFILE 'Set-Location $env:HOME'") is None


def test_pointing_head_is_no_symbolic_branch(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    assert bash(repo, "git symbolic-ref HEAD refs/heads/feat/x") is None


@pytest.mark.parametrize("command", [
    "gh api -XPATCH repos/o/r/git/refs/heads/main -fsha=abc -Fforce=true",
    "gh api graphql -f query='mutation{updateRef(input:{refId:\"x\",oid:\"y\",force:true}){clientMutationId}}'",
])
def test_the_code_hosts_ref_writes_by_other_spellings(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    assert "floor:main" in (bash(repo, command) or "")


def _guard_sh(tmp_path, command, floor_section, python=True, **extra):
    import os
    import shutil
    import subprocess
    sh = shutil.which("bash")
    if not sh:
        pytest.skip("no bash")
    cfg = tmp_path / "cfg" / "config.json"
    cfg.parent.mkdir(exist_ok=True)
    cfg.write_text(json.dumps({"v": 1, "floor": floor_section}), encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    if python:   # PATH's python3 that judges nothing (prints nothing, exits 0)
        fake = bin_ / "python3"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("BRAIN_PYTHON", "CLAUDE_BRAIN_DIR", "BRAIN_PERSONAL")}
    env.update(BRAIN_HOME=str(tmp_path / "home"), BRAIN_SELFTIME="0", BRAIN_CONFIG=str(cfg),
               PATH=os.pathsep.join([str(bin_), os.path.dirname(sh)]), **extra)
    from test_guards import PLUGIN
    return subprocess.run([sh, "-p", str(PLUGIN / "hooks" / "guard.sh"), "shell"],   # as hooks.json runs it
                          input=json.dumps(payload("Bash", tmp_path, command=command)), capture_output=True,
                          text=True, env=env, timeout=60).stdout


@pytest.mark.parametrize("python", [True, False], ids=["path-python", "no-python"])
def test_guard_sh_fails_closed_while_the_floor_is_on(tmp_path, python):
    out = _guard_sh(tmp_path, "setx BRAIN_GUARD_ALLOW floor", {"only": True}, python)
    assert "the locked floor is on" in out and "deny" in out
    assert "the locked floor is on" in _guard_sh(tmp_path, "git send-pack origin HEAD:main", {"refuse": True}, python)
    assert "the locked floor" not in _guard_sh(tmp_path, "setx X y", {}, python)       # the floor off: as before


# --- review round 4: wrappers, global options, the environment, copies, the plugin --------------------------------

@pytest.mark.parametrize("command", [
    "timeout 60 git push origin main", "env git push origin main", "nohup git push origin main",
    "bash -c 'git push origin main'", "sh -c \"git push -f origin feat/x\"", "cmd //c git push origin main",
    "eval \"git push origin main\"", "timeout 60 git -c alias.p=push p origin feat/x:main",
    "echo main | xargs git push origin", "git --attr-source HEAD push origin feat/x:main",
    "git --git-dir=.git push origin feat/x", "git frobnicate origin", "bash -c \"$CMD\"",
])
def test_wrappers_global_options_and_unknown_subcommands(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    run_git(repo, "switch", "-q", "-c", "feat/x")
    assert "floor:" in (bash(repo, command) or ""), command


def test_powershell_launchers(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    assert pwsh(repo, "Start-Process git -ArgumentList 'push','origin','main' -Wait")
    assert pwsh(repo, "cmd /c git push origin main")
    assert bash(repo, "git -C . --no-pager log -1") is None and bash(repo, "timeout 60 git status") is None


def test_wrapped_commands_in_the_config_checkout(repo, monkeypatch):
    _floor_in(repo, monkeypatch, refuse=True)
    for command in ("timeout 60 git checkout HEAD~1 -- config.json", "env git checkout HEAD~1 -- config.json",
                    "bash -c 'git checkout HEAD~1 -- config.json'"):
        assert "floor" in (bash(repo, command) or ""), command


@pytest.mark.parametrize("command", [
    'env GIT_""CONFIG_COUNT=1 GIT_""CONFIG_KEY_0=alias.p GIT_""CONFIG_VALUE_0=push git p origin feat/x:main',
    'export GIT_""CONFIG_COUNT=1; git push origin', "printf -v GIT_CONFIG_COUNT 1; export GIT_CONFIG_COUNT",
    "XDG_CONFIG_HOME=/tmp/x git status", "HOME=/tmp/h git status", "export $n=1", "declare -x \"$n\"=1",
    "BASH_ENV=/tmp/x.sh bash -c true", "export PATH=/tmp/fake:$PATH",
])
def test_every_way_to_set_a_watched_variable_is_refused(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "floor:config" in (bash(repo, command) or ""), command


@pytest.mark.parametrize("command", [
    "${env:GIT_CONFIG_COUNT}='1'", "$env:GIT_DIR = 'x'", "Set-Item env:GIT_CONFIG_COUNT 1",
    "[Environment]::SetEnvironmentVariable('GIT_CONFIG_COUNT','1')",
    "$n='BRAIN_GUARD';$n+='_ALLOW';Set-ItemProperty HKCU:\\Environment $n floor",
    "[Microsoft.Win32.Registry]::SetValue('HKEY_CURRENT_USER\\Environment', $n, 'floor')",
    "[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment',$true).SetValue($n,'floor')",
    "reg import x.reg", "New-ItemProperty HKCU:\\Environment $n -Value floor",
])
def test_powershell_variables_and_the_environment_key(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "floor:config" in (pwsh(repo, command) or ""), command


@pytest.mark.parametrize("command", ["export PYTHONPATH=src", "echo $HOME", "FOO=${HOME}/x make",
                                     "PYTHONPATH=src python -m pytest -q", "reg query HKCU\\Environment"])
def test_reading_variables_passes(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert bash(repo, command) is None, command


def test_a_copy_or_an_extraction_is_judged_on_what_it_writes(repo, tmp_path, monkeypatch):
    _floor_in(repo, monkeypatch, refuse=True)
    p, evil = repo.as_posix(), (tmp_path / "evil").as_posix()
    for command in (f"cp {evil}/config.json '{p}'", f'cp {evil}/personal.json "$BRAIN_HOME/"',
                    f'cp -r {evil}/. "$BRAIN_HOME"', f'cp -r {evil}/venv "$BRAIN_HOME/"',
                    f"rsync {evil}/config.json '{p}/'", f"robocopy {evil} '{p}' config.json",
                    f"tar -xf evil.tar -C '{p}'", f"unzip -o evil.zip -d '{p}'"):
        assert "floor" in (bash(tmp_path, command) or ""), command
    for command in (f"Copy-Item {evil}/config.json -Destination '{p}' -Force",
                    f"Expand-Archive evil.zip -DestinationPath '{p}' -Force"):
        assert "floor" in (pwsh(tmp_path, command) or ""), command
    for command in (f"cp notes.txt '{p}/docs/'", "cp notes.txt ~/", "tar -xzf x.tgz -C ~",
                    'cp -r src "$BRAIN_HOME/notes/"', f"tar -tf evil.tar -C '{p}'"):
        assert bash(tmp_path, command) is None, command


def test_the_config_checkout_pulls_only_its_own_branch(repo, monkeypatch):
    _floor_in(repo, monkeypatch, refuse=True)
    for command in ("git pull --ff-only origin feat/off", "git remote set-url origin https://code.example/evil.git",
                    "git config branch.main.merge refs/heads/feat/off", "git remote add other https://code.example/o"):
        assert "floor" in (bash(repo, command) or ""), command
    for command in ("git pull --ff-only", "git config --get user.name", "git remote -v", "git config user.name"):
        assert bash(repo, command) is None, command


def test_bash_reads_no_startup_file_for_the_guard(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    settings = repo / ".claude" / "settings.json"
    for content in ('{"env": {"BASH_ENV": "C:/tmp/x.sh"}}', '{"env": {"SHELLOPTS": "noexec"}}',
                    '{"env": {"CLAUDE_PLUGIN_ROOT": "C:/tmp/p"}}', '{"env": {"ENV": "C:/tmp/x.sh"}}'):
        assert edit(repo, settings, content), content
    assert bash(repo, "setx BASH_ENV C:/tmp/x.sh") and bash(repo, "setx SHELLOPTS noexec")
    hooks = json.loads((guards_plugin() / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    commands = [h["command"] for e in hooks["hooks"].values() for m in e for h in m["hooks"] if "guard.sh" in h["command"]]
    assert commands and all(c.startswith("bash -p ") for c in commands)
    startup = tmp_path / "exit0.sh"
    startup.write_text("exit 0\n", encoding="utf-8")
    out = _guard_sh(tmp_path, "git push origin main", {"only": True}, False, BASH_ENV=startup.as_posix(),
                    SHELLOPTS="noexec")
    assert "the locked floor is on" in out                                           # bash -p read neither


def guards_plugin():
    from test_guards import PLUGIN
    return PLUGIN


def test_the_plugin_that_runs_the_guard_is_kept(repo, tmp_path, monkeypatch):
    from pathlib import Path
    config(tmp_path, monkeypatch, only=True)
    plugins = Path.home() / ".claude" / "plugins"
    assert edit(repo, plugins / "cache" / "m" / "brain-core" / "1.0" / "hooks" / "guard.sh", "exit 0\n")
    assert edit(repo, plugins / "installed_plugins.json", "{}")
    assert bash(repo, f"rm -rf '{(plugins / 'cache').as_posix()}'")
    for command in ("claude plugin disable brain-core@brain", "claude plugin uninstall brain-core@brain",
                    "claude plugin marketplace remove brain"):
        assert bash(repo, command), command
    assert bash(repo, "claude plugin disable other@market") is None


def test_an_edit_is_judged_on_the_file_it_leaves(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)                                                       # the owner guard, floor off
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"disableXHooks": true, "env": {"BRAIN_GUARD_XLLOW": "floor"}, '
                        '"enabledPlugins": {"brain-core@brain": true}}', encoding="utf-8")
    assert decide(payload("Edit", repo, file_path=str(settings), old_string="XLLOW", new_string="ALLOW"))
    rc = repo / ".bashrc"
    rc.write_text("export BRAIN_GUARD_XLLOW=floor\n", encoding="utf-8")
    assert decide(payload("Edit", repo, file_path=str(rc), old_string="X", new_string="A"))
    config(tmp_path, monkeypatch, only=True)
    assert decide(payload("Edit", repo, file_path=str(settings), old_string="X", new_string="All"))
    assert decide(payload("Edit", repo, file_path=str(settings), old_string="true}}", new_string="false}}"))
    assert decide(payload("Edit", repo, file_path=str(settings), old_string="disableXHooks", new_string="other"))\
        is None                                                                           # nothing added


def test_a_movers_target_is_no_source(repo, tmp_path, monkeypatch):
    import os
    config(tmp_path, monkeypatch, only=True)
    parent = os.path.dirname(os.environ["BRAIN_HOME"]).replace("\\", "/")
    assert pwsh(repo, f"Move-Item -Destination '{parent}' -Path a.txt") is None
    assert bash(repo, f"mv -t '{parent}' a.txt") is None and bash(repo, f"mv a.txt '{parent}/sub/'") is None
    assert bash(repo, f"mv '{os.environ['BRAIN_HOME']}' /tmp/x")


# --- review round 5: writes judged by the path they reach (round 6: the floor read from config.json and the lock) ---

def test_an_unreadable_config_json_reads_as_the_floor_on(repo, tmp_path, monkeypatch):
    f = config(tmp_path, monkeypatch)
    f.write_text("{oops", encoding="utf-8")
    assert guards.floor_settings(guards.config.load())["refuse"] is True


@pytest.mark.parametrize("command", [
    "cp {evil}/config.json '{p}'", "mv {evil}/config.json '{p}/'", "patch '{p}/config.json' x.diff",
    "git -C '{p}' log -1 --format=x --output=config.json", "icacls '{p}/config.json' /deny x:(R)",
])
def test_a_local_write_of_config_json_is_refused(repo, tmp_path, monkeypatch, command):
    config(repo, monkeypatch, refuse=True)
    assert "floor" in (bash(tmp_path, command.format(evil=(tmp_path / "evil").as_posix(), p=repo.as_posix())) or "")


@pytest.mark.parametrize("command", [
    "cp {evil}/s.json '{p}/.claude/settings.json'", "cat {evil}/s.json > '{p}/.claude/settings.local.json'",
    "mv {evil}/s.json '{p}/.claude/settings.json'", "cp -r {evil}/. '{p}/.claude'",
])
def test_a_settings_file_changes_by_write_or_edit_only(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    (repo / ".claude").mkdir()
    assert "floor" in (bash(tmp_path, command.format(evil=(tmp_path / "evil").as_posix(), p=repo.as_posix())) or "")
    assert edit(repo, repo / ".claude" / "settings.json", '{"permissions": {}}') is None


def test_the_interpreter_and_python_startup_files_are_kept(repo, tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    config(tmp_path, monkeypatch, only=True)
    site = Path(sys.base_prefix) / "Lib" / "sitecustomize.py"
    assert "runs the guard" in (edit(repo, site, "import os; os._exit(0)\n") or "")
    assert "runs the guard" in (bash(repo, f"cp x.py '{site.as_posix()}'") or "")
    assert edit(repo, tmp_path / "pkgs" / "evil.pth", "import os\n")
    assert pwsh(repo, "New-CimInstance -ClassName Win32_Environment -Property @{Name='BRAIN_PYTHON'}")
    assert bash(repo, 'wmic environment create name="BRAIN_PYTHON",variablevalue="x",username="pc\\\\me"')


@pytest.mark.parametrize("command", [
    "if true; then git push origin main; fi", "for b in main; do git push origin feat/x:$b; done",
    "! git push origin main", "while true; do git push origin main; break; done",
    "f() { git push \"$@\"; }; f origin main", "git push origin feat/x:$(echo main)", "git push origin `echo main`",
])
def test_control_flow_and_unread_refspecs(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    assert "floor" in (bash(repo, command) or ""), command


@pytest.mark.parametrize("command", [
    "git log -1 --output=x.txt", "git diff --output=x.txt", "git grep -Ocp x", "git fetch --upload-pack=x origin",
    "git rebase -x 'cp a b' HEAD~1", "git bisect run sh -c x", "git submodule foreach x", "git difftool -x x",
    "git config core.fsmonitor x", "git config core.worktree x", "git config -f ~/.claude/settings.json a.b c",
    "git update-ref refs/heads/main HEAD",
    "git apply --unsafe-paths x.diff", "git config credential.helper x", "git config filter.x.clean y",
])
def test_git_options_that_write_or_run(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    assert "floor:config" in (bash(repo, command) or ""), command


@pytest.mark.parametrize("command", [
    "git log -1", "git diff --text", "git clean -fdx", "git push -u origin feat/x", "git config user.name x",
    "git config -f .git/config user.name x", "git commit -m \"export GIT_DIR=x is documented\"",
    "GIT_EDITOR=true git rebase --continue", "export GIT_EDITOR=true", "GIT_TRACE=1 git status", "ENV=prod make",
    "export CLAUDE_CODE_MAX_OUTPUT_TOKENS=1", "ls | xargs git add", "eval \"$(ssh-agent -s)\"",
    "reg add HKCU\\Software\\MyApp /v x /d 1 /f",
])
def test_ordinary_work_passes_under_the_floor(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, refuse=True)
    run_git(repo, "switch", "-q", "-c", "feat/x")
    assert bash(repo, command) is None, command


def test_start_process_of_a_program_that_is_not_git_passes(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, refuse=True)
    assert pwsh(repo, "Start-Process python -ArgumentList '-m','http.server'") is None


@pytest.mark.parametrize("command", [
    "export \"GIT_CONFIG_PARAMETERS='core.fsmonitor=cp a b; false'\"; git status",
    "env \"GIT_CONFIG_PARAMETERS='remote.origin.mirror=true' 'user.x=y z'\" git push origin",
    "set -a; : ${GIT_DIR:=x}; git status", "(( GIT_CONFIG_COUNT = 1 ))", "set -o allexport; git status",
])
def test_assignments_quoted_whole_or_by_expansion(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "floor:config" in (bash(repo, command) or ""), command


@pytest.mark.parametrize("command", [
    "New-Item -Path Env:\\GIT_DIR -Value x", "$e='env:GIT_DIR'; Set-Item $e x", "Rename-Item env:FOO GIT_DIR",
    "$env:GIT_CONFIG_PARAMETERS, $x = 'a', 1", "Copy-Item env:FOO env:GIT_DIR",
])
def test_the_powershell_env_provider(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "floor:config" in (pwsh(repo, command) or ""), command


def test_a_move_lands_like_a_copy(repo, tmp_path, monkeypatch):
    _floor_in(repo, monkeypatch, refuse=True)
    p, evil = repo.as_posix(), (tmp_path / "evil").as_posix()
    for command in (f"mv -t '{p}' {evil}/config.json", f'mv {evil}/personal.json "$BRAIN_HOME/"'):
        assert "floor" in (bash(tmp_path, command) or ""), command
    assert "floor" in (pwsh(tmp_path, f"Move-Item {evil}/config.json '{p}' -Force") or "")


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


# --- review round 6: what the lock does not cover, by class --------------------------------------------------------

@pytest.mark.parametrize("command", [
    "time -p cp {evil}/s.json {p}/.claude/settings.json", "time -p git push origin feat/x:main",
    "time -- git push origin feat/x:main", "time -p setx BRAIN_PYTHON C:/x",
    "coproc cp {evil}/s.json {p}/.claude/settings.json; wait", "coproc git push origin feat/x:main",
    "coproc setx BRAIN_PYTHON C:/x", "coproc P {{ git push origin main; }}",
])
def test_time_p_and_coproc_hide_no_command(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    (repo / ".claude").mkdir()
    cmd = command.format(evil=(tmp_path / "evil").as_posix(), p=repo.as_posix())
    assert "floor" in (bash(repo, cmd) or ""), cmd


def test_time_p_hides_nothing_from_the_other_guards(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)   # the floor off: the power guard reads past time -p
    assert "power" in (bash(repo, "time -p shutdown /s /t 0") or "")
    assert guards._unwrap(["time", "-p", "--", "git", "push"]) == ["git", "push"]
    assert guards._unwrap(["coproc", "NAME", "{", "git", "push"]) == ["git", "push"]
    assert guards._unwrap(["coproc", "git", "push"]) == ["git", "push"]


def _evil_branch(repo):
    """A branch feat/evil whose commit adds .claude/settings.json turning every hook off, the work tree on main."""
    (repo / ".claude").mkdir(exist_ok=True)
    run_git(repo, "checkout", "-q", "-b", "feat/evil")
    (repo / ".claude" / "settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")
    run_git(repo, "add", ".claude/settings.json")
    run_git(repo, "commit", "-q", "-m", "evil")
    run_git(repo, "checkout", "-q", "main")


@pytest.mark.parametrize("command", [
    "git checkout -- .claude/settings.json", "git restore --source=feat/evil .claude/settings.json",
    "git update-index --add --cacheinfo 100644,0123456789abcdef0123456789abcdef01234567,.claude/settings.json",
    "git merge feat/evil", "git checkout feat/evil", "git switch feat/evil", "git cherry-pick feat/evil",
    "git reset --hard feat/evil", "git restore -s feat/evil .", "git worktree add ../w feat/evil",
    "git update-index --index-info",
])
def test_git_writing_a_settings_file_is_refused(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    _evil_branch(repo)
    assert "Claude Code's settings" in (bash(repo, command) or "") or "floor" in (bash(repo, command) or ""), command


def test_git_work_that_brings_no_settings_file_passes(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    run_git(repo, "checkout", "-q", "-b", "feat/ok")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    run_git(repo, "add", "a.txt")
    run_git(repo, "commit", "-q", "-m", "ok")
    run_git(repo, "checkout", "-q", "main")
    for command in ("git merge feat/ok", "git checkout feat/ok", "git switch -c feat/new", "git reset --hard HEAD",
                    "git cherry-pick feat/ok", "git stash", "git restore a.txt"):
        assert bash(repo, command) is None, command


def test_an_archive_holding_a_settings_file_is_refused(repo, tmp_path, monkeypatch):
    import tarfile
    import zipfile
    config(tmp_path, monkeypatch, only=True)
    s = tmp_path / "s.json"
    s.write_text('{"disableAllHooks": true}', encoding="utf-8")
    with tarfile.open(tmp_path / "s.tar", "w") as tf:
        tf.add(s, ".claude/settings.json")
    with zipfile.ZipFile(tmp_path / "s.zip", "w") as z:
        z.write(s, ".claude/settings.local.json")
    with tarfile.open(tmp_path / "ok.tar", "w") as tf:
        tf.add(s, "data/s.json")
    (tmp_path / "s.7z").write_bytes(b"7z\xbc\xaf\x27\x1c")   # a 7z archive: its members cannot be listed
    t, p = tmp_path.as_posix(), repo.as_posix()
    for command in (f"tar -xf {t}/s.tar -C {p}", f"tar xf {t}/s.tar -C {p}", f"unzip -o {t}/s.zip -d {p}",
                    f"curl -s https://x.example/a.tgz | tar -xz -C {p}", f"7z x {t}/s.7z -o{p}"):
        assert "floor" in (bash(repo, command) or ""), command
    assert "floor" in (pwsh(repo, f"Expand-Archive -Path {t}/s.zip -DestinationPath {p}") or "")
    assert bash(repo, f"tar -xf {t}/ok.tar -C {p}") is None


@pytest.mark.parametrize("command", [
    "f() ( cp \"$1\" \"$2\" ); f a b", "f() [[ -n x ]]; f", "function f ( cp a b ); f",
    "shopt -s expand_aliases; alias c=cp\nc a .claude/settings.json", "alias c=cp", "f() if true; then cp a b; fi",
])
def test_functions_of_any_body_and_aliases_are_refused(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "floor" in (bash(repo, command) or ""), command


def test_powershell_aliases_are_refused(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    assert "floor" in (pwsh(repo, "Set-Alias c Copy-Item; c a b") or "")


@pytest.mark.parametrize("command", [
    "declare -x -t \"GIT_CONFIG_PARAMETERS='core.fsmonitor=cp a b; false'\"; git status -s",
    "set -o errexit -o allexport; for GIT_DIR in x/.git; do :; done; git status",
    "shopt -so allexport", "select GIT_DIR in x; do break; done", "getopts a GIT_DIR", "mapfile -t GIT_DIR < f",
    "for GIT_WORK_TREE in x; do :; done", "readarray PATH < f",
])
def test_every_bash_form_of_assignment_is_read(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "floor:config" in (bash(repo, command) or ""), command


@pytest.mark.parametrize("command", [
    "$env:FOO='x/.git'; Get-Item Env:FOO | Rename-Item -NewName GIT_DIR", "$p='Env:'; New-Item -Path $p -Name GIT_DIR -Value x",
    "$psi.EnvironmentVariables['GIT_DIR']='x'", "$psi.Environment.Add('GIT_DIR', 'x')",
])
def test_every_powershell_form_of_assignment_is_read(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "floor:config" in (pwsh(repo, command) or ""), command


def test_prose_is_only_git_s_and_gh_s_message(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    assert bash(repo, 'git commit -m "set GIT_DIR=x in the docs"') is None
    assert bash(repo, 'gh pr create -t "set GIT_DIR=x" -b "PATH=y and more"') is None
    assert "floor" in (bash(repo, 'mytool -t "GIT_DIR=x y"') or "")


@pytest.mark.parametrize("command", [
    "git config protocol.ext.allow always", "git fetch -q \"ext::sh -c cp% a% b\"", "git clone fd::3 x",
    "git config submodule.x.update '!cp a b'", "git config interactive.diffFilter cat",
    "git config browser.x.cmd x", "git config web.browser x", "git config man.x.cmd x", "git config instaweb.httpd x",
    "git config sendemail.smtpServer /bin/x", "git config init.templateDir /tmp/t", "git config ssh.variant x",
    "git config trailer.x.command x", "git config hook.x.command x", "GIT_ALLOW_PROTOCOL=ext git fetch x",
    "git config credential.helper '!cp a b'", "git config core.hooksPath x", "git config core.fsmonitor x",
])
def test_git_keys_and_transports_that_run_a_program(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert "floor" in (bash(repo, command) or ""), command


@pytest.mark.parametrize("command", [
    "git config core.autocrlf false", "git config core.longpaths true", "git config core.filemode false",
    "git config --global core.autocrlf input", "git config credential.helper manager",
    "git config credential.helper 'cache --timeout=3600'", "git config diff.tool vscode",
    "git config branch.feat/x.description \"what it does\"", "git format-patch -o patches HEAD~1",
    "git fetch origin main:main",
])
def test_ordinary_repo_keys_pass_under_the_floor(repo, tmp_path, monkeypatch, command):
    config(tmp_path, monkeypatch, only=True)
    assert bash(repo, command) is None, command


def test_a_link_onto_a_settings_file_is_refused(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, only=True)
    o = repo.as_posix()
    for command in (f"cmd //c mklink {o}/.claude/settings.json C:/evil/s.json",
                    f"cmd /c mklink /H {o}/.claude/settings.local.json C:/evil/s.json",
                    f"ln -s /evil/s.json {o}/.claude/settings.json"):
        assert "floor" in (bash(repo, command) or ""), command
    assert "floor" in (pwsh(repo, f"New-Item -ItemType SymbolicLink -Path {o}/.claude/settings.json -Target x") or "")
    assert bash(repo, f"ln -s a.txt {o}/b.txt") is None


def test_an_acl_on_a_folder_above_a_kept_path_is_refused(repo, tmp_path, monkeypatch):
    from pathlib import Path
    config(tmp_path, monkeypatch, only=True)
    home = Path.home().as_posix()
    for command in (f"icacls {home}/.claude /deny x:(OI)(CI)(RX)", f"cacls {home}/.claude /E /D x",
                    f"icacls {home} /deny x:(OI)(CI)(RX)", f"chmod -R 000 {home}/.claude"):
        assert "floor" in (bash(repo, command) or ""), command
    assert bash(repo, "chmod +x a.sh") is None and bash(repo, "icacls a.txt /grant x:R") is None
