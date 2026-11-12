# The Brain as an MCP server

`brain mcp serve` (`brain.mcpserver`, `wi-brain-mcp-server`) lets any agent that speaks the Model Context Protocol
read and use the Brain the way Claude Code does through its files and the `brain` command: Cursor, other desktop
clients and, once the owner decides to expose it, hosted agents. One tool layer serves two transports, so a tool
behaves the same on either.

Nothing starts on its own. `brain mcp serve` runs in the foreground of whoever launched it; the container definition
never restarts by itself. Running it as a service, and anything that makes it reachable from another machine, is the
owner's decision.

## What it serves

Read from the personal brain it runs in (`brain --root DIR mcp serve`, else the personal brain `brain` finds):

| MCP primitive | What | Where it comes from |
|---|---|---|
| resources | `brain://rules/<file>`: each rules file of the neutral source, as an agent reads it (`# title`, intro, the rules, ids taken out) | `source/rules/` (`brain.neutral`) |
| resources | `brain://procedures/<name>/<file>`: each file of each procedure | the engine's procedures, the owner's laid over them |
| resources | `brain://decisions`: the decision log's index (date and title of every ADR) | `notes/decisions.md` |
| resource template | `brain://decisions/{ref}`: one ADR by its id, title or the start of its id | `brain adr show` |
| prompts | each procedure (its `SKILL.md`), with an optional `task` argument | the procedures |
| tools | see below | |

`brain mcp tools` lists the tools:

| Tool | Kind | What it runs |
|---|---|---|
| `brain_items` | read | `brain items` with its filters (status, text, wave, priority, type, milestone, limit) |
| `brain_item_show` | read | `brain item show ID` |
| `brain_adr_show` | read | `brain adr show REF [--titles]` |
| `brain_spec_show` | read | `brain spec show REF [--section N \| --toc]` |
| `brain_next` | read | `brain next` |
| `brain_check` | read | `brain check` |
| `memory_read` | read | the memory notes of this machine: the folders, a folder's notes, a note |
| `memory_propose` | write | writes a note into this machine's memory folder of a project; the memory sync exports it by a reviewed PR, never to main (`brain memory`) |

Every tool takes an optional `project` (a registered project). A graph tool runs the `brain` command in a child
process with a deadline (`BRAIN_MCP_TIMEOUT`, seconds, default 120). Its arguments are validated first: an id never
starts with `-`, a free text goes as `--text=VALUE`, an argument the tool does not declare is refused, and nothing
runs when one is wrong. `memory_propose` refuses a note whose text matches a secret pattern, and a project folder that
does not exist on this machine.

**No secret in an answer.** Every answer (a tool's, a resource's, a prompt's) passes `brain.secretscan.clean`: a line
with a key's shape is dropped, and the answer says how many lines were. An internal error reaches the client as its
type only; the detail goes to the server's stderr.

## The transports

### stdio (the default)

The client launches `brain mcp serve` and speaks newline-delimited JSON-RPC 2.0 on its stdin and stdout (UTF-8, bare
newlines). Nothing is exposed. A client's configuration, Cursor's `~/.cursor/mcp.json` for instance:

```json
{"mcpServers": {"brain": {"command": "brain", "args": ["mcp", "serve"]}}}
```

### HTTP on loopback, with the machine's token

`brain mcp serve --http [--host 127.0.0.1] [--port 8791]` speaks Streamable HTTP: a `POST /mcp` per message (or
batch), each answer a JSON body; a notification gets `202`. The server sends no request of its own, so it opens no
stream: `GET` and `DELETE` answer `405`.

- **Loopback only.** It refuses to bind any address but 127.0.0.0/8, `::1` or `localhost`. Inside its container
  (`BRAIN_MCP_CONTAINER=1`, set by the image) it binds the container's addresses, and the compose file publishes the
  port on `127.0.0.1` only.
- **The machine's token** on every request: `Authorization: Bearer <token>`, compared in constant time; without it,
  `401`. The token is the one `brain ipc token --init` makes once (below); the server refuses to start without one.
- **Host and Origin.** A request whose `Host` is not a loopback name, or whose `Origin` names another host (a page in
  a browser, DNS rebinding), gets `403`.
- **Limits.** A body over 1 MB gets `413`; an `MCP-Protocol-Version` header naming a version it does not speak gets
  `400` (it speaks 2025-06-18, 2025-03-26 and 2024-11-05). A refused request closes its connection.

A client's configuration with a header, the token taken from an environment variable the owner fills from the file:

```json
{"mcpServers": {"brain": {"url": "http://127.0.0.1:8791/mcp",
                          "headers": {"Authorization": "Bearer ${env:BRAIN_IPC_TOKEN}"}}}}
```

## The machine's token: `brain ipc token`

One token per machine for every local service the Brain starts (`brain.ipcauth`), in `<BRAIN_HOME>/ipc/token`
(`$BRAIN_IPC_TOKEN_FILE` names another file; the container reads the copy its compose file mounts as a secret).

- `brain ipc token`: the file, and whether it holds a usable token (exit 1 when not).
- `brain ipc token --init`: makes it when there is none, from 32 random bytes, the file readable by its owner only;
  an existing usable token is kept. A rotation is the file's deletion, then `--init`, then each client updated.

The token is never printed, never in a log line (the server logs the request line and the status only) and never in
the image.

## The container

`packages/brain/container/` holds the image's definition, versioned with the engine:

- `Dockerfile`: the base image pinned by digest, the engine installed from this checkout, a user that is not root
  (uid 10001), the image's version label from the build argument `BRAIN_VERSION`. Build it from the repo's root:
  `docker build -f packages/brain/container/Dockerfile --build-arg BRAIN_VERSION=<version> -t brain-mcp:<version> .`
- `compose.yaml`: the personal brain's checkout mounted read-only at `/brain` (`BRAIN_ROOT_DIR`), the token file as a
  secret (`BRAIN_IPC_TOKEN`), the port published on `127.0.0.1:8791`, a read-only root file system, every capability
  dropped, no new privileges, `restart: "no"`. Its `BRAIN_HOME` is a named volume.

A remote endpoint (a tunnel, the cluster) waits on the owner's answers to the connector spec's open questions: which
projects it serves, which providers, where it runs. The guards every tool call passes before it runs are
`wi-brain-mcp-guards`'.
