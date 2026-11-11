"""A project's command plugin (wi-brain-command-plugins): brain <project> <subcommand> runs the subcommands its
plugin brings, named under its plugin key in projects.yaml (an entry point of brain.plugins, or module:attr); a
registry without the key behaves as before; brain --help lists the plugged projects; brain check --all reports a
plugin that can never run."""

import json

import pytest

from brain import cli, plugins, projects

MODULE = '''
def register(sub, ctx):
    p = sub.add_parser("hello", help="say hello")
    p.add_argument("--name", default="world")
    sub.add_parser("fail")


def run(args, root):
    if args.cmd == "fail":
        return 3
    print(f"hello {args.name} from {args.project} at {root.name} ({args.project_obj.name})")
    return 0
'''

MAIN = '''
SEEN = []


def main(argv):
    SEEN.append(list(argv))
    return 5 if argv[:1] == ["boom"] else None
'''


@pytest.fixture
def plugged(tmp_path, monkeypatch, store):
    """A registry whose project demo plugs the module plugin, side the main one, plain none; the packages on
    sys.path, side's through an installed distribution's entry point."""
    root = store.parents[1]
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "demo_cli.py").write_text(MODULE, encoding="utf-8")
    (lib / "side_cli.py").write_text(MAIN, encoding="utf-8")
    info = lib / "side_cli-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: side-cli\nVersion: 1.0\n", encoding="utf-8")
    (info / "entry_points.txt").write_text("[brain.plugins]\nside = side_cli:main\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(lib))
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {root.as_posix()}, title: The demo, plugin: 'demo_cli:'}}\n"
                   f"side: {{root: {root.as_posix()}/side, stores: [g], plugin: side}}\n"
                   f"plain: {{root: {root.as_posix()}/plain, stores: [g]}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return reg


def _ref(reg, ref):
    reg.write_text(reg.read_text(encoding="utf-8").replace("'demo_cli:'", ref), encoding="utf-8")


def test_resolve_a_module_an_attribute_or_an_entry_point(plugged):
    import demo_cli
    import side_cli
    assert plugins.declared() == {"demo": "demo_cli:", "side": "side"}
    assert plugins.resolve("demo_cli:") is demo_cli and plugins.resolve("side_cli:main") is side_cli.main
    assert plugins.resolve("side") is side_cli.main
    assert plugins.shape(demo_cli) == "module" and plugins.shape(side_cli.main) == "main"
    assert plugins.shape(side_cli) == ""
    for ref, why in (("demo_cli:missing", "cannot be loaded"), ("nope_cli:", "cannot be loaded"),
                     ("demo", "no entry point of that name in the group brain.plugins")):
        with pytest.raises(plugins.PluginError, match=why):
            plugins.resolve(ref)


def test_a_plugin_that_cannot_load_fails_its_own_run_only(plugged, capsys):
    _ref(plugged, "'nope_cli:'")
    assert cli.main(["demo", "hello"]) == 2
    assert "plugin 'nope_cli:' cannot be loaded" in capsys.readouterr().err
    assert cli.main(["status", "--project", "demo", "--quick"]) == 0
    _ref(plugged, "'side_cli:'")   # a module that is neither a command module nor a main
    plugged.write_text(plugged.read_text(encoding="utf-8").replace("nope_cli:", "side_cli:"), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["demo", "hello"]) == 2
    assert "neither a command module" in capsys.readouterr().err


def test_brain_project_runs_a_module_plugins_subcommands_at_its_root(plugged, store, capsys):
    root = store.parents[1]
    assert cli.main(["demo", "hello", "--name", "you"]) == 0
    assert capsys.readouterr().out == f"hello you from demo at {root.name} (demo)\n"
    assert cli.main(["--root", str(root), "demo", "hello"]) == 0
    assert "hello world from demo" in capsys.readouterr().out
    assert cli.main(["demo", "fail"]) == 3
    with pytest.raises(SystemExit) as exc:   # the plugin's own parser: brain demo --help lists its subcommands
        cli.main(["demo", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: brain demo") and "hello" in out and "The demo" in out
    assert cli.main(["--project", "side", "demo", "hello"]) == 2   # --project names another project
    assert "names another" in capsys.readouterr().err


def test_a_main_plugin_from_an_entry_point_gets_the_words_after_the_project(plugged, capsys):
    import side_cli
    assert cli.main(["side", "cron", "list", "--all"]) == 0
    assert cli.main(["side", "boom"]) == 5
    assert side_cli.SEEN == [["cron", "list", "--all"], ["boom"]]


def test_a_registry_without_the_key_behaves_as_before(plugged, capsys):
    with pytest.raises(SystemExit) as exc:   # plain plugs nothing: argparse's own error, as before
        cli.main(["plain", "x"])
    assert exc.value.code == 2 and "invalid choice: 'plain'" in capsys.readouterr().err
    plugged.write_text("plain: {root: ., stores: [g]}\n", encoding="utf-8")
    assert plugins.declared() == {} and plugins.help_lines() == []


def test_brain_help_lists_the_plugged_projects_without_importing_them(plugged, capsys, monkeypatch):
    monkeypatch.setattr(plugins, "resolve", lambda ref: pytest.fail("a plugin was imported for the help"))
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "Plugged projects (brain <project> <subcommand>" in out
    assert "demo  The demo (plugin demo_cli:)" in out and "side  (plugin side)" in out and "  plain" not in out
    with pytest.raises(SystemExit):   # a command's help is its own: no paragraph
        cli.main(["status", "--help"])
    assert "Plugged projects" not in capsys.readouterr().out


def test_a_plugin_run_is_timed_as_brain_project_subcommand(plugged, monkeypatch, brain_home):
    monkeypatch.delenv("BRAIN_SELFTIME", raising=False)
    assert cli.main(["demo", "hello"]) == 0
    assert cli.main(["side", "cron", "list"]) == 0
    events = [json.loads(x) for f in sorted((brain_home / "ledger" / "engine").glob("exec-2*.jsonl"))
              for x in f.read_text(encoding="utf-8").splitlines()]
    assert [e["task"] for e in events] == ["brain demo hello", "brain side cron"]


def test_check_reports_a_plugin_that_never_runs(tmp_path, monkeypatch, capsys):
    reg = tmp_path / "projects.yaml"
    reg.write_text("status: {root: ., plugin: x}\nbad: {root: ., stores: [g], plugin: 3}\n"
                   "ok: {root: ., stores: [h], plugin: 'pkg:main'}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    errors = plugins.check(None, {"status", "item"})
    assert errors == ["project status: its plugin never runs, brain status is one of brain's commands (rename the "
                      "project or drop the key)",
                      "project bad: plugin is an entry point name of the group brain.plugins or module:attr"]
    assert "plugin" in projects.KEYS and "reserved" not in projects.KEYS["plugin"]


def test_split_skips_brains_own_options():
    assert plugins.split(["--root", "r", "--store=s", "demo", "x", "--root", "y"]) == (
        ["--root", "r", "--store=s"], "demo", ["x", "--root", "y"])
    assert plugins.split(["--help"]) is None and plugins.split([]) is None
