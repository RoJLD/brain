"""The scout's norm lints (brain.norms, wi-brain-norm-lints; spec-brain-client-standards §2 and §4): each norm on
invented snippets, positive and negative, then through brain audit --diff on a fixture repo: info lines by default
(the release rule: nothing that passed is newly refused), NEW under config.json audit.norm_lints_strict, DEFER for
the occurrences already in a touched file, nothing for one moved from another file, justified by a Justified: line."""

import json
import shutil

import pytest

from brain import cli, config, norms

from conftest import BRAIN
from test_scout import LAB, _setup

NORMS = set(norms.SEVERITY)


def _found(text):
    return [(h.check, h.line) for h in norms.hits(text)]


# --- each norm on its own ---

@pytest.mark.parametrize("text", [
    "import subprocess\nsubprocess.run(['git', 'status'])\n",
    "import subprocess as sp\nsp.check_output(['git', 'log'], text=True)\n",
    "from subprocess import call\ncall(['ls'])\n",
    "import subprocess\nsubprocess.check_call(['ls'], cwd='.')\n",
    "import urllib.request\nurllib.request.urlopen('https://example.org')\n",
    "from urllib.request import urlopen\nurlopen('https://example.org', None)\n",
    "import subprocess\np = subprocess.Popen(['x'])\np.wait()\n",
    "import subprocess\nwith subprocess.Popen(['x']) as proc:\n    out, err = proc.communicate(b'in')\n",
    "import subprocess\nsubprocess.run(['x'], timeout=None)\n",                  # an explicit no-timeout
    "from urllib.request import urlopen\nurlopen('https://example.org', timeout=None)\n",
    "from urllib.request import urlopen\nurlopen('https://example.org', None, None)\n",
    "import subprocess\np = subprocess.Popen(['x'])\np.wait(None)\n",
])
def test_a_call_without_a_timeout(text):
    assert _found(text)[-1][0] == "norm.timeout"


@pytest.mark.parametrize("text", [
    "import subprocess\nsubprocess.run(['git', 'status'], timeout=30)\n",
    "import subprocess\nsubprocess.check_output(['git'], **opts)\n",           # the keyword may be in it
    "from urllib.request import urlopen\nurlopen('https://example.org', None, 10)\n",
    "import subprocess\np = subprocess.Popen(['x'])\np.wait(5)\np.communicate(timeout=5)\np.communicate(b'', 5)\n",
    "def run(cmd):\n    pass\nrun(['ls'])\n",                                   # not subprocess's run
    "import asyncio\nasyncio.run(main())\n",
    "queue.wait()\n",                                                              # not a Popen
])
def test_a_call_with_a_timeout_or_another_function(text):
    assert "norm.timeout" not in {c for c, _ in _found(text)}


@pytest.mark.parametrize("text", [
    "open('notes.md')\n",
    "with open(path, 'w') as f:\n    f.write(x)\n",
    "open(path, mode='rt')\n",
    "import io\nio.open(path, 'a')\n",
    "from pathlib import Path\nPath('x').read_text()\n",
    "p.write_text(data)\n",
    "p.read_text(errors='replace')\n",
    "open('x', encoding=None)\n",                       # the locale's
])
def test_a_text_file_without_an_encoding(text):
    assert [c for c, _ in _found(text)] == ["norm.encoding"]


@pytest.mark.parametrize("text", [
    "open('x', encoding='utf-8')\n",
    "open('x', 'rb')\n",
    "open('x', mode='wb')\n",
    "open('x', mode)\n",                                # not a literal: not judged
    "open('x', 'r', -1, 'utf-8')\n",
    "open(*args)\n",
    "import os\nos.open('x', os.O_RDONLY)\n",
    "p.read_text('utf-8')\np.read_text(encoding='utf-8')\np.write_text(s, 'utf-8')\np.write_text(s, encoding='utf-8')\n",
    "p.read_bytes()\nwebbrowser.open(url)\n",
])
def test_a_binary_file_or_an_encoding(text):
    assert _found(text) == []


@pytest.mark.parametrize("text", [
    "from datetime import datetime\nrow = {'at': datetime.now().isoformat()}\n",
    "import datetime\nprint(f'{datetime.datetime.now()}')\n",
    "import datetime as dt\nrec = {'at': dt.datetime.utcnow()}\n",
    "from datetime import datetime\ns = str(datetime.today())\n",
    "from datetime import datetime\ndef f():\n    stamp = datetime.now().replace(microsecond=0)\n"
    "    return stamp.isoformat()\n",
    "from datetime import datetime\nimport json\ndef f(out):\n    now = datetime.now()\n    json.dump(now, out)\n",
    "from datetime import datetime\nrec = dict(at=datetime.now(tz=None))\n",
    "from datetime import datetime\ns = datetime.utcnow().replace(tzinfo=None).isoformat()\n",   # still naive
])
def test_a_naive_datetime_stored(text):
    assert [c for c, _ in _found(text)] == ["norm.naive-time"]


