"""The PreToolUse guards on the payloads Claude Code sends (Bash and PowerShell commands, Edit, Write, NotebookEdit)."""

import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import run_git

import brain
from brain import guards, paths, projects

PLUGIN = Path(brain.__file__).resolve().parents[1]  # the plugin that holds the brain package
# Fake keys are assembled at run time, so this file never holds one.
FAKE_KEY = "sk-ant-" + "api03-" + "Xy7Qa9Lm2Pz4" * 3
CLAUDE = "Co-Authored-By: " + "Claude Opus 5.5 <noreply@anthropic.com>"
GENERATED = "\N{ROBOT FACE} Generated with " + "[Claude Code](https://claude.com/claude-code)"
REAL_GITLEAKS = guards.gitleaks


@pytest.fixture
def plat(tmp_path, monkeypatch):
    """A platform folder with two production checkouts, a worktree nested in one, and the registry naming them."""
    demo = tmp_path / "demo"
    for name in ("demo-lab", "demo-data", "demo-lab2"):
        (demo / name / ".git").mkdir(parents=True)
    nested = demo / "demo-lab" / ".claude" / "worktrees" / "wt"
    nested.mkdir(parents=True)
    (nested / ".git").write_text("gitdir: ../../../.git/worktrees/wt\n", encoding="utf-8")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {(demo / 'demo-lab').as_posix()}, production: [., ../demo-data]}}\n",
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setattr(guards, "gitleaks", lambda repo: None)
    return demo


