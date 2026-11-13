"""brain review: the review packet at zero token, the stamp of a reviewed head, the merge gate's check
(wi-brain-review-step)."""

import json

import pytest

from brain import cli, review


@pytest.fixture
def pr(make_repo):
    """A repo whose main has one commit and a branch two more: a guard, a schema, a test and a doc touched."""
    repo = make_repo("eng", {"src/brain/guards.py": "x = 1\n", "README.md": "# Eng\n"})
    base = make_repo.commit(repo, {"src/brain/schemas/config.json": "{}\n"})
    import subprocess
    subprocess.run(["git", "branch", "main-tip", base], cwd=repo, check=True)
    make_repo.commit(repo, {"src/brain/guards.py": "x = 2\n", "tests/test_guards.py": "def test(): pass\n"})
    head = make_repo.commit(repo, {"docs/guards.md": "# Guards\n", "README.md": None})
    return repo, base, head


def test_prep_writes_the_packet_with_the_lenses_the_surfaces_call_for(pr, brain_home):
    repo, base, head = pr
    p = review.prep(repo, f"{base}..{head}", scout=False)
    folder = review.folder_for(head)
    assert p.folder == str(folder) and p.head == head
    assert sorted(p.files) == ["README.md", "docs/guards.md", "src/brain/guards.py", "tests/test_guards.py"]
    # no schema, installer or procedure touched
    assert p.lenses == ["correctness", "scope", "security", "tests", "docs"]
    assert (folder / "files" / "src" / "brain" / "guards.py").read_text(encoding="utf-8") == "x = 2\n"
    assert not (folder / "files" / "README.md").exists()   # deleted at the head
    assert "+x = 2" in (folder / "diff.patch").read_text(encoding="utf-8")
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert f"brain review stamp {head}" in readme and "**security**" in readme and "**compatibility**" not in readme
    assert json.loads((folder / "packet.json").read_text(encoding="utf-8"))["lenses"] == p.lenses


def test_a_packet_prepared_again_keeps_no_file_of_an_older_diff(pr, brain_home, tmp_path):
    repo, base, head = pr
    out = tmp_path / "packet"
    review.prep(repo, f"{base}..{head}", out, scout=False)
    stale = out / "files" / "old.py"
    stale.write_text("from an older diff\n", encoding="utf-8")
    review.prep(repo, f"{base}..{head}", out, scout=False)
    assert not stale.exists() and (out / "files" / "docs" / "guards.md").is_file()


def test_a_schema_or_an_installer_calls_their_lenses():
    assert review.lenses_for(["packages/brain/src/brain/schemas/x.json", "packages/brain/installer/install.ps1"]) == [
        "correctness", "scope", "compatibility", "install and upgrade"]
    assert review.lenses_for(["packages/brain/src/brain/procedures/close-item/SKILL.md"]) == [
        "correctness", "scope", "procedure", "docs"]


def test_the_scope_lens_is_always_asked_and_the_skeptics_carry_the_evidence_rule(pr, brain_home):
    """wi-brain-review-scope-lens (TR-3): scope on every diff, even one file of no named surface; the packet's README
    says the scope lens's ask and that a negative claim stands only with its query and that query's coverage."""
    assert review.lenses_for(["a/b.txt"]) == ["correctness", "scope"]
    repo, base, head = pr
    review.prep(repo, f"{base}..{head}", scout=False)
    readme = (review.folder_for(head) / "README.md").read_text(encoding="utf-8")
    assert "- **scope**: a changed line the item does not need" in readme and "follow-up item" in readme
    assert "a negative claim (nothing calls it, untested, no other reader" in readme
    assert "the query that shows it and that query's coverage" in readme


def test_stamp_then_check_by_the_heads_full_sha_and_a_new_head_is_not_reviewed(pr, brain_home, tmp_path, capsys):
    repo, base, head = pr
    assert cli.main(["review", "check", head, "--repo", str(repo)]) == 1
    note = tmp_path / "note.md"
    note.write_text("3 lenses, 2 findings kept\n", encoding="utf-8")
    assert cli.main(["review", "stamp", "HEAD", "--findings", "2", "--fixed", "1", "--contested", "1",
                     "--note", str(note), "--repo", str(repo)]) == 0
    assert cli.main(["review", "check", head, "--repo", str(repo)]) == 0
    assert "2 finding(s), 1 fixed, 1 contested, 0 open" in capsys.readouterr().out
    assert review.check(head)["note"] == "3 lenses, 2 findings kept\n"
    assert review.check(base) is None   # another head: reviewed again


