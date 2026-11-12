"""wi-brain-tui-settings: the settings as data (brain.settings), the remembered intervals and the text view; the
Settings tab of the Textual app is test_tui_tabs'."""

import json

import pytest

from test_cockpit import _cockpit

from brain import cli, cockpit, settings


def _by_key(rows):
    return {s.key: s for s in rows}


def test_the_cockpit_page_says_each_setting_its_place_and_how_it_changes():
    """Spec cockpit-ux §4.13: each setting, its value, the file it comes from, the command (or the screen) that
    changes it; the cockpit's own are edited here, a default shown when nothing is set."""
    rows = _by_key(settings.cockpit_settings({"scope": "demo", "settings": {"tz": "utc", "refresh": 5.0,
                                                                            "titles": {"queue": "Ma file"}}},
                                             themes=("nord", "textual-dark")))
    tui_json = str(cockpit.state_path())
    assert rows["tz"].value == "utc" and rows["tz"].edit == "choice" and rows["tz"].choices == cockpit.TZS
    assert rows["tz"].source == f"{tui_json} settings.tz" and rows["tz"].change.startswith(settings.HERE)
    assert rows["theme"].value == "textual-dark" and rows["theme"].choices == ("nord", "textual-dark")  # its default
    assert rows["refresh"].value == "5 s" and rows["refresh"].edit == "duration" and rows["refresh"].default == "2 s"
    assert rows["probe"].value == "5 min"  # the default
    assert rows["titles.queue"].value == "Ma file" and rows["titles.queue"].edit == "text"
    assert rows["titles.sessions"].value == "Sessions"  # no free title: the panel's own
    assert rows["scope"].value == "demo" and not rows["scope"].edit  # p changes it, not a dialog
    assert {f"titles.{n}" for n in (*cockpit.PANELS, *cockpit.FRAMES)} <= set(rows)


def test_brain_lang_wins_and_the_page_says_so(monkeypatch):
    monkeypatch.setenv("BRAIN_LANG", "fr")
    lang = _by_key(settings.cockpit_settings({"settings": {"lang": "en"}}))["lang"]
    assert lang.value == "fr" and lang.source.startswith("$BRAIN_LANG") and "unset $BRAIN_LANG" in lang.change
    assert settings.page_label("setup") == "Mise en place"


def test_a_value_typed_is_checked_then_set_or_removed():
    assert settings.parse("refresh", "500ms") == 0.5 and settings.parse("probe", "10m") == 600.0
    assert settings.parse("tz", "utc") == "utc" and settings.parse("titles.queue", "  Ma file ") == "Ma file"
    assert settings.parse("theme", "nord", ("nord",)) == "nord"
    assert settings.parse("refresh", "") is None  # empty: the default
    for wrong in (("refresh", "100ms"), ("refresh", "soon"), ("tz", "mars"), ("lang", "de"),
                  ("theme", "pink", ("nord",)), ("titles.nowhere", "x"), ("registry", "x")):
        with pytest.raises(ValueError):
            settings.parse(*wrong)
    before = {"tz": "utc", "titles": {"queue": "Ma file"}}
    after = settings.edited(before, "titles.queue", None)
    assert after == {"tz": "utc"} and before == {"tz": "utc", "titles": {"queue": "Ma file"}}  # a copy
    assert settings.edited(after, "titles.digest", "News") == {"tz": "utc", "titles": {"digest": "News"}}
    assert settings.edited(after, "tz", None) == {} and settings.edited(after, "refresh", 5.0)["refresh"] == 5.0


def test_the_refresh_and_probe_intervals_are_remembered():
    cockpit.save_state({"settings": {"refresh": 5, "probe": 60.0, "theme": "nord"}})
    assert cockpit.load_state()["settings"] == {"refresh": 5.0, "probe": 60.0, "theme": "nord"}
    cockpit.save_state({"settings": {"refresh": 0.1, "probe": "1m"}})  # too short, not a number: left out
    assert cockpit.load_state()["settings"] == {}
    cockpit.save_state({"settings": {"refresh": True}})
    assert cockpit.load_state()["settings"] == {}


