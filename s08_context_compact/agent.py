"""核心 agent 循环（s08）：s07 + 四层压缩管线 + compact 工具 + reactive。"""
from typing import Callable


def agent_loop(*, client, model, system, tools, messages, run_tool,
               trigger: Callable, nag=None, compact=None, max_tokens: int = 8000) -> None:
    reactive_retries = 0
    while True:
        if compact:  # s08: 管线（便宜优先，0 API 调用）
            compact.run_pipeline(messages)
            if compact.should_auto_compact(messages):  # L4: 仍超阈值 → LLM 总结
                print("[auto compact]")
                compact.compact_history(messages)
        if nag:  # s05: nag（auto-compact 后，reminder 存活）
            reminder = nag.maybe_nag(messages)
            if reminder:
                messages.append({"role": "user", "content": reminder})
        try:
            response = client.messages.create(
                model=model, system=system, messages=messages,
                tools=tools, max_tokens=max_tokens,
            )
            reactive_retries = 0
        except Exception as e:  # s08: reactive 紧急压缩
            if (compact and compact.is_prompt_too_long(e)
                    and reactive_retries < compact.max_reactive_retries):
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
        if nag:  # s05: tool 轮计数
            nag.on_round()
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "compact":  # s08: compact 工具 special-case（不走 run_tool/hook）
                compact.compact_history(messages)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "[Compacted. Conversation history has been summarized.]"})
                break
            blocked = trigger("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)
            if nag and block.name == "todo_write":  # s05: todo_write 归零
                nag.on_todo_write()
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
