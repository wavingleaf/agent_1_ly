"""
记忆与持久化模块

LangGraph 的 Checkpointer 负责在每个节点执行后自动保存 State 快照。
这使得 Agent 具备：
1. **跨请求记忆**：同一个 thread_id，第二次调用记得第一次的对话
2. **时间旅行**：可以回溯到任意历史快照，继续执行或分析
3. **故障恢复**：进程重启后恢复未完成的对话

Checkpointer 对比：
┌──────────────────┬──────────────┬──────────────┬────────────────┐
│                  │ MemorySaver  │ SqliteSaver  │ PostgresSaver  │
├──────────────────┼──────────────┼──────────────┼────────────────┤
│ 持久化           │ ❌ 内存      │ ✅ 磁盘      │ ✅ 数据库      │
│ 进程重启后       │ 丢失         │ 保留         │ 保留           │
│ 并发安全         │ ❌           │ ⚠️ 有限       │ ✅             │
│ 适合场景         │ 开发调试     │ 单机部署     │ 生产集群       │
└──────────────────┴──────────────┴──────────────┴────────────────┘

用法：
    from src.memory.store import create_checkpointer
    checkpointer = create_checkpointer("memory")  # 或 "sqlite"
    graph = workflow.compile(checkpointer=checkpointer)
"""

import os
import sqlite3
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from ..config.settings import settings


def create_checkpointer(backend: str = "memory"):
    """
    根据配置创建 Checkpointer（同步版本）。

    Args:
        backend: "memory" | "sqlite"

    Returns:
        BaseCheckpointSaver 实例

    SqliteSaver 构造方法：
    - 直接传 sqlite3.Connection —— 简单，适合单线程
    - from_conn_string() —— context manager 方式，自动管理连接生命周期
    这里用第一种，因为模块级全局实例需要在 import 时就创建好。
    check_same_thread=False 是必须的 —— LangGraph 可能在多线程中使用连接。
    """
    if backend == "sqlite":
        db_path = settings.SQLITE_DB_PATH
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        # 直接传 Connection 对象 —— 绕过 context manager 的限制
        conn = sqlite3.connect(db_path, check_same_thread=False)
        return SqliteSaver(conn)

    # 默认：内存（开发调试用）
    return MemorySaver()


async def create_async_checkpointer():
    """
    创建 AsyncSqliteSaver，用于 FastAPI 异步上下文中持久化对话历史。

    与同步版 create_checkpointer("sqlite") 的区别：
    - 使用 aiosqlite（异步 SQLite 驱动），不阻塞事件循环
    - 支持 astream() 的异步并发，不会出现"同步阻塞 async 队列"问题

    为什么不用 from_conn_string()：
    - from_conn_string() 返回 context manager，不能在模块级 import 时使用
    - 改用直接传 aiosqlite.Connection 给构造函数，绕开此限制
      （原因同 踩坑记录 #03）

    aiosqlite 已作为 langgraph-checkpoint-sqlite 的依赖自动安装。
    """
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = settings.SQLITE_DB_PATH
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = await aiosqlite.connect(db_path)
    return AsyncSqliteSaver(conn)
