"""The engine's stores under BRAIN_HOME and the sources it reads (wi-brain-classes-home-stores; spec-brain-session-
telemetry §3.7, §9.4; spec-brain-data-compat N1 and COMPAT-6): every name the engine's code writes under BRAIN_HOME
has a class, an undeclared one takes its default and is only noted, and the desktop app's session metadata is read
through a closed list of keys, its text keys never reaching a store."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from brain import capture, classes, config, governor, sessions, tidy

SRC = Path(classes.__file__).parent
INSTALLER = SRC.parents[1] / "installer"
HOST = "local_44444444-4444-4444-8444-444444444444"
CLI = "dddddddd-0000-4000-8000-000000000004"
PARENT = "local_55555555-5555-4555-8555-555555555555"

# --- what the engine's code writes under BRAIN_HOME ------------------------------------------------------------------

_PY = re.compile(r"""brain_home\(\)\s*/\s*(?:"([^"{}/]+)"|'([^'{}/]+)'|f"([^"{}/]+)/|([A-Z][A-Z0-9_]*)\b)""")
_SH = re.compile(r"\$\{BRAIN_HOME:-(?:\$\{[^}]*\}|\$(?!\{)|[^}$])*\}/([\w.-]+)")   # a nested ${...} whole
_HOME_VAR = re.compile(r"\$home/([\w.-]+)")
_DOC = re.compile(r"(?:<BRAIN_HOME>|\$BRAIN_HOME|~/\.brain)[\\/]([A-Za-z][\w.-]*)")
_PS = re.compile(r"Join-Path \$brain_home '([\w.-]+)'")


def _const(text: str, name: str) -> str | None:
    m = re.search(rf"^{name}\s*=\s*[\"']([^\"']+)[\"']", text, re.M)
    return m.group(1).split("/")[0] if m else None


def written_names(files: list[Path] | None = None) -> tuple[dict[str, set[str]], list[str]]:
    """{name at the top of BRAIN_HOME: the files that name it}, and the ``brain_home() / NAME`` constants that could
    not be resolved: the Python modules, the hooks' scripts and the installer (not brain.classes, which lists them)."""
    names: dict[str, set[str]] = {}
    unresolved = []
    if files is None:
        files = [f for f in [*SRC.rglob("*.py"), *SRC.rglob("*.sh"), *INSTALLER.glob("*.ps1")]
                 if f.name != "classes.py" or f.parent != SRC]
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(SRC.parent).as_posix() if SRC.parent in f.parents else f.name
        found = set(_DOC.findall(text)) | set(_PS.findall(text))
        if f.suffix == ".sh":
            found |= set(_SH.findall(text)) | set(_HOME_VAR.findall(text))
        if f.suffix == ".py":
            for lit, lit2, fstr, const in _PY.findall(text):
                if const:
                    value = _const(text, const)
                    if value is None:
                        unresolved.append(f"{rel}: brain_home() / {const}")
                        continue
                    found.add(value)
                else:
                    found.add((lit or lit2 or fstr).split("/")[0])
        for n in found:
            names.setdefault(n.rstrip("."), set()).add(rel)
    return names, unresolved


def test_every_name_the_engine_writes_under_brain_home_has_a_class():
    """The scan finds the stores (a sanity floor), resolves every constant, and fails on a name no engine store
    covers: a new store is added to classes.ENGINE_STORES with its class and format, in the same PR."""
    names, unresolved = written_names()
    assert unresolved == []
    assert {"ledger", "usage", "cache", "budget", "announce", "handover", "features", "forecast", "memory-sync",
            "venv", "bin", "secrets", "stacks", "tui.json", "update.json", "personal.json", "profile.json",
            "code-index.json", "public-check", "reviews", "code-map", "merge-ready"} <= set(names)
    every = classes.effective([])
    unknown = {n: sorted(w) for n, w in names.items() if not classes.store_of(every, f"$BRAIN_HOME/{n}")}
    assert unknown == {}, f"names written under BRAIN_HOME without a class (add them to ENGINE_STORES): {unknown}"


def test_the_scan_finds_a_new_store(tmp_path):
    """A module that writes a name no engine store covers is caught, whichever way it names it."""
    f = tmp_path / "newmod.py"
    f.write_text('DIR = "new-store"\ndef a():\n    return paths.brain_home() / DIR / "x.json"\n'
                 'def b():\n    return paths.brain_home() / "other" / "y"\n'
                 'def c():\n    return paths.brain_home() / MISSING\n', encoding="utf-8")
    sh = tmp_path / "hook.sh"
    sh.write_text('mark="${BRAIN_HOME:-${USERPROFILE:-$HOME}/.brain}/marks/$sid.mark"\n', encoding="utf-8")
    names, unresolved = written_names([f, sh])
    assert set(names) == {"new-store", "other", "marks"} and unresolved == ["newmod.py: brain_home() / MISSING"]
    every = classes.effective([])
    assert not any(classes.store_of(every, f"$BRAIN_HOME/{n}") for n in names)


def test_engine_stores_are_well_formed():
    """Each store has a class no looser than sealed (secret for the secrets), a format class, what it holds; a
    specific path comes before the folder that holds it (the first store that covers a path wins)."""
    for name, k in classes.ENGINE_STORES.items():
        assert classes.class_ok(k.cls) and classes.RANK[k.cls] >= classes.RANK[classes.FLOOR], name
        assert k.format in classes.FORMATS and k.what and classes.is_machine(k.path), name
    assert classes.ENGINE_STORES["secrets"].cls == "secret"
    assert classes.KNOWN == {n: (k.path, k.cls) for n, k in classes.ENGINE_STORES.items()}
    order = [k.path for k in classes.ENGINE_STORES.values()]
    for i, p in enumerate(order):
        assert not any(p.startswith(q + "/") for q in order[:i]), f"{p} comes after the folder that holds it"
    assert classes.store_of(classes.effective([]), "$BRAIN_HOME/stacks/sovereign/data/otel-collector/x").name \
        == "collector"
    assert classes.store_of(classes.effective([]), "$BRAIN_HOME/stacks/sovereign/compose.yaml").name == "stacks"
    # the suggested lines are valid: a secret store takes no exit, a sealed log goes offsite and to the backups
    assert "to" not in classes.engine_line("secrets") and "to" not in classes.engine_line("venv")
    assert classes.engine_line("usage") == {"class": "sealed", "paths": ["$BRAIN_HOME/usage"],
                                            "to": ["offsite", "backup"]}


def test_the_runbook_lists_every_engine_store_and_text_key():
    doc = (SRC.parents[1] / "docs" / "vault.md").read_text(encoding="utf-8")
    missing = [n for n in classes.ENGINE_STORES if f"`{n}`" not in doc]
    assert missing == [] and all(f"`{k}`" in doc for k in classes.APP_TEXT_KEYS)
    assert all(f"`{k}`" in doc for k in classes.APP_SESSION_KEYS | classes.APP_SPAWN_KEYS)


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A brain folder (no git) whose config.json is the test's ``stores``."""
    root = tmp_path / "brain"
    root.mkdir()
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-projects.yaml"))
    monkeypatch.delenv("BRAIN_SCOPES", raising=False)

    def write(stores: dict) -> config.Config:
        data = {"v": 1, "identity": {"owner": "Ada"}, "classes": {"stores": stores}}
        (root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
        return config.load(root)
    write.root = root
    return write


def test_a_name_in_brain_home_no_store_covers_is_noted(brain, brain_home, capsys):
    """BRAIN_HOME's names are read: a store the engine knows, a write's leftover and a declared one pass; another
    is noted, sealed by default, and never fails the check."""
    for d in ("usage", "stacks/sovereign/data/otel-collector", "odd-folder", "mine"):
        (brain_home / d).mkdir(parents=True)
    for f in ("tui.json", "tui.json.bak", "update.tmp", "stray.txt"):
        (brain_home / f).write_text("{}", encoding="utf-8")
    cfg = brain({"mine": {"class": "sealed", "paths": ["$BRAIN_HOME/mine"]}, "repo": {"class": "private",
                                                                                      "paths": ["**"]}})
    rep = classes.check(cfg=cfg)
    assert rep.unknown == ["odd-folder", "stray.txt"] and rep.errors == []
    assert rep.home_notes[-1] == ("2 name(s) in BRAIN_HOME that no store covers, sealed by default: odd-folder, "
                                  "stray.txt (declare them in classes.stores)")
    assert classes.main(brain.root, check_only=True) == 0
    out = capsys.readouterr().out
    assert "note: 2 name(s) in BRAIN_HOME" in out and "engine store(s) undeclared" in out
    # a catch-all over BRAIN_HOME covers every name
    rep = classes.check(cfg=brain({"home": {"class": "sealed", "paths": ["$BRAIN_HOME"]},
                                   "repo": {"class": "private", "paths": ["**"]}}))
    assert rep.unknown == [] and rep.defaulted == [s for s in rep.defaulted if s.name == "transcripts"]


def test_a_leftover_is_told_by_its_suffix_not_by_a_substring(brain_home):
    """A write's leftover ends in .tmp, .bak or .lock, or carries a set-aside stamp; a name that only holds one of
    those marks inside it (export.tmpl, sync.lockfile) is still a name no store covers."""
    brain_home.mkdir(parents=True, exist_ok=True)
    for f in ("export.tmpl", "sync.lockfile", "notes.backup", "a.json.tmp", "b.123.tmp", "c.json.bak", "d.lock",
              "e.json.unreadable-20261110T120000Z"):
        (brain_home / f).write_text("{}", encoding="utf-8")
    assert classes.home_unknown([]) == ["export.tmpl", "notes.backup", "sync.lockfile"]


def test_suggest_prints_the_lines_a_brain_misses(brain, capsys):
    """A brain that declares classes gets only the engine stores it leaves at their default (a name it already
    uses gets home-); declaring them clears the note, with no error."""
    stores = {"usage": {"class": "private", "paths": ["docs/**"]},
              "ledger": {"class": "sealed", "paths": ["$BRAIN_HOME/ledger"], "to": ["offsite"]},
              "repo": {"class": "private", "paths": ["**"]}}
    cfg = brain(stores)
    block = classes.suggest(cfg)["stores"]
    assert "ledger" not in block and "home-usage" in block and "usage" not in block
    assert block["home-usage"]["paths"] == ["$BRAIN_HOME/usage"] and block["secrets"] == {
        "class": "secret", "paths": ["$BRAIN_HOME/secrets"]}
    assert len(block) == len(classes.ENGINE_STORES) - 1
    assert classes.main(brain.root, suggest_=True) == 0
    assert json.loads(capsys.readouterr().out)["classes"]["stores"] == block
    rep = classes.check(cfg=brain({**{k: v for k, v in stores.items() if k != "repo"}, **block,
                                   "repo": stores["repo"]}))
    assert rep.defaulted == [] and rep.home_notes == [] and rep.errors == []


def test_a_path_shows_its_default_class(brain, capsys):
    brain({"repo": {"class": "private", "paths": ["**"]}})
    assert classes.main(brain.root, which=["$BRAIN_HOME/usage/quota.json", "$BRAIN_HOME/secrets/x", "notes/a.md"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "$BRAIN_HOME/usage/quota.json: usage (sealed, by default: undeclared)",
        "$BRAIN_HOME/secrets/x: secrets (secret, by default: undeclared)",
        "notes/a.md: repo (private)"]


def test_the_json_view_names_the_defaults_and_the_sources(brain, capsys):
    brain({"repo": {"class": "private", "paths": ["**"]}})
    assert classes.main(brain.root, as_json=True) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"name": "usage", "class": "sealed", "paths": ["$BRAIN_HOME/usage"], "format": "log"} in data["defaulted"]
    app = data["sources"]["app-sessions"]
    assert app["never"] == list(classes.APP_TEXT_KEYS) and "lastTurnReport" not in app["keys"]
    assert classes.main(brain.root) == 0
    out = capsys.readouterr().out
    assert "usage          sealed        $BRAIN_HOME/usage                  by default (undeclared)" in out
    assert "source app-sessions: $LOCALAPPDATA/Claude-Data/*/claude-code-sessions: read only, 14 key(s)" in out


# --- the desktop app's session metadata: a source read through a closed list of keys ----------------------------------

def test_the_closed_list_holds_the_readers_lists():
    """brain.sessions' own lists are inside the declared closed list, and no text key is in it."""
    assert set(sessions.APP_KEYS.values()) | {"spawnedFrom", "prs"} <= classes.APP_SESSION_KEYS
    assert set(sessions.SPAWN_KEYS.values()) <= classes.APP_SPAWN_KEYS
    assert not set(classes.APP_TEXT_KEYS) & (classes.APP_SESSION_KEYS | classes.APP_SPAWN_KEYS)
    assert classes.outside("app-sessions", {"sessionId", "spawnedFrom.taskId", "cwd"}) == []
    assert classes.outside("app-sessions", {"lastTurnReport", "spawnedFrom.title", "spawnedFrom.spawnSeed", "*",
                                            "worktrees"}) == ["*", "lastTurnReport", "spawnedFrom.spawnSeed",
                                                              "spawnedFrom.title", "worktrees"]
    assert classes.outside("app-worktrees", {"worktrees", "worktrees.*.path", "worktrees.*.leasedBy"}) == []
    assert classes.outside("app-notes", {"anything"}) == []


MARK = "TEXT-KEY-MARKER"


@pytest.fixture
def app(tmp_path, monkeypatch):
    """One app session file (its parent named) whose text keys hold a marker, the session's ids in the
    environment."""
    d = tmp_path / "appdata" / "Claude-Data" / "claude_t" / "claude-code-sessions" / "acct" / "org"
    d.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv(sessions.HOST_ENV, HOST)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", CLI)
    data = {"sessionId": HOST, "cliSessionId": CLI, "title": "A session", "createdAt": 1_000, "cwd": str(tmp_path),
            "lastActivityAt": int(datetime.now(timezone.utc).timestamp() * 1000), "isArchived": False,
            "model": "a-model", "effort": "high", "branch": "feat/x", "completedTurns": 3, "prs": [{"n": 1}],
            "spawnedFrom": {"sessionId": PARENT, "taskId": "task_1", "name": "f1-x", "sideSession": True,
                            "title": f"{MARK} spawn title", "spawnSeed": f"{MARK} seed"}}
    data.update({k: f"{MARK} {k}" for k in classes.APP_TEXT_KEYS if k != "remoteMcpServersConfig"})
    data["remoteMcpServersConfig"] = {"server": {"token": f"{MARK} token", "email": "ada@example.invalid"}}
    (d / f"{HOST}.json").write_text(json.dumps(data), encoding="utf-8")
    return d


class _Recorded(dict):
    """An app file's mapping that records every key a reader takes (``*`` for a read of every key)."""
    def __init__(self, data, seen, prefix=""):
        super().__init__(data)
        self._seen, self._prefix = seen, prefix

    def _wrap(self, key, value):
        return _Recorded(value, self._seen, f"{self._prefix}{key}.") if isinstance(value, dict) else value

    def get(self, key, default=None):
        self._seen.add(self._prefix + key)
        return self._wrap(key, super().get(key, default))

    def __getitem__(self, key):
        self._seen.add(self._prefix + key)
        return self._wrap(key, super().__getitem__(key))

    def __contains__(self, key):
        self._seen.add(self._prefix + key)
        return super().__contains__(key)

    def _all(self):
        self._seen.add(self._prefix + "*")

    def keys(self):
        self._all()
        return super().keys()

    def items(self):
        self._all()
        return super().items()

    def values(self):
        self._all()
        return super().values()

    def __iter__(self):
        self._all()
        return super().__iter__()


class _Json:
    """The json module, its loads recording the keys taken from an app session file (the one that holds text
    keys)."""
    def __init__(self, seen):
        self.seen = seen

    def loads(self, text, *a, **kw):
        data = json.loads(text, *a, **kw)
        if isinstance(data, dict) and any(k in data for k in classes.APP_TEXT_KEYS):
            return _Recorded(data, self.seen)
        return data

    def __getattr__(self, name):
        return getattr(json, name)


def _read_everything():
    """Every reader of the app's session files, and the writers they feed: the session tree's index and its cache,
    one session's keys, the SessionStart event (the capture hook), the governor's sessions and cache, tidy's state."""
    index = sessions.app_index()
    meta = sessions.app_meta(HOST)
    capture.session_start({"session_id": CLI, "source": "startup", "model": "a-model"})
    gov = governor.app_sessions(datetime.now(timezone.utc), timedelta(days=1))
    st = tidy.app_state()
    return index, meta, gov, st


def test_every_reader_takes_only_the_closed_list(app, monkeypatch):
    seen: set[str] = set()
    for module in (sessions, governor, tidy):
        monkeypatch.setattr(module, "json", _Json(seen))
    index, meta, gov, st = _read_everything()
    assert index[HOST]["parent"] == PARENT and meta["task"] == "task_1" and gov[0]["id"] == HOST
    assert st.cli == {CLI: HOST}
    assert {"sessionId", "cliSessionId", "spawnedFrom.sessionId", "cwd", "isArchived"} <= seen   # the scan saw reads
    assert classes.outside("app-sessions", seen) == []


def test_no_text_key_reaches_a_store(app, brain_home):
    """The readers write their caches and the ledger: the picked keys are there, never a text key's content."""
    _read_everything()
    written = [f for f in brain_home.rglob("*") if f.is_file()]
    names = {f.relative_to(brain_home).as_posix().split("/")[0] for f in written}
    assert {"cache", "ledger"} <= names
    blob = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in written)
    assert HOST in blob and PARENT in blob and "task_1" in blob              # the closed list's keys are kept
    assert MARK not in blob and "ada@example.invalid" not in blob
    assert not any(k in blob for k in classes.APP_TEXT_KEYS)
    every = classes.effective([])
    assert all(classes.store_of(every, f"$BRAIN_HOME/{f.relative_to(brain_home).as_posix()}") for f in written)


# --- the read gate: a reader of BRAIN_HOME asks brain.classes first (wi-brain-home-read-gate) -----------------------

_WALK_METHODS = {"glob", "rglob", "iterdir", "walk"}
_WALK_FUNCS = {("os", "walk"), ("os", "scandir"), ("os", "listdir"), ("glob", "glob"), ("glob", "iglob"),
               ("shutil", "copytree"), ("shutil", "make_archive")}
_SH_WALK = re.compile(r"""\b(?:find|ls|du|tar|cp\s+-\w*r\w*)\s+["']?\$\{?BRAIN_HOME(?::-[^}]*)?\}?["']?(?:\s|$|;|\|)""")


def _is_home_call(node) -> bool:
    """``brain_home()`` or ``<x>.brain_home()``: BRAIN_HOME itself, not a store under it."""
    f = getattr(node, "func", None)
    return (isinstance(node, __import__("ast").Call) and not node.args
            and ((getattr(f, "id", None) == "brain_home") or (getattr(f, "attr", None) == "brain_home")))


def home_walks(files: list[Path] | None = None) -> list[str]:
    """'file:line' of each walk of BRAIN_HOME itself in the engine's code but brain.classes (the gate): a glob, rglob,
    iterdir or walk of ``brain_home()`` or of a name bound to it in the same function, os.walk / os.scandir /
    os.listdir / glob.glob / shutil.copytree of it, and in a hook's shell script a find, ls, du, tar or cp -r of
    $BRAIN_HOME. A walk of a store under it (``brain_home() / "ledger"``) is the store's reader, not a walk of the home."""
    import ast

    out = []
    if files is None:
        files = [f for f in [*SRC.rglob("*.py"), *SRC.rglob("*.sh")] if f.name != "classes.py" or f.parent != SRC]
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(SRC.parent).as_posix() if SRC.parent in f.parents else f.name
        if f.suffix == ".sh":
            out += [f"{rel}:{n}" for n, line in enumerate(text.splitlines(), 1)
                    if not line.lstrip().startswith("#") and _SH_WALK.search(line)]
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] + [tree]
        for scope in scopes:
            bound = {t.id for n in ast.walk(scope) if isinstance(n, ast.Assign) and _is_home_call(n.value)
                     for t in n.targets if isinstance(t, ast.Name)}

            def home(e) -> bool:
                return _is_home_call(e) or (isinstance(e, ast.Name) and e.id in bound)

            for n in ast.walk(scope):
                if not isinstance(n, ast.Call):
                    continue
                fn = n.func
                if isinstance(fn, ast.Attribute) and fn.attr in _WALK_METHODS and home(fn.value):
                    out.append(f"{rel}:{n.lineno}")
                elif (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                      and (fn.value.id, fn.attr) in _WALK_FUNCS and n.args and home(n.args[0])):
                    out.append(f"{rel}:{n.lineno}")
    return sorted(set(out))


