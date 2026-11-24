"""brain.inventory split by concern (wi-brain-engine-debt, batch 4): the text patterns and Python facts
(brain.inventory_python), the production closure (brain.inventory_closure), the test evidence
(brain.inventory_evidence) and the code stores (brain.inventory_stores). brain.inventory stays their front: every
public name it had is still there, the same object, and each concern module imports on its own, first, in a fresh
interpreter (no import cycle through brain.inventory)."""

import subprocess
import sys

import pytest

from brain import inventory, inventory_closure, inventory_evidence, inventory_python, inventory_stores

CONCERNS = (inventory_python, inventory_closure, inventory_evidence, inventory_stores)

# the public names brain.inventory had before the split (0.6.1), each still read there by its callers
BEFORE = {
    "ALL", "ASSIGN", "DASH_M", "DASH_M_ARG", "DEF", "DOTTED", "DOTTED_FULL", "FILE_REF", "FIXTURE", "GIT_ENV", "IDENT",
    "IMPORT", "MAKE_CALL", "MAKE_TARGET", "RUN", "SCRIPT_EXT", "SKIP_DIRS", "STR", "STRING", "SUBPARSER", "TEST_DIRS",
    "TEXT_EXT", "TRIPLE", "USED", "WORD", "AuditError", "Evidence", "Index", "Layout", "PyFacts", "Reach",
    "RepoFacts", "Store", "Tree", "Unit", "closure", "code_stores", "collect", "command_at", "default_branch", "edges",
    "evidence", "facts", "frozen_store", "git", "git_tree", "has_symbol", "in_tests", "is_doc", "is_test", "layout",
    "make_targets", "module_evidence", "module_index", "parse_code_ref", "reading_ref", "reexports", "run_mentions",
    "script_evidence", "shim_target", "skipped", "stem", "subcommand_of", "tests_reach", "text_imports", "text_tokens",
    "unit_evidence", "wanted", "week_commits", "without_fixtures", "work_tree",
}


def test_the_front_keeps_every_public_name():
    assert set(inventory.__all__) == BEFORE
    assert all(hasattr(inventory, n) for n in BEFORE)
    # the private names callers read through brain.inventory (links.py, audit_measure.py)
    for n in ("_norm", "_parse", "_load_yaml", "_run_git", "_read_bytes", "_blob_id", "_BLOBS"):
        assert hasattr(inventory, n), n


@pytest.mark.parametrize("mod", CONCERNS, ids=lambda m: m.__name__)
def test_a_moved_name_is_the_concern_modules_own_object(mod):
    moved = [n for n in BEFORE if n in vars(mod)]
    assert moved, mod.__name__
    for n in moved:
        assert getattr(inventory, n) is getattr(mod, n), n


@pytest.mark.parametrize("name", [m.__name__ for m in CONCERNS])
def test_a_concern_module_imports_first(name):
    """Imported before brain.inventory in a fresh interpreter: none reads brain.inventory at import time (its names
    are annotations only), so no cycle."""
    r = subprocess.run([sys.executable, "-c", f"import {name}; import brain.inventory as i; print(len(i.__all__))"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(len(BEFORE))
