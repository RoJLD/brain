"""The machine's IPC token kept from a session's tool calls (brain.tokenguard, wi-brain-ipc-token-read-guard): every
door to the file (Read, Grep, a tool edit, a shell call in Bash and PowerShell, nested or wrapped, over ssh) is refused
under config.json guards.refuse_token_read, passes without it, and the MCP server refuses it and redacts the token
whatever the key says. The tests run as owner Ada, in a temporary BRAIN_HOME."""

import json
import os
import subprocess

import pytest
from test_guards import PLUGIN, decide, payload

from brain import guards, ipcauth, mcpguards, mcpserver, tokenguard

TOKEN = "t0k3n-" + "a1b2c3d4" * 6   # an invented token: 54 ASCII characters


@pytest.fixture
def machine(tmp_path, monkeypatch, brain_home):
    """Ada's config.json with the check on, her token made in <BRAIN_HOME>/ipc/token, a working folder."""
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-projects.yaml"))
    cfg = tmp_path / "ada-config.json"
    cfg.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"},
                               "guards": {"refuse_token_read": True}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    tok = ipcauth.token_file()
    tok.parent.mkdir(parents=True)
    tok.write_text(TOKEN, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    return work


def _off(cfg_dir, monkeypatch, value=None):
    cfg = cfg_dir / "off-config.json"
    data = {"v": 1, "identity": {"owner": "Ada", "kind": "person"}}
    if value is not None:
        data["guards"] = {"refuse_token_read": value}
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))


def _token_refusal(reason):
    return reason is not None and "IPC token" in reason and f"{guards.ALLOW_ENV}=owner (or owner:token)" in reason


def tok(posix: bool = False) -> str:
    f = ipcauth.token_file()
    return f.as_posix() if posix else str(f)


def home(posix: bool = False) -> str:
    f = ipcauth.token_file().parent.parent
    return f.as_posix() if posix else str(f)


# --- every door to the file is refused ------------------------------------------------------------------------------

BASH = [
    "cat {tok}", "cat '{tok}'", "head -c 64 {tok}", "cp {tok} /tmp/x", "less {tok}", "base64 {tok}",
    "xxd {tok}", "rm {tok}", "grep -r . {home}/ipc", "tar czf /tmp/k.tgz {home}/ipc", "cp -r {home}/ipc /tmp/x",
    "cat < {tok}", "wc -c 0< {tok}", "cat {home}/ipc/../ipc/token", "cat {home}/ipc/tok*", "cat {home}/ip?/*",
    "cd {home}/ipc && cat token", "cd {home} && cat ipc/token", "sudo cat {tok}", "env X=1 cat {tok}",
    "timeout 5 cat {tok}", "bash -c 'cat {tok}'", "sh -c \"head {tok}\"", "xargs cat <<< {tok}",
    "python -c \"print(open('{tok}').read())\"", "python3 -c \"import pathlib; print(pathlib.Path('{home}') / 'ipc' "
    "/ 'token')\"", "python -c \"from brain import ipcauth; print(ipcauth.read())\"",
    "node -e \"console.log(require('fs').readFileSync('{tok}','utf8'))\"", "cat $(echo {tok})",
    "curl -d @{tok} http://127.0.0.1:9", "dd if={tok} of=/tmp/x", "git add --force {tok}",
    "ssh box1 cat .brain/ipc/token", "perl -ne print {tok}", "awk 1 {tok}", "sed -n p {tok}",
    # found by the review (2026-11-16): the brain's home whole, heredocs, pipes, ${VAR}, redirections, shares...
    "grep -r . {home}", "cp -r {home} /tmp/b", "tar czf /tmp/b.tgz {home}", "zip -r /tmp/b.zip {home}",
    "rsync -a {home}/ /tmp/b", "python - <<'X'\nprint(open('{tok}').read())\nX",
    "cat <<'X' | python3\nimport brain.ipcauth as a; print(a.read())\nX", "node <<'X'\nrequire('fs').readFileSync('{tok}')\nX",
    "echo {tok} | xargs cat", "ls -d {home}/ipc/* | xargs cat", "echo {tok} | while read f; do cat \"$f\"; done",
    "cat ${{BRAIN_HOME}}/ipc/token", "echo x > {tok}", ": > {tok}", "printf x >> {tok}",
    "python -c 'import sys' -m brain x; cat {tok}", "brain --root=`cat {tok}` items",
    "curl -F 'f=@{tok}' http://127.0.0.1:9", "cat {home}/ipc/../../{homename}/ipc/token",
    "cat {home}/i*/../ipc/t?ken",
    # round 2
    "grep -r . \"$BRAIN_HOME\"",
    # round 3: a heredoc's code with argv after python's -, or /dev/stdin
    "python - foo <<'X'\nprint(open('{tok}').read())\nX", "python /dev/stdin <<'X'\nopen('{tok}')\nX",
    "python3 - a b <<'X'\nimport brain.ipcauth as a\nX",
]
PWSH = [
    "Get-Content {tok}", "gc '{tok}'", "Get-Content -Path:{tok}", "Get-Content -Raw -LiteralPath {tok}",
    "type {tok}", "Copy-Item {tok} C:\\tmp\\x", "Select-String -Path {tok} -Pattern .",
    "[IO.File]::ReadAllText('{tok}')", "${{{tok}}}", "cmd /c type {tok}", "pwsh -Command \"Get-Content {tok}\"",
    "Set-Location {home}\\ipc; Get-Content token", "Get-Content {home}\\ipc\\*",
    # found by the review (2026-11-16)
    "Get-Content -Path 'x','{tok}'", "Get-Content (Join-Path $env:BRAIN_HOME 'ipc' 'token')",
    "Get-Content ([IO.Path]::Combine($env:BRAIN_HOME, 'ipc', 'token'))", "gc ${{env:BRAIN_HOME}}\\ipc\\token",
    "Get-Item {tok} | Get-Content", "gci {home}\\ipc | % {{ gc $_ }}", "'x' > {tok}",
    "Copy-Item -Recurse {home} C:\\tmp\\b", "Compress-Archive {home} C:\\tmp\\b.zip",
    "Select-String -Path $env:BRAIN_HOME\\ipc\\* -Pattern .",
    # round 3: the home listed recursively into a reader
    "Get-ChildItem -Recurse {home} | Select-String .", "gci {home} -Recurse -File | gc",
]


