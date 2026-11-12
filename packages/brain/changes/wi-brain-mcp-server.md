section: Added

- `brain mcp serve` (`wi-brain-mcp-server`): the Brain as an MCP server, in the foreground of whoever launches it.
  Resources: the neutral source's rules, the procedures' files, the decision log's index and one ADR by template;
  prompts: the procedures; tools: the graph's reads (`brain items`, `item show`, `adr show`, `spec show`, `next`),
  `brain check`, the memory notes read and a proposed memory note the memory sync carries by a reviewed PR. Every
  answer passes the secret scan. stdio by default; `--http`: Streamable HTTP on a loopback address only, each request
  with the machine's token. `brain mcp tools` lists the tools. A versioned container definition
  (`packages/brain/container/`: a user that is not root, the port published on 127.0.0.1 only, never restarted by
  itself) builds the image; running it is the owner's decision (docs/mcp.md).
- `brain ipc token [--init]`: the machine's token for the Brain's local services, `<BRAIN_HOME>/ipc/token`, made
  once by `--init` and never printed (docs/mcp.md, « The machine's token »).
