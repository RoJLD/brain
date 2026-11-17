"""The engine's own CI workflows (wi-brain-harness-negative-controls): a step that writes a command substitution to
GITHUB_OUTPUT tests first that it is not empty. An empty output is no error to the shell: compat-prev once found no
tag and went on, green, testing nothing (the skeptic review of brain #52). This checks the engine's .github/workflows
only, so no user repository is newly refused."""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"

SUBST = re.compile(r"\$\(|`")
OUTPUT = re.compile(r"(?:>>|\btee\s+-a)\s*\"?\$(?:env:)?\{?GITHUB_OUTPUT\b")
ASSIGN = re.compile(r"^\s*(?:export\s+|local\s+|readonly\s+)?([A-Za-z_]\w*)=(.*)$")
VAR = re.compile(r"\$\{?([A-Za-z_]\w*)")


def checked_nonempty(var: str, lines: list[str]) -> bool:
    """A test, in ``lines``, that ``var`` is not empty: test -n / [ -n ] / [[ -n ]], test -z (or [ -z ]) followed by
    an exit or ||, or ${var:?}."""
    v = rf"\"?\$\{{?{var}\}}?\"?"
    nonempty = re.compile(rf"(?:\btest|\[\[?)\s+-n\s+{v}")
    empty = re.compile(rf"(?:\btest|\[\[?)\s+-z\s+{v}.*(?:\bexit\b|\|\|)")
    required = re.compile(rf"\$\{{{var}:\?")
    return any(nonempty.search(x) or empty.search(x) or required.search(x) for x in lines)


def unchecked_outputs(script: str) -> list[str]:
    """Each line of a step's script that writes a command substitution to GITHUB_OUTPUT (directly, or through a
    variable assigned one) with no test before it that the value is not empty."""
    lines = [x for x in script.splitlines() if not x.lstrip().startswith("#")]
    assigned: dict[str, int] = {}          # a variable assigned a command substitution: the line it was
    found = []
    for i, line in enumerate(lines):
        out = OUTPUT.search(line)
        if not out:
            m = ASSIGN.match(line)
            if m and SUBST.search(m.group(2)):
                assigned[m.group(1)] = i
            continue
        written = line[:out.start()]
        if SUBST.search(written):
            found.append(line.strip())
            continue
        if any(v in assigned and not checked_nonempty(v, lines[assigned[v] + 1:i + 1]) for v in VAR.findall(written)):
            found.append(line.strip())
    return found


def workflow_steps(path: Path):
    """(job, step name, run script) of each step of a workflow that runs a script."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for job, spec in (data.get("jobs") or {}).items():
        for i, step in enumerate((spec or {}).get("steps") or []):
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                yield job, step.get("name") or f"step {i + 1}", step["run"]


def test_the_engines_workflows_test_each_substitution_they_output():
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert files, WORKFLOWS
    found = [f"{f.name}: {job} / {name}: {line}" for f in files for job, name, run in workflow_steps(f)
             for line in unchecked_outputs(run)]
    assert not found, "a command substitution written to GITHUB_OUTPUT untested (test -n first):\n" + "\n".join(found)
    # not vacuous: the engine's workflows do write such an output (compat-prev's last tag)
    assert any(OUTPUT.search(run) for f in files for _, _, run in workflow_steps(f))


@pytest.mark.parametrize("script, refused", [
    ('tag=$(git describe --tags)\necho "tag=$tag" >> "$GITHUB_OUTPUT"', True),
    ('tag=$(git describe --tags)\ntest -n "$tag"\necho "tag=$tag" >> "$GITHUB_OUTPUT"', False),
    ('tag=`git describe`\n[ -n "$tag" ] || exit 1\necho "tag=${tag}" >> $GITHUB_OUTPUT', False),
    ('tag=$(git describe)\n[ -z "$tag" ] && exit 1\necho "tag=$tag" >> "$GITHUB_OUTPUT"', False),
    ('tag=$(git describe)\necho "tag=${tag:?no tag}" >> "$GITHUB_OUTPUT"', False),
    ('echo "tag=$(git describe --tags)" >> "$GITHUB_OUTPUT"', True),
    ('tag=$(git describe)\ntest -n "$other"\necho "tag=$tag" >> "$GITHUB_OUTPUT"', True),
    ('echo "tag=$tag"\ntag=$(git describe)\n# test -n "$tag"\necho "tag=$tag" >> "$GITHUB_OUTPUT"', True),
    ('echo "run=true" >> "$GITHUB_OUTPUT"', False),
    ('echo "tag=$(git describe)" | tee -a "$GITHUB_OUTPUT"', True),
    ('"tag=$(git describe)" >> $env:GITHUB_OUTPUT', True),
    ('name=${{ github.ref_name }}\necho "name=$name" >> "$GITHUB_OUTPUT"', False),
])
def test_a_substitution_written_untested_is_refused(script, refused):
    assert bool(unchecked_outputs(script)) is refused, script


def test_compat_prev_without_its_guard_is_refused():
    """The negative control on the real workflow: ci.yml's last-tag step with its ``test -n "$tag"`` line removed is
    the check's finding."""
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    unguarded, n = re.subn(r'^[ \t]*test -n "\$tag"\r?\n', "", text, flags=re.M)
    assert n == 1
    runs = [s["run"] for spec in yaml.safe_load(unguarded)["jobs"].values() for s in spec.get("steps", [])
            if "GITHUB_OUTPUT" in str(s.get("run", ""))]
    assert runs and any(unchecked_outputs(r) for r in runs)


