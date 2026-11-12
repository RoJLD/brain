"""The old-store fixture (wi-brain-old-store-fixture; spec-brain-waves-retro 4, spec-brain-data-compat N8): a brain as
a released engine wrote it, frozen in the engine's tests, so that every store-reading command of this checkout is
tested on a store it did not write itself.

    python packages/brain/installer/freeze_store.py TAG [--source DIR] [--out DIR] [--work DIR] [--keep] [--force]
                                                    [--only-formats] [--reuse] [--formats-out DIR]

TAG (``v0.3.1``) is installed from the public repo into a fresh venv and an isolated home (the stranger test's,
:mod:`stranger_test`); ``--source DIR`` installs a checkout instead (a dry run, frozen under TAG all the same). As an
invented owner (Ada Example), that engine writes an owner-shaped brain through its own commands: brain init, the
first commit, a milestone, three items (one depending on another, one closed), a decision, a journal line, a lesson,
an AR, an SR from the transcript fixture and the generated views (brain refresh --on-main), then its own brain check.
A command the engine does not have, or refuses (a lesson before the Lesson type), is recorded and skipped: the store
is what that engine could write. The brain's files (``.git`` and the ledger left out) are copied to
``tests/fixtures/stores/<TAG>/brain/``, with ``freeze.json`` beside them: the tag, the engine's version, and each step
with its exit code.

A frozen store is never edited: ``tests/test_old_stores.py`` copies it, commits it and runs this checkout's check,
sync, item, lesson and retro on it, strict. The version PR adds the last tag's store (docs/release.md, « The fixture
freeze »); an existing folder is refused unless ``--force``. The engine is public, and a fixture names no machine of
anyone's: this machine's user and host names, which brain init writes into ``public.deny``, are replaced by invented
ones (``host-a``, ``ada-l``, :data:`INVENTED`; the files listed in freeze.json's ``neutralized``), and a store that
still names one, the work folder or this checkout (an absolute path of this machine), is refused.

**Each format's file** (wi-brain-format-fixture-freeze) is frozen too, as that engine wrote it, neutralized the same
way: ``tests/fixtures/formats/<format>/v<N>/<TAG>.<ext>`` (N the ``v`` the file states), from the brain (ar, config,
ddr, sr, projects, packs), the engine's ledger (event, its first :data:`LINES` lines) and the engine's own template
manifest; ``tests/test_formats_frozen.py`` reads each one strict. A format no command writes (permissions, members,
readme, modules, standards) is skipped, and so is the status document (:data:`MACHINE_FORMATS`: brain doctor --json
prints this machine's inventory). One already frozen is kept unless ``--force``. ``--only-formats`` freezes them
alone, the store untouched; ``--reuse`` (with ``--work``) takes the engine and the brain a previous freeze kept there,
nothing installed.

Exit code 0 when frozen, 1 when a step the store needs failed (init, the first commit, the engine's own check) or the
store names the work folder or a machine term, 2 when the install fails.
"""

from __future__ import annotations

import argparse
import ast
import getpass
import importlib.util
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from pathlib import Path


