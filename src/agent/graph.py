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
from langgraph.config import get_config
from langchain_openai import ChatOpenAI

from .state import AgentState
from ..config.settings import settings
from ..tools.builtin import ALL_TOOLS, DST_TOOLS, PLAN_TOOLS
from ..memory.store import create_checkpointer

logger = logging.getLogger("agent.graph")

# ═══════════════════════════════════════════════════════════════
# System Prompts — 按模式分发
#
# 设计原则（2026-07-04）：
# - system prompt 和工具描述必须「双管齐下」，不因 DeepSeek 遵循度弱而敷衍
#   system prompt。GPT-4/Claude 等模型会认真读 system prompt，DeepSeek 更
#   依赖 function calling schema，两个信号源都要覆盖。
# - Plan 模式当前为占位（项目尚无文件编辑工具），仅做身份声明。
# ═══════════════════════════════════════════════════════════════

DST_SYSTEM_PROMPT = (
    "你是 DST（Don't Starve Together，饥荒联机版）Mod 开发助手。\n"
    "DST 是 Klei Entertainment 开发的生存游戏，使用 Lua 作为 Mod 脚本语言。\n"
    "你的工作：帮助开发者查询 DST 的 Lua 源码，分析组件、API、TUNING 常量和控制台命令。\n"
    "\n"
    "可用工具：\n"
    "1. grep —— 搜索源码中的函数定义、组件实现、TUNING 值。\n"
    "   触发词：查/搜/找/看看/在哪/定义/源码/代码/函数/组件/命令/API/参数。\n"
    "   示例：\n"
    "   - \"SetDomestication 在哪定义\" → grep(pattern=\"SetDomestication\")\n"
    "   - \"beefalo 有哪些驯化方法\" → grep(pattern=\"domesticatable\")\n"
    "   - \"AXE_DAMAGE 值是多少\" → grep(pattern=\"AXE_DAMAGE\")\n"
    "2. calculator —— 执行数学计算。触发词：算/计算/等于/乘/加/减/除。\n"
    "\n"
    "行为规则：\n"
    "- 收到请求后直接调用工具，不要反问用户确认（如\"DST 是什么\"）。\n"
    "- grep 搜不到时，换搜索词重试（如搜更短的子串、搜组件文件名）。\n"
    "- 看到 grep 结果后，优先用简洁语言总结：文件路径、行号、核心逻辑。\n"
    "  如果贴出关键代码片段有助于理解，可以贴——grep 结果本身就供你分析用。\n"
    "- 用户要求搜索源码时，一定用 grep，不要直接回答\"我不知道\"。"
)

GENERAL_SYSTEM_PROMPT = (
    "你是一个通用的开发者助手，可以使用工具来完成任务。\n"
    "你可以搜索源码、执行计算、获取时间，请根据用户需求选择合适的工具。\n"
    "\n"
    "工具使用规则：\n"
    "1. grep —— 在配置的源码目录中搜索文件内容。\n"
    "   触发词：查/搜/找/看看/在哪/定义/源码/代码/函数/组件/命令/API。\n"
    "   注意：当前搜索的是本地文件系统中的源码，不是网络搜索。\n"
    "2. calculator —— 执行数学计算。触发词：算/计算/等于/乘/加/减/除。\n"
    "3. get_current_time —— 获取当前时间。只有明确问时间（\"几点\"\"今天几号\"）才调用。\n"
    "\n"
    "行为规则：\n"
    "- 收到请求后先判断最适合的工具，然后直接调用。\n"
    "- 不要调用无关工具——问源码用 grep，问时间用 get_current_time，问计算用 calculator。"
)

PLAN_SYSTEM_PROMPT = (
    "你处于规划模式（Plan Mode），当前任务是探索和理解问题，不是执行修改。\n"
    "你可以使用工具来搜索源码、执行计算、获取时间，但最终目标是帮用户理清思路、\n"
    "输出一个清晰的计划，而不是直接修改任何东西。\n"
    "\n"
    "行为规则：\n"
    "- 多提问、多探索，不要急于给出结论。\n"
    "- 输出结构化的分析结果或计划。\n"
    "- 本模式当前为占位——项目尚无文件编辑工具，Plan 模式仅影响回答风格。"
)

# 模式 → System Prompt 映射
MODE_PROMPTS = {
    "dst": DST_SYSTEM_PROMPT,
    "general": GENERAL_SYSTEM_PROMPT,
    "plan": PLAN_SYSTEM_PROMPT,
}

# 模式 → 工具集映射（Plan 模式为占位，未来可能精简工具）
MODE_TOOLS = {
    "dst": DST_TOOLS,
    "general": ALL_TOOLS,
    "plan": PLAN_TOOLS,
}

# 默认模式
DEFAULT_MODE = "general"


