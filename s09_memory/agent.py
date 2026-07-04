"""核心 agent 循环（s09）：s08 + memory（注入索引/相关记忆 + turn 结束提取+整合）。"""
from typing import Callable


def _stringify(content) -> str:
    """把消息 content 转成字符串快照（保真用）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(getattr(b, "text", "")) for b in content
                        if getattr(b, "type", None) == "text")
    return str(content)


def agent_loop(*, client, model, system, tools, messages, run_tool,
               trigger: Callable, nag=None, compact=None, memory=None,
               max_tokens: int = 8000) -> None:
    reactive_retries = 0
    # s09: 每轮注入相关记忆 + system 加索引（per turn）
    memories_content = memory.load_memories(messages) if memory else ""
    memory_turn = (len(messages) - 1) if (memory and messages
                                          and isinstance(messages[-1].get("content"), str)) else None
    sys_prompt = system + (memory.build_index_section() if memory else "")
    while True:
        # s09: 压缩前 stringify 快照（提取保真）
        pre_compress = ([{"role": m.get("role", ""), "content": _stringify(m.get("content", ""))}
                         for m in messages] if memory else None)
        if compact:                                   # s08: 管线（便宜优先）
            compact.run_pipeline(messages)
            if compact.should_auto_compact(messages):
                print("[auto compact]")
                compact.compact_history(messages)
        if nag:                                       # s05: nag
            reminder = nag.maybe_nag(messages)
            if reminder:
                messages.append({"role": "user", "content": reminder})
        try:
            request_messages = messages
            if memory and memories_content and memory_turn is not None and memory_turn < len(messages):
                request_messages = messages.copy()
                request_messages[memory_turn] = {
                    **messages[memory_turn],
                    "content": memories_content + "\n\n" + messages[memory_turn]["content"],
                }
            response = client.messages.create(
                model=model, system=sys_prompt, messages=request_messages,
                tools=tools, max_tokens=max_tokens,
            )
            reactive_retries = 0
        except Exception as e:                        # s08: reactive
            if (compact and compact.is_prompt_too_long(e)
                    and reactive_retries < compact.max_reactive_retries):
                print("[reactive compact]")
                compact.reactive_compact(messages)
                reactive_retries += 1
                continue
            raise
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            if memory:                                # s09: turn 结束提取+整合
                memory.extract_memories(pre_compress)
                memory.consolidate_memories()
            force = trigger("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return
        if nag:                                       # s05: tool 轮计数
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
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)
            if nag and block.name == "todo_write":    # s05: todo_write 归零
                nag.on_todo_write()
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