@pytest.mark.parametrize("text", [
    "from datetime import datetime, timezone\nrow = {'at': datetime.now(timezone.utc).isoformat()}\n",
    "from datetime import datetime\nrow = {'at': datetime.now(tz).isoformat()}\n",
    "from datetime import datetime\nrow = {'at': datetime.now().astimezone().isoformat()}\n",
    "from datetime import datetime\nprint(datetime.now().strftime('%H:%M'))\n",        # a display
    "from datetime import datetime\ndef f(t0):\n    now = datetime.now()\n    return (now - t0).seconds\n",
    "from datetime import date\nrow = {'on': date.today().isoformat()}\n",              # a date, not a time
    "from datetime import datetime, timezone\nrow = {'t': datetime.utcnow().replace(tzinfo=timezone.utc)}\n",
    "from datetime import datetime, timezone\ns = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()\n",
    "from datetime import datetime, timezone\ndef f():\n"
    "    t = datetime.now().replace(microsecond=0).replace(tzinfo=timezone.utc)\n    return t.isoformat()\n",
])
def test_an_aware_datetime_or_one_not_stored(text):
    assert _found(text) == []


@pytest.mark.parametrize("text", [
    "import subprocess\nsubprocess.run(['gh', 'auth', '--with-token', token], timeout=9)\n",
    "import subprocess\nsubprocess.run(['tool', f'--password={args.password}'], timeout=9)\n",
    "import subprocess\ndef f(api_key):\n    cmd = ['curl', '-H']\n    cmd.append(api_key)\n"
    "    subprocess.run(cmd, timeout=9)\n",
    "import subprocess\nsubprocess.Popen(['x'], env={'GH_TOKEN': tok})\n",
    "import os, subprocess\nsubprocess.run(['x'], env=dict(os.environ, GITHUB_TOKEN=t), timeout=9)\n",
    "import os, subprocess\ndef f(self):\n    env = {**os.environ, 'X': self.secret}\n"
    "    subprocess.run(['x'], env=env, timeout=9)\n",
    "import os\nos.environ['OPENAI_API_KEY'] = key\n",
    "def f(tok):\n    env = {}\n    env['GH_TOKEN'] = tok\n",
    "import subprocess\nsubprocess.check_output(['x', get_token()], timeout=9)\n",
    "import os, subprocess\nsubprocess.run(['x'], env={'A': os.environ['GH_TOKEN']}, timeout=1)\n",
    "import subprocess\nsubprocess.run(['x', cfg['api_key']], timeout=1)\n",
])
def test_a_secret_in_argv_or_env(text):
    assert [c for c, _ in _found(text)] == ["norm.secret-argv"]


@pytest.mark.parametrize("text", [
    "import subprocess\nsubprocess.run(['gh', 'auth', 'token'], input=token, timeout=9)\n",    # by stdin
    "import subprocess\nsubprocess.run(['x', '--token-file', token_path], timeout=9)\n",
    "import subprocess\nsubprocess.run(['x', '--max-tokens', str(max_tokens)], timeout=9)\n",
    "import subprocess\nsubprocess.run(['x', key], timeout=9)\n",                            # a bare key
    "import os, subprocess\nsubprocess.run(['x'], env={**os.environ, 'GH_TOKEN': ''}, timeout=9)\n",  # cleared
    "import os\nos.environ['TOKEN_ENV'] = name\n",
    "import secrets\nheaders = {'Authorization': token}\n",                                 # not a child's
    "def run(cmd):\n    pass\nrun(['x', token])\n",
    "import os, subprocess\nsubprocess.run(['x', cfg['token_path']], env={'H': os.environ['HOME']}, timeout=1)\n",
])
def test_no_secret_given_to_a_child(text):
    assert _found(text) == []


def test_secret_names():
    yes = ["token", "gh_token", "GH_TOKEN", "password", "dbPassword", "api_key", "OPENAI_API_KEY", "private_key",
           "client_secret", "passphrase", "credentials"]
    no = ["key", "keys", "monkey", "tokens", "max_tokens", "token_path", "TOKEN_ENV", "secret_name", "author",
          "sort_key", "token_count", "PASSWORD_STORE_DIR", ""]
    assert [n for n in yes if not norms.secret_name(n)] == [] and [n for n in no if norms.secret_name(n)] == []


def test_a_text_that_does_not_parse_has_none_and_the_scope_is_the_function():
    assert norms.hits("def (:\n") == [] and norms.hits(None) == []
    [h] = norms.hits("class A:\n    def go(self):\n        return open('x')\n")
    assert (h.check, h.scope, h.line) == ("norm.encoding", "A.go", 3)


# --- through the scout ---

BAD = ("import subprocess\n\n\ndef go():\n    subprocess.run(['ls'])\n\n\n"
       "def read(p):\n    return open(p).read()\n")


def _write(repo, rel, text):
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8", newline="\n")


def _norms(capsys, repo, *args):
    rc = cli.main(["audit", "--diff", *args, "--repo-dir", str(repo), "--json"])
    data = json.loads(capsys.readouterr().out)
    return rc, sorted((f["check"], f["unit"], f["tag"]) for f in data["findings"] if f["check"] in NORMS), data


