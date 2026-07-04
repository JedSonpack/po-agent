# s08 Context Compact — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第八阶段（对应 `learn-claude-code/s08_context_compact`）
- 状态：自主模式
- 前置：s07 已完成

## 1. 背景与目标

s07 的 agent 上下文只增不减，长对话会爆。s08 在 LLM 调用前插入**四层压缩管线**（便宜优先，贵最后）+ `compact` 工具 + 反应式紧急压缩：

- **L1 snip_compact**：消息数 > 50 时砍中间（保留头 3 + 尾，不拆 tool_use/tool_result 对）。
- **L2 micro_compact**：旧 tool_result（非最近 KEEP_RECENT 个）内容 > 120 字符 → 占位符。
- **L3 tool_result_budget**：末消息 tool_result 总字节 > max_bytes → 把最大的（>PERSIST_THRESHOLD）落盘，替换成 `<persisted-output>` 预览。
- **L4 compact_history**：estimate_size > CONTEXT_LIMIT → 落 transcript + LLM 总结，messages 替换成 `[Compacted]\n\n{summary}`。
- **compact 工具**：模型显式调 → compact_history，本轮结束、下轮用压缩后上下文。
- **reactive_compact**：API 返 prompt_too_long → 落 transcript + 总结头部 + 保留尾 5 条，重试（MAX_REACTIVE_RETRIES=1）。

**核心原则**：便宜优先、贵最后；执行序 budget→snip→micro→auto（对齐 CC 源）。

**目标**：行为对齐 s08 的压缩机制，沿用包 + DI + TDD。新机制 `compact.py`（`Compactor` 类 + 纯函数）；`agent_loop` 注入 `compact`，循环加压缩管线 + compact 工具 special-case + reactive try/except。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），压缩机制行为严格对齐 |
| 累积结构 | **保留 s07 的 4 事件 hooks + nag + Stop hook**（po-agent 累积设计）；s08 参考为教学聚焦简化了 hooks/去 nag，po-agent 不跟随该简化——压缩与 nag/hooks 正交，可共存 |
| 功能范围 | 严格对齐 s08：4 层管线 + compact 工具 + reactive；不加 isCompactNeeded/92% 阈值/microCompact trigger 比例等 CC 细节 |
| Compactor DI | `Compactor(*, client, model, context_limit, keep_recent, persist_threshold, transcript_dir, tool_results_dir, max_reactive_retries, summarize_max_tokens)` 注入 `agent_loop`（`compact=None` 默认） |
| 纯函数 vs 方法 | 纯函数（无状态）`estimate_size`/`_block_type`/`_message_has_tool_use`/`_is_tool_result_message`/`collect_tool_results`/`snip_compact`/`micro_compact` 模块级可直测；状态性（client/目录）`tool_result_budget`/`persist_large_output`/`compact_history`/`reactive_compact`/`summarize_history`/`write_transcript` 为 `Compactor` 方法 |
| compact 工具 | 在 `make_tools`（9 工具），**不在** `TOOL_HANDLERS`（循环 special-case，不走 run_tool） |
| 子 agent | 不给 compact（SUB_TOOLS 仍 5）；子 agent 上下文小且短命 |
| 循环集成 | 管线在 LLM 调用前；nag 在 auto-compact 后（reminder 存活）；reactive try/except 包 create |
| 常量 | CONTEXT_LIMIT=50000、KEEP_RECENT=3、PERSIST_THRESHOLD=30000、MAX_REACTIVE_RETRIES=1、budget max_bytes=200_000、snip max_messages=50、summarize 截 80000 字符 |

## 3. 结构

```
po-agent/s08_context_compact/
├── __init__.py
├── config.py     # env + make_tools(9 含 compact) + make_sub_tools(5) + 双提示 + load(scan_skills)
├── tools.py      # s07 原样（8 handlers + SUB_HANDLERS + make_run_tool）
├── compact.py    # 新：纯函数 + Compactor 类（4 层 + compact_history + reactive + transcript + persist）
├── skills.py     # s07 原样
├── hooks.py      # s07 原样
├── todo.py       # s07 原样
├── subagent.py   # s07 原样
├── agent.py      # s07 + 压缩管线 + compact 工具 + reactive（注入 compact）
├── cli.py        # REPL（接线 Compactor）
├── __main__.py
├── README.md
└── tests/        # test_compact(新) / test_tools / test_skills / test_hooks / test_todo / test_subagent / test_agent(+压缩) / test_config
```

