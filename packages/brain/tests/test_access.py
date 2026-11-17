"""Access, the doctrine (brain.access; spec-brain-access ACC-1 to ACC-4, slice 1, read only): groups and grants in
members.yaml, grades on the scope tree inherited by union, capability roles, the reference checks, brain access
explain; a solo brain unchanged; nothing refused. Fictitious names only."""

import json
import shutil
from pathlib import Path

import pytest

from brain import access, cli, config, identity, schema, scopes
from brain.commands import _stores

TREE = """\
v: 1
scopes:
  acme: {type: company, title: ACME SA, aliases: [acme-old]}
  finance: {type: unit, title: Finance, parent: acme}
"""
MEMBERS = """\
v: 1
people:
  - {person_id: carol, name: Carol}
  - {person_id: alice, name: Alice}
  - {person_id: bob, name: Bob}
  - {person_id: dave, name: Dave}
groups:
  - {id: finance-team, title: Finance team, members: [alice, bob]}
  - {id: staff, title: Everyone, members: [finance-team, dave]}
memberships:
  - {person_id: carol, roles: [owner]}
  - {group: staff, scope: acme, grade: viewer}
  - {group: finance-team, scope: finance, grade: maintainer, roles: [decider]}
  - {person_id: dave, scope: ledger, grade: contributor, until: 2027-03-31}
  - {person_id: bob, scope: ledger, grade: owner, since: 2099-01-01}
"""


