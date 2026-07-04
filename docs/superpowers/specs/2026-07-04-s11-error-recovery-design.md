# s11 Error Recovery — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第十一阶段（对应 `learn-claude-code/s11_error_recovery`）
- 状态：自主模式
- 前置：s10 已完成

## 1. 背景与目标

s10 的 LLM 调用只有 s08 的 reactive_compact（prompt_too_long 重试 1 次）+ 未捕获异常上抛。s11 给 LLM 调用套**韧性外壳**，按错误类型走三条恢复路径：
- **输出截断**（`stop_reason=="max_tokens"`）→ 升级 token 上限（1 次，不 append 截断输出）→ 续写提示（最多 3 次）。
- **上下文超限**（prompt_too_long）→ reactive_compact（1 次）；复用 s08 `Compactor.reactive_compact`。
- **临时故障**（429 限流 / 529 过载）→ `with_retry` 指数退避重试（最多 10 次），529 连续 3 次切备用模型。
- 不可恢复 → 优雅追加 `[Error]` 消息并返回（不崩 REPL）。

**目标**：行为对齐 s11 恢复机制，沿用包 + DI + TDD。新模块 `recovery.py`（`RecoveryState`/`with_retry`/`retry_delay`/`is_prompt_too_long_error` + 常量）；`agent_loop` LLM 调用包 `with_retry`，加 max_tokens 升级/续写、outer except 优雅返回。保留 s10 全部机制。无新工具。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），恢复机制行为严格对齐 |
| 累积结构 | **保留 s10 全部**（段落化 system prompt + hooks/nag/compact/memory/skills/subagent/9 工具）；s11 参考为教学聚焦简化 loop（去 hooks/nag/skills/compact-tool/memory），po-agent 不跟随 |
| RecoveryState | `RecoveryState(current_model=model)`：has_escalated/recovery_count/consecutive_529/has_attempted_reactive_compact/current_model。循环内局部持有 |
| with_retry | `with_retry(fn, state)`：429（名含 ratelimit 或 msg 含 429）/529（名含 overloaded 或 msg 含 529/overloaded）→ `retry_delay(attempt)` 退避重试，最多 `MAX_RETRIES=10`；529 累加 consecutive_529，达 `MAX_CONSECUTIVE_529=3` 切 `FALLBACK_MODEL`（若有）并归零；成功归零 consecutive_529；非瞬态 re-raise；耗尽 raise RuntimeError |
| retry_delay | `retry_delay(attempt, retry_after=None)`：`retry_after` 优先；否则 `min(500×2^attempt, 32000)/1000 + uniform(0, base×0.25)` |
| is_prompt_too_long_error | 字符串匹配：`prompt is too long`/`prompt_is_too_long`/`prompt_too_long`/`context_length_exceeded`/`max_context_window`/`too many tokens`（参考串 + po-agent s08 串的并集，保 s08 测试兼容） |
| max_tokens 升级 | `stop_reason=="max_tokens"` 且 `not has_escalated` → `current_max_tokens=ESCALATED_MAX_TOKENS`（默认 64000，可 env `ESCALATED_MAX_TOKENS` 覆盖），不 append，`continue` 重试 |
| 续写 | 升级后仍 max_tokens → append 截断 content + `CONTINUATION_PROMPT` user 消息，`recovery_count++`（≤`MAX_RECOVERY_RETRIES=3`）；超限 return |
| outer except | prompt_too_long 且未 reactive 过 → `compact.reactive_compact`（1 次，`has_attempted_reactive_compact=True`）continue；否则 append `[Error] {type}: {msg[:200]}` + return（优雅退出，对齐参考；**s08 的 raise 改为优雅返回**） |
| lambda 捕获 | `with_retry(lambda mt=current_max_tokens, mdl=state.current_model: create(model=mdl, ..., max_tokens=mt), state)`——默认参数捕获，对齐参考：with_retry 内重试用旧 mt/mdl，fallback/升级下一轮外层迭代才生效 |
| s08 reactive 复用 | 复用 `Compactor.reactive_compact`（LLM 总结，比参考"留最后 5 条"丰富）；不引入参考 standalone reactive_compact。s08 的 `reactive_retries` 计数器替换为 `state.has_attempted_reactive_compact` 布尔（等价 1 次） |
| compact.is_prompt_too_long | agent_loop 改用 `recovery.is_prompt_too_long_error`（统一）；`Compactor.is_prompt_too_long` 保留不动（向后兼容） |
| 无新工具 | TOOLS 仍 9 |

