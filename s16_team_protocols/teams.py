"""Agent Teams — MessageBus（文件收件箱）+ Team 类（队友 daemon 线程）+ lead 工具 handler。

s06 Subagent 是一次性同步回总结；s15 队友是异步 daemon 线程，多轮（限 max_turns），经文件邮箱通信。
每轮顶上注入 `<inbox>`，sliding window `messages[-20:]`，完成后倒序取 assistant text 作 summary 发给 lead。
send_message 的 from = 队友名（lead handler 固定 from="lead"）。无 spawn_teammate 工具防组队递归。
"""
import json
import threading
import time
from pathlib import Path
from typing import Callable

WORKDIR = Path.cwd()
MAILBOX_DIR = WORKDIR / ".mailboxes"


class MessageBus:
    """文件收件箱：每个 agent 一个 .jsonl 邮箱。send=append，read_inbox=读+unlink（消费式），peek=非消费式。

    教学版无文件锁（read+unlink 有竞态，单消费者场景可接受）；真实 CC 用 proper-lockfile。
    """

    def __init__(self, mailbox_dir=None):
        self.dir = Path(mailbox_dir) if mailbox_dir else MAILBOX_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message") -> None:
        msg = {"from": from_agent, "to": to_agent, "content": content,
               "type": msg_type, "ts": time.time()}
        with open(self.dir / f"{to_agent}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        print(f"  \033[33m[bus] {from_agent} → {to_agent}: {content[:50]}\033[0m")

    def read_inbox(self, agent: str) -> list:
        """消费式：读全部消息后删除邮箱文件。缺失返 []。"""
        inbox = self.dir / f"{agent}.jsonl"
        if not inbox.exists():
            return []
        msgs = [json.loads(line) for line in inbox.read_text().splitlines()
                if line.strip()]
        inbox.unlink()
        return msgs

    def peek(self, agent: str) -> bool:
        """非消费式：有未读消息返 True。inbox_poller 的 wake 条件用。"""
        inbox = self.dir / f"{agent}.jsonl"
        return inbox.exists() and inbox.stat().st_size > 0


BUS = MessageBus()
active_teammates: dict = {}  # name → True（在跑）


def _extract_last_text(messages) -> str:
    """倒序找最近一条含 text block 的 assistant 消息，返其首个 text。无则 ''。"""
    for msg in reversed(messages):
        if msg.get("role") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        for b in msg["content"]:
            if getattr(b, "type", None) == "text":
                return b.text
    return ""


class Team:
    """队伍：spawn 启动队友 daemon 线程跑自己的简化循环，完成后发 summary 给 lead。

    队友 4 工具（bash/read_file/write_file/send_message）；send_message 的 from=队友名（per-spawn 绑定）。
    无 spawn_teammate → 不能递归组队。max_turns 安全限防无限循环（真实 CC 用 idle loop）。
    """

    def __init__(self, *, client, model, bus: MessageBus, base_handlers: dict,
                 sub_tools: list, trigger: Callable, max_turns: int = 10,
                 max_tokens: int = 8000):
        self.client = client
        self.model = model
        self.bus = bus
        self.base_handlers = base_handlers
        self.sub_tools = sub_tools
        self.trigger = trigger
        self.max_turns = max_turns
        self.max_tokens = max_tokens

    def _make_sub_run_tool(self, name: str) -> Callable:
        """构造队友分发器：base_handlers + send_message（from 绑定 name）。"""
        handlers = dict(self.base_handlers)
        handlers["send_message"] = lambda to, content: (self.bus.send(name, to, content), "Sent")[1]

        def run_tool(tool_name: str, tool_input: dict) -> str:
            handler = handlers.get(tool_name)
            return handler(**tool_input) if handler else f"Unknown: {tool_name}"

        return run_tool

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """启动队友 daemon 线程，立即返回。同名去重。"""
        if name in active_teammates:
            return f"Teammate '{name}' already exists"
        active_teammates[name] = True
        threading.Thread(target=self._run, args=(name, role, prompt), daemon=True).start()
        print(f"  \033[36m[teammate] {name} spawned as {role}\033[0m")
        return f"Teammate '{name}' spawned as {role}"

    def _run(self, name: str, role: str, prompt: str) -> None:
        system = (f"You are '{name}', a {role}. Use tools to complete tasks. "
                  f"Send results via send_message to 'lead'.")
        messages = [{"role": "user", "content": prompt}]
        sub_run_tool = self._make_sub_run_tool(name)

        for _ in range(self.max_turns):
            inbox = self.bus.read_inbox(name)
            if inbox:
                messages.append({"role": "user",
                                 "content": f"<inbox>{json.dumps(inbox)}</inbox>"})
            try:
                response = self.client.messages.create(
                    model=self.model, system=system, messages=messages[-20:],
                    tools=self.sub_tools, max_tokens=self.max_tokens)
            except Exception:
                break
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                blocked = self.trigger("PreToolUse", block)
                if blocked:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": str(blocked)})
                    continue
                output = sub_run_tool(block.name, block.input)
                self.trigger("PostToolUse", block, output)
                print(f"  \033[90m[teammate {name}] {block.name}: {str(output)[:100]}\033[0m")
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(output)})
            messages.append({"role": "user", "content": results})

        summary = _extract_last_text(messages) or "Done."
        self.bus.send(name, "lead", summary, "result")
        active_teammates.pop(name, None)
        print(f"  \033[32m[teammate] {name} finished\033[0m")


# ── Lead 工具 handler（用模块 BUS，from 固定 "lead"）──
def run_send_message(to: str, content: str) -> str:
    BUS.send("lead", to, content)
    return f"Sent to {to}"


def run_check_inbox() -> str:
    msgs = BUS.read_inbox("lead")
    if not msgs:
        return "(inbox empty)"
    lines = [f"  [{m['from']}] {m['content'][:200]}" for m in msgs]
    return "\n".join(lines)