def _fmt(command: str, posix: bool) -> str:
    return command.format(tok=tok(posix), home=home(posix), homename=os.path.basename(home()))


@pytest.mark.parametrize("command", BASH)
def test_shell_reads_of_the_token_are_refused_in_bash(machine, command):
    assert _token_refusal(decide(payload("Bash", machine, command=_fmt(command, True), description="run"))), command


@pytest.mark.parametrize("command", PWSH)
def test_shell_reads_of_the_token_are_refused_in_powershell(machine, command):
    assert _token_refusal(decide(payload("PowerShell", machine, command=_fmt(command, False),
                                         description="run"))), command


@pytest.mark.skipif(os.name != "nt", reason="a loopback admin share and WSL's /mnt/c are Windows paths")
def test_a_loopback_share_and_a_wsl_path_are_the_file(machine):
    drive, rest = os.path.splitdrive(tok())
    share = f"\\\\localhost\\{drive[0]}$" + rest
    assert _token_refusal(decide(payload("Read", machine, file_path=share)))
    assert _token_refusal(decide(payload("PowerShell", machine, command=f"Get-Content '{share}'", description="r")))
    import socket
    for host in (os.environ.get("COMPUTERNAME") or socket.gethostname(), "0--1.ipv6-literal.net", "127.0.0.1"):
        assert _token_refusal(decide(payload("Read", machine, file_path=f"\\\\{host}\\{drive[0]}$" + rest))), host
    assert decide(payload("Read", machine, file_path=f"\\\\fileserver\\{drive[0]}$" + rest)) is None   # another
    wsl = f"/mnt/{drive[0].lower()}" + rest.replace("\\", "/")
    assert _token_refusal(decide(payload("Bash", machine, command=f"wsl cat {wsl}", description="run")))


def test_a_deep_glob_costs_nothing(machine):
    import time
    deep = " ".join(f"{home(True)}/*/*/*/*/*/*/*/x{i}" for i in range(8))
    t0 = time.monotonic()
    assert decide(payload("Bash", machine, command=f"true {deep}; echo done", description="run")) is None
    assert time.monotonic() - t0 < 5


def test_the_terminal_panel_is_judged_as_a_shell(machine):
    p = payload("mcp__terminal__run_in_terminal", machine)
    command = f"Get-Content {tok()}" if os.name == "nt" else f"cat {tok(True)}"
    p["tool_input"] = {"command": command, "cwd": str(machine)}
    assert _token_refusal(decide(p))


