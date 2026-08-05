# pyagent — Codex 风格的终端编码 Agent（CLI + TUI + 桌面 GUI）

`pyagent` 是一个运行在本地的 Python 编码 Agent。你用自然语言描述任务，它按「**思考 → 调用工具 → 观察结果 → 继续**」的循环自主完成工作（读写/编辑文件、搜索、执行 Shell 命令），并在终端里渲染整个交互过程（流式输出、工具状态、diff 预览、权限确认）；此外还提供一套 Codex 风格的桌面 GUI。

架构参照 `GOAL.md` 中的参考项目分层设计：`core`（agent 循环 / 模型 / 消息 / 上下文）、`tools`（注册表 / 文件 / Shell / 权限）、解耦的 `tui` 与 `gui` 界面层。模型走 **OpenAI 兼容接口**——同一客户端可用于 OpenAI、DeepSeek、DashScope、Ollama 等。

## 安装

需要 **Python 3.11+**。

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"         # 安装项目 + 开发依赖（pytest、ruff）
pip install -e ".[gui]"         # 如需桌面 GUI，再装 pywebview（可选）
```

安装后获得 `pyagent` 命令和 `python -m pyagent` 入口。

## 配置

配置位于 `~/.pyagent/config.toml`（或通过 `--config` 指定）。配置文件可省略——缺失时使用默认值。示例：

```toml
[model]
base_url = "https://api.deepseek.com/v1"   # 任意 OpenAI 兼容端点
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"           # 存放 API key 的环境变量
# api_key = "sk-..."                       # 也可直接填字面 key
max_turns = 20

[permissions]
default_write = "prompt"    # allow | deny | prompt
default_bash  = "prompt"

[session]
dir = "C:/Users/you/.pyagent/sessions"

[tools]
bash_timeout = 120
```

非法配置（TOML 语法错误、未知段落、类型错误）会给出明确报错，而不是静默降级。

## 用法

### 单次问答模式

```bash
pyagent "新建 src/demo.py，定义一个 greet(name) 函数，返回 f'Hello, {name}!'，然后执行它"
```

Agent 把过程流式输出到 stdout。在终端中，危险操作（写文件、执行命令）仍会弹出 `allow`/`deny` 确认；stdin 被管道接管（非交互）时按配置默认策略处理。

### 交互式 TUI

```bash
pyagent
```

TUI 会流式显示模型输出、展示工具调用状态、预览编辑 diff、弹出权限确认，并支持：

```
/help         查看帮助
/save         保存当前会话
/sessions     列出已保存的会话
/resume <id>  恢复某个会话
/clear        开启新对话
/quit         退出（自动保存会话）
```

`Ctrl+C` 中断当前任务；再按一次 `Ctrl+C` 或输入 `/quit` 退出。

### 恢复会话

```bash
pyagent --resume <session-id> "继续之前的任务"
```

### 其他参数

```bash
pyagent --version          # 打印版本号
pyagent --config <path>    # 指定 TOML 配置文件
pyagent --cwd <path>       # 工具的工作目录
```

### 桌面 GUI

Codex 风格的桌面窗口（聊天流式输出、工具调用状态卡片、权限确认弹窗、diff 预览、会话侧边栏）。它复用同一套核心循环与工具，通过本地回环 HTTP+SSE 服务提供，并用 `pywebview` 原生窗口渲染（Windows 使用内置 WebView2）。

```bash
pip install -e ".[gui]"        # 安装 pywebview（可选 extra）
pyagent gui                    # 打开原生桌面窗口
pyagent gui --browser          # 改用默认浏览器打开
```

设置环境变量 `PYAGENT_GUI_BROWSER=1` 也会强制走浏览器模式。

## 工具集

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文本文件（大文件安全截断）。 |
| `write_file` | 新建/覆盖文件；自动创建父目录。 |
| `edit_file` | 精确替换第一个 `old_string`；应用前展示 diff 预览，目标不匹配时返回可诊断错误。 |
| `glob` | 按 glob 模式查找文件（如 `src/**/*.py`）。 |
| `grep` | 用正则搜索文件内容，输出 `path:line: text`。 |
| `bash` | 在宿主机执行 Shell 命令；返回 stdout/stderr 与退出码。 |

## 权限系统

写操作（`write_file`、`edit_file`）与 Shell 命令（`bash`）需要授权。判定顺序：

1. 命中的已记忆规则（路径 glob / 命令前缀）→ 直接生效；
2. 交互式弹窗确认（`y` 允许一次、`n` 拒绝一次、`a` 总是允许、`d` 总是拒绝）——**记住的规则会持久化到 `permissions.json`**；
3. 否则按配置默认值（`prompt` = 非交互时自动放行；`deny` = 拒绝并给出明确反馈）。

## 会话

每次对话都会自动保存到会话目录（默认 `~/.pyagent/sessions`），一个会话一个 JSON 文件。可在 TUI 里用 `/resume` 恢复，或用 `pyagent --resume <id> "..."`。历史过长时会压缩成滚动摘要（以系统消息形式注入），让模型在有限的上下文窗口内持续工作。

## 开发

```bash
ruff check .      # 静态检查
pytest            # 单元 + 集成测试（62 个用例）
```

测试覆盖：mock 模型下的核心循环（工具调用、直接回复、轮次上限、上下文压缩）、全部六个工具、权限系统、配置校验、会话持久化、TUI 命令分发，以及桌面 GUI（渲染器 + 服务端集成 + SSE 权限批准 E2E）。

## 目录结构

```
src/pyagent/
  __main__.py / cli.py    # 入口：单次问答、TUI、pyagent gui
  config.py               # TOML 配置加载与校验
  core/                   # loop.py, model.py, messages.py, context.py
  tools/                  # registry.py, files.py, shell.py, permissions.py
  tui/                    # app.py, renderer.py, headless.py, prompts.py
  gui/                    # app.py, server.py, renderer.py, static/（前端）
tests/                    # pytest 测试套件
```

## 非目标（v1）

沙箱/容器、MCP、多模型供应商、子 Agent、IDE 集成、skills 技能系统、遥测/埋点。其中若干接缝已就位（`LLMClient` 接口、`register_tool`、renderer 协议），为后续扩展预留。
