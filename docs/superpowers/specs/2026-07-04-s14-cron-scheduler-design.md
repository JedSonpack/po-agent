# s14 Cron Scheduler — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第十四阶段（对应 `learn-claude-code/s14_cron_scheduler`）
- 状态：自主模式
- 前置：s13 已完成

## 1. 背景与目标

s13 后台任务仍由用户手动触发。s14 加**闹钟**：设 cron 表达式，到点调度线程把任务塞进 `cron_queue`，agent 空闲时消费并执行。把"触发"与"执行"解耦——独立 daemon 线程判时间，队列传递，queue processor 在 agent 空闲时拉起一轮 agent_loop。

**目标**：行为对齐 s14 调度机制，沿用包 + DI + TDD。新模块 `cron.py`（`CronJob` + cron 匹配 + 校验 + schedule/cancel + 持久化 + scheduler/queue processor + 3 工具）；`agent_loop` 顶部消费 cron 队列注入 `[Scheduled]`；cli 接线 `start_scheduler` + `agent_lock`。保留 s13 全部。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），调度机制行为严格对齐 |
| 累积结构 | **保留 s13 全部**（background + tasks + recovery + 段落化 system prompt + hooks/nag/compact/memory/skills/subagent/14 工具）；s14 参考为聚焦简化 loop，po-agent 不跟随 |
| 线程启动显式化（po-agent 改进） | 参考在 import 时起调度线程（不可测）；po-agent 把 `start_scheduler(run_turn)` 放 cli main 调用，import 不起线程。`_check_and_fire(now)` 抽为纯函数供测试 |
| CronJob | `@dataclass(id, cron, prompt, recurring, durable)` |
| cron 字段 | 5 字段：min hour dom month dow；支持 `*`/`*/N`/`N`/`N-M`/`N,M`；dow 换算 `(weekday+1)%7`（Sun=0..Sat=6） |
| DOM/DOW OR | 两者都非 `*` 时 OR（任一匹配即真）；任一为 `*` 时只看另一边（标准 cron） |
| _cron_field_matches | 单字段匹配 `*`/`*/N`(step>0)/`N-M`/`N,M`/`N` |
| validate_cron | 5 字段数；各字段界内（min 0-59/hour 0-23/dom 1-31/month 1-12/dow 0-6）；step>0；range start≤end；list 逐项；非数字报错。返错误串或 None |
| schedule_job | `id=f"cron_{random.randint(0,999999):06d}"`；先 validate_cron，通过则加锁写 scheduled_jobs +（若 durable）save_durable_jobs；返 CronJob 或错误串 |
| cancel_job | 存在→pop +（durable）重存盘，返 `Cancelled {id}`；不存在→`Job {id} not found` |
| 持久化 | `DURABLE_PATH=WORKDIR/.scheduled_tasks.json`；`save_durable_jobs` 写 `[asdict(j) for durable]`；`load_durable_jobs` 启动恢复，逐个 validate_cron，非法打印跳过，异常静默吞 |
| cron_queue | `list[CronJob]` + `cron_lock`；`consume_cron_queue` 加锁拷贝+清空；`has_cron_queue` 非空判断 |
| _last_fired 去重 | `dict[job_id→minute_marker]`，marker=`"%Y-%m-%d %H:%M"`（日期感知，防次日跳过）；同分钟不重复 fire |
| _check_and_fire(now) | 纯函数：遍历 scheduled_jobs，cron_matches 且 marker 未设 → append cron_queue + 设 marker；one-shot(recurring=False)→pop+重存盘；异常打印不杀。**测试直接调，注入 now** |
| cron_scheduler_loop | `while True: sleep(1); _check_and_fire(datetime.now())`，daemon |
| queue_processor_loop(run_turn) | daemon：`sleep(0.2); if has_cron_queue() and agent_lock.acquire(False): try: run_turn() finally: release()`。抢不到锁则跳过等下一拍 |
| agent_lock | 模块级 `threading.Lock()`；cli 用户 turn 与 queue_processor 互斥 |
| agent_loop | 顶部 `for job in consume_cron_queue(): messages.append({"role":"user","content":f"[Scheduled] {job.prompt}"})` |
| 工具 | 3 个：schedule_cron(cron, prompt, recurring=True, durable=True)/list_crons()/cancel_cron(job_id)。进 TOOL_HANDLERS + make_tools（17） |
| cli | `run_turn(query=None)` 闭包（append query[若有] + agent_loop + 打印末文本）；`start_scheduler(run_turn)` 起两个 daemon；REPL `with agent_lock: run_turn(query)` |

