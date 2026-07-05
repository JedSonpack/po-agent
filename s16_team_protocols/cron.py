"""Cron Scheduler — 按时间表触发任务（daemon fire → cron_queue → agent 消费注入 [Scheduled]）。

线程显式启动（start_scheduler，cli 调用，import 不起线程）。_check_and_fire 抽为纯函数供测试。
cron 5 字段，DOM/DOW OR 语义，dow 换算 (weekday+1)%7。durable 持久化 .scheduled_tasks.json。
"""
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
    dow_val = (dt.weekday() + 1) % 7  # Python Mon=0..Sun=6 → cron Sun=0..Sat=6
    if not (_cron_field_matches(minute, dt.minute) and _cron_field_matches(hour, dt.hour)
            and _cron_field_matches(month, dt.month)):
        return False
    dom_match = _cron_field_matches(dom, dt.day)
    dow_match = _cron_field_matches(dow, dow_val)
    if dom != "*" and dow != "*":
        return dom_match or dow_match  # OR 语义：都约束时任一匹配即真
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
    """一次轮询：fire 匹配 job，minute_marker 去重，one-shot 删除。纯函数（测试注入 now）。"""
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
                print(f"  \033[33m[cron fire] {job.id} → {job.prompt[:40]}\033[0m")
                if not job.recurring:
                    scheduled_jobs.pop(job.id, None)
                    if job.durable:
                        save_durable_jobs()
            except Exception as e:
                print(f"  \033[31m[cron error] {job.id}: {e}\033[0m")


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
    """agent 空闲（agent_lock 可获取）且有 cron 队列时拉起一轮 turn。"""
    while True:
        time.sleep(0.2)
        if has_cron_queue() and agent_lock.acquire(blocking=False):
            try:
                run_turn()
            finally:
                agent_lock.release()


def start_scheduler(run_turn) -> None:
    """显式启动调度线程 + 队列处理器（cli 调用，import 不起线程）。"""
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
