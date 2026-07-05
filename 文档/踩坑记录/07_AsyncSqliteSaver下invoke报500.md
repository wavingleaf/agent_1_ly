# 07 — AsyncSqliteSaver 下同步 `invoke()` 500 报错

**领域**：LangGraph · **触发条件**：lifespan 中将 graph 升级为 AsyncSqliteSaver 后，用同步 `graph.invoke()` 调用 `/chat` 端点

---

## 问题现象

FastAPI 启动日志显示 `AsyncSqliteSaver 初始化完成`，但 `/chat` 端点返回 HTTP 500。日志中无 `agent_node` 输出——请求在进入节点之前就失败了。

---

## 根因

`lifespan` 中将全局 graph 替换为 `AsyncSqliteSaver` 实例后，checkpointer 的所有 I/O 操作（读/写 checkpoint）都是异步的。同步 `graph.invoke()` 在调用 checkpointer 时会触发 `asyncio` 事件循环冲突或类型错误，导致 500。

`/chat/stream` 端点不受影响——`graph.astream()` 天然兼容异步 checkpointer。

---

## 修复

将 `/chat` 端点从同步 `graph.invoke()` 改为异步 `await graph.ainvoke()`：

```python
# ❌ 错误
result = graph.invoke(...)

# ✅ 正确
result = await graph.ainvoke(...)
```

```python
# ❌ 原因：AsyncSqliteSaver 是异步 checkpointer，invoke() 同步调用会触发事件循环冲突
# ✅ 修复：改为 await graph.ainvoke()，与异步 checkpointer 兼容
```

---

## 教训

- AsyncSqliteSaver 必须搭配 `ainvoke()` / `astream()`，不能用同步版
- 测试时 `build_graph()` 默认用 `MemorySaver`（同步），两条路径行为不同——lifespan 升级 checkpointer 后 `/chat` 的行为会变
- 写集成测试时如果用了 `await graph.ainvoke()`，测试函数本身也要是 `async def`