## 4. 核心新增：compact.py

### 4.1 模块级纯函数

```python
CONTEXT_LIMIT = 50000
KEEP_RECENT = 3
PERSIST_THRESHOLD = 30000
MAX_REACTIVE_RETRIES = 1
TRANSCRIPT_DIR = Path.cwd() / ".transcripts"
TOOL_RESULTS_DIR = Path.cwd() / ".task_outputs" / "tool-results"

def estimate_size(msgs) -> int: return len(str(msgs))

def _block_type(block):  # dict .get("type") 或 attr .type
def _message_has_tool_use(msg) -> bool:  # assistant 含 tool_use 块
def _is_tool_result_message(msg) -> bool:  # user 含 tool_result 块
def collect_tool_results(messages) -> list[(mi, bi, block)]

def snip_compact(messages, max_messages=50) -> list:
    # >max_messages：keep_head=3, keep_tail=max_messages-3；不拆 tool_use/result 对；
    # head_end>=tail_start → 不砍；返 head + [{"role":"user","content":f"[snipped {n} messages]"}] + tail

def micro_compact(messages, keep_recent=KEEP_RECENT) -> list:
    # tool_results = collect_tool_results；<=keep_recent → 不动；
    # 否则除最后 keep_recent 个外，content>120 → "[Earlier tool result compacted. Re-run if needed.]"
```

### 4.2 Compactor 类

```python
class Compactor:
    def __init__(self, *, client, model, context_limit=CONTEXT_LIMIT, keep_recent=KEEP_RECENT,
                 persist_threshold=PERSIST_THRESHOLD, transcript_dir=TRANSCRIPT_DIR,
                 tool_results_dir=TOOL_RESULTS_DIR, max_reactive_retries=MAX_REACTIVE_RETRIES,
                 summarize_max_tokens=2000): ...

    def run_pipeline(self, messages):
        """L3→L1→L2（0 API 调用）。序：budget → snip → micro。"""
        self.tool_result_budget(messages)
        messages[:] = snip_compact(messages)
        micro_compact(messages, self.keep_recent)

    def tool_result_budget(self, messages, max_bytes=200_000):
        # 末消息 tool_result 总字节 > max_bytes → 按大→小 persist（>persist_threshold），重算 total

    def persist_large_output(self, tool_use_id, output) -> str:
        # <=persist_threshold → 原样；否则落 {tool_results_dir}/{tool_use_id}.txt，
        # 返 f"<persisted-output>\nFull output: {path}\nPreview:\n{output[:2000]}\n</persisted-output>"

    def compact_history(self, messages):
        """L4：落 transcript + LLM 总结，messages[:] = [{"role":"user","content":f"[Compacted]\n\n{summary}"}]。"""
        path = self.write_transcript(messages)
        print(f"[transcript saved: {path}]")
        summary = self.summarize_history(messages)
        messages[:] = [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]

    def reactive_compact(self, messages):
        """紧急：落 transcript + 总结头（保留尾 5，不拆对），messages[:] = [summary, *tail]。"""
        self.write_transcript(messages)
        tail_start = max(0, len(messages) - 5)
        if (tail_start > 0 and tail_start < len(messages)
                and _is_tool_result_message(messages[tail_start])
                and _message_has_tool_use(messages[tail_start - 1])):
            tail_start -= 1
        summary = self.summarize_history(messages[:tail_start])
        messages[:] = [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}, *messages[tail_start:]]

    def summarize_history(self, messages) -> str:
        conversation = json.dumps(messages, default=str)[:80000]
        prompt = ("Summarize this coding-agent conversation so work can continue.\n"
                  "Preserve: 1. current goal, 2. key findings/decisions, 3. files read/changed, "
                  "4. remaining work, 5. user constraints.\nBe compact but concrete.\n\n" + conversation)
        response = self.client.messages.create(model=self.model, messages=[{"role":"user","content":prompt}],
                                               max_tokens=self.summarize_max_tokens)
        return "\n".join(getattr(b,"text","") for b in response.content
                         if getattr(b,"type",None)=="text").strip() or "(empty summary)"

    def write_transcript(self, messages) -> Path:
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        path = self.transcript_dir / f"transcript_{int(time.time())}.jsonl"
        with path.open("w") as f:
            for msg in messages: f.write(json.dumps(msg, default=str) + "\n")
        return path

    def should_auto_compact(self, messages) -> bool:
        return estimate_size(messages) > self.context_limit

    @staticmethod
    def is_prompt_too_long(e) -> bool:
        s = str(e).lower()
        return "prompt_too_long" in s or "too many tokens" in s
```

