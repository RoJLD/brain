"""wi-brain-tui-layout, UX-20: the detail beside the list (brain.tui_side, the Textual app; test_tui has the helpers)."""

from test_tui import GRID, OVER, PANELS, _run
from textual.widgets import DataTable, Static

from brain import tui, tui_screens, tui_side


def _side_text(app):
    """What the pane shows: its title and its lines."""
    lines = [str(w.render()) for w in app.query_one("#side-body").query(Static)]
    return "\n".join([str(app.query_one("#side-title").render()), *lines])


async def _rest(pilot, app):
    """The cursor at rest, the read done, the lines mounted."""
    await pilot.pause(tui_side.FOLLOW_S + 0.1)
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)


def test_the_detail_sits_beside_a_list_and_follows_its_cursor():
    async def check(app, pilot, fake):
        side = app.query_one("#side")
        assert not side.display and not app.beside  # the cards: no list
        await pilot.press("3")
        await _rest(pilot, app)
        assert side.display and app.side_at == ("frontier", "demo/wi-one") and "First" in _side_text(app)
        table = app.query_one("#frontier", DataTable)
        assert side.region.x >= table.region.right and side.region.width == round(160 * 0.42)  # right of the list
        await pilot.press("down")
        await _rest(pilot, app)
        assert app.side_at == ("frontier", "demo/wi-three") and "Third" in _side_text(app)
        await pilot.press("1")
        await _rest(pilot, app)
        assert app.side_at[0] == "queue" and "Pick a theme" in _side_text(app)  # the queue's own first row
        await pilot.press("8")  # several panels: no pane
        await pilot.pause(0.1)
        assert not side.display and not app.beside
        await pilot.press("enter")  # the alerts' line says why: nothing opens
        await pilot.pause(0.1)
        assert app.screen is app.screen_stack[0]
    _run(check)


def _reads(monkeypatch):
    reads, of = [], tui.detail.of
    monkeypatch.setattr(tui.detail, "of", lambda name, r, cp=None, **kw: reads.append(r["id"]) or of(name, r, cp, **kw))
    return reads


def _still(fake):
    """The panels change only when the test says so: a tick reads nothing new."""
    fake.refresh = lambda probe=False: set()


def test_holding_an_arrow_reads_nothing_on_the_way(monkeypatch):
    """§10: it follows the cursor without reading at each line."""
    reads = _reads(monkeypatch)

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await _rest(pilot, app)
        assert reads == ["wi-one"]
        reads.clear()
        table = app.query_one("#frontier", DataTable)
        table.action_cursor_down()
        await pilot.pause(0.01)
        table.action_cursor_down()
        await _rest(pilot, app)
        assert reads == ["wi-two"] and app.side_at == ("frontier", "demo/wi-two")  # the row it rests on, not wi-three
    _run(check)


def test_a_row_is_read_once_until_its_panel_changes(monkeypatch):
    reads = _reads(monkeypatch)

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await _rest(pilot, app)
        table = app.query_one("#frontier", DataTable)
        table.action_cursor_down()
        await _rest(pilot, app)
        assert reads == ["wi-one", "wi-three"]
        app.draw({"queue"})  # another panel changed: what is remembered of this one stays
        await _rest(pilot, app)
        table.action_cursor_up()
        await _rest(pilot, app)
        assert reads == ["wi-one", "wi-three"] and app.side_at == ("frontier", "demo/wi-one")
        app.draw({"frontier"})  # its panel changed: read again
        await _rest(pilot, app)
        assert reads == ["wi-one", "wi-three", "wi-one"]
    _run(check)


def test_a_read_its_panels_change_overtook_is_thrown_away(monkeypatch):
    """A read running when the panel changes says what was true before: it is not remembered, nor shown for long."""
    import threading
    gate = threading.Event()
    of, seen = tui.detail.of, []

    def slow(name, r, cp=None, **kw):
        seen.append(r["id"])
        if len(seen) == 1:
            gate.wait(5)
            return {**of(name, r, cp, **kw), "title": "the old one"}
        return of(name, r, cp, **kw)
    monkeypatch.setattr(tui.detail, "of", slow)

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await pilot.pause(tui_side.FOLLOW_S + 0.1)  # the first read runs
        app.draw({"frontier"})  # the panel changes under it
        gate.set()
        await _rest(pilot, app)
        assert seen == ["wi-one", "wi-one"] and app.side_at == ("frontier", "demo/wi-one")
        assert app.side_cache[app.side_at]["title"] == "First" and "the old one" not in _side_text(app)
    _run(check)


