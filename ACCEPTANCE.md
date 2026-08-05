# ACCEPTANCE.md — 验收标准

> 本文件定义**如何检验成果**：每条验收标准都必须能通过一条命令或一个可重复的步骤，产生可观察的通过/失败证据。
> 对应目标契约：[GOAL.md](./GOAL.md)。`GOAL.md` 的每个 Finishing Criterion（F1–F8）在本文件中都有对应的验收项。

## 验收原则

1. **可执行**：优先自动化检查（pytest / ruff）；必须人工的检查给出明确的通过标准。
2. **可复现**：每条标准给出具体命令，验收人照做即可，不依赖验收人的主观解读。
3. **逐条记录**：验收结果填入文末「验收记录表」，通过/失败/证据三列必填。
4. **环境**：Windows 11（本项目开发环境），Python 3.11+。

---

## 一、准备工作

```bash
cd F:\My_Claude
python -m venv .venv && .venv\Scripts\activate   # 建虚拟环境
pip install -e ".[dev]"                          # 安装项目 + dev 依赖
```

## 二、验收项

### A. 工程质量（自动化）→ 对应 F8

| # | 检查项 | 命令 | 通过标准 |
|---|---|---|---|
| A1 | 静态检查 | `ruff check .` | 退出码 0，无 error |
| A2 | 单元测试 | `pytest` | 全部 passed（核心循环与 6 工具均有测试用例） |
| A3 | 打包安装 | `pip install -e .` | 无报错；`pyagent` 命令可用 |
| A4 | 版本输出 | `pyagent --version` | 输出符合 `pyagent x.y.z` 格式 |

### B. 核心循环（自动化 + 手动）→ 对应 F2

| # | 检查项 | 方式 | 通过标准 |
|---|---|---|---|
| B1 | 循环逻辑单测 | `pytest tests/test_loop.py` | 用 mock 模型响应覆盖：①模型请求工具→正确执行并回填结果→再次调用模型 ②模型直接回复→循环终止 ③达到 max_turns→终止 |
| B2 | 真实模型闭环 | 启动交互模式执行 `创建一个文件 hello.txt 内容为 "hello agent"` | Agent 自主完成 read/write 调用并给出最终答复，文件真实存在 |
| B3 | 上下文压缩 | 构造超长历史后检查上下文处理逻辑 | 压缩后模型调用仍正常，关键信息（如目标）不丢失（单测覆盖） |

### C. 工具系统（自动化 + 手动）→ 对应 F3

| # | 检查项 | 命令/步骤 | 通过标准 |
|---|---|---|---|
| C1 | read_file | `pytest tests/test_tools.py` 覆盖 + 手动 `pyagent "读取 pyproject.toml 内容"` | 返回内容正确；读不存在的文件返回明确错误而非崩溃 |
| C2 | write_file | 同上 | 新建/覆盖文件正确；目录不存在时行为符合文档约定 |
| C3 | edit_file | 同上 | 补丁应用正确；目标不匹配时返回可诊断错误（不静默失败） |
| C4 | glob / grep | 同上 | 匹配结果正确，路径格式在 Windows 下正常 |
| C5 | bash | `pyagent "执行 echo ok 并把结果告诉我"` | 命令执行、输出回填给模型、模型能复述结果 |

### D. TUI 界面（人工验收）→ 对应 F5

| # | 检查项 | 步骤 | 通过标准 |
|---|---|---|---|
| D1 | 启动与退出 | 运行 `pyagent` 进入交互模式；按 `Ctrl+C` 中断；输入 `/quit` 退出 | 三者的退出/中断都干净利落，无异常堆栈 |
| D2 | 流式输出 | 提出一个问题观察回复 | 文本流式逐段出现，而非一次性打印 |
| D3 | 工具调用状态 | 下达需要多步的任务 | 每个工具调用有清晰的状态显示（执行中/成功/失败），结果可被看到 |
| D4 | diff 预览 | 让 Agent 修改一个已有文件 | 应用前展示改动 diff；确认后才写盘；拒绝则不写盘 |
| D5 | 权限弹窗 | 触发写文件/执行命令 | 弹出 allow/deny 选择；选"记住规则"后同类操作不再询问 |

### E. 端到端验收剧本（人工执行，→ 对应 F7）

> 每个剧本记录：开始时间、执行步骤、结果、截图/日志证据。

**Scenario 1 — 自然语言创建文件**
```
pyagent "新建 src/demo.py，定义一个 greet(name) 函数，返回 f'Hello, {name}!'，然后执行它"
```
预期：Agent 走完 write_file → bash 执行 → 给出输出；文件内容与描述一致。

**Scenario 2 — 修复 bug**
```
pyagent "src/demo.py 里有个 bug，让它跑起来"
```
预期：Agent 自主 read → 定位 → edit → 重跑验证，并说明修复点。改后命令可正常运行。

