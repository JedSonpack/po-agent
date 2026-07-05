import json
from datetime import datetime
import pytest
from s16_team_protocols import cron
from s16_team_protocols.cron import (CronJob, _cron_field_matches, cron_matches, validate_cron,
                                     schedule_job, cancel_job, save_durable_jobs, load_durable_jobs,
                                     _check_and_fire, consume_cron_queue, has_cron_queue,
                                     run_schedule_cron, run_list_crons, run_cancel_cron)


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(cron, "DURABLE_PATH", tmp_path / "scheduled.json")
    cron.scheduled_jobs.clear()
    cron.cron_queue.clear()
    cron._last_fired.clear()
    yield
    cron.scheduled_jobs.clear()
    cron.cron_queue.clear()
    cron._last_fired.clear()


# ── _cron_field_matches ──
def test_field_star():
    assert _cron_field_matches("*", 5) is True


def test_field_step():
    assert _cron_field_matches("*/5", 0) is True
    assert _cron_field_matches("*/5", 10) is True
    assert _cron_field_matches("*/5", 3) is False


def test_field_step_zero():
    assert _cron_field_matches("*/0", 0) is False


def test_field_range():
    assert _cron_field_matches("1-5", 3) is True
    assert _cron_field_matches("1-5", 6) is False


def test_field_list():
    assert _cron_field_matches("1,15,30", 15) is True
    assert _cron_field_matches("1,15,30", 7) is False


def test_field_single():
    assert _cron_field_matches("9", 9) is True
    assert _cron_field_matches("9", 8) is False


# ── cron_matches ──
def test_matches_every():
    assert cron_matches("* * * * *", datetime(2026, 7, 4, 9, 0)) is True


def test_matches_specific():
    assert cron_matches("0 9 * * *", datetime(2026, 7, 4, 9, 0)) is True
    assert cron_matches("0 9 * * *", datetime(2026, 7, 4, 9, 1)) is False
    assert cron_matches("0 9 * * *", datetime(2026, 7, 4, 10, 0)) is False


def test_matches_step_minute():
    assert cron_matches("*/5 * * * *", datetime(2026, 7, 4, 9, 0)) is True
    assert cron_matches("*/5 * * * *", datetime(2026, 7, 4, 9, 5)) is True
    assert cron_matches("*/5 * * * *", datetime(2026, 7, 4, 9, 3)) is False


def test_matches_weekday_range():
    # 2026-07-06 是周一
    assert cron_matches("0 9 * * 1-5", datetime(2026, 7, 6, 9, 0)) is True
    # 2026-07-05 是周日
    assert cron_matches("0 9 * * 1-5", datetime(2026, 7, 5, 9, 0)) is False


def test_matches_dom_dow_or():
    # 0 0 1 * 1：每月 1 号 或 周一 0:00
    # 2026-07-01 是周三，dom 匹配（1号）→ True
    assert cron_matches("0 0 1 * 1", datetime(2026, 7, 1, 0, 0)) is True
    # 2026-07-06 周一，非 1 号，dow 匹配 → True
    assert cron_matches("0 0 1 * 1", datetime(2026, 7, 6, 0, 0)) is True
    # 2026-07-02 周四，非 1 号非周一 → False
    assert cron_matches("0 0 1 * 1", datetime(2026, 7, 2, 0, 0)) is False


def test_matches_dow_sunday():
    # 周日 → dow_val=0；2026-07-05 是周日
    assert cron_matches("0 0 * * 0", datetime(2026, 7, 5, 0, 0)) is True
    assert cron_matches("0 0 * * 0", datetime(2026, 7, 6, 0, 0)) is False


def test_matches_not_five_fields():
    assert cron_matches("* * *", datetime(2026, 7, 4, 9, 0)) is False


# ── validate_cron ──
def test_validate_ok():
    assert validate_cron("0 9 * * *") is None


def test_validate_minute_out_of_bounds():
    assert validate_cron("60 * * * *") is not None


def test_validate_hour_out_of_bounds():
    assert validate_cron("0 25 * * *") is not None


def test_validate_dom_zero():
    assert validate_cron("0 0 0 * *") is not None


def test_validate_six_fields():
    assert "5" in validate_cron("* * * * * *")


def test_validate_step_zero():
    assert validate_cron("*/0 * * * *") is not None


def test_validate_range_reversed():
    assert validate_cron("5-3 * * * *") is not None


def test_validate_non_numeric():
    assert validate_cron("a * * * *") is not None


def test_validate_list_out_of_bounds():
    assert validate_cron("1,99 * * * *") is not None


# ── schedule_job / cancel_job ──
def test_schedule_valid():
    job = schedule_job("0 9 * * *", "check")
    assert isinstance(job, CronJob)
    assert job.id in cron.scheduled_jobs
    import re
    assert re.fullmatch(r"cron_\d{6}", job.id)


