"""交互式 REPL（s07）：s06 + load_skill 按需加载技能。"""
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s07_skill_loading.agent import agent_loop
from s07_skill_loading.config import load
from s07_skill_loading.tools import TOOL_HANDLERS, SUB_HANDLERS, make_run_tool
from s07_skill_loading.hooks import trigger_hooks, register_defaults
from s07_skill_loading.todo import TodoNag
from s07_skill_loading.subagent import Subagent


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
    print("s07: Skill Loading — catalog in SYSTEM, content on demand")
    print("Type a question, press Enter. Type q to quit.\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms07 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(
            client=cfg["client"], model=cfg["model"], system=cfg["system"],
            tools=cfg["tools"], messages=history, run_tool=run_tool,
            trigger=trigger_hooks, nag=nag,
        )
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
