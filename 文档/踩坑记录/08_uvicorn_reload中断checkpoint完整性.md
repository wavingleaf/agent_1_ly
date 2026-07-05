# 08 — uvicorn --reload 中断 checkpoint 完整性，导致 API 400 错误

**领域**：LangGraph + uvicorn · **触发条件**：agent 处理请求中途，文件变更触发 `--reload` 重启

---

## 问题现象

终端日志：

```
INFO:agent.api:开始流式处理 [thread=web-xxx]: 帮我查...
INFO:agent.graph:agent_node mode=dst tools=['calculator', 'grep']
INFO:watchfiles.main:2 changes detected         ← uvicorn 检测到文件变更
INFO:httpx:HTTP Request: POST ... "HTTP/1.1 400 Bad Request"
ERROR:agent.api:流式处理出错: Error code: 400 - {
  'error': {'message': "An assistant message with 'tool_calls' must be
   followed by tool messages responding to each 'tool_call_id'."}}
```

用户重试同一 thread_id 后，DeepSeek 返回 400 错误。

---

## 根因

uvicorn `--reload` 在 tool 节点执行途中重启进程：

```
时刻 T1: agent_node 产出 AIMessage(tool_calls=[grep])
时刻 T2: LangGraph 写入 checkpoint（含 AIMessage）
时刻 T3: ToolNode 执行 grep ← uvicorn 检测到 .py 文件变更，SIGTERM 杀进程
结果：checkpoint 保存了 [human, ai(tool_calls=[grep])] ← 缺少 ToolMessage
```

用户用同一 thread_id 重试时，LangGraph 从 checkpoint 恢复出截断的消息列表。`agent_node` 把它发给 DeepSeek → 模型检测到 `tool_calls` 缺少对应的 `tool` 回复 → 400 错误。

---

## 修复

`agent_node` 在构造消息列表后、发给 LLM 前，检测孤立的 `tool_calls`：

```python
for i, m in enumerate(msgs):
    tc_list = getattr(m, "tool_calls", None)
    if tc_list and isinstance(m, AIMessage):
        # 收集该 AIMessage 之后所有 ToolMessage 的 tool_call_id
        follow_ids = set()
        for j in range(i + 1, len(msgs)):
            tcid = getattr(msgs[j], "tool_call_id", None)
            if tcid:
                follow_ids.add(tcid)
        expected_ids = {tc["id"] for tc in tc_list if tc.get("id")}
        missing = expected_ids - follow_ids
        if missing:
            # 剥离不可恢复的 tool_calls，构造无 tool_calls 的备选 AIMessage
            logger.warning("检测到 %d 个孤立的 tool_calls，已剥离", len(missing))
            msgs[i] = AIMessage(content=m.content or "", id=m.id)
```

---

## 教训

- `--reload` 是开发便利项，但会中断正在执行的 StateGraph 节点，产生不一致的 checkpoint
- 修复不是在 uvicorn 层做（无法预测重启时机），而是在 LangGraph 层做弹性恢复——检测并剥离不可恢复的 tool_calls
- 生产环境不应使用 `--reload`，用 gunicorn + 多 worker 替代
