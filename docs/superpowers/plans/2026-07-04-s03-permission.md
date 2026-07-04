# s03 Permission 实现计划

> **面向 AI 代理的工作者：** 用 superpowers:executing-plans 逐任务实现。复选框跟踪进度。

**目标：** s03 Permission——三道闸门权限管线插在工具执行前，行为对齐 `learn-claude-code/s03_permission`。
**架构：** `s03_permission` 包，沿用 s02；新增 `permissions.py`；`agent_loop` 注入 `check_permission(name,input)->bool`，deny → `"Permission denied."`。
**规格：** `docs/superpowers/specs/2026-07-04-s03-permission-design.md`

从 po-agent 根目录运行，先 `source .venv/bin/activate`。pytest 已装。

---

## 执行状态（2026-07-04 完成）

全部 7 个任务完成，34/34 测试通过，已推送 origin/main。验收：s03 实时跑通（write_file 过闸执行；rm 触发闸2 审批 ⚠）。

| 任务 | commit | 说明 |
|---|---|---|
| 1 包骨架 | `6bec31c` | 初始化包 |
| 2 tools | `762cc83` | run_bash 简化，危险检查移到权限层（18 测试） |
| 3 permissions | `efb8d7d` | 三道闸门管线（10 测试） |
| 4 agent | `b735a20` | agent_loop 注入 check_permission（3 测试） |
| 5 config | `08baebc` | SYSTEM 改为需审批（3 测试） |
| 6 cli + __main__ | `eacbb71` | REPL 入口 |
| 7 README + 全测 + push | `e8bb7c0` | 34 passed，推送 |

---

### 任务 1：包骨架
- 创建 `s03_permission/__init__.py`（`"""s03_permission — 三道闸门权限管线。"""`）、`s03_permission/tests/__init__.py`（空）
- 验证：`pytest s03_permission -q` → no tests ran（exit 5）
- Commit：`git add s03_permission/ && git commit -m "chore(s03): 初始化包骨架"`

### 任务 2：tools.py（TDD）
- 创建 `s03_permission/tests/test_tools.py` + `s03_permission/tools.py`
- `tools.py`：与 s02 相同，**但 `run_bash` 简化**（移除 DANGEROUS 检查，移到闸 1；无 encoding/OSError，与 s03 参考一致）：

```python
# s03_permission/tools.py
import glob as _glob
import subprocess
from pathlib import Path

WORKDIR = Path.cwd()
TIMEOUT = 120
MAX_OUTPUT = 50000


def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=TIMEOUT)
        out = (r.stdout + r.stderr).strip()
        return out[:MAX_OUTPUT] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text()
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str) -> str:
    try:
        results = []
        for match in _glob.glob(pattern, root_dir=WORKDIR):
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


TOOL_HANDLERS = {"bash": run_bash, "read_file": run_read, "write_file": run_write,
                 "edit_file": run_edit, "glob": run_glob}


def run_tool(name: str, input: dict) -> str:
    handler = TOOL_HANDLERS.get(name)
    return handler(**input) if handler else f"Unknown: {name}"
```

- `test_tools.py`：同 s02 的 test_tools，**但删掉 `test_dangerous_command_blocked`**（危险拦截移到 test_permissions）。即：`run_bash` 安全命令/超时(mock)/截断/空 + safe_path(3) + run_read(3) + run_write + run_edit(2) + run_glob(2) + run_tool(3) = 18 个。
- 验证：`pytest s03_permission/tests/test_tools.py -v` → 18 passed
- Commit：`git add s03_permission/tools.py s03_permission/tests/test_tools.py && git commit -m "feat(s03): 实现 tools（run_bash 简化，危险检查移到权限层）"`

### 任务 3：permissions.py（TDD，新模块）
- 创建 `s03_permission/tests/test_permissions.py` + `s03_permission/permissions.py`

