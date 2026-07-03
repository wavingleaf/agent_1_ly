"""
Agent 编排核心 — 手写 StateGraph 实现 ReAct 循环

   ┌──────────┐   有tool_calls   ┌──────────┐
   │  agent   │ ───────────────→ │  tools   │
   │ (调LLM)  │ ←─────────────── │ (执行工具) │
   └────┬─────┘   返回结果       └──────────┘
        │ 无tool_calls
        ↓
      END

每次循环：
1. LLM 收到消息 → 推理 → 决定"调用工具 X" 或 "直接回答"
2. 如果决定调工具 → tools 节点执行 → 结果追加到消息列表 → 回到 1
3. 如果直接回答 → 结束
"""

import time
import logging

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_openai import ChatOpenAI

from .state import AgentState
from ..config.settings import settings
from ..tools.builtin import ALL_TOOLS
from ..memory.store import create_checkpointer

logger = logging.getLogger("agent.graph")


def build_graph():
    """
    构建 ReAct StateGraph。

    返回编译好的 graph，可调用 .invoke() 和 .astream()。
    checkpointer 使用 MemorySaver（进程重启后丢失）。
    AsyncSqliteSaver 持久化方案见 TODO 改进 #2。
    """

    # ── 初始化 LLM ──
    llm_kwargs = {
        "model": settings.MODEL_NAME,
        "api_key": settings.OPENAI_API_KEY,
    }
    if settings.OPENAI_BASE_URL:
        llm_kwargs["base_url"] = settings.OPENAI_BASE_URL

    model = ChatOpenAI(**llm_kwargs)
    llm_with_tools = model.bind_tools(ALL_TOOLS)

    # ── agent 节点：调用 LLM 进行推理 ──
    call_count = 0  # 闭包变量，统计 LLM 调用次数

    def agent_node(state: AgentState) -> dict:
        nonlocal call_count
        call_count += 1
        msg_count = len(state.get("messages", []))
        t0 = time.perf_counter()

        response = llm_with_tools.invoke(state["messages"])

        elapsed = time.perf_counter() - t0
        token_info = ""
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            token_info = f"，输入 {um.get('input_tokens','?')}，输出 {um.get('output_tokens','?')} tokens"

        tc_info = ""
        if hasattr(response, "tool_calls") and response.tool_calls:
            tc_info = "，tool_calls: [" + ", ".join(
                f"{tc['name']}({tc.get('args',{})})" for tc in response.tool_calls
            ) + "]"

        logger.info(
            "LLM #%d（%.2fs，消息数 %d%s%s）",
            call_count, elapsed, msg_count, token_info, tc_info,
        )

        return {"messages": [response]}

    # ── tools 节点：自动识别 AIMessage.tool_calls 并逐个执行 ──
    tool_node = ToolNode(ALL_TOOLS)

    # ── 组装 StateGraph ──
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")

    # 条件边：AIMessage 有 tool_calls → tools，否则 → END
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", "__end__": END},
    )
    # 普通边：tools 执行完 → 回到 agent
    workflow.add_edge("tools", "agent")

    checkpointer = create_checkpointer("memory")
    return workflow.compile(checkpointer=checkpointer)


# 全局实例
graph = build_graph()
