"""核心 agent 循环（s02）：与 s01 结构一致，工具执行改为按名字分发。"""
from typing import Callable, Optional


def agent_loop(
    *,
    client,
    model: str,
    system: str,
    tools: list,
    messages: list,
    run_tool: Callable[[str, dict], str],
    max_tokens: int = 8000,
    on_tool_use: Optional[Callable[[str, str], None]] = None,
) -> None:
    while True:
        response = client.messages.create(
            model=model, system=system, messages=messages,
            tools=tools, max_tokens=max_tokens,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = run_tool(block.name, block.input)
                if on_tool_use:
                    on_tool_use(block.name, output)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
        messages.append({"role": "user", "content": results})
