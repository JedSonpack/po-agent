"""TodoNag — 规划提醒：连续 N 个 tool 轮未调 todo_write 就注入 reminder。"""


class TodoNag:
    def __init__(self, threshold: int = 3,
                 reminder: str = "<reminder>Update your todos.</reminder>"):
        self.rounds_since_todo = 0
        self.threshold = threshold
        self.reminder = reminder

    def maybe_nag(self, messages) -> str | None:
        """循环顶部调用：达阈值且 messages 非空 → 返回 reminder 并归零。"""
        if self.rounds_since_todo >= self.threshold and messages:
            self.rounds_since_todo = 0
            return self.reminder
        return None

    def on_round(self) -> None:
        """每个 tool 轮 +1（确认 tool_use 后、处理 block 前调用）。"""
        self.rounds_since_todo += 1

    def on_todo_write(self) -> None:
        """调 todo_write 后归零（处理完 todo_write block 后调用）。"""
        self.rounds_since_todo = 0
