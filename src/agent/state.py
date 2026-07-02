"""
AgentState 定义 — Agent 在节点间流转的共享数据结构

用 TypedDict 定义 State 的"形状"，用 Annotated 指定每个字段
在多节点并行/串联更新时的合并策略（reducer）。

关键概念：
- 普通字段（如 str, int）：后写入的覆盖前一个，没问题
- messages 字段：用 add_messages 做追加（追加而非覆盖），
  因为 agent 节点和 tools 节点都要往 messages 里追加新消息

add_messages 是 LangGraph 内置的消息合并函数：
- 如果是新消息 → 追加到列表末尾
- 如果是同一消息 ID 的更新 → 原地替换（用于流式场景）
"""

from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """
    Agent 的共享状态。

    流转过程：
    1. 用户输入 → messages = [HumanMessage]
    2. agent 节点 → messages 追加 AIMessage（可能含 tool_calls）
    3. tools 节点 → messages 追加 ToolMessage（工具执行结果）
    4. agent 节点 → messages 追加 AIMessage（最终回答）
    """

    # Annotated[类型, 合并函数] —— LangGraph 的核心类型体操
    # add_messages 确保消息是"追加"而非"覆盖"
    messages: Annotated[list, add_messages]
