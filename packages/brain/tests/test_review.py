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
