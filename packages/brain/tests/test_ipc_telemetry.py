"""wi-brain-install-claude-telemetry: Claude Code's OTLP export settings from config.json adapters.claude.telemetry
(brain.ipchealth.export_settings, brain ipc claude-settings), the installer's telemetry step that adds them to the
user settings (additions only), and brain health ipc's line when the collector requires the token."""

import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from brain import cli, config, ipcauth, ipchealth, schema

INSTALLER = Path(ipchealth.__file__).resolve().parents[2] / "installer" / "install.ps1"
HELPER = "brain ipc otel-headers"


def _config(tmp_path, monkeypatch, telemetry=None, ipc=None):
    """The tests' owner's config.json with adapters.claude.telemetry and an ipc block when given."""
    data = {"v": 1, "identity": {"owner": "Ada", "kind": "person"}}
    if telemetry is not None:
        data["adapters"] = {"claude": {"marketplace": "ada-brain", "plugin": "ada-core", "source": "ada/brain",
                                       "telemetry": telemetry}}
    if ipc is not None:
        data["ipc"] = ipc
    f = tmp_path / "cfg" / "config.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    return config.load()


# --- the settings rendered ---------------------------------------------------------------------------------------------

def test_the_export_settings_follow_the_section_and_the_helper_follows_the_collectors_token(tmp_path, monkeypatch):
    off = ipchealth.export_settings(_config(tmp_path, monkeypatch, {}))
    assert off == {"enabled": False, "env": {}, "otelHeadersHelper": None, "errors": []}   # default off: nothing
    cfg = _config(tmp_path, monkeypatch, {"enabled": True})
    assert schema.validate("config", cfg.data) == ([], [])   # the section is the schema's
    assert ipchealth.export_settings(cfg) == {
        "enabled": True, "otelHeadersHelper": None, "errors": [],
        "env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_METRICS_EXPORTER": "otlp", "OTEL_LOGS_EXPORTER": "otlp",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318"}}
    # auto: the helper once the collector requires the token, never for a collector that does not
    cfg = _config(tmp_path, monkeypatch, {"enabled": True, "exporters": ["metrics"],
                                          "env": {"OTEL_METRIC_EXPORT_INTERVAL": "10000"}},
                  {"require_token": ["otel-collector"]})
    assert schema.validate("config", cfg.data) == ([], [])
    res = ipchealth.export_settings(cfg)
    assert res["otelHeadersHelper"] == HELPER and not res["errors"]
    assert "OTEL_LOGS_EXPORTER" not in res["env"] and res["env"]["OTEL_METRIC_EXPORT_INTERVAL"] == "10000"
    never = ipchealth.export_settings(_config(tmp_path, monkeypatch, {"enabled": True, "headers_helper": "never"},
                                              {"require_token": ["otel-collector"]}))
    assert never["otelHeadersHelper"] is None
    always = ipchealth.export_settings(_config(tmp_path, monkeypatch, {"enabled": True, "headers_helper": "always"}))
    assert always["otelHeadersHelper"] == HELPER


def test_the_schema_refuses_an_unknown_key_or_value_of_the_section(tmp_path, monkeypatch):
    for bad in ({"enabled": True, "colour": "red"}, {"protocol": "udp"}, {"exporters": ["traces"]},
                {"endpoint": "collector:4318"}, {"env": {"OTEL_X": 1}}, {"headers_helper": "sometimes"}):
        errors, _ = schema.validate("config", _config(tmp_path, monkeypatch, bad).data)
        assert errors, bad


@pytest.mark.parametrize("telemetry, error", [
    ({"protocol": "grpc", "headers_helper": "always"}, "otelHeadersHelper works with http/protobuf and http/json"),
    ({"endpoint": "https://collector.example.invalid:4318", "headers_helper": "always"},
     "off loopback: the machine's token would leave it"),
    # Python's urlsplit reads 127.0.0.1 here, the WHATWG parser Claude Code's exporter uses reads evil.example
    ({"endpoint": "http://evil.example" + chr(92) + "@127.0.0.1:4318", "headers_helper": "always"},
     "off loopback: the machine's token would leave it"),
    ({"endpoint": "http://evil.example" + chr(92) + "@127.0.0.1:4318"}, "no user part, backslash or space"),
    ({"endpoint": "http://user@127.0.0.1:4318"}, "no user part, backslash or space"),
    ({"env": {"OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer x"}}, "never in clear in settings.json"),
    ({"env": {"OTEL_EXPORTER_OTLP_METRICS_HEADERS": "a=b"}}, "never in clear in settings.json"),
    ({"env": {"PATH": "x"}}, "only OTEL_* variables"),
    ({"env": {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1"}}, "set by the section's own keys"),
    ({"endpoint": "collector:4318"}, "an http:// or https:// URL"),
])
def test_a_section_that_would_leak_the_token_or_cannot_work_is_refused(tmp_path, monkeypatch, telemetry, error):
    res = ipchealth.export_settings(_config(tmp_path, monkeypatch, {"enabled": True, **telemetry}))
    assert any(error in e for e in res["errors"]), res["errors"]


def test_a_loopback_endpoint_by_name_or_address_takes_the_helper(tmp_path, monkeypatch):
    for endpoint in ("http://localhost:4318", "http://127.0.0.1:4318", "http://[::1]:4318", "http://127.0.0.1:4318/"):
        res = ipchealth.export_settings(_config(tmp_path, monkeypatch, {"enabled": True, "endpoint": endpoint,
                                                                        "headers_helper": "always"}))
        assert res["errors"] == [] and res["otelHeadersHelper"] == HELPER, endpoint
    for endpoint in ("http://127.1:4318", "http://0x7f.0.0.1:4318", "http://localhost.example:4318"):
        assert not ipchealth.loopback_url(endpoint), endpoint


@pytest.mark.parametrize("kept, error", [
    ({"OTEL_EXPORTER_OTLP_ENDPOINT": "https://api.vendor.example"}, "OTEL_EXPORTER_OTLP_ENDPOINT off loopback"),
    ({"OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "https://api.vendor.example/v1/metrics"},
     "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT off loopback"),
    ({"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"}, "OTEL_EXPORTER_OTLP_PROTOCOL grpc"),
    ({"OTEL_EXPORTER_OTLP_LOGS_PROTOCOL": "grpc"}, "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL grpc"),
])
def test_the_helper_is_refused_over_a_value_the_settings_keep(tmp_path, monkeypatch, kept, error):
    """The installer only adds: a remote endpoint or grpc already in Claude Code's settings stays, and the helper
    added beside it would send the machine's token off the machine, or never."""
    cfg = _config(tmp_path, monkeypatch, {"enabled": True}, {"require_token": ["otel-collector"]})
    assert ipchealth.export_settings(cfg, {"env": {}})["errors"] == []
    res = ipchealth.export_settings(cfg, {"env": kept, "otelHeadersHelper": "x"})
    assert any(error in e for e in res["errors"]), res["errors"]
    without = ipchealth.export_settings(_config(tmp_path, monkeypatch, {"enabled": True}), {"env": kept})
    assert without["errors"] == []   # no helper wanted: the owner's own export is theirs


def test_the_command_judges_the_settings_it_is_given(tmp_path, monkeypatch, capsys):
    _config(tmp_path, monkeypatch, {"enabled": True}, {"require_token": ["otel-collector"]})
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"env": {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://api.vendor.example"}}), encoding="utf-8")
    assert cli.main(["ipc", "claude-settings", "--json", "--settings", str(f)]) == 1
    assert "off loopback" in json.loads(capsys.readouterr().out)["errors"][0]
    f.write_text("{not json", encoding="utf-8")   # unreadable: the installer refuses it, not judged here
    assert cli.main(["ipc", "claude-settings", "--json", "--settings", str(f)]) == 0
    capsys.readouterr()
    default = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "settings.json"   # no --settings: Claude Code's user settings
    default.parent.mkdir(parents=True, exist_ok=True)
    default.write_text(json.dumps({"env": {"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"}}), encoding="utf-8")
    assert cli.main(["ipc", "claude-settings", "--json"]) == 1
    assert "grpc" in capsys.readouterr().out


def test_the_command_prints_the_settings_and_no_secret(tmp_path, monkeypatch, capsys):
    ipcauth.init()
    token = ipcauth.read()
    _config(tmp_path, monkeypatch, {"enabled": True}, {"require_token": ["otel-collector"]})
    assert cli.main(["ipc", "claude-settings", "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["otelHeadersHelper"] == HELPER and token not in out
    assert cli.main(["ipc", "claude-settings"]) == 0
    out = capsys.readouterr().out
    assert "env      OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318" in out
    assert f"helper   otelHeadersHelper: {HELPER}" in out and token not in out
    _config(tmp_path, monkeypatch, {"enabled": True, "protocol": "grpc"}, {"require_token": ["otel-collector"]})
    assert cli.main(["ipc", "claude-settings", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["errors"]
    _config(tmp_path, monkeypatch)
    assert cli.main(["ipc", "claude-settings"]) == 0
    assert "Claude Code's telemetry: off" in capsys.readouterr().out


# --- brain health ipc ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("settings, state, part", [
    (None, "OK", "export is off"),
    ({"env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1"}}, "FAIL", "carry no otelHeadersHelper"),
    ({"env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1"}, "otelHeadersHelper": HELPER}, "OK", "export carries the token"),
    ({"env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"},
      "otelHeadersHelper": HELPER}, "FAIL", "OTEL_EXPORTER_OTLP_PROTOCOL grpc"),
    ({"env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_EXPORTER_OTLP_ENDPOINT": "https://api.vendor.example"},
      "otelHeadersHelper": HELPER}, "FAIL", "off loopback: the machine's token would leave it"),
    ({"env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_EXPORTER_OTLP_ENDPOINT": "https://api.vendor.example",
              "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer vendor"}}, "OK", "not to the collector"),
    ({"env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "true", "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer x"}},
     "warning", "token in clear"),
    ({"env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1"}, "otelHeadersHelper": "/bin/other"}, "warning", "not brain ipc"),
    ("{not json", "warning", "could not be read"),
])
def test_health_says_when_the_collector_requires_the_token_and_the_settings_carry_no_helper(
        tmp_path, monkeypatch, settings, state, part):
    monkeypatch.setattr(ipchealth, "probe_mcp", lambda port, token=True: ("OFF", "mcp: nothing answers"))
    monkeypatch.setattr(ipchealth, "_docker", lambda argv: (None, ""))
    monkeypatch.setattr(ipchealth, "index_containers", lambda root=None: [])
    ipcauth.init()
    claude = Path(os.environ["CLAUDE_CONFIG_DIR"])   # the conftest's: never the owner's ~/.claude
    claude.mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (claude / "settings.json").write_text(settings if isinstance(settings, str) else json.dumps(settings),
                                              encoding="utf-8")
    assert ipchealth.claude_settings_file() == claude / "settings.json"

    def run(cfg):
        out = io.StringIO()
        return ipchealth.health(cfg, out=out), out.getvalue().splitlines()
    rc, lines = run(_config(tmp_path, monkeypatch, ipc={"require_token": ["otel-collector"]}))
    line = next(x for x in lines if "Claude Code's" in x)
    assert line.startswith(f"ipc {state} " if state != "warning" else "ipc warning: ") and part in line
    assert rc == (1 if state == "FAIL" else 0)
    _, lines = run(_config(tmp_path, monkeypatch))   # a collector that does not require the token: no such line
    assert not any("Claude Code's" in x for x in lines)


# --- install.ps1: the telemetry step, in PowerShell -------------------------------------------------------------------

def _telemetry_block() -> str:
    """The installer's telemetry step (the foreign file helpers, its function, then a call), as install.ps1 runs it."""
    text = INSTALLER.read_text(encoding="utf-8-sig")
    helpers = text[text.index("# --- the foreign file helpers"):text.index("# --- end of the foreign file helpers")]
    step = text[text.index("# --- the telemetry step"):text.index("# --- end of the telemetry step")]
    return helpers + step + "Set-ClaudeTelemetry\n"


def _ps(tmp_path, settings, payload, code=0, apply=True, venv=True):
    """The step run alone, its brain command a .cmd that prints ``payload`` and exits ``code``."""
    fake = tmp_path / "python.cmd"
    fake.write_text("@echo off\r\n" + (f"echo {payload}\r\n" if payload else "") + f"exit /b {code}\r\n",
                    encoding="utf-8")
    script = tmp_path / "install.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n"
                      f"$repo = '{tmp_path}'\n$settings_path = '{settings}'\n"
                      f"$venv_python = '{fake if venv else tmp_path / 'absent.exe'}'\n"
                      f"$Apply = ${str(apply).lower()}\n" + _telemetry_block(), encoding="utf-8")
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                          capture_output=True, text=True, timeout=60)


WANT = ('{"enabled": true, "env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_EXPORTER_OTLP_ENDPOINT": '
        '"http://127.0.0.1:4318"}, "otelHeadersHelper": "brain ipc otel-headers", "errors": []}')


def test_the_installer_documents_and_calls_the_step():
    text = INSTALLER.read_text(encoding="utf-8-sig")
    assert "if ($claude_steps) { Set-ClaudeTelemetry }" in text and "      telemetry    " in text
    assert "ipc claude-settings --json --settings $settings_path" in _telemetry_block()


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell")
def test_install_adds_the_telemetry_settings_and_keeps_the_owners_values(tmp_path):
    settings = tmp_path / "settings.json"
    before = {"enabledPlugins": {"a@b": True},
              "env": {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9999", "MINE": "owner-value"}}
    settings.write_text(json.dumps(before), encoding="utf-8")
    plan = _ps(tmp_path, settings, WANT, apply=False)
    assert plan.returncode == 0, plan.stdout + plan.stderr
    assert "set      env CLAUDE_CODE_ENABLE_TELEMETRY=1 in" in plan.stdout
    assert f"set      otelHeadersHelper = {HELPER} in" in plan.stdout
    assert "keep     env OTEL_EXPORTER_OTLP_ENDPOINT in" in plan.stdout and "9999" not in plan.stdout
    assert json.loads(settings.read_text(encoding="utf-8-sig")) == before   # a plan writes nothing
    res = _ps(tmp_path, settings, WANT)
    assert res.returncode == 0, res.stdout + res.stderr
    assert json.loads(settings.read_text(encoding="utf-8-sig")) == {
        "enabledPlugins": {"a@b": True}, "otelHeadersHelper": HELPER,
        "env": {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9999", "MINE": "owner-value",
                "CLAUDE_CODE_ENABLE_TELEMETRY": "1"}}   # additions only: the owner's value kept
    assert json.loads(Path(str(settings) + ".bak").read_text(encoding="utf-8-sig")) == before
    again = _ps(tmp_path, settings, WANT)
    assert again.returncode == 0 and "same     Claude Code's telemetry: 2 setting(s)" in again.stdout
    assert "owner-value" not in plan.stdout + res.stdout + again.stdout


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell")
@pytest.mark.parametrize("case", ["off", "errors", "old", "crash", "none", "missing"])
def test_install_telemetry_step_writes_nothing_unless_the_section_asks(tmp_path, case):
    settings = tmp_path / "settings.json"
    if case != "missing":
        settings.write_text('{"env": {}}', encoding="utf-8")
    payload = {"off": '{"enabled": false, "env": {}, "otelHeadersHelper": null, "errors": []}',
               "errors": '{"enabled": true, "env": {}, "otelHeadersHelper": null, "errors": ["endpoint off loopback"]}',
               "missing": WANT}.get(case)
    code = {"errors": 1, "old": 2, "crash": 1}.get(case, 0)
    res = _ps(tmp_path, settings, payload, code=code, venv=case != "none")
    if case == "missing":   # no settings.json yet: made with the settings alone
        assert res.returncode == 0, res.stdout + res.stderr
        assert json.loads(settings.read_text(encoding="utf-8-sig"))["otelHeadersHelper"] == HELPER
        return
    assert settings.read_text(encoding="utf-8") == '{"env": {}}'
    assert (res.returncode != 0) is (case in ("errors", "crash")), res.stdout + res.stderr
    assert {"off": "skip     Claude Code's telemetry", "errors": "error    telemetry: endpoint off loopback",
            "old": "has no ipc claude-settings yet", "crash": "brain ipc claude-settings --json failed (exit 1)",
            "none": "once the command is installed"}[case] in res.stdout
