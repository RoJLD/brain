"""The floor's watched variables, narrowed (wi-brain-floor-watched-vars; brain.floor.watched, brain.floorenv.env,
brain.floorenv; docs/guards.md, « The environment »): every BRAIN_* name stays watched but those the engine says
why it lets through; BRAIN_CONFIG and BRAIN_PROJECTS pass as a literal path inside a worktree of the repository that
holds config.json; BRAIN_CONFIG never lowers the floor the guard holds; the checkout that holds config.json pulls only
its upstream, main or master of a remote; guard.sh's pre-filter starts Python for every watched assignment."""

import json
import os

import pytest
from brain import config, faults, floor, floorenv, floorguard, guards
from conftest import run_git
from test_floor import _floor_in, edit
from test_guards import bash, pwsh


@pytest.fixture(autouse=True)
def held(monkeypatch):
    """A floor-only machine whose lock holds (as test_floor's parser tests): brain.floor.unlocked says ''."""
    monkeypatch.setattr(floor, "unlocked", lambda *a, **k: "")


@pytest.fixture
def repo(git_repo):
    run_git(git_repo, "remote", "add", "origin", "https://code.example/ada/lab.git")
    run_git(git_repo, "config", "branch.main.remote", "origin")
    run_git(git_repo, "config", "branch.main.merge", "refs/heads/main")
    return git_repo


@pytest.fixture
def tree(repo, tmp_path, monkeypatch):
    """The checkout that holds config.json (floor.refuse on) with one linked worktree: (checkout, worktree)."""
    _floor_in(repo, monkeypatch, refuse=True)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "config")
    w = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-q", "-b", "feat/x", str(w))
    return repo, w


def refused(cwd, command, ps=False):
    reason = (pwsh if ps else bash)(cwd, command)
    return bool(reason) and "floor" in reason


# --- the Brain's own variables -------------------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "BRAIN_STRICT=1 brain check", "export BRAIN_STRICT=0; brain check --all", "BRAIN_READ_HINT=0 brain x",
    "env BRAIN_WAIT_HINT=0 BRAIN_BUDGET_WATCH=0 brain y", "declare -x BRAIN_STRICT=1",
])
def test_read_path_variables_pass(tree, command):
    assert not refused(tree[0], command), command


def test_read_path_variables_pass_in_powershell(tree):
    assert not refused(tree[0], "$env:BRAIN_STRICT = '1'; brain check", ps=True)


@pytest.mark.parametrize("command", ["BRAIN_NOW=2030-01-31 brain quiet", "BRAIN_FAULT=net:timeout brain sync",
                                     "export BRAIN_NOW=+3d; brain journal last"])
def test_the_clock_and_faults_pass_off_a_scratch_home_only(tree, monkeypatch, command):
    monkeypatch.setattr(faults, "scratch", lambda: False)
    assert not refused(tree[0], command), command
    monkeypatch.setattr(faults, "scratch", lambda: True)   # a scratch home honours them: the guard's then watched
    assert refused(tree[0], command), command


@pytest.mark.parametrize("command", [
    "BRAIN_GUARD_ALLOW=floor claude -p x", "BRAIN_PYTHON=C:/x/python.exe claude", "BRAIN_HOME=C:/evil claude -p x",
    "BRAIN_PERSONAL=C:/evil claude", "BRAIN_AGENT_SESSION= claude -p x", "BRAIN_IPC_TOKEN_FILE=x claude",
    "BRAIN_ROOT=C:/evil brain sync", "BRAIN_SOMETHING_NEW=1 brain x", "BRAIN_STRICTER=1 brain x",
    "BRAIN_STRICT_X=1 brain x", "BRAIN_NOW2=x brain x", "BRAIN_STR''ICT_X=1 brain x", "BRAIN_HO^ME=x claude",
    "export BRAIN_STRICT=1 BRAIN_HOME=C:/evil", "BRAIN_HOME[0]=C:/evil claude", "PATH[0]=C:/evil claude",
    "declare -n BRAIN_STRICT=BRAIN_HOME", "for BRAIN_HOME in C:/evil; do claude; done",
])
def test_every_other_brain_variable_stays_watched(tree, monkeypatch, command):
    monkeypatch.setattr(faults, "scratch", lambda: False)
    assert refused(tree[0], command), command