def test_read_grep_and_edits_of_the_token_are_refused(machine):
    assert _token_refusal(decide(payload("Read", machine, file_path=tok())))
    assert _token_refusal(decide(payload("Read", machine, file_path=tok() + "::$DATA"))) or os.name != "nt"
    assert _token_refusal(decide(payload("Read", machine, file_path=os.path.join(home(), "ipc", "..", "ipc",
                                                                                  "token"))))
    for where in (tok(), os.path.dirname(tok()), home()):
        assert _token_refusal(decide(payload("Grep", machine, pattern=".", path=where))), where
    assert _token_refusal(decide(payload("Grep", home(), pattern=".")))   # no path: the cwd
    for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path")):
        assert _token_refusal(decide(payload(tool, machine, **{key: tok(), "content": "mine"}))), tool


def test_a_link_to_the_token_is_the_token(machine):
    link = machine / "innocent.txt"
    try:
        os.symlink(tok(), link)
    except (OSError, NotImplementedError):
        pytest.skip("this machine cannot make a symbolic link")
    assert _token_refusal(decide(payload("Read", machine, file_path=str(link))))
    assert _token_refusal(decide(payload("Bash", machine, command="cat innocent.txt", description="run")))


def test_the_token_file_named_by_the_environment(machine, tmp_path, monkeypatch):
    other = tmp_path / "secrets" / "brain-token"
    other.parent.mkdir()
    other.write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv(ipcauth.ENV, str(other))
    assert _token_refusal(decide(payload("Read", machine, file_path=str(other))))
    assert _token_refusal(decide(payload("Bash", machine, command=f"cat {other.as_posix()}", description="run")))
    assert _token_refusal(decide(payload("Grep", machine, pattern=".", path=str(other.parent))))
    assert _token_refusal(decide(payload("Bash", machine, command='cat "$BRAIN_IPC_TOKEN_FILE"', description="r")))
    from test_guards import _needs_python
    assert _needs_python(['cat "$BRAIN_IPC_TOKEN_FILE"', "cat /x/BRAIN-TOKEN"]) == [True, True]
    # the default file stays guarded too
    assert _token_refusal(decide(payload("Read", machine, file_path=str(tokenguard.token_files()[1]))))


# --- what passes ---------------------------------------------------------------------------------------------------

PASSES = [
    "ls -l {tok}", "test -f {tok} && echo yes", "stat {tok}", "ls {home}/ipc", "icacls {tok}",
    "brain ipc token", "brain ipc token --init", "python -m brain ipc token", "echo {tok}",
    "grep -rn 'ipc/token' docs/mcp.md", "rg ipcauth src", "cat README.md", "cat {home}/ipc-notes.txt",
    "python -m pytest tests/test_ipc_token.py", "cat {home}/config.json",
    # found by the review (2026-11-16): mentions in an argument, a search, a message
    "python -m pytest -k 'ipc/token' tests", "python -c \"print('ipc/token')\"",
    "grep -rn 'open(ipc/token' src", "rg -n 'read(.*ipc/token' src",
    "git commit -m 'The guard refuses cat ipc/token (and Read)'",
    "gh pr create --title t --body 'refuses open(\"ipc/token\")'",
    # round 2: a heredoc into git or a file, pipes elsewhere in the call, the home listed in a pipe
    "git commit -F - <<'X'\nGuard python and node: open('ipc/token') is refused\nX",
    "cat > notes.md <<'X'\npython -c \"open('.brain/ipc/token')\"\nX",
    "ls {home} && git log | head", "test -f {tok} && echo yes | cat", "ls {home} | head",
    "cd {home} && grep -rn 'ipc/token' handover", "grep -e '{tok}' notes.txt", "rg -e 'ipc/token' -e x src",
    "python script.py <<'X'\nopen('{tok}')\nX",
]


@pytest.mark.parametrize("command", PASSES)
def test_names_metadata_and_mentions_pass(machine, command):
    assert decide(payload("Bash", machine, command=_fmt(command, True), description="run")) is None, command


def test_powershell_metadata_passes(machine):
    for command in ("Test-Path {tok}", "Get-Item {tok}", "Get-Acl {tok}", "Get-ChildItem {home}\\ipc",
                    "Test-Path {tok}; Get-Process | Select-Object -First 1", "Get-ChildItem {home} | Format-Table",
                    "Join-Path $env:BRAIN_HOME handover", "Get-Content (Join-Path $env:BRAIN_HOME 'handover\\x.md')"):
        assert decide(payload("PowerShell", machine, command=command.format(tok=tok(), home=home()),
                              description="run")) is None, command


