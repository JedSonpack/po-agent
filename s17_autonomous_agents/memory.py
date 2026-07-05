"""Memory — 持久跨会话记忆：SYSTEM 注索引 + 按需注入 + turn 结束提取 + 整合。"""
import json
import re
import time
from pathlib import Path

from s17_autonomous_agents.skills import _parse_frontmatter
from s17_autonomous_agents.subagent import extract_text

MEMORY_TYPES = ["user", "feedback", "project", "reference"]
CONSOLIDATE_THRESHOLD = 10


class Memory:
    """持久记忆层。client/model 用于选择/提取/整合的 LLM 调用；memory_dir 存记忆文件。"""

    def __init__(self, *, client, model, memory_dir, max_items=5,
                 consolidate_threshold=CONSOLIDATE_THRESHOLD,
                 select_max_tokens=2000, extract_max_tokens=4000,
                 consolidate_max_tokens=4000):
        self.client = client
        self.model = model
        self.memory_dir = Path(memory_dir)
        self.max_items = max_items
        self.consolidate_threshold = consolidate_threshold
        self.select_max_tokens = select_max_tokens
        self.extract_max_tokens = extract_max_tokens
        self.consolidate_max_tokens = consolidate_max_tokens

    def write_memory_file(self, name, mem_type, description, body) -> Path:
        """写单个记忆文件（YAML frontmatter + body），重建索引。"""
        slug = name.lower().replace(" ", "-").replace("/", "-")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        path = self.memory_dir / f"{slug}.md"
        path.write_text(
            f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n\n{body}\n"
        )
        self._rebuild_index()
        return path

    def _rebuild_index(self):
        """从所有记忆文件重建 MEMORY.md 索引（一行一记忆）。"""
        lines = []
        for f in sorted(self.memory_dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            raw = f.read_text()
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", f.stem)
            desc = meta.get("description", body.split("\n")[0][:80])
            lines.append(f"- [{name}]({f.name}) — {desc}")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        (self.memory_dir / "MEMORY.md").write_text("\n".join(lines) + "\n" if lines else "")

    def read_memory_index(self) -> str:
        path = self.memory_dir / "MEMORY.md"
        if not path.exists():
            return ""
        text = path.read_text().strip()
        return text if text else ""

    def read_memory_file(self, filename) -> str | None:
        path = self.memory_dir / filename
        if not path.exists():
            return None
        return path.read_text()

    def list_memory_files(self) -> list[dict]:
        result = []
        for f in sorted(self.memory_dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            raw = f.read_text()
            meta, body = _parse_frontmatter(raw)
            result.append({
                "filename": f.name,
                "name": meta.get("name", f.stem),
                "description": meta.get("description", ""),
                "type": meta.get("type", "user"),
                "body": body,
            })
        return result

    def select_relevant_memories(self, messages) -> list[str]:
        """LLM 选相关记忆索引 → filenames；失败回退关键词匹配。"""
        files = self.list_memory_files()
        if not files:
            return []

        # 最近 3 条 user 文本
        recent_texts = []
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = " ".join(str(getattr(b, "text", "")) for b in content
                                       if getattr(b, "type", None) == "text")
                if isinstance(content, str):
                    recent_texts.append(content)
                if len(recent_texts) >= 3:
                    break
        recent = " ".join(reversed(recent_texts))[:2000]
        if not recent.strip():
            return []

        catalog = "\n".join(f"{i}: {f['name']} — {f['description']}" for i, f in enumerate(files))
        prompt = (
            "Given the recent conversation and the memory catalog below, "
            "select the indices of memories that are clearly relevant. "
            "Return ONLY a JSON array of integers, e.g. [0, 3]. "
            "If none are relevant, return [].\n\n"
            f"Recent conversation:\n{recent}\n\n"
            f"Memory catalog:\n{catalog}"
        )
        try:
            response = self.client.messages.create(
                model=self.model, messages=[{"role": "user", "content": prompt}],
                max_tokens=self.select_max_tokens,
            )
            text = extract_text(response.content).strip()
            match = re.search(r"\[.*?\]", text, re.DOTALL)
            if match:
                indices = json.loads(match.group())
                selected = []
                for idx in indices:
                    if isinstance(idx, int) and 0 <= idx < len(files):
                        selected.append(files[idx]["filename"])
                        if len(selected) >= self.max_items:
                            break
                return selected
        except Exception:
            pass

        # 回退：关键词匹配 name + description
        keywords = [w.lower() for w in recent.split() if len(w) > 3]
        selected = []
        for f in files:
            text = (f["name"] + " " + f["description"]).lower()
            if any(kw in text for kw in keywords):
                selected.append(f["filename"])
                if len(selected) >= self.max_items:
                    break
        return selected

    def load_memories(self, messages) -> str:
        """选相关记忆 → 读内容 → 包 <relevant_memories>。"""
        selected_files = self.select_relevant_memories(messages)
        if not selected_files:
            return ""
        parts = ["<relevant_memories>"]
        for filename in selected_files:
            content = self.read_memory_file(filename)
            if content:
                parts.append(content)
        parts.append("</relevant_memories>")
        return "\n\n".join(parts)

    def extract_memories(self, messages) -> None:
        """从最近对话抽新记忆（LLM），写文件。turn 结束调用。"""
        dialogue_parts = []
        for msg in messages[-10:]:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(getattr(b, "text", "")) for b in content
                                   if getattr(b, "type", None) == "text")
            if isinstance(content, str) and content.strip():
                dialogue_parts.append(f"{role}: {content}")
        dialogue = "\n".join(dialogue_parts)
        if not dialogue.strip():
            return

        existing = self.list_memory_files()
        existing_desc = ("\n".join(f"- {m['name']}: {m['description']}" for m in existing)
                         if existing else "(none)")
        prompt = (
            "Extract user preferences, constraints, or project facts from this dialogue.\n"
            "Return a JSON array. Each item: {name, type, description, body}.\n"
            "- name: short kebab-case identifier (e.g. 'user-preference-tabs')\n"
            "- type: one of 'user' (user preference), 'feedback' (guidance), "
            "'project' (project fact), 'reference' (external pointer)\n"
            "- description: one-line summary for index lookup\n"
            "- body: full detail in markdown\n"
            "If nothing new or already covered by existing memories, return [].\n\n"
            f"Existing memories:\n{existing_desc}\n\n"
            f"Dialogue:\n{dialogue[:4000]}"
        )
        try:
            response = self.client.messages.create(
                model=self.model, messages=[{"role": "user", "content": prompt}],
                max_tokens=self.extract_max_tokens,
            )
            text = extract_text(response.content).strip()
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if not match:
                return
            items = json.loads(match.group())
            if not items:
                return
            count = 0
            for mem in items:
                name = mem.get("name", f"memory_{int(time.time())}")
                mem_type = mem.get("type", "user")
                desc = mem.get("description", "")
                body = mem.get("body", "")
                if desc and body:
                    self.write_memory_file(name, mem_type, desc, body)
                    count += 1
            if count:
                print(f"\n\033[33m[Memory: extracted {count} new memories]\033[0m")
        except Exception:
            pass

    def consolidate_memories(self) -> None:
        """记忆数 ≥ threshold → LLM 合并去重，删旧重写。"""
        files = self.list_memory_files()
        if len(files) < self.consolidate_threshold:
            return
        catalog = "\n\n".join(
            f"## {f['filename']}\nname: {f['name']}\ndescription: {f['description']}\n{f['body']}"
            for f in files
        )
        prompt = (
            "Consolidate the following memory files. Rules:\n"
            "1. Merge duplicates into one\n"
            "2. Remove outdated/contradicted memories\n"
            "3. Keep the total under 30 memories\n"
            "4. Preserve important user preferences above all\n"
            "Return a JSON array. Each item: {name, type, description, body}.\n\n"
            f"{catalog[:16000]}"
        )
        try:
            response = self.client.messages.create(
                model=self.model, messages=[{"role": "user", "content": prompt}],
                max_tokens=self.consolidate_max_tokens,
            )
            text = extract_text(response.content).strip()
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if not match:
                return
            items = json.loads(match.group())
            # 删旧记忆文件（保留 MEMORY.md）
            for f in self.memory_dir.glob("*.md"):
                if f.name != "MEMORY.md":
                    f.unlink()
            for mem in items:
                name = mem.get("name", f"memory_{int(time.time())}")
                mem_type = mem.get("type", "user")
                desc = mem.get("description", "")
                body = mem.get("body", "")
                if desc and body:
                    self.write_memory_file(name, mem_type, desc, body)
            print(f"\n\033[33m[Memory: consolidated {len(files)} → {len(items)} memories]\033[0m")
        except Exception:
            pass

    def build_index_section(self) -> str:
        """追加到 SYSTEM 的记忆索引段（含引导）。无记忆 → 空。"""
        index = self.read_memory_index()
        if not index:
            return ""
        return (f"\n\nMemories available:\n{index}\n"
                "Relevant memories are injected below. Respect user preferences from memory.\n"
                "When the user says 'remember' or expresses a clear preference, extract it as a memory.")