def test_stamp_refuses_counts_that_do_not_add_up_and_an_unknown_target(pr, brain_home, capsys):
    repo, base, head = pr
    with pytest.raises(review.ReviewError, match="fixed and contested are among the findings"):
        review.stamp(head, 1, 1, 1)
    with pytest.raises(review.ReviewError, match="a full commit sha"):
        review.stamp(head[:8], 1, 1)
    assert cli.main(["review", "prep", "nope..HEAD", "--repo", str(repo), "--no-scout"]) == 1
    assert "git fetch first" in capsys.readouterr().err


# --- the error score (wi-brain-review-error-score) ---

NOTE = """Review of the item: three lenses, two skeptics each.
- high correctness A.b fixed: a rotation cut between two writes leaves a plain copy
- fixed A.e docs medium: the runbook says it refuses
- severity=low lens=tests cause=C outcome=contested when=after covered: the owner's git config read
- low scope refuted: the rename is the item's own
- Refuted: a claim nobody upheld
- high risk: prose, not a finding line
1. medium: a numbered line is prose too
"""


def test_the_notes_finding_lines_in_any_order_and_prose_left_out():
    rows = review.parse_note(NOTE)
    assert [(r["severity"], r["lens"], r["cause"], r["outcome"], r["when"], r["covered"]) for r in rows] == [
        ("high", "correctness", "A.b", "fixed", "before", ""), ("medium", "docs", "A.e", "fixed", "before", ""),
        ("low", "tests", "C", "contested", "after", "covered"), ("low", "scope", "", "refuted", "before", "")]
    assert rows[0]["text"] == "a rotation cut between two writes leaves a plain copy"
    assert len(review.confirmed(rows)) == 3   # a refuted line is kept, not counted
    assert review.parse_note("- install medium: the upgrade step")[0]["lens"] == "install and upgrade"
    assert review.parse_note("") == [] and review.parse_note("- G high: an unknown family") == []


def _rec(head, findings, wave="", pr="", at="2026-11-01T10:00:00+00:00", rows=()):
    return {"v": 1, "head": head, "at": at, "findings": findings, "fixed": findings, "contested": 0, "open": 0,
            "note": "", "wave": wave, "pr": pr, "rows": list(rows)}


def test_score_counts_each_pr_once_by_its_latest_stamp_and_orders_the_waves():
    rows = review.parse_note(NOTE)
    recs = [_rec("a" * 40, 9, "0.3.9", "10", at="2026-11-01T10:00:00+00:00"),
            _rec("b" * 40, 4, "0.3.9", "10", at="2026-11-01T12:00:00+00:00", rows=rows),   # PR 10 again: this one
            _rec("c" * 40, 2, "0.3.10", "11"), _rec("d" * 40, 6, "0.3.10", "12"), _rec("e" * 40, 1)]
    sc = review.score(recs)
    assert [(w["wave"], w["prs"], w["findings"], w["per_pr"]) for w in sc["waves"]] == [
        ("0.3.9", 1, 4, 4.0), ("0.3.10", 2, 8, 4.0)]   # 0.3.10 after 0.3.9: release order, not text
    t = sc["total"]
    assert (t["prs"], t["findings"], t["rows"], sc["unplaced"]) == (4, 13, 3, 1)
    assert t["severity"] == {"high": 1, "medium": 1, "low": 1} and t["cause"] == {"A.b": 1, "A.e": 1, "C": 1}
    assert t["after"] == 1 and t["covered"] == 1
    assert sc["lighten"] == {"ok": False, "why": "2 wave(s) scored, 3 needed"}
    text = "\n".join(review.score_lines(sc, "0.3.9"))
    assert "review error score, wave 0.3.9: 1 PR(s) reviewed, 4 confirmed finding(s), 4.0 per PR" in text
    assert "by root cause: A.b 1, A.e 1, C 1; 1 found after the merge, 1 a script now covers" in text
    assert "per wave: 0.3.9 4.0 (1 PR), 0.3.10 4.0 (2 PR)" in text and "1 stamp(s) placed in no wave" in text
    assert "the reviews stay complete: 2 wave(s) scored, 3 needed" in text