def _harness():
    """The stranger test beside this file (install, isolated_env, run_steps), whoever loads this one."""
    spec = importlib.util.spec_from_file_location("stranger_test", Path(__file__).resolve().with_name("stranger_test.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


st = _harness()
STORES = st.FIXTURES / "stores"
FORMATS_OUT = st.FORMATS   # where each format's file is frozen (the registry stays st.FORMATS: st.formats())
NEEDED = ("init apply", "git init", "first commit", "check")   # without these there is no store to freeze
LEFT_OUT = (".git",)
INVENTED = {"hosts": "host-a", "users": "ada-l"}   # in the place of this machine's names (as tests/test_init.py)
CHECKOUT = st.FIXTURES.parents[3]                   # this checkout: a step names its fixtures (the SR's transcript)


def common_names() -> set[str]:
    """brain.init.COMMON_NAMES, read from this checkout's source without importing brain (this script runs on the
    standard library): the names init never denies, so never replaced here either ('root' in projects.yaml)."""
    tree = ast.parse((CHECKOUT / "packages" / "brain" / "src" / "brain" / "init.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COMMON_NAMES"
                                                for t in node.targets):
            return {str(x).lower() for x in ast.literal_eval(node.value)}
    raise SystemExit("freeze: brain.init.COMMON_NAMES not found: the rule of brain init's machine terms moved")


def steps(brain: str) -> list[tuple]:
    """The owner-shaped brain's steps, as (name, cmd, stdin, check) for :func:`stranger_test.run_steps`. Each writes
    through a command of the engine being frozen; one it lacks or refuses is recorded, not fatal (:data:`NEEDED`)."""
    git = ["git", "add", "-A"]
    return [
        ("version", [brain, "--version"], None, lambda o: o.startswith("brain ")),
        ("init apply", [brain, "init", "--owner", st.OWNER, "--apply"], None, None),
        ("git init", ["git", "init", "-q"], None, None),
        ("git add", git, None, None),
        ("first commit", ["git", "commit", "-q", "-m", "my brain"], None, None),
        ("milestone", [brain, "item", "add", "ms-first-release", "--type", "Milestone", "--status", "pending",
                       "--title", "The first release", "--prop", "trigger=the first two items done"], None, None),
        ("item", [brain, "item", "add", "wi-first", "--title", "Write the first page", "--priority", "P1",
                  "--reason", "the first step", "--milestone", "ms-first-release"], None, None),
        ("item after", [brain, "item", "add", "wi-second", "--title", "Review the first page", "--priority", "P2",
                        "--after", "wi-first", "--milestone", "ms-first-release"], None, None),
        ("item idea", [brain, "item", "add", "wi-later", "--title", "An idea for later",
                       "--idea", "Ada, a first brainstorm"], None, None),
        ("close", [brain, "item", "close", "wi-first", "--pr", "ada/brain #1", "--outcome",
                   "the first page written and read"], None, None),
        ("decision", [brain, "decision", "ask", "--title", "Pick a colour", "--question", "Which colour?",
                      "--option", "Teal: calm", "--option", "Red: loud", "--why", "calm", "--no-notify"], None, None),
        ("journal", [brain, "journal", "add", "--title", "First day", "Installed the brain and tried it."], None,
         None),
        ("lesson", [brain, "lesson", "add", "les-ada-first-page", "--title", "Read the page before closing it",
                    "--trigger", "closing an item", "--anti-pattern", "closed without reading the page",
                    "--check", "a reviewer reads it", "--from", "wi-first"], None, None),
        ("ar", [brain, "record", "ar", "--kind", "commit", "--repo", "ada/brain", "--sha", "0123456789abcdef",
                "--subject", "my brain", "--session", st.SESSION], None, None),
        ("sr", [brain, "record", "sr", "--transcript", str(st.FIXTURES / "transcript.jsonl"), "--session",
                st.SESSION, "--summary", "a first session", "--closed"], None, None),
        ("refresh", [brain, "refresh", "--on-main"], None, None),
        ("git add", git, None, None),
        ("commit", ["git", "commit", "-q", "-m", "a first week"], None, None),
        ("check", [brain, "check"], None, lambda o: "graph-check OK" in o),
    ]


def files(root: Path) -> list[Path]:
    return sorted(f for f in root.rglob("*") if f.is_file() and not set(f.relative_to(root).parts) & set(LEFT_OUT))


def machine() -> dict[str, str]:
    """This machine's names that brain init writes into public.deny (brain.init.machine_terms: its user and host, at
    least 3 characters and none of :func:`common_names`), each with the invented name a fixture holds in its place."""
    try:
        user = getpass.getuser()
    except Exception:   # no user name in this environment: nothing to replace
        user = ""
    host = socket.gethostname().split(".")[0]
    common = common_names()
    return {term: invented for term, invented in ((host, INVENTED["hosts"]), (user, INVENTED["users"]))
            if len(term) >= 3 and term.lower() not in common}


def places_of(work: Path) -> set[str]:
    """The absolute paths of this machine a store may not name, lower-cased: the work folder and this checkout (a
    step reads its fixtures), each as Windows and POSIX text, JSON-escaped and as a file URI."""
    out = set()
    for p in (work, CHECKOUT):
        p = p.resolve()
        out |= {str(p), p.as_posix(), str(p).replace("\\", "\\\\"), p.as_uri()}
    return {n.lower() for n in out}


def _term(term: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])", re.I)


def neutralize(root: Path, terms: dict[str, str]) -> list[str]:
    """Each machine term replaced by its invented name in the store's text files, bytes otherwise kept (a fixture
    names no host or user of anyone's: the engine is public); the files changed."""
    out = []
    for f in files(root):
        try:
            text = f.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        new = text
        for term, invented in terms.items():
            new = _term(term).sub(invented, new)
        if new != text:
            f.write_bytes(new.encode("utf-8"))
            out.append(f.relative_to(root).as_posix())
    return out


def named(root: Path, work: Path, terms: dict[str, str] | None = None) -> list[str]:
    """The store's files that name the work folder or this checkout (:func:`places_of`, whatever the case) or a machine
    term: never frozen."""
    needles = places_of(work)
    out = []
    for f in files(root):
        text = f.read_text(encoding="utf-8", errors="replace")
        if any(n in text.lower() for n in needles) or any(_term(t).search(text) for t in terms or {}):
            out.append(f.relative_to(root).as_posix())
    return out


def freeze(root: Path, dest: Path, report: dict) -> int:
    """Copy the brain (:data:`LEFT_OUT` aside) to ``dest/brain`` and write ``dest/freeze.json``; the file count."""
    if dest.exists():
        shutil.rmtree(dest)
    target = dest / "brain"
    for f in files(root):
        out = target / f.relative_to(root)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(f.read_bytes())
    (dest / "freeze.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                                      newline="\n")
    return len(files(target))


def show(ran: list[dict]) -> None:
    for s in ran:
        mark = "ok  " if s["ok"] else "FAIL" if s["step"] in NEEDED or s["step"] == "install" else "skip"
        print(f"  {mark} {s['step']:<12} rc {s['rc']}  {s['cmd']}")


def refusals(ran: list[dict], root: Path, work: Path, terms: dict[str, str]) -> list[str]:
    """Why the store is not frozen: a step it needs failed (:data:`NEEDED`), or a file names the work folder or a
    machine term still."""
    out = [f"{s['step']} failed:\n" + "\n".join(s["out"].strip().splitlines()[-12:])
           for s in ran if s["step"] in NEEDED and not s["ok"]]
    leaked = named(root, work, terms)
    if leaked:
        out.append("these files name the work folder or this machine, an absolute path or a name of this "
                   "machine's: " + ", ".join(leaked))
    return out


def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tag", help="the released engine that writes the store, e.g. v0.3.1")
    ap.add_argument("--source", help="install this checkout instead of the tag (a dry run, frozen under TAG)")
    ap.add_argument("--out", help=f"the stores folder (default: {STORES})")
    ap.add_argument("--work", help="the folder to work in (default: a new temporary one)")
    ap.add_argument("--keep", action="store_true", help="keep the work folder")
    ap.add_argument("--force", action="store_true", help="replace a store, and format files, already frozen under TAG")
    ap.add_argument("--only-formats", action="store_true",
                    help="freeze each format's file only (tests/fixtures/formats/<format>/v<N>/<TAG>.<ext>), not the "
                         "store")
    ap.add_argument("--reuse", action="store_true",
                    help="with --work: the engine and the brain a previous freeze left there, nothing installed")
    ap.add_argument("--formats-out", help=f"the formats folder (default: {FORMATS_OUT})")
    args = ap.parse_args(argv)
    if args.reuse and not args.work:
        ap.error("--reuse: with --work, the folder of a previous freeze")
    if not args.tag.strip():
        ap.error("TAG: empty")
    return args


def installed(work: Path, tag: str, source: str) -> Path | None:
    """The engine installed in ``work/venv``: its scripts folder, or None (the failure printed)."""
    scripts, inst = st.install(work, tag, source, False)
    show(inst)
    if all(s["ok"] for s in inst):
        return scripts
    print("\n".join(inst[-1]["out"].strip().splitlines()[-12:]), file=sys.stderr)
    return None


def prepared(args, work: Path, source: str) -> tuple[Path, list[dict]] | int:
    """(the engine's scripts folder, the steps run) in ``work``: the tag installed and the brain written, or, with
    --reuse, those a previous freeze left there (``work/venv``, ``work/ada-brain``); an exit code on a failure."""
    if args.reuse:
        scripts = work / "venv" / ("Scripts" if os.name == "nt" else "bin")
        if not (scripts.is_dir() and (work / "ada-brain" / "config.json").is_file()):
            print(f"freeze: --reuse: no engine and brain of a previous freeze in {work}", file=sys.stderr)
            return 2
        return scripts, []
    scripts = installed(work, args.tag, source)
    if scripts is None:
        return 2
    root = work / "ada-brain"
    root.mkdir(exist_ok=True)
    ran = st.run_steps(steps(st._exe(scripts, "brain")), st.isolated_env(work, scripts), root)
    show(ran)
    return scripts, ran


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    dest = Path(args.out or STORES) / args.tag
    if not args.only_formats and dest.exists() and not args.force:
        print(f"freeze: {dest} exists: a frozen store is never edited (--force replaces it)", file=sys.stderr)
        return 1
    work = Path(args.work or tempfile.mkdtemp(prefix="freeze-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = str(Path(args.source).resolve()) if args.source else ""
    got = prepared(args, work, source)
    if isinstance(got, int):
        return got
    scripts, ran = got
    root, terms = work / "ada-brain", machine()
    replaced = neutralize(root, terms)
    if any_refused(refusals(ran, root, work, terms), work):
        return 1
    done = freeze_formats(args.tag, work, scripts, terms, Path(args.formats_out or FORMATS_OUT), args.force)
    if not args.only_formats:
        store(args.tag, root, dest, {**report_of(args.tag, source, ran), "neutralized": replaced})
    if not (args.keep or args.work):
        shutil.rmtree(work, ignore_errors=True)
    return 0 if done else 1


def any_refused(refused: list[str], work: Path) -> bool:
    for why in refused:
        print(f"freeze: {why}", file=sys.stderr)
    if refused:
        print(f"freeze: nothing frozen (the work folder: {work})", file=sys.stderr)
    return bool(refused)


def store(tag: str, root: Path, dest: Path, report: dict) -> None:
    count = freeze(root, dest, report)
    print(f"freeze: {count} file(s) of brain {report['engine'] or '?'} ({tag}) frozen in {dest}")


# --- each format's file, as the tag wrote it (tests/fixtures/formats/<format>/v<N>/<TAG>.<ext>) --------------------

LINES = 5   # a JSONL format's first lines: enough to read, small to keep
V_JSON = re.compile(r'"v"\s*:\s*(\d+)')
V_YAML = re.compile(r"^v:\s*(\d+)\s*$", re.M)


def version_of(text: str) -> int:
    """The ``v`` a format's file states (its first one: a JSONL file's first line), 1 when none."""
    found = [m for m in (V_JSON.search(text), V_YAML.search(text)) if m]
    return int(min(found, key=lambda m: m.start()).group(1)) if found else 1


# Never frozen from a machine: the status document (brain doctor --json) is this machine's inventory (its CPU, GPU,
# memory, host): hand-written fixtures only (tests/fixtures/formats/status/v1/older|newer), never a real one.
MACHINE_FORMATS = ("status",)


def engine_text(fmt: str, root: Path, scripts: Path, env: dict) -> tuple[str, str] | None:
    """(text, extension) of the template manifest the tag's engine ships, the one format no file of the brain holds;
    None for any other, or when that engine has no such file."""
    if fmt != "template":
        return None
    rc, out = st._py(scripts, "import sys; from brain import init\nsys.stdout.write((init.TEMPLATES / "
                     "init.DEFAULT_TEMPLATE / 'template.yaml').read_text(encoding='utf-8'))", env, root)
    return (out, ".yaml") if rc == 0 and out.strip() else None


def format_text(fmt: str, places: dict, root: Path, scripts: Path, env: dict) -> tuple[str, str] | None:
    files = places.get(fmt) or []
    if not files:
        return engine_text(fmt, root, scripts, env)
    f = files[0]
    text = f.read_bytes().decode("utf-8")
    if f.suffix == ".jsonl":
        text = "".join(text.splitlines(keepends=True)[:LINES])
    return text, f.suffix


def freeze_formats(tag: str, work: Path, scripts: Path, terms: dict[str, str], out: Path, force: bool) -> bool:
    """Each registered format's file the tag's engine wrote, neutralized, frozen as ``<out>/<format>/v<N>/<tag><ext>``
    (an existing one kept unless ``force``). A format no command of that engine writes (permissions, members, readme,
    modules, standards: by hand) is skipped and said, and so is :data:`MACHINE_FORMATS`; one that names this machine
    is refused. True when nothing was refused."""
    root, home = work / "ada-brain", work / "home"
    env = st.isolated_env(work, scripts)
    places, needles, refused = st.where(root, home), places_of(work), []
    for fmt, _ in st.formats():
        got = None if fmt in MACHINE_FORMATS else format_text(fmt, places, root, scripts, env)
        if got is None:
            why = "a machine's inventory: never frozen" if fmt in MACHINE_FORMATS else f"no file of it written by {tag}"
            print(f"  skip {fmt:<12} {why}")
            continue
        text, ext = got
        for term, invented in terms.items():
            text = _term(term).sub(invented, text)
        if any(n in text.lower() for n in needles):
            refused.append(fmt)
            print(f"  FAIL {fmt:<12} names this machine (a path): not frozen", file=sys.stderr)
            continue
        dest = out / fmt / f"v{version_of(text)}" / f"{tag}{ext}"
        if dest.exists() and not force:
            print(f"  kept {fmt:<12} {dest.relative_to(out).as_posix()} (frozen already)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(text.encode("utf-8"))
        print(f"  ok   {fmt:<12} {dest.relative_to(out).as_posix()}")
    return not refused


def report_of(tag: str, source: str, ran: list[dict]) -> dict:
    """freeze.json: the tag, the engine's version (from its brain --version), where it came from, each step."""
    version = next((s["out"].split()[1] for s in ran if s["step"] == "version" and s["ok"]), "")
    return {"tag": tag, "engine": version, "source": "checkout" if source else "tag", "owner": st.OWNER,
            "steps": [{"step": s["step"], "rc": s["rc"], "ok": s["ok"]} for s in ran]}


if __name__ == "__main__":
    sys.exit(main())
