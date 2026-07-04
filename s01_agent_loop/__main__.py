# __main__.py —— 让包可以用 `python -m s01_agent_loop` 运行
#
# 执行 `python -m 包名` 时，Python 会运行包里的 __main__.py。这是一个约定入口。

from s01_agent_loop.cli import main

main()  # 启动 REPL