def test_other_reads_pass(machine):
    other = machine / "notes.md"
    other.write_text("x", encoding="utf-8")
    assert decide(payload("Read", machine, file_path=str(other))) is None
    assert decide(payload("Grep", machine, pattern="x", path=str(machine))) is None
    assert decide(payload("Grep", machine, pattern="x")) is None
    assert decide(payload("Write", machine, file_path=str(machine / "token"), content="x")) is None
    # a Grep in the brain's home whose glob or type cannot match the token's file
    assert decide(payload("Grep", home(), pattern="x", glob="*.md")) is None
    assert decide(payload("Grep", machine, pattern="x", path=home(), type="py")) is None
    assert decide(payload("Grep", machine, pattern="x", path=home(), glob="*.{md,json}")) is None
    assert _token_refusal(decide(payload("Grep", machine, pattern="x", path=home(), glob="tok*")))
    assert _token_refusal(decide(payload("Grep", machine, pattern="x", path=home(), glob="**/ipc/*")))
    assert _token_refusal(decide(payload("Grep", machine, pattern="x", path=home(), glob="!*.md")))   # all the rest


@pytest.mark.parametrize("value", [None, False])
def test_off_by_default(machine, tmp_path, monkeypatch, value):
    _off(tmp_path, monkeypatch, value)
    assert decide(payload("Read", machine, file_path=tok())) is None
    assert decide(payload("Bash", machine, command=f"cat {tok(True)}", description="run")) is None
    assert decide(payload("Write", machine, file_path=tok(), content="x")) is None


def test_the_owner_lifts_it(machine, monkeypatch, brain_home):
    monkeypatch.setenv(guards.ALLOW_ENV, "owner:token")
    assert decide(payload("Read", machine, file_path=tok())) is None
    monkeypatch.setenv(guards.ALLOW_ENV, "owner:keys")
    assert _token_refusal(decide(payload("Read", machine, file_path=tok())))


def test_an_error_lets_a_hook_through_and_refuses_strictly(machine, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(tokenguard, "Protected", boom)
    p = payload("Read", machine, file_path=tok())
    assert decide(p) is None
    assert [(g, c) for g, c, _, _ in guards.refusals(p, strict=True)] == [("owner", "token")]
    p = payload("Bash", machine, command=f"cat {tok(True)}", description="run")
    assert ("owner", "token") in [(g, c) for g, c, _, _ in guards.refusals(p, strict=True)]


# --- the MCP server -----------------------------------------------------------------------------------------------

def test_the_mcp_server_refuses_it_whatever_the_key(machine, tmp_path, monkeypatch):
    _off(tmp_path, monkeypatch, False)
    link = machine / "spec.md"
    try:
        os.symlink(tok(), link)
    except (OSError, NotImplementedError):
        link = None
    if link is None:
        pytest.skip("this machine cannot make a symbolic link")
    # the effect of brain_spec_show (brain spec show REF, run in the root): a REF that is a link to the token
    effect = mcpguards.bash_payload(machine, ["spec", "show", "spec.md"])
    assert any(c == "token" for _, c, _, _ in guards.refusals(effect, strict=True))
    assert not any(c == "token" for _, c, _, _ in guards.refusals(
        mcpguards.bash_payload(machine, ["spec", "show", "spec-brain-x"]), strict=True))


def test_the_mcp_answers_carry_no_token(machine):
    assert tokenguard.redact({"a": [f"x {TOKEN} y"], "b": 1}) == {
        "a": ["x [the machine's IPC token, redacted] y"], "b": 1}
    server = mcpserver.Server(root=machine)
    server.tools = (mcpserver.Tool("leak", "Leak", "a test tool", {}, kind="read",
                                   func=lambda s, a: (f"the token is {TOKEN}", False)),)
    out = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "leak", "arguments": {}}})
    assert TOKEN not in json.dumps(out) and "redacted" in json.dumps(out)


def test_no_token_file_redacts_nothing(tmp_path, brain_home):
    assert tokenguard.redact("plain") == "plain"


# --- the hooks start Python for each refused shape, and for no other Read ----------------------------------------------

