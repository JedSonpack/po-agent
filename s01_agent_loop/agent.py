# agent.py —— 核心 agent 循环
#
# 这是整个 agent 的心脏：一个 while 循环。
#   模型调工具 → 执行工具 → 把结果喂回模型 → 继续循环
#   模型不调工具 → 退出循环
#
# 所有依赖（client/model/tools/要执行的工具函数/日志回调）都从参数传进来——
# 这叫"依赖注入"。好处：测试时可以传"假的"client 和工具函数，不用真的调 API。

from typing import Callable, Optional
# Callable[[参数类型...], 返回类型]  用来标注一个函数的类型
# Optional[X]  等价于 X | None，表示"X 或者 None"


def agent_loop(
    *,  # 单独的 * 表示：后面的参数都必须用关键字传递（调用时写 client=...，不能按位置）
    client,                                  # anthropic 客户端（测试时可传假 client）
    model: str,                              # 模型 id，如 "glm-5.2"
    system: str,                             # 系统提示
    tools: list,                             # 工具定义列表
    messages: list,                          # 对话历史（会被原地修改）
    run_tool: Callable[[str], str],          # 执行工具的函数：传命令字符串，返回输出字符串
    max_tokens: int = 8000,                  # 模型单次回复最多 8000 token
    on_tool_use: Optional[Callable[[str, str], None]] = None,  # 可选：工具调用时的日志回调
) -> None:                                   # -> None 表示函数不返回值
    while True:  # 无限循环，靠下面的 return 退出
        # 1) 把当前对话历史发给模型，拿到回复
        response = client.messages.create(
            model=model, system=system, messages=messages,
            tools=tools, max_tokens=max_tokens,
        )

        # 2) 把模型这一轮的回复追加到对话历史
        messages.append({"role": "assistant", "content": response.content})

        # 3) 如果模型没调工具（stop_reason 不是 "tool_use"），说明它做完了，退出循环
        if response.stop_reason != "tool_use":
            return

        # 4) 模型调了工具，逐个执行它要求的工具调用
        results = []
        for block in response.content:          # response.content 是这一轮回复的"块"列表
            if block.type == "tool_use":        # 找到工具调用块（可能还有 text/thinking 块，跳过）
                output = run_tool(block.input["command"])  # 执行命令，拿输出
                # ★ 这就是"日志"被加载/触发的地方 ★
                # 如果调用方传了 on_tool_use 回调，就调用它。
                # cli 传进来的 print_tool_use 会被这里调用，把命令和输出打印出来。
                # 没传（on_tool_use 是 None）就什么都不做——if None 在 Python 里为假。
                if on_tool_use:
                    on_tool_use(block.input["command"], output)
                # 组装一个 tool_result 块，把执行结果回喂给模型
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,     # block.id 把结果和对应的工具调用配对
                    "content": output,
                })

        # 5) 把所有工具结果作为新的"用户消息"追加到历史，回到循环开头让模型继续推理
        messages.append({"role": "user", "content": results})
