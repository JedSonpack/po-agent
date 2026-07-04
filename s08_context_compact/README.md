# s08: Context Compact

po-agent 第八阶段，参照 `learn-claude-code/s08_context_compact`。在 LLM 调用前插**四层压缩管线**（便宜优先）+ `compact` 工具 + reactive 紧急压缩，防止长对话爆上下文。

## 本阶段完成（相对 s07）

在 s07 循环上做了一件核心事：**上下文压缩（便宜优先、贵最后）**。

1. **四层管线**（`compact.py`，LLM 调用前每轮跑，0 API 调用）：
   - **L1 snip_compact**：消息数 > 50 砍中间（保头 3 + 尾，不拆 tool_use/tool_result 对）。
   - **L2 micro_compact**：旧 tool_result（非最近 3 个）内容 > 120 → 占位符。
   - **L3 tool_result_budget**：末消息 tool_result 总字节 > 200KB → 落盘最大的（>30KB），替换成 `<persisted-output>` 预览。
   - **L4 compact_history**：`estimate_size > 50000` → 落 transcript + LLM 总结，messages 替换成 `[Compacted]\n\n{summary}`。
2. **`compact` 工具**：模型显式调 → `compact_history`，本轮结束、下轮用压缩后上下文（循环 special-case，不走 run_tool/hook）。
3. **reactive_compact**：API 返 `prompt_too_long` → 落 transcript + 总结头部 + 保留尾 5 条，重试 1 次。
4. **`Compactor` 类注入** `agent_loop`（`compact=None` 默认）；保留 s07 的 hooks/nag——压缩与 nag/hooks 正交共存（nag 在 auto-compact 后注入，reminder 存活）。
- **循环加管线**：`run_pipeline`（budget→snip→micro）→ auto-compact 判断 → nag → create（try/except reactive）→ ...；compact 工具 special-case 在 PreToolUse 前。
- 比 s07 多了**上下文回收**：长对话不爆，关键信息落盘/总结保留。

## 结构
- `config.py` — env + `make_tools`(9 含 compact) + `make_sub_tools`(5) + 目录提示 + `load`
- `tools.py` / `skills.py` / `hooks.py` / `todo.py` / `subagent.py` — 同 s07
- `compact.py` — 纯函数（snip/micro/collect/helpers）+ `Compactor`（budget/persist/compact_history/reactive/summarize/transcript）
- `agent.py` — `agent_loop`（注入 `compact`，加管线 + compact 工具 + reactive）
- `cli.py` / `__main__.py` — REPL（接线 `Compactor`）

## 运行
```sh
source ../.venv/bin/activate
python -m s08_context_compact
```

## 使用示例

让 agent 读完一个文件再压缩历史：

```
s08 >> 先用 read_file 读 s07_skill_loading/README.md，然后调用 compact 工具压缩对话历史，告诉我压缩后还剩什么
```

```
[HOOK] read_file(['s07_skill_loading/README.md'])
[transcript saved: .transcripts/transcript_*.jsonl]
```

`compact` 工具触发 `compact_history`——落 transcript + LLM 总结，messages 替换成 `[Compacted]\n\n{summary}`。agent 报告保留（目标/架构/决策）与丢弃（原文逐字/中间细节）。长对话不爆，关键信息落盘/总结保留。

## 测试
```sh
pytest s08_context_compact/tests -v
```
