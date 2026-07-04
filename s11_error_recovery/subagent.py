"""Subagent — fresh messages[] 跑自己的循环，只返回总结。"""
from typing import Callable


def extract_text(content) -> str:
    """从消息 content blocks 提取文本。"""
    if not isinstance(content, list):
        return str(content)
    return "\n".join(getattr(b, "text", "") for b in content
                     if getattr(b, "type", None) == "text")


class Subagent:
    """子 agent：全新 messages[]，跑自己的循环（max_turns 安全限），只返回总结。

    没有 task 工具 → 不能递归派子。中间过程丢弃，只回最后总结。
    """

    def __init__(self, *, client, model, sub_system: str, sub_tools: list,
                 sub_run_tool: Callable, trigger: Callable,
                 max_turns: int = 30, max_tokens: int = 8000):
        self.client = client
        self.model = model
        self.sub_system = sub_system
        self.sub_tools = sub_tools
        self.sub_run_tool = sub_run_tool
        self.trigger = trigger
        self.max_turns = max_turns
        self.max_tokens = max_tokens

    def run(self, description: str) -> str:
        print(f"\n\033[35m[Subagent spawned]\033[0m")
        messages = [{"role": "user", "content": description}]  # fresh context

        for _ in range(self.max_turns):
            response = self.client.messages.create(
                model=self.model, system=self.sub_system,
                messages=messages, tools=self.sub_tools, max_tokens=self.max_tokens,
            )
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                blocked = self.trigger("PreToolUse", block)
                if blocked:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": str(blocked)})
                    continue
                output = self.sub_run_tool(block.name, block.input)
                self.trigger("PostToolUse", block, output)
                print(f"  \033[90m[sub] {block.name}: {str(output)[:100]}\033[0m")
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
            messages.append({"role": "user", "content": results})

        # fallback：safety limit 命中时 last message 可能是 tool_result（无 text）
        result = extract_text(messages[-1]["content"])
        if not result:
            for msg in reversed(messages):
                if msg["role"] == "assistant":
                    result = extract_text(msg["content"])
                    if result:
                        break
            if not result:
                result = f"Subagent stopped after {self.max_turns} turns without final answer."
        print(f"\033[35m[Subagent done]\033[0m")
        return result  # only summary, entire message history discarded