def test_a_name_in_any_case_where_names_have_none():
    """Windows reads an environment variable's name in any case (brain_home=x is a native program's BRAIN_HOME): the
    names but HOME and PATH, which bash keeps beside a lowercase shell variable, are read in any case there."""
    nt, posix = floor.env_assign(False, True), floor.env_assign(False, False)
    for text in ("brain_home=C:/evil claude", "Brain_Guard_Allow=floor claude", "git_dir=x git status",
                 "export brain_python=x", "claude_config_dir=x claude"):
        assert nt.search(text) and not posix.search(text), text
    for text in ("brain_strict=1 brain x", "path=$(pwd)", "while read -r path; do echo $path; done", "home=~",
                 "path=x; echo $path", "Write-Output $env:Path", "export X=$path",
                 "export X=/a/path", "for path in a b; do :; done"):
        assert not nt.search(text), text
    assert nt.search("PATH=/x claude") and nt.search("$env:path = 'x'")
    # their exported forms do reach a native program (review: export path=x; claude, home=x claude)
    for text in ("export path=C:/evil claude -p x", "declare -x path=C:/evil claude", "export home=C:/evil",
                 "typeset -x home=/evil", "home=C:/evil claude -p x", "path=C:/evil:$PATH claude -p x",
                 "env path=C:/evil claude", "env home=/e claude", "local -x Path=x", "x; Home=/e git push"):
        assert nt.search(text) and not posix.search(text), text


# --- BRAIN_CONFIG and BRAIN_PROJECTS: a worktree of the same repository ------------------------------------------

def _forms(path):
    return [f"BRAIN_CONFIG={path}/config.json brain audit", f"BRAIN_PROJECTS={path}/projects.yaml brain audit --diff",
            f"BRAIN_CONFIG='{path}/config.json' brain x", f'export BRAIN_CONFIG="{path}/config.json"; brain x',
            f"env BRAIN_PROJECTS={path}/projects.yaml brain y", f"cd x && BRAIN_CONFIG={path}/config.json brain z"]


def test_a_worktree_of_the_same_repository_passes(tree):
    checkout, w = tree
    for path in (checkout.as_posix(), w.as_posix()):
        for command in _forms(path):
            assert not refused(w, command), command
    win = str(w)   # backslashes: quoted in bash, as PowerShell writes them
    assert not refused(w, f'BRAIN_CONFIG="{win}\\config.json" brain x')
    assert not refused(w, f"$env:BRAIN_PROJECTS = '{win}\\projects.yaml'; brain audit --diff", ps=True)
    assert not refused(w, f'$env:BRAIN_CONFIG = "{win}\\config.json"', ps=True)
    if os.name == "nt":   # Git Bash's /e/x is E:/x for a native program
        msys = "/" + w.as_posix()[0].lower() + w.as_posix()[2:]
        assert not refused(w, f"BRAIN_PROJECTS={msys}/projects.yaml brain audit")


