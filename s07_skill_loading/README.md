# s07: Skill Loading

po-agent 第七阶段，参照 `learn-claude-code/s07_skill_loading`。给 agent **两级按需知识注入**：SYSTEM 常驻技能目录（便宜），`load_skill` 按需返全文（贵）。

## 本阶段完成（相对 s06）

在 s06 循环上做了一件核心事：**按需知识注入（不把所有知识塞 SYSTEM）**。

1. **`skills.py`**：启动扫 `skills/` 目录，`_parse_frontmatter` 解析 YAML frontmatter，建 `SKILL_REGISTRY`（name/description/content）；`scan_skills(skills_dir)` 显式可测；`list_skills()` 列目录；`load_skill(name)` 注册表查找返全文（不走文件系统，防路径穿越）。
2. **两级注入**：Layer 1——`build_system_prompt` 把 `list_skills()` 目录（name + 一行描述）注入 SYSTEM（~100 token/skill，常驻）；Layer 2——`load_skill` 工具按需返全文 SKILL.md（~2000 token/skill，经 tool_result）。
3. **`load_skill` 静态处理器**：读模块 `SKILL_REGISTRY`，无需 client → 直接进 `TOOL_HANDLERS`（与 s06 的 `task` 不同，task 要 client 走 `make_run_tool` extra）。
- **循环核心不变**——`load_skill` 经 `run_tool` 自动分发；子 agent 不给 load_skill（SUB_TOOLS 仍 5）。
- 比 s06 多了**按需知识**：技能全文不常驻，用到才加载，省上下文。

## 结构
- `config.py` — env + `make_tools`(8) + `make_sub_tools`(5) + 目录提示 + `load`(先 scan_skills)
- `tools.py` — s06 工具(6) + `load_skill` + `SUB_HANDLERS`(5) + `make_run_tool`
- `skills.py` — `SKILL_REGISTRY` + `_parse_frontmatter`/`scan_skills`/`list_skills`/`load_skill`
- `hooks.py` / `todo.py` / `subagent.py` / `agent.py` — 同 s06
- `cli.py` / `__main__.py` — REPL（load() 内 scan_skills）
- `skills/` — 样本技能（code-review、mcp-builder）

## 运行
```sh
source ../.venv/bin/activate
python -m s07_skill_loading
```

## 使用示例

SYSTEM 已列出技能目录（`Skills available:`）。让 agent 加载一个技能：

```
s07 >> 有哪些 skill？加载 code-review 并总结它建议的 review 步骤
```

```
[HOOK] load_skill(['code-review'])
```

`load_skill` 返回 `skills/code-review/SKILL.md` 全文（经 tool_result），agent 据此总结 review 步骤（完整阅读 → 查正确性 → 查风格 → 报告）。技能全文不常驻 SYSTEM，用到才加载——省上下文。

## 测试
```sh
pytest s07_skill_loading/tests -v
```
