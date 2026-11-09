"""Decisions by default, then reviewed (wi-brain-decision-default): the low-stakes mark, refused on the topics a
default never decides; final 24 h later without an answer; the review list; reversible with --again."""

import json

import pytest
import yaml

from brain import batch, cli, decisions, defaults, graph, midsession, projects, records

AT = "2026-11-01T09:00:00Z"
BEFORE = "2026-11-02T08:59:59Z"
AFTER = "2026-11-02T09:00:00Z"


def _root(store):
    return store.parents[1]


def _ask(root, title, question="Which one?", options=("Short: fewer words", "Long: more words"), **kw):
    return decisions.ask(root, title=title, question=question, options=list(options), why="clearer", at=AT,
                         project="demo", **kw)[0]


@pytest.fixture
def registry(tmp_path, monkeypatch, store):
    root = _root(store)
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)
    return root


def test_ask_low_stakes_marks_the_recommendation_and_its_deadline(store):
    ddr = _ask(_root(store), "Label wording", low_stakes=True)
    assert ddr["default"] == {"option": "Short", "after": "2026-11-02T09:00:00Z"}
    assert ddr["status"] == "pending" and records.check(_root(store)) == ([], [])


@pytest.mark.parametrize("title, question, topic", [
    ("Pilot price", "Which price for the pilot?", "money"),
    ("Rotate", "Rotate the API key now?", "keys"),
    ("Vault", "Create the recovery key?", "keys"),
    ("Repo", "Make the repo public?", "visibility"),
    ("Release", "Publish the release notes?", "publication"),
    ("Tag", "Push the tag v1.2?", "publication"),
    ("Sign-up", "Create an account for the tester?", "accounts"),
    ("Canary", "Arm the boot of the node?", "arming"),
    ("Lint", "A new rule for the backlog?", "rules"),
    ("Cron", "Add a scheduled task for the alerts?", "scheduled tasks"),
    ("Prix", "Quel tarif pour le pilote ?", "money"),
    ("Clé", "Créer la clé de récupération ?", "keys"),
    ("Dépôt", "Rendre le dépôt public ?", "visibility"),
    ("Tâche", "Créer une tâche planifiée ?", "scheduled tasks"),
])
def test_the_mark_is_refused_on_what_a_default_never_decides(store, title, question, topic):
    root = _root(store)
    with pytest.raises(decisions.QueueError, match=f"--low-stakes refused: a decision on {topic}"):
        _ask(root, title, question, low_stakes=True)
    assert not (root / "records" / "ddr").is_dir() or not list((root / "records" / "ddr").iterdir())
    _ask(root, title, question)  # without the mark: the owner's, as always


def test_brain_check_refuses_a_hand_written_mark(store):
    root = _root(store)
    ddr = _ask(root, "Domain", "Spend twenty euros on a domain?")
    ddr["default"] = {"option": "Short", "after": AFTER}
    records.write(root, "ddr", ddr, replace=True)
    errors, _ = records.check(root)
    assert any("low-stakes mark refused: a decision on money ('Spend')" in e for e in errors)
    ddr = _ask(root, "Wording", "Which wording?")
    ddr["default"] = {"option": "Long", "after": AFTER}
    records.write(root, "ddr", ddr, replace=True)
    assert any("default.option 'Long' is not the recommendation" in e for e in records.check(root)[0])