def test_anything_else_stays_watched(tree, tmp_path):
    checkout, w = tree
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    W, win = w.as_posix(), str(w)
    commands = [
        *_forms(elsewhere.as_posix()),
        "BRAIN_CONFIG=config.json brain x", "BRAIN_CONFIG=./wt/config.json brain x", f"BRAIN_CONFIG={W}/../elsewhere/c brain",
        'BRAIN_CONFIG=$PWD/config.json brain x', f'BRAIN_CONFIG="{W}/$(echo x)" brain x', "BRAIN_CONFIG=~/c.json brain",
        f"BRAIN_CONFIG={W}/config.json BRAIN_HOME={W} brain x", f"export BRAIN_CONFIG={W}/c.json BRAIN_GUARD_ALLOW",
        f"BRAIN_CONFIG={W}/c.json\"BRAIN_HOME=x\" brain", f"BRAIN_CONFIG={W}/c.json'x' brain",
        f"BRAIN_CONFIG+={W}/c.json brain", f"BRAIN_CONFIG={win}\\config.json brain x",
        f"read BRAIN_CONFIG <<< {W}/c.json", f"printf -v BRAIN_CONFIG {W}/c.json", "BRAIN_CONFIG=//host/share/c brain",
        f"BRAIN_HOME={W} claude",
    ]
    for command in commands:
        assert refused(w, command), command
    for command in (f"$env:BRAIN_CONFIG = {win}\\c.json", f"${{env:BRAIN_CONFIG}} = '{win}\\c.json'",
                    f"$env:BRAIN_CONFIG = \"{win}\\$x\"", f"Set-Item env:BRAIN_CONFIG '{win}\\c.json'"):
        assert refused(w, command, ps=True), command


def test_a_worktree_git_no_longer_lists_is_none(tree):
    checkout, w = tree
    W = w.as_posix()
    run_git(checkout, "worktree", "remove", "--force", str(w))
    w.mkdir()                                           # a folder made where a worktree was: not one now
    (w / ".git").write_text(f"gitdir: {checkout.as_posix()}/.git/worktrees/wt\n", encoding="utf-8")
    assert refused(checkout, f"BRAIN_CONFIG={W}/config.json brain x")


def test_a_link_inside_a_worktree_is_judged_where_it_leads(tree, tmp_path):
    checkout, w = tree
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, w / "out", target_is_directory=True)
    except (OSError, NotImplementedError):
        import _winapi
        try:
            _winapi.CreateJunction(str(outside), str(w / "out"))
        except (OSError, AttributeError):
            pytest.skip("no link")
    assert refused(w, f"BRAIN_CONFIG={w.as_posix()}/out/config.json brain x")


# --- BRAIN_CONFIG never lowers the floor --------------------------------------------------------------------------