## 3. 结构

```
po-agent/s14_cron_scheduler/
├── __init__.py
├── cron.py           # 新：CronJob + 匹配/校验 + schedule/cancel + 持久化 + _check_and_fire + scheduler/queue processor + agent_lock + 3 run_*
├── config.py         # s13 + make_tools 加 3 cron 工具（17）
├── tools.py          # s13 + TOOL_HANDLERS 加 3 cron handler
├── background.py / tasks.py / recovery.py / system_prompt.py / skills.py / hooks.py / todo.py / subagent.py / compact.py / memory.py  # s13 原样
├── agent.py          # s13 + 顶部消费 cron 队列
├── cli.py            # s13 + run_turn + start_scheduler + agent_lock
├── __main__.py
├── README.md
└── tests/            # test_cron(新) / test_agent(+cron 注入) / test_tools(+3) / test_config(17) / 其余 s13 原样
```

## 4. 核心新增：cron.py

```python
import json
import random
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

WORKDIR = Path.cwd()
DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"

scheduled_jobs: dict[str, "CronJob"] = {}
cron_queue: list = []
cron_lock = threading.Lock()
_last_fired: dict[str, str] = {}
agent_lock = threading.Lock()


@dataclass
class CronJob:
    id: str
    cron: str
    prompt: str
    recurring: bool
    durable: bool


def _cron_field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    if "*/" in field:
        parts = field.split("/")
        if len(parts) != 2:
            return False
        step = int(parts[1])
        if step <= 0:
            return False
        return value % step == 0
    if "," in field:
        return any(_cron_field_matches(f, value) for f in field.split(","))
    if "-" in field:
        lo, hi = field.split("-", 1)
        return int(lo) <= value <= int(hi)
    return field == str(value)


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    fields = cron_expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    dow_val = (dt.weekday() + 1) % 7  # Sun=0..Sat=6
    if not (_cron_field_matches(minute, dt.minute) and _cron_field_matches(hour, dt.hour)
            and _cron_field_matches(month, dt.month)):
        return False
    dom_match = _cron_field_matches(dom, dt.day)
    dow_match = _cron_field_matches(dow, dow_val)
    if dom != "*" and dow != "*":
        return dom_match or dow_match  # OR 语义
    return dom_match and dow_match


def _validate_cron_field(field: str, lo: int, hi: int) -> str | None:
    if field == "*":
        return None
    for part in field.split(","):
        if "*/" in part:
            step = int(part.split("/")[1])
            if step <= 0:
                return f"Invalid step in '{part}'"
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            ai, bi = int(a), int(b)
            if ai > bi:
                return f"Range start > end in '{part}'"
            if not (lo <= ai <= hi and lo <= bi <= hi):
                return f"'{part}' out of bounds [{lo},{hi}]"
        else:
            v = int(part)
            if not (lo <= v <= hi):
                return f"'{part}' out of bounds [{lo},{hi}]"
    return None


def validate_cron(cron_expr: str) -> str | None:
    fields = cron_expr.split()
    if len(fields) != 5:
        return f"Expected 5 fields, got {len(fields)}"
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    for f, (lo, hi) in zip(fields, bounds):
        try:
            err = _validate_cron_field(f, lo, hi)
        except ValueError:
            return f"Invalid field '{f}'"
        if err:
            return err
    return None


def save_durable_jobs() -> None:
    durable = [asdict(j) for j in scheduled_jobs.values() if j.durable]
    DURABLE_PATH.write_text(json.dumps(durable, indent=2))


def load_durable_jobs() -> None:
    try:
        data = json.loads(DURABLE_PATH.read_text())
    except Exception:
        return
    for item in data:
        job = CronJob(**item)
        if validate_cron(job.cron):
            print(f"  [cron] skipping invalid job {job.id}: {job.cron}")
            continue
        scheduled_jobs[job.id] = job


def schedule_job(cron, prompt, recurring=True, durable=True):
    err = validate_cron(cron)
    if err:
        return err
    job = CronJob(id=f"cron_{random.randint(0, 999999):06d}", cron=cron, prompt=prompt,
                  recurring=recurring, durable=durable)
    with cron_lock:
        scheduled_jobs[job.id] = job
        if durable:
            save_durable_jobs()
    return job


def cancel_job(job_id: str) -> str:
    with cron_lock:
        if job_id not in scheduled_jobs:
            return f"Job {job_id} not found"
        job = scheduled_jobs.pop(job_id)
        if job.durable:
            save_durable_jobs()
    return f"Cancelled {job_id}"


def _check_and_fire(now: datetime) -> None:
    """一次轮询：fire 匹配 job，去重，one-shot 删除。纯函数（测试注入 now）。"""
    marker = now.strftime("%Y-%m-%d %H:%M")
    with cron_lock:
        for job in list(scheduled_jobs.values()):
            try:
                if not cron_matches(job.cron, now):
                    continue
                if _last_fired.get(job.id) == marker:
                    continue
                cron_queue.append(job)
                _last_fired[job.id] = marker
                print(f"  [cron fire] {job.id} → {job.prompt[:40]}")
                if not job.recurring:
                    scheduled_jobs.pop(job.id, None)
                    if job.durable:
                        save_durable_jobs()
            except Exception as e:
                print(f"  [cron error] {job.id}: {e}")


def cron_scheduler_loop() -> None:
    while True:
        time.sleep(1)
        _check_and_fire(datetime.now())


def consume_cron_queue() -> list:
    with cron_lock:
        fired = list(cron_queue)
        cron_queue.clear()
    return fired


def has_cron_queue() -> bool:
    with cron_lock:
        return len(cron_queue) > 0


def queue_processor_loop(run_turn) -> None:
    while True:
        time.sleep(0.2)
        if has_cron_queue() and agent_lock.acquire(blocking=False):
            try:
                run_turn()
            finally:
                agent_lock.release()


def start_scheduler(run_turn) -> None:
    load_durable_jobs()
    threading.Thread(target=cron_scheduler_loop, daemon=True).start()
    threading.Thread(target=queue_processor_loop, args=(run_turn,), daemon=True).start()


# ── 工具 handler ──
def run_schedule_cron(cron, prompt, recurring=True, durable=True) -> str:
    result = schedule_job(cron, prompt, recurring, durable)
    if isinstance(result, str):
        return result
    return f"Scheduled {result.id}: '{result.cron}' → {result.prompt}"


def run_list_crons() -> str:
    with cron_lock:
        jobs = list(scheduled_jobs.values())
    if not jobs:
        return "No cron jobs. Use schedule_cron to add one."
    lines = []
    for j in jobs:
        kind = "recurring" if j.recurring else "one-shot"
        dur = "durable" if j.durable else "session"
        lines.append(f"  {j.id}: '{j.cron}' → {j.prompt[:40]} [{kind}, {dur}]")
    return "\n".join(lines)


def run_cancel_cron(job_id: str) -> str:
    return cancel_job(job_id)
```