def _commands(script: str) -> list[list[str]]:
    """A step's commands as words, its comments left out (a line's own ``#`` and what follows a `` #``)."""
    out = []
    for line in script.splitlines():
        words = []
        for w in line.split():
            if w.startswith("#"):
                break
            words.append(w)
        if words:
            out.append(words)
    return out


def _runs_suite(words: list[str], cwd: str) -> bool:
    """``pytest`` over the brain command's whole suite: packages/brain from the root, or tests (or .) in
    packages/brain, whatever options come first; one file, or the docker-only run (``-m docker``), is not it."""
    if "pytest" not in words:   # pytest ..., or python -m pytest ...
        return False
    args = words[words.index("pytest") + 1:]
    if any(a == "-m" and b.strip("'\"") == "docker" for a, b in zip(args, args[1:], strict=False)):
        return False
    paths = {a.rstrip("/") for a in args if not a.startswith("-")}
    return "packages/brain" in paths or (cwd.rstrip("/") == "packages/brain" and bool(paths & {"tests", "."}))


def suite_jobs_without_textual(data: dict) -> list[str]:
    """The jobs with a step that runs the brain command's suite and no step before it that installs Textual: there
    the cockpit's tests (test_tui*.py, ``pytest.importorskip("textual")``) are skipped, unseen, and the coverage
    counts none of them. A commented-out install is none; the working directory is the step's, else the job's
    ``defaults.run``."""
    missing = []
    for job, spec in (data.get("jobs") or {}).items():
        spec = spec or {}
        home = ((spec.get("defaults") or {}).get("run") or {}).get("working-directory") or ""
        installed = False
        for s in spec.get("steps") or []:
            if not (isinstance(s, dict) and isinstance(s.get("run"), str)):
                continue
            cmds = _commands(s["run"])
            if any(_runs_suite(c, s.get("working-directory") or home) for c in cmds) and not installed:
                missing.append(job)
                break
            installed = installed or any("install" in c and any(w.strip("'\"").startswith("textual") for w in c)
                                         for c in cmds)
    return missing


def test_the_jobs_that_run_the_brain_suite_install_textual():
    """The cockpit's tests ran nowhere while the CI lacked Textual: three of them broke unseen (a sort and three
    columns added to the frontier) and brain audit measured tui*.py at 0 % (wi-brain-engine-debt, batch 2)."""
    data = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    assert suite_jobs_without_textual(data) == []
    assert {"brain", "brain-linux"} <= {j for j, s in data["jobs"].items()   # the guard sees their suite
                                        if any(_runs_suite(c, x.get("working-directory") or "")
                                               for x in s.get("steps", []) for c in _commands(x.get("run") or ""))}


def test_a_suite_job_without_textual_is_named():
    def job(*steps, **spec):
        return {"jobs": {"a": {"steps": [s if isinstance(s, dict) else {"run": s} for s in steps], **spec}}}

    install = 'pip install pyyaml pytest\npip install "textual>=8,<9" psutil'
    suite = {"run": "pytest tests -n auto", "working-directory": "packages/brain"}
    assert suite_jobs_without_textual(job("pip install pyyaml pytest", suite)) == ["a"]
    assert suite_jobs_without_textual(job(install, suite)) == []
    assert suite_jobs_without_textual(job("pip install pytest  # pip install textual", suite)) == ["a"]  # a comment
    assert suite_jobs_without_textual(job("# pip install textual", suite)) == ["a"]
    assert suite_jobs_without_textual(job(suite, install)) == ["a"]   # installed after the suite ran
    assert suite_jobs_without_textual(job("pip install pytest", "pytest tests -n auto",
                                          defaults={"run": {"working-directory": "packages/brain"}})) == ["a"]
    for run in ("pytest -n auto packages/brain", "pytest packages/brain/ -q", "python -m pytest packages/brain"):
        assert suite_jobs_without_textual(job("pip install pytest", run)) == ["a"], run
    for run in ("pytest packages/brain -m docker", "pytest packages/brain -m 'docker'",
                "pytest packages/brain/tests/test_x.py", "pytest"):   # docker only, one file, the root's suite
        assert suite_jobs_without_textual(job("pip install pytest", run)) == [], run
