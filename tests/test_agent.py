"""
Agent 基础测试

在 CI 或本地运行：
    cd d:/Github项目/agent项目/agent_langchain_1_ly
    D:/Apps/Python/python.exe -m pytest tests/ -v

注意：集成测试需要 .env 中有有效的 OPENAI_API_KEY。
在没有有效 API key 的环境会自动跳过。
"""

import pytest

# pydantic-settings 会自动从 .env 文件加载；os.getenv 则只看真实环境变量。
# 测试中用 settings 来判断是否有有效 API key，避免误 skip。
from src.config.settings import settings


def test_settings_load():
    """测试配置能正确加载"""
    from src.config.settings import settings
    assert settings.MODEL_NAME, "MODEL_NAME 不能为空"


def test_tools_import():
    """测试工具模块可导入并有工具"""
    from src.tools.builtin import ALL_TOOLS, DST_TOOLS
    assert len(ALL_TOOLS) == 3
    assert ALL_TOOLS[0].name == "get_current_time"
    assert ALL_TOOLS[1].name == "calculator"
    assert ALL_TOOLS[2].name == "grep"
    # DST 模式不含 get_current_time（避免 DeepSeek 误调）
    assert len(DST_TOOLS) == 2
    assert DST_TOOLS[0].name == "calculator"
    assert DST_TOOLS[1].name == "grep"


def test_state_structure():
    """测试 AgentState 结构正确"""
    from src.agent.state import AgentState
    assert "messages" in AgentState.__annotations__


def test_graph_builds():
    """测试 graph 能成功编译"""
    from src.agent.graph import graph

    assert "agent" in graph.nodes


def test_checkpointer_factory_memory():
    """测试 MemorySaver 创建"""
    from src.memory.store import create_checkpointer
    c = create_checkpointer("memory")
    from langgraph.checkpoint.memory import MemorySaver
    assert isinstance(c, MemorySaver)


def test_checkpointer_factory_sqlite():
    """测试 SqliteSaver 创建"""
    from src.memory.store import create_checkpointer
    c = create_checkpointer("sqlite")
    from langgraph.checkpoint.sqlite import SqliteSaver
    assert isinstance(c, SqliteSaver)


def test_grep_tool_basic():
    """测试 grep 工具能正常搜索 DST 源码"""
    from src.tools.grep_ly import grep

    # 搜索一个确定存在的组件名 —— domesticatable.lua 中应该有 SetDomestication
    result = grep.invoke({"pattern": "SetDomestication"})

    # 应该找到匹配
    assert "未找到" not in result
    assert "错误" not in result
    assert "domesticatable" in result.lower() or "匹配" in result


def test_grep_tool_not_found():
    """测试 grep 工具在搜不到时返回提示"""
    from src.tools.grep_ly import grep

    result = grep.invoke({"pattern": "ThisSymbolDefinitelyDoesNotExist12345"})
    assert "未找到" in result


@pytest.mark.skipif(
    not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY.startswith("sk-xxx"),
    reason="需要有效的 OPENAI_API_KEY（不能是占位值 sk-xxx）",
)
def test_agent_invoke():
    """集成测试：实际调用 Agent（需要 API key）"""
    from src.agent.graph import graph

    result = graph.invoke(
        {"messages": [{"role": "user", "content": "1+1等于几？直接回答数字"}]},
        config={"configurable": {"thread_id": "test-1"}},
    )

    # 至少应该有用户消息、AI 回复
    assert len(result["messages"]) >= 2


@pytest.mark.skipif(
    not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY.startswith("sk-xxx"),
    reason="需要有效的 OPENAI_API_KEY",
)
def test_multi_turn_memory():
    """集成测试：多轮对话记忆"""
    from src.agent.graph import graph

    config = {"configurable": {"thread_id": "test-memory"}}

    # 第一轮
    graph.invoke(
        {"messages": [{"role": "user", "content": "我的名字叫测试员"}]},
        config=config,
    )

    # 第二轮
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "我叫什么名字？直接回答"}]},
        config=config,
    )

    # 找最后一条 AI 消息
    for msg in reversed(result["messages"]):
        if getattr(msg, "type", "") == "ai" and msg.content:
            assert "测试员" in msg.content, f"Agent 应该记住名字，但回复是: {msg.content}"
            break
