# s11: Error Recovery

po-agent 第十一阶段，参照 `learn-claude-code/s11_error_recovery`。给 LLM 调用套**韧性外壳**：按错误类型走三条恢复路径，不可恢复时优雅退出而不崩 REPL。

## 本阶段完成（相对 s10）

在 s10 循环上做了一件核心事：**LLM 调用的错误重试与恢复**。

1. **`recovery.py`**：
   - **`RecoveryState`**：跨循环迭代跟踪恢复状态（has_escalated / recovery_count / consecutive_529 / has_attempted_reactive_compact / current_model）。
   - **`with_retry(fn, state)`**：429（限流）/529（过载）→ `retry_delay` 指数退避重试（最多 10 次）；529 连续 3 次切 `FALLBACK_MODEL`（若配置）；成功归零 529 计数；非瞬态错误 re-raise。
   - **`retry_delay(attempt, retry_after=None)`**：`min(500×2^attempt, 32000)/1000 + 0~25% 抖动`，Retry-After 优先。
   - **`is_prompt_too_long_error(e)`**：字符串匹配上下文超限（参考串 + s08 串并集）。
   - 常量：`DEFAULT_MAX_TOKENS=8000`、`ESCALATED_MAX_TOKENS=64000`（可 env 覆盖）、`MAX_RETRIES=10`、`MAX_CONSECUTIVE_529=3`、`MAX_RECOVERY_RETRIES=3`、`CONTINUATION_PROMPT`。
2. **`agent_loop` 集成**：
   - LLM 调用包 `with_retry`（默认参数捕获 mt/mdl，对齐参考）。
   - **max_tokens 路径**：`stop_reason=="max_tokens"` → 升级 8K→64K（1 次，不 append 截断输出）→ 续写提示（最多 3 次）→ 仍截断则 return。
   - **outer except**：prompt_too_long → `Compactor.reactive_compact`（1 次，复用 s08 的 LLM 总结版）；不可恢复 → 追加 `[Error] {type}: {msg}` 并 return（**s08 的 raise 改为优雅返回**）。
- **保留 s10 全部**（段落化 system prompt + hooks/nag/compact/memory/skills/subagent/9 工具）——recovery 与这些正交共存。无新工具。
- 比 s10 多了**韧性**：429/529 自动退避重试、输出截断自动升级/续写、上下文超限自动压缩、不可恢复优雅退出。

## 结构
- `recovery.py` — RecoveryState + with_retry + retry_delay + is_prompt_too_long_error + 常量
- `agent.py` — `agent_loop`（with_retry 包 LLM 调用 + max_tokens 升级/续写 + 优雅返回）
- `config.py` / `tools.py` / `skills.py` / `hooks.py` / `todo.py` / `subagent.py` / `compact.py` / `memory.py` / `system_prompt.py` — 同 s10
- `cli.py` / `__main__.py` — 同 s10（recovery 是内部机制，无需接线）

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s11_error_recovery
```

## 使用示例

正常情况下 recovery 路径不触发，agent 行为同 s10：

```
s11 >> 用 glob 工具列出当前目录的 *.py 文件
  [assembled] sections: identity, tools, workspace, skills
  [cache hit] system prompt unchanged
  [HOOK] glob(['*.py'])
  ...
```

恢复路径在异常时自动生效（429/529 退避重试、max_tokens 升级/续写、prompt_too_long reactive compact），无需用户介入。

## 测试
```sh
pytest s11_error_recovery/tests -v
```
