"""交互式 REPL（s15）：s14 + 团队（事件队列 + inbox_poller + wake 注入 [Inbox]）。

事件队列统一 user/wake/quit；input_reader 读 stdin，inbox_poller（1s）peek 队友 inbox + 后台完成 → wake。
wake 时排干 lead inbox + 后台通知，拼 `[Inbox]` 注入 history 起一轮 turn。cron 仍走 s14 的
start_scheduler + queue_processor（调 run_turn() → agent_loop 顶部消费 cron 队列）。main 与 queue_processor
经 agent_lock 串行。run_turn 不持锁，调用方持锁。
"""
import queue
import threading
import time
from pathlib import Path
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s15_agent_teams.agent import agent_loop
from s15_agent_teams.config import load
from s15_agent_teams.tools import TOOL_HANDLERS, SUB_HANDLERS, TEAM_HANDLERS, make_run_tool
from s15_agent_teams.hooks import trigger_hooks, register_defaults
from s15_agent_teams.todo import TodoNag
from s15_agent_teams.subagent import Subagent
from s15_agent_teams.compact import Compactor
from s15_agent_teams.memory import Memory
from s15_agent_teams.cron import start_scheduler, agent_lock
from s15_agent_teams.teams import Team, BUS, active_teammates
from s15_agent_teams.background import has_pending_background, collect_background_results


def main() -> None:
    register_defaults()
    cfg = load()  # load() 内 scan_skills
    subagent = Subagent(
        client=cfg["client"], model=cfg["model"], sub_system=cfg["sub_system"],
        sub_tools=cfg["sub_tools"], sub_run_tool=make_run_tool(SUB_HANDLERS),
        trigger=trigger_hooks,
    )
    team = Team(
        client=cfg["client"], model=cfg["model"], bus=BUS,
        base_handlers=TEAM_HANDLERS, sub_tools=cfg["team_tools"],
        trigger=trigger_hooks,
    )
    run_tool = make_run_tool(TOOL_HANDLERS, {"task": subagent.run, "spawn_teammate": team.spawn})
    nag = TodoNag()
    compactor = Compactor(client=cfg["client"], model=cfg["model"])
    memory = Memory(client=cfg["client"], model=cfg["model"], memory_dir=Path.cwd() / ".memory")
    memory.memory_dir.mkdir(parents=True, exist_ok=True)
    history: list = []

    def run_turn(query=None, inject=None) -> None:
        """一轮 turn。调用者须持 agent_lock。query=用户输入；inject=预构造内容（[Inbox] 等）。"""
        if query is not None:
            trigger_hooks("UserPromptSubmit", query)
            history.append({"role": "user", "content": query})
        elif inject is not None:
            history.append({"role": "user", "content": inject})
        agent_loop(
            client=cfg["client"], model=cfg["model"], context=cfg["context"],
            tools=cfg["tools"], messages=history, run_tool=run_tool,
            trigger=trigger_hooks, nag=nag, compact=compactor, memory=memory,
        )
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)

    events = queue.Queue()

    def input_reader() -> None:
        while True:
            try:
                line = input("\033[36ms15 >> \033[0m")
            except (EOFError, KeyboardInterrupt):
                events.put(("quit", None))
                return
            events.put(("user", line))

    def inbox_poller() -> None:
        # 1s 轮询：队友 inbox 或后台完成 → wake。不 gate active_teammates：队友发完结果后 pop，
        # 末消息可能晚于注销，gate 会漏收。
        while True:
            time.sleep(1)
            if BUS.peek("lead") or has_pending_background():
                events.put(("wake", None))

    threading.Thread(target=input_reader, daemon=True).start()
    threading.Thread(target=inbox_poller, daemon=True).start()
    start_scheduler(run_turn)  # cron queue_processor 调 run_turn() 消费 cron 队列（与 s14 一致）
    print("s15: Agent Teams — teammate threads + inbox")
    print("Type a question, press Enter. Type q to quit.\n")

    had_teammates = False
    while True:
        kind, payload = events.get()
        if kind == "quit":
            break
        if kind == "user":
            if payload.strip().lower() in ("q", "exit", ""):
                break
            with agent_lock:  # 与 cron queue_processor 互斥
                run_turn(query=payload)
        else:  # wake: 队友 inbox 或后台完成
            parts = []
            inbox = BUS.read_inbox("lead")
            if inbox:
                parts.append("[Inbox]\n" + "\n".join(
                    f"From {m['from']}: {m['content'][:200]}" for m in inbox))
            bg = collect_background_results()
            parts.extend(bg)
            if not parts:
                continue  # 已被先前 wake 排干（幂等）
            print(f"\n\033[33m[wake: {len(inbox)} inbox + {len(bg)} background → new turn]\033[0m")
            with agent_lock:
                run_turn(inject="\n".join(parts))
        # all-teammates-done 公告（一次）
        if active_teammates:
            had_teammates = True
        elif had_teammates and not BUS.peek("lead") and not has_pending_background():
            print("\033[32m[all teammates done]\033[0m")
            had_teammates = False
        print()
