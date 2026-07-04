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
        # 工具不是 Claude 自己说的话，所以不能放 assistant。Anthropic 也没有通用 tool role；
        # 工具结果必须作为紧跟 tool_use 后的 user message，以 tool_result block 形式返回，并用 tool_use_id 关联调用。
        # 这样模型会把它理解为“外部环境/客户端返回的观察结果”，再继续推理生成下一条 assistant 回复
        messages.append({"role": "user", "content": results})
