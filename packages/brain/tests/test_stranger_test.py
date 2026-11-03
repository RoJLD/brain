"""installer/stranger_test.py, the stranger test's harness (wi-brain-stranger-install-test): its isolation and its leak
scan; the install and the scenario themselves run against a fresh venv (see the script's docstring)."""

import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "installer" / "stranger_test.py"


@pytest.fixture(scope="module")
def st():
    spec = importlib.util.spec_from_file_location("stranger_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_environment_is_a_strangers(st, tmp_path, monkeypatch):
    """A home of its own, none of the caller's brain variables, and a PATH with the venv first and no docker."""
    for k, v in {"BRAIN_CONFIG": "x", "BRAIN_PERSONAL": "x", "CLAUDE_BRAIN_DIR": "x", "BRAIN_PROJECTS": "x",
                 "GH_TOKEN": "x"}.items():
        monkeypatch.setenv(k, v)
    scripts = tmp_path / "venv" / "bin"
    env = st.isolated_env(tmp_path, scripts)
    assert not {"BRAIN_CONFIG", "BRAIN_PERSONAL", "CLAUDE_BRAIN_DIR", "BRAIN_PROJECTS", "GH_TOKEN"} & set(env)
    home = tmp_path / "home"
    assert env["HOME"] == env["USERPROFILE"] == str(home) and env["BRAIN_HOME"] == str(home / ".brain")
    assert env["PATH"].split(os.pathsep)[0] == str(scripts)
    gitconfig = Path(env["GIT_CONFIG_GLOBAL"]).read_text(encoding="utf-8")
    assert f"name = {st.OWNER}" in gitconfig and "example.invalid" in gitconfig


def test_leaks_are_whole_words_in_outputs_and_files(st):
    deny = st.parse_deny(["people:Grace Example", "repos:secret-lab"])
    texts = {"output of status": "waiting on grace example", "notes/x.md": "the secret-labs and secret_lab",
             "README.md": "nothing"}
    assert st.leaks(texts, deny) == [{"category": "people", "term": "Grace Example", "where": "output of status"}]


def test_a_deny_needs_its_category(st):
    with pytest.raises(SystemExit, match="category:term"):
        st.parse_deny(["Grace"])


def test_the_hooks_bash_is_never_wsls(st):
    """On Windows a bare bash is WSL's System32 one, found before the PATH: the harness names Git's."""
    assert "system32" not in st.git_bash().lower()
