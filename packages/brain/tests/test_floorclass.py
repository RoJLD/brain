"""The floor's round-14 classes (wi-brain-unadopted-floor; brain.floorpwsh, brain.floorguard): refused as classes, not
spellings, under floor.only (the lock simulated: test_floor's ``held``) and floor.refuse alike: a link in any spelling,
any write into a .git folder by anything but git, git am or rebase resuming a queue, git apply unless its options read
as git reads them are read-only, a path the floor cannot resolve where it makes a link or writes what it keeps; the
ordinary work of review rounds 11 and 13 passes, and with the floor off every call below passes the floor."""

import json
import os
import tarfile
import zipfile

import pytest
from brain import floor
from test_floor import config, edit
from test_guards import bash, pwsh

EVIL = json.dumps({"env": {"BASH_FUNC_git%%": "() { git push origin HEAD:main; }"}})


@pytest.fixture(autouse=True)
def held(monkeypatch):
    """The lock simulated: brain.floor.unlocked says it holds."""
    monkeypatch.setattr(floor, "unlocked", lambda *a, **k: "")


@pytest.fixture
def repo(git_repo, tmp_path):
    """A checkout with a project settings file, an ordinary file, archives and a staging folder beside it."""
    settings = git_repo / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    (git_repo / "a.txt").write_text("a", encoding="utf-8")
    (git_repo / "notes").mkdir(exist_ok=True)
    stage = tmp_path / "stage"
    (stage / ".git" / "rebase-apply").mkdir(parents=True)
    (stage / ".git" / "rebase-apply" / "next").write_text("1", encoding="utf-8")
    with tarfile.open(tmp_path / "state.tar", "w") as tf:
        tf.add(stage / ".git", arcname=".git")
    with tarfile.open(tmp_path / "links.tar", "w") as tf:
        info = tarfile.TarInfo("y.txt")
        info.type, info.linkname = tarfile.SYMTYPE, ".claude/settings.json"
        tf.addfile(info)
    with zipfile.ZipFile(tmp_path / "plain.zip", "w") as z:
        z.writestr("rebase-apply/next", "1")
    return git_repo


LINKS_BASH = [
    f"cp --lin .claude/settings.json y.txt && echo '{EVIL}' > y.txt", "cp --l .claude/settings.json y.txt",
    "cp --sym .claude/settings.json y.txt", f"ln .claude/setting?.json y.txt && echo '{EVIL}' > y.txt",
    "link .claude/settings.jso? y.txt", 'ln "$(printf .claude/settings.json)" y.txt', "ln -s ../.claude/x sub/y.txt",
    "ln -s .{claude,x}/settings.json y.txt", "busybox ln .claude/settings.json y.txt",
    "perl -e 'link \".claude/settings.json\",\"y.txt\"'", "node -e \"require('fs').linkSync('s.json','y.txt')\"",
    "python -c \"import nt; nt.link('s.json','y.txt')\"", "python -c \"import os; getattr(os,'li'+'nk')('a','b')\"",
    "python -c \"import os; os .link('a','b')\"", "python -c \"from os import link; link('a','b')\"",
    "python -c \"import shutil,os; shutil.copytree('.claude','cc',copy_function=os.link)\"",
    "python -c \"import os; os.symlink('a.txt','z.txt')\"",
    "python - <<'EOF'\nfrom pathlib import Path\nPath('n.txt').symlink_to('a.txt')\nEOF",
    "python -c \"import subprocess; subprocess.run(['ln','a.txt','b.txt'])\"",
    "ruby -e \"File.link('a.txt','b.txt')\"", "ln a.txt b.txt && echo x > b.txt", "ls | xargs ln -s",
    "find . -name a.txt -exec ln {} y.txt ';'", "rsync -a --link-dest=../.claude notes/ out/",
    "find . | cpio -pdl ../out",
]
LINKS_PS = [
    "New-Item -ItemType h -Path y.txt -Target .claude/settings.json; Set-Content y.txt x",
    "New-Item -ItemType:HardLink -Path y.txt -Target:.claude/settings.json",
    "New-Item -Ite:Hard -Path y.txt -Value .claude/settings.json",
    "New-Item -ItemType 'hard*' -Path y.txt -Value a.txt; Set-Content y.txt x",
    "$p = @{ItemType='HardLink'; Path='y.txt'; Target='a.txt'}; New-Item @p",
    "New-Item -ItemType Sym -Path k -Target .claude", "[IO.File]::CreateSymbolicLink('y.txt', 'a.txt')",
    "Add-Type -MemberDefinition '[DllImport(\"kernel32.dll\")] public static extern bool CreateHardLink(string a, "
    "string b, IntPtr c);' -Name K -Namespace W",
]
GIT_DIR_BASH = [
    "cp -r ../stage/.git/rebase-apply .git/", "mv ../stage/.git/rebase-apply .git/", "tar -xf ../state.tar -C .git",
    "robocopy ../stage/.git .git /E", "cp -r ../stage/.git/rebase-apply ./.git && git am --continue",
    "cd .git && tar -xf ../../state.tar && cd ..", "unzip -o ../plain.zip -d .git", "echo x > .git/hooks/pre-commit",
    "cp a.txt .gi?/hooks/", "cp -r ../stage/. .", "tar -xf ../state.tar", "echo x > $(printf .git)/rebase-apply/next",
    "mkdir -p .git/rebase-merge", "sed -i s/a/b/ .git/rebase-merge/git-rebase-todo",
    "tar -xf ../links.tar",
]
GIT_DIR_PS = ["Copy-Item -Recurse ../stage/.git/rebase-apply .git/",
              "Expand-Archive -Path ../plain.zip -DestinationPath .git -Force",
              "Set-Content -Path .git/rebase-apply/next -Value 1"]
