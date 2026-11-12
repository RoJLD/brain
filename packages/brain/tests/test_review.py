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
