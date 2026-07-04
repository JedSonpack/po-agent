# s12 Task System — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第十二阶段（对应 `learn-claude-code/s12_task_system`）
- 状态：自主模式
- 前置：s11 已完成

## 1. 背景与目标

s05 的 TodoWrite 是会话内执行清单（进程态、无依赖）。s12 加**文件持久化的任务图**：每个任务一个 `.tasks/{id}.json`，`blockedBy` 声明依赖（DAG），状态跨会话保留，可被认领/追踪/解锁。是多 agent 协作与长项目恢复的基础设施。

**目标**：行为对齐 s12 任务系统，沿用包 + DI + TDD。新模块 `tasks.py`（`Task` dataclass + 持久化 + `can_start`/`claim_task`/`complete_task` + 5 工具 handler）；5 工具进 `TOOL_HANDLERS` + `make_tools()`（共 14）。`agent_loop` 不改（任务逻辑全在 handler，经 run_tool 自动分发）。保留 s11 全部。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），任务系统行为严格对齐 |
| 累积结构 | **保留 s11 全部**（recovery + 段落化 system prompt + hooks/nag/compact/memory/skills/subagent/9 工具）；s12 参考为聚焦简化 loop（去 recovery/hooks/nag/skills/compact/memory），po-agent 不跟随——任务工具经 run_tool 自动分发，循环不变 |
| Task 模型 | `@dataclass: id/subject/description/status/owner/blockedBy`；status ∈ pending/in_progress/completed；owner 默认 None；blockedBy 默认 [] |
| 持久化 | `TASKS_DIR = WORKDIR/.tasks`；每任务 `task_{id}.json`；`save_task` 用 `json.dumps(asdict, indent=2)`；`TASKS_DIR.mkdir(exist_ok=True)` 模块加载时（测试用 tmp_path + monkeypatch TASKS_DIR/WORKDIR） |
| ID 生成 | `f"task_{int(time.time())}_{random.randint(0,9999):04d}"`（以 code.py 为准，非 README 的 hex） |
| can_start | blockedBy 全 completed 才 True；缺失依赖=blocked（不抛）；不递归（只查直接依赖） |
| claim_task | pending + can_start → owner=owner(默认"agent") + in_progress，返 `"Claimed {id} ({subject})"`；非 pending → `"Task {id} is {status}, cannot claim"`；blocked → `"Blocked by: {deps}"` |
| complete_task | in_progress → completed，返 `"Completed {id} ({subject})"` + 扫描下游（pending 且 blockedBy 非空且 can_start）追加 `"\nUnblocked: {subjects}"`；非 in_progress → `"Task {id} is {status}, cannot complete"` |
| list_tasks | 按 `sorted(glob("task_*.json"))`（文件名序） |
| run_list_tasks | 空 → `"No tasks. Use create_task to add some."`；非空每行 `  {icon} {id}: {subject} [owner] (blockedBy: ...)`，icon ○/●/✓ |
| run_get_task | 存在 → indented JSON；不存在 → `"Error: Task {id} not found"`（底层 get_task 抛 FileNotFoundError，handler 捕获） |
| 工具 | 5 个：create_task(subject, description="", blockedBy=None)/list_tasks()/get_task(task_id)/claim_task(task_id, owner="agent")/complete_task(task_id)。进 TOOL_HANDLERS + make_tools（14 工具） |
| agent_loop | 不改——任务工具静态 handler，run_tool 自动分发（同 todo_write/load_skill） |
| 无环检测 | 不实现（can_start 不递归，循环依赖永远 blocked，不死循环） |

## 3. 结构

```
po-agent/s12_task_system/
├── __init__.py
├── tasks.py          # 新：Task + 持久化 + can_start/claim/complete + 5 run_* handler
├── config.py         # s11 + make_tools 加 5 任务工具（14）
├── tools.py          # s11 + TOOL_HANDLERS 加 5 任务 handler
├── recovery.py / system_prompt.py / skills.py / hooks.py / todo.py / subagent.py / compact.py / memory.py  # s11 原样
├── agent.py          # s11 原样
├── cli.py            # s11 原样
├── __main__.py
├── README.md
└── tests/            # test_tasks(新) / test_tools(+5) / test_config(14) / 其余 s11 原样
```

## 4. 核心新增：tasks.py

