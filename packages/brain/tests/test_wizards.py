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
