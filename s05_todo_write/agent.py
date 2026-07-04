"""核心 agent 循环（s05）：s04 + 可选 nag reminder（规划提醒）。"""
from typing import Callable


def agent_loop(*, client, model, system, tools, messages, run_tool,
               trigger: Callable, nag=None, max_tokens: int = 8000) -> None:
    while True:
        if nag:                                   # s05: nag reminder（LLM 调用前）
            reminder = nag.maybe_nag(messages)
            if reminder:
                messages.append({"role": "user", "content": reminder})
        response = client.messages.create(
            model=model, system=system, messages=messages,
            tools=tools, max_tokens=max_tokens,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            force = trigger("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return
        if nag:                                   # s05: tool 轮计数（处理 block 前）
            nag.on_round()
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
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
