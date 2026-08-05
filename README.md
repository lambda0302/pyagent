# pyagent — a Codex-style terminal coding agent (CLI + TUI)

`pyagent` is a local Python coding agent. You describe a task in natural
language; the agent runs a **think → call tools → observe → continue** loop
(read/write/edit files, search, run shell commands) until it can answer, and
renders everything in an interactive terminal UI (streaming output, tool
status, diff previews, permission confirmations).

The architecture follows the reference projects in `GOAL.md`: a layered
`core` (agent loop / model / messages / context), a `tools` layer (registry +
files + shell + permissions), and a decoupled `tui` layer. The model provider
is an **OpenAI-compatible API** — the same client works with OpenAI,
DeepSeek, DashScope, Ollama, etc.

## Installation

Requires **Python 3.11+**.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"         # project + dev dependencies (pytest, ruff)
```

This installs the `pyagent` console script and the `python -m pyagent` entry
point.

## Configuration

Configuration lives in `~/.pyagent/config.toml` (or a path passed with
`--config`). It is optional — defaults are used if the file is missing.
Example:

```toml
[model]
base_url = "https://api.deepseek.com/v1"   # any OpenAI-compatible endpoint
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"           # env var holding the API key
# api_key = "sk-..."                       # optional literal key
max_turns = 20

[permissions]
default_write = "prompt"    # allow | deny | prompt
default_bash  = "prompt"

[session]
dir = "C:/Users/you/.pyagent/sessions"

[tools]
bash_timeout = 120
```

An invalid config file (bad TOML, unknown section, wrong type) produces a
clear error instead of silently degrading.

## Usage

### Single-shot mode

```bash
pyagent "新建 src/demo.py，定义一个 greet(name) 函数，返回 f'Hello, {name}!'，然后执行它"
```

The agent streams its progress to stdout. In a terminal, dangerous operations
(writes, shell commands) still prompt for `allow`/`deny`; when stdin is piped
(non-interactive) the configured defaults apply.

### Interactive TUI

```bash
pyagent
```

The TUI streams model output, shows tool call status, previews edit diffs,
prompts for permissions, and supports:

```
/help            show help
/save            save the current session
/sessions        list saved sessions
/resume <id>     continue a saved session
/clear           start a fresh conversation
/quit            exit (session is auto-saved)
```

`Ctrl+C` interrupts the current task; `Ctrl+C` again or `/quit` exits.

### Resuming a session

```bash
pyagent --resume <session-id> "继续之前的任务"
```

### Other flags

```bash
pyagent --version          # print version
pyagent --config <path>    # use a specific TOML config
pyagent --cwd <path>       # working directory for tools
```

### Desktop GUI

A Codex-style desktop window (chat streaming, tool-call status cards,
permission dialogs, diff previews, a session sidebar) — it reuses the same core
loop and tools, served over a local loopback HTTP+SSE server and rendered in a
native `pywebview` window (WebView2 on Windows).

```bash
pip install -e ".[gui]"        # install pywebview (optional extra)
pyagent gui                    # native desktop window
pyagent gui --browser          # fall back to the default browser instead
```

`PYAGENT_GUI_BROWSER=1` also forces browser mode.

## Tools

| Tool        | Description                                                        |
|-------------|--------------------------------------------------------------------|
| `read_file` | Read a text file (large files are truncated safely).               |
| `write_file`| Create/overwrite a file; parent directories are created.           |
| `edit_file` | Surgical replace of the first `old_string` occurrence; shows a diff preview and fails with a diagnostic on mismatch. |
| `glob`      | Find files by glob pattern (`src/**/*.py`).                        |
| `grep`      | Regex search across files, `path:line: text` output.               |
| `bash`      | Run a shell command on the host; returns stdout/stderr and exit code. |

## Permissions

Writes (`write_file`, `edit_file`) and shell commands (`bash`) require
approval. The order of resolution is:

1. a remembered rule (path glob / command prefix) → apply it;
2. an interactive prompt (`y` once, `n` once, `a` always allow, `d` always
   deny) — *remembered rules persist to `permissions.json`*;
3. otherwise the config default (`prompt` = auto-allow when non-interactive,
   `deny` blocks the operation with clear feedback).

## Sessions

Every conversation is auto-saved to the session directory
(`~/.pyagent/sessions` by default) as one JSON file per session id. Resume
with `/resume` in the TUI or `pyagent --resume <id> "..."`. Long histories are
compressed into a running summary (kept as a system message) so the model can
keep working within the context window.

## Development

```bash
ruff check .      # static checks
pytest            # unit + integration tests (52 tests)
```

Test coverage includes the core loop under a mock model (tool calls, direct
reply, turn-limit, compression), all six tools, the permission system, config
validation, session persistence, and the TUI command dispatch.

## Project layout

```
src/pyagent/
  __main__.py / cli.py    # entry points, single-shot + TUI modes
  config.py               # TOML config loading + validation
  core/                   # loop.py, model.py, messages.py, context.py
  tools/                  # registry.py, files.py, shell.py, permissions.py
  tui/                    # app.py, renderer.py, headless.py, prompts.py
tests/                    # pytest suite
```

## Non-goals (v1)

Sandboxing/containers, MCP, multiple model providers, sub-agents, IDE
integration, skills, telemetry. The seams for several of these (the `LLMClient`
interface, `register_tool`, the renderer protocol) are already in place.