## 5. agent_loop 集成（agent.py）

```python
def agent_loop(*, client, model, system, tools, messages, run_tool, trigger,
               nag=None, compact=None, max_tokens=8000) -> None:
    reactive_retries = 0
    while True:
        if compact:                                   # s08: 管线（便宜优先）
            compact.run_pipeline(messages)
            if compact.should_auto_compact(messages):
                print("[auto compact]")
                compact.compact_history(messages)
        if nag:                                       # s05: nag（auto-compact 后，reminder 存活）
            reminder = nag.maybe_nag(messages)
            if reminder:
                messages.append({"role": "user", "content": reminder})
        try:
            response = client.messages.create(model=model, system=system, messages=messages,
                                              tools=tools, max_tokens=max_tokens)
            reactive_retries = 0
        except Exception as e:
            if compact and compact.is_prompt_too_long(e) and reactive_retries < compact.max_reactive_retries:
                print("[reactive compact]")
                compact.reactive_compact(messages)
                reactive_retries += 1
                continue
            raise
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            force = trigger("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return
        if nag:
            nag.on_round()
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "compact":               # s08: compact 工具 special-case
                compact.compact_history(messages)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "[Compacted. Conversation history has been summarized.]"})
                break
            blocked = trigger("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(blocked)})
                continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)
            if nag and block.name == "todo_write":
                nag.on_todo_write()
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```

**注意**：compact 工具 special-case 在 PreToolUse 前（不走权限/日志 hook，meta 操作）；break 后统一在 for 外 append results（compact 与非 compact 路径合一，等价参考的 for-else）。

## 6. config.py

- `make_tools()` → 9（s07 的 8 + `compact`）。`compact` schema：`focus`(string, 非 required)，描述 "Summarize earlier conversation to free context space."。
- `load()` 多返无（Compactor 在 cli 构造，需 client/model；同 Subagent 模式）。

## 7. cli.py 接线

```python
compactor = Compactor(client=cfg["client"], model=cfg["model"])
agent_loop(..., run_tool=run_tool, trigger=trigger_hooks, nag=nag, compact=compactor)
```

## 8. 测试策略

- **test_compact.py**（新，最多）：
  - 纯函数：`snip_compact`（<=50 不动 / >50 砍中间插 [snipped N] / 不拆 tool_use-result 对 / head_end>=tail_start 不砍）；`micro_compact`（<=keep_recent 不动 / 旧 content>120 占位 / content<=120 不动）；`collect_tool_results`；`_message_has_tool_use`/`_is_tool_result_message`/`_block_type`；`estimate_size`。
  - Compactor（FakeClient + tmp dirs）：`tool_result_budget`（<=max_bytes 不动 / >max_bytes persist 最大 / content<=persist_threshold 跳过）；`persist_large_output`（<=threshold 原样 / > 落盘返 placeholder）；`compact_history`（落 transcript + summarize + messages[:]=[summary]）；`reactive_compact`（落 transcript + 总结头 + 保留尾、不拆对）；`summarize_history`（返 text / 空 → "(empty summary)"）；`write_transcript`（写 jsonl）；`should_auto_compact`；`is_prompt_too_long`；`run_pipeline`（调 budget/snip/micro）。
- **test_agent.py**：s07 的 7 个（compact=None）+ compact 工具触发 compact_history / reactive 重试 / auto-compact 触发（用 SpyCompactor）。
- **test_config.py**：make_tools 9（含 compact）；make_sub_tools 5。
- 其余 test_*：s07 原样（改包名）。

## 9. 行为对齐验收

- 全量测试通过（s01-s08）。
- 实时冒烟：`echo '先用 read_file 读 s07_skill_loading/README.md，再调用 compact 工具压缩对话历史，告诉我压缩后还剩什么。' | python -m s08_context_compact` → 观察 read_file 工具结果、`compact` 工具触发 `[transcript saved: ...]`、messages 被总结替换、agent 报告压缩后内容。`.transcripts/` 落盘（gitignored）。

## 10. 范围外（YAGNI）

- isCompactNeeded/92% 阈值、microCompact 的 trigger 比例、wU2 量化压缩、按 token 计数（用 len(str) 近似）—教学版简化。
- compact 工具的 focus 参数语义化使用（参考也仅声明 schema 未用）。