def test_a_failed_read_is_not_remembered(monkeypatch):
    calls = []
    of = tui.detail.of

    def flaky(name, r, cp=None, **kw):
        calls.append(r["id"])
        if len(calls) == 1:
            raise OSError("disk gone")
        return of(name, r, cp, **kw)
    monkeypatch.setattr(tui.detail, "of", flaky)

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await _rest(pilot, app)
        assert "OSError: disk gone" in _side_text(app) and not app.side_cache
        await pilot.press("enter")  # Enter reads it again
        await _rest(pilot, app)
        assert "First" in _side_text(app) and calls == ["wi-one", "wi-one"]
    _run(check)


def test_enter_gives_it_the_focus_and_escape_gives_it_back(monkeypatch):
    opened = []
    monkeypatch.setattr(tui.detail, "open_link", lambda x: opened.append(x) or "opened")

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await _rest(pilot, app)
        app.side_d["links"] = [{"label": "PR demo #1", "kind": "url", "url": "https://x/pull/1"}]
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.screen is app.screen_stack[0] and app.focused is app.query_one("#side-body")  # no dialog over it
        assert app.tab == "frontier"
        await pilot.press("o")  # one link: opened
        await pilot.pause(0.1)
        assert opened == [app.side_d["links"][0]]
        app.side_d["links"].append({"label": "PR demo #2", "kind": "url", "url": "https://x/pull/2"})
        await pilot.press("o")  # two: a list to pick from
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui_screens.LinkScreen)
        assert not app.check_action("side_open", ())  # the panels' keys are off under a dialog
        await pilot.press("escape")
        await pilot.pause(0.1)
        await pilot.press("escape")  # back to the list, not to the overview
        await pilot.pause(0.1)
        assert app.tab == "frontier" and app.focused is app.query_one("#frontier")
        await pilot.press("o")  # on the list, o is its order, as before
        assert app.views["frontier"]["reverse"]
    _run(check)


def test_enter_reads_the_row_at_once(monkeypatch):
    """Enter does not wait for the cursor to rest: the pane it gives the focus to shows the row."""
    monkeypatch.setattr(tui_side, "FOLLOW_S", 30)

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert app.side_at == ("frontier", "demo/wi-one") and "First" in _side_text(app)
    _run(check)


def test_a_row_hidden_or_gone_shows_nothing_and_takes_no_key():
    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await _rest(pilot, app)
        assert app.side_d is not None
        await pilot.press("slash", *"nothing", "enter")  # the search hides every row
        await _rest(pilot, app)
        assert app.side_d is None and tui_side.NO_ROW in _side_text(app)
        assert not app.check_action("side_open", ())
        await pilot.press("enter")  # the line that says why: the focus stays on the list
        await pilot.pause(0.1)
        assert app.focused is app.query_one("#frontier")
        table = app.query_one("#frontier", DataTable)
        table.clear()
        assert app._side_row("frontier") is None  # no row at all
    _run(check)


def test_the_foot_and_the_lines_follow_and_the_same_detail_is_not_redrawn(monkeypatch):
    of = tui.detail.of

    def linked(name, r, cp=None, **kw):
        return {**of(name, r, cp, **kw), "links": [{"label": f"the item {r['id']}", "kind": "item", "id": r["id"],
                                                    "project": "demo"}]}
    monkeypatch.setattr(tui.detail, "of", linked)

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await _rest(pilot, app)
        foot = app.query_one("#side-foot")
        assert "o opens: the item wi-one" in str(foot.render())
        body = app.query_one("#side-body")
        first = list(body.children)
        app.draw({"frontier"})  # read again, the same detail: the same widgets
        await _rest(pilot, app)
        assert list(body.children) == first
        await pilot.press("down")
        await _rest(pilot, app)
        assert list(body.children) != first and "o opens: the item wi-three" in str(foot.render())
    _run(check)


