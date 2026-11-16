"""The floor's round-7 and round-8 parser classes (wi-brain-unadopted-floor; brain.floorpwsh, brain.floorguard):
PowerShell's pipelines and .NET's writers onto what the floor keeps, a .NET type held in a variable, the environment
through COM and .NET, the new spellings of settings and git keys, a settings file's hooks and shell keys, network paths.
Owner Ada, on a machine whose lock holds (test_floor's ``held``)."""

import json
import time

import pytest
from brain import floor
from test_floor import config, edit
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


def test_a_type_held_in_a_variable_and_the_function_drive_through_set_content_are_refused(repo, tmp_path, monkeypatch):
    """Review round 8 #6, #7: $t = [type]'IO.File' then $t::WriteAllText(...) was not read as [IO.File]; Set-Content
    and Add-Content define a function or an alias through the function: and alias: drives."""
    config(tmp_path, monkeypatch, refuse=True)
    home, o, cfg = _r7(repo, tmp_path)
    for command in (f"$t=[type]'IO.File'; $t::WriteAllText('{cfg}','{{}}')", f"$t = [IO.File]; $t::Move('{cfg}', 'x')",
                    f"$t = 'IO.File' -as [type]; $t::Delete('{cfg}')",
                    f"${{t}} = [Type]::GetType('System.IO.File'); ${{t}}::Copy('a', '{o}/.claude/settings.json')",
                    "Set-Content -Path function:f -Value { Copy-Item $args[0] $args[1] }; f a b",
                    "Add-Content function:f { cp a b }", "sc alias:c Copy-Item; c a b"):
        assert "floor" in (pwsh(repo, command) or ""), command
    for command in ("$t = [IO.File]::ReadAllText('a.txt')", "$n = [int]'4'; $n + 1", "[IO.Path]::GetTempPath()"):
        assert pwsh(repo, command) is None, command


def test_a_settings_file_s_hook_or_shell_key_is_refused_under_the_floor(repo, tmp_path, monkeypatch):
    """Review round 8 #1: a settings PreToolUse hook runs beside the guard and its updatedInput replaces the call the
    guard judged; env keys pick the shell or git every command runs."""
    config(tmp_path, monkeypatch, refuse=True)
    hook = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "node x.js"}]}]}}
    for path in (repo / ".claude" / "settings.json", repo / ".claude" / "settings.local.json"):
        assert "PRETOOLUSE" in (edit(repo, path, json.dumps(hook)) or ""), path
    for key in ("CLAUDE_CODE_GIT_BASH_PATH", "GIT_EXEC_PATH", "SHELL", "ComSpec", "PATHEXT",
                "NoDefaultCurrentDirectoryInExePath", "CLAUDE_CODE_SHELL_PREFIX"):
        reason = edit(repo, repo / ".claude" / "settings.json", json.dumps({"env": {key: "C:/x/evil.exe"}})) or ""
        assert "moves or stops the floor" in reason, key
    allow = {"permissions": {"allow": ["Bash(npm test)"]}, "env": {"OTEL_LOGS_EXPORTER": "otlp"}}
    assert edit(repo, repo / ".claude" / "settings.local.json", json.dumps(allow)) is None


def test_a_network_path_is_judged_as_written_never_resolved():
    """Review round 8 #2: realpath of an unreachable host took 21 s, which a call used to outrun the hook."""
    start = time.monotonic()
    for path in ("//10.255.255.3/s/a", r"\\10.255.255.4\s\b", r"\\?\UNC\10.255.255.5\s\c"):
        assert "10.255.255." in floor.resolve(path)
    assert time.monotonic() - start < 2
    assert floor.UNC.match("//host/share") and not floor.UNC.match(r"\\?\C:\x") and not floor.UNC.match("C:/x")


def test_settings_env_is_an_allowlist_and_frontmatter_hooks_are_refused(repo, tmp_path, monkeypatch):
    """Review round 9 #1, #2: under the floor a settings write adds only floor.ENV_ALLOWED names to env (BASH_FUNC_git%%
    redefines git in the Bash tool's bash; GIT_* change what git runs); a skill's, command's or agent's frontmatter
    hooks run beside the guard."""
    config(tmp_path, monkeypatch, refuse=True)
    settings = repo / ".claude" / "settings.json"
    for key in ("BASH_FUNC_git%%", "BASH_FUNC_git()", "GIT_EXTERNAL_DIFF", "GIT_SSH_COMMAND", "GIT_DIR", "FOO"):
        reason = edit(repo, settings, json.dumps({"env": {key: "() { git push origin HEAD:main; }"}})) or ""
        assert "moves or stops the floor" in reason and key in reason, key
    ok = {"env": {"OTEL_LOGS_EXPORTER": "otlp", "BRAIN_READ_HINT": "0"}, "permissions": {"allow": ["Bash(npm test)"]}}
    assert edit(repo, settings, json.dumps(ok)) is None
    hook = "---\nname: x\nhooks:\n  PreToolUse:\n    - matcher: Bash\n---\nbody\n"
    for path in (repo / ".claude" / "skills" / "x" / "SKILL.md", repo / ".claude" / "commands" / "x.md",
                 repo / ".claude" / "agents" / "x.md"):
        assert "adds hooks" in (edit(repo, path, hook) or ""), path
        assert edit(repo, path, "---\nname: x\ndescription: y\n---\nhooks: in the body is text\n") is None


def test_a_type_reached_through_an_expression_is_refused_as_a_class(repo, tmp_path, monkeypatch):
    """Review round 9 #3: anything but a literal [Type] before ::, and reflection on a type."""
    config(tmp_path, monkeypatch, refuse=True)
    _, _, cfg = _r7(repo, tmp_path)
    for command in (f"$t=([IO.File]); $t::WriteAllText('{cfg}','x')", f"([IO.File])::WriteAllText('{cfg}','x')",
                    f"$t=[IO.File].UnderlyingSystemType; $t::Delete('{cfg}')",
                    f"Set-Variable t ([IO.File]); $t::Delete('{cfg}')", f"$t='IO.File' -as 'type'; $t::Delete('{cfg}')",
                    f"[IO.File] | % {{ $_::WriteAllText('{cfg}','x') }}",
                    f"[IO.File].GetMethod('WriteAllText',[type[]]@([string],[string])).Invoke($null,@('{cfg}','x'))"):
        assert "floor" in (pwsh(repo, command) or ""), command
    for command in ("[IO.Path]::GetTempPath()", "[int]::MaxValue", "[DateTime]::Now.ToString('s')"):
        assert pwsh(repo, command) is None, command


def test_device_and_volume_prefixes_are_judged_as_written():
    r"""Review round 9 #4: the \\?\ and \\.\ prefixes (//?/, //./) but a drive letter's are judged as written."""
    for path in (r"\\?\GLOBALROOT\Device\Mup\10.255.255.3\s\a", "//?/GLOBALROOT/Device/Mup/h/s/a",
                 r"\\.\GLOBALROOT\Device\Mup\h\s", r"\\?\Volume{0b1c}\x"):
        assert floor.UNC.match(path), path
    for path in (r"\\?\C:\x", "//?/C:/x", r"\\.\C:\x", "C:/x", "/home/x"):
        assert not floor.UNC.match(path), path