def _reads_token(payloads, **env):
    from test_capture import _bash
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    lines = "\n".join(json.dumps(p) for p in payloads) + "\n"
    script = (f'source "{(PLUGIN / "hooks" / "tokenguard.sh").as_posix()}"; '
              'while IFS= read -r l; do reads_token "$l" && echo 1 || echo 0; done')
    out = subprocess.run([sh, "-c", script], input=lines.encode(), capture_output=True, timeout=60,
                         env=dict(os.environ, BRAIN_HOME=home(), **env))
    assert out.returncode == 0, out.stderr
    return [x == b"1" for x in out.stdout.split()]


def test_prefilter_of_read_and_grep(machine, tmp_path):
    link = machine / "innocent.txt"
    try:
        os.symlink(tok(), link)
    except (OSError, NotImplementedError):
        link = None
    calls = [payload("Read", machine, file_path=tok()),
             payload("Grep", machine, pattern=".", path=os.path.dirname(tok())),
             payload("Grep", home(), pattern="."),
             payload("Read", machine, file_path=str(machine / "README.md")),
             payload("Grep", machine, pattern="def ", path=str(machine))]
    want = [True, True, True, False, False]
    if link is not None:
        calls += [payload("Read", machine, file_path=str(link)), payload("Read", machine, file_path="innocent.txt"),
                  payload("Grep", machine, pattern=".", path=str(link) + os.sep)]
        want += [True, True, True]
    assert _reads_token(calls) == want
    other = tmp_path / "secrets" / "brain-key"
    assert _reads_token([payload("Read", machine, file_path=str(other))], BRAIN_IPC_TOKEN_FILE=str(other)) == [True]


def test_the_read_hook_is_opt_in(machine, tmp_path):
    from brain import render
    assert render.OPTIONAL_HOOKS["tokenguard.sh"] == ("guards", tokenguard.CONFIG_KEY)


def test_prefilter_reads_the_home_only_under_the_key(machine, tmp_path, monkeypatch):
    from test_guards import _needs_python
    shapes = ["ls ~/.brain/ledger", "cat ~/.BRAIN/cache/x.md", "grep -r x \"$BRAIN_HOME\""]
    assert all(_needs_python(shapes))
    _off(tmp_path, monkeypatch, False)
    assert not any(_needs_python(shapes))   # the key off: the home named starts no Python


def test_prefilter_starts_python_for_the_shell_shapes(machine, tmp_path):
    from test_guards import _needs_python
    # a glob that spells neither ipc nor token nor the brain's home (ip?/*) starts no Python: a limit the docs name
    commands = [_fmt(c, True).replace(home(True), "~/.brain") for c in BASH if "ip?" not in c]
    assert all(_needs_python(commands)), [c for c, s in zip(commands, _needs_python(commands)) if not s]


# --- beside the locked floor -----------------------------------------------------------------------------------------

def test_the_floor_neither_turns_it_on_nor_off(machine, tmp_path, monkeypatch):
    cfg = tmp_path / "floor-config.json"
    data = {"v": 1, "identity": {"owner": "Ada", "kind": "person"}, "floor": {"refuse": True}}
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    # the floor makes the guard strict for its errors, never the token check on: it stays the key's
    assert decide(payload("Read", machine, file_path=tok())) is None
    assert decide(payload("Bash", machine, command=f"cat {tok(True)}", description="run")) is None
    data["guards"] = {"refuse_token_read": True}
    cfg.write_text(json.dumps(data), encoding="utf-8")
    assert _token_refusal(decide(payload("Read", machine, file_path=tok())))
    assert _token_refusal(decide(payload("Bash", machine, command=f"cat {tok(True)}", description="run")))
    assert _token_refusal(decide(payload("Write", machine, file_path=tok(), content="x")))


def test_a_floor_only_machine_keeps_the_check(machine, tmp_path, monkeypatch):
    from brain import floor
    monkeypatch.setattr(floor, "unlocked", lambda *a, **k: "")   # the lock simulated
    cfg = tmp_path / "only-config.json"
    cfg.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"}, "floor": {"only": True},
                               "guards": {"refuse_token_read": True}}), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    assert _token_refusal(decide(payload("Read", machine, file_path=tok())))
    assert _token_refusal(decide(payload("Bash", machine, command=f"cat {tok(True)}", description="run")))
    assert _token_refusal(decide(payload("Edit", machine, file_path=tok(), old_string="a", new_string="b")))
    assert decide(payload("Bash", machine, command="cat README.md", description="run")) is None
