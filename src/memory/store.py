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
    根据配置创建 Checkpointer。

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