def build_graph(checkpointer=None):
    """
    构建 ReAct StateGraph。

    Args:
        checkpointer: 可选，传入预创建的 checkpointer 实例。
                      为 None 时默认使用 MemorySaver（测试用）。

    Returns:
        编译好的 graph。调用 .invoke() 时通过 config 传入 mode：
            graph.invoke(input, config={"configurable": {"thread_id": "...", "mode": "dst"}})
    """

    # ── 初始化 LLM ──
    llm_kwargs = {
        "model": settings.MODEL_NAME,
        "api_key": settings.OPENAI_API_KEY,
    }
    if settings.OPENAI_BASE_URL:
        llm_kwargs["base_url"] = settings.OPENAI_BASE_URL

    model = ChatOpenAI(**llm_kwargs)

    # ── agent 节点：调用 LLM 进行推理 ──
    call_count = 0  # 闭包变量，统计 LLM 调用次数

    def agent_node(state: AgentState) -> dict:
        nonlocal call_count
        call_count += 1
        msg_count = len(state.get("messages", []))
        t0 = time.perf_counter()

        # 用 get_config() 获取 mode —— StateGraph 不会自动将 config
        # 注入为函数参数，必须显式调用 get_config() 才能拿到。
        # （之前用 RunnableConfig 类型标注作为参数，LangGraph 1.x
        #  不会注入它，config 始终为 None，导致 mode 永远回退到 general。）
        config = get_config()
        mode = config.get("configurable", {}).get("mode", DEFAULT_MODE)
        system_prompt = MODE_PROMPTS.get(mode, GENERAL_SYSTEM_PROMPT)
        tools = MODE_TOOLS.get(mode, ALL_TOOLS)

        # Debug: 记录模式与工具选择，便于排查路由问题
        logger.info("agent_node mode=%s tools=%s", mode, [t.name for t in tools])

        # 每次 LLM 调用前把 system prompt 作为第一条消息临时插入。
        # 不追加到 state 中，避免 system 消息被反复累积到对话历史。
        msgs = list(state["messages"])
        if not msgs or getattr(msgs[0], "type", "") != "system":
            msgs = [{"role": "system", "content": system_prompt}] + msgs

        # 修复 checkpoint 损坏导致的 tool_calls 不完整问题。
        # uvicorn --reload 可能在 tool 节点执行过程中重启进程，
        # 导致 checkpoint 保存了 AIMessage(tool_calls=[...]) 但缺少
        # 对应的 ToolMessage。直接发给 LLM 会触发 API 400 错误：
        # "tool_calls must be followed by tool messages"。
        # 修复方式：检测不完整的 tool_calls 配对，剥离缺失的 tool_calls。
        from langchain_core.messages import AIMessage

        for i, m in enumerate(msgs):
            tc_list = getattr(m, "tool_calls", None)
            if tc_list and isinstance(m, AIMessage):
                # 收集该 AI 消息之后所有 ToolMessage 的 tool_call_id
                follow_ids = set()
                for j in range(i + 1, len(msgs)):
                    tcid = getattr(msgs[j], "tool_call_id", None)
                    if tcid:
                        follow_ids.add(tcid)
                expected_ids = {tc["id"] for tc in tc_list if tc.get("id")}
                missing = expected_ids - follow_ids
                if missing:
                    # 有 tool_call_id 在后续消息中找不到对应 ToolMessage——
                    # 说明 checkpoint 在此处被截断。替换为无 tool_calls 的副本。
                    logger.warning(
                        "agent_node: 检测到 %d 个孤立的 tool_calls（%s），"
                        "已剥离（可能是 --reload 重启导致 checkpoint 不完整）",
                        len(missing), ", ".join(sorted(missing)[:3]),
                    )
                    repaired = AIMessage(
                        content=m.content or "",
                        id=m.id,
                    )
                    msgs[i] = repaired

        # 按模式绑定工具集（Plan 模式为占位，工具集暂与 general 相同）
        llm_with_tools = model.bind_tools(tools)
        response = llm_with_tools.invoke(msgs)

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
            "LLM #%d [%s]（%.2fs，消息数 %d%s%s）",
            call_count, mode, elapsed, msg_count, token_info, tc_info,
        )

        return {"messages": [response]}

    # ── tools 节点：自动识别 AIMessage.tool_calls 并逐个执行 ──
    # 使用 ALL_TOOLS 而非动态切换，因为 ToolNode 在 compile 时创建。
    # 不同模式用相同的工具池，路由由 system prompt + 工具描述控制。
    # Plan 模式为占位，当前工具池不区分。
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

    if checkpointer is None:
        checkpointer = create_checkpointer("memory")
    return workflow.compile(checkpointer=checkpointer)


# ── 全局实例 ──
# 默认用 MemorySaver 编译，保证 import 后立即可用（测试、脚本等场景）。
# FastAPI 启动时通过 lifespan 调用 `init_graph(checkpointer)` 替换为 AsyncSqliteSaver 实例。
graph = build_graph()


def init_graph(checkpointer=None):
    """
    重新初始化全局 graph 实例，用于 FastAPI lifespan 中替换 checkpointer。

    调用时机：FastAPI 启动时，在 lifespan 中创建 AsyncSqliteSaver 后调用。
    不调用此函数时 graph 默认为 MemorySaver（测试兼容）。
    """
    global graph
    graph = build_graph(checkpointer=checkpointer)
    return graph