def test_the_reviews_lighten_only_once_the_score_falls_over_two_waves_in_a_row():
    def trend(*per):
        return [{"wave": f"0.{i}.0", "per_pr": p} for i, p in enumerate(per)]
    assert review.lighten(trend(9, 7, 5))["ok"]
    why = review.lighten(trend(3, 9, 7, 5))["why"]   # the last three waves only
    assert why == "findings per PR 0.1.0 9 -> 0.2.0 7 -> 0.3.0 5: fell over two waves"
    for per in ((9, 5, 5), (9, 4, 6), (5, 7, 3), (9, 7)):
        assert not review.lighten(trend(*per))["ok"], per


def test_stamp_places_the_review_and_says_when_the_note_and_the_counts_differ(pr, brain_home, tmp_path, capsys,
                                                                              monkeypatch):
    from types import SimpleNamespace

    from brain import standards, waves
    repo, base, head = pr
    note = tmp_path / "review.md"
    note.write_text(NOTE, encoding="utf-8")
    plan = SimpleNamespace(wave_of=lambda nid: "wave-0.4.1" if nid == "wi-x" else None, label=lambda w: "0.4.1",
                           resolve=lambda ref: None, waves=["wave-0.4.1"])
    monkeypatch.setattr(standards, "project_of_repo", lambda r: SimpleNamespace(stores=[tmp_path]))
    monkeypatch.setattr(waves, "applies", lambda store: True)
    monkeypatch.setattr(waves, "load", lambda store: plan)
    assert cli.main(["review", "stamp", head, "--findings", "4", "--fixed", "4", "--note", str(note), "--pr", "7",
                     "--item", "wi-x", "--stream", "lot review", "--repo", str(repo)]) == 0
    out = capsys.readouterr()
    assert "wave 0.4.1" in out.out and "the note describes 3 confirmed finding line(s), --findings says 4" in out.err
    rec = review.check(head)
    assert (rec["pr"], rec["item"], rec["wave"], rec["stream"], len(rec["rows"])) == ("7", "wi-x", "0.4.1",
                                                                                      "lot review", 4)
    assert rec["wave_id"] == "wave-0.4.1"   # the wave's stable id: its label may move
    # an item no plan places, and --wave given: the stamp says what it was told
    assert cli.main(["review", "stamp", base, "--findings", "0", "--fixed", "0", "--item", "wi-y", "--wave", "0.4.2",
                     "--repo", str(repo)]) == 0
    assert review.check(base)["wave"] == "0.4.2" and "pr" not in review.check(base)
    capsys.readouterr()
    assert cli.main(["review", "score", "--json"]) == 0
    sc = json.loads(capsys.readouterr().out)
    assert [w["wave"] for w in sc["waves"]] == ["0.4.1", "0.4.2"] and sc["total"]["prs"] == 2
    assert cli.main(["review", "score", "--wave", "0.4.1"]) == 0
    assert "review error score, wave 0.4.1: 1 PR(s) reviewed, 4 confirmed" in capsys.readouterr().out


def test_an_older_stamp_without_rows_or_place_still_counts(brain_home):
    f = review.stamp_file("f" * 40)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"v": 1, "head": "f" * 40, "at": "2026-11-03T10:00:00+00:00", "findings": 11,
                             "fixed": 11, "contested": 0, "open": 0, "note": "11 kept"}), encoding="utf-8")
    (f.parent / "broken.json").write_text("{", encoding="utf-8")
    sc = review.score()
    assert sc["total"]["prs"] == 1 and sc["total"]["findings"] == 11 and sc["unplaced"] == 1 and sc["waves"] == []


def test_the_health_tab_shows_the_review_error_score(brain_home):
    """wi-brain-review-error-score: the totals, the last waves and the rule's verdict, read from the stamps."""
    from brain import cockpit
    assert cockpit.review_summary()["total"]["prs"] == 0
    assert not any("review error score" in x for x in cockpit.health_lines({"projects": [],
                                                                           "reviews": cockpit.review_summary()}))
    for i, (wave, n) in enumerate((("0.4.0", 9), ("0.4.1", 6), ("0.4.2", 3))):
        review.stamp(str(i) * 40, n, n, wave=wave, pr=str(i))
    lines = cockpit.health_lines({"projects": [], "reviews": cockpit.review_summary()}, width=200)
    assert ("  review error score: 6.0 confirmed finding(s) per PR over 3 PR(s); per wave 0.4.0 9.0, 0.4.1 6.0, "
            "0.4.2 3.0; the reviews may lighten") in lines