```python
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
    return json.dumps(asdict(load_task(task_id)), indent=2)


def can_start(task_id: str) -> bool:
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
    if not can_start(task_id):
        deps = [d for d in task.blockedBy
                if not _task_path(d).exists() or load_task(d).status != "completed"]
        return f"Blocked by: {deps}"
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    return f"Claimed {task.id} ({task.subject})"


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
    tasks = list_tasks()
    if not tasks:
        return "No tasks. Use create_task to add some."
    icon = {"pending": "○", "in_progress": "●", "completed": "✓"}
    lines = []
    for t in tasks:
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
```

## 5. tools.py / config.py 改动

- **tools.py**：`TOOL_HANDLERS` 加 5：`"create_task": run_create_task, "list_tasks": run_list_tasks, "get_task": run_get_task, "claim_task": run_claim_task, "complete_task": run_complete_task`（import from `.tasks`）。`SUB_HANDLERS` 不加（子 agent 不给任务工具，防递归？参考 teammate 无 task——但 s12 是主 agent 工具；子 agent 是否给？s06 子 agent 5 工具无 todo_write/task/load_skill。s12 任务工具也只给主 agent，子 agent 不加）。
- **config.py**：`make_tools()` 加 5 任务工具 dict（共 14）：
```python
{"name": "create_task", "description": "Create a new task with optional blockedBy dependencies.",
 "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}, "blockedBy": {"type": "array", "items": {"type": "string"}}}, "required": ["subject"]}},
{"name": "list_tasks", "description": "List all tasks with status, owner, and dependencies.",
 "input_schema": {"type": "object", "properties": {}, "required": []}},
{"name": "get_task", "description": "Get full details of a specific task by ID.",
 "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
{"name": "claim_task", "description": "Claim a pending task. Sets owner, changes status to in_progress.",
 "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
{"name": "complete_task", "description": "Complete an in-progress task. Reports unblocked downstream tasks.",
 "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
```

## 6. agent.py / cli.py

- agent.py：s11 原样（任务工具经 run_tool 自动分发）。
- cli.py：s11 原样（`make_run_tool(TOOL_HANDLERS, {"task": subagent.run})` 自动含 5 新 handler）。

## 7. 测试策略

- **test_tasks.py**（新，tmp_path + monkeypatch `tasks.TASKS_DIR`/`tasks.WORKDIR`）：
  - create_task：返 Task（pending/owner None/blockedBy []），文件存在；blockedBy 传入；ID 格式 `task_\d+_\d{4}`
  - save/load 往返相等
  - list_tasks：空 []；多个按文件名序
  - get_task：存在返 JSON；不存在抛 FileNotFoundError
  - can_start：[]→True；缺失依赖→False；pending 依赖→False；completed 依赖→True；多依赖混合
  - claim_task：pending+can_start→in_progress+owner+"Claimed..."；非 pending→"cannot claim"；blocked→"Blocked by: [...]";owner 传入
  - complete_task：in_progress→completed+"Completed..."；非 in_progress→"cannot complete"；下游解锁报 "Unblocked: ..."；无下游不报
  - run_list_tasks：空→"No tasks..."；非空含图标/owner/blockedBy
  - run_get_task：不存在→"Error: Task ... not found"
  - DAG 端到端：schema→endpoints(blockedBy schema)→tests(blockedBy endpoints)；claim schema OK；claim endpoints blocked；complete schema→endpoints+tests 解锁
  - 跨会话持久：create 后重新 list_tasks 仍读得到
- **test_tools.py**：s11 + 5 handler 分发测试（run_tool("create_task", {...}) → 调 run_create_task）。
- **test_config.py**：make_tools 14（加 5 任务工具名）。
- 其余 test_*：s11 原样 sed 改名。

## 8. 行为对齐验收

- 全量测试通过（s01-s12）。
- 实时冒烟：`echo '创建三个任务：schema、endpoints（依赖 schema）、tests（依赖 endpoints），然后 claim schema' | python -m s12_task_system` → agent 调 create_task ×3 + claim_task，list_tasks 显示 DAG 与状态。

## 9. 范围外（YAGNI）

- `TaskUpdate`（通用更新）/`TaskDelete`/release（in_progress 退回 pending）/环检测/ID 单调递增 highwatermark/owner 多 agent 并发认领——参考不实现，po-agent 也不实现。
- 任务状态自动注入 system prompt（参考 update_context 不读任务，po-agent 同）。