def test_schedule_invalid_returns_str():
    result = schedule_job("bad", "check")
    assert isinstance(result, str)


def test_schedule_durable_writes_file():
    schedule_job("0 9 * * *", "check", durable=True)
    data = json.loads(cron.DURABLE_PATH.read_text())
    assert len(data) == 1
    assert data[0]["cron"] == "0 9 * * *"


def test_schedule_not_durable_no_file():
    schedule_job("0 9 * * *", "check", durable=False)
    assert not cron.DURABLE_PATH.exists()


def test_cancel_existing():
    job = schedule_job("0 9 * * *", "check", durable=True)
    msg = cancel_job(job.id)
    assert "Cancelled" in msg
    assert job.id not in cron.scheduled_jobs


def test_cancel_missing():
    assert "not found" in cancel_job("cron_000000")


# ── save/load ──
def test_load_restores_durable():
    schedule_job("0 9 * * *", "check1", durable=True)
    schedule_job("*/5 * * * *", "check2", durable=True)
    cron.scheduled_jobs.clear()
    load_durable_jobs()
    assert len(cron.scheduled_jobs) == 2


def test_load_skips_invalid():
    # 手写一个非法 cron 的 durable 文件
    cron.DURABLE_PATH.write_text(json.dumps([
        {"id": "cron_1", "cron": "0 9 * * *", "prompt": "ok", "recurring": True, "durable": True},
        {"id": "cron_2", "cron": "bad", "prompt": "no", "recurring": True, "durable": True},
    ]))
    load_durable_jobs()
    assert "cron_1" in cron.scheduled_jobs
    assert "cron_2" not in cron.scheduled_jobs


# ── _check_and_fire ──
def test_check_and_fire_fires():
    job = schedule_job("* * * * *", "run")
    _check_and_fire(datetime(2026, 7, 4, 9, 0))
    assert job in cron.cron_queue
    assert cron._last_fired[job.id] == "2026-07-04 09:00"


def test_check_and_fire_dedup_same_marker():
    job = schedule_job("* * * * *", "run")
    _check_and_fire(datetime(2026, 7, 4, 9, 0))
    _check_and_fire(datetime(2026, 7, 4, 9, 0))  # 同分钟
    assert cron.cron_queue.count(job) == 1


def test_check_and_fire_next_minute():
    job = schedule_job("* * * * *", "run")
    _check_and_fire(datetime(2026, 7, 4, 9, 0))
    cron.cron_queue.clear()
    _check_and_fire(datetime(2026, 7, 4, 9, 1))  # 下一分钟
    assert job in cron.cron_queue


def test_check_and_fire_one_shot_removed():
    job = schedule_job("* * * * *", "run", recurring=False)
    _check_and_fire(datetime(2026, 7, 4, 9, 0))
    assert job.id not in cron.scheduled_jobs


def test_check_and_fire_recurring_kept():
    job = schedule_job("* * * * *", "run", recurring=True)
    _check_and_fire(datetime(2026, 7, 4, 9, 0))
    assert job.id in cron.scheduled_jobs


def test_check_and_fire_no_match_no_fire():
    schedule_job("0 9 * * *", "run")
    _check_and_fire(datetime(2026, 7, 4, 10, 0))  # 不匹配
    assert cron.cron_queue == []


def test_check_and_fire_bad_cron_no_crash():
    cron.scheduled_jobs["bad"] = CronJob("bad", "not cron", "p", True, False)
    schedule_job("* * * * *", "good")
    _check_and_fire(datetime(2026, 7, 4, 9, 0))  # 不崩
    assert len(cron.cron_queue) >= 1


# ── consume / has ──
def test_consume_empty():
    assert consume_cron_queue() == []
    assert has_cron_queue() is False


def test_consume_returns_and_clears():
    job = schedule_job("* * * * *", "run")
    _check_and_fire(datetime(2026, 7, 4, 9, 0))
    assert has_cron_queue() is True
    fired = consume_cron_queue()
    assert job in fired
    assert consume_cron_queue() == []


# ── 工具 handler ──
def test_run_schedule_cron_ok():
    msg = run_schedule_cron("0 9 * * *", "check")
    assert "Scheduled" in msg


def test_run_schedule_cron_bad():
    assert run_schedule_cron("bad", "check")  # 返错误串（非 Scheduled）


def test_run_list_crons_empty():
    assert "No cron" in run_list_crons()


def test_run_list_crons_format():
    job = schedule_job("0 9 * * *", "check progress")
    out = run_list_crons()
    assert job.id in out
    assert "0 9 * * *" in out
    assert "recurring" in out


def test_run_cancel_cron():
    job = schedule_job("0 9 * * *", "check")
    assert "Cancelled" in run_cancel_cron(job.id)
    assert "not found" in run_cancel_cron(job.id)
