import os
import subprocess

DANGEROUS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
TIMEOUT = 120
MAX_OUTPUT = 50000


def run_bash(command: str) -> str:
    """执行 shell 命令，返回截断后的输出字符串。"""
    if any(d in command for d in DANGEROUS):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=TIMEOUT)
        out = (r.stdout + r.stderr).strip()
        return out[:MAX_OUTPUT] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"
