"""交互式 REPL（s10）：s09 + 运行时段落化组装系统提示。"""
from pathlib import Path
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s13_background_tasks.agent import agent_loop
from s13_background_tasks.config import load
from s13_background_tasks.tools import TOOL_HANDLERS, SUB_HANDLERS, make_run_tool
from s13_background_tasks.hooks import trigger_hooks, register_defaults
from s13_background_tasks.todo import TodoNag
from s13_background_tasks.subagent import Subagent
from s13_background_tasks.compact import Compactor
from s13_background_tasks.memory import Memory


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
    print("s12: Task System — persistent task graph")
    print("Type a question, press Enter. Type q to quit.\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms12 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
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
        print()