def payload(tool, cwd, **tool_input):
    return {"session_id": "s-1", "transcript_path": "C:/t/s-1.jsonl", "cwd": str(cwd), "permission_mode": "default",
            "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "tool_use_id": "toolu_01"}


def decide(p):
    """The refusal reason the hook prints, or None when the call passes."""
    out = io.StringIO()
    assert guards.main(stdin=io.StringIO(json.dumps(p)), stdout=out) == 0
    if not out.getvalue():
        return None
    hso = json.loads(out.getvalue())["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse" and hso["permissionDecision"] == "deny"
    assert "\n" not in hso["permissionDecisionReason"]
    return hso["permissionDecisionReason"]


def bash(cwd, command):
    return decide(payload("Bash", cwd, command=command, description="run"))


def pwsh(cwd, command):
    return decide(payload("PowerShell", cwd, command=command, description="run"))


# --- reading commands --------------------------------------------------------------------------------------------

def test_segments_follow_quotes_separators_and_heredocs():
    cmd = "cd \"D:\\work\\a b\" && git commit -m \"$(cat <<'EOF'\nl'item; ok\nEOF\n)\" | tail -1; echo x # c"
    open_, close = guards.SUBSHELL
    assert guards.segments(cmd) == [["cd", "D:\\work\\a b"], [open_], ["cat"], [close],
                                    ["git", "commit", "-m", "$(cat <<'EOF'\nl'item; ok\nEOF\n)"],
                                    ["tail", "-1"], ["echo", "x"]]
    assert guards.segments("git commit -F - <<'EOF'\ngit push; x'y\nEOF\ngit status") == [
        ["git", "commit", "-F", "-"], ["git", "status"]]
    ps = "Set-Location 'D:\\work\\it''s'; if ($?) { git commit -m @'\nl'item `n\n'@ }"
    assert guards.segments(ps, powershell=True) == [["Set-Location", "D:\\work\\it's"], ["if"], ["$?"],
                                                    ["git", "commit", "-m", "l'item `n"]]


def test_calls_track_the_folder(tmp_path):
    a = tmp_path / "a"
    cmds = guards.calls(f'cd "{a}" && git status; pushd b && git log; popd; git -C c diff', str(tmp_path))
    assert [(w[-1], d) for w, d in cmds] == [("status", str(a)), ("log", str(a / "b")), ("diff", str(a))]
    assert guards.git_parts(cmds[2][0], cmds[2][1])[0] == str(a / "c")


@pytest.mark.skipif(os.name != "nt", reason="Git Bash drive paths are a Windows shape")
def test_git_bash_drive_paths():
    assert guards._path("/d/work/demo", "C:\\x").lower() == "d:\\work\\demo"


# --- production checkouts ----------------------------------------------------------------------------------------

def test_edits_refused_in_production(plat):
    lab = plat / "demo-lab"
    reason = decide(payload("Edit", lab, file_path=str(lab / "src" / "x.py"), old_string="a", new_string="b"))
    assert "Edit refused" in reason and "production checkout" in reason and "BRAIN_GUARD_ALLOW=production" in reason
    assert reason.startswith("brain-core guard: ") and "Override (Ada only): BRAIN_GUARD_ALLOW=" in reason
    assert decide(payload("Write", plat, file_path=str(plat / "demo-data" / "README.md"), content="x"))
    assert decide(payload("NotebookEdit", lab, notebook_path="nb/a.ipynb", new_source="x"))
    assert decide(payload("Edit", lab, file_path="CLAUDE.md", old_string="a", new_string="b"))


def test_edits_allowed_outside_production_and_in_nested_worktrees(plat):
    wt = plat / "demo-lab" / ".claude" / "worktrees" / "wt"
    assert decide(payload("Edit", wt, file_path=str(wt / "src" / "x.py"), old_string="a", new_string="b")) is None
    assert decide(payload("Write", plat, file_path=str(plat / "demo-lab2" / "x.py"), content="x")) is None
    assert decide(payload("Write", plat, file_path=str(plat / "notes.md"), content="x")) is None


@pytest.mark.parametrize("command", [
    'cd "{lab}" && git add -A && git commit -m "fix"',
    "git -C {lab} checkout -b feat/x",
    "git -C {lab} switch feat/x",
    "cd {lab} && git reset --hard origin/main",
    "cd {lab} && git pull",
    "cd {lab} && git pull --rebase origin main",
    "cd {lab} && git stash",
    "cd {lab} && git push origin main",
    "cd {lab} && git merge origin/feat",
    "cd {lab} && git rebase main",
    "cd {md} && git checkout -- data/x.parquet",
    "cd {lab} && gh pr checkout 12",
])
def test_bash_git_changes_refused_in_production(plat, command):
    reason = bash(plat, command.format(lab=(plat / "demo-lab").as_posix(), md=(plat / "demo-data").as_posix()))
    assert reason and "refused in the production checkout" in reason


@pytest.mark.parametrize("command", [
    "Set-Location \"{lab}\"; git commit -m @'\nl'item\n'@",
    "git -C \"{lab}\" checkout main",
    "Push-Location {lab}; if ($?) {{ git stash pop }}",
])
def test_powershell_git_changes_refused_in_production(plat, command):
    assert "refused in the production checkout" in pwsh(plat, command.format(lab=plat / "demo-lab"))


@pytest.mark.parametrize("command", [
    "git -C {lab} pull --ff-only",
    "cd {lab} && git fetch origin && git status -sb",
    "cd {lab} && git worktree add ../wt-x -b feat/x origin/main",
    "git -C {lab} worktree remove ../wt-x && git -C {lab} worktree list",
    "cd {lab} && git log --oneline -5 && git diff --stat && git show HEAD",
    "cd {lab} && git branch -d feat/x && git stash list",
    "cd {lab} && python scripts/run_cycle.py --write data/qmd/x.parquet",
    "cd {lab} && git worktree add ../wt-y && cd ../wt-y && git commit -m x",
    "cd {lab}/.claude/worktrees/wt && git checkout -b feat/y && git commit -m y && git push -u origin feat/y",
    "git -C {lab} commit --help",
])
def test_reads_and_daily_coordinator_commands_allowed_in_production(plat, command):
    assert bash(plat, command.format(lab=(plat / "demo-lab").as_posix())) is None


def test_powershell_pull_ff_only_allowed(plat):
    assert pwsh(plat, f'Set-Location "{plat / "demo-lab"}"; if ($?) {{ git pull --ff-only }}') is None


def msys(p):
    """``p`` as Git Bash writes it on Windows (/c/Users/...)."""
    p = Path(p)
    return "/" + p.drive[0].lower() + p.as_posix()[2:] if os.name == "nt" else p.as_posix()


def _worktree_shapes(plat):
    lab, scratch = plat / "demo-lab", plat.parent / "scratchpad"
    return dict(lab=msys(lab), lab_win=lab, s=msys(scratch), wt=msys(scratch / "ql-x"), wt_win=scratch / "ql-x",
                wt_fwd=(scratch / "ql-x").as_posix())


@pytest.mark.parametrize("cwd, command", [
    ("plat", "cd {lab} && git worktree add -q -b feat/x {wt} origin/main && cd {wt} && git add -A && git commit -m x"),
    ("lab", "git -C {wt} commit -m x && git -C {wt} push -u origin feat/x"),
    ("lab", 'S={s}; cd {lab} && git worktree add -b feat/x $S/ql-x origin/main && W=$S/ql-x && cd "$W" && '
            "git add -A && git commit -m x && git push -u origin feat/x"),
    ("lab", 'export PATH="$PATH:/c/Program Files/GitHub CLI"; S={s}; W=$S/ql-x; git -C $W add -A && '
            'git -C ${{W}} commit -q -m x && git -C "$W" push -q -u origin feat/x 2>&1 | tail -1'),
    ("lab", 'export W="{wt_win}" && cd "$W" && git commit -m x'),
    ("lab", "cd {wt_fwd} && git commit -m x"),
    ("lab", 'W=$(cygpath -w {wt}); cd "$W" && git commit -m x'),
    ("lab", 'cd "$(cygpath -u "{wt_win}")" && git commit -m x'),
    ("lab", "(cd {wt} && git status) && cd {wt} && git commit -m x"),
])
def test_worktree_commits_allowed_after_production_cds(plat, cwd, command):
    shapes = _worktree_shapes(plat)
    assert bash(plat / "demo-lab" if cwd == "lab" else plat, command.format(**shapes)) is None


@pytest.mark.parametrize("command", [
    "$W = '{wt_win}'; Set-Location $W; if ($?) {{ git commit -m x }}",
    '$env:W = "{wt_win}"; git -C $env:W commit -m x',
])
def test_powershell_worktree_commits_allowed(plat, command):
    assert pwsh(plat / "demo-lab", command.format(**_worktree_shapes(plat))) is None


@pytest.mark.parametrize("cwd, command", [
    ("plat", "cd {wt} && git status && cd {lab} && git commit -m x"),
    ("scratch", "git -C {lab} commit -m x"),
    ("plat", "W={lab}; git -C $W push origin main"),
    ("scratch", 'W="{lab_win}" && cd "$W" && git commit -m x'),
    ("lab", 'W=$(git rev-parse --show-toplevel); cd "$W" && git commit -m x'),
    ("lab", 'cd "$BRAIN_TEST_UNSET_DIR" && git commit -m x'),
    ("lab", "(cd {wt} && git status); git commit -m x"),
])
def test_production_commits_still_refused(plat, cwd, command):
    shapes = _worktree_shapes(plat)
    where = {"plat": plat, "lab": plat / "demo-lab", "scratch": plat.parent / "scratchpad"}[cwd]
    assert "refused in the production checkout" in bash(where, command.format(**shapes))


def test_powershell_production_variable_refused(plat):
    assert "refused in the production checkout" in pwsh(plat, f"$W = '{plat / 'demo-lab'}'; Set-Location $W; "
                                                             "git commit -m x")


# --- shell writes into production checkouts ----------------------------------------------------------------------

def test_segments_mark_redirections():
    r = guards.REDIRECT
    assert guards.segments("echo x > a 2>&1 >> b 2>err &>all >|c") == [
        ["echo", "x", r + ">", "a", r + ">>", "b", r + "2>", "err", r + "&>", "all", r + ">|", "c"]]
    assert guards.segments("sort < in > out; echo '>' \"a > b\" >&2") == [
        ["sort", r + "<", "in", r + ">", "out"], ["echo", ">", "a > b"]]
    assert guards.segments("[[ a > b ]] && (( n > 3 )) && echo $((n>2))")[:2] == [["[[", "a", ">", "b", "]]"],
                                                                                ["n", ">", "3"]]
    assert guards.segments("cat <<'EOF' > notes.md\nbody > x\nEOF\necho done") == [
        ["cat", r + ">", "notes.md"], ["echo", "done"]]
    assert guards.segments("echo x *> f 2>&1 > $null", powershell=True) == [
        ["echo", "x", r + "*>", "f", r + ">", "$null"]]


def test_calls_judge_redirections_in_their_folder(tmp_path):
    a, out = tmp_path / "a", (tmp_path / "out").as_posix()
    cmds = guards.calls(f"cd {a.as_posix()} && (cd b && ls) > {out}/x; ls > y", str(tmp_path))
    assert [(w, Path(d)) for w, d in cmds] == [(["ls"], a / "b"), ([guards.REDIRECT + ">", f"{out}/x"], a),
                                               ([guards.REDIRECT + ">", "y"], a), (["ls"], a)]
    tmp = guards.calls("D=$(mktemp -d); tar -xzf a.tgz -C \"$D\"", str(tmp_path))[0][0][-1]
    assert Path(tmp).parent == Path(tempfile.gettempdir())
    home = os.environ["BRAIN_HOME"]
    assert guards.calls('touch "$(cygpath -w "$BRAIN_HOME/x")"', str(tmp_path))[-1][0] == ["touch", home + "/x"]
    assert guards.calls("touch $(cygpath -m /e/x)", str(tmp_path))[-1][0] == ["touch", "e:/x"]


def _shapes(plat):
    lab, md, wt = plat / "demo-lab", plat / "demo-data", plat.parent / "scratchpad" / "ql-x"
    return dict(lab=msys(lab), lab_win=lab, md=msys(md), wt=msys(wt), wt_win=wt, nested=msys(lab / ".claude" /
                "worktrees" / "wt"), home=msys(Path.home()), enc=base64.b64encode("Remove-Item x".encode("utf-16-le"))
                .decode())


SHELL_WRITES_REFUSED = [
    # redirections and heredocs
    ("plat", "echo x > {lab}/notes/alerts.md"), ("lab", "cat >> src/model.py <<'EOF'\nx = 1\nEOF"),
    ("plat", "cd {lab} && python -m demo_lab.scan > results/run.log 2>&1"), ("lab", "make 2>build.err"),
    ("lab", "cmd &> all.log"), ("lab", "echo x >| f"), ("plat", "tee >(gzip > {lab}/z.gz) < /dev/null"),
    ("plat", "cat <<'EOF' > {md}/README.md\nbody\nEOF"), ("lab", "(cd {wt} && ls) > ls.txt"),
    # programs that write the files they name
    ("lab", "sed -i 's/a/b/' src/x.py"), ("lab", "sed -ie 's/a/b/' x.py"), ("lab", "sed -E -i 's#a#b#' x.yaml"),
    ("plat", "sed --in-place=.bak -e s/a/b/ {md}/x.py"), ("lab", "perl -pi -e 's/a/b/' x.txt"),
    ("plat", "cp {wt}/x.py {lab}/src/"), ("plat", "cp -t {lab} a b"), ("plat", "mv {lab}/x.py {wt}/"),
    ("lab", "rm -rf build"), ("plat", "rm -f {md}/data/x.parquet"), ("lab", "touch -d now t"),
    ("lab", "truncate -s 0 log"), ("plat", "dd if=/dev/zero of={lab}/img bs=1 count=1"), ("lab", "mkdir -p a/b"),
    ("lab", "chmod +x scripts/run.sh"), ("lab", "ln -s ../x y"), ("plat", "install -m 644 a {lab}/a"),
    ("plat", "rsync -a {wt}/ {lab}/"), ("lab", "sort -o sorted.txt in.txt"), ("lab", "curl -sSLo dl.zip https://x/y"),
    ("lab", "curl -O https://x/y.zip"), ("lab", "wget https://x/y.zip"), ("plat", "tar -xzf a.tgz -C {lab}"),
    ("lab", "tar xzf a.tgz"), ("plat", "tar -czf {lab}/out.tgz {wt}"), ("plat", "unzip a.zip -d {lab}/x"),
    ("lab", "patch -p1 < fix.diff"), ("lab", "find . -name '*.pyc' -delete"),
    ("plat", "find {lab}/src -name '*.py' -exec sed -i s/a/b/ {{}} +"), ("lab", "git ls-files | xargs rm"),
    ("lab", "env X=1 nohup rm z"), ("lab", "timeout 5 touch t"), ("lab", "awk -i inplace '{{print}}' x"),
    ("lab", 'rm "$BRAIN_TEST_UNSET_DIR"'), ("lab", 'echo x > "$(date +%F).log"'),
    # inline code, and the commands of another shell
    ("lab", "python -c \"open('w.txt', 'w').write('x')\""),
    ("plat", "python -I -c \"import pathlib; pathlib.Path(r'{lab_win}/x.txt').write_text('x')\""),
    ("plat", "python3 -c \"import shutil; shutil.copy('a.csv', '{lab}/b.csv')\""),
    ("plat", "python -c \"import pandas as pd; df = pd.DataFrame(); df.to_parquet('{lab}/x.parquet')\""),
    ("plat", "python -c \"import sys; open(sys.argv[1], 'a').write('x')\" {lab}/log.txt"),
    ("plat", "python -c \"p = '{lab}/x.json'; f = open(p, mode='w')\""),
    ("lab", "python -c \"import os; [os.remove(f) for f in os.listdir('.')]\""),
    ("plat", "node -e \"require('fs').writeFileSync('{lab}/n.json', '{{}}')\""),
    ("plat", "bash -c 'rm -f {lab}/x'"), ("lab", "bash -lc \"echo x > b\""), ("plat", "sh -c 'cd {lab} && touch x'"),
    ("plat", "pwsh -NoProfile -Command \"Set-Content -Path {lab_win}\\x -Value y\""),
    ("lab", "powershell -EncodedCommand {enc}"), ("lab", "cmd //c \"del /q x && echo y > z\""),
]


@pytest.mark.parametrize("cwd, command", SHELL_WRITES_REFUSED)
def test_bash_shell_writes_refused_in_production(plat, cwd, command):
    where = {"plat": plat, "lab": plat / "demo-lab"}[cwd]
    reason = bash(where, command.format(**_shapes(plat)))
    assert reason and "refused: it writes" in reason and "in the production checkout" in reason, command
    assert "BRAIN_GUARD_ALLOW=production" in reason


PS_WRITES_REFUSED = [
    "Set-Content -Path {lab}\\notes\\x.md -Value x", "'x' | Out-File {lab}\\o.txt -Encoding utf8",
    "Add-Content -Encoding utf8 {lab}\\a.log 'v'", "echo x > {lab}\\f.txt", "echo x *>> {lab}\\f.txt",
    "git log | Tee-Object -FilePath {lab}\\log.txt", "New-Item -ItemType Directory -Force -Path {lab}\\n",
    "Remove-Item -Recurse -Force {wt}\\a, {lab}\\b", "Set-Location {lab}; Get-ChildItem *.tmp | Remove-Item",
    "Copy-Item -Path {wt}\\a -Destination {lab}\\a", "Copy-Item {wt}\\a {lab}", "Move-Item {lab}\\a {wt}\\a",
    "Rename-Item {lab}\\a.txt b.txt", "Expand-Archive x.zip -DestinationPath {lab}\\x",
    "Invoke-WebRequest -Uri https://x -OutFile {lab}\\w.zip", "Get-Process | Export-Csv -Path {lab}\\p.csv",
    "Set-Location {lab}; sc s.txt 'v'", "ni {lab}\\n.txt", "rm -r -fo {lab}\\x", "del {lab}\\x", "mkdir {lab}\\d",
    "$p = '{lab}\\x.txt'; Set-Content $p 'x'", "[IO.File]::WriteAllText('{lab}\\io.txt', 'v')",
    "[System.IO.File]::Delete(\"{lab}\\io.txt\")", "iex 'Remove-Item {lab}\\x'", "cmd /c \"copy a.txt {lab}\\b.txt\"",
    "Set-Location {lab}; python -c \"open('x', 'w')\"", "bash -c 'rm {labm}/x'",
]


@pytest.mark.parametrize("command", PS_WRITES_REFUSED)
def test_powershell_shell_writes_refused_in_production(plat, command):
    lab, wt = plat / "demo-lab", plat.parent / "scratchpad" / "ql-x"
    reason = pwsh(plat, command.format(lab=lab, wt=wt, labm=msys(lab)))
    assert reason and "refused: it writes" in reason and "in the production checkout" in reason, command


SHELL_WRITES_ALLOWED = [
    # reads
    ("lab", "cat notes/x.md | grep -n x | head -5 > /dev/null 2>&1"), ("lab", "ls -la 2>/dev/null; wc -l < x.txt"),
    ("lab", "sed -n '1,20p' src/x.py"), ("lab", "grep -c x y >&2"), ("lab", "curl -s https://x/api"),
    ("lab", "tar -tzf a.tgz"), ("lab", "unzip -l a.zip"), ("lab", "find . -name '*.py' -newer x"),
    ("lab", "echo '>' \"a > b\"; git log --format='%h > %s' -3"),
    ("lab", "[[ a > b ]] && (( n > 3 )) && echo $((n>2))"),
    ("lab", "python -c \"print(open('notes/x.md').read())\""),
    ("lab", "python -c \"import sys; sys.stdout.write('x')\""),
    ("lab", "python -m pytest -q"), ("lab", "python scripts/report.py --out x.csv"),
    ("plat", "python -c \"import pandas as pd; r = pd.read_parquet(r'{lab_win}/data/x.parquet'); "
             "r.to_csv(r'{wt_win}/x.csv')\""),
    ("lab", "python -I -c \"import json; d = json.load(open('x.json')); json.dump(d, open(r'{wt_win}/y.json', 'w'))\""),
    ("lab", "python -c \"import re, sys; p = sys.argv[1]; open(p, 'w').write('x')\" {wt}/x.txt"),
    ("lab", "node -e \"console.log(require('fs').readFileSync('package.json', 'utf8'))\""),
    # the daily coordinator commands, scripts and the cycle
    ("lab", "git pull --ff-only 2>&1 | tail -3"), ("lab", "git worktree add -b feat/x {wt} origin/main > /dev/null"),
    ("lab", "git worktree remove --force {wt} && git branch -d feat/x"), ("lab", "gh pr merge 12 --merge"),
    ("lab", "python scripts/run_cycle.py --write data/qmd/x.parquet"), ("lab", "bash scripts/cycle.sh"),
    # writes outside production: worktrees, the nested one, the scratchpad, /dev/null, the brain venv, temp folders
    ("lab", "cd {wt} && echo x > notes.md && sed -i s/a/b/ x.py && rm -rf build"),
    ("lab", "cp src/x.py {wt}/src/ && mkdir -p {wt}/a && tee {wt}/log < /dev/null"),
    ("plat", "cd {nested} && touch x && echo y >> notes/journal.md"),
    ("lab", "python -m pytest -q > {wt}/pytest.log 2>&1"), ("lab", "(cd src && ls) > {wt}/ls.txt"),
    ("lab", "{home}/.brain/venv/Scripts/pip install -q -e . > /dev/null && cp x {home}/.brain/venv/x"),
    ("lab", "D=$(mktemp -d); tar --force-local -xzf tests/a.tgz -C \"$D\"; ls \"$D\"; rm -rf \"$D\""),
    ("lab", "rm -rf /tmp/$BRAIN_TEST_UNSET_DIR"),
    ("lab", "cmd //c mklink //J \"$(cygpath -w \"{wt}/node_modules\")\" x"),
    ("lab", "bash -c 'cd {wt} && rm -f x'"), ("plat", "sh -c 'cd /e/other && touch ok'"),
]


@pytest.mark.parametrize("cwd, command", SHELL_WRITES_ALLOWED)
def test_bash_reads_and_writes_outside_production_allowed(plat, cwd, command):
    where = {"plat": plat, "lab": plat / "demo-lab"}[cwd]
    command = command.format(**_shapes(plat))
    assert bash(where, command) is None, command


@pytest.mark.parametrize("command", [
    "Get-Content notes\\x.md | Select-String x | Out-Null", "git log > $null 2>&1", "echo x *> $null",
    "git log | Tee-Object -Variable out", "iwr https://x/api", "Remove-Item x -WhatIf",
    "Set-Location {wt}; Set-Content x.txt 'v'; New-Item -ItemType Directory -Force -Path d",
    "Copy-Item -Path src\\x.py -Destination {wt}\\x.py", "New-Item -ItemType Directory -Force -Path $env:BRAIN_HOME\\x",
    "[System.IO.File]::ReadAllText('x.txt')", ".\\scripts\\cycle_host.ps1 -Setup", "pwsh scripts/health_check.ps1",
    "git pull --ff-only; git worktree add {wt} -b feat/x origin/main",
])
def test_powershell_reads_and_writes_outside_production_allowed(plat, command):
    lab, wt = plat / "demo-lab", plat.parent / "scratchpad" / "ql-x"
    assert pwsh(lab, command.format(wt=wt)) is None, command


def test_shell_write_reason_names_the_target(plat):
    lab = plat / "demo-lab"
    reason = bash(lab, "sed -i s/a/b/ src/x.py")
    assert f"sed -i refused: it writes {lab / 'src' / 'x.py'} in the production checkout {lab}; write in a" in reason
    reason = bash(lab, 'rm -rf "$BRAIN_TEST_UNSET_DIR/x"')
    assert f"rm refused: it writes $BRAIN_TEST_UNSET_DIR/x (read as its folder {lab})" in reason
    assert "Remove-Item refused: it writes its input (read as its folder" in pwsh(lab, "ls *.tmp | Remove-Item")


def test_shell_write_refusals_are_counted_apart(plat, brain_home, monkeypatch):
    (brain_home / "ledger").mkdir(parents=True)
    lab = plat / "demo-lab"
    assert bash(lab, "echo x > notes.md")
    assert bash(lab, "git commit -m x")
    assert decide(payload("Write", lab, file_path=str(lab / "x.md"), content="x"))
    monkeypatch.setenv(guards.ALLOW_ENV, "production")
    assert pwsh(lab, "Set-Content x.md 'v'") is None
    rows = _guard_ledger(brain_home)
    assert [(r["guard"], r["check"], r["decision"]) for r in rows] == [
        ("production", "shell-write", "denied"), ("production", "git", "denied"), ("production", "edit", "denied"),
        ("production", "shell-write", "overridden")]
    assert rows[0]["reason"].startswith("redirection > refused: it writes")


# --- the pre-filter of guard.sh ----------------------------------------------------------------------------------

def _needs_python(commands, kind="shell"):
    """guard.sh's needs_python on the payload of each command, in one bash process: [True, False, ...]."""
    from test_capture import _bash
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    lines = "\n".join(json.dumps(payload("Bash", "D:/work/x", command=c, description="Copy, move, find and sort"))
                      for c in commands) + "\n"
    script = (f'source "{(PLUGIN / "hooks" / "guard.sh").as_posix()}"; '
              'while IFS= read -r l; do needs_python ' + kind + ' "$l" && echo 1 || echo 0; done')
    out = subprocess.run([sh, "-c", script], input=lines.encode(), capture_output=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return [x == b"1" for x in out.stdout.split()]


def test_prefilter_starts_python_for_every_refused_shape(plat):
    shapes = _shapes(plat)
    ps = dict(lab=shapes["lab_win"], wt=shapes["wt_win"], labm=shapes["lab"])
    commands = [c.format(**shapes) for _, c in SHELL_WRITES_REFUSED] + [c.format(**ps) for c in PS_WRITES_REFUSED]
    assert all(_needs_python(commands))


def test_prefilter_names_cover_the_tables():
    names = (set(guards.WRITERS) | guards.SPECIAL | set(guards.PS_WRITERS) | set(guards.PS_ALIASES)
             | set(guards.CMD_WRITERS) | set(guards.SHELLS) | set(guards.INLINE) | {"iex", "invoke-expression"}
             | {"python3", "python3.12", "pythonw", "py", "xargs"}) - {"sed"}
    names = sorted(names)
    commands = [f"{name} x" for name in names] + [f"ls\n{name.upper()} x" for name in names] + \
        [f"(\"{name}.exe\" x)" for name in names] + ["sed -i s/a/b/ x", "ls; sed -Ei s/a/b/ x",
                                                     "sed --in-place s/a/b/ x", "[IO.File]::Delete('x')"]
    missed = [c for c, started in zip(commands, _needs_python(commands)) if not started]
    assert not missed


def test_prefilter_skips_reads_without_git():
    assert _needs_python(["ls -la 2>&1 | head", "cat x > /dev/null", "grep -n x y 2>/dev/null >&2",
                          "sed -n 1,5p f", "Get-Content x > $null", "cd GitNexus && ls"]) == [False] * 6
    assert _needs_python(["git status", "gh pr view 1", "echo x > f", "cat a >> b"]) == [True] * 4
    assert _needs_python(["ls"], kind="edit") == [True]


# --- AI attribution ----------------------------------------------------------------------------------------------

def test_attribution_refused_in_commit_messages(plat):
    heredoc = f"git commit -m \"$(cat <<'EOF'\nAdd the guards\n\n{CLAUDE}\nEOF\n)\""
    reason = bash(plat, heredoc)
    assert "git commit message refused" in reason and "BRAIN_GUARD_ALLOW=attribution" in reason
    assert bash(plat, f'git commit -m "fix" -m "{CLAUDE}"')
    assert pwsh(plat, f"git commit -m @'\nl'item est fait\n\n{CLAUDE}\n'@")
    (plat / "msg.txt").write_text(f"fix\n\n{CLAUDE}\n", encoding="utf-8")
    assert bash(plat, "git commit -F msg.txt")


def test_attribution_refused_in_pr_text(plat):
    body = f"## Summary\n- guards\n\n{GENERATED}"
    assert "gh pr create text refused" in bash(plat, f'gh pr create --title "Guards" --body "{body}"')
    (plat / "body.md").write_text(body, encoding="utf-8")
    assert bash(plat, "gh pr edit 12 --body-file body.md")
    assert pwsh(plat, f"gh pr create --title Guards --body @'\n{body}\n'@")
    assert bash(plat, f"gh pr create --title t --body-file - <<'EOF'\n{body}\nEOF")


@pytest.mark.parametrize("command", [
    "git commit -m \"$(cat <<'EOF'\nAdd the guards\n\nThey refuse a Co-Authored-By: Claude line.\nEOF\n)\"",
    'git commit -m "pair" -m "Co-Authored-By: Alice <alice@example.invalid>"',
    'git log --grep "Co-Authored-By: Claude"',
    'gh pr create --title "Guards" --body "Refuses Generated with Claude Code lines."',
    'gh pr view 12 --json body',
])
def test_attribution_allowed(plat, command):
    assert bash(plat, command) is None


# --- secrets -----------------------------------------------------------------------------------------------------

@pytest.fixture
def repo(git_repo, monkeypatch):
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setattr(guards, "gitleaks", lambda repo: None)
    monkeypatch.setenv("BRAIN_PROJECTS", str(git_repo / "no-registry.yaml"))
    return git_repo


def test_staged_secret_refused_with_file_and_line(repo):
    (repo / "config.py").write_text(f'URL = "https://x"\nKEY = "{FAKE_KEY}"\n', encoding="utf-8")
    run_git(repo, "add", "config.py")
    reason = bash(repo, 'git commit -m "config"')
    assert "git commit refused: config.py:2 (anthropic-key) looks like a secret" in reason
    assert FAKE_KEY not in reason and "BRAIN_GUARD_ALLOW=secrets" in reason


def test_secret_staged_by_the_same_command_refused(repo):
    (repo / "config.py").write_text(f"KEY={FAKE_KEY}\n", encoding="utf-8")
    assert "config.py:1" in bash(repo, 'git add config.py && git commit -m "config"')
    assert "config.py:1" in pwsh(repo, 'git add -A; if ($?) { git commit -m "config" }')
    assert bash(repo, 'git add notes && git commit -m "notes"') is None


def test_commit_all_scans_tracked_changes(repo):
    (repo / "notes" / "decisions.md").write_text(f"# Decisions\napi_key: \"{'Ab1' * 8}\"\n", encoding="utf-8")
    assert "notes/decisions.md:2 (assignment)" in bash(repo, 'git commit -am "decisions"')


@pytest.mark.parametrize("line", [
    "token_count = compute_token_count_for(x)",
    "secret_names = secretscan.find(line)",
    f'KEY = "{FAKE_KEY}"  # gitleaks:allow',
    "password = os.environ['DB_PASSWORD']",
])
def test_code_and_marked_lines_allowed(repo, line):
    (repo / "code.py").write_text(line + "\n", encoding="utf-8")
    run_git(repo, "add", "code.py")
    assert bash(repo, 'git commit -m "code"') is None


def test_gitleaks_report_is_read(repo, monkeypatch):
    monkeypatch.setattr(guards.shutil, "which", lambda name: "gitleaks")

    def fake_run(args, cwd, timeout=10):
        report = args[args.index("--report-path") + 1]
        Path(report).write_text(json.dumps([{"File": "a.env", "StartLine": 3, "RuleID": "generic-api-key"}]),
                                encoding="utf-8")
        return subprocess.CompletedProcess(args, 1, b"", b"")

    monkeypatch.setattr(guards, "_run", fake_run)
    assert REAL_GITLEAKS(str(repo)) == ["a.env:3 (generic-api-key)"]
    monkeypatch.setattr(guards, "_run", lambda args, cwd, timeout=10: subprocess.CompletedProcess(args, 2, b"", b""))
    assert REAL_GITLEAKS(str(repo)) is None


# --- override, ledger, errors ------------------------------------------------------------------------------------

def _guard_ledger(home):
    return [json.loads(line) for f in sorted((home / "ledger").glob("guards-*.jsonl"))
            for line in f.read_text(encoding="utf-8").splitlines()]


def test_override_lets_the_call_through_and_is_recorded(plat, brain_home, monkeypatch):
    (brain_home / "ledger").mkdir(parents=True)
    edit = payload("Edit", plat, file_path=str(plat / "demo-lab" / "x.py"), old_string="a", new_string="b")
    assert decide(edit)
    monkeypatch.setenv(guards.ALLOW_ENV, "attribution, production")
    assert decide(edit) is None
    monkeypatch.setenv(guards.ALLOW_ENV, "all")
    assert bash(plat, f'git -C {(plat / "demo-lab").as_posix()} commit -m "x" -m "{CLAUDE}"') is None
    rows = _guard_ledger(brain_home)
    assert [(r["guard"], r["decision"]) for r in rows] == [("production", "denied"), ("production", "overridden"),
                                                           ("production", "overridden"), ("attribution", "overridden")]
    assert rows[0]["session_id"] == "s-1" and rows[0]["tool"] == "Edit"


def test_no_ledger_written_when_absent(plat, brain_home):
    assert decide(payload("Write", plat, file_path=str(plat / "demo-lab" / "x.py"), content="x"))
    assert not (brain_home / "ledger").exists()


def test_internal_error_lets_the_call_through(plat, brain_home, monkeypatch):
    def boom(p):
        raise RuntimeError("bad payload")
        yield

    monkeypatch.setattr(guards, "refusals", boom)
    assert decide(payload("Bash", plat, command="git commit -m x")) is None
    assert "guard: RuntimeError: bad payload" in (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")
    assert guards.main(stdin=io.StringIO("not json"), stdout=io.StringIO()) == 0


# --- configuration and the hook ----------------------------------------------------------------------------------

def test_registry_production_paths(plat):
    proj = projects.load()["demo"]
    assert proj.production == [plat / "demo-lab", plat / "demo-data"]
    assert guards.production_roots() == [str(plat / "demo-lab"), str(plat / "demo-data")]


def test_installed_checkout_from_the_brain_venv(brain_home, tmp_path):
    site = brain_home / "venv" / ("Lib/site-packages" if os.name == "nt" else "lib/python3.12/site-packages")
    info = site / "brain-0.1.0.dist-info"
    info.mkdir(parents=True)
    (info / "direct_url.json").write_text(json.dumps({"dir_info": {"editable": True},
                                                      "url": (tmp_path / "brain-clone").as_uri()}), encoding="utf-8")
    assert paths.installed_checkout() == tmp_path / "brain-clone"


def test_hooks_json_declares_the_guards():
    pre = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert [(m["matcher"], m["hooks"][0]["command"].split()[-1]) for m in pre] == [
        ("Bash|PowerShell", "shell"), ("Edit|Write|MultiEdit|NotebookEdit", "edit"),
        ("mcp__.*scheduled[-_]?tasks?__(create|update)_scheduled_task", "tool")]
    assert not any(h.get("async") for m in pre for h in m["hooks"])
    tools = re.compile(pre[2]["matcher"])
    assert tools.fullmatch("mcp__scheduled-tasks__create_scheduled_task") and guards.SCHEDULED_TOOL.match(
        "mcp__scheduled-tasks__create_scheduled_task")
    assert not tools.fullmatch("mcp__scheduled-tasks__list_scheduled_tasks")


def test_guard_script_end_to_end(plat, tmp_path):
    from test_capture import _bash
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    env = dict(os.environ, BRAIN_PYTHON=sys.executable)

    def run(kind, p):
        out = subprocess.run([sh, str(PLUGIN / "hooks" / "guard.sh"), kind], input=json.dumps(p), capture_output=True,
                             text=True, env=env, timeout=60)
        assert out.returncode == 0
        return out.stdout

    refused = run("shell", payload("Bash", plat / "demo-lab", command="git commit -m x"))
    assert json.loads(refused)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert run("shell", payload("Bash", plat / "demo-lab", command="ls -la")) == ""
    assert run("edit", payload("Write", tmp_path, file_path=str(tmp_path / "a.md"), content="x")) == ""
    assert run("edit", payload("Write", plat, file_path=str(plat / "demo-lab" / "a.md"), content="x"))
    refused = run("shell", payload("PowerShell", plat / "demo-lab", command="sed -i s/a/b/ x.py"))
    assert "sed -i refused" in json.loads(refused)["hookSpecificOutput"]["permissionDecisionReason"]
    assert run("shell", payload("Bash", plat / "demo-lab", command="ls 2>&1 > /dev/null")) == ""