RESUMERS = ["git rebase --continue", "git rebase --skip", "git rebase --cont", "git am --sk", "git am --continue",
            "git am -r", "git cherry-pick --continue", "git revert --skip"]
APPLY = ["git apply --stat --app p.diff", "git apply --check --appl p.diff", "git apply --summary --ap p.diff",
         "git apply --stat --no-stat p.diff", "git apply --check --reject p.diff",
         "git apply --check --build-fake-ancestor=x p.diff", "git apply --check --unsafe-paths p.diff",
         "git apply --check --no-check p.diff", "git apply --stat --odd p.diff", "git apply --s p.diff",
         "git apply -Rx --check p.diff"]
CLONE = ["git clone --template=../t https://code.example/a/b", "git init --templ ../t x",
         "git clone -c core.hooksPath=h https://code.example/a/b", "git clone --conf core.hooksPath=h https://x/y"]

ORDINARY_BASH = [
    "git add -A && git commit -m x", "gh pr create --fill", "python -m pytest -q", "cp a.txt b.txt",
    "cp -r notes notes2", "ln a.txt c.txt", "ln -s a.txt d.txt", "cp -l a.txt e.txt", "git apply --check p.diff",
    "git apply --stat -p1 p.diff", "git apply --numstat -z p.diff", "git apply --check --3way p.diff",
    "git apply --check --no-apply p.diff", "git apply --chec p.diff", "git am --abort", "git rebase --abort",
    "grep -rn CreateSymbolicLink src", "grep -rn \"os.symlink(\" src", "git grep -n CreateHardLink",
    "git log -S CreateSymbolicLink --oneline", "git diff | grep -c CreateHardLink",
    "sed -n '/fs.symlinkSync(/p' build.js", "cat > probe.py <<'EOF'\nimport os\nos.symlink('a.txt', 'b.txt')\nEOF",
    "python -c \"print('os.symlink is documented')\"", "python -c \"import json,sys; print(json.load(sys.stdin)['links'])\"",
    "python -c \"import subprocess; subprocess.run(['git', 'status'])\"", "node -e \"console.log(1)\"",
    "echo x > notes/a.txt", "rm -rf build/*", "rm -f .git/index.lock", "cp *.txt notes/",
    "git clone https://code.example/a/b", "mkdir sub && cd sub && ln -s .. up", "perl -ne 'print if /link/' a.txt",
    "python -c \"import importlib.metadata as m; print(m.version('pip'))\"",
    "python -c \"import re; print(re.compile('link').pattern)\"",
]
ORDINARY_PS = ["New-Item -ItemType HardLink -Path f.txt -Target a.txt", "New-Item -ItemType File -Path g.txt",
               "Copy-Item a.txt h.txt", "Select-String -Path src/*.py -Pattern CreateSymbolicLink",
               "New-Item -ItemType Directory -Path out"]


