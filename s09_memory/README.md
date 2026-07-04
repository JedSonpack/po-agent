# s09: Memory

po-agent 第九阶段，参照 `learn-claude-code/s09_memory`。加**持久跨会话记忆**：关键细节存 `.memory/`，压缩会丢的偏好/约束/项目事实跨会话存活。

## 本阶段完成（相对 s08）

在 s08 循环上做了一件核心事：**持久记忆层（压缩会丢的，记忆保留）**。

1. **`memory.py`（`Memory` 类）**：`.memory/` 存记忆文件（YAML frontmatter + body，type ∈ user/feedback/project/reference）+ `MEMORY.md` 索引（一行一记忆）。
   - **SYSTEM 注索引**（便宜，常驻）：`build_index_section()` 把索引 + "Respect user preferences... extract as memory" 引导追加到系统提示。
   - **按需注入**：`load_memories(messages)`——LLM 选相关记忆（JSON 索引，回退关键词），内容包 `<relevant_memories>` 注入当前 user 轮。
   - **提取**：turn 结束 `extract_memories(pre_compress)`——LLM 从对话抽 `{name,type,description,body}`，写新文件（去重看 existing）。
   - **整合**：记忆数 ≥ 10 → `consolidate_memories`——LLM 合并去重、删过时、≤30。
2. **`Memory` 注入 `agent_loop`**（`memory=None` 默认）：每轮注索引到 system、注入相关记忆到 user 轮（压缩前 `pre_compress` stringify 快照保真）、turn 结束提取+整合。
- **保留 s08 全部**（hooks/nag/compact 工具/load_skill/skills/subagent/Compactor）——记忆与这些正交共存。无新工具（记忆是内部机制）。
- 比 s08 多了**跨会话持久**：agent 记住用户偏好/项目事实，下次还在。

## 结构
- `config.py` / `tools.py` / `skills.py` / `hooks.py` / `todo.py` / `subagent.py` / `compact.py` — 同 s08
- `memory.py` — `Memory` 类（write/read/index/select/load/extract/consolidate + build_index_section）
- `agent.py` — `agent_loop`（注入 `memory`，加 system 索引/user 轮注入/turn 结束提取+整合/pre_compress 快照）
- `cli.py` / `__main__.py` — REPL（接线 `Memory`，建 `.memory/`）

## 运行
```sh
source ../.venv/bin/activate
python -m s09_memory
```

## 使用示例

告诉 agent 一个偏好：

```
s09 >> 记住：我喜欢深色主题，回答尽量简短
```

agent 口头确认后，turn 结束自动提取记忆：

```
[Memory: extracted 2 new memories]
```

`.memory/` 落记忆文件 + `MEMORY.md` 索引：

```
- [user-preference-dark-theme](user-preference-dark-theme.md) — User prefers dark theme
- [user-preference-concise-answers](user-preference-concise-answers.md) — User prefers short responses
```

下次启动时 SYSTEM 注入这个索引，相关记忆按需注入 user 轮——跨会话持久，压缩会丢的偏好这里保留。

## 测试
```sh
pytest s09_memory/tests -v
```
