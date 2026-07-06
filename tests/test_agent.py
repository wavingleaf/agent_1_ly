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
    from src.tools.builtin import ALL_TOOLS, DST_TOOLS, PLAN_TOOLS
    assert len(ALL_TOOLS) == 6
    tool_names = [t.name for t in ALL_TOOLS]
    assert tool_names == [
        "get_current_time", "calculator", "grep",
        "read_file", "list_files", "web_search",
    ]
    # DST 模式不含 get_current_time（避免 DeepSeek 误调）
    assert len(DST_TOOLS) == 5
    dst_names = [t.name for t in DST_TOOLS]
    assert "get_current_time" not in dst_names
    assert dst_names == ["calculator", "grep", "read_file", "list_files", "web_search"]
    # Plan 模式当前等同于 ALL_TOOLS
    assert len(PLAN_TOOLS) == 6


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


# ═══════════════════════════════════════════════════════════════
# read_file 工具测试
# ═══════════════════════════════════════════════════════════════

def test_read_file_basic():
    """测试 read_file 能读取已知文件"""
    from src.tools.read_file_ly import read_file

    # 搜索一个确定存在的文件 —— 用 grep 先找到的实际文件
    result = read_file.invoke({
        "file_path": "components/domesticatable.lua",
        "start_line": 1,
        "end_line": 10,
    })

    assert "错误" not in result
    assert "📄" in result
    # 前 10 行应该包含 require("easing") 或 easing（该文件的标准开头）
    assert ("require" in result or "easing" in result)


def test_read_file_range():
    """测试 read_file 行范围截断"""
    from src.tools.read_file_ly import read_file

    # 读一个范围
    result = read_file.invoke({
        "file_path": "components/domesticatable.lua",
        "start_line": 5,
        "end_line": 15,
    })

    assert "错误" not in result
    assert "第 5～15 行" in result or "5～" in result


def test_read_file_not_found():
    """测试 read_file 文件不存在时返回错误"""
    from src.tools.read_file_ly import read_file

    result = read_file.invoke({"file_path": "nonexistent/file.lua"})
    assert "不存在" in result or "错误" in result


# ═══════════════════════════════════════════════════════════════
# list_files 工具测试
# ═══════════════════════════════════════════════════════════════

def test_list_files_root():
    """测试 list_files 列出根目录"""
    from src.tools.list_files_ly import list_files

    result = list_files.invoke({"directory": ""})
    assert "错误" not in result
    assert "📁" in result


def test_list_files_subdir():
    """测试 list_files 列出子目录"""
    from src.tools.list_files_ly import list_files

    result = list_files.invoke({"directory": "components"})
    assert "错误" not in result
    # components 目录下应该有 Lua 文件
    assert ".lua" in result or "📁" in result or "📄" in result


def test_list_files_not_found():
    """测试 list_files 目录不存在时返回错误"""
    from src.tools.list_files_ly import list_files

    result = list_files.invoke({"directory": "nonexistent_dir_12345"})
    assert "不存在" in result or "错误" in result


# ═══════════════════════════════════════════════════════════════
# web_search 工具测试
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    True,  # 默认跳过，仅在有网络且手动执行时启用
    reason="需要网络连接，仅在手动测试时取消 skip",
)
def test_web_search_basic():
    """测试 web_search 能返回搜索结果（需要网络）"""
    from src.tools.web_search_ly import web_search

    result = web_search.invoke({"query": "DST beefalo domestication", "max_results": 3})
    assert "错误" not in result
    assert "🔍" in result
    assert len(result) > 50  # 应该有实质内容


def test_web_search_import():
    """测试 web_search 工具可导入且参数正确"""
    from src.tools.web_search_ly import web_search
    assert web_search.name == "web_search"
    # 验证参数
    params = web_search.args_schema.model_fields  # type: ignore[union-attr]
    assert "query" in params
    assert "max_results" in params
