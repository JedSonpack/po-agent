"""交互式 REPL（s14）：s13 + cron 调度（start_scheduler + agent_lock + run_turn 闭包）。"""
from pathlib import Path
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s14_cron_scheduler.agent import agent_loop
from s14_cron_scheduler.config import load
from s14_cron_scheduler.tools import TOOL_HANDLERS, SUB_HANDLERS, make_run_tool
from s14_cron_scheduler.hooks import trigger_hooks, register_defaults
from s14_cron_scheduler.todo import TodoNag
from s14_cron_scheduler.subagent import Subagent
from s14_cron_scheduler.compact import Compactor
from s14_cron_scheduler.memory import Memory
from s14_cron_scheduler.cron import start_scheduler, agent_lock


def main() -> None:
    register_defaults()
    cfg = load()  # load() 内 scan_skills
    subagent = Subagent(
        client=cfg["client"], model=cfg["model"], sub_system=cfg["sub_system"],
        sub_tools=cfg["sub_tools"], sub_run_tool=make_run_tool(SUB_HANDLERS),
        trigger=trigger_hooks,
    )
    run_tool = make_run_tool(TOOL_HANDLERS, {"task": subagent.run})
    nag = TodoNag()
    compactor = Compactor(client=cfg["client"], model=cfg["model"])
    memory = Memory(client=cfg["client"], model=cfg["model"], memory_dir=Path.cwd() / ".memory")
    memory.memory_dir.mkdir(parents=True, exist_ok=True)
    history: list = []

    def run_turn(query=None) -> None:
        """一轮 agent turn（用户输入或 cron 触发）。调用者须持 agent_lock。"""
        if query is not None:
            trigger_hooks("UserPromptSubmit", query)
            history.append({"role": "user", "content": query})
        agent_loop(
            client=cfg["client"], model=cfg["model"], context=cfg["context"],
            tools=cfg["tools"], messages=history, run_tool=run_tool,
            trigger=trigger_hooks, nag=nag, compact=compactor, memory=memory,
        )
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)

    start_scheduler(run_turn)  # 起调度线程 + 队列处理器（agent 空闲时 cron 触发 turn）
    print("s14: Cron Scheduler — scheduled triggers")
    print("Type a question, press Enter. Type q to quit.\n")
    while True:
        try:
            query = input("\033[36ms14 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        with agent_lock:  # 与 queue_processor 互斥
            run_turn(query)
        print()
