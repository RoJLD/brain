# xerj's answers, as recorded

What `packages/brain/tests/test_xerj.py` feeds `packages/brain/src/brain/xerj.py` in place of a running xerj
(wi-brain-code-index-xerj-backend; no network, no xerj binary in CI); `fake_xerj.py` is the stand-in binary. Every
answer is read from xerj's public repository (`xerj-org/xerj`, Apache-2.0) at commit
`53e4db0c1f90abe71ff13520063b89cc84d51fa8` (2026-11-23), never written by the engine: verbatim where the table says
so, else transcribed from xerj's source, with the place named.

| What | What it is | Where it comes from |
|---|---|---|
| `autoindex-completed.txt` | the terminal line of a finished `xerj autoindex` (exit 3, completed with junk) | verbatim: `benchmarks/autoindex-resilience/limits-real-node.txt`, its control run |
| `autoindex-aborted.txt` | a run the node refused (exit 1, `ok=false`): its notice, terminal line and error | verbatim: the same file, its `max_body_bytes = 65536` run |
| `autoindex-refused.txt` | a run whose one dataset the node refused, the rest indexed (exit 3, finished; it held no code file: `code_files=0`) | verbatim: `content/answers/autoindex-exit-codes.md` |
| `search.json` | `xerj search --json`'s answer: Elasticsearch's hits after xerj's pass (`match_line`, `_passage`, `_xerj`) | transcribed: `engine/crates/xerj-autoindex/src/search.rs` (its tests' hit shapes, `attach_embed_mode`, the `--json` path), `scripts/mcp-search-contract-smoke.py` (`match_line` on the hit); `_index` is `<prefix>-docs` as autoindex names it (`ax-docs` in xerj's tests, for its default prefix `ax`) |
| `fake_xerj.py`, `--detach` | the banner of a detached start, its `(pid N)` read by the engine | transcribed: `engine/crates/xerj-server/src/main.rs`, `run_detached` |
| `fake_xerj.py`, a search that fails | `xerj search: query failed against <url>/<prefix>-*: <error>`, exit 1 | transcribed: `search.rs`, `query_failure_message`; the error after it (`connection refused`) is the client's, an example |
| `fake_xerj.py`, a start that fails | `error: <the OS error>`, exit 1 | `main.rs` prints `error:` and the failure; the OS error (`Address already in use`) is an example |
| `test_xerj.py`, `node.lock` | a bare pid as text (`node.lock.pid` while the lock is held) | `engine/crates/xerj-common/src/nodedir.rs`, `lock_pid`; its tests write `4242` the same way |

`search.json` is the main transcription: no live capture was made on this machine (the owner decides when xerj runs
here). The first run of the code bench's second stage captures a real answer (`xerj search --json`, the same flags as
`brain.xerj.search`) and replaces it.
