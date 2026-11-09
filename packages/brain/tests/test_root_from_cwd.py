"""wi-brain-root-from-cwd: --project P resolves to the worktree the cwd is in, when it is a worktree of P's repo."""
import types

from brain import cli, projects

from conftest import run_git


def _repo(path):
    path.mkdir(parents=True)
    run_git(path, "init", "-q", "-b", "main")
    (path / "f.txt").write_text("x", encoding="utf-8")
    run_git(path, "add", "f.txt")
    run_git(path, "commit", "-q", "-m", "init")
    return path.resolve()


def _setup(tmp_path, monkeypatch):
    main = _repo(tmp_path / "proj")
    code = _repo(tmp_path / "code")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {main.as_posix()}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    run_git(main, "worktree", "add", "-q", "-b", "wt", str(tmp_path / "proj-wt"))
    run_git(code, "worktree", "add", "-q", "-b", "cwt", str(tmp_path / "code-wt"))
    return main, (tmp_path / "proj-wt").resolve(), code, (tmp_path / "code-wt").resolve()


def test_cwd_worktree_of_the_projects_repo(tmp_path, monkeypatch):
    main, wt, code, cwt = _setup(tmp_path, monkeypatch)
    p = projects.get("demo")
    assert projects.cwd_worktree(p, wt) == wt
    (wt / "sub").mkdir()
    assert projects.cwd_worktree(p, wt / "sub") == wt  # a sub-folder resolves to the worktree's top


def test_cwd_in_other_repo_or_plain_checkout_keeps_registry_root(tmp_path, monkeypatch):
    main, wt, code, cwt = _setup(tmp_path, monkeypatch)
    p = projects.get("demo")
    assert projects.cwd_worktree(p, cwt) is None      # a worktree of a code repo
    assert projects.cwd_worktree(p, code) is None
    assert projects.cwd_worktree(p, main) is None     # the project's own checkout
    plain = tmp_path / "plain"
    plain.mkdir()
    assert projects.cwd_worktree(p, plain) is None


def _dispatch(monkeypatch, argv, cwd):
    seen = {}
    stub = types.SimpleNamespace(run=lambda args, root: seen.setdefault("root", root) and 0)
    monkeypatch.setattr(cli.registry, "owner", lambda cmd: stub)
    monkeypatch.chdir(cwd)
    args = cli.build_parser().parse_args(argv)
    cli._dispatch(args)
    return seen["root"]


def test_dispatch_uses_worktree_unless_root_is_explicit(tmp_path, monkeypatch):
    main, wt, code, cwt = _setup(tmp_path, monkeypatch)
    assert _dispatch(monkeypatch, ["--project", "demo", "status"], wt) == wt
    assert _dispatch(monkeypatch, ["--project", "demo", "status"], cwt) == main
    assert _dispatch(monkeypatch, ["--project", "demo", "status"], tmp_path) == main
    assert _dispatch(monkeypatch, ["--project", "demo", "--root", str(code), "status"], wt) == code.resolve()