## 5. agent_loop 集成（agent.py）

s13 agent_loop + 顶部消费 cron 队列（循环顶部，pre_compress 之前）：
```python
from s14_cron_scheduler.cron import consume_cron_queue
# ...
    while True:
        # s14: 消费已触发的 cron 任务 → 注入 [Scheduled] 消息
        for job in consume_cron_queue():
            messages.append({"role": "user", "content": f"[Scheduled] {job.prompt}"})
        pre_compress = ...
        # ... 其余同 s13 ...
```

## 6. config.py / tools.py / cli.py

- **config.py**：`make_tools()` 加 3 cron 工具（17）：
```python
{"name": "schedule_cron", "description": "Schedule a cron job. cron is 5-field: min hour dom month dow.",
 "input_schema": {"type": "object", "properties": {"cron": {"type": "string"}, "prompt": {"type": "string"}, "recurring": {"type": "boolean"}, "durable": {"type": "boolean"}}, "required": ["cron", "prompt"]}},
{"name": "list_crons", "description": "List all registered cron jobs.", "input_schema": {"type": "object", "properties": {}, "required": []}},
{"name": "cancel_cron", "description": "Cancel a cron job by ID.", "input_schema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
```
- **tools.py**：`TOOL_HANDLERS` 加 3（import from cron）。
- **cli.py**：`run_turn(query=None)` 闭包 + `start_scheduler(run_turn)` + REPL `with agent_lock: run_turn(query)`：
```python
from s14_cron_scheduler.cron import start_scheduler, agent_lock

def main():
    register_defaults(); cfg = load()
    ... subagent/run_tool/nag/compactor/memory ...
    history = []
    def run_turn(query=None):
        if query is not None:
            trigger_hooks("UserPromptSubmit", query)
            history.append({"role": "user", "content": query})
        agent_loop(client=cfg["client"], model=cfg["model"], context=cfg["context"],
                   tools=cfg["tools"], messages=history, run_tool=run_tool,
                   trigger=trigger_hooks, nag=nag, compact=compactor, memory=memory)
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
    start_scheduler(run_turn)
    print("s14: Cron Scheduler — scheduled triggers")
    while True:
        try:
            query = input("\033[36ms14 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        with agent_lock:
            run_turn(query)
        print()
```

