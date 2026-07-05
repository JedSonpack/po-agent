"""交互式 REPL（s15）：s14 + 团队（事件队列 + inbox_poller + wake 注入 [Inbox]）。"""
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
from s15_agent_teams.tools import TOOL_HANDLERS, SUB_HANDLERS, make_run_tool
from s15_agent_teams.hooks import trigger_hooks, register_defaults
from s15_agent_teams.todo import TodoNag
from s15_agent_teams.subagent import Subagent
from s15_agent_teams.compact import Compactor
from s15_agent_teams.memory import Memory
from s15_agent_teams.cron import start_scheduler, agent_lock


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
    print("s15: Agent Teams — teammate threads + inbox")
    print("Type a question, press Enter. Type q to quit.\n")
    while True:
        try:
            query = input("\033[36ms15 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        with agent_lock:  # 与 queue_processor 互斥
            run_turn(query)
        print()
