# The code index and its backends

`brain index`, `brain code-map`, `brain impact` and `brain health code-index` read the code through one interface
(`brain.codebackends`), which picks a backend for each. Each backend is declared in the tier registry
(`tiers.yaml`: `code-index-gitnexus`, `code-index-cbm`, `code-index-xerj`) with its requirements and its fallback; without any, the
impact is at the file level (every CodeRef of a changed file, a Python symbol's checked by the AST of both sides) and
says why.

| | GitNexus (`gitnexus`) | codebase-memory-mcp (`cbm`) | xerj (`xerj`) |
|---|---|---|---|
| What it is | GitNexus in its container: the stack whose `index:` names it (projects.yaml) | one native binary, run as a stdio MCP server for the time of a command | one native binary, a local search node: the stack whose start is `brain index --backend xerj --serve` |
| Needs | a container runtime (Docker) | its binary under `$BRAIN_HOME/code-index/cbm/bin` | its binary, built from xerj's public main, under `$BRAIN_HOME/code-index/xerj/bin` |
| Serves | index, code-map, impact, health | index, impact, health | index, health, search |
| Its role | the code authority for search, the default | `brain impact` on a worktree; the code index of a machine without Docker | opt-in, never a default: a third arm of the code bench's second stage |
| What it indexes | a snapshot of each repo's branch, in GitNexus's own clone | the checkout itself, in place (no file written into it) | a `git archive` snapshot of each repo's branch head, under `$BRAIN_HOME/code-index/xerj/snapshots` |
| Its record | `$BRAIN_HOME/code-index.json` | `$BRAIN_HOME/code-index/cbm/record.json` | `$BRAIN_HOME/code-index/xerj/record.json` |

How a command picks:

- `brain index`: GitNexus when a stack declares `index:`, else codebase-memory-mcp when it is installed;
  `--backend gitnexus|cbm|xerj` names one. xerj is never chosen unless named.
- The adapter's search (`brain.codebackends.search`, the ranked rows a bench reads): xerj only, named; with no backend
  named it refuses, because GitNexus stays the search authority through its own MCP `query` tool (CBM-1) until the
  code bench's second stage picks one.
- `brain impact`: GitNexus first, codebase-memory-mcp first on a worktree (a checkout other than the main one), each
  the other's fallback when it is there; `--backend` names one. CBM reads a checkout's working tree, so a commit range
  (`--diff A..B`) is never asked of it.
- `brain code-map`: GitNexus only (it resolves each CodeRef through GitNexus's Cypher).
- `brain health code-index`: every backend this machine has; CBM's line also when no repo is declared; xerj's line
  only once it indexed a repo, said and never counted (an opt-in arm: a stale index or a stopped node is normal).

The interface names the kind of artefact it indexes (`code` today): a typology pack may declare another kind of index
(a CAD feature tree, a media index) behind the same four doors.

## codebase-memory-mcp

### Install (the owner)

The release read by the engine is **v0.12.1** (its tool and argument names: `index_repository`, `index_status`,
`list_projects`, `delete_project`, `detect_changes`). The asset `codebase-memory-mcp-windows-amd64.zip`, 48,508,123
bytes, sha256 `4e4e0f16b45233af5c757a1fcbe3c3b16e9056375b1fbe2ce020b6de75dedcc0` (the release's `checksums.txt`
lists it; its cosign bundle `codebase-memory-mcp-windows-amd64.zip.bundle`).

1. Download the zip (and its bundle) into a new empty folder; check the digest before anything runs:

   ```powershell
   (Get-FileHash .\codebase-memory-mcp-windows-amd64.zip -Algorithm SHA256).Hash -eq '4E4E0F16B45233AF5C757A1FCBE3C3B16E9056375B1FBE2CE020B6DE75DEDCC0'
   ```

2. Unzip it to `$BRAIN_HOME\code-index\cbm\bin` (`Unblock-File` on the exe). Nothing else: never its `install` (it
   wires agents and hooks), no service, no scheduled task.
3. `brain index --backend cbm` sets its settings off (below) and prints each declared repo's state; `brain health
   code-index` checks them.

### What the engine keeps off

v0.12.1 starts its HTTP UI (`127.0.0.1:9749`) and a file watcher with any stdio session unless its settings say no,
and can index on its own. Before every session the engine sets `ui_enabled`, `auto_watch`, `watcher_enabled` and
`auto_index` to false (`codebase-memory-mcp config set`, kept in its store) and refuses to go on when one stays on;
`brain health code-index` reads them back (`config list`) and says `UNSAFE` when one is on (a missing one counts as
on: CBM's default). A session ends when the command ends: its input closed, the server ends with its daemon and
index workers; a call past its deadline kills its process tree (`taskkill /T` on Windows), and every later call of
that session fails at once, in one line. The server's last error lines are kept for that line.

### Its store

`CBM_CACHE_DIR` is always `$BRAIN_HOME/code-index/cbm/cache` (the engine sets it for every call): CBM refuses a
second, empty store, so a user has one. It is part of the `code-index` store (sealed, derived: the index is rebuilt by
reindexing, the binary by the install steps above). Its daemon keeps lock files under `%LOCALAPPDATA%\cbm-daemon-<hash>`: CBM's, outside BRAIN_HOME.

### brain index

Each declared repo is indexed in place (its main checkout's working tree, as CBM's project named after the repo's
folder) and recorded with its branch, its HEAD and whether it had uncommitted changes. `--stale` reindexes the repos
whose HEAD moved; `brain health code-index` says `STALE` for those (for every declared repo when no stack declares
`index:`, else only for those CBM indexed).

### brain impact on a worktree

The checkout is indexed in place under a temporary project (`<repo>-wt-<digest of its path>`, CBM's fast mode,
about 10 s for the engine), `detect_changes` against the base gives the changed symbols (its seeds; a file or module
node is not one) and their callers (CALLS, `--depth` levels up, each with the symbol it reaches), and the temporary
project is deleted, the index failing or not, while the server answers. One a run could not delete (killed, the
server ended) is deleted by the next run once its checkout is gone. The cockpit's impact frame, read at every probe,
asks GitNexus only: CBM would index the checkout each time. A CodeRef is placed by its qualified name: the project, the file's folders and stem, the symbol, joined by
dots (`code:lab:lab/core.py::Engine.run` is `<project>.src.lab.core.Engine.run` when the file is `src/lab/core.py`).
A CodeRef of a changed file that is neither a seed nor a caller is checked by the AST, as at the file level. The
branch needs no push: what kept `brain impact` on the host's diff with GitNexus does not apply.

### When it fails

Not installed, a binary that does not start, no answer within the deadline (the process is killed), an answer that
is not JSON-RPC, or a tool's error: one line, CBM's own `error` when it gives one; `brain index` exits 1, `brain
impact` falls back (GitNexus, else the file level) and says why on its second line. When CBM answers after GitNexus
failed, the impact's note says why GitNexus could not.

### Not yet

`brain status`'s code index rows read GitNexus's record only: a machine whose code index is CBM shows none there;
`brain health code-index` is the check.

## xerj

[xerj](https://github.com/xerj-org/xerj) (Apache-2.0) is one Rust binary: a search node behind an
Elasticsearch-compatible API, `xerj autoindex` (a folder into indices under a prefix, code parsed by tree-sitter) and
`xerj search` (its query client). It is an **opt-in** backend: `--backend xerj` names it, nothing chooses it by
default. It is the third arm of the code bench's second stage, beside GitNexus and codebase-memory-mcp, until that
bench picks the search authority. It serves index, health and the adapter's search, not code-map nor impact.

### Install (the owner)

The official binaries are built from a private tree with proprietary crates; the engine reads a binary **built from
xerj's public main** at a pinned commit (the commit the engine's calls are read from: `53e4db0c`, 2026-11-23).

1. Clone `https://github.com/xerj-org/xerj` at that commit into a short path; build with Rust 1.94.1 or later
   (`cargo build --release -p xerj-server`; on Windows a full Perl, such as Strawberry, for the bundled OpenSSL).
2. Copy `target/release/xerj(.exe)` to `$BRAIN_HOME/code-index/xerj/bin`. Nothing else: never `xerj init` (it wires
   agents and skill files), never `xerj feedback`, no scheduled task.
3. Declare its stack in projects.yaml, under a project's `stacks:` (below): a new service is the owner's decision.
4. `brain up xerj`, then `brain index --backend xerj` prints each declared repo's state.

### The service

The stack, under a project of projects.yaml:

```yaml
stacks:
  xerj:  # xerj's search node, the code index's opt-in arm (brain.xerj): started and stopped by the engine
    start: [brain, index, --backend, xerj, --serve]
    stop: [brain, index, --backend, xerj, --stop]
    health: {urls: ['http://127.0.0.1:9200/']}
    timeout: 180
    class: service
    profile: custom
    provides: [code search]
    requires: []
    resources: {ram_mb: 2048, disk_mb: 500}
    fallback: GitNexus, the search authority, else git grep
```

`--serve` starts the node unless the engine's node runs: `xerj --detach` (it returns once the node serves), bound to
127.0.0.1 on port 9200 (the Elasticsearch-compatible API; xerj also claims 9201 and 9202), TLS and API keys off
(loopback only), `--no-auto-port`, lexical embeddings (no model is downloaded), its data in
`$BRAIN_HOME/code-index/xerj/data` (its log `node.log` there). The engine's node is the live process that xerj's own
lock of that folder names (`node.lock`, a bare pid; `node.lock.pid` while the lock is held), checked by its program
file to be the engine's binary; another service answering on the port is left alone and the start refused (and
`brain index` or the search never write to it). `--stop` signals that process only, re-checked before each signal:
on Linux and macOS SIGTERM (xerj's graceful stop: its memtables flushed), SIGKILL after 30 s; on Windows a detached
node has no console, so it is stopped at once with `taskkill /F` (xerj's own `hub stop` does the same; its WAL is
replayed at the next start). A node the engine did not start (no lock in its folder) is left alone. `brain up` with
no name starts every declared stack: while the binary is not installed, the xerj stack's line says `FAILED ... xerj
is not installed`.

### What the engine keeps off

Every call of the binary runs with `XERJ_DISABLE_FEEDBACK=true` (no field report, no weekly corpus feedback),
`XERJ_NO_AUTOSTART=1` (xerj's clients start a stopped local node on their own; here only `brain up` does) and
`HF_HUB_OFFLINE=1`. Its output goes to a file, never to a pipe the detached node could inherit. xerj itself writes
`~/.xerj/by-port/<port>.data-dir` at each start, outside its data folder: xerj's, not the engine's.

### brain index

Each declared repo's branch head (its declared branch, else the default one) is read with `git archive` into
`$BRAIN_HOME/code-index/xerj/snapshots/<repo>` (tracked files at a known commit: the path the xerj trial measured),
then `xerj autoindex` indexes that folder under the repo's prefix (`bx` and its name's lowercase letters and digits:
xerj searches a prefix as `<prefix>-*`, so no prefix is another's followed by a dash; two declared repos whose names
give the same prefix, `acme-data` and `acme_data`, are neither indexed nor searched, and the line says to rename a
folder), its state in `$BRAIN_HOME/code-index/xerj/state/<repo>`, `--no-graph`, `--max-minutes 0` (no time gate),
`--progress plain`. `--no-graph`: xerj's resume policy reconciles added, changed, deleted and renamed files on every
run of such a journal, where a graph-enabled one answers `stale-resume-plan` once a file needs a new dataset, until a
`--fresh` it then refuses; `xerj search` does not read that link layer. The run is read from its `xerj-done` line:
exit 0 and 3 (completed with junk) are a finished run when the line is there and says neither `ok=false` nor that
every code file was dropped (`code_files` > 0 and `code_files_indexed` = 0); no line (an output that is not xerj's) is
a failure; exit 4 is a decision xerj asks (its disk budget), reported and never answered for the owner; the run is
killed after an hour. The trial measured 4.7 to 6.9 minutes a repo and up to 1.9 GB of memory.

### The adapter's search

`brain.codebackends.search(query, repo, k, backend="xerj")` runs `xerj search --json` on the repo's prefix and
returns ranked rows: `rank`, `path` (relative to the snapshot, `/`-separated), `line` (the matched line, else the
passage's or symbol's first), `name` and `kind` (a symbol's, empty for a file), `score`, `backend`;
`brain.xerj.files(rows)` gives the distinct paths in rank order, what a file recall reads. A node that does not
answer is said (`brain up xerj starts it`) and never started by the query.

### When it fails

Not installed, a binary that does not start, a node that does not answer (or a port held by another service), a
snapshot that fails (git, the disk, a path too long), no end within the deadline (killed), an answer that is not
xerj's, or xerj's own error: one line; `brain index` exits 1 and records nothing for that repo, the search raises the
adapter's error. An installed xerj never stands for a counted backend: declared repos with neither GitNexus's stack
nor codebase-memory-mcp stay a declaration error of `brain health code-index` (exit 2), and only `--backend xerj`
lifts it. The recorded answers the tests replay are in `tests/fixtures/xerj` (its README
says where each comes from).