```python
# s03_permission/permissions.py
from s03_permission import tools

DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]

PERMISSION_RULES = [
    {"tools": ["write_file", "edit_file"],
     "check": lambda args: not (tools.WORKDIR / args.get("path", "")).resolve().is_relative_to(tools.WORKDIR),
     "message": "Writing outside workspace"},
    {"tools": ["bash"],
     "check": lambda args: any(kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]),
     "message": "Potentially destructive command"},
]


def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return f"Blocked: '{pattern}' is on the deny list"
    return None


def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]
    return None


def ask_user(tool_name: str, args: dict, reason: str) -> str:
    print(f"\n\033[33m⚠  {reason}\033[0m")
    print(f"   Tool: {tool_name}({args})")
    choice = input("   Allow? [y/N] ").strip().lower()
    return "allow" if choice in ("y", "yes") else "deny"


def check_permission(name: str, input: dict) -> bool:
    if name == "bash":
        reason = check_deny_list(input.get("command", ""))
        if reason:
            print(f"\n\033[31m⛔ {reason}\033[0m")
            return False
    reason = check_rules(name, input)
    if reason:
        decision = ask_user(name, input, reason)
        if decision == "deny":
            return False
    return True
```

- `test_permissions.py`（monkeypatch `tools.WORKDIR`、`permissions.ask_user`、`builtins.input`）：

```python
# s03_permission/tests/test_permissions.py
import pytest
from s03_permission import tools, permissions


def test_check_deny_list_hits():
    assert permissions.check_deny_list("rm -rf /tmp") == "Blocked: 'rm -rf /' is on the deny list"
    assert permissions.check_deny_list("sudo ls") == "Blocked: 'sudo' is on the deny list"


def test_check_deny_list_safe():
    assert permissions.check_deny_list("ls -la") is None


def test_check_rules_write_outside(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert permissions.check_rules("write_file", {"path": "/etc/x", "content": "y"}) == "Writing outside workspace"


def test_check_rules_bash_destructive(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert permissions.check_rules("bash", {"command": "rm foo"}) == "Potentially destructive command"
    assert permissions.check_rules("bash", {"command": "ls"}) is None


def test_ask_user_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert permissions.ask_user("bash", {"command": "rm x"}, "r") == "allow"


def test_ask_user_no(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert permissions.ask_user("bash", {"command": "rm x"}, "r") == "deny"


def test_check_permission_deny_list(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert permissions.check_permission("bash", {"command": "rm -rf /"}) is False


def test_check_permission_rule_allow(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    monkeypatch.setattr(permissions, "ask_user", lambda *a: "allow")
    assert permissions.check_permission("bash", {"command": "rm foo"}) is True


def test_check_permission_rule_deny(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    monkeypatch.setattr(permissions, "ask_user", lambda *a: "deny")
    assert permissions.check_permission("bash", {"command": "rm foo"}) is False


def test_check_permission_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert permissions.check_permission("bash", {"command": "ls"}) is True
    assert permissions.check_permission("read_file", {"path": "a.txt"}) is True
```

- 验证：`pytest s03_permission/tests/test_permissions.py -v` → 10 passed
- Commit：`git add s03_permission/permissions.py s03_permission/tests/test_permissions.py && git commit -m "feat(s03): 实现三道闸门权限管线"`

### 任务 4：agent.py（TDD）
- 创建 `s03_permission/tests/test_agent.py` + `s03_permission/agent.py`

```python
# s03_permission/agent.py
from typing import Callable, Optional


def agent_loop(
    *,
    client,
    model: str,
    system: str,
    tools: list,
    messages: list,
    run_tool: Callable[[str, dict], str],
    check_permission: Callable[[str, dict], bool],
    max_tokens: int = 8000,
    on_tool_use: Optional[Callable] = None,
) -> None:
    while True:
        response = client.messages.create(
            model=model, system=system, messages=messages,
            tools=tools, max_tokens=max_tokens,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if on_tool_use:
                on_tool_use(block.name, None)
            if not check_permission(block.name, block.input):
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "Permission denied."})
                continue
            output = run_tool(block.name, block.input)
            if on_tool_use:
                on_tool_use(block.name, output)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```

- `test_agent.py`（fake client + fake run_tool + fake check_permission）：

