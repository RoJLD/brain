"""brain.overlap: a rule, a procedure or a memory note restated in another, by entity-neutral 8-word shingles, a
warning of brain check and a note of the review's procedure lens (wi-brain-rule-overlap). Invented texts only."""

import json

import pytest

from brain import cli, config, overlap, review

RELEASE = ("Before a release the owner runs the whole suite on a clean checkout, then writes the changelog from the "
           "fragments, then tags the merge commit and pushes the tag; nobody tags a branch that is not merged.")
OTHER = ("A session that waits on a background job gives it a deadline and an exit when its file is gone, and it "
         "stops the job before it deletes the logs the job writes, so nothing is left running behind it.")
THIRD = ("Plots use the shared palette of the lab: one hue per series, grey for the context, and the same colour for "
         "the same series in every figure of a report, so a reader never has to learn the legend twice.")

RULES = f"""---
scope: global
title: Lab rules
---

## Releases
<!-- id: rule-release -->

{RELEASE}

## Waiting
<!-- id: rule-wait -->

{OTHER}
"""


def note(body: str, name: str = "a-note") -> str:
    return f"---\nname: {name}\ndescription: one line\nmetadata:\n  type: feedback\n---\n\n{body}\n"


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """An invented brain: Ada's, with the projects lab and acme, a neutral source and a memory folder."""
    root = tmp_path / "ada-brain"
    files = {
        "config.json": json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"}}),
        "projects.yaml": "lab:\n  root: .\nacme:\n  root: ../acme\n",
        "source/packs.yaml": "packs: {}\n",
        "source/rules/global.md": RULES,
        "source/procedures/plots/SKILL.md": f"---\nname: plots\ndescription: plots\n---\n\n## 1. Colours\n\n{THIRD}\n",
        "memory/lab/MEMORY.md": f"- [Release](release.md): {RELEASE}\n",
    }
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")
    (tmp_path / "acme").mkdir()
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.delenv("CLAUDE_BRAIN_DIR", raising=False)
    return root


