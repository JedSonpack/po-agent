# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目

po-agent 逐步重实现 [`learn-claude-code`](https://github.com/shareAI-lab/learn-claude-code)（20 个阶段 s01–s20）。参考教程在同级目录 `../learn-claude-code/`，每个阶段对应其 `sNN_*` 目录，是**行为的真实来源**。当前进度见 `PROGRESS.md`。

## 常用命令

所有命令从 **po-agent 根目录**运行（`python -m sNN_*` 才能找到包）。

```sh
# 一次性环境（不在本机装 Python，用 uv 隔离）
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install pytest            # 测试依赖，未列入 requirements.txt

# 跑某个阶段（交互式 REPL）
python -m s01_agent_loop
python -m s02_tool_use

# 跑测试——用显式阶段路径（上级目录 claude-code-done/ 的 pyproject.toml 会让裸 `pytest` 的 rootdir 错位）
pytest s01_agent_loop/tests s02_tool_use/tests -v

# 单个测试
pytest s01_agent_loop/tests/test_tools.py::test_timeout -v
```

无 lint 配置。

## 架构

**每阶段一个独立自包含包**（`s01_agent_loop/`、`s02_tool_use/`、…），镜像 learn-claude-code 的阶段划分。阶段之间**不共享代码**——这是刻意的学习设计（每阶段是完整可跑的例子），不是技术债。新阶段开新包，复制上一阶段循环结构再叠加机制。

每个阶段包布局一致：
- `config.py` — env 加载（`load_dotenv` + ARK 鉴权处理）、`make_tools()`、`build_system_prompt()`、`load()` 组装 client/model/system/tools
- `tools.py` — 工具实现 + `TOOL_HANDLERS` 字典 + `run_tool` 分发器
- `agent.py` — `agent_loop` 核心循环
- `cli.py` / `__main__.py` — REPL 入口（`python -m sNN_*`）
- `tests/` — mock 单测

**核心循环是稳定基座**：`agent_loop` 就是一个 `while True`——调 LLM → 模型调工具（`stop_reason == "tool_use"`）就执行并把结果喂回、继续；不调就退出。**循环本身跨阶段几乎不变**，每阶段在它上面叠加一个机制（s01: 循环+bash；s02: +5 工具+查表分发+`safe_path`；s03: +权限门；…）。

**依赖注入是可测性的关键**：`agent_loop(*, client, model, system, tools, messages, run_tool, on_tool_use=None)` 把所有依赖作为参数传入。测试用 fake client（预设 response）+ fake `run_tool`，**绝不发真实 API**。`run_tool` 这条缝随阶段演进：s01 是 `run_tool(command)`（只有 bash），s02 升级为 `run_tool(name, input)`（查 `TOOL_HANDLERS` 分发）；后续阶段在这条缝上继续扩展。

**工具沙箱**：`tools.WORKDIR = Path.cwd()` 是文件工具的根；`safe_path` 把 read/write/edit/glob 的路径锁在 WORKDIR 内。但 `bash` 不受 `safe_path` 约束（只有简陋危险命令黑名单）——已知缺口，s03 Permission 会补。

## 模型与密钥

- GLM via Volcengine ARK 的 Anthropic 兼容端点：`ANTHROPIC_BASE_URL=https://ark.cn-beijing.volces.com/api/coding`。
- `MODEL_ID=glm-5.2`。**`/api/coding` 端点不支持 `glm-5.1`**（返回 404 UnsupportedModel）——别改回 5.1。
- glm-5.2 是推理模型：response 里 `ThinkingBlock`（`type == "thinking"`）在 `TextBlock`/`ToolUseBlock` 之前。遍历 `response.content` 时**按 `block.type` 分发**，跳过 thinking 块。
- 密钥只在 `.env`（Python 应用，`ANTHROPIC_API_KEY`）和 `.claude/settings.local.json`（Claude Code CLI），均 gitignored。`.env.example` 与 `.claude/settings.json` 是提交的模板/非密配置。

## 工作流约定

- **新阶段走 superpowers 流程**：brainstorming → 设计规格（`docs/superpowers/specs/YYYY-MM-DD-sNN-*.md`）→ 实现计划（`docs/superpowers/plans/...`）→ TDD 执行。完成后更新 `PROGRESS.md`（对应行 ⬜→✅ + 补「已完成阶段详情」一节）。
- **每阶段 README 带 `## 本阶段完成（相对 sNN-1）`** 一节（~200 字：做了什么 + 比上阶段多了什么）。
- **TDD**：先写失败测试 → 实现 → 通过 → 每个任务一个 commit。测试 mock 化，不发真实 API。
- **行为对齐 learn-claude-code/sNN**，结构重构（包 + DI + TDD）。参考的 `code.py` 是行为基准；"严格对齐"指行为一致，不指代码照搬。
- 在 `main` 分支上工作，commit 用约定式前缀：`feat(sNN)` / `fix(sNN)` / `docs(sNN)` / `chore(sNN)`。