def test_the_brain_pages_name_each_place_and_never_a_secret(tmp_path, monkeypatch):
    root = tmp_path / "brain"
    root.mkdir()
    (root / "config.json").write_text(json.dumps({
        "v": 1, "identity": {"owner": "Ada", "display_name": "Ada L."},
        "engine": {"pin": "v0.3.2"}, "scope_types": {"lab": {"en": "Lab", "fr": "Labo"}}}), encoding="utf-8")
    (root / "projects.yaml").write_text(
        "demo:\n  root: .\n  notify:\n    channels: {phone: {type: ntfy, topic_env: DEMO_NTFY_TOPIC}}\n"
        "    levels: {warn: phone}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.setenv("DEMO_NTFY_TOPIC", "a-secret-topic-value")
    pages = settings.collect(root)
    assert list(pages) == list(settings.PAGES)
    ident = _by_key(pages["identity"])
    assert ident["identity.owner"].value == "Ada" and ident["identity.display_name"].value == "Ada L."
    assert ident["identity.display_name"].source == f"{root / 'config.json'} identity.display_name"
    assert "no brain config set" in ident["identity.owner"].change and not ident["identity.owner"].edit
    brain = _by_key(pages["brain"])
    assert brain["engine.pin"].value == "v0.3.2" and brain["registry"].value == str(root / "projects.yaml")
    assert brain["notify routes"].value == "demo" and "brain notify status" in brain["notify routes"].change
    assert brain["scope_types"].value == "1 renamed or added"
    assert brain["claude settings"].change.startswith("a plan only")  # install.ps1 -Apply is the owner's
    assert "brain profile set" in brain["profile"].change
    assert not any(s.edit for page in ("identity", "brain", "permissions", "setup") for s in pages[page])
    text = "\n".join(settings.lines(pages))
    assert "a-secret-topic-value" not in text and "Identity (4)" in text and "  identity.owner: Ada" in text
    assert "brain notify setup ntfy|telegram|email" in text  # the setup page: one command per step


def test_a_page_that_cannot_be_read_says_why_and_the_others_still_read(monkeypatch):
    def broken(root=None):
        raise OSError("the disk is gone")
    monkeypatch.setitem(settings.READERS, "permissions", broken)
    pages = settings.collect()
    (row,) = pages["permissions"]
    assert row.key == "read failed" and row.value == "OSError: the disk is gone"
    assert pages["setup"] and pages["cockpit"]


def test_brain_tui_prints_the_settings_and_starts_with_the_remembered_intervals(tmp_path, monkeypatch, store, capsys):
    _cockpit(tmp_path, monkeypatch, store)
    assert cli.main(["tui", "--project", "demo", "--once", "--quick", "--tab", "settings"]) == 0
    out = capsys.readouterr().out
    assert "\nCockpit (" in out and "\nSetup (" in out and "  tz: local" in out and "change: here: Enter" in out
    seen = {}
    monkeypatch.setattr(cockpit, "watch", lambda cp, refresh_s, probe_s, **kw: seen.update(r=refresh_s, p=probe_s) or 0)
    cockpit.save_state({"settings": {"refresh": 5.0, "probe": 60.0}})
    assert cli.main(["tui", "--project", "demo", "--plain"]) == 0
    assert seen == {"r": 5.0, "p": 60.0}  # the Settings tab's
    assert cli.main(["tui", "--project", "demo", "--plain", "--refresh", "1s"]) == 0
    assert seen == {"r": 1.0, "p": 60.0}  # the flag wins
    assert cockpit.load_state()["settings"]["refresh"] == 5.0  # for that launch only
    assert cli.main(["tui", "--project", "demo", "--plain", "--reset"]) == 0
    assert seen == {"r": cockpit.REFRESH_S, "p": cockpit.PROBE_S}
