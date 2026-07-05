"""Team Protocols — MessageBus（文件收件箱）+ 协议状态机 + Team 类（idle loop）+ lead 工具。

s15 队友是 max_turns 退出；s16 队友 idle loop 等待 inbox（shutdown_request/plan_approval_response）。
两种协议一套机制：shutdown（Lead→队友握手关机）/ plan_approval（队友→Lead 提交计划审批）。
request_id 贯穿请求-回复链；match_response 类型校验 + 幂等；consume_lead_inbox 统一路由。
"""
import json
import random
import threading
import time
from dataclasses import dataclass, field
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
             msg_type: str = "message", metadata: dict = None) -> None:
        msg = {"from": from_agent, "to": to_agent, "content": content,
               "type": msg_type, "ts": time.time(), "metadata": metadata or {}}
        with open(self.dir / f"{to_agent}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        print(f"  \033[33m[bus] {from_agent} → {to_agent}: ({msg_type}) {content[:50]}\033[0m")

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


# ── 协议状态机（s16）──
# 两种协议一套机制：shutdown（Lead→队友）/ plan_approval（队友→Lead）。
# request_id 贯穿请求-回复链；match_response 类型校验 + 幂等。
@dataclass
class ProtocolState:
    request_id: str
    type: str        # "shutdown" | "plan_approval"
    sender: str
    target: str
    status: str      # pending | approved | rejected
    payload: str     # 计划文本或关机原因
    created_at: float = field(default_factory=time.time)


pending_requests: dict = {}  # request_id → ProtocolState


def new_request_id() -> str:
    return f"req_{random.randint(0, 999999):06d}"


def match_response(response_type: str, request_id: str, approve: bool) -> None:
    """经 request_id 关联回复与请求，类型校验 + 幂等。unknown/类型不匹配/已决议均 no-op。"""
    state = pending_requests.get(request_id)
    if not state:
        return
    if state.type == "shutdown" and response_type != "shutdown_response":
        return
    if state.type == "plan_approval" and response_type != "plan_approval_response":
        return
    if state.status != "pending":
        return
    state.status = "approved" if approve else "rejected"
    icon = "✓" if approve else "✗"
    color = "32" if approve else "31"
    print(f"  \033[{color}m[protocol] {state.type} {icon} ({request_id}: {state.status})\033[0m")


def consume_lead_inbox(route_protocol: bool = True) -> list:
    """统一消费 lead 邮箱：route_protocol 时把 _response 消息经 match_response 路由，返全部消息。

    run_check_inbox 与 cli wake 都调它，避免消息被读走但协议状态没更新。
    """
    msgs = BUS.read_inbox("lead")
    if not msgs:
        return []
    if route_protocol:
        for msg in msgs:
            meta = msg.get("metadata", {})
            req_id = meta.get("request_id", "")
            msg_type = msg.get("type", "")
            if req_id and msg_type.endswith("_response"):
                match_response(msg_type, req_id, meta.get("approve", False))
    return msgs


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
    """消费 lead 邮箱，路由协议响应，返带 [type] req:id 标签的格式。"""
    msgs = consume_lead_inbox(route_protocol=True)
    if not msgs:
        return "(inbox empty)"
    lines = []
    for m in msgs:
        meta = m.get("metadata", {})
        req_id = meta.get("request_id", "")
        tag = f" [{m['type']} req:{req_id}]" if req_id else f" [{m['type']}]"
        lines.append(f"  [{m['from']}]{tag} {m['content'][:200]}")
    return "\n".join(lines)


# ── Lead 协议工具（s16）──
def run_request_shutdown(teammate: str) -> str:
    """Lead 发关机握手请求：创建 pending ProtocolState + 发 shutdown_request。"""
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="shutdown", sender="lead", target=teammate,
        status="pending", payload="")
    BUS.send("lead", teammate, "Please shut down gracefully.", "shutdown_request",
             {"request_id": req_id})
    print(f"  \033[35m[protocol] shutdown_request → {teammate} ({req_id})\033[0m")
    return f"Shutdown request sent to {teammate} (req: {req_id})"


def run_request_plan(teammate: str, task: str) -> str:
    """Lead 让队友提交计划（普通消息，无协议状态）。"""
    BUS.send("lead", teammate, f"Please submit a plan for: {task}", "message")
    return f"Asked {teammate} to submit a plan"


def run_review_plan(request_id: str, approve: bool, feedback: str = "") -> str:
    """Lead 审批计划：设状态 + 发 plan_approval_response 给提交者。"""
    state = pending_requests.get(request_id)
    if not state:
        return f"Request {request_id} not found"
    if state.status != "pending":
        return f"Request {request_id} already {state.status}"
    state.status = "approved" if approve else "rejected"
    BUS.send("lead", state.sender, feedback or ("Approved" if approve else "Rejected"),
             "plan_approval_response", {"request_id": request_id, "approve": approve})
    icon = "✓" if approve else "✗"
    print(f"  \033[32m[protocol] plan {icon} ({request_id})\033[0m")
    return f"Plan {'approved' if approve else 'rejected'} ({request_id})"


def _teammate_submit_plan(from_name: str, plan: str) -> str:
    """队友提交计划给 Lead 审批：创建 plan_approval 状态 + 发 plan_approval_request。

    注意：协议级请求，非代码级门控——提交后队友线程继续跑，仍可调 bash/write。
    真实门控需阻塞队友工具分发直到审批回复。教学版只演示消息流程。
    """
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="plan_approval", sender=from_name, target="lead",
        status="pending", payload=plan)
    BUS.send(from_name, "lead", plan, "plan_approval_request", {"request_id": req_id})
    return f"Plan submitted ({req_id}). Waiting for approval..."