def test_no_walk_of_brain_home_outside_the_read_gate():
    """The engine walks BRAIN_HOME only through brain.classes (home_names, home_files): a new reader that walks it
    must ask the gate, so a secret store cannot be reached even by mistake (spec-brain-gnn-rose-grmg 3.4)."""
    assert home_walks() == [], "walks of BRAIN_HOME outside brain.classes: use classes.home_files or home_store"


def test_the_walk_scan_finds_each_way_of_walking_the_home(tmp_path):
    f = tmp_path / "reader.py"
    f.write_text("import os, glob\nfrom brain import paths\n"
                 "def a():\n    return list(paths.brain_home().rglob('*.yaml'))\n"
                 "def b():\n    home = paths.brain_home()\n    return list(os.walk(home))\n"
                 "def c():\n    return os.listdir(brain_home())\n"
                 "def d():\n    return list((paths.brain_home() / 'ledger').glob('*.jsonl'))\n"
                 "def e():\n    home = paths.brain_home()\n    return sorted(home.iterdir())\n", encoding="utf-8")
    g = tmp_path / "hook.sh"
    g.write_text('#!/bin/sh\n# find "$BRAIN_HOME" in a comment\nfind "${BRAIN_HOME:-$HOME/.brain}" -name x\n'
                 'ls "$BRAIN_HOME/ledger"\n', encoding="utf-8")
    assert home_walks([f, g]) == ["hook.sh:3", "reader.py:14", "reader.py:4", "reader.py:7", "reader.py:9"]