## 3. 结构

```
po-agent/s11_error_recovery/
├── __init__.py
├── recovery.py      # 新：RecoveryState + with_retry + retry_delay + is_prompt_too_long_error + 常量
├── config.py        # s10 原样
├── tools.py         # s10 原样
├── skills.py        # s10 原样
├── hooks.py         # s10 原样
├── todo.py          # s10 原样
├── subagent.py      # s10 原样
├── compact.py       # s10 原样
├── memory.py        # s10 原样
├── system_prompt.py # s10 原样
├── agent.py         # s10 + recovery 集成（with_retry + max_tokens 升级/续写 + 优雅返回）
├── cli.py           # s10 原样
├── __main__.py
├── README.md
└── tests/           # test_recovery(新) / test_agent(+recovery, 改 unrelated-error) / 其余 s10 原样
```

## 4. 核心新增：recovery.py

```python
import os
import random
import time

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = int(os.getenv("ESCALATED_MAX_TOKENS", "64000"))
MAX_RETRIES = 10
MAX_CONSECUTIVE_529 = 3
MAX_RECOVERY_RETRIES = 3
BASE_DELAY_MS = 500
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")  # None if unset
CONTINUATION_PROMPT = "Please continue from where you left off."

_PROMPT_TOO_LONG_MARKERS = ("prompt is too long", "prompt_is_too_long", "prompt_too_long",
                            "context_length_exceeded", "max_context_window", "too many tokens")


class RecoveryState:
    def __init__(self, current_model=None):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        self.current_model = current_model


def retry_delay(attempt, retry_after=None):
    if retry_after:
        return retry_after
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    jitter = random.uniform(0, base * 0.25)
    return base + jitter


def is_prompt_too_long_error(e) -> bool:
    s = str(e).lower()
    return any(m in s for m in _PROMPT_TOO_LONG_MARKERS)


def with_retry(fn, state: RecoveryState):
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            name = type(e).__name__.lower()
            msg = str(e).lower()
            if "ratelimit" in name or "429" in msg:
                time.sleep(retry_delay(attempt))
                continue
            if "overloaded" in name or "529" in msg or "overloaded" in msg:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529:
                    if FALLBACK_MODEL:
                        state.current_model = FALLBACK_MODEL
                    state.consecutive_529 = 0
                time.sleep(retry_delay(attempt))
                continue
            raise
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")
```

## 5. agent_loop 集成（agent.py）