def test_the_grammar_after_the_review_prose_stays_prose_and_values_are_one_vocabulary():
    """The review of wi-brain-review-error-score: a lone severity, a nested bullet, a value off the vocabulary are
    prose; a family in lower case and a lens as key=value read as the bare words do."""
    note = ("- Low: a tradeoff, not a finding\n  - medium docs: a nested bullet\n- low when=soon: off the vocabulary\n"
            "- high correctness a.b fixed: lower case\n- medium lens=install: as a key\n")
    rows = review.parse_note(note)
    assert [(r["severity"], r["lens"], r["cause"]) for r in rows] == [("high", "correctness", "A.b"),
                                                                     ("medium", "install and upgrade", "")]


def test_a_stamp_no_engine_wrote_is_read_with_defaults_or_left_out(brain_home):
    folder = review.stamp_file("a" * 40).parent
    folder.mkdir(parents=True, exist_ok=True)
    recs = {"a": {"head": "a" * 40, "findings": 1, "rows": [{"severity": "low"}], "wave": 5},
            "b": {"head": "b" * 40, "findings": 2, "rows": "x", "open": None, "pr": 9},
            "c": {"head": "c" * 40, "findings": "two"}, "d": ["not", "a", "stamp"]}
    for k, rec in recs.items():
        (folder / f"{k}.json").write_text(json.dumps(rec), encoding="utf-8")
    sc = review.score()
    assert sc["total"]["prs"] == 2 and sc["total"]["findings"] == 3 and sc["total"]["severity"] == {"low": 1}
    assert [w["wave"] for w in sc["waves"]] == ["5"]
    from brain import cockpit
    assert cockpit.review_summary()["total"]["prs"] == 2


def test_a_pr_stamped_with_and_without_its_number_counts_once_and_two_repos_stay_apart():
    recs = [_rec("a" * 40, 5, at="2026-11-01T10:00:00+00:00"), dict(_rec("a" * 40, 5, pr="7"), repo_slug="o/one"),
            dict(_rec("b" * 40, 3, pr="7"), repo_slug="o/two")]
    assert sorted(r["findings"] for r in review.per_pr(recs)) == [3, 5]
    recs = [dict(_rec("c" * 40, 1), item="wi-x"), dict(_rec("d" * 40, 2), item="wi-x")]   # two PRs of one item
    assert review.score(recs)["total"]["findings"] == 3


def test_a_clean_wave_after_a_clean_one_is_no_rise_and_a_waves_id_names_it_too():
    trend = [{"wave": w, "per_pr": p} for w, p in (("0.1.0", 2), ("0.2.0", 0), ("0.3.0", 0))]
    assert review.lighten(trend)["ok"]
    sc = review.score([_rec("e" * 40, 2, "wave-3", "1")])
    assert "review error score, wave 3: 1 PR(s) reviewed" in "\n".join(review.score_lines(sc, "3"))


def test_stamp_names_the_repo_by_its_folder_without_a_github_remote(pr, brain_home, capsys):
    repo, base, head = pr
    assert cli.main(["review", "stamp", head, "--findings", "0", "--fixed", "0", "--pr", "3", "--item", "wi-x",
                     "--repo", str(repo)]) == 0
    assert review.check(head)["repo_slug"] == repo.name and "pr" in review.check(head)
    assert cli.main(["review", "stamp", base, "--findings", "0", "--fixed", "0", "--item", "wi-x",
                     "--repo", str(repo)]) == 0
    assert "--item without --pr" in capsys.readouterr().err


