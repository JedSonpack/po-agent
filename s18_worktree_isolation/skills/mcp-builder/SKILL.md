---
name: mcp-builder
description: Build an MCP server that exposes tools to LLMs
---

# MCP Builder

Use this skill when asked to build an MCP (Model Context Protocol) server.

## Steps

1. **Pick transport** — stdio (local) or HTTP (remote).
2. **Define tools** — each tool: name, input schema, handler.
3. **Implement handlers** — pure functions, validate input, return JSON.
4. **Wire the server** — register tools, start transport loop.

## Rules

- One responsibility per tool.
- Never crash on bad input — return an error result.
- Keep tool descriptions short (one line).
