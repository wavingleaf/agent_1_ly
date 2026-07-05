# 06 — RunnableConfig 参数不被 LangGraph 注入

**领域**：LangGraph · **触发条件**：在 StateGraph 节点函数上用 `config: RunnableConfig` 参数标注

---

## 问题现象

在 `agent_node` 中用 `RunnableConfig` 类型标注作为第二个参数来获取 mode：

```python
from langchain_core.runnables import RunnableConfig

def agent_node(state: AgentState, config: RunnableConfig = None) -> dict:
    mode = config.get("configurable", {}).get("mode", "general") if config else "general"
```

预期：`graph.invoke(input, config={"configurable": {"mode": "dst"}})` 时 config 被自动注入。
实际：`config` 始终为 `None`，`mode` 永远回退到 `"general"`。

**后果**：DST 模式从未生效——工具集和 System Prompt 用的都是 general 模式的。

---

## 根因

LangGraph StateGraph 的节点函数签名中，**不会自动注入 `RunnableConfig` 参数**。这和 LangChain 的 Runnable 链不同——StateGraph 的边和节点是自定义执行的。

---

## 正确做法

使用 `langgraph.config.get_config()` 显式获取：

```python
from langgraph.config import get_config

def agent_node(state: AgentState) -> dict:
    config = get_config()
    mode = config.get("configurable", {}).get("mode", "general")
```

`get_config()` 是 LangGraph 1.x 提供的公共 API，在 StateGraph 节点的执行上下文中返回当前的 `RunnableConfig`。

---

## 教训

- StateGraph 节点函数接收的第二个参数不是 config——LangGraph 没有把 config 注入为位置/关键字参数的约定
- `get_config()` 是 LangGraph 1.x 推荐的做法，文档中有明确说明
- `invoke()` 和 `astream()` 的 config 传递方式相同——两者都通过 `get_config()` 读取