def _home(brain_home: Path) -> None:
    for rel in ("ledger/events.jsonl", "secrets/stack/db.env", "ipc/token", "usage/quota.json", "stray/x.yaml"):
        (brain_home / rel).parent.mkdir(parents=True, exist_ok=True)
        (brain_home / rel).write_text("x\n", encoding="utf-8")


def test_home_store_resolves_a_store_or_refuses(brain_home):
    cfg = config.Config(None, brain_home)
    assert classes.home_store("ledger", cfg=cfg) == brain_home / "ledger"
    for store in ("secrets", "ipc"):   # the secret stores: refused whatever the exit, the engine's own reads included
        for exit_ in (None, "local-model", "backup"):
            with pytest.raises(classes.Refused, match="secret store"):
                classes.home_store(store, exit_, cfg=cfg)
    with pytest.raises(classes.Refused, match="never"):
        classes.home_store("ledger", "cloud-model", cfg=cfg)
    with pytest.raises(classes.Refused, match="only sealed"):
        classes.home_store("ledger", "offsite", cfg=cfg)
    assert classes.home_store("ledger", "offsite", sealed=True, cfg=cfg) == brain_home / "ledger"
    with pytest.raises(classes.Refused, match="no store"):
        classes.home_store("nothing-of-the-kind", cfg=cfg)
    with pytest.raises(classes.Refused, match="not an exit"):
        classes.home_store("ledger", "a-dataset", cfg=cfg)
    declared = config.Config(None, brain_home, {"classes": {"stores": {
        "notes-cache": {"class": "private", "paths": ["$BRAIN_HOME/notes-cache"]},
        "usage": {"class": "sealed", "paths": ["$BRAIN_HOME/usage"], "to": ["local-model"]},
        "ledger": {"class": "secret", "paths": ["$BRAIN_HOME/ledger"]}}}})
    assert classes.home_store("notes-cache", "cloud-model", cfg=declared) == brain_home / "notes-cache"
    assert classes.home_store("usage", "local-model", cfg=declared) == brain_home / "usage"   # opted in by its to
    with pytest.raises(classes.Refused, match="never"):   # sealed to a local model: opt-in, and the engine's is not
        classes.home_store("usage", "local-model", cfg=cfg)
    with pytest.raises(classes.Refused):   # the brain's own class wins over the engine's suggestion
        classes.home_store("ledger", cfg=declared)


