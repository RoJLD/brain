"""The floor's round-7 parser classes (wi-brain-unadopted-floor; brain.floorpwsh, brain.floorguard): PowerShell's
pipelines and .NET's writers onto what the floor keeps, the environment through COM and .NET, and the new spellings
of settings and git keys. Owner Ada, on a machine whose lock holds (test_floor's ``held``)."""

import pytest
from brain import floor
from test_floor import config
from test_guards import bash, pwsh


@pytest.fixture(autouse=True)
def held(monkeypatch):
    monkeypatch.setattr(floor, "unlocked", lambda *a, **k: "")


@pytest.fixture
def repo(git_repo):
    return git_repo


def _r7(repo, tmp_path):
    from pathlib import Path
    home, o = Path.home().as_posix(), repo.as_posix()
    return home, o, (tmp_path / "config.json").as_posix()


def test_a_kept_path_piped_into_a_writer_or_a_net_method_is_refused(repo, tmp_path, monkeypatch):
    """Review round 7 #1, #6: a pipeline's input is the cmdlet's -Path, and .NET's MoveTo, CopyTo, Replace, Delete and
    SetAccessControl write whatever object they are called on."""
    config(tmp_path, monkeypatch, refuse=True)
    home, o, cfg = _r7(repo, tmp_path)
    for command in (f"Get-Item {home}/.claude/plugins | Rename-Item -NewName old",
                    f"Get-ChildItem {home}/.claude/plugins | Rename-Item -NewName old",
                    f"gi {home}/.claude | ren -NewName .claude.old", f"'{cfg}' | Rename-Item -NewName c.old",
                    f"Get-Item {cfg} | Remove-Item", f"Get-Item {o}/.claude/settings.json | Set-Content -Value x",
                    f"Get-Item {home}/.gitconfig | Add-Content -Value x",
                    f"(Get-Item C:/evil/off.json).CopyTo('{cfg}', $true)",
                    f"(Get-Item {home}/.claude/plugins).MoveTo('C:/x/old')", f"(Get-Item {home}/.claude/plugins).Delete($true)",
                    f"(Get-Item g.txt).CopyTo('{home}/.gitconfig', $true)",
                    f"(Get-Item s.json).Replace('{o}/.claude/settings.json', 'b.json')",
                    "$d = Get-Item ~/.claude; $d.SetAccessControl($a)",
                    "(Get-Item $env:USERPROFILE/.claude/plugins).MoveTo('C:/x')"):
        assert "floor" in (pwsh(repo, command) or ""), command
    for command in ("Get-ChildItem | Rename-Item -NewName { $_.Name + '.bak' }", "'a.txt' | Remove-Item",
                    "(Get-Item a.txt).CopyTo('b.txt')", "$s = 'x'; $s.Replace('a', 'b')", "Get-Item a.txt | Set-Content -Value x"):
        assert pwsh(repo, command) is None, command


def test_the_environment_through_com_net_or_a_pipeline_is_refused(repo, tmp_path, monkeypatch):
    """Review round 7 #2: WScript.Shell's Environment, a RegistryKey's writers, the Environment key piped."""
    config(tmp_path, monkeypatch, refuse=True)
    for command in ("$s = New-Object -ComObject WScript.Shell; $s.Environment('User').Item('BRAIN_GUARD_ALLOW') = 'floor'",
                    "$e = (New-Object -ComObject WScript.Shell).Environment('User'); $e['BRAIN_HOME'] = 'C:/evil'",
                    "$r = [Microsoft.Win32.Registry]::CurrentUser; $k = $r.OpenSubKey('Environment', $true); "
                    "$k.SetValue('BRAIN_PYTHON', 'C:/x/python.exe')",
                    "$r = [Microsoft.Win32.Registry]::CurrentUser; $r.CreateSubKey('Env' + 'ironment')",
                    "Get-Item HKCU:\\Environment | Set-ItemProperty -Name BRAIN_GUARD_ALLOW -Value floor",
                    "Get-Item HKCU:\\Environment | New-ItemProperty -Name BRAIN_PYTHON -Value x"):
        assert "floor" in (pwsh(repo, command) or ""), command


def test_round_7_spellings_of_settings_and_git_are_refused(repo, tmp_path, monkeypatch):
    """Review round 7 #7: Env:/, ${function:}, the function: and alias: drives, BASH_ALIASES, set -o posix, imap.*, a
    credential helper's value that holds a command."""
    config(tmp_path, monkeypatch, only=True)
    for command in ("Set-Item -Path Env:/GIT_CONFIG_PARAMETERS -Value x; git status", "New-Item Env:/GIT_DIR -Value x",
                    "${function:f} = { Copy-Item $args[0] $args[1] }; f a b", "Set-Item function:f { x }",
                    "Set-Item alias:c Copy-Item; c a b", "New-Item alias:c -Value Copy-Item"):
        assert "floor" in (pwsh(repo, command) or ""), command
    for command in ("BASH_ALIASES[c]=cp", "set -o posix", "set -e -o posix", "git config imap.tunnel 'cp a b'",
                    "git config credential.helper 'store ;cp a b #'", "git config credential.helper '!cp a b'"):
        assert "floor" in (bash(repo, command) or ""), command
    assert bash(repo, "git config credential.helper 'store --file=~/.git-credentials'") is None