@pytest.fixture
def brain(tmp_path, monkeypatch, store):
    """A shared brain at tmp_path/root: config.json, a registry (the brain itself, ledger under finance, site under
    acme), scopes.yaml and members.yaml. Returns a writer of members.yaml."""
    root = store.parent.parent
    for name in ("ledger", "site"):
        shutil.copytree(store, tmp_path / name / "notes" / "graph")
    (root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": "carol"}}), encoding="utf-8")
    (root / "projects.yaml").write_text("hub: {root: .}\nledger: {root: ../ledger, parent: finance}\n"
                                        "site: {root: ../site, parent: acme}\n", encoding="utf-8")
    (root / scopes.FILE).write_text(TREE, encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.delenv("BRAIN_SCOPES", raising=False)
    monkeypatch.delenv("BRAIN_STRICT", raising=False)
    monkeypatch.delenv("CI", raising=False)

    def members(text: str = MEMBERS) -> None:
        (root / identity.FILE).write_text(text, encoding="utf-8")

    members.root = root
    return members


def _x(person, node, root, client="", today="2026-12-01"):
    m = identity.load(root)
    return access.explain(m.data, person, scopes.load(root), node, client, today)


# --- the model ---

def test_grades_are_ordered_and_each_includes_the_one_below():
    assert access.GRADES == ("viewer", "contributor", "maintainer", "owner")
    for lower, higher in zip(access.GRADES, access.GRADES[1:]):
        assert set(access.GRADE_VERBS[lower]) < set(access.GRADE_VERBS[higher])
    assert "decide" not in access.GRADE_VERBS["owner"] and access.ROLE_VERBS["decider"] == ("decide",)
    assert set(access.ROLES) == {"decider", "releaser", "auditor"}


def test_the_members_file_with_groups_and_grants_is_valid(brain):
    brain()
    m = identity.load(brain.root)
    assert m.findings == []
    assert access.memberships_of("alice", m.data) == {"finance-team": ["finance-team"],
                                                     "staff": ["finance-team", "staff"]}


def test_a_grant_holds_down_the_tree_by_union_the_highest_grade_winning(brain):
    brain()
    on_ledger = _x("alice", "ledger", brain.root)
    assert on_ledger["chain"] == ["ledger", "finance", "acme", "global"]
    assert on_ledger["grade"] == "maintainer"   # finance's maintainer over acme's viewer
    assert set(on_ledger["verbs"]) == {"read", "propose", "write", "decide"}
    assert any("via group finance-team -> staff" in s for s in on_ledger["verbs"]["read"])   # nested group, said
    assert on_ledger["roles"] == {"decider": ["maintainer on finance, memberships[2], via group finance-team"]}
    on_site = _x("alice", "site", brain.root)
    assert on_site["grade"] == "viewer" and set(on_site["verbs"]) == {"read"} and on_site["roles"] == {}
    assert _x("alice", "global", brain.root)["grade"] == ""   # nothing on the whole brain
    carol = _x("carol", "ledger", brain.root)   # owner on Global, a role named as the grade: everywhere
    assert carol["grade"] == "owner" and "administer" in carol["verbs"] and "decide" not in carol["verbs"]


def test_since_and_until_bound_a_grant(brain):
    brain()
    dave = _x("dave", "ledger", brain.root, today="2026-12-01")
    assert dave["grade"] == "contributor"
    assert _x("dave", "ledger", brain.root, today="2027-04-01")["grade"] == "viewer"   # expired: staff's viewer left
    assert any("until 2027-03-31" in n for n in _x("dave", "ledger", brain.root, today="2027-04-01")["not_counted"])
    bob = _x("bob", "ledger", brain.root)
    assert bob["grade"] == "maintainer" and any("since 2099-01-01" in n for n in bob["not_counted"])


def test_an_agent_reaches_its_persons_verbs_within_its_clients_ceiling(brain):
    brain()
    x = _x("alice", "ledger", brain.root, client="cursor")
    assert x["client"]["verbs"] == ["read", "propose"]   # never write, decide or administer for an agent here
    assert set(x["client"]["never"]) == {"administer", "decide"}
    assert _x("dave", "site", brain.root, client="claude")["client"]["verbs"] == ["read"]   # never above its person


def test_legacy_roles_read_as_grades_never_above(brain):
    brain("v: 1\npeople:\n  - {person_id: ada, name: Ada}\nmemberships:\n  - {person_id: ada, roles: [member]}\n"
          "  - {person_id: ada, project: site, roles: [decider]}\n")
    assert identity.load(brain.root).findings == []
    assert _x("ada", "global", brain.root)["grade"] == "viewer"   # member: viewer, never above
    site = _x("ada", "site", brain.root)
    assert "decide" in site["verbs"] and site["roles"] == {"decider": ["decider on site, memberships[1], direct"]}


def test_an_organization_or_tenant_membership_grants_nothing_here(brain):
    brain("v: 1\npeople:\n  - {person_id: ada, name: Ada}\norganizations:\n  - {id: acme-org, name: Acme, kind: tenant}"
          "\nmemberships:\n  - {person_id: ada, tenant: acme-org, roles: [owner]}\n")
    assert identity.load(brain.root).findings == []
    assert _x("ada", "site", brain.root)["grade"] == ""


# --- the reference checks ---

@pytest.mark.parametrize("extra,needle", [
    ("  - {group: nobody, grade: viewer}\n", "group 'nobody' is not in groups"),
    ("  - {person_id: carol, group: staff, grade: viewer}\n", "names a person_id or a group, exactly one"),
    ("  - {grade: viewer}\n", "names a person_id or a group, exactly one"),
    ("  - {person_id: carol, scope: nowhere, grade: viewer}\n", "scope 'nowhere' is no node of the scope tree"),
    ("  - {person_id: carol, scope: acme-old, grade: viewer}\n",
     "scope 'acme-old' is an alias of acme: a grant names a node by its id"),
    ("  - {person_id: carol, scope: site, project: ledger, grade: viewer}\n", "scope and project name two nodes"),
    ("  - {person_id: carol, scope: site}\n", "grants nothing: give it roles (or a grade)"),
    ("  - {person_id: carol, grade: viewer, since: 2027-01-02, until: 2027-01-01}\n", "until 2027-01-01 is before"),
    ("  - {person_id: zed, grade: viewer}\n", "person_id 'zed' is not in people"),
])
def test_members_reference_checks(brain, extra, needle):
    brain(MEMBERS + extra)
    errors = identity.load(brain.root).findings
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("groups,needle", [
    ("  - {id: a, members: [b]}\n  - {id: b, members: [a]}\n", "groups: a cycle: a -> b -> a"),
    ("  - {id: a, members: [a]}\n", "group 'a' lists itself"),
    ("  - {id: a, members: [ghost]}\n", "member 'ghost' is neither a person_id nor a group"),
    ("  - {id: carol, members: [alice]}\n", "group 'carol' is a person_id too"),
    ("  - {id: a, members: []}\n  - {id: a, members: []}\n", "group 'a' is declared twice"),
])
def test_group_checks(brain, groups, needle):
    brain("v: 1\npeople:\n  - {person_id: carol, name: Carol}\n  - {person_id: alice, name: Alice}\ngroups:\n"
          + groups + "memberships:\n  - {person_id: carol, roles: [owner]}\n")
    errors = identity.load(brain.root).findings
    assert any(needle in e for e in errors), errors


def test_an_unknown_grade_is_a_note_read_as_none_never_above(brain, capsys, monkeypatch):
    brain(MEMBERS + "  - {person_id: carol, scope: site, grade: steward}\n")
    assert identity.load(brain.root).findings == []   # read mode: a newer brain's grade, noted
    assert "grade 'steward' is not one of" in capsys.readouterr().err
    x = _x("carol", "site", brain.root)
    assert x["grade"] == "owner" and x["unknown_grades"] == ["steward (steward on site, memberships[5], direct)"]
    monkeypatch.setenv("BRAIN_STRICT", "1")
    assert any("grade 'steward' is not one of" in e for e in identity.load(brain.root).findings)


def test_the_findings_are_warnings_unless_require_signed(brain):
    """A reference error of the access fields follows every identity finding: a warning by default (nothing new is
    refused), an error under config.json identity.require_signed."""
    brain(MEMBERS + "  - {person_id: carol, scope: nowhere, grade: viewer}\n")
    errors, warnings = identity.check(brain.root)
    assert errors == [] and any("scope 'nowhere'" in w for w in warnings)
    (brain.root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": "carol", "require_signed": True}}),
                                          encoding="utf-8")
    errors, _ = identity.check(brain.root)
    assert any("scope 'nowhere'" in e for e in errors)


def test_a_members_file_of_before_the_grades_reads_as_before(brain):
    """members.yaml as 0.3.1 wrote it (the format's older fixture): no new finding, the decider read as before."""
    older = Path(__file__).parent / "fixtures" / "formats" / "members" / "v1" / "older.yaml"
    brain(older.read_text(encoding="utf-8"))
    m = identity.load(brain.root)
    assert m.findings == []
    assert list(identity.deciders(m.data)) == ["ada"]
    assert _x("ada", "site", brain.root)["grade"] == "owner"


def test_grades_labels_are_renamed_by_config_json(brain, capsys):
    brain()
    (brain.root / config.FILE).write_text(json.dumps({"v": 1, "identity": {"owner": "carol"},
                                                      "grades": {"contributor": {"fr": "Chercheur"},
                                                                 "steward": {"en": "Steward"}}}), encoding="utf-8")
    cfg = config.load(brain.root)
    assert access.labels(cfg.data)["contributor"] == {"en": "Contributor", "fr": "Chercheur"}
    assert config.check(brain.root) == []   # the key is known (an optional key of config.json)
    assert identity.load(brain.root).findings == []   # steward: noted, a brain's own grade is not built
    assert "'steward' is no grade" in capsys.readouterr().err
    assert cli.main(["access", "explain", "dave", "--scope", "ledger", "--lang", "fr"]) == 0
    assert "grade contributor (Chercheur)" in capsys.readouterr().out


# --- brain access explain ---

def test_brain_access_explain_prints_the_grant_behind_each_verb(brain, capsys):
    brain()
    assert cli.main(["access", "explain", "alice", "--scope", "ledger", "--client", "cursor"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("alice on acme/finance/ledger: grade maintainer (Maintainer)")
    assert "groups: finance-team, finance-team -> staff" in out
    assert "write      maintainer on finance, memberships[2], via group finance-team" in out
    assert "role decider: maintainer on finance, memberships[2], via group finance-team" in out
    assert "an agent of cursor for them: read, propose (ceiling read, propose; never administer, decide)" in out
    assert cli.main(["access", "explain", "alice", "--json"]) == 0   # Global, then each node a grant names
    data = json.loads(capsys.readouterr().out)
    assert [n["node"] for n in data["nodes"]] == ["global", "acme", "finance"] and data["solo"] is False
    assert cli.main(["access", "explain", "alice", "--scope", "acme-old"]) == 0   # an alias, with a notice
    got = capsys.readouterr()
    assert "alice on acme: grade viewer" in got.out and "'acme-old' is an alias of 'acme'" in got.err


def test_brain_access_explain_fails_on_an_unknown_person_or_node(brain, capsys):
    brain()
    assert cli.main(["access", "explain", "zed"]) == 1
    assert "'zed' is not in members.yaml people" in capsys.readouterr().err
    assert cli.main(["access", "explain", "alice", "--scope", "nowhere"]) == 1
    assert "no node of that id" in capsys.readouterr().err


def test_a_solo_brain_sees_no_change(brain, capsys):
    """No members.yaml: the owner has every verb, nothing is checked, nothing refused."""
    assert identity.load(brain.root) is None and identity.check(brain.root) == ([], [])
    assert cli.main(["access", "explain", "carol"]) == 0
    assert "a solo brain: the owner's terminal has every verb on every node" in capsys.readouterr().out
    assert cli.main(["access", "explain", "carol", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"person": "carol", "solo": True}
    assert cli.main(["access", "explain", "zed"]) == 1
    brain("v: 1\npeople:\n  - {person_id: carol, name: Carol}\nmemberships:\n  - {person_id: carol, roles: [owner]}\n")
    assert identity.load(brain.root).findings == []   # one owner on Global: the same, said
    assert _x("carol", "site", brain.root)["grade"] == "owner"


def test_brain_check_reports_the_access_findings_as_warnings(brain, capsys):
    brain(MEMBERS + "  - {person_id: carol, scope: nowhere, grade: viewer}\n")
    assert schema.mode() == schema.READ
    assert _stores._check_identity(brain.root, "hub") == 0   # a warning: nothing new is refused
    assert "warning: identity: members.yaml: memberships[5]: scope 'nowhere' is no node" in capsys.readouterr().out


def test_a_grant_on_a_node_never_widens_who_verifies_a_signature(brain):
    """A decider or a releaser granted on a node (scope:) is that node's, never the whole brain's; a role granted to a
    group verifies no signature in this slice (identity.deciders and the release signers read people only)."""
    from brain import tagsig
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample0 x@y"
    brain("v: 1\npeople:\n  - {person_id: carol, name: Carol, keys: {signing: [{key: \"" + key + "\"}]}}\n"
          "  - {person_id: alice, name: Alice, keys: {signing: [{key: \"" + key + "\"}]}}\n"
          "groups:\n  - {id: crew, members: [alice]}\n"
          "memberships:\n  - {person_id: carol, scope: finance, roles: [decider, releaser]}\n"
          "  - {group: crew, roles: [decider, releaser]}\n  - {person_id: carol, scope: global, roles: [owner]}\n")
    m = identity.load(brain.root)
    assert m.findings == []
    assert identity.deciders(m.data) == {}   # neither is a decider of the whole brain
    assert list(identity.deciders(m.data, "finance")) == ["carol"]   # the node's own
    assert tagsig._releaser_ids(m.data) == set()
    assert identity.node_of({"scope": "global"}) == "" and identity.node_of({"project": "site"}) == "site"
    assert identity.node_of({"scope": 3}) == "<no node>"   # a wrong type names no node: never the whole brain


KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample0 x@y"


def _signers(brain, grant: str):
    from brain import tagsig
    brain("v: 1\npeople:\n  - {person_id: alice, name: Alice, keys: {signing: [{key: \"" + KEY + "\"}]}}\n"
          "memberships:\n  - " + grant + "\n")
    m = identity.load(brain.root)
    return list(identity.deciders(m.data)), tagsig._releaser_ids(m.data)


@pytest.mark.parametrize("grant", [
    "{person_id: alice, scope: null, project: finance, roles: [decider, releaser]}",   # scope there, null: no node
    "{person_id: alice, project: null, roles: [decider, releaser]}",
    "{person_id: alice, roles: [decider, releaser], until: 2020-01-01}",   # expired
    "{person_id: alice, roles: [decider, releaser], since: 2099-01-01}",   # not started
    "{person_id: alice, scope: global, project: finance, roles: [decider, releaser]}",   # two nodes: none
    "{person_id: alice, group: crew, roles: [decider, releaser]}",   # a person and a group: never the person's
])
def test_a_signer_out_of_its_node_or_its_dates_verifies_nothing(brain, grant):
    assert _signers(brain, grant) == ([], set())


def test_a_signer_within_its_dates_still_verifies(brain):
    assert _signers(brain, "{person_id: alice, roles: [decider, releaser], since: 2020-01-01, until: 2099-12-31}") \
        == (["alice"], {"alice"})


def test_an_access_warning_never_moves_the_release_signers_nor_refuses_attach(brain):
    """A group's typo is an access finding: reported, but neither the release signers (tagsig reads members.yaml
    only when it has no error) nor brain identity attach depend on it."""
    from brain import tagsig
    brain("v: 1\npeople:\n  - {person_id: alice, name: Alice, keys: {signing: [{key: \"" + KEY + "\"}]}}\n"
          "groups:\n  - {id: crew, members: [alicee]}\n"
          "memberships:\n  - {person_id: alice, roles: [decider, releaser]}\n  - {group: crew, grade: viewer}\n")
    m = identity.load(brain.root)
    assert m.errors == [] and any("member 'alicee'" in f for f in m.access)
    assert tagsig._from_members(brain.root) is not None   # the signers still come from members.yaml
    assert any("member 'alicee'" in w for w in identity.check(brain.root)[1])   # and the finding is reported


@pytest.mark.parametrize("text", [
    "memberships:\n  - {group: [1], grade: viewer}\n",
    "memberships:\n  - {group: {a: 1}, grade: viewer}\n",
    "groups:\n  - {id: crew, members: [carol]}\nmemberships:\n  - {group: crew, grade: viewer}\n"
    "  - {person_id: [carol], grade: viewer}\n",
])
def test_a_value_of_the_wrong_type_is_reported_never_a_crash(brain, capsys, text):
    brain("v: 1\npeople:\n  - {person_id: carol, name: Carol}\n  - {person_id: [x], name: X}\n" + text)
    m = identity.load(brain.root)
    assert m.findings != []
    assert cli.main(["access", "explain", "carol"]) == 0
    assert cli.main(["identity", "check"]) == 0   # warnings: nothing refused


def test_deep_or_shared_group_nesting_is_checked_in_linear_time(brain):
    import time
    chain_ = "".join(f"  - {{id: g{i}, members: [g{i + 1}]}}\n" for i in range(1500)) + "  - {id: g1500, members: [carol]}\n"
    diamond = "".join(f"  - {{id: d{i}, members: [d{i + 1}a, d{i + 1}b]}}\n  - {{id: d{i + 1}a, members: [d{i + 1}]}}\n"
                      f"  - {{id: d{i + 1}b, members: [d{i + 1}]}}\n" for i in range(40)) + "  - {id: d40, members: [carol]}\n"
    brain("v: 1\npeople:\n  - {person_id: carol, name: Carol}\ngroups:\n" + chain_ + diamond
          + "  - {id: loop-a, members: [loop-b]}\n  - {id: loop-b, members: [loop-a]}\n"
          "memberships:\n  - {group: g0, grade: viewer}\n")
    start = time.monotonic()
    m = identity.load(brain.root)
    assert time.monotonic() - start < 20
    assert [f for f in m.access if "a cycle" in f] == ["members.yaml: groups: a cycle: loop-a -> loop-b -> loop-a"]
    assert _x("carol", "global", brain.root)["grade"] == "viewer"   # through 1501 nested groups


def test_an_organization_membership_takes_no_grade_nor_group(brain):
    brain("v: 1\npeople:\n  - {person_id: ada, name: Ada}\norganizations:\n  - {id: acme-org, name: Acme}\n"
          "groups:\n  - {id: crew, members: [ada]}\nmemberships:\n"
          "  - {person_id: ada, organization: acme-org, grade: owner, roles: [member]}\n"
          "  - {group: crew, organization: acme-org, roles: [member]}\n")
    found = identity.load(brain.root).findings
    assert any("memberships[0]: an organization's or a tenant's membership" in f and "not grade" in f for f in found)
    assert any("memberships[1]: an organization's or a tenant's membership" in f and "not group" in f for f in found)


def test_explain_json_says_why_it_fails(brain, capsys):
    brain()
    assert cli.main(["access", "explain", "zed", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {"error": "'zed' is not in members.yaml people"}


def test_explain_says_which_decide_verifies_a_signature(brain, capsys):
    brain()
    assert cli.main(["access", "explain", "alice", "--scope", "ledger"]) == 0
    assert "a signature verifies only a decider granted to the person by name" in capsys.readouterr().out