def test_home_files_never_enters_a_secret_store(brain_home):
    _home(brain_home)
    cfg = config.Config(None, brain_home)
    got = {(s, f.relative_to(brain_home).as_posix()) for s, f in classes.home_files(cfg=cfg)}
    assert got == {("ledger", "ledger/events.jsonl"), ("usage", "usage/quota.json"), ("stray", "stray/x.yaml")}
    assert list(classes.home_files("cloud-model", cfg=cfg)) == []   # sealed stores: never to a cloud model
    assert {s for s, _ in classes.home_files("offsite", sealed=True, cfg=cfg)} == {"ledger", "usage"}
    declared = config.Config(None, brain_home, {"classes": {"stores": {
        "quota": {"class": "secret", "paths": ["$BRAIN_HOME/usage/quota.json"]}}}})
    assert "usage/quota.json" not in {f.relative_to(brain_home).as_posix()   # a secret store nested in another
                                      for _, f in classes.home_files(cfg=declared)}
    assert classes.home_names() == ["ipc", "ledger", "secrets", "stray", "usage"]


def test_home_files_follows_no_link(brain_home, tmp_path):
    _home(brain_home)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("x\n", encoding="utf-8")
    try:
        (brain_home / "ledger" / "link").symlink_to(outside, target_is_directory=True)
        (brain_home / "usage" / "to-token").symlink_to(brain_home / "ipc" / "token")
    except OSError:
        pytest.skip("no symlinks here (Windows without the privilege)")
    names = {f.name for _, f in classes.home_files(cfg=config.Config(None, brain_home))}
    assert "private.txt" not in names and "to-token" not in names and "token" not in names


def test_the_probe_measures_the_home_through_the_gate(brain_home):
    from brain import probe

    _home(brain_home)
    (brain_home / "secrets" / "stack" / "big.env").write_bytes(b"0" * 10_000)
    out = probe.probe_disk()["brain_home"]
    assert out["complete"] and 6 <= out["bytes"] < 10_000   # ledger, usage and stray; the secrets never walked
