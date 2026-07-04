# po-agent

逐步实现 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 的 Claude Code 学习项目。

**20 阶段进度总览：[PROGRESS.md](PROGRESS.md)**

## 环境

- Python 3.11，通过 [uv](https://docs.astral.sh/uv/) 管理的虚拟环境（不在本机安装 Python）
- 依赖见 `requirements.txt`

## 快速开始

```bash
# 创建虚拟环境（需先安装 uv：brew install uv）
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt

# 配置密钥（复制示例并填入真实值）
cp .env.example .env
```

## 配置说明

| 用途 | 文件 | 是否提交 | 内容 |
| --- | --- | --- | --- |
| Claude Code CLI | `.claude/settings.json` | 是 | 模型、主题等非密配置 |
| Claude Code CLI | `.claude/settings.local.json` | 否（gitignore） | `ANTHROPIC_AUTH_TOKEN` 密钥 |
| Python 应用 | `.env.example` | 是 | 模板 |
| Python 应用 | `.env` | 否（gitignore） | 真实密钥 |

密钥只存在于本地被 gitignore 的文件中，不会进入远端。
