"""核心 agent 循环（s04）：扩展逻辑挂在 hook 上，循环只调 trigger。"""
from typing import Callable


def agent_loop(*, client, model, system, tools, messages, run_tool,
               trigger: Callable, max_tokens: int = 8000) -> None:
    while True:
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
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
