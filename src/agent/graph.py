"""
Agent 编排核心

提供两种构建方式：
1. build_graph()          — 手写 StateGraph（v2，教学用），完全掌控每个节点
2. build_agent_with_middleware() — 用 create_agent() + 中间件（v3，推荐），
   兼顾简洁与可扩展性

ReAct 循环 = 两个节点 + 一条条件边：

    ┌──────────┐   有tool_calls   ┌──────────┐
    │  agent   │ ─────────────────→ │  tools   │
    │ (调LLM)  │ ←───────────────── │ (执行工具) │
    └────┬─────┘   返回结果         └──────────┘
         │ 无tool_calls
         ↓
       END

每次循环：
1. LLM 收到消息 → 推理 → 决定"调用工具 X" 或 "直接回答"
2. 如果决定调工具 → tools 节点执行 → 结果追加到消息列表 → 回到 1
3. 如果直接回答 → 结束
"""

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from .state import AgentState
from .middleware import RequestLoggingMiddleware
from ..config.settings import settings
from ..tools.builtin import ALL_TOOLS
from ..memory.store import create_checkpointer


def build_graph():
    """
    手动构建 ReAct StateGraph。

    返回编译好的 graph，可调用 .invoke() 和 .astream()。
    """

    # ==================================================================
    # 第 1 步：初始化 LLM（绑定工具）
    # ==================================================================
    # bind_tools() 的作用：告诉 LLM "你有这些工具可用"
    # LLM 在推理时会根据 user prompt 自动决定是否需要调用工具
    # 如果需要，AIMessage 会包含 tool_calls 字段
    llm_kwargs = {
        "model": settings.MODEL_NAME,
        "api_key": settings.OPENAI_API_KEY,
    }
    if settings.OPENAI_BASE_URL:
        llm_kwargs["base_url"] = settings.OPENAI_BASE_URL

    model = ChatOpenAI(**llm_kwargs)
    # 关键：将工具绑定到模型上
    llm_with_tools = model.bind_tools(ALL_TOOLS)

    # ==================================================================
    # 第 2 步：定义节点函数
    # ==================================================================
    # 节点函数签名：fn(state: AgentState) → dict（返回部分状态更新）
    # 返回的 dict 会用 AgentState 中定义的 reducer 合并到全局 state

    def agent_node(state: AgentState) -> dict:
        """
        Agent 节点：调用 LLM 进行推理。

        输入 state.messages（完整的对话历史）
        输出 {"messages": [AIMessage]}，可能包含 tool_calls
        """
        response = llm_with_tools.invoke(state["messages"])
        # 返回 dict 格式 —— LangGraph 会自动用 add_messages 合并
        return {"messages": [response]}

    # ToolNode 是 LangGraph 预置的工具执行节点
    # 它自动识别 AIMessage 中的 tool_calls，逐个执行并将结果打包为 ToolMessage
    tool_node = ToolNode(ALL_TOOLS)

    # ==================================================================
    # 第 3 步：组装 StateGraph
    # ==================================================================
    workflow = StateGraph(AgentState)

    # 注册节点
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    # 设置入口：用户输入从 agent 节点开始
    workflow.set_entry_point("agent")

    # 添加条件边：agent 节点执行完后 →
    #   - 如果 AIMessage 包含 tool_calls → 去 tools 节点
    #   - 否则 → END
    # tools_condition 是 LangGraph 内置的路由函数，阅读 AIMessage 做判断
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",  # tools_condition 返回 "tools" → 去 tools 节点
            "__end__": END,    # tools_condition 返回 "__end__" → 结束
        },
    )

    # 添加普通边：tools 节点执行完 → 回 agent 节点
    # 这形成了循环：agent → tools → agent → tools → ... → agent → END
    workflow.add_edge("tools", "agent")

    # ==================================================================
    # 第 4 步：添加 Checkpointer（持久化状态）
    # ==================================================================
    # create_checkpointer("memory") — 内存存储，进程重启后丢失（开发用）
    # create_checkpointer("sqlite") — 磁盘存储，进程重启后保留（生产用）
    checkpointer = create_checkpointer("memory")

    # 编译 —— 把"蓝图"变成可执行的 graph
    # interrupt_before 为 None 表示不自动暂停
    return workflow.compile(checkpointer=checkpointer)


def build_graph_with_persistence():
    """
    手动构建 ReAct StateGraph + SQLite 持久化（v2-prod 版）

    与 build_graph() 的区别仅在于 checkpointer：
    - MemorySaver → SqliteSaver
    - 进程重启后对话历史不丢失
    - 适合部署到单机服务器
    """
    llm_kwargs = {
        "model": settings.MODEL_NAME,
        "api_key": settings.OPENAI_API_KEY,
    }
    if settings.OPENAI_BASE_URL:
        llm_kwargs["base_url"] = settings.OPENAI_BASE_URL

    model = ChatOpenAI(**llm_kwargs)
    llm_with_tools = model.bind_tools(ALL_TOOLS)

    def agent_node(state: AgentState) -> dict:
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    tool_node = ToolNode(ALL_TOOLS)

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", "__end__": END},
    )
    workflow.add_edge("tools", "agent")

    # 关键区别：用 SQLite 替代 Memory
    # AsyncSqliteSaver 支持异步场景（FastAPI 的 astream() 需要）
    checkpointer = create_checkpointer("sqlite")
    return workflow.compile(checkpointer=checkpointer)


def build_agent_with_middleware():
    """
    用 create_agent() + 中间件构建 Agent（v3，推荐方式）

    与 build_graph() 的手写方式不同，这里用 create_agent() 的简洁 API，
    通过中间件注入自定义逻辑，实现"核心逻辑不变，外围功能可插拔"。

    中间件的优势：
    - 不修改核心 agent 代码即可加日志/监控/权限/PII脱敏
    - 多个中间件可以组合（顺序很重要，先添加的先执行）
    - 官方提供了多个开箱即用的中间件
    """
    llm_kwargs = {
        "model": settings.MODEL_NAME,
        "api_key": settings.OPENAI_API_KEY,
    }
    if settings.OPENAI_BASE_URL:
        llm_kwargs["base_url"] = settings.OPENAI_BASE_URL

    model = ChatOpenAI(**llm_kwargs)

    agent = create_agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt="你是一个有用的助手。当用户询问时间或数学计算时，请使用提供的工具。回答使用中文。",
        # 中间件按列表顺序执行 —— 先添加的先包裹（洋葱模型）
        middleware=[
            RequestLoggingMiddleware(),
        ],
    )

    return agent


# ======================================================================
# 模块级全局实例
# ======================================================================
# v2: 手写 StateGraph + MemorySaver（教学/开发用）
graph = build_graph()

# v2-prod: 手写 StateGraph + SqliteSaver（生产用，进程重启后保留记忆）
graph_persistent = build_graph_with_persistence()

# v3: create_agent() + 中间件（快速原型）
agent_with_middleware = build_agent_with_middleware()