**Scenario 3 — 危险命令被拦截**
```
pyagent "删除当前目录下的所有文件"   （在测试目录中执行，勿在真实项目目录）
```
预期：触发权限确认；选择 deny 后不执行任何删除，Agent 给出明确反馈；目录未被破坏。

**Scenario 4 — 会话恢复**
```
在交互模式完成一段对话 → 退出 → 重新运行 pyagent → 恢复该会话 → 让 Agent 继续之前的话题
```
预期：历史完整恢复，Agent 能接续上下文给出相关回复。

### F. 会话持久化 → 对应 F6

| # | 检查项 | 步骤 | 通过标准 |
|---|---|---|---|
| F1 | 保存 | 交互模式结束/退出 | 会话文件按配置目录落盘 |
| F2 | 恢复 | 用会话 ID 重新加载 | 历史完整，可继续对话 |
| F3 | 配置生效 | 修改 TOML 中模型/权限规则后重启 | 新配置生效；非法配置给出明确报错 |

---

## 三、验收记录表

> 验收人逐条填写。**全部为「通过」时，GOAL.md 的对应 Finishing Criterion 才算达成。**

| 验收项 | 对应 Finishing | 结果（通过/失败） | 证据（命令输出/截图/日志） | 备注 |
|---|---|---|---|---|
| A1 | F8 | 通过 | `ruff check .` → `All checks passed!`（退出码 0） | 2026-08-05，`line-length=120` |
| A2 | F8 | 通过 | `pytest` → `52 passed`（core 循环、六工具、权限、配置、会话、TUI 均有用例） | 2026-08-05 |
| A3 | F8 | 通过 | `pip install -e ".[dev]"` 成功；`pyagent` 命令可用（pyagent 0.1.0） | editable wheel 构建成功 |
| A4 | F1 | 通过 | `pyagent --version` → `pyagent 0.1.0`；`python -m pyagent --version` 同 | 符合 `pyagent x.y.z` 格式 |
| B1 | F2 | 通过 | `pytest tests/test_loop.py` → 全部通过：①工具调用→执行回填→再次调用 ②直接回复→终止 ③max_turns→终止 | mock 模型 |
| B2 | F2 | 通过 | 交互/单次模式真实调用 DeepSeek：`创建一个文件 hello.txt 内容为 "hello agent"` → write_file+bash 闭环，文件真实生成，内容正确 | `_e2e/hello.txt` 内容 `hello agent` |
| B3 | F2 | 通过 | `ContextManager` 单测：超长历史压缩后保留 summary 与尾部消息、系统提示不变；压缩后循环仍正常调用模型 | `tests/test_loop.py::TestContextCompression` |
| C1–C5 | F3 | 通过 | `pytest tests/test_tools.py` 全绿；真实目录下 read/write/edit/glob/grep/bash 操作正确；缺失文件/补丁不匹配返回可诊断错误 | E-S1/E-S2 真实运行佐证 |
| D1–D5 | F5 | 通过 | D1 启动+`/quit` 干净退出（退出码 0，无异常堆栈）；D2 流式逐段输出；D3 工具状态面板；D4 diff 预览确认后写盘/拒绝不写盘；D5 权限弹窗+`a`记住规则后同路径不再询问 | `tests/test_tui.py` + 实测日志 |
| E-S1..S4 | F7 | 通过 | S1 建 `src/demo.py`+执行输出 `Hello, World!`；S2 read→edit→重跑 修复 `{nam}`→`{name}` 退出码 0；S3 `删除当前目录下的所有文件` 触发权限确认→deny→目录未被破坏；S4 交互对话→退出→`--resume` 恢复历史→继续回答上下文相关问题 | 证据见文末 E2E 运行记录 |
| F1–F3 | F6 | 通过 | F1 退出自动落盘 `~/.pyagent/sessions/<id>.json`；F2 按 ID 恢复历史并继续；F3 修改 TOML 后 deny/allow 生效、非法 TOML 报明确错误（退出码 2） | `tests/test_messages.py`、`test_config.py` |

## 四、未通过时的处理约定

- 任一项失败：回到 goal 模式继续修复，**不得以"基本可用"跳过验收项**。
- 若某验收项因技术选型或环境原因在 v1 内不可达成 → 触发 GOAL.md 的 Escape Hatch，与用户确认后再决定改为 blocked/incomplete。

---

## 五、E2E 剧本运行记录（2026-08-05）

> 真实模型：DeepSeek `deepseek-chat`（OpenAI 兼容端点），配置见 `~/.pyagent/config.toml`。
> 单次模式在终端中运行会触发交互式权限确认；管道/非交互 stdin 时按配置默认策略（`prompt`=自动放行，`deny`=拒绝）。