def test_final_by_default_24_hours_later_then_reviewed_and_reversible(registry, capsys):
    root = registry
    _ask(root, "Label wording", low_stakes=True)
    _ask(root, "Answered early", low_stakes=True)
    decisions.answer(root, "answered-early", ["Long"], at=BEFORE, by="Ada")
    assert defaults.finalize(root, BEFORE) == []
    assert defaults.review(root, BEFORE)["provisional"][0]["hours_left"] == 0
    assert defaults.finalize(root, AFTER) == ["ddr-2026-11-01-label-wording"]
    ddr = decisions.find(root, "label-wording")[1]
    assert ddr["status"] == "answered"
    assert ddr["answer"] == {"at": AFTER, "by": "default", "choices": ["Short"], "via": "default"}
    assert records.check(root) == ([], [])
    assert defaults.finalize(root, "2026-11-09T00:00:00Z") == []  # once
    assert decisions.find(root, "answered-early")[1]["answer"]["choices"] == ["Long"]  # the owner's answer stays

    base = ["--project", "demo", "decision"]
    assert cli.main(base + ["defaulted", "--at", AFTER]) == 0
    out = capsys.readouterr().out
    assert "demo: 1 decision(s) taken by default to review, 0 provisional, 0 reversed; reverse one: brain decision " \
           "answer ID <option> --again" in out
    assert "  ddr-2026-11-01-label-wording: Label wording -> Short (final 2026-11-02T09:00:00Z)" in out
    text = decisions.announce(root)   # the SessionStart hook announces it like any answer not integrated yet
    assert "ddr-2026-11-01-label-wording: Short (by default" in text

    assert cli.main(base + ["defaulted", "--seen", "--at", AFTER]) == 0
    assert "reviewed 1: ddr-2026-11-01-label-wording" in capsys.readouterr().out
    assert decisions.find(root, "label-wording")[1]["default"]["reviewed"] == {"at": AFTER}
    assert cli.main(base + ["defaulted", "--json", "--at", AFTER]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["defaulted"] == [] and data["reviewed"] == 1

    assert cli.main(base + ["answer", "label-wording", "Long", "--again", "--at", "2026-11-03T10:00:00Z"]) == 0
    capsys.readouterr()
    assert cli.main(base + ["defaulted", "--at", "2026-11-03T10:00:00Z"]) == 0
    assert "reversed ddr-2026-11-01-label-wording: Label wording: Short -> Long" in capsys.readouterr().out


def test_apply_and_seen_from_the_cli(registry, monkeypatch, capsys):
    root = registry
    _ask(root, "Label wording", low_stakes=True)
    base = ["--project", "demo", "decision", "defaulted"]
    assert cli.main(base + ["--at", BEFORE]) == 0
    assert "provisional ddr-2026-11-01-label-wording: Label wording -> Short (final in 0 h, unless answered)" in \
        capsys.readouterr().out
    assert cli.main(base + ["--apply", "--at", AFTER]) == 0
    assert "demo: ddr-2026-11-01-label-wording taken by default" in capsys.readouterr().out
    view = (root / "notes" / "decision_queue.md").read_text(encoding="utf-8")
    assert "## Answered, to integrate (1)" in view
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(base + ["--seen", "--at", AFTER]) == 1  # the owner's own note: not from an agent's session
    assert "not an agent's session" in capsys.readouterr().err


def test_the_morning_batch_and_the_hooks_name_the_defaults(registry, tmp_path):
    root = registry
    _ask(root, "Label wording", low_stakes=True)
    _ask(root, "Other wording", low_stakes=True)
    defaults.finalize(root, AFTER)   # both final
    _ask(root, "Third wording", low_stakes=True)
    for d in (root / "records" / "ddr").glob("*third*"):   # still provisional
        assert yaml.safe_load(d.read_text(encoding="utf-8"))["status"] == "pending"
    data = batch.build(projects.Project(name="demo", root=root))
    assert data["defaulted"] == "Taken by default, to review: 2 (1 provisional) — brain decision defaulted"
    zen = "\n".join(batch.zen(data))
    assert "  Taken by default, to review: 2 (1 provisional) — brain decision defaulted" in zen
    queue = root / "records" / "ddr"
    top = midsession._read(queue / "ddr-2026-11-01-label-wording.yaml")
    assert top["via"] == "default"
    assert "(by default: brain decision defaulted)" in midsession.render(queue, [top], [])


def test_topics_are_words_not_parts_of_words():
    assert defaults.topics({"title": "Monkey keyboard harmless", "question": "Keystroke or tagline?"}) == []
    assert defaults.topics({"title": "x", "question": "y", "options": [{"label": "Rotate the password"}]}) == [
        ("keys", "password")]


def test_the_cockpit_line_sums_the_projects(store, tmp_path):
    root = _root(store)
    _ask(root, "Label wording", low_stakes=True)
    defaults.finalize(root, AFTER)
    _ask(root, "Other wording", low_stakes=True)
    line = defaults.total_line([root, tmp_path / "no-records"], AFTER)
    assert line == "Taken by default, to review: 1 (1 provisional) — brain decision defaulted"
    assert defaults.total_line([tmp_path], AFTER) == ""
    from brain import cockpit
    text = cockpit.queue_lines({"projects": [], "defaulted": line, "denials_read": True})
    assert text[1] == f"  {line}"


# --- review of #19: the never-by-default check, naive stamps, the reversed list, --seen ---

@pytest.mark.parametrize("text,topic", [
    ("Spend $50 a month on the GPU host?", "money"), ("Bigger: +40€/month", "money"), ("€50 or nothing", "money"),
    ("Coût : 30€ par mois", "money"), ("What does it cost?", "money"), ("Rotate the HF_TOKEN?", "keys"),
    ("Where does API_KEY live?", "keys"), ("A new ssh-key for the runner", "keys"), ("A cron-job at night", "scheduled tasks"),
    ("A systemd-timer", "scheduled tasks"), ("Use the Task Scheduler", "scheduled tasks"), ("Re-arm the host", "arming"),
    ("A sign-in page", "accounts"), ("A pre-release", "publication"), ("Edit settings.json", "rules")])
def test_7_amounts_compounds_and_synonyms_are_refused(text, topic):
    assert topic in {t for t, _ in defaults.topics({"title": "x", "question": text})}


def test_7_everyday_words_stay_low_stakes():
    for text in ("The context tokens of a session", "Log format: JSON lines", "Which layout for the kanban?"):
        assert defaults.topics({"title": "x", "question": text}) == []


def test_29_the_recommendation_why_and_the_linked_ids_are_read(store):
    ddr = {"title": "Nightly host", "question": "Which host for the nightly runs?",
           "options": [{"label": "Big host"}, {"label": "Small host"}],
           "recommendation": {"option": "Big host", "why": "halves the runtime"}, "links": {"items": ["wi-nightly-billing"]}}
    assert defaults.topics(ddr) == [("money", "billing")]
    ddr["links"] = {}
    ddr["recommendation"]["why"] = "it needs a new GitHub account for the runner"
    assert defaults.topics(ddr) == [("accounts", "account")]
    with pytest.raises(decisions.QueueError, match="never decided by default"):
        decisions.ask(_root(store), title="Nightly host", question="Which host?", options=["Big", "Small"],
                      why="it costs 30 euros more", at=AT, project="demo", low_stakes=True)


def test_30_a_stamp_without_a_zone_is_utc_not_a_crash(store):
    root = _root(store)
    ddr = _ask(root, "Label wording", low_stakes=True)
    ddr["default"]["after"] = "2026-11-02T09:00:00"   # a hand edit, no Z
    records.write(root, "ddr", ddr, replace=True)
    assert defaults.review(root, "2026-11-02T08:00")["provisional"][0]["hours_left"] == 1
    assert defaults.finalize(root, AFTER) == ["ddr-2026-11-01-label-wording"]


def test_31_an_answer_that_took_the_default_option_is_not_reversed_and_seen_clears_one(store):
    root = _root(store)
    _ask(root, "Log format", low_stakes=True)
    decisions.answer(root, "log-format", ["Short"], at="2026-11-03T09:00:00Z", by="Ada")   # late, the same option
    assert defaults.review(root, "2026-11-03T10:00:00Z")["reversed"] == []
    _ask(root, "Label wording", low_stakes=True)
    defaults.finalize(root, AFTER)
    decisions.answer(root, "label-wording", ["Long"], at="2026-11-03T10:00:00+01:00", by="Ada", again=True)
    assert [e["id"] for e in defaults.review(root, "2026-11-03T12:00:00Z")["reversed"]] == \
        ["ddr-2026-11-01-label-wording"]
    assert defaults.seen(root, ["label-wording"], at="2026-11-03T12:00:00Z") == ["ddr-2026-11-01-label-wording"]
    assert defaults.review(root, "2026-11-03T12:00:00Z")["reversed"] == []   # reviewed since that answer


def test_33_seen_checks_every_id_before_writing(store):
    root = _root(store)
    _ask(root, "Label wording", low_stakes=True)
    _ask(root, "Plain wording")
    defaults.finalize(root, AFTER)
    with pytest.raises(decisions.QueueError, match="plain-wording: not decided by default"):
        defaults.seen(root, ["label-wording", "plain-wording"], at=AFTER)
    assert "reviewed" not in decisions.find(root, "label-wording")[1]["default"]   # nothing half-written


# --- the PR's own review (2 lenses, 2 skeptics each) ---

@pytest.mark.parametrize("text,topic", [("Rotate the keys", "keys"), ("A new github PAT", "keys"),
                                        ("Read the .env file", "keys")])
def test_review_more_key_forms_are_refused(text, topic):
    assert topic in {t for t, _ in defaults.topics({"title": "x", "question": text})}


def test_review_code_words_stay_low_stakes():
    for text in ("Raise max_tokens", "A primary_key column", "Restart the hook", "Run npm test"):
        assert defaults.topics({"title": "x", "question": text}) == []


def test_review_a_word_learned_later_never_fails_an_answered_decision(store):
    root = _root(store)
    ddr = _ask(root, "Label wording", low_stakes=True)
    defaults.finalize(root, AFTER)
    ddr = decisions.find(root, "label-wording")[1]
    ddr["question"] = "Which one, at what cost?"   # a word the check learned after the default was taken
    records.write(root, "ddr", ddr, replace=True)
    assert records.check(root) == ([], [])
    ddr["status"], ddr["answer"] = "pending", None
    ddr.pop("answer")
    records.write(root, "ddr", ddr, replace=True)
    assert any("low-stakes mark refused" in e for e in records.check(root)[0])   # a pending one is refused


def test_review_a_captured_answer_shows_in_the_review_not_due(store):
    from brain import answers
    root = _root(store)
    ddr = _ask(root, "Label wording", low_stakes=True)
    answers._append(answers.CAPTURED, [{"v": 1, "id": "ans-1", "at": BEFORE, "ddr": ddr["id"], "project": "demo",
                                        "answer": "Long", "choices": ["Long"]}])
    (e,) = defaults.review(root, AFTER)["provisional"]
    assert e["due"] is False and e["captured"] == BEFORE
    assert "answered in time through the question tool" in "\n".join(defaults.render("demo", defaults.review(root, AFTER)))


def test_review_seen_twice_on_a_reversed_default_is_a_no_op(store):
    root = _root(store)
    _ask(root, "Label wording", low_stakes=True)
    defaults.finalize(root, AFTER)
    decisions.answer(root, "label-wording", ["Long"], at="2026-11-03T10:00:00Z", by="Ada", again=True)
    assert defaults.seen(root, ["label-wording"], at="2026-11-03T12:00:00Z")
    assert defaults.seen(root, ["label-wording"], at="2026-11-03T13:00:00Z") == ["ddr-2026-11-01-label-wording"]


# --- review of #19, the findings left for after the command registry ---

def test_32_apply_and_seen_never_write_a_main_checkout_unless_on_main(registry, monkeypatch, capsys):
    """A main checkout on main is check-only for brain refresh: defaulted --apply and --seen wrote its records and
    queue view in place, and a later pull there aborted over them."""
    import shutil

    from conftest import GIT_ENV, git_init, run_git
    if not shutil.which("git"):
        pytest.skip("git not available")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    root = registry
    _ask(root, "Label wording", low_stakes=True)
    git_init(root)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-qm", "init")
    base = ["--project", "demo", "decision", "defaulted", "--at", AFTER]
    for argv in (base + ["--apply"], ["decision", "defaulted", "--all", "--apply", "--at", AFTER], base + ["--seen"]):
        assert cli.main(argv) == 0
        assert "demo: main checkout on main: not written (run it from a worktree, or --on-main)" in \
            capsys.readouterr().out
        assert run_git(root, "status", "--porcelain") == ""   # nothing changed in place
    assert decisions.find(root, "label-wording")[1]["status"] == "pending"
    assert cli.main(base + ["--apply", "--on-main"]) == 0
    assert "demo: ddr-2026-11-01-label-wording taken by default" in capsys.readouterr().out
    assert cli.main(base + ["--seen", "--on-main"]) == 0
    assert decisions.find(root, "label-wording")[1]["default"]["reviewed"] == {"at": AFTER}


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Two registered projects, alpha then beta, each with its own DDRs."""
    roots = {}
    for name in ("alpha", "beta"):
        roots[name] = tmp_path / name
        (roots[name] / "records" / "ddr").mkdir(parents=True)
        (roots[name] / "notes").mkdir()
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir()
    reg.write_text("".join(f"{n}: {{root: {r.as_posix()}}}\n" for n, r in roots.items()), encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setattr(graph, "research_graph_json", lambda *a: None)
    return roots


def test_33_all_seen_marks_each_full_id_in_the_project_that_holds_it(two, capsys):
    alpha, beta = two["alpha"], two["beta"]
    _ask(alpha, "Label wording extra", low_stakes=True)   # its id contains beta's
    _ask(alpha, "Plain wording")
    _ask(beta, "Label wording", low_stakes=True)
    for root in (alpha, beta):
        defaults.finalize(root, AFTER)
    base = ["decision", "defaulted", "--all", "--at", AFTER, "--seen"]
    assert cli.main(base + ["label-wording"]) == 1   # a part of an id: it would name a different DDR in each
    assert "label-wording: no project written here holds a DDR of that id" in capsys.readouterr().err
    assert cli.main(base + ["ddr-2026-11-01-label-wording", "ddr-2026-11-01-plain-wording"]) == 1
    assert "plain-wording: not decided by default" in capsys.readouterr().err
    for root in (alpha, beta):   # nothing marked in any project
        assert all("reviewed" not in d["default"] for _, d in decisions.load(root) if d.get("default"))
    assert cli.main(base + ["ddr-2026-11-01-label-wording"]) == 0   # beta's, although alpha comes first
    out = capsys.readouterr().out
    assert "beta: reviewed 1: ddr-2026-11-01-label-wording" in out and "alpha: reviewed" not in out
    assert decisions.find(beta, "ddr-2026-11-01-label-wording")[1]["default"]["reviewed"] == {"at": AFTER}
    assert "reviewed" not in decisions.find(alpha, "label-wording-extra")[1]["default"]
    assert (alpha / "notes" / "decision_queue.md").is_file() and (beta / "notes" / "decision_queue.md").is_file()


def test_35_the_refresh_that_takes_a_default_writes_the_records_graph_after_it(registry, monkeypatch, capsys):
    root = registry
    ddr = _ask(root, "Label wording", low_stakes=True)   # asked 2026-11-01: its deadline has passed
    monkeypatch.setattr(graph, "research_graph", lambda *a: 0)
    assert cli.main(["--project", "demo", "sync", "--offline"]) == 0
    assert f"{ddr['id']}: taken by default" in capsys.readouterr().out
    nodes = yaml.safe_load((root / "notes" / "graph" / "nodes" / "_generated_records.yaml").read_text(encoding="utf-8"))
    node = next(n for n in nodes if n["id"] == ddr["id"])
    assert node["status"] == "answered"   # not the pending of the state before the default
