"""Finished sessions archive themselves (wi-brain-archive-after-merge, the ADRs of 2026-11-03 and 2026-11-04 on
archiving finished sessions): the token-free check that the close-item procedure, the brief and the generic rules
template all say it, so that an edit dropping a clause fails the suite instead of leaving a session open after its
merge."""

from pathlib import Path

from brain import brief


def _flat(text: str) -> str:
    return " ".join(text.split())


def _step5() -> str:
    text = (Path(brief.__file__).parent / "procedures" / "close-item" / "SKILL.md").read_text(encoding="utf-8")
    return _flat(text.split("## 5.", 1)[1].split("## 6.", 1)[0])


def test_close_item_step_5_says_the_merging_session_archives_itself():
    step = _step5()
    assert "The session that merges its own PR archives itself" in step
    for after in ("main checkout pulled", "journal note written", "report given"):
        assert after in step
    assert "The archive is its last act, after the report." in step
    assert "standing authorization stands for their yes" in step and "nobody asks it again" in step


def test_close_item_step_5_says_the_coordinator_archives_its_children_without_asking():
    step = _step5()
    assert "A coordinator archives its children" in step
    assert "merged and verified" in step and "without asking the owner again" in step


def test_close_item_step_5_never_archives_live_or_unfinished_work():
    step = _step5()
    assert "**Never** a session that is running (mid-turn), one with uncommitted changes, or one with unmerged or " \
           "unverified work" in step


def test_close_item_step_5_names_the_owners_seven_day_net():
    step = _step5()
    assert "`auto_archive_inactive_days = 7`" in step
    assert "The owner sets it; no session changes the app's settings." in step


def test_close_item_report_ends_before_the_self_archive():
    text = (Path(brief.__file__).parent / "procedures" / "close-item" / "SKILL.md").read_text(encoding="utf-8")
    report = _flat(text.split("## Report", 1)[1])
    assert "it archives itself (step 5): the report is its last message" in report


def test_the_brief_carries_the_same_clauses():
    text = _flat(" ".join(brief.AFTER_MERGE))
    assert "You merge your own PR" in text and "archive this session (close-item step 5)" in text
    assert "standing authorization stands for their yes" in text and "The archive is your last act." in text
    assert "archives you as soon as your report says merged and verified, without asking again" in text
    assert "a running session, one with uncommitted changes, or one with unmerged or unverified work" in text
    assert "`auto_archive_inactive_days = 7`" in text and "no session changes the app's settings" in text


def test_the_generic_rules_template_counts_the_archive_in_done():
    text = (Path(brief.__file__).parent / "templates" / "generic" / "rules.md").read_text(encoding="utf-8")
    done = _flat("\n".join(brief.section(text, "Definition of done")))
    assert "its session archived (the close-item procedure, step 5)" in done
    assert "the session that merges its own PR archives itself" in done
    assert "a coordinator archives a child whose report says merged and verified" in done
    assert "never a running session or one with uncommitted or unmerged work" in done