s10 agent_loop + recovery：
```python
from s11_error_recovery.recovery import (RecoveryState, with_retry, is_prompt_too_long_error,
    DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS, MAX_RECOVERY_RETRIES, CONTINUATION_PROMPT)

def agent_loop(*, client, model, context, tools, messages, run_tool, trigger,
               nag=None, compact=None, memory=None, max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
    state = RecoveryState(current_model=model)
    current_max_tokens = max_tokens
    memories_content = memory.load_memories(messages) if memory else ""
    memory_turn = (len(messages) - 1) if (memory and messages
                                          and isinstance(messages[-1].get("content"), str)) else None
    while True:
        pre_compress = ([{"role": m.get("role", ""), "content": _stringify(m.get("content", ""))}
                         for m in messages] if memory else None)
        ctx = build_context(cwd=context.get("cwd", ""), tools=tools,
                            skills_catalog=context.get("skills_catalog", ""),
                            memories=(memory.build_index_section().strip() if memory else ""))
        sys_prompt = get_system_prompt(ctx)
        if compact:
            compact.run_pipeline(messages)
            if compact.should_auto_compact(messages):
                print("[auto compact]")
                compact.compact_history(messages)
        if nag:
            reminder = nag.maybe_nag(messages)
            if reminder:
                messages.append({"role": "user", "content": reminder})
        try:
            request_messages = messages
            if memory and memories_content and memory_turn is not None and memory_turn < len(messages):
                request_messages = messages.copy()
                request_messages[memory_turn] = {**messages[memory_turn],
                                                 "content": memories_content + "\n\n" + messages[memory_turn]["content"]}
            response = with_retry(
                lambda mt=current_max_tokens, mdl=state.current_model: client.messages.create(
                    model=mdl, system=sys_prompt, messages=request_messages,
                    tools=tools, max_tokens=mt),
                state)
        except Exception as e:
            if (compact and is_prompt_too_long_error(e)
                    and not state.has_attempted_reactive_compact):
                print("[reactive compact]")
                state.has_attempted_reactive_compact = True
                compact.reactive_compact(messages)
                continue
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": f"[Error] {type(e).__name__}: {str(e)[:200]}"}]})
            return
        # s11: max_tokens → 升级（1 次，不 append）→ 续写（3 次）
        if response.stop_reason == "max_tokens":
            if not state.has_escalated:
                state.has_escalated = True
                current_max_tokens = ESCALATED_MAX_TOKENS
                print(f"[max_tokens] escalating to {ESCALATED_MAX_TOKENS}")
                continue
            messages.append({"role": "assistant", "content": response.content})
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                state.recovery_count += 1
                print("[max_tokens] requesting continuation")
                continue
            return
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            if memory:
                memory.extract_memories(pre_compress)
                memory.consolidate_memories()
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
            if block.name == "compact":
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

## 6. config.py / cli.py

- config.py：s10 原样。
- cli.py：s10 原样（recovery 是 agent_loop 内部机制，无需接线）。

## 7. 测试策略

- **test_recovery.py**（新）：
  - `retry_delay`：attempt=0 base=0.5 + jitter ∈ [0.5, 0.625]；retry_after 优先；attempt 大 base ≤32（jitter ≤8）
  - `is_prompt_too_long_error`：各 marker True；"network down" False
  - `with_retry` 429：第一次抛（名 RateLimitError 或 msg 429）第二次成功 → 返第二次，sleep 调用
  - `with_retry` 429 连续 10 次 → RuntimeError（mock sleep）
  - `with_retry` 529 连续 3 次 + FALLBACK_MODEL set → state.current_model 切换、consecutive_529 归零（monkeypatch recovery.FALLBACK_MODEL）
  - `with_retry` 529 连续 3 次 + FALLBACK_MODEL=None → current_model 不变、归零
  - `with_retry` 529 后成功 → consecutive_529 归零
  - `with_retry` 非瞬态（ValueError）→ 立即 re-raise，不 sleep
- **test_agent.py**：s10 的 17 个 sed 复制；改 `test_reactive_does_not_swallow_unrelated_error` → `test_unrelated_error_exits_gracefully`（不 reactive、append `[Error]`、return 不抛）；加 max_tokens 测试：
  - 首次 max_tokens → 升级（current_max_tokens 变 ESCALATED，不 append，第二次用 ESCALATED 调用）
  - 升级后仍 max_tokens → append 截断 + CONTINUATION_PROMPT，recovery_count==1
  - 续写 3 次仍 max_tokens → return
  - max_tokens 后恢复正常 → 正常 append 返回
  - with_retry 429 在 agent_loop 内：FakeClient 第一次抛 429 第二次成功（mock sleep）→ 正常继续
- 其余 test_*：s10 原样 sed 改名。

## 8. 行为对齐验收

- 全量测试通过（s01-s11）。
- 实时冒烟：`echo '列出当前目录的 .py 文件' | python -m s11_error_recovery` → 正常跑通（recovery 路径正常情况不触发，但不应崩溃）。

## 9. 范围外（YAGNI）

- CC 真实的 `collapse_drain_retry`/`model_error`/`image_error`/`aborted_streaming`/`aborted_tools`/`stop_hook_*`/`token_budget_continuation`/`blocking_limit`/`max_turns` 等 reason——参考只展开前 5 种，po-agent 只做 429/529/prompt_too_long/max_tokens。
- Retry-After header 提取（参考 `retry_delay` 支持但 with_retry 未传；po-agent 同）。
- 真实 API 级重试的指数退避策略调优。
