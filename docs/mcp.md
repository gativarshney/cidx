# Using cidx from an AI coding agent (MCP)

cidx runs as an [MCP](https://modelcontextprotocol.io) server over stdio. A
coding agent that speaks MCP starts `cidx serve` as a child process,
discovers five read-only tools, and calls them instead of grepping and
reading whole files. This guide assumes you have never used cidx or MCP.

## 1. Install

You need Python 3.11 or newer and git on your PATH. Either run the
published package without installing it (`uvx` ships with
[uv](https://docs.astral.sh/uv/); the first run downloads cidx):

```bash
uvx cidx --version
```

or install it:

```bash
pip install --pre cidx
cidx --version
```

Nothing else is required: no API key, no Docker, no database server, no
account. cidx never writes inside your repository. The index lives in a
per-user cache (`%LOCALAPPDATA%\cidx` on Windows, `~/.cache/cidx` elsewhere);
`cidx stats --repo .` prints its exact path.

## 2. Build the index once (recommended)

From your repository root:

```bash
cidx index --repo .
cidx stats --repo .
```

With `uvx`, prefix each command (`uvx cidx index --repo .`). The commands
are identical in PowerShell.

`cidx serve` builds a missing index by itself, so this step is optional,
but until that first build finishes the agent gets partial answers. On
Django (3,043 files) the build takes about 30 seconds; see
[verification.md](verification.md) for every measurement in this guide.

## 3. Point your agent at it

Every stdio MCP client takes the same facts: a command and its arguments.
Use an **absolute** repository path, because the client does not run inside
your repository. On Windows, write the path with forward slashes
(`C:/code/myrepo`) so it needs no escaping in JSON.

With `uvx`:

```json
{
  "mcpServers": {
    "cidx": { "command": "uvx", "args": ["cidx", "serve", "--repo", "/absolute/path/to/repo"] }
  }
}
```

With cidx installed on the PATH:

```json
{
  "mcpServers": {
    "cidx": { "command": "cidx", "args": ["serve", "--repo", "/absolute/path/to/repo"] }
  }
}
```

### Claude Code

Register it for the current project, then restart Claude Code:

```bash
claude mcp add cidx -- uvx cidx serve --repo /absolute/path/to/repo
```

`claude mcp list` should then show `cidx`, and the tools appear to the agent
as `mcp__cidx__search_symbols`, `mcp__cidx__find_definition`, and so on.
Equivalently, put the JSON above in a `.mcp.json` file at the project root.

**What has been verified, and what has not.** The protocol path — spawning
`cidx serve`, MCP `initialize`, `tools/list`, and `tools/call` for every
tool — is exercised by the official MCP Python client in
`tests/integration/test_mcp_server.py` on Linux, macOS, and Windows in CI,
and by `scripts/mcp_smoke.py` below against both a source checkout and the
published package. The `claude mcp add` form above is Claude Code's
documented registration command; the Claude Code client itself was not
driven by this project's tests. Other clients are not listed because they
were not tested.

## 4. Verify the server without an agent

```bash
python scripts/mcp_smoke.py --repo /absolute/path/to/repo
```

From a checkout of this repository; add `--command "uvx cidx"` to test the
published package instead. The script starts the server the way a client
does, lists the tools, calls `find_definition`, and exits non-zero unless
exactly the five tools below are registered. Running `cidx serve` by hand
prints nothing — it is waiting for MCP messages on stdin — so use the
script.

## 5. What the five tools return

All five are read-only: they look things up and never write to, execute,
or modify the repository. Every response is plain text, one result per
line, followed by a short trailer. The examples are real output on Django.

| Tool | Ask it when | One result line |
|---|---|---|
| `search_symbols(query)` | you only roughly know a name | `get_object_or_404  function  django/shortcuts.py:79  def get_object_or_404(klass, *args, **kwargs)` |
| `find_definition(name)` | where is `Model.save` defined | `Model.save  method  django/db/models/base.py:847  def save( self, *, force_insert=False, ...)` |
| `find_references(name)` | who uses `get_object_or_404` | `django/contrib/flatpages/views.py:37  get_object_or_404  [import]  -> get_object_or_404 (django/shortcuts.py)` |
| `outline_file(path)` | what is in `django/shortcuts.py` | `79  get_object_or_404  function  def get_object_or_404(klass, *args, **kwargs)` |
| `repo_map()` | orienting in an unfamiliar repository | `django/db/models/query.py  (python, 248 symbols, 2885 inbound)  MAX_GET_RESULTS, REPR_OUTPUT_SIZE, ...` |

What to know when reading a response:

- **Locations, not file bodies.** A result is `qualified name, kind,
  path:line, signature`. The agent verifies by opening the cited line; cidx
  never returns source beyond the one-line signature.
- **Token budget.** Each tool accepts `max_tokens` (default 700, estimated
  as characters ÷ 4). Result lines stop at the budget; when results were
  cut the trailer says `truncated: true, total_matches: N`. The trailer
  itself (that line plus the freshness stamp) is about 20 tokens outside
  the budget, so a 700-token budget yields roughly 720 tokens.
- **Freshness stamp.** Every response ends with `index_age_ms: N`, the
  milliseconds since the most recent file was indexed. A large value on a
  repository nobody is editing is normal, not a sign of staleness.
- **Confidence tags on references** say how a usage was matched to a
  definition. `[exact]`: a definition of that name in the same file.
  `[import]`: the file imports that name and cidx followed the import to
  its source. `[name-only]`: either the only definition of that name in the
  repository, or no definition at all (then no `->` target is shown). There
  is no type checker behind the tags; treat `name-only` as a lead.
- **Misses fail open.** When cidx cannot answer, it says so and recommends
  grep — for example `cidx: no definition of 'foo' in the index. Fall back
  to grep/ripgrep for this question; results may simply not be indexed
  yet.` cidx recommends grep; it does not run it.
- `outline_file` takes a repository-relative path with forward slashes
  (`src/app.py`), not an absolute path.

## 6. Keeping the index fresh

While `cidx serve` runs, a file watcher re-indexes each saved file (only
that file's rows are replaced, in one SQLite transaction), and a
reconciliation sweep every 30 seconds catches anything the operating
system's watcher dropped. How quickly a save becomes queryable depends on
repository size, because references are re-resolved across the whole index
after every change: milliseconds on a small project, about two seconds on
Django. `cidx check --repo .` proves at any time that the live index equals
a fresh rebuild.

## 7. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every tool answers `cidx: no index for ...` | The index has not been built. Run `cidx index --repo <path>`, or wait for the watcher's first sweep. |
| `outline_file` finds no symbols for a file that exists | The path must be repository-relative with forward slashes. |
| The agent lists no cidx tools | The client could not start the command. Check that `uvx` (or `cidx`) is on the PATH the client uses and the `--repo` path is absolute; run `scripts/mcp_smoke.py` with the same `--command`. |
| First answers after startup are incomplete | `serve` is still building a missing index; `index_age_ms` keeps resetting while it does. Pre-build with `cidx index`. |
| The first start after upgrading cidx re-indexes everything | The index schema version changed and cidx rebuilds rather than misread an old index. A one-time cost equal to a fresh build. |
| A file's symbols are missing | Only Python and TypeScript/JavaScript are indexed; files over 1 MiB, gitignored files, and `.venv`, `node_modules`, `build`, `dist` and similar directories are skipped. |
