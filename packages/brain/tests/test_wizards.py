"""wi-brain-tui-setup: the setup wizards as data (brain.wizards): every step a brain command the CLI parses, a plan
before an apply, what stays the owner's said; the cockpit's Setup page runs them (test_tui_settings)."""

import pytest

from brain import cli, settings, wizards


def _every_choice(w):
    return w.choices or ("",)


def test_every_wizard_step_is_a_brain_command_the_cli_parses():
    """Each step is a logged brain command, never a hidden edit: the words a wizard runs parse as brain's own."""
    parser = cli.build_parser()
    seen = 0
    for w in wizards.wizards():
        for choice in _every_choice(w):
            for which in ("plan", "apply"):
                words = w.words(which, choice, "new-brain" if w.ask else "")
                if words is None:
                    continue
                assert words[0] == "brain", (w.id, words)
                parser.parse_args(words[1:])  # SystemExit on a word the command does not take
                seen += 1
    assert seen > len(wizards.wizards())


def test_a_wizard_plans_before_it_applies_and_says_what_stays_the_owners():
    ws = wizards.by_id()
    first = ws["first-run"]
    assert first.choices == ("lite", "default", "recommended") and not first.reads
    assert first.words("plan", "lite") == ["brain", "profile", "set", "lite"]
    assert first.words("apply", "lite") == ["brain", "profile", "set", "lite", "--apply"]
    inst = ws["instance"]
    assert inst.words("apply", "generic", "D:/x") == ["brain", "init", "D:/x", "--template", "generic", "--apply"]
    assert inst.ask and "generic" in inst.choices and not any(c.startswith("_") for c in inst.choices)
    assert ws["notify-telegram"].words("plan", "") == ["brain", "notify", "setup", "telegram"]
    assert ws["checks"].reads and ws["checks"].words("apply") is None
    # a change of Claude Code's settings or install.ps1, a project added, a grant: a plan only, the owner's to run
    for wid in ("claude-settings", "project", "permissions"):
        assert ws[wid].apply is None and ws[wid].owner and not ws[wid].reads
    assert "install.ps1 -Apply" in ws["claude-settings"].owner
    assert "--apply" not in " ".join(" ".join(w.plan or []) for w in ws.values())  # a plan never writes
    assert ws["first-run"].command() == ("brain profile set lite|default|recommended, then brain profile set "
                                         "lite|default|recommended --apply")
    assert ws["notify-telegram"].command() == "brain notify setup telegram [--find-chat]"
    assert ws["instance"].command().startswith("brain init DIR --template TEMPLATE")


def test_the_stacks_offered_are_the_built_ones_and_an_unreadable_registry_offers_none(monkeypatch):
    stacks = wizards.by_id()["stacks"].choices
    assert stacks and all(c.startswith("--with ") for c in stacks)
    from brain import tiers

    def broken(root):
        raise OSError("unreadable")
    monkeypatch.setattr(tiers, "registry", broken)
    assert wizards.by_id()["stacks"].choices == ()


def test_the_setup_page_lists_the_wizards_and_never_a_secret(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "a-secret-topic-value")
    rows = settings.collect(pages=("setup",))["setup"]
    assert [s.key for s in rows] == [w.id for w in wizards.wizards()]
    assert all(s.edit == "wizard" for s in rows)
    by = {s.key: s for s in rows}
    assert by["claude-settings"].change.endswith("yours: install.ps1 -Apply, in the owner's own terminal: it writes "
                                                 "~/.claude/settings.json")
    text = "\n".join(settings.lines({"setup": rows}))
    assert "a-secret-topic-value" not in text and "  first-run: First run: the profile" in text


@pytest.mark.parametrize("wid", ["modules", "project", "notify-ntfy", "machines", "checks"])
def test_a_wizard_without_a_choice_runs_its_plan_as_is(wid):
    w = wizards.by_id()[wid]
    assert not w.choices and not w.ask and w.words("plan") == w.plan


def test_a_new_brains_folder_is_an_absolute_path_never_an_option():
    """Review of wi-brain-tui-setup: the folder typed goes into brain init's plan, run before any yes."""
    assert wizards.folder('"D:\\brains\\new"') == "D:\\brains\\new" or wizards.folder('"/srv/new"') == "/srv/new"
    assert wizards.folder("  '/srv/new brain'  ") == str(__import__("pathlib").PurePath("/srv/new brain"))
    for wrong in ("--apply", "-x", "new-brain", "./x", "", '""'):
        with pytest.raises(ValueError):
            wizards.folder(wrong)


