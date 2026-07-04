import glob as _glob
import subprocess
from pathlib import Path

WORKDIR = Path.cwd()
TIMEOUT = 120
MAX_OUTPUT = 50000


def run_bash(command: str) -> str:
    # s03：危险命令拦截移到权限层（check_deny_list），这里只负责执行
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
