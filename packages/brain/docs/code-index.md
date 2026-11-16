# The code index and its backends

`brain index`, `brain code-map`, `brain impact` and `brain health code-index` read the code through one interface
(`brain.codebackends`), which picks a backend for each. Each backend is declared in the tier registry
(`tiers.yaml`: `code-index-gitnexus`, `code-index-cbm`) with its requirements and its fallback; without any, the
impact is at the file level (every CodeRef of a changed file, a Python symbol's checked by the AST of both sides) and
says why.

| | GitNexus (`gitnexus`) | codebase-memory-mcp (`cbm`) |
|---|---|---|
| What it is | GitNexus in its container: the stack whose `index:` names it (projects.yaml) | one native binary, run as a stdio MCP server for the time of a command |
| Needs | a container runtime (Docker) | its binary under `$BRAIN_HOME/code-index/cbm/bin` |
| Serves | index, code-map, impact, health | index, impact, health |
| Its role | the code authority for search, the default | `brain impact` on a worktree; the code index of a machine without Docker |
| What it indexes | a snapshot of each repo's branch, in GitNexus's own clone | the checkout itself, in place (no file written into it) |
| Its record | `$BRAIN_HOME/code-index.json` | `$BRAIN_HOME/code-index/cbm/record.json` |

How a command picks:

- `brain index`: GitNexus when a stack declares `index:`, else codebase-memory-mcp when it is installed;
  `--backend gitnexus|cbm` names one.
- `brain impact`: GitNexus first, codebase-memory-mcp first on a worktree (a checkout other than the main one), each
  the other's fallback when it is there; `--backend` names one. CBM reads a checkout's working tree, so a commit range
  (`--diff A..B`) is never asked of it.
- `brain code-map`: GitNexus only (it resolves each CodeRef through GitNexus's Cypher).
- `brain health code-index`: every backend this machine has; CBM's line also when no repo is declared.

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