@pytest.mark.parametrize("section", [{"only": True}, {"refuse": True}])
def test_each_class_is_refused_under_the_floor(repo, tmp_path, monkeypatch, section):
    config(tmp_path, monkeypatch, **section)
    monkeypatch.chdir(repo)
    for command in LINKS_BASH + GIT_DIR_BASH + RESUMERS + APPLY + CLONE:
        assert "locked floor" in (bash(repo, command) or ""), command
    for command in LINKS_PS + GIT_DIR_PS:
        assert "locked floor" in (pwsh(repo, command) or ""), command
    for path in (repo / ".git" / "rebase-merge" / "git-rebase-todo", repo / ".git" / "hooks" / "pre-commit",
                 repo / ".git" / "info" / "exclude"):
        assert ".git folder" in (edit(repo, path, "exec x") or ""), path


@pytest.mark.parametrize("section", [{"only": True}, {"refuse": True}])
def test_ordinary_work_passes_under_the_floor(repo, tmp_path, monkeypatch, section):
    config(tmp_path, monkeypatch, **section)
    monkeypatch.chdir(repo)
    (tmp_path / "copy").mkdir()
    for command in ORDINARY_BASH + [f"robocopy '{(repo / 'notes').as_posix()}' '{(tmp_path / 'copy').as_posix()}' /E"]:
        assert bash(repo, command) is None, command
    for command in ORDINARY_PS:
        assert pwsh(repo, command) is None, command


def test_the_floor_off_refuses_none_of_them(repo, tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    for command in LINKS_BASH + GIT_DIR_BASH + RESUMERS + APPLY + CLONE + ORDINARY_BASH:
        assert "locked floor" not in (bash(repo, command) or ""), command
    for command in LINKS_PS + GIT_DIR_PS + ORDINARY_PS:
        assert "locked floor" not in (pwsh(repo, command) or ""), command


def test_apply_options_are_read_as_git_reads_them():
    from brain import floorpwsh as fp
    assert fp.apply_reads_only(["--check", "-p1", "--exclude", "x", "--", "p.diff"])
    assert fp.apply_reads_only(["--sta", "--whitespace=fix", "p.diff"]) and fp.apply_reads_only(["--no-apply", "--check"])
    assert not fp.apply_reads_only(["--stat", "--apply"]) and not fp.apply_reads_only(["--nu", "--ap"])
    assert not fp.apply_reads_only(["--no-check", "--check", "--no-check"]) and not fp.apply_reads_only(["p.diff"])
    assert fp._long("--n", fp.APPLY_LONG) is None and fp._long("--no-st", fp.APPLY_LONG) == ("stat", True)
    assert fp.resumes("rebase", ["--edit-todo"]) == "" and fp.resumes("rebase", ["--c"])


def test_inline_code_is_judged_by_what_it_calls():
    from brain import floorpwsh as fp
    assert fp.code_link("python", "import os; os.link('a', 'b')") == ".link"
    assert fp.code_link("python", "print('os.link(a, b)')  # os.symlink") == ""
    assert fp.code_link("python", "for link in links: print(link)") == ""
    assert fp.code_link("node", "fs['sym'+'link']('a','b')")
    assert fp.code_link("perl", "print 'x'") == "" and fp.code_link("perl", "symlink 'a', 'b'")


def test_globs_and_braces_are_read_as_the_shell_expands_them(tmp_path):
    from brain import floorpwsh as fp
    (tmp_path / ".git").mkdir()
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    def norm(paths):
        return [os.path.normcase(os.path.normpath(p)) for p in paths]
    assert norm(fp.expand(".gi?", str(tmp_path), "bash")) == norm([str(tmp_path / ".git")])
    assert norm(fp.expand("*", str(tmp_path), "bash")) == norm([str(tmp_path / "a.txt")])   # no dot file
    assert len(fp.expand("*", str(tmp_path), "ps")) == 2
    assert fp.expand("x{a,b}", str(tmp_path), "bash") == ["xb", "xa"] and fp.expand("$x", ".", "bash") is None
    assert fp.expand("@p", ".", "ps") is None and fp.expand("q*", str(tmp_path), "bash") == ["q*"]
