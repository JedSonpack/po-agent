# cli.py —— 交互式 REPL（读取-求值-打印 循环）
#
# 负责和用户交互：读输入、调 agent_loop、打印工具调用日志和最终回复。

# readline 让 input() 支持方向键编辑、历史回溯等。macOS 的 libedit 处理中文输入有 bug，
# 下面四行 parse_and_bind 是修复。readline 不是所有平台都有，所以用 try/except 包起来：
# 导入失败就跳过，不影响主功能。
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass  # pass = 什么都不做

# 从同包的其他模块导入（写法：包名.模块名）
from s01_agent_loop.agent import agent_loop
from s01_agent_loop.config import load
from s01_agent_loop.tools import run_bash


def print_tool_use(command: str, output: str) -> None:
    """工具被调用时的日志回调：彩色打印命令和输出前 200 字符。"""
    # \033[33m ... \033[0m 是 ANSI 颜色码：33=黄色，0=重置。打印出来命令是黄色的。
    # 这个函数会被 agent_loop 在每次工具调用时回调（见 agent.py 的 on_tool_use）。
    print(f"\033[33m$ {command}\033[0m")
    print(output[:200])  # 只预览前 200 字符，避免刷屏


def main() -> None:
    cfg = load()  # 加载配置：client/model/system/tools（见 config.py 的 load）
    print("s01: Agent Loop")
    print("输入问题，回车发送。输入 q 退出。\n")
    history: list = []  # 对话历史；`history: list` 是变量类型标注，初始空列表
    while True:
        try:
            # input() 读一行用户输入。提示符 \033[36m 是青色。
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            # EOFError: 输入结束（Ctrl-D）；KeyboardInterrupt: Ctrl-C。两者都退出 REPL。
            break
        # query.strip() 去首尾空白；.lower() 转小写；in (...) 判断是否在元组里。
        # "" 也在里面——直接回车也退出。
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})  # 用户问题加进历史
        # 调核心循环。所有依赖从 cfg 取；run_tool 传 run_bash；
        # ★ on_tool_use=print_tool_use 就是把上面的"日志函数"加载进 agent_loop ★
        # ——这样模型每调一次工具，agent_loop 就回调 print_tool_use 打印日志。
        agent_loop(
            client=cfg["client"], model=cfg["model"], system=cfg["system"],
            tools=cfg["tools"], messages=history, run_tool=run_bash,
            on_tool_use=print_tool_use,
        )
        # agent_loop 返回后，history 最后一条就是模型的最终回复
        response_content = history[-1]["content"]  # history[-1] 是列表最后一个元素
        if isinstance(response_content, list):  # 回复内容是"块"列表（可能含文本块）
            for block in response_content:
                # getattr(block, "type", None)：取 block.type；没有该属性就返回 None（不报错）
                if getattr(block, "type", None) == "text":
                    print(block.text)  # 打印模型最终的文本回复
        print()