def test_no_link_or_action_no_key():
    async def check(app, pilot, fake):
        _still(fake)
        assert not app.check_action("side_open", ()) and not app.check_action("side_act", ("answer",))  # no pane
        await pilot.press("1")
        await _rest(pilot, app)
        assert app.side_d["actions"] == [] and not app.check_action("side_act", ("answer",))
        assert not app.check_action("side_open", ())  # this entry has no link
        app.side_d["actions"] = [tui.detail.Action("answer", "Answer", "demo", "x", None)]
        assert app.check_action("side_act", ("answer",))
        await pilot.press("8")  # no pane on this tab: what it last showed gives no key
        await pilot.pause(0.1)
        assert not app.beside and app.side_d is not None and not app.check_action("side_act", ("answer",))
    _run(check)


def test_the_actions_wait_for_the_rows_own_detail(tmp_path, monkeypatch):
    """Never on the row the cursor left: a, d and A are off until the pane shows the row under the cursor."""
    monkeypatch.setattr(tui_side, "FOLLOW_S", 30)  # the cursor moved, its detail not read yet

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("1", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        app.side_d["actions"] = [tui.detail.Action("answer", "Answer", "demo", "x", None)]
        assert app.check_action("side_act", ("answer",))
        await pilot.press("escape")
        await pilot.pause(0.1)
        await pilot.press("down")
        assert app.side_at != ("queue", app._side_row("queue")) and not app.check_action("side_act", ("answer",))
        await pilot.press("a")
        await pilot.pause(0.1)
        assert app.screen is app.screen_stack[0]  # nothing opened on the old row
    _run(check)


def test_d_and_a_capital_run_their_own_action(tmp_path, monkeypatch):
    from brain import projects, queue
    root = tmp_path / "demo"
    ddr, _, _ = queue.add(root, kind="action", title="Apply the seed", what=r"Then .\install.ps1 -Apply.",
                          at="2026-11-02T10:00:00Z", project="demo")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(tui.detail, "run", lambda a, steps: [
        {"command": tui.detail.shown(s), "exit": 0, "seconds": 0.1, "output": "out"} for s in steps])
    entry = {"id": ddr["id"], "kind": "action", "source": "ddr", "unblocks": 0, "age_days": 0, "title": "Apply the seed",
             "since": ""}
    panels = {**PANELS, "queue": {"projects": [{"project": "demo", "entries": [entry]}]}}

    async def check(app, pilot, fake):
        _still(fake)
        fake.choices["demo"] = projects.Project("demo", root)
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"queue"})
        await pilot.press("1")
        await _rest(pilot, app)
        assert sorted(a.kind for a in app.side_d["actions"]) == ["apply", "done"]
        await pilot.press("d")
        await pilot.pause(0.2)
        assert isinstance(app.screen, tui_screens.ConfirmScreen) and app.screen.a.kind == "done"
        await pilot.press("n")
        await pilot.pause(0.1)
        await pilot.press("A")
        await pilot.pause(0.3)
        assert isinstance(app.screen, tui_screens.ConfirmScreen) and app.screen.a.kind == "apply"
    _run(check)


def test_the_actions_work_from_the_list_and_from_the_pane(tmp_path, monkeypatch):
    from brain import decisions, projects
    root = tmp_path / "demo"
    ddr, _ = decisions.ask(root, title="Pick a layout", question="Grid or tabs?", at="2026-11-02T10:00:00Z", why="both",
                           options=["Grid and tabs", "Tabs only"], project="demo")
    ran = []
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setattr(tui.detail, "run", lambda a, steps: ran.append((a.kind, steps)) or [
        {"command": tui.detail.shown(steps[0]), "exit": 0, "seconds": 0.1, "output": "answered"}])
    entry = {"id": ddr["id"], "kind": "decision", "source": "ddr", "unblocks": 0, "age_days": 0, "title": "Pick a layout",
             "since": "", "how": f"brain decision answer {ddr['id']} <option>"}
    panels = {**PANELS, "queue": {"projects": [{"project": "demo", "counts": {"decision": 1}, "entries": [entry]}]}}
    reads = _reads(monkeypatch)

    async def check(app, pilot, fake):
        _still(fake)
        fake.choices["demo"] = projects.Project("demo", root)
        fake.snapshot = lambda: {"scope": "demo", "read_at": None, "probed_at": None, "panels": panels}
        app.draw({"queue"})
        await pilot.press("1")
        await _rest(pilot, app)
        assert [a.kind for a in app.side_d["actions"]] == ["answer"] and app.check_action("side_act", ("answer",))
        assert not app.check_action("side_act", ("done",))
        assert app.focused is app.query_one("#queue")
        await pilot.press("d")  # not this row's: nothing
        await pilot.pause(0.1)
        assert app.screen is app.screen_stack[0]
        await pilot.press("a")  # from the list: the same dialog as in the detail over it
        await pilot.pause(0.1)
        answer = app.screen
        assert isinstance(answer, tui_screens.AnswerScreen) and answer.title_text == "Pick a layout"
        assert not app.check_action("side_act", ("answer",))  # the panels' keys are off under a dialog
        await pilot.press("escape")
        await pilot.pause(0.1)
        await pilot.press("enter", "a")  # from the pane
        await pilot.pause(0.1)
        answer = app.screen
        assert isinstance(answer, tui_screens.AnswerScreen)
        answer.query(tui_screens.RadioButton).first().value = True
        await pilot.pause(0.1)
        await pilot.click("#ok")
        await pilot.pause(0.1)
        before = len(reads)
        await pilot.press("y")
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        assert [k for k, _ in ran] == ["answer"] and app.screen is app.screen_stack[0]
        await _rest(pilot, app)
        assert len(reads) == before + 1 and app.side_at == ("queue", f"demo/{ddr['id']}")  # its entry changed: read again
    _run(check)


