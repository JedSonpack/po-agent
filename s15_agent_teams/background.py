"""Background Tasks — 慢操作 daemon 线程异步执行 + <task_notification> 注入。

should_run_background 判断（显式 run_in_background 优先，启发式兜底）；start_background_task 派发；
collect_background_results 收集完成结果作通知注入。worker 异常不泄漏（po-agent 改进）。
"""
import threading

_bg_counter = 0
background_tasks: dict[str, dict] = {}    # bg_id → {tool_use_id, command, status}
background_results: dict[str, str] = {}   # bg_id → output
background_lock = threading.Lock()

_SLOW_KEYWORDS = ["install", "build", "test", "deploy", "compile",
                  "docker build", "pip install", "npm install",
                  "cargo build", "pytest", "make"]


def is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    """启发式：非 bash 返 False；bash 命令小写含关键词任一返 True。"""
    if tool_name != "bash":
        return False
    cmd = tool_input.get("command", "").lower()
    return any(kw in cmd for kw in _SLOW_KEYWORDS)


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    """模型显式 run_in_background 优先；否则回落 is_slow_operation。"""
    if tool_input.get("run_in_background"):
        return True
    return is_slow_operation(tool_name, tool_input)


def start_background_task(block, run_tool) -> str:
    """daemon 线程执行 block，立即返 bg_id。worker 异常写 Error 标 completed（不泄漏）。"""
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{_bg_counter:04d}"
    cmd = block.input.get("command", block.name)

    def worker():
        try:
            result = run_tool(block.name, block.input)
        except Exception as e:
            result = f"Error: {type(e).__name__}: {e}"
        with background_lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = result

    with background_lock:
        background_tasks[bg_id] = {"tool_use_id": block.id, "command": cmd, "status": "running"}
    threading.Thread(target=worker, daemon=True).start()
    print(f"  \033[33m[background] dispatched {bg_id}: {cmd[:40]}\033[0m")
    return bg_id


def collect_background_results() -> list[str]:
    """收集已完成后台任务，pop 并格式化为 <task_notification>（summary 截 200）。"""
    with background_lock:
        ready_ids = [bid for bid, t in background_tasks.items() if t["status"] == "completed"]
    notifications = []
    for bg_id in ready_ids:
        with background_lock:
            task = background_tasks.pop(bg_id)
            output = background_results.pop(bg_id, "")
        summary = output[:200] if len(output) > 200 else output
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>")
        print(f"  \033[32m[background done] {bg_id}: {task['command'][:40]} ({len(output)} chars)\033[0m")
    return notifications


def has_pending_background() -> bool:
    """非消费式：有已完成未收集的后台任务返 True。inbox_poller 的 wake 条件用。"""
    with background_lock:
        return any(t["status"] == "completed" for t in background_tasks.values())
