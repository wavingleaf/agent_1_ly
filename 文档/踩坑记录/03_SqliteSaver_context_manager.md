# 03 — SqliteSaver.from_conn_string 返回 context manager

## 症状

```python
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("checkpoints.db")
workflow.compile(checkpointer=checkpointer)
# TypeError: Invalid checkpointer provided. Expected an instance of BaseCheckpointSaver.
# Received _GeneratorContextManager.
```

## 根因

LangGraph 1.2 中，`SqliteSaver.from_conn_string()` 和 `AsyncSqliteSaver.from_conn_string()` **不是构造函数**，而是 **context manager**（内部用 `yield` 实现）。它们的设计意图是：

```python
# 官方期望的用法（在 with 块内创建和使用）
with SqliteSaver.from_conn_string("checkpoints.db") as checkpointer:
    graph = workflow.compile(checkpointer=checkpointer)
    # ... 使用 graph ...
```

但本项目需要**模块级全局实例**——`graph = build_graph()` 在 import 时就执行，不能用 `with` 包裹。直接调用 `.from_conn_string()` 拿到的是未 `yield` 的 generator 对象，不是 `SqliteSaver` 实例。

## 修复

改为直接传 `sqlite3.Connection` 给构造函数：

```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)  # 直接构造，不用 from_conn_string
```

`check_same_thread=False` 是必须的——LangGraph 可能在多线程中访问 SQLite 连接。

## 替代方案

如果需要异步版本，可以改为 lazy init 模式（用 async factory 函数），在启动时而非 import 时创建 graph。但本项目选择同步版 `SqliteSaver`，因为 LangGraph 内部会把同步 checkpointer 放到线程池执行，兼容 `astream()`。

## 教训

LangGraph 的 checkpointer API 在版本迭代中多次变化。`from_conn_string()` 的 context manager 模式是 1.2 引入的——**网上旧教程如果直接用返回值当实例，在新版会直接报这个错**。