def test_a_narrower_terminal_opens_the_detail_over_the_list(monkeypatch):
    """UX-20: under 140 columns the dialog; a resize moves between the two, the focus never left in a hidden pane."""
    async def check(app, pilot, fake):
        await pilot.press("3")
        await _rest(pilot, app)
        assert not app.query_one("#side").display
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.DetailScreen)
        await pilot.press("escape")
        await pilot.pause(0.1)
        await pilot.resize_terminal(140, 48)
        await pilot.pause(0.2)
        await _rest(pilot, app)
        assert app.beside and app.query_one("#side").display and app.side_at == ("frontier", "demo/wi-one")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.focused is app.query_one("#side-body")
        await pilot.resize_terminal(139, 48)
        await pilot.pause(0.2)
        assert not app.beside and app.focused is app.query_one("#frontier")
    _run(check, size=OVER)


def test_a_resize_under_a_dialog_gives_the_focus_back_to_the_list():
    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await _rest(pilot, app)
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.focused is app.query_one("#side-body")
        await pilot.press("i")
        await pilot.pause(0.1)
        await pilot.resize_terminal(130, 48)
        await pilot.pause(0.2)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not app.beside and app.focused is app.query_one("#frontier")
    _run(check)


def test_the_grid_opens_the_detail_over_it_even_when_wide():
    async def check(app, pilot, fake):
        assert not app.beside
        app.query_one("#frontier").focus()
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, tui.DetailScreen)
    _run(check, tabs=GRID)


def test_a_late_answer_is_not_shown_over_the_row_the_cursor_moved_to(monkeypatch):
    import threading
    gate = threading.Event()
    of = tui.detail.of

    def slow(name, r, cp=None, **kw):
        if r["id"] == "wi-one":
            gate.wait(5)
        return of(name, r, cp, **kw)
    monkeypatch.setattr(tui.detail, "of", slow)

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await pilot.pause(tui_side.FOLLOW_S + 0.1)  # wi-one is being read
        await pilot.press("down")
        await pilot.pause(tui_side.FOLLOW_S + 0.1)
        await pilot.pause(0.1)
        assert app.side_at == ("frontier", "demo/wi-three")
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert app.side_at == ("frontier", "demo/wi-three") and "Third" in _side_text(app)  # the old answer not shown
        assert ("frontier", "demo/wi-one") in app.side_cache  # but kept
    _run(check)


def test_the_same_detail_keeps_its_scroll_and_another_row_starts_at_its_top(monkeypatch):
    many = [str(i) for i in range(200)]
    of = tui.detail.of

    def long(name, r, cp=None, **kw):
        d = of(name, r, cp, **kw)
        d["sections"] = [("Lines", many)]
        return d
    monkeypatch.setattr(tui.detail, "of", long)

    async def check(app, pilot, fake):
        _still(fake)
        await pilot.press("3")
        await _rest(pilot, app)
        body = app.query_one("#side-body")
        body.scroll_to(y=30, animate=False, immediate=True)
        await pilot.pause(0.1)
        assert body.scroll_y == 30
        app.draw({"frontier"})  # read again, the same lines: nothing moves
        await _rest(pilot, app)
        assert body.scroll_y == 30
        await pilot.press("down")
        await _rest(pilot, app)
        assert body.scroll_y == 0
    _run(check)