def test_the_packet_carries_the_failure_modes_of_the_diff_and_of_the_item(pr, brain_home, make_repo):
    """wi-brain-brief-failure-modes: without --item, the diff's files and a removed test; with modes (brain review
    prep --item: brain.brief.failure_modes), the item's section is the packet's; an unregistered repo refuses --item."""
    repo, base, head = pr
    p = review.prep(repo, f"{base}..{head}", scout=False)
    assert p.failure_modes[0].startswith("- **a guard or a gate** (src/brain/guards.py): every sibling path")
    readme = (review.folder_for(head) / "README.md").read_text(encoding="utf-8")
    assert "## Invariants and failure modes to test\n" in readme
    assert readme.index("## Invariants and failure modes") < readme.index("## Files (")
    gone = make_repo.commit(repo, {"tests/test_guards.py": None})
    p = review.prep(repo, f"{head}..{gone}", scout=False, public=True)   # the test removed
    assert [x.split("**")[1] for x in p.failure_modes] == ["a test removed or a check moved", "the public engine"]
    seen = {}

    def modes(files, changed):
        seen.update(files=files, changed=changed)
        return ["- **the item's own** (props.invariants): x"]

    p = review.prep(repo, f"{base}..{head}", scout=False, item="wi-x", modes=modes)
    assert p.failure_modes == ["- **the item's own** (props.invariants): x"] and "src/brain/guards.py" in seen["files"]
    assert "+x = 2" in seen["changed"]
    assert "## Invariants and failure modes to test (wi-x)" in (review.folder_for(head) / "README.md").read_text(
        encoding="utf-8")


def test_prep_item_through_the_cli_hands_the_items_section_and_the_repos_public_line(pr, brain_home, monkeypatch,
                                                                                      capsys):
    """brain review prep --item: the item found in the repo's project, brain.brief.failure_modes given the diff's files
    and changed lines and whether the reviewed repo is public; an unknown item (or an unreadable store) exits 1."""
    from types import SimpleNamespace

    from brain import brief, public, standards
    repo, base, head = pr
    monkeypatch.setattr(standards, "project_of_repo", lambda r: SimpleNamespace(root=repo, name="demo"))
    monkeypatch.setattr(standards, "lenses", lambda p: [])
    monkeypatch.setattr(public, "is_public", lambda slug, cfg: True)
    got = {}

    def find(proj, nid):
        if nid != "wi-x":
            raise brief.BriefError(f"{nid}: no such node in demo's stores")
        return "st", {"id": nid}, None

    def modes(proj, st, node, cfg, files, changed, public=False):
        got.update(node=node["id"], files=files, public=public)
        return ["- **the item's own** (props.invariants): x"]

    monkeypatch.setattr(brief, "_find", find)
    monkeypatch.setattr(brief, "failure_modes", modes)
    assert cli.main(["review", "prep", f"{base}..{head}", "--item", "wi-x", "--repo", str(repo), "--no-scout"]) == 0
    assert got["node"] == "wi-x" and got["public"] is True and "src/brain/guards.py" in got["files"]
    readme = (review.folder_for(head) / "README.md").read_text(encoding="utf-8")
    assert "## Invariants and failure modes to test (wi-x)" in readme and "props.invariants): x" in readme
    assert cli.main(["review", "prep", f"{base}..{head}", "--item", "wi-nope", "--repo", str(repo), "--no-scout"]) == 1
    assert "--item wi-nope: wi-nope: no such node" in capsys.readouterr().err


def test_prep_item_in_a_repo_of_no_project_is_refused(pr, brain_home, monkeypatch, capsys):
    from brain import standards
    repo, base, head = pr
    monkeypatch.setattr(standards, "project_of_repo", lambda r: None)
    assert cli.main(["review", "prep", f"{base}..{head}", "--item", "wi-x", "--repo", str(repo), "--no-scout"]) == 1
    assert "--item wi-x: this repo belongs to no registered project" in capsys.readouterr().err


def test_the_score_counts_a_stamp_in_its_wave_s_release_now():
    """wi-brain-wave-ids-decoupled: wave-s3 was stamped as 1.0.2, then wave 1.0.1 shipped as 1.1.0 and wave-s3 is
    1.1.1 now; a stamp without a wave_id keeps its label."""
    recs = [{"head": "a" * 40, "findings": 2, "fixed": 2, "pr": "1", "wave": "1.0.2", "wave_id": "wave-s3"},
            {"head": "b" * 40, "findings": 1, "fixed": 1, "pr": "2", "wave": "1.0.2"}]
    assert [w["wave"] for w in review.score(recs)["waves"]] == ["1.0.2"]
    got = {w["wave"]: w["prs"] for w in review.score(recs, labels={"wave-s3": "1.1.1"})["waves"]}
    assert got == {"1.0.2": 1, "1.1.1": 1}