```python
# s03_permission/tests/test_agent.py
from types import SimpleNamespace
from s03_permission.agent import agent_loop


def make_response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def tool_use_block(bid, name, inp):
    return SimpleNamespace(type="tool_use", id=bid, name=name, input=inp)


def text_block(t):
    return SimpleNamespace(type="text", text=t)


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **kwargs):
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def test_allowed_tool_runs():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", check_permission=lambda n, i: True)
    assert msgs[2]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "OUT"}


def test_denied_tool_returns_permission_denied():
    client = FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "rm -rf /"})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    run_calls = []
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: run_calls.append(n) or "OUT",
               check_permission=lambda n, i: False)
    assert run_calls == []  # 未执行
    assert msgs[2]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "Permission denied."}


def test_on_tool_use_called_before_and_after():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    calls = []
    def on_use(name, output):
        calls.append((name, output))
    agent_loop(client=client, model="m", system="s", tools=[],
               messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", check_permission=lambda n, i: True,
               on_tool_use=on_use)
    assert calls == [("read_file", None), ("read_file", "OUT")]
```

- 验证：`pytest s03_permission/tests/test_agent.py -v` → 3 passed
- Commit：`git add s03_permission/agent.py s03_permission/tests/test_agent.py && git commit -m "feat(s03): agent_loop 注入 check_permission"`

### 任务 5：config.py（轻量 TDD）
- 创建 `s03_permission/tests/test_config.py` + `s03_permission/config.py`
- 与 s02 config 相同，但 `build_system_prompt` = `"You are a coding agent at {cwd}. All destructive operations require user approval."`；`make_tools()` 同 s02（5 工具）
- `test_config.py`：`make_tools` 5 个、`build_system_prompt` 含 "approval"、`prepare_env` pop AUTH_TOKEN（同 s02 测试，3 个）
- 验证：`pytest s03_permission/tests/test_config.py -v` → 3 passed
- Commit：`git add s03_permission/config.py s03_permission/tests/test_config.py && git commit -m "feat(s03): 实现 config（SYSTEM 改为需审批）"`

### 任务 6：cli + __main__（导入冒烟）
- 创建 `s03_permission/cli.py` + `s03_permission/__main__.py`

```python
# s03_permission/cli.py
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s03_permission.agent import agent_loop
from s03_permission.config import load
from s03_permission.tools import run_tool
from s03_permission.permissions import check_permission


def print_tool_use(name: str, output) -> None:
    if output is None:
        print(f"\033[36m> {name}\033[0m")
    else:
        print(str(output)[:200])


def main() -> None:
    cfg = load()
    print("s03: Permission")
    print("输入问题，回车发送。输入 q 退出。\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms03 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(
            client=cfg["client"], model=cfg["model"], system=cfg["system"],
            tools=cfg["tools"], messages=history, run_tool=run_tool,
            check_permission=check_permission, on_tool_use=print_tool_use,
        )
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
```

```python
# s03_permission/__main__.py
from s03_permission.cli import main
main()
```

- 导入冒烟：`python -c "from s03_permission.cli import main; from s03_permission.permissions import check_permission; print('ok')"`
- Commit：`git add s03_permission/cli.py s03_permission/__main__.py && git commit -m "feat(s03): 实现 REPL 入口"`

### 任务 7：README + 全量测试 + 推送 + 实时验收
- 写 `s03_permission/README.md`（结构 + 运行 + 测试 + `## 本阶段完成（相对 s02）` 一节）
- 全量：`pytest s03_permission/tests -v` → 34 passed（tools 18 + permissions 10 + agent 3 + config 3）
- Commit：`git add s03_permission/README.md && git commit -m "docs(s03): 添加阶段 README"`
- 推送：`git push`
- 实时验收：`printf 'Create a file called test.txt in the current directory\n' | python -m s03_permission`——写工作区内文件，闸 2 规则 1 不命中（在工作区内）→ 直接执行；或试 `Delete the file test.txt` 触发闸 2（bash rm）→ 管道喂 "y" 批准。s03 跑通 = 验收。

## 自检
1. 规格覆盖：tools/permissions/agent/config/cli/README/验收 均有任务。✓
2. 占位符：无。✓
3. 类型一致：`check_permission(name, input)->bool` 在 permissions/agent/test 一致；`on_tool_use(name, output)`（output 可 None）一致；DENY_LIST/PERMISSION_RULES 定义。✓
