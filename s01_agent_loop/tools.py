# tools.py —— 工具执行
#
# 实现 s01 唯一的工具 run_bash：执行一条 shell 命令并返回输出字符串。
# 包含三层保护：危险命令黑名单、超时、输出截断。

import os
import subprocess  # 标准库：用来执行子进程（外部命令）

DANGEROUS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]  # 危险命令关键词黑名单
TIMEOUT = 120       # 单条命令最长运行 120 秒
MAX_OUTPUT = 50000  # 输出最多保留 50000 个字符，防止超大输出撑爆上下文


def run_bash(command: str) -> str:
    """执行 shell 命令，返回截断后的输出字符串。"""
    # any(...)：只要里面有一个为 True 就返回 True。
    # `d in command for d in DANGEROUS` 是生成器表达式：遍历黑名单，
    # 逐个判断 d 是否是 command 的子串。任一命中就拦截。
    if any(d in command for d in DANGEROUS):
        return "Error: Dangerous command blocked"
    try:
        # subprocess.run 执行命令并等它结束。各关键字参数含义：
        #   shell=True        把命令交给 shell 解释（可用管道 |、通配符 * 等）
        #   cwd=os.getcwd()   在当前工作目录下执行
        #   capture_output=True 捕获 stdout/stderr，而不是直接打印到终端
        #   text=True         把输出作为字符串返回（默认是字节 bytes）
        #   timeout=120       超过 120 秒就杀掉进程并抛 TimeoutExpired
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=TIMEOUT)
        # r.stdout 是标准输出，r.stderr 是错误输出；拼一起再 strip() 去首尾空白。
        out = (r.stdout + r.stderr).strip()
        # 三元表达式：A if 条件 else B。out 非空就截断，空就返回占位文本。
        # out[:MAX_OUTPUT] 是切片，取前 MAX_OUTPUT 个字符。
        return out[:MAX_OUTPUT] if out else "(no output)"
    except subprocess.TimeoutExpired:
        # 命令超时会抛 TimeoutExpired，在这里捕获。
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        # 一个 except 同时捕获多种异常类型；as e 把异常对象赋给变量 e。
        return f"Error: {e}"  # f-string 里 {e} 替换成异常的字符串信息
