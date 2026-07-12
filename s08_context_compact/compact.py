"""Context Compact — 四层压缩管线 + compact 工具 + reactive 紧急。

便宜优先、贵最后。执行序：budget → snip → micro → auto(L4)。
"""
import json
import time
from pathlib import Path

CONTEXT_LIMIT = 50000
KEEP_RECENT = 3
PERSIST_THRESHOLD = 30000
MAX_REACTIVE_RETRIES = 1
TRANSCRIPT_DIR = Path.cwd() / ".transcripts"
TOOL_RESULTS_DIR = Path.cwd() / ".task_outputs" / "tool-results"


def estimate_size(msgs) -> int:
    return len(str(msgs))


def _block_type(block):
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def _message_has_tool_use(msg) -> bool:
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(_block_type(block) == "tool_use" for block in content)


def _is_tool_result_message(msg) -> bool:
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(block, dict) and block.get("type") == "tool_result"
               for block in content)


def collect_tool_results(messages) -> list:
    """返回 [(message_index, block_index, block)] 所有 tool_result 块。"""
    blocks = []
    for mi, msg in enumerate(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for bi, block in enumerate(msg["content"]):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                blocks.append((mi, bi, block))
    return blocks


# L1: snipCompact — 消息数 > max_messages 时砍中间
def snip_compact(messages, max_messages=50):
    if len(messages) <= max_messages:
        return messages
    keep_head, keep_tail = 3, max_messages - 3
    head_end, tail_start = keep_head, len(messages) - keep_tail
    # 不拆 tool_use/tool_result 对（头）：head 前一条是 tool_use → 推进 head_end 越过 tool_result
    if head_end > 0 and _message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and _is_tool_result_message(messages[head_end]):
            head_end += 1
    # 不拆对（尾）：tail_start 是 tool_result 且前一条 tool_use → 包进尾
    if (tail_start > 0 and tail_start < len(messages)
            and _is_tool_result_message(messages[tail_start])
            and _message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    if head_end >= tail_start:
        return messages
    snipped = tail_start - head_end
    return messages[:head_end] + [{"role": "user", "content": f"[snipped {snipped} messages]"}] + messages[tail_start:]


# L2: microCompact — 旧 tool_result 占位
def micro_compact(messages, keep_recent=KEEP_RECENT):
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= keep_recent:
        return messages
    for _, _, block in tool_results[:-keep_recent]:
        if len(block.get("content", "")) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages


class Compactor:
    """四层压缩 + reactive。client/model 用于 L4 总结；目录用于落盘。"""

    def __init__(self, *, client, model, context_limit=CONTEXT_LIMIT, keep_recent=KEEP_RECENT,
                 persist_threshold=PERSIST_THRESHOLD, transcript_dir=TRANSCRIPT_DIR,
                 tool_results_dir=TOOL_RESULTS_DIR, max_reactive_retries=MAX_REACTIVE_RETRIES,
                 summarize_max_tokens=2000):
        self.client = client
        self.model = model
        self.context_limit = context_limit
        self.keep_recent = keep_recent
        self.persist_threshold = persist_threshold
        self.transcript_dir = Path(transcript_dir)
        self.tool_results_dir = Path(tool_results_dir)
        self.max_reactive_retries = max_reactive_retries
        self.summarize_max_tokens = summarize_max_tokens

    def run_pipeline(self, messages):
        """L3→L1→L2（0 API 调用）。序：budget → snip → micro。"""
        # L3: 将最近一次的工具返回结果 进行裁剪，防止让大块tool结果落到 Context Window
        self.tool_result_budget(messages)
        # L1:
        messages[:] = snip_compact(messages)
        micro_compact(messages, self.keep_recent)

    # L3: toolResultBudget — 落盘大结果
    def persist_large_output(self, tool_use_id, output) -> str:
        if len(output) <= self.persist_threshold:
            return output
        self.tool_results_dir.mkdir(parents=True, exist_ok=True)
        path = self.tool_results_dir / f"{tool_use_id}.txt"
        if not path.exists():
            path.write_text(output)
        return (f"<persisted-output>\nFull output: {path}\nPreview:\n{output[:2000]}\n"
                f"</persisted-output>")

    def tool_result_budget(self, messages, max_bytes=200_000):
        # 只处理最新一条 user 消息里的工具结果。
        last = messages[-1] if messages else None
        if not last or last.get("role") != "user" or not isinstance(last.get("content"), list):
            return messages
        blocks = [(i, b) for i, b in enumerate(last["content"])
                  if isinstance(b, dict) and b.get("type") == "tool_result"]
        total = sum(len(str(b.get("content", ""))) for _, b in blocks)
        # 总量没超预算，就保留原样。
        if total <= max_bytes:
            return messages
        # 优先压缩最大的结果，最快降到预算内。
        ranked = sorted(blocks, key=lambda p: len(str(p[1].get("content", ""))), reverse=True)
        for _, block in ranked:
            if total <= max_bytes:
                break
            content = str(block.get("content", ""))
            # 小结果不落盘，避免产生太多碎文件。
            if len(content) <= self.persist_threshold:
                continue
            tid = block.get("tool_use_id", "unknown")
            block["content"] = self.persist_large_output(tid, content)
            # 替换后重新计算，因为预览文本仍占空间。
            total = sum(len(str(b.get("content", ""))) for _, b in blocks)
        return messages

    # L4: autoCompact — LLM 全量总结
    def write_transcript(self, messages) -> Path:
        self.transcript_dir.mkdir(parents=True, exist_ok=True)
        path = self.transcript_dir / f"transcript_{int(time.time())}.jsonl"
        with path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg, default=str) + "\n")
        return path

    def summarize_history(self, messages) -> str:
        conversation = json.dumps(messages, default=str)[:80000]
        prompt = ("Summarize this coding-agent conversation so work can continue.\n"
                  "Preserve: 1. current goal, 2. key findings/decisions, 3. files read/changed, "
                  "4. remaining work, 5. user constraints.\nBe compact but concrete.\n\n" + conversation)
        response = self.client.messages.create(model=self.model,
                                               messages=[{"role": "user", "content": prompt}],
                                               max_tokens=self.summarize_max_tokens)
        return "\n".join(getattr(b, "text", "") for b in response.content
                         if getattr(b, "type", None) == "text").strip() or "(empty summary)"

    def compact_history(self, messages):
        """L4：落 transcript + LLM 总结，messages 替换成单条 [Compacted] 消息。"""
        path = self.write_transcript(messages)
        print(f"[transcript saved: {path}]")
        summary = self.summarize_history(messages)
        messages[:] = [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]

    # Emergency: reactiveCompact — API prompt_too_long 时
    def reactive_compact(self, messages):
        self.write_transcript(messages)
        tail_start = max(0, len(messages) - 5)
        if (tail_start > 0 and tail_start < len(messages)
                and _is_tool_result_message(messages[tail_start])
                and _message_has_tool_use(messages[tail_start - 1])):
            tail_start -= 1
        summary = self.summarize_history(messages[:tail_start])
        messages[:] = [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}] + messages[tail_start:]

    def should_auto_compact(self, messages) -> bool:
        return estimate_size(messages) > self.context_limit

    @staticmethod
    def is_prompt_too_long(e) -> bool:
        s = str(e).lower()
        return "prompt_too_long" in s or "too many tokens" in s