def test_the_notification_and_index_wizards_run_for_the_project_shown():
    ws = wizards.by_id()
    assert ws["notify-status"].words("plan", project="demo") == ["brain", "--project", "demo", "notify", "status"]
    assert ws["code-index"].words("apply", project="demo") == ["brain", "--project", "demo", "index", "--stale"]
    assert ws["first-run"].words("plan", "lite", project="demo") == ["brain", "profile", "set", "lite"]  # the machine's
    cli.build_parser().parse_args(ws["notify-status"].words("plan", project="demo")[1:])


def test_a_module_turns_on_or_off_by_brain_mods_plan_then_its_apply():
    """wi-brain-modules-tab: the Modules page's wizard: brain mod enable|disable ID, a plan then --apply."""
    on, off, part = (wizards.module_wizard("tui", "on"), wizards.module_wizard("plane", "off"),
                     wizards.module_wizard("x", "partly on (1/2)"))
    assert on.choices == ("disable", "disable --cascade") and off.choices == ("enable",) and len(part.choices) == 3
    assert on.words("plan", "disable --cascade") == ["brain", "mod", "disable", "--cascade", "tui"]
    assert off.words("apply", "enable") == ["brain", "mod", "enable", "plane", "--apply"]
    parser = cli.build_parser()
    for w in (on, off):
        for c in w.choices:
            parser.parse_args(w.words("apply", c)[1:])


# --- the Local services step (wi-brain-wizard-local-services) ---

LOCAL_IDS = ["local-token", "local-claude-export", "local-require-token", "local-bundle", "local-health",
             "local-cursor"]


def test_the_local_services_steps_come_in_their_order_before_the_checks():
    ids = [w.id for w in wizards.wizards()]
    assert [i for i in ids if i.startswith("local-")] == LOCAL_IDS
    # the token, then the export's header, then the collector requiring it, then the bundle: the order of the ADR
    assert ids.index("local-token") < ids.index("local-require-token") < ids.index("local-bundle") < ids.index("checks")
    assert ids[-1] == "checks"


def test_the_owners_steps_stay_plans_and_the_others_plan_before_they_apply():
    ws = wizards.by_id()
    tok = ws["local-token"]
    assert tok.words("plan") == ["brain", "ipc", "token", "--plan"] and tok.words("apply") == [
        "brain", "ipc", "token", "--init"]
    assert ws["local-bundle"].words("apply") == ["brain", "bundle", "apply", "sovereign"]
    for wid in ("local-claude-export", "local-require-token", "local-cursor"):   # a settings file, a PR, a render
        assert ws[wid].apply is None and ws[wid].owner and not ws[wid].reads, wid
    assert "install.ps1 -Apply" in ws["local-claude-export"].owner and "never a session edit" in \
        ws["local-claude-export"].owner
    assert "ipc.require_token: [otel-collector]" in ws["local-require-token"].owner
    assert ws["local-health"].reads and ws["local-health"].words("plan") == ["brain", "health", "ipc"]
    assert all(any(n.startswith("optional") for n in ws[i].notes) for i in LOCAL_IDS)   # each says it may be skipped


def test_the_tokens_plan_never_fails_and_never_shows_the_token(brain_home, capsys):
    """A plan that fails keeps the wizard's apply off: --plan exits 0 with or without a token."""
    from brain import ipcauth
    assert cli.main(["ipc", "token", "--plan"]) == 0
    assert "no usable token: --init makes it" in capsys.readouterr().out
    assert cli.main(["ipc", "token", "--init"]) == 0
    capsys.readouterr()
    assert cli.main(["ipc", "token", "--plan"]) == 0
    out = capsys.readouterr().out
    assert "a usable token: --init keeps it" in out and ipcauth.read() not in out
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["ipc", "token", "--plan", "--init"])


def test_brain_init_prints_the_local_services_in_the_same_order():
    lines = wizards.local_lines()
    assert lines[0].strip().startswith("local services (optional: only where the telemetry collector runs")
    assert [ln.strip().split(".", 1)[0] for ln in lines[1:]] == ["1", "2", "3", "4", "5", "6"]
    assert lines[1].strip() == "1. brain ipc token --plan, then brain ipc token --init"
    assert "the owner's: install.ps1 -Apply" in lines[2] and "brain bundle apply sovereign" in lines[4]
