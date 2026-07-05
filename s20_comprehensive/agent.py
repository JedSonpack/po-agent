"""核心 agent 循环（s20）：全部机制综合（tool_pool + mcp_servers 提示段）。"""
from typing import Callable

from s20_comprehensive.system_prompt import build_context, get_system_prompt
from s20_comprehensive.recovery import (RecoveryState, with_retry, is_prompt_too_long_error,
                                           DEFAULT_MAX_TOKENS, ESCALATED_MAX_TOKENS,
                                           MAX_RECOVERY_RETRIES, CONTINUATION_PROMPT)
from s20_comprehensive.background import (should_run_background, start_background_task,
                                             collect_background_results)
from s20_comprehensive.cron import consume_cron_queue


def _stringify(content) -> str:
    """把消息 content 转成字符串快照（保真用）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(getattr(b, "text", "")) for b in content
                        if getattr(b, "type", None) == "text")
    return str(content)


def agent_loop(*, client, model, context, tools, messages, run_tool,
               trigger: Callable, nag=None, compact=None, memory=None,
               max_tokens: int = DEFAULT_MAX_TOKENS, tool_pool=None) -> None:
    state = RecoveryState(current_model=model)
    current_max_tokens = max_tokens
    # s09: 每轮注入相关记忆
    memories_content = memory.load_memories(messages) if memory else ""
    memory_turn = (len(messages) - 1) if (memory and messages
                                          and isinstance(messages[-1].get("content"), str)) else None
    while True:
        # s19: tool_pool 提供时每轮刷新 tools/run_tool（connect_mcp 后下轮自动纳入 MCP 工具）
        if tool_pool is not None:
            tools = tool_pool.tools
            run_tool = tool_pool.run_tool
        # s14: 消费已触发的 cron 任务 → 注入 [Scheduled] 消息
        for job in consume_cron_queue():
            messages.append({"role": "user", "content": f"[Scheduled] {job.prompt}"})
        # s09: 压缩前 stringify 快照（提取保真）
        pre_compress = ([{"role": m.get("role", ""), "content": _stringify(m.get("content", ""))}
                         for m in messages] if memory else None)
        # s10: 每轮重算 context（重读 memory 索引）+ 组装 system prompt（缓存）
        ctx = build_context(
            cwd=context.get("cwd", ""),
            tools=tools,
            skills_catalog=context.get("skills_catalog", ""),
            memories=(memory.build_index_section().strip() if memory else ""),
        )
        sys_prompt = get_system_prompt(ctx)
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
            # s11: with_retry 包 LLM 调用（429/529 退避）；默认参数捕获 mt/mdl
            response = with_retry(
                lambda mt=current_max_tokens, mdl=state.current_model: client.messages.create(
                    model=mdl, system=sys_prompt, messages=request_messages,
                    tools=tools, max_tokens=mt),
                state)
        except Exception as e:
            # s11: prompt_too_long → reactive compact（1 次）；否则优雅返回
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
            # s13: 慢操作后台派发（PreToolUse 后、同步执行前）
            if should_run_background(block.name, block.input):
                bg_id = start_background_task(block, run_tool)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"[Background task {bg_id} started] "
                                           f"Command: {block.input.get('command', '')}. "
                                           f"Result will be available when complete."})
                continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)
            if nag and block.name == "todo_write":    # s05: todo_write 归零
                nag.on_todo_write()
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        # s13: 收集后台通知，作 text block 追加（results 在前、通知在后）
        user_content = list(results)
        notifications = collect_background_results()
        if notifications:
            for notif in notifications:
                user_content.append({"type": "text", "text": notif})
        messages.append({"role": "user", "content": user_content})
