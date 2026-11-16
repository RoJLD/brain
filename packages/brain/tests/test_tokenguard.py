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
]
PWSH = [
    "Get-Content {tok}", "gc '{tok}'", "Get-Content -Path:{tok}", "Get-Content -Raw -LiteralPath {tok}",
    "type {tok}", "Copy-Item {tok} C:\\tmp\\x", "Select-String -Path {tok} -Pattern .",
    "[IO.File]::ReadAllText('{tok}')", "${{{tok}}}", "cmd /c type {tok}", "pwsh -Command \"Get-Content {tok}\"",
    "Set-Location {home}\\ipc; Get-Content token", "Get-Content {home}\\ipc\\*",
]


@pytest.mark.parametrize("command", BASH)
def test_shell_reads_of_the_token_are_refused_in_bash(machine, command):
    assert _token_refusal(decide(payload("Bash", machine, command=command.format(tok=tok(True), home=home(True)),
                                         description="run"))), command


@pytest.mark.parametrize("command", PWSH)
def test_shell_reads_of_the_token_are_refused_in_powershell(machine, command):
    assert _token_refusal(decide(payload("PowerShell", machine, command=command.format(tok=tok(), home=home()),
                                         description="run"))), command


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
    # the default file stays guarded too
    assert _token_refusal(decide(payload("Read", machine, file_path=str(tokenguard.token_files()[1]))))


# --- what passes ---------------------------------------------------------------------------------------------------

PASSES = [
    "ls -l {tok}", "test -f {tok} && echo yes", "stat {tok}", "ls {home}/ipc", "icacls {tok}",
    "brain ipc token", "brain ipc token --init", "python -m brain ipc token", "echo {tok}",
    "grep -rn 'ipc/token' docs/mcp.md", "rg ipcauth src", "cat README.md", "cat {home}/ipc-notes.txt",
    "python -m pytest tests/test_ipc_token.py", "cat {home}/config.json",
]


@pytest.mark.parametrize("command", PASSES)
def test_names_metadata_and_mentions_pass(machine, command):
    assert decide(payload("Bash", machine, command=command.format(tok=tok(True), home=home(True)),
                          description="run")) is None, command


def test_powershell_metadata_passes(machine):
    for command in ("Test-Path {tok}", "Get-Item {tok}", "Get-Acl {tok}", "Get-ChildItem {home}\\ipc"):
        assert decide(payload("PowerShell", machine, command=command.format(tok=tok(), home=home()),
                              description="run")) is None, command


def test_other_reads_pass(machine):
    other = machine / "notes.md"
    other.write_text("x", encoding="utf-8")
    assert decide(payload("Read", machine, file_path=str(other))) is None
    assert decide(payload("Grep", machine, pattern="x", path=str(machine))) is None
    assert decide(payload("Grep", machine, pattern="x")) is None
    assert decide(payload("Write", machine, file_path=str(machine / "token"), content="x")) is None


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
    monkeypatch.setattr(tokenguard, "_protected", boom)
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
    effect = mcpguards.bash_payload(machine, ["spec", "show", "x"])
    effect["tool_input"]["command"] = f"cat {tok(True)}"
    assert any(c == "token" for _, c, _, _ in guards.refusals(effect, strict=True))
    if link is not None:
        effect["tool_input"]["command"] = "cat spec.md"
        assert any(c == "token" for _, c, _, _ in guards.refusals(effect, strict=True))


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


# --- guard.sh starts Python for each refused shape, and for no other Read ---------------------------------------------

def _reads_token(payloads):
    from test_capture import _bash
    sh = _bash()
    if not sh:
        pytest.skip("no bash")
    lines = "\n".join(json.dumps(p) for p in payloads) + "\n"
    script = (f'source "{(PLUGIN / "hooks" / "guard.sh").as_posix()}"; '
              'while IFS= read -r l; do needs_python read "$l" && echo 1 || echo 0; done')
    out = subprocess.run([sh, "-c", script], input=lines.encode(), capture_output=True, timeout=60,
                         env=dict(os.environ, BRAIN_HOME=home()))
    assert out.returncode == 0, out.stderr
    return [x == b"1" for x in out.stdout.split()]


def test_prefilter_of_read_and_grep(machine):
    started = _reads_token([payload("Read", machine, file_path=tok()),
                            payload("Grep", machine, pattern=".", path=os.path.dirname(tok())),
                            payload("Grep", home(), pattern="."),
                            payload("Read", machine, file_path=str(machine / "README.md")),
                            payload("Grep", machine, pattern="def ", path=str(machine))])
    assert started == [True, True, True, False, False]


def test_prefilter_starts_python_for_the_shell_shapes(machine):
    from test_guards import _needs_python
    # a glob that spells neither ipc nor token (ip?/*) starts no Python: a limit docs/guards.md names
    commands = [c.format(tok="~/.brain/ipc/token", home="~/.brain") for c in BASH if "ip?" not in c]
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
