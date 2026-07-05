"""Task System — 文件持久化任务图（blockedBy DAG）+ claim/complete 状态机 + 5 工具 handler。

每个任务一个 .tasks/{id}.json；can_start 检查依赖全完成；complete 扫描并报告解锁的下游。
任务逻辑全在 handler，经 run_tool 自动分发，agent_loop 不改。
"""
import json
import random
import time
from dataclasses import dataclass, asdict
from pathlib import Path

WORKDIR = Path.cwd()
TASKS_DIR = WORKDIR / ".tasks"
TASKS_DIR.mkdir(exist_ok=True)


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str          # pending | in_progress | completed
    owner: str | None
    blockedBy: list[str]
    worktree: str | None = None   # s18: 绑定的 worktree 名（bind_task_to_worktree 写，状态保持 pending）


def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def create_task(subject, description="", blockedBy=None) -> Task:
    task = Task(id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
                subject=subject, description=description,
                status="pending", owner=None, blockedBy=blockedBy or [])
    save_task(task)
    return task


def save_task(task: Task):
    _task_path(task.id).write_text(json.dumps(asdict(task), indent=2))


def load_task(task_id: str) -> Task:
    return Task(**json.loads(_task_path(task_id).read_text()))


def list_tasks() -> list[Task]:
    return [Task(**json.loads(p.read_text()))
            for p in sorted(TASKS_DIR.glob("task_*.json"))]


def get_task(task_id: str) -> str:
    """返回完整任务 JSON 字符串。不存在抛 FileNotFoundError。"""
    return json.dumps(asdict(load_task(task_id)), indent=2)


def can_start(task_id: str) -> bool:
    """所有 blockedBy 依赖 completed 才 True；缺失依赖=blocked（不抛）。不递归。"""
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        if not _task_path(dep_id).exists():
            return False
        if load_task(dep_id).status != "completed":
            return False
    return True


def claim_task(task_id: str, owner: str = "agent") -> str:
    task = load_task(task_id)
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    if task.owner:  # s17: owner 检查——拒绝已认领（并发认领的最简保护）
        return f"Task {task_id} already owned by {task.owner}"
    if not can_start(task_id):
        deps = [d for d in task.blockedBy
                if not _task_path(d).exists() or load_task(d).status != "completed"]
        return f"Blocked by: {deps}"
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    return f"Claimed {task.id} ({task.subject})"


def scan_unclaimed_tasks() -> list:
    """s17: 扫可认领任务——pending + 无 owner + can_start（按文件名排序）。"""
    unclaimed = []
    for p in sorted(TASKS_DIR.glob("task_*.json")):
        task = json.loads(p.read_text())
        if (task.get("status") == "pending"
                and not task.get("owner")
                and can_start(task["id"])):
            unclaimed.append(task)
    return unclaimed


def complete_task(task_id: str) -> str:
    task = load_task(task_id)
    if task.status != "in_progress":
        return f"Task {task_id} is {task.status}, cannot complete"
    task.status = "completed"
    save_task(task)
    unblocked = [t.subject for t in list_tasks()
                 if t.status == "pending" and t.blockedBy and can_start(t.id)]
    msg = f"Completed {task.id} ({task.subject})"
    if unblocked:
        msg += f"\nUnblocked: {', '.join(unblocked)}"
    return msg


# ── 工具 handler ──
def run_create_task(subject, description="", blockedBy=None) -> str:
    task = create_task(subject, description, blockedBy)
    print(f"\033[36m[task] created {task.id}: {task.subject}\033[0m")
    return f"Created {task.id}: {task.subject}"


def run_list_tasks() -> str:
    ts = list_tasks()
    if not ts:
        return "No tasks. Use create_task to add some."
    icon = {"pending": "○", "in_progress": "●", "completed": "✓"}
    lines = []
    for t in ts:
        line = f"  {icon[t.status]} {t.id}: {t.subject}"
        if t.owner:
            line += f" [{t.owner}]"
        if t.blockedBy:
            line += f" (blockedBy: {', '.join(t.blockedBy)})"
        lines.append(line)
    return "\n".join(lines)


def run_get_task(task_id: str) -> str:
    try:
        return get_task(task_id)
    except FileNotFoundError:
        return f"Error: Task {task_id} not found"


def run_claim_task(task_id: str, owner: str = "agent") -> str:
    return claim_task(task_id, owner)


def run_complete_task(task_id: str) -> str:
    return complete_task(task_id)
