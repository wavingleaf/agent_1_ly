"""
自定义 Agent 中间件

中间件是 LangChain v1.0 引入的扩展机制，借鉴了 Web 框架（FastAPI/Express）
的中间件模式。它让你在 Agent 生命周期的关键节点注入自定义逻辑，
而**不需要修改 agent 的核心代码**。

中间件的生命周期钩子：

    before_agent  → before_model → [LLM 调用] → after_model → ... → after_agent
                                    ↑ 可以被 wrap_model_call 包裹
                   工具调用链同理：
                   wrap_tool_call 包裹每个工具的执行

用法：
    agent = create_agent(
        model=...,
        tools=[...],
        middleware=[MyMiddleware()],  # 传入中间件列表
    )

约束：
- 中间件可以有状态（比如累积统计），但要注意并发安全
- before/after 钩子返回 dict 会合并到 AgentState
- wrap 钩子可以修改/拦截请求，实现权限控制、模型切换等
"""

import time
import logging
from dataclasses import dataclass, field
from langchain.agents.middleware import AgentMiddleware

# 获取模块级 logger
logger = logging.getLogger("agent.middleware")


# ============================================================================
# 中间件 1：请求日志中间件
# ============================================================================

@dataclass
class RequestLoggingMiddleware(AgentMiddleware):
    """
    记录每次 LLM 调用的耗时和 token 用量。

    使用 @dataclass 是因为中间件可以在多次调用间保持状态。
    AgentMiddleware 本身要求是可哈希的（用于去重），@dataclass 自动生成 __hash__。

    挂载方式：
        agent = create_agent(..., middleware=[RequestLoggingMiddleware()])
    """

    # 累积统计（在一个 agent 实例内跨多次调用累积）
    total_llm_calls: int = field(default=0, init=False)
    total_tool_calls: int = field(default=0, init=False)
    _call_start_time: float = field(default=0.0, init=False)

    def before_model(self, state, runtime) -> dict | None:
        """
        每次 LLM 被调用前触发。

        这里记录开始时间，以便 after_model 中计算耗时。

        参数：
            state:  当前的 AgentState（完整的消息历史等）
            runtime: Runtime 对象，包含 context、config 等运行时信息

        返回：
            dict | None —— 返回 dict 会合并到 AgentState，返回 None 则不变
        """
        self._call_start_time = time.perf_counter()
        msg_count = len(state.get("messages", []))
        logger.info(
            "🤖 LLM 调用 #%d 开始（当前消息数：%d）",
            self.total_llm_calls + 1,
            msg_count,
        )
        return None  # 不修改 state

    def after_model(self, state, runtime) -> dict | None:
        """
        每次 LLM 调用完成后触发。

        这里计算耗时和 token 用量。

        注意：after_model 即使 LLM 调用失败也会触发，
        此时 usage_metadata 可能为空。
        """
        elapsed = time.perf_counter() - self._call_start_time
        self.total_llm_calls += 1

        # 从最后一条 AI 消息中提取 token 用量
        messages = state.get("messages", [])
        token_info = ""
        if messages:
            last_msg = messages[-1]
            # LangChain v1.0 中，usage_metadata 包含 token 统计
            if hasattr(last_msg, "usage_metadata") and last_msg.usage_metadata:
                um = last_msg.usage_metadata
                input_tokens = um.get("input_tokens", "?")
                output_tokens = um.get("output_tokens", "?")
                token_info = f"，输入 {input_tokens} tokens，输出 {output_tokens} tokens"

        logger.info(
            "🤖 LLM 调用 #%d 完成（耗时 %.2f 秒%s）",
            self.total_llm_calls,
            elapsed,
            token_info,
        )
        return None

    def wrap_tool_call(self, request, handler):
        """
        包裹每个工具调用。

        这里记录工具调用日志，可以在此处做：
        - 权限检查（拒绝危险操作）
        - 参数校验/改写
        - 结果脱敏

        参数：
            request: ToolCallRequest，包含 tool_call（工具名+参数）等信息
            handler:  下一个处理器，调用 handler(request) 执行实际的工具调用

        返回：
            ToolMessage | Command —— 工具执行结果
        """
        tool_name = request.tool_call.get("name", "unknown")
        tool_args = request.tool_call.get("args", {})

        self.total_tool_calls += 1
        logger.info("🔧 工具调用 #%d：%s(%s)", self.total_tool_calls, tool_name, tool_args)

        # 调用 handler 执行实际的工具调用
        result = handler(request)

        # 精简结果日志（避免超长输出）
        result_str = str(result.content) if hasattr(result, "content") else str(result)
        if len(result_str) > 120:
            result_str = result_str[:120] + "..."

        logger.info("🔧 工具调用 #%d 完成：%s", self.total_tool_calls, result_str)
        return result