def _strict(tmp_path, monkeypatch):
    folder = tmp_path / "strict-brain"
    folder.mkdir()
    shutil.copy(BRAIN.parent / "rules.md", folder / "rules.md")
    data = json.loads(BRAIN.read_text(encoding="utf-8"))
    data["audit"] = {norms.STRICT_KEY: True}
    cfg = folder / "config.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))


def test_what_a_change_adds_is_info_by_default_and_never_blocks(make_repo, tmp_path, monkeypatch, capsys):
    assert not norms.strict(None)   # the tests' brain has no audit key
    lab = _setup(make_repo, tmp_path, monkeypatch)
    _write(lab, "src/lab/core.py", BAD)
    rc, found, data = _norms(capsys, lab)
    assert found == [("norm.encoding", "src/lab/core.py::read", "info"),
                     ("norm.timeout", "src/lab/core.py::go", "info")]
    assert data["new_findings"] == 0 and data["ruleset"] >= 7
    info = next(f for f in data["findings"] if f["check"] == "norm.timeout")
    assert "line 5" in info["why"] and "audit.norm_lints_strict" in info["why"]
    _write(lab, "src/lab/core.py", LAB["src/lab/core.py"])
    assert _norms(capsys, lab)[1] == [] and rc == 0


def test_the_owners_opt_in_makes_them_new_and_a_justified_line_clears_one(make_repo, tmp_path, monkeypatch, capsys):
    _strict(tmp_path, monkeypatch)
    assert config.check() == [] and norms.strict(None)   # an optional key the schema declares
    lab = _setup(make_repo, tmp_path, monkeypatch)
    _write(lab, "src/lab/core.py", BAD)
    rc, found, _ = _norms(capsys, lab)
    assert rc == 1 and {t for *_, t in found} == {"NEW"} and len(found) == 2
    body = tmp_path / "body.md"
    body.write_text("Justified: src/lab/core.py::go: the child is the owner's own command\n", encoding="utf-8")
    _, found, _ = _norms(capsys, lab, "--pr-body", str(body))
    assert found == [("norm.encoding", "src/lab/core.py::read", "NEW"),
                     ("norm.timeout", "src/lab/core.py::go", "justified")]


def test_old_ones_are_deferred_by_batch_and_a_moved_one_is_not_new(make_repo, tmp_path, monkeypatch, capsys):
    _strict(tmp_path, monkeypatch)
    lab = _setup(make_repo, tmp_path, monkeypatch, {**LAB, "src/lab/old.py": BAD + "\n\ndef again(p):\n"
                                                    "    return open(p).read() + open(p, 'a').name\n"})
    _write(lab, "src/lab/old.py", BAD + "\n\nX = 1\n")                      # touched: the old ones stay
    _write(lab, "src/lab/core.py", "def again(p):\n    return open(p).read() + open(p, 'a').name\n")   # moved
    _, found, data = _norms(capsys, lab)   # (core.py's go removed makes other findings: not this test's)
    assert found == [("norm.encoding", "src/lab/core.py", "DEFER"), ("norm.encoding", "src/lab/old.py", "DEFER"),
                     ("norm.timeout", "src/lab/old.py", "DEFER")]   # the moved ones stay old code where they land
    whys = {f["unit"]: f["why"] for f in data["findings"] if f["check"] == "norm.encoding"}
    assert whys["src/lab/old.py"].startswith("1 already in the file (line 9)")
    assert whys["src/lab/core.py"].startswith("2 already in the file (line 2, 2)")
    _write(lab, "src/lab/core.py", "def fresh(p):\n    return open(p).read()\n")   # not moved: added
    _, found, _ = _norms(capsys, lab)
    assert ("norm.encoding", "src/lab/core.py::fresh", "NEW") in found


def test_a_fix_in_one_file_does_not_excuse_the_same_text_added_in_another(make_repo, tmp_path, monkeypatch, capsys):
    _strict(tmp_path, monkeypatch)
    lab = _setup(make_repo, tmp_path, monkeypatch, {**LAB, "src/lab/old.py": BAD})
    _write(lab, "src/lab/old.py", BAD.replace("open(p)", "open(p, encoding='utf-8')"))   # read() fixed, still there
    _write(lab, "src/lab/core.py", "def read(p):\n    return open(p).read()\n")          # the same text, added
    _, found, _ = _norms(capsys, lab)
    assert found == [("norm.encoding", "src/lab/core.py::read", "NEW"), ("norm.timeout", "src/lab/old.py", "DEFER")]


def test_old_ones_are_deferred_without_blocking_by_default(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch, {**LAB, "src/lab/old.py": BAD,
                                                    "tests/test_old.py": "from lab.old import go, read\n"})
    _write(lab, "src/lab/old.py", BAD + "\n\nX = 1\n")
    rc, found, data = _norms(capsys, lab)
    assert found == [("norm.encoding", "src/lab/old.py", "DEFER"), ("norm.timeout", "src/lab/old.py", "DEFER")]
    assert data["new_findings"] == 0 and data["left"] == 0 and rc == 0   # the release rule: DEFER never blocks
