# GOAL.md — 目标契约

> 本文件是 goal 模式的契约。描述**要建成什么**以及**怎么算完成**。
> 配套文件：[ACCEPTANCE.md](./ACCEPTANCE.md) 定义了逐条可执行的验收标准。

- **Goal id**: `agent-v1`
- **Title**: 用 Python 构建一个 Codex 风格的终端编码 Agent（CLI + TUI）
- **Objective**: 构建一个运行在本地的 Python 终端编码 Agent：用户用自然语言下达编码任务，Agent 通过「思考 → 调用工具（读写文件、搜索、执行命令）→ 观察结果 → 继续」的循环自主完成工作，并提供一个交互式终端 UI（流式输出、diff 预览、权限确认）。
- **Parent goal**: 无（新项目）

---

## 1. 背景与参考

本项目参考已有开源实现，而非从零发明架构：

| 项目 | 借鉴点 |
|---|---|
| [OpenAI Codex](https://github.com/openai/codex)（Rust） | 分层架构：核心 agent 循环 / 工具层 / 模型供应商抽象 / 界面层彼此解耦 |
| [keen-code](https://github.com/mochow13/keen-code)（Go） | 极简工具集（read/write/edit/glob/grep/bash）、跨轮记忆摘要 |
| [ClawCode](https://github.com/deepelementlab/clawcode)（Python） | 同语言参考，验证 Python 技术选型可行性 |
| [awesome-cli-coding-agents](https://github.com/bradAGI/awesome-cli-coding-agents) | 功能清单与交互模式参考 |

**核心设计原则**：MVP 只保留让「编码循环」成立的最小闭环，界面与隔离能力后置。工具与模型供应商之间用接口解耦，为后续扩展沙箱、MCP、多供应商留好接缝。

## 2. 范围

### 2.1 In scope（v1 必须包含）

- **入口与界面**
  - `python -m pyagent` 启动交互式终端会话；支持单次问答模式（如 `pyagent "创建文件"`）
  - 简单 TUI：LLM 回复流式渲染、工具调用状态显示、编辑前后 diff 预览、权限确认弹窗、退出/中断处理
- **核心 agent 循环**
  - 标准循环：组装消息 → 调用模型 → 若请求工具则执行并回填结果 → 继续，直到模型给出最终答复或达到上限
  - 上下文管理与压缩（历史过长时的摘要策略，参照 keen-code 的 TurnMemory 思路）
- **工具集（6 个核心工具）**
  - `read_file` / `write_file` / `edit_file` / `glob` / `grep` / `bash`
  - `edit_file` 采用「生成补丁 → TUI 预览 → 确认后应用」的方式，失败时返回可诊断的错误
- **权限系统**
  - 危险操作（写文件、执行命令）默认需用户 allow/deny；支持"记住此规则"（per-路径、per-命令前缀）
- **配置**
  - TOML 配置文件：模型供应商、默认模型、权限规则、会话保存目录
- **会话持久化**
  - 对话历史可保存到磁盘、可恢复继续
- **工程质量**
  - 单元测试（pytest）、静态检查（ruff），核心循环与工具必须有测试

### 2.2 Out of scope（v1 明确不做，列入 non-goals）

- 命令沙箱/容器隔离（v1 命令在宿主机直接执行，只靠权限确认兜底）
- MCP 协议支持
- 多模型供应商接入（v1 只接一个 OpenAI 兼容 API，但接口保持抽象）
- 子 Agent / 多 Agent 编排
- IDE / VS Code 集成
- skills 技能系统
- 遥测 / 埋点

## 3. 目标架构

```
pyagent/
  pyproject.toml              # 打包 + console script + dev 依赖
  src/pyagent/
    __main__.py               # python -m pyagent 入口
    cli.py                    # 参数解析、启动交互/单次模式
    config.py                 # TOML 配置加载与校验
    core/
      loop.py                 # ★ 主 agent 循环（消息 ↔ 工具调用）
      model.py                # LLM 客户端接口 + OpenAI 兼容实现
      messages.py             # 会话历史、消息组装、持久化
      context.py              # 上下文压缩/摘要策略
    tools/
      registry.py             # 工具注册表与分发（name → callable + schema）
      files.py                # read_file / write_file / edit_file / glob / grep
      shell.py                # bash 执行（走权限确认）
      permissions.py          # allow/deny 规则与记忆
    tui/
      app.py                  # TUI 主循环
      renderer.py             # 流式渲染、diff 渲染、状态面板
  tests/                      # pytest，core 与 tools 必须覆盖
```

关键接缝（为 v2 预留）：
- `model.py` 暴露统一 `LLMClient` 接口，v2 可并行实现 Anthropic / Ollama 等
- `tools/registry.py` 提供 `register_tool`，v2 可注册 MCP 工具
- `tui/` 与 `core/` 通过事件/回调解耦，v2 可替换为纯 CLI 或 IDE 前端

## 4. Finishing Criteria（完成标准）

**每一项都必须能在 ACCEPTANCE.md 中找到对应的、可执行的验收步骤。全部通过才算完成，缺一不可。**

- [x] **F1 可安装可启动**：`pip install -e .` 成功；`pyagent --version` 输出版本号；`pyagent` 进入交互界面
- [x] **F2 核心循环可用**：真实调用模型时，能从「自然语言 → 连续工具调用 → 最终答复」走完整条闭环；单元测试覆盖 mock 模型下的循环逻辑
- [x] **F3 六个工具全部可用且有测试**：read_file / write_file / edit_file / glob / grep / bash 各自通过单元测试，且在真实目录下操作正确
- [x] **F4 权限系统生效**：写文件与执行命令默认触发确认；允许「记住规则」；deny 后操作不执行并给出明确反馈
- [x] **F5 TUI 可用**：流式输出、工具状态显示、diff 预览+确认应用、权限弹窗、Ctrl+C/`/quit` 正常退出
- [x] **F6 会话持久化**：保存会话后重启可恢复历史并继续
- [x] **F7 端到端验收场景通过**：ACCEPTANCE.md 中 4 个 E2E 剧本全部按剧本走通
- [x] **F8 工程质量达标**：`ruff check .` 通过；`pytest` 全绿；README 说明安装与用法

## 5. Runtime Goal Coupling

维护项目下的 agent 账本：`implementation-notes.html` 记录当前阶段、已完成/进行中/受阻工作、决策与下一步精确动作。在压缩、中断或交接前更新 `Resume Here` 区块与进度时间线。验收结果逐条记录到 ACCEPTANCE.md 的验收记录表。

## 6. Escape Hatch（逃生通道）

遇到以下情况，暂停、向用户提问或把相关项标记为 blocked/incomplete（而非强行"完成"）：

- 验收标准与真实实现矛盾（如某工具在 Windows 上行为与预期不符）
- 需要超出 v1 范围的改动（如必须上沙箱才能让 bash 工具安全可用）
- 在某一验收项上循环尝试却无实质进展
- 下一步可能破坏已完成的验收项或删除有价值的历史
- 技术选型受阻（如所选模型供应商 API 无法满足需求）