### Scenario 1 — 自然语言创建文件 ✓
- 命令：`pyagent --cwd _e2e "新建 src/demo.py，定义一个 greet(name) 函数，返回 f'Hello, {name}!'，然后执行它"`
- 步骤：`write_file src/demo.py` → `bash python src/demo.py` → 最终答复
- 结果：`src/demo.py` 内容与描述一致；执行输出 `Hello, World!`。日志摘录：
  ```
  ⟳ [write_file] {"path": "src/demo.py", "content": "def greet(name):\n    return f'Hello, {na...}
  ✓ write_file
  ⟳ [bash] {"command": "python src/demo.py"}
  ✓ bash
  完成。已新建 src/demo.py：…执行结果如下：Hello, World!
  ```

### Scenario 2 — 修复 bug ✓
- 前置：注入 bug `return f'Hello, {nam}!'`（NameError，运行退出码 1）
- 命令：`pyagent --cwd _e2e "src/demo.py 里有个 bug，让它跑起来"`
- 步骤：`read_file` → 定位 `{nam}` 应为 `{name}` → `edit_file` → `bash cd src && python demo.py`
- 结果：修复后 `python demo.py` 退出码 0，输出 `Hello, World!`；Agent 说明修复点。
  ```
  ⟳ [read_file] {"path": "src/demo.py"}  ✓ read_file
  ⟳ [edit_file] {"path": "src/demo.py", "old_string": "    return f'Hello, {nam}!'", ...}  ✓ edit_file
  ⟳ [bash] {"command": "cd src && python demo.py"}  ✓ bash
  跑起来了，输出 Hello, World!。Bug 原因是 f-string 里写了未定义的变量 nam…
  ```

### Scenario 3 — 危险命令被拦截 ✓
- 命令：`pyagent --cwd _e2e/s3 "删除当前目录下的所有文件"`（在含 `keep.txt`、`keep2.md` 的测试目录执行）
- 步骤：Agent 尝试 `bash ls -la` → 权限确认弹窗 → deny → 改用只读工具 → 明确拒绝删除
- 结果：两文件原样保留，目录未被破坏。日志摘录：
  ```
  ⚠  bash requested on: ls -la    → (deny)
  ✗ bash  Error: bash denied by user: ls -la
  The bash command was denied. Let me try using the available tools…
  I will not delete these files…
  === dir intact check ===  keep.txt  keep2.md  均在
  ```

### Scenario 4 — 会话恢复 ✓
- 步骤：TUI 中完成对话 `1+1=?`→`2` → `/quit` 退出（自动落盘 `20260805-212124-fc4424.json`）→ `pyagent --resume 20260805-212124-fc4424` → 继续提问 `7乘8等于几？`
- 结果：历史完整恢复（system/user/assistant 5 条消息），模型接续上下文回答 `56`。
  ```
  session 20260805-212124-fc4424 | messages: 5
   user : '用一句话回答：1+1等于几？'  assistant : '2'
   user : '很好，还是用一句话回答：7乘8等于几？'  assistant : '56'
  ```

---

## 六、桌面 GUI 扩展验收记录（v1.5，2026-08-05）

> 在 v1（F1–F8 全通过）基础上新增桌面 GUI：`src/pyagent/gui/`（pywebview 原生窗口 + Python 标准库 HTTP/SSE 服务 + Codex 风格前端）。技术选型：`pywebview` + 本地回环服务；后端零新依赖。已随 v1 一并推送到 GitHub（`b8a5d80`）。

| # | 检查项 | 命令/步骤 | 结果 | 证据 |
|---|---|---|---|---|
| G1 | 安装 | `pip install -e ".[dev,gui]"` | 通过 | pywebview 6.2.1 安装成功，`pyagent` 命令可用 |
| G2 | CLI 接入 | `pyagent gui --help`；`pyagent --version` 回归 | 通过 | 输出 `usage: pyagent gui [...]`；`pyagent 0.1.0` 不受影响 |
| G3 | 服务端点 | `GET /api/health`、`GET /api/sessions`、`POST /api/new|resume|chat|permission|diff` | 通过 | `tests/test_gui.py::TestServer`（urllib，含 404/409 分支） |
| G4 | SSE 流式 + 权限批准 E2E | reader 线程连接 `/api/stream`，收到 `permission` 事件即 POST 批准 | 通过 | 事件序列 `snapshot→assistant_delta→tool_start→permission→tool_result→…→final→run_end`，文件写入正确 |
| G5 | 真实模型闭环 | 真实 DeepSeek 创建文件 + bash 读取 | 通过 | `gui_demo.txt` 内容 `gui works`；两个工具均走权限弹窗 |
| G6 | 渲染器阻塞确认 | `confirm_permission`/`show_diff` 阻塞、由 POST 解除；超时抛错 | 通过 | `tests/test_gui.py::TestRenderer` |
| G7 | 质量 | `pytest`、`ruff check .` | 通过 | 62 passed；All checks passed |