def _anchored(tmp_path, monkeypatch, anchor_floor, named_floor):
    """A personal brain the pointer names (the anchor) and another config.json BRAIN_CONFIG names: (anchor, named)."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    personal = tmp_path / "personal"
    personal.mkdir()
    anchor = personal / "config.json"
    anchor.write_text(json.dumps({"v": 1, "rules": [], "floor": anchor_floor}), encoding="utf-8")
    (home / "personal.json").write_text(json.dumps({"root": str(personal)}), encoding="utf-8")
    named = tmp_path / "named" / "config.json"
    named.parent.mkdir()
    named.write_text(json.dumps({"v": 1, "rules": [], "floor": named_floor}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_HOME", str(home))
    monkeypatch.setenv("BRAIN_CONFIG", str(named))
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    return anchor, named


def test_brain_config_never_lowers_the_floor(repo, tmp_path, monkeypatch):
    anchor, named = _anchored(tmp_path, monkeypatch, {"refuse": True}, {})
    assert config.anchored().file == anchor
    assert "breaks the locked floor" in bash(repo, "git push origin main")       # the anchor's floor holds
    assert "sets the floor" in edit(repo, anchor, '{"v": 1, "floor": {}}')        # and its file is kept
    assert "sets the floor" in edit(repo, named, '{"v": 1, "floor": {}}')
    assert guards._floor_state() == "on"


def test_the_anchor_is_none_without_brain_config_or_for_the_same_file(repo, tmp_path, monkeypatch):
    anchor, named = _anchored(tmp_path, monkeypatch, {}, {"refuse": True})
    assert config.anchored().file == anchor
    assert "breaks the locked floor" in bash(repo, "git push origin main")       # the named file's floor holds
    monkeypatch.setenv("BRAIN_CONFIG", str(anchor))
    assert config.anchored() is None
    monkeypatch.delenv("BRAIN_CONFIG")
    assert config.anchored() is None
    assert bash(repo, "git push origin main") is None                            # both off: the floor is off


def test_an_unreadable_anchor_holds_the_floor_on(repo, tmp_path, monkeypatch):
    anchor, _ = _anchored(tmp_path, monkeypatch, {}, {})
    anchor.write_text("{not json", encoding="utf-8")
    assert "breaks the locked floor" in bash(repo, "git push origin main")


def test_the_core_plugin_of_either_config_is_kept(repo, tmp_path, monkeypatch):
    anchor, named = _anchored(tmp_path, monkeypatch, {"refuse": True}, {})
    data = json.loads(anchor.read_text(encoding="utf-8"))
    data["adapters"] = {"claude": {"plugin": "ada-core", "marketplace": "ada-brain"}}
    anchor.write_text(json.dumps(data), encoding="utf-8")
    settings = repo / ".claude" / "settings.json"
    assert "core plugin off" in edit(repo, settings, '{"enabledPlugins": {"ada-core@ada-brain": false}}')
    assert "turns off the plugin" in bash(repo, "claude plugin disable ada-core@ada-brain")


# --- the checkout that holds config.json pulls its upstream only ---------------------------------------------------

@pytest.mark.parametrize("command", ["git pull", "git pull --ff-only", "git pull --ff-only origin main",
                                     "git pull --rebase", "git pull -q --no-rebase origin", "git pull origin refs/heads/main"])
def test_the_checkout_pulls_its_upstream(tree, command):
    assert not refused(tree[0], command), command


@pytest.mark.parametrize("command", [
    "git pull origin feat/x", "git pull upstream main", "git pull origin main:main", "git pull origin +main",
    "git pull -s ours", "git pull --allow-unrelated-histories", "git pull --rebase=interactive", "git pull -X theirs",
    "git pull --recurse-submodules", "git pull --ff-o", "git pull https://code.example/evil.git main",
    "git commit -m x", "git switch feat/x",
])
def test_the_checkout_pulls_nothing_else(tree, command):
    assert refused(tree[0], command), command


def test_a_pull_is_judged_by_the_upstream_it_reads_when_it_runs(tree):
    """Whoever set it (git branch -u, git push -u, a worktree sharing the configuration), the upstream git reads
    when the pull is judged says what the pull brings."""
    checkout, w = tree
    run_git(checkout, "branch", "evil")
    run_git(w, "branch", "-u", "evil", "main")                                     # a local branch: remote "."
    assert "upstream is ./evil" in bash(checkout, "git pull --ff-only")
    run_git(w, "config", "branch.main.remote", "origin")
    run_git(w, "config", "branch.main.merge", "refs/heads/feat/off")              # another branch of the remote
    assert "upstream is origin/feat/off" in bash(checkout, "git pull")
    run_git(w, "config", "branch.main.merge", "refs/heads/main")
    run_git(w, "remote", "set-url", "origin", str(checkout.parent / "evil.git"))  # a local path
    assert "a local path" in bash(checkout, "git pull")
    run_git(checkout, "switch", "-q", "--detach")
    assert "no branch is checked out" in bash(checkout, "git pull")


def test_a_worktree_of_the_repository_writes_no_remote(tree, tmp_path):
    checkout, w = tree
    for command in ("git remote set-url origin https://code.example/evil.git", "git remote add evil https://e/x",
                    "git remote rename origin old", "git remote remove origin", "git -C {} remote rm origin"):
        assert "pulls from these remotes" in (bash(w, command.format(w.as_posix())) or ""), command
    for command in ("git remote -v", "git remote", "git remote show origin", "git remote get-url origin"):
        assert not refused(w, command), command
    other = tmp_path / "other"
    other.mkdir()
    run_git(other, "init", "-q")
    assert not refused(other, "git remote add origin https://code.example/o.git")   # another repository


# --- guard.sh starts Python for every watched assignment ------------------------------------------------------------

PREFILTER = [
    "BRAIN_HOME=C:/evil claude -p hi", "BRAIN_GUARD_ALLOW=floor claude -p hi", "brain_ho''me=x claude",
    "BRAIN_HO^ME=x claude", "BRAIN_CONFIG=E:/x/config.json brain audit", "$env:BRAIN_HOME='C:/e'; claude -p hi",
    "HOME=/tmp/h claude", "PATH=/tmp:$PATH claude -p x", "PATH[0]=/x claude", "export BRAIN_HOME",
    ": ${BRAIN_HOME:=x}; claude", "(( GIT_CONFIG_COUNT = 1 ))", "set -a; claude", "set -o allexport", "shopt -so allexport",
    "for BRAIN_HOME in x; do claude; done", "read BRAIN_HOME", "printf -v BRAIN_HOME x", "mapfile BRAIN_HOME",
    "getopts ab BRAIN_HOME", "Set-Item env:BRAIN_HOME x", "New-Item -Path Env:\\BRAIN_HOME -Value x",
    "export $n=x", "[Environment]::SetEnvironmentVariable('BRAIN_HOME','x')", "select GIT_DIR in a; do :; done",
]


def test_guard_sh_starts_python_for_every_watched_assignment():
    from test_guards import _needs_python
    missed = [c for c, started in zip(PREFILTER, _needs_python(PREFILTER)) if not started]
    assert not missed
    plain = ["ls -la", "cat x | head", "echo hi", "grep -n path x", "Get-Content x > $null", "cd notes && ls",
             "printf '%s' \"$x\"", "for f in *.md; do wc -l $f; done", "while read -r line; do echo \"$line\"; done < f"]
    assert _needs_python(plain) == [False] * len(plain)


def test_every_prefilter_shape_is_one_the_floor_refuses(tree, monkeypatch):
    """The pre-filter's list is the floor's: each shape above is refused once Python judges it."""
    monkeypatch.setattr(faults, "scratch", lambda: False)
    ps = {"$env:BRAIN_HOME='C:/e'; claude -p hi", "Set-Item env:BRAIN_HOME x", "New-Item -Path Env:\\BRAIN_HOME -Value x",
          "[Environment]::SetEnvironmentVariable('BRAIN_HOME','x')"}
    for command in PREFILTER:
        assert refused(tree[0], command, ps=command in ps), command


def test_guard_sh_holds_the_anchors_floor_when_it_cannot_judge(tmp_path):
    """guard.sh, with no Python that runs the guard: BRAIN_CONFIG naming a floor-off file does not hide the anchor's
    floor, and every call it would judge is refused."""
    import subprocess

    from test_capture import _bash
    from test_guards import PLUGIN, payload
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    home, personal, named = tmp_path / "home", tmp_path / "personal", tmp_path / "named.json"
    home.mkdir()
    personal.mkdir()
    (personal / "config.json").write_text('{"v": 1, "floor": {"refuse": true}}', encoding="utf-8")
    (home / "personal.json").write_text(json.dumps({"root": personal.as_posix()}), encoding="utf-8")
    named.write_text('{"v": 1, "floor": {}}', encoding="utf-8")
    import shutil
    tr = shutil.which("tr")   # common.sh reads the pointer with tr: its folder, with no Python in it
    if not tr or any(shutil.which(p, path=os.path.dirname(tr)) for p in ("python", "python3")):
        pytest.skip("no tr without a Python beside it")
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
    env.update(BRAIN_HOME=str(home), BRAIN_SELFTIME="0", PATH=os.pathsep.join([str(tmp_path / "no-python"),
                                                                               os.path.dirname(tr)]),
               BRAIN_CONFIG=str(named))
    out = subprocess.run([sh, str(PLUGIN / "hooks" / "guard.sh"), "shell"],
                         input=json.dumps(payload("Bash", tmp_path, command="rm -rf x")), capture_output=True,
                         text=True, env=env, timeout=60).stdout
    assert "the locked floor is on" in out


def test_floorguard_reads_the_worktrees_of_both_configs(tree):
    checkout, w = tree
    kept = floorguard.Kept(checkout / "config.json")
    trees = floorenv.worktrees(kept.configs)
    assert floorguard.g._real(str(checkout)) in trees and floorguard.g._real(str(w)) in trees