def put(root, rel: str, text: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8", newline="\n")


# --- the neutral words ------------------------------------------------------------------------------------------------

def test_ids_dates_numbers_and_entity_names_are_dropped_and_compounds_split():
    text = ("---\nname: x\n---\nSee wi-lab-release-steps on 2026-01-02 (PR #42, v0.3.1) for Acme's zero-token "
            "check <!-- id: rule-x --> at https://example.org/a-b-c and read_only mode.")
    assert overlap.words(text, {"acme"}) == ["see", "on", "pr", "for", "s", "zero", "token", "check", "at", "and",
                                             "read", "only", "mode"]


def test_a_copy_that_swaps_its_ids_dates_and_names_still_scores_whole():
    a = "Ada tags wi-lab-release-one on 2026-01-02 after PR #12: " + RELEASE
    b = "Bob tags wi-acme-release-two on 2027-05-06 after PR #99: " + RELEASE
    neutral = {"ada", "bob"}
    ua, ub = overlap.units("a.md", a, neutral)[0], overlap.units("b.md", b, neutral)[0]
    pair = overlap.pairs([ua, ub])[0]
    assert pair.containment == 100.0 and pair.jaccard == 100.0
    assert overlap.pairs([ua, overlap.units("c.md", OTHER)[0]]) == []   # nothing shared: no pair at all


def test_crlf_and_lf_read_alike():
    lf = RULES
    crlf = RULES.replace("\n", "\r\n")
    assert [(u.line, u.title, u.shingles) for u in overlap.units("r.md", lf)] == \
           [(u.line, u.title, u.shingles) for u in overlap.units("r.md", crlf)]


# --- the units --------------------------------------------------------------------------------------------------------

def test_a_file_is_cut_at_its_level_two_headings_with_their_lines():
    us = overlap.units("source/rules/global.md", "Intro words " * 10 + "\n" + RULES.split("---\n", 2)[2])
    assert [(u.line, u.title) for u in us] == [(1, ""), (3, "Releases"), (8, "Waiting")]
    assert us[1].name == "source/rules/global.md:3 (Releases)" and us[0].name == "source/rules/global.md:1"
    fm = overlap.units("n.md", note(RELEASE))
    assert [(u.line, u.title) for u in fm] == [(1, "")]   # the front matter is no text, the lines still count
    assert overlap.units("e.md", "## Empty\n\nshort\n") == []   # under 8 words: no shingle, no unit


def test_containment_sees_a_note_inside_a_longer_rule_that_jaccard_dilutes():
    long_rule = overlap.units("r.md", " ".join([OTHER, RELEASE, THIRD, OTHER.upper()]))[0]
    short = overlap.units("n.md", RELEASE)[0]
    pair = overlap.pairs([long_rule, short])[0]
    assert pair.containment == 100.0 and pair.jaccard < 40


def test_a_unit_under_min_shingles_is_not_scored():
    small = overlap.units("s.md", "one two three four five six seven eight nine ten")[0]   # 3 shingles
    copy = overlap.units("t.md", "one two three four five six seven eight nine ten")[0]
    assert overlap.pairs([small, copy]) == []
    assert len(overlap.pairs([small, copy], min_shingles=1)) == 1


# --- the settings and the roots -------------------------------------------------------------------------------------

def test_the_defaults_follow_the_source_and_memory_keys_and_a_bad_value_keeps_its_default(lab):
    cfg = config.load(lab)
    assert overlap.settings(cfg) == {"roots": ["source/rules/**/*.md", "source/procedures/**/*.md", "memory/**/*.md"],
                                     "exclude": ["**/MEMORY.md"], "warn": 20.0, "min_shingles": 10}
    cfg.data.update({"source": "src", "memory": "notes/mem",
                     "overlap": {"roots": ["CLAUDE.md"], "warn": "high", "min_shingles": True, "exclude": [3]}})
    assert overlap.settings(cfg) == {"roots": ["CLAUDE.md"], "exclude": ["**/MEMORY.md"], "warn": 20.0,
                                     "min_shingles": 10}
    cfg.data["overlap"] = {"warn": 35, "min_shingles": 4, "exclude": []}
    s = overlap.settings(cfg)
    assert s["roots"][0] == "src/rules/**/*.md" and (s["warn"], s["min_shingles"], s["exclude"]) == (35.0, 4, [])


def test_the_memory_index_and_a_rendered_copy_are_no_roots(lab):
    put(lab, "plugins/ada-core/rules/global.md", RULES)          # what brain render writes: not a root
    names = [p.relative_to(lab).as_posix() for p in overlap.files(lab, overlap.settings(config.load(lab)))]
    assert names == ["source/procedures/plots/SKILL.md", "source/rules/global.md"]
    assert overlap.findings(lab) == []                           # today's texts: nothing restated


def test_the_brain_s_entity_names_are_neutral(lab):
    names = overlap.entities(config.load(lab))
    assert {"ada", "lab", "acme"} <= names


# --- brain check and the review ---------------------------------------------------------------------------------------

def test_a_note_restating_a_rule_is_one_warning_line(lab):
    put(lab, "memory/lab/release.md", note("Acme learned it the hard way on 2026-03-04: " + RELEASE))
    found = overlap.findings(lab)
    assert len(found) == 1
    p = found[0]
    assert {p.a.name, p.b.name} == {"memory/lab/release.md:1", "source/rules/global.md:6 (Releases)"}
    assert overlap.check_lines(lab) == [
        f"overlap: {p.a.name} and {p.b.name} share 100 % of the smaller one's 8-word shingles (Jaccard "
        f"{p.jaccard:.0f} %): one text says it, the other points to it"]
    put(lab, "config.json", json.dumps({"v": 1, "identity": {"owner": "Ada"}, "overlap": {"exclude": ["memory/**"]}}))
    assert overlap.findings(lab) == []


def test_the_warn_level_is_inclusive_and_read_from_config(lab):
    half = " ".join(RELEASE.split()[:20])   # the rule's first 20 words, then words of its own
    put(lab, "memory/lab/half.md", note(half + " and then the lab keeps a copy of every report it ever sent out"))
    p = overlap.pairs(overlap.corpus(lab))[0]
    level = round(p.containment, 6)
    for warn, n in ((level, 1), (level + 0.01, 0)):
        put(lab, "config.json", json.dumps({"v": 1, "identity": {"owner": "Ada"}, "overlap": {"warn": warn}}))
        assert len(overlap.findings(lab)) == n, warn


def test_an_error_in_the_check_is_one_warning_never_a_failure(lab, monkeypatch):
    monkeypatch.setattr(overlap, "corpus", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    assert overlap.check_lines(lab) == ["overlap: not checked (OSError: disk)"]
    assert overlap.review_notes(lab, ["source/rules/global.md"]) == ["overlap: not checked (OSError: disk)"]


def test_brain_check_prints_the_warning_and_keeps_its_exit_code(lab, monkeypatch, capsys):
    monkeypatch.setattr(cli.graph, "research_graph", lambda *a, **k: 0)
    (lab / "notes" / "graph" / "nodes").mkdir(parents=True)
    put(lab, "notes/graph/schema.yaml", "owner: Ada\nnode_types: [WorkItem]\nedge_types: []\n")
    put(lab, "notes/graph/edges.yaml", "[]\n")
    rc = cli.main(["--root", str(lab), "check"])
    assert "overlap:" not in capsys.readouterr().out
    put(lab, "memory/lab/release.md", note(RELEASE))
    assert cli.main(["--root", str(lab), "check"]) == rc
    out = capsys.readouterr().out
    assert "warning: overlap: memory/lab/release.md:1 and source/rules/global.md:6 (Releases) share 100 %" in out


def test_the_procedure_lens_is_given_the_pairs_a_touched_file_takes_part_in(make_repo, brain_home, monkeypatch):
    files = {"config.json": json.dumps({"v": 1, "identity": {"owner": "Ada"}}), "source/rules/global.md": RULES,
             "source/procedures/plots/SKILL.md": f"## 1. Colours\n\n{THIRD}\n"}
    repo = make_repo("ada-brain", files)
    monkeypatch.setenv("BRAIN_CONFIG", str(repo / "config.json"))
    base = make_repo.commit(repo, {"memory/lab/plots.md": note(THIRD)})   # restated before this PR
    head = make_repo.commit(repo, {"memory/lab/release.md": note(RELEASE)})
    p = review.prep(repo, f"{base}..{head}", scout=False)
    assert "procedure" not in p.lenses and not [n for n in p.notes if "overlap" in n]   # a memory note alone
    head = make_repo.commit(repo, {"source/rules/global.md": RULES + "\n## Extra\n\nOne more line.\n"})
    p = review.prep(repo, f"{base}..{head}", scout=False)
    notes = [n for n in p.notes if n.startswith("overlap:")]
    assert "procedure" in p.lenses and len(notes) == 1
    assert "memory/lab/release.md:1 and source/rules/global.md:" in notes[0] and notes[0].endswith("(procedure lens)")
    assert notes[0] in (review.folder_for(head) / "README.md").read_text(encoding="utf-8")


# --- the review's fixes -----------------------------------------------------------------------------------------------

def test_an_exclusion_reads_its_glob_as_the_roots_do(lab):
    put(lab, "memory/archive/old.md", note(RELEASE))
    put(lab, "memory/archive/deep/older.md", note(OTHER))
    cfg = config.load(lab)
    cfg.data["overlap"] = {"exclude": ["memory/archive/**/*.md", "**/MEMORY.md"]}
    names = [overlap.rel_name(p, lab) for p in overlap.files(lab, overlap.settings(cfg))]
    assert names == ["source/procedures/plots/SKILL.md", "source/rules/global.md"]   # the folder's own and deeper
    cfg.data["overlap"] = {"exclude": ["memory/*.md"]}   # '*' stays within one folder, as in a root
    names = [overlap.rel_name(p, lab) for p in overlap.files(lab, overlap.settings(cfg))]
    assert "memory/archive/old.md" in names and "memory/lab/MEMORY.md" in names


def test_an_absolute_memory_folder_is_read_and_named_by_its_path(lab, tmp_path):
    outside = tmp_path / "notes-elsewhere"
    put(outside, "lab/release.md", note(RELEASE))
    put(lab, "config.json", json.dumps({"v": 1, "identity": {"owner": "Ada"}, "memory": outside.as_posix()}))
    found = overlap.findings(lab)
    assert len(found) == 1 and {found[0].a.path, found[0].b.path} == {
        (outside / "lab" / "release.md").resolve().as_posix(), "source/rules/global.md"}


def test_only_a_one_word_entity_name_is_neutral(lab):
    put(lab, "config.json", json.dumps({"v": 1, "public": {"deny": {"paths": ["C:/Users/someone"],
                                                                     "repos": ["ada/core-notes", "Zeta"]}}}))
    names = overlap.entities(config.load(lab))
    assert "zeta" in names and not {"the", "owner", "c", "users", "someone", "ada", "core"} & names


def test_a_bom_is_no_text(lab):
    (lab / "memory" / "lab").mkdir(parents=True, exist_ok=True)
    (lab / "memory" / "lab" / "bom.md").write_bytes(("\ufeff" + note(RELEASE)).encode("utf-8"))
    p = overlap.findings(lab)[0]
    assert "memory/lab/bom.md:1" in (p.a.name, p.b.name) and p.containment == 100.0


def test_brain_check_warns_at_a_root_several_projects_share_and_with_all(lab, monkeypatch, capsys):
    from brain.commands import check
    seen = []
    monkeypatch.setattr(check, "_each_store", lambda *a, **k: seen.append(k.get("scope")) or 0)
    monkeypatch.setattr(check, "_scope", lambda *a, **k: ["lab", "side"])   # two projects at this root
    put(lab, "memory/lab/release.md", note(RELEASE))
    args = cli.build_parser().parse_args(["--root", str(lab), "check"])
    assert check._cmd_check(args, lab) == 0 and seen == [["lab", "side"]]
    args = cli.build_parser().parse_args(["--root", str(lab), "check", "--all"])
    assert check._cmd_check(args, lab) == 0 and seen[-1] is None
    out = capsys.readouterr().out
    assert out.count("warning: overlap: memory/lab/release.md:1 and source/rules/global.md:6") == 2