## 7. 测试策略

- **test_cron.py**（新，reset scheduled_jobs/cron_queue/_last_fired fixture）：
  - _cron_field_matches：`*`/`*/5`/`1-5`/`1,15,30`/单值；`*/0` False
  - cron_matches：`* * * * *` 任意 True；`0 9 * * *` 对 9:00 True/9:01 False/10:00 False；`*/5 * * * *` minute∈{0,5,..}；`0 9 * * 1-5` 周一 9:00 True/周六 False；DOM/DOW OR（`0 0 1 * 1` 1号或周一）；DOW 换算（周日→0）；非 5 字段 False
  - validate_cron：`0 9 * * *`→None；`60 *`/`0 25`/`0 0 0`/6 字段/`*/0`/`5-3`/`a *`/`1,99`→错误串
  - schedule_job：合法→CronJob + scheduled_jobs + durable 文件；非法→错误串；id 格式 `cron_\d{6}`
  - cancel_job：存在→移除+重存盘 `Cancelled`；不存在→`not found`
  - save/load 往返：注册 durable→save→清空→load→恢复；磁盘非法 cron→load 跳过
  - _check_and_fire：注册 `* * * * *` + 注入 now → cron_queue 含 job + _last_fired 设；同 marker 再调→不重复；跨分钟（next marker）→再 fire；one-shot fire→scheduled_jobs 移除；recurring fire→保留；坏 cron job→打印不杀
  - consume/has_cron_queue：空→[]/False；有→返列表+清空
- **test_agent.py**：s13 sed 复制；加：预填 cron_queue 一个 job → agent_loop 注入 `[Scheduled] {prompt}` user 消息
- **test_tools.py**：+3 cron handler 分发
- **test_config.py**：make_tools 17
- 其余 test_*：s13 原样 sed 改名。

## 8. 行为对齐验收

- 全量测试通过（s01-s14）。
- 实时冒烟：`echo '用 schedule_cron 安排一个每分钟执行的任务，提示词"检查进度"，然后列出所有 cron 任务' | python -m s14_cron_scheduler` → agent 调 schedule_cron + list_crons，`.scheduled_tasks.json` 落 job，list_crons 显示。

## 9. 范围外（YAGNI）

- MAX_JOBS 限制、抖动、7 天自动过期（参考不实现）。
- 时区处理（全程本地时间 datetime.now()）。
- 真正"等一分钟看 fire"的实时冒烟（_check_and_fire 单测覆盖；live 需等分钟）。
