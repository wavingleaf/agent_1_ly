# 04 — create_agent 图节点名：model vs agent

## 症状

测试代码检查 `"agent" in graph.nodes` 时，手写版（`build_graph()`）通过，`create_agent()` 版（`agent_with_middleware`）失败。

## 根因

**`create_agent()` 编译后的 LangGraph 图中，LLM 调用节点叫 `model`，不叫 `agent`。**

手写版 `build_graph()` 中我们自己命名的：

```python
workflow.add_node("agent", agent_node)  # ← 我们叫它 "agent"
```

`create_agent()` 内部等效于：

```python
workflow.add_node("model", call_model_node)  # ← 框架叫它 "model"
```

这是 LangChain 团队有意为之——节点名反映的是"这个节点调用模型"，而非"这个节点就是 Agent 的全部"。同时 `before_model` / `after_model` 中间件钩子命名也和节点名对齐。

## 两个版本的实际节点列表

```python
# 手写 StateGraph
graph.nodes.keys()  → ['__start__', 'agent', 'tools']

# create_agent() + Middleware（每个中间件钩子都是独立节点）
agent_with_middleware.nodes.keys()
→ ['__start__', 'model', 'tools',
   'RequestLoggingMiddleware.before_model',
   'RequestLoggingMiddleware.after_model']
```

## 修复

在测试中分开处理：

```python
assert 'agent' in graph.nodes               # 手写版
assert 'model' in agent_with_middleware.nodes  # create_agent 版
```

生产代码中用 `graph.nodes` 检查节点存在性时，需要知道用的是哪种构建方式。

## 教训

框架的"缩写版 API"（`create_agent()`）和"底层 API"（`StateGraph`）存在命名约定差异。**测试中不要假设两者的内部实现一致**——它们本就不应该一致。
