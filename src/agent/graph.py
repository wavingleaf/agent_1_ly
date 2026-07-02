"""
Agent 编排核心 — 第一版（create_agent 方式）

这是最简单的 Agent 创建方式：用 LangChain v1.0 的 create_agent()
一行代码创建具备工具调用能力的 Agent。

工作原理（隐藏在 create_agent 内部）：
1. 用户输入 → LLM 推理
2. LLM 决定"我需要调用工具 X，参数为 Y"
3. 框架执行工具 X(Y)，把结果返回给 LLM
4. LLM 基于工具结果给出最终回答
5. 如果 LLM 觉得还需要更多信息，回到步骤 2

这个循环就是著名的 ReAct（Reasoning + Acting）模式。

create_agent() 底层实际运行在 LangGraph 的 StateGraph 上，
所以它天然支持 checkpoint、streaming、human-in-the-loop 等高级特性。
"""

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from ..config.settings import settings
from ..tools.builtin import ALL_TOOLS


def build_agent():
    """
    构建 Agent 实例。

    返回的 agent 是一个编译好的 LangGraph StateGraph，
    可以直接调用 .invoke() 或 .astream()。
    """
    # 第一步：初始化模型
    # LangChain v1.0 中，ChatModel 统一了所有 LLM 的调用方式
    llm_kwargs = {
        "model": settings.MODEL_NAME,
        "api_key": settings.OPENAI_API_KEY,
    }
    # 如果配置了自定义 API 地址（中转/代理），加入 base_url
    if settings.OPENAI_BASE_URL:
        llm_kwargs["base_url"] = settings.OPENAI_BASE_URL

    model = ChatOpenAI(**llm_kwargs)

    # 第二步：用 create_agent() 创建 Agent
    # 参数说明：
    #   model          - LLM 实例（支持任何 LangChain ChatModel）
    #   tools          - 工具列表，LLM 自主决定何时调用哪个工具
    #   system_prompt  - 系统提示词，定义 Agent 的角色和行为规范
    agent = create_agent(
        model=model,
        tools=ALL_TOOLS,
        system_prompt="你是一个有用的助手。当用户询问时间或数学计算时，请使用提供的工具。回答使用中文。",
    )

    return agent


# 模块级全局实例 —— 其他模块直接从此处 import
# 注意：这在生产环境不是最佳实践（应用启动前就要有 API key），
# 但学习阶段这样写简单清晰。
agent = build_agent()
