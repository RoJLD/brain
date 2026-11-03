"""The stranger test (wi-brain-stranger-install-test): install the brain from the public repo into a fresh venv, as
someone who has never seen its author's machine would, then run the Lite scenario; its verdict is a pilot's go.

    python stranger_test.py [--ref v0.2.1 | --source DIR] [--pre-tag] [--deny people:NAME ...] [--work DIR] [--keep]
                            [--json]

Standard library only, on Windows, Linux or macOS (a container: ``docker run --rm -v <this folder>:/t:ro python:3.12
python /t/stranger_test.py``; Docker is the harness there, never something the brain needs):

- **Isolated.** A new folder with its own home (HOME, USERPROFILE), BRAIN_HOME, Claude config folder and git config;
  no BRAIN_* or CLAUDE_BRAIN_DIR variable of the caller's; a PATH reduced to the venv, git, bash and the system folder,
  so no ``docker`` is reachable. The only network is pip's: the package index, and GitHub for the source.
- **Installed as the docs say.** ``pip install "brain @ git+https://github.com/RoJLD/brain.git@REF#subdirectory=
  packages/brain"``, which brings research-graph at the tag it pins. ``--pre-tag`` (a branch before its tag exists):
  research-graph from the same ref first, then brain with ``--no-deps`` and its plain dependencies. ``--source DIR``
  installs a local checkout instead (a dry run of the harness, not the go).
- **The Lite scenario**, as an invented owner (Ada Example): brain init (plan, then apply), git init and the first
  commit, brain check, brain profile, an item, a decision, a journal line, brain refresh --on-main, brain status,
  brain queue, the cockpit's first screen (brain tui --once), brain boundary --check, a help text (the owner's name,
  never the author's), and the hooks the local marketplace ships: the rules injected at SessionStart and the guard
  refusing ``gh repo create --public``.
- **Checked.** Every step exits 0 (the guard's refusal is its expected output); the queue and the rules carry the
  owner's name; no traceback; and no term of ``--deny`` (``category:term``, e.g. the author's name: they are read
  from the caller's arguments, never written in this file) in any output or in the brain's files.

Exit code 0 on a go, 1 when a check fails, 2 when the install fails. ``--json`` prints the report; it is also
written to ``<work>/report.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO = "https://github.com/RoJLD/brain.git"
OWNER = "Ada Example"
EMAIL = "ada@example.invalid"
PLAIN_DEPS = ["pyyaml>=6", "tomli>=2; python_version < '3.11'"]


def run(cmd: list[str], env: dict, cwd: Path, stdin: str | None = None, timeout: float = 600) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, input=stdin, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{cmd[0]}: {exc}"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def git_bash() -> str:
    """The bash that runs the hooks, as Claude Code's: on Windows, Git for Windows' (a bare ``bash`` there starts
    WSL's System32 bash.exe, found before the PATH), else the PATH's."""
    if os.name != "nt":
        return shutil.which("bash") or "bash"
    git = shutil.which("git")
    candidates = [Path(git).parent.parent / "bin" / "bash.exe"] if git else []
    candidates += [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"]
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        candidates.insert(0, Path(found))
    return next((str(c) for c in candidates if c.is_file()), "bash")


def isolated_env(work: Path, scripts: Path) -> dict:
    """The environment of a stranger: a home of its own, nothing of the caller's brain, no docker on the PATH."""
    home = work / "home"
    home.mkdir(parents=True, exist_ok=True)
    gitconfig = home / ".gitconfig"
    gitconfig.write_text(f"[user]\n\tname = {OWNER}\n\temail = {EMAIL}\n[init]\n\tdefaultBranch = main\n"
                         "[commit]\n\tgpgsign = false\n[core]\n\tautocrlf = false\n", encoding="utf-8")
    keep = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL", "TZ",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS")
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    folders = [str(scripts)]
    for found in (shutil.which("git"), git_bash()):
        if found:
            folders.append(str(Path(found).parent))
    if os.name == "nt":
        folders.append(os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32"))
    else:
        folders += ["/usr/bin", "/bin"]
    env.update({"HOME": str(home), "USERPROFILE": str(home), "BRAIN_HOME": str(home / ".brain"),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"), "GIT_CONFIG_GLOBAL": str(gitconfig),
                "GIT_CONFIG_NOSYSTEM": "1", "BRAIN_NOTIFY": "off", "PYTHONUTF8": "1",
                "PATH": os.pathsep.join(dict.fromkeys(folders))})
    return env


def install(work: Path, ref: str, source: str, pre_tag: bool) -> tuple[Path, list[dict]]:
    """A fresh venv in ``work/venv`` with the brain installed; (its scripts folder, the install steps)."""
    target = work / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(target)
    scripts = target / ("Scripts" if os.name == "nt" else "bin")
    py = str(scripts / ("python.exe" if os.name == "nt" else "python"))
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1")
    if source:
        plan = [[py, "-m", "pip", "install", "-q", str(Path(source))],
                [py, "-m", "pip", "install", "-q", "--no-deps", str(Path(source) / "packages" / "brain")],
                [py, "-m", "pip", "install", "-q", *PLAIN_DEPS]]
    elif pre_tag:
        plan = [[py, "-m", "pip", "install", "-q", f"research-graph @ git+{REPO}@{ref}"],
                [py, "-m", "pip", "install", "-q", "--no-deps",
                 f"brain @ git+{REPO}@{ref}#subdirectory=packages/brain"],
                [py, "-m", "pip", "install", "-q", *PLAIN_DEPS]]
    else:
        plan = [[py, "-m", "pip", "install", "-q", f"brain @ git+{REPO}@{ref}#subdirectory=packages/brain"]]
    steps = []
    for cmd in plan:
        rc, out = run(cmd, env, work, timeout=900)
        steps.append({"step": "install", "cmd": " ".join(cmd[1:]), "rc": rc, "ok": rc == 0, "out": out[-2000:]})
        if rc:
            break
    return scripts, steps


def scenario(work: Path, env: dict, scripts: Path) -> list[dict]:
    """The Lite scenario in ``work/ada-brain``: (step, cmd, rc, ok, out) for each step."""
    brain = str(scripts / ("brain.exe" if os.name == "nt" else "brain"))
    py = str(scripts / ("python.exe" if os.name == "nt" else "python"))
    root = work / "ada-brain"
    root.mkdir(exist_ok=True)
    plugin = root / "plugins" / "brain-core"
    hook_env = dict(env, CLAUDE_PLUGIN_ROOT=str(plugin), CLAUDE_PROJECT_DIR=str(root), BRAIN_PYTHON=py)
    session = json.dumps({"session_id": "stranger", "hook_event_name": "SessionStart", "source": "startup",
                          "cwd": str(root)})
    push = json.dumps({"session_id": "stranger", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": "gh repo create my-brain --public"}, "cwd": str(root)})
    steps = [
        ("version", [brain, "--version"], None, lambda o: o.startswith("brain ")),
        ("init plan", [brain, "init", "--owner", OWNER], None, lambda o: "plan only" in o and "template generic" in o),
        ("init apply", [brain, "init", "--owner", OWNER, "--apply"], None, lambda o: "claude plugin install" in o),
        ("git init", ["git", "init", "-q"], None, None),
        ("git add", ["git", "add", "-A"], None, None),
        ("first commit", ["git", "commit", "-q", "-m", "my brain"], None, None),
        ("check", [brain, "check"], None, lambda o: "graph-check OK" in o and "public scan green" in o),
        ("profile", [brain, "profile"], None, lambda o: "lite" in o),
        ("item", [brain, "item", "add", "wi-first", "--title", "My first item", "--priority", "P1", "--reason",
                  "the pilot's first step"], None, lambda o: "wi-first" in o),
        ("decision", [brain, "decision", "ask", "--title", "Pick a name", "--question", "Which name for the project?",
                      "--option", "Orion: short and free", "--option", "Atlas: taken elsewhere", "--why",
                      "short and free", "--no-notify"], None, lambda o: f"{OWNER} answers" in o),
        ("journal", [brain, "journal", "add", "--title", "First day", "Installed the brain and tried it."], None,
         None),
        ("refresh", [brain, "refresh", "--on-main"], None, lambda o: "0 project(s) failed" in o),
        ("status", [brain, "status"], None, lambda o: f"waiting on {OWNER}" in o),
        ("queue", [brain, "queue"], None, lambda o: f"waiting on {OWNER}" in o and "Pick a name" in o),
        ("cockpit", [brain, "tui", "--once"], None, lambda o: f"{OWNER}'s queue" in o and "wi-first" in o),
        ("boundary", [brain, "boundary", "--check"], None, None),
        ("help", [brain, "decision", "answer", "--help"], None, lambda o: f"{OWNER}'s own answer" in o),
        ("hook rules", [git_bash(), str(plugin / "hooks" / "inject-rules.sh"), "SessionStart"], session,
         lambda o: f"{OWNER}'s rules" in o),
        ("hook guard", [git_bash(), str(plugin / "hooks" / "guard.sh"), "shell"], push,
         lambda o: '"deny"' in o or "refused" in o.lower()),
    ]
    out = []
    for name, cmd, stdin, ok in steps:
        rc, text = run(cmd, hook_env if name.startswith("hook") else env, root, stdin)
        good = rc == 0 and "Traceback" not in text and (ok is None or bool(ok(text)))
        out.append({"step": name, "cmd": " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd)),
                    "rc": rc, "ok": good, "out": text[-4000:]})
    return out


def leaks(texts: dict[str, str], deny: list[tuple[str, str]]) -> list[dict]:
    """Each denied term found, whole word and case-insensitive, in the outputs and files given ({where: text})."""
    found = []
    for cat, term in deny:
        rx = re.compile(rf"(?i)(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])")
        for where, text in texts.items():
            if rx.search(text):
                found.append({"category": cat, "term": term, "where": where})
    return found


def brain_files(root: Path) -> dict[str, str]:
    out = {}
    for f in root.rglob("*"):
        if f.is_file() and ".git" not in f.relative_to(root).parts:
            try:
                out[f.relative_to(root).as_posix()] = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    return out


def parse_deny(values: list[str]) -> list[tuple[str, str]]:
    out = []
    for v in values:
        cat, sep, term = v.partition(":")
        if not sep or not term.strip():
            raise SystemExit(f"--deny {v!r}: category:term, e.g. people:Name")
        out.append((cat.strip(), term.strip()))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", default="v0.2.1", help="the tag (or, with --pre-tag, the branch) to install")
    ap.add_argument("--source", help="install this local checkout of the repo instead (a dry run of the harness)")
    ap.add_argument("--pre-tag", action="store_true", help="research-graph from --ref, then brain with --no-deps")
    ap.add_argument("--deny", action="append", default=[], help="category:term that must appear nowhere")
    ap.add_argument("--work", help="the folder to work in (default: a new temporary one)")
    ap.add_argument("--keep", action="store_true", help="keep the work folder")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    deny = parse_deny(args.deny)
    work = Path(args.work or tempfile.mkdtemp(prefix="stranger-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    scripts, steps = install(work, args.ref, str(Path(args.source).resolve()) if args.source else "", args.pre_tag)
    report = {"ref": args.source or args.ref, "pre_tag": args.pre_tag, "platform": sys.platform,
              "python": sys.version.split()[0], "work": str(work), "steps": steps, "leaks": []}
    if all(s["ok"] for s in steps):
        env = isolated_env(work, scripts)
        report["docker_on_path"] = bool(shutil.which("docker", path=env["PATH"]))
        report["steps"] += scenario(work, env, scripts)
        texts = {f"output of {s['step']}": s["out"] for s in report["steps"]}
        texts.update(brain_files(work / "ada-brain"))
        report["leaks"] = leaks(texts, deny)
    failed = [s for s in report["steps"] if not s["ok"]]
    installed = all(s["ok"] for s in steps)
    report["verdict"] = "go" if installed and not failed and not report["leaks"] and \
        not report.get("docker_on_path") else "no-go"
    (work / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    else:
        print(f"stranger test: {report['ref']}{' (pre-tag)' if args.pre_tag else ''} on {sys.platform}, Python "
              f"{report['python']}, in {work}")
        for s in report["steps"]:
            print(f"  {'ok  ' if s['ok'] else 'FAIL'} {s['step']:<12} rc {s['rc']}  {s['cmd']}")
            if not s["ok"]:
                print("       " + "\n       ".join(s["out"].strip().splitlines()[-12:]))
        if report.get("docker_on_path"):
            print("  FAIL docker is on the reduced PATH")
        for lk in report["leaks"]:
            print(f"  LEAK {lk['category']} term {lk['term']!r} in {lk['where']}")
        print(f"verdict: {report['verdict']} (report: {work / 'report.json'})")
    if not args.keep and not args.work and report["verdict"] == "go":
        shutil.rmtree(work, ignore_errors=True)
    return 2 if not installed else 0 if report["verdict"] == "go" else 1


if __name__ == "__main__":
    sys.exit(main())
