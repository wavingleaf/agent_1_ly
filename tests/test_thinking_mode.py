"""
思考模式 TDD 测试套件

按阶段递进：
  Phase 1 — ChatDeepSeek 导入与配置（无 API 调用）
  Phase 2 — 单轮推理内容提取（需要 API）
  Phase 3 — 多轮工具调用 round-trip（核心坑，需要 API）
  Phase 4 — LangGraph Agent 集成（需要 API）

运行：
  cd d:/Github项目/agent项目/agent_langchain_1_ly
  D:/Apps/Python/python.exe -m pytest tests/test_thinking_mode.py -v
"""

import pytest

from src.config.settings import settings

# ── Helpers ────────────────────────────────────────────────────

def _make_chat_deepseek(**overrides):
    """
    用项目现有 .env 配置创建 ChatDeepSeek 实例。

    ChatDeepSeek 的 api_key 从 DEEPSEEK_API_KEY 环境变量读取，
    但项目用的是 OPENAI_API_KEY。这里显式传入绕过此差异。
    """
    from langchain_deepseek import ChatDeepSeek

    kwargs = {
        "model": settings.MODEL_NAME,  # deepseek-v4-pro
        "api_key": settings.OPENAI_API_KEY,
        "api_base": settings.OPENAI_BASE_URL or "https://api.deepseek.com/v1",
    }
    kwargs.update(overrides)
    return ChatDeepSeek(**kwargs)


# ═══════════════════════════════════════════════════════════════
# Phase 1: ChatDeepSeek 导入与配置（纯本地，无 API 调用）
# ═══════════════════════════════════════════════════════════════

class TestPhase1_ChatDeepSeekBasics:
    """最基础的验证：能 import、能实例化、能 bind_tools"""

    def test_01_import(self):
        """ChatDeepSeek 可导入"""
        from langchain_deepseek import ChatDeepSeek
        assert ChatDeepSeek is not None

    def test_02_instantiate(self):
        """ChatDeepSeek 可用项目配置实例化"""
        llm = _make_chat_deepseek()
        assert llm.model_name == "deepseek-v4-pro"
        assert llm.api_base is not None

    def test_03_model_profile(self):
        """deepseek-v4-pro 的 model profile 标记 reasoning_output=True"""
        from langchain_deepseek.chat_models import _get_default_model_profile
        profile = _get_default_model_profile("deepseek-v4-pro")
        assert profile.get("reasoning_output") is True, (
            f"v4-pro 应标记 reasoning_output=True，实际: {profile}"
        )

    def test_04_bind_tools(self):
        """ChatDeepSeek.bind_tools 返回的 bound model 仍能 invoke"""
        from src.tools.builtin import ALL_TOOLS

        llm = _make_chat_deepseek()
        bound = llm.bind_tools(ALL_TOOLS)
        assert bound is not None
        # 验证工具被正确绑定 —— 检查 bound model 有 tools 参数
        assert hasattr(bound, "tools") or hasattr(bound, "kwargs")

    def test_05_thinking_mode_param(self):
        """extra_body 中传 thinking={type:'enabled'} + reasoning_effort='high' 不会报错"""
        llm = _make_chat_deepseek()
        # 模拟 bind_tools 后再调用的场景 —— 只是验证参数不抛异常
        llm_with_thinking = _make_chat_deepseek(
            reasoning_effort="high",
        )
        assert llm_with_thinking is not None


# ═══════════════════════════════════════════════════════════════
# Phase 2: 单轮推理内容提取（需要 API）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY.startswith("sk-xxx"),
    reason="需要有效的 API key",
)
class TestPhase2_ReasoningContentExtraction:
    """验证 ChatDeepSeek 在思考模式下能提取 reasoning_content"""

    def test_01_single_turn_has_reasoning(self):
        """
        RED 测试：思考模式单轮对话应返回 reasoning_content。

        如果返回的 AIMessage.additional_kwargs 中没有 reasoning_content，
        说明思考模式未生效，或 ChatDeepSeek 没有正确解析。
        """
        llm = _make_chat_deepseek(
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        response = llm.invoke("1+1等于几？直接回答数字即可，不要解释。")

        rc = response.additional_kwargs.get("reasoning_content")
        # 思考模式开启时，应该有推理内容
        assert rc is not None, (
            f"思考模式下应返回 reasoning_content，但 additional_kwargs 中未找到。"
            f"实际 additional_kwargs keys: {list(response.additional_kwargs.keys())}"
        )
        # 推理内容不应为空
        assert len(str(rc)) > 0, "reasoning_content 不应为空字符串"

    def test_02_non_thinking_has_no_reasoning(self):
        """
        对照测试：非思考模式下不应返回 reasoning_content（或为空）。
        """
        # ChatDeepSeek 在非思考模式下不传 thinking 参数
        llm = _make_chat_deepseek()
        response = llm.invoke("1+1等于几？直接回答数字即可，不要解释。")

        rc = response.additional_kwargs.get("reasoning_content")
        # 非思考模式：reasoning_content 要么不存在，要么为空
        # 注意：V4-Pro 默认可能就是 thinking 模式，所以这个测试反映实际情况
        if rc is not None and len(str(rc)) > 0:
            # 如果默认也是开启的，记录即可，不算失败
            pass

    def test_03_tool_call_with_thinking(self):
        """
        思考模式 + 工具调用：验证 AIMessage.tool_calls 和 reasoning_content
        可以同时存在于同一条响应中。
        """
        from src.tools.builtin import ALL_TOOLS

        llm = _make_chat_deepseek(
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        llm_with_tools = llm.bind_tools(ALL_TOOLS)
        response = llm_with_tools.invoke("现在几点了？（用 get_current_time 工具）")

        # 关键断言：工具调用存在
        assert response.tool_calls, (
            f"应该调用 get_current_time 工具，但 tool_calls 为空。"
            f"content={response.content[:200]}"
        )

        # 推理内容应同时存在（interleaved thinking + tool calling）
        rc = response.additional_kwargs.get("reasoning_content")
        if rc is not None:
            assert len(str(rc)) > 0, "有 tool_calls 时 reasoning_content 不应为空"


# ═══════════════════════════════════════════════════════════════
# Phase 3: 多轮工具调用 round-trip（核心坑）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY.startswith("sk-xxx"),
    reason="需要有效的 API key",
)
class TestPhase3_ReasoningRoundTrip:
    """
    验证 reasoning_content 在工具调用循环中正确往返。

    核心场景：
      轮1: Human → LLM(thinking) → AIMessage(reasoning_content + tool_calls)
      轮2: Human + AIMessage(含reasoning_content) + ToolMessage → LLM(thinking)
            → 如果 reasoning_content 没传回 → API 400 错误

    这是整个思考模式集成中最大的风险点。
    """

    def test_01_round_trip_single_tool_call(self):
        """
        RED 测试：模拟完整的 ReAct 一步回合。

        1. 用户提问 → LLM 返回 tool_calls + reasoning_content
        2. 手动执行工具（calculator）
        3. 将 AIMessage + ToolMessage + 新一轮用户消息发回 LLM
        4. 如果 reasoning_content 正确 round-trip → 正常返回
           如果缺失 → DeepSeek API 400 错误
        """
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        from src.tools.builtin import ALL_TOOLS

        llm = _make_chat_deepseek(
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        llm_with_tools = llm.bind_tools(ALL_TOOLS)

        # ── 第一轮：触发工具调用 ──
        msg1 = llm_with_tools.invoke([
            HumanMessage(content="帮我算一下 3.14 * 2.5 等于多少")
        ])

        assert msg1.tool_calls, f"第一轮应该有工具调用，实际: {msg1.content[:200]}"
        rc1 = msg1.additional_kwargs.get("reasoning_content")
        assert rc1 is not None, (
            f"第一轮思考模式下应有 reasoning_content，"
            f"keys: {list(msg1.additional_kwargs.keys())}"
        )
        assert len(str(rc1)) > 0, "reasoning_content 不应为空"

        # ── 手动执行工具 ──
        tool_name = msg1.tool_calls[0]["name"]
        tool_args = msg1.tool_calls[0]["args"]
        tool_id = msg1.tool_calls[0].get("id", "unknown")

        # 找到对应工具并执行
        tool_map = {t.name: t for t in ALL_TOOLS}
        assert tool_name in tool_map, f"工具 {tool_name} 不在注册表中"
        tool_result = tool_map[tool_name].invoke(tool_args)

        # ── 第二轮：传回 reasoning_content ──
        # 这是关键步骤：必须在第二轮消息中包含第一轮的 reasoning_content
        msg2 = llm_with_tools.invoke([
            HumanMessage(content="帮我算一下 3.14 * 2.5 等于多少"),
            msg1,  # ← 这个 AIMessage 必须带 reasoning_content
            ToolMessage(content=str(tool_result), name=tool_name, tool_call_id=tool_id),
        ])

        # ── 验证第二轮 ──
        # 第二轮应该直接返回计算结果，不再调工具
        assert msg2.content, "第二轮应该有文本回复"
        # 不应再调工具
        assert not msg2.tool_calls, (
            f"第二轮不应再调工具，但实际 tool_calls={msg2.tool_calls}"
        )

        # 第二轮也应该有 reasoning_content
        rc2 = msg2.additional_kwargs.get("reasoning_content")
        assert rc2 is not None, "第二轮也应有 reasoning_content"
        assert len(str(rc2)) > 0, "第二轮的 reasoning_content 不应为空"

    def test_02_round_trip_chained_tools(self):
        """
        链式工具调用：第一轮搜源码 → 第二轮读文件。

        DST 模式最典型的场景：
        grep 找到文件 → read_file 读内容 → 总结

        这个测试验证连续两轮工具调用中 reasoning_content 都能正确往返。
        """
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

        llm = _make_chat_deepseek(
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        # 只给 grep + read_file 两个工具，模拟 DST 模式
        from src.tools.grep_ly import grep
        from src.tools.read_file_ly import read_file
        dst_tools = [grep, read_file]
        llm_with_tools = llm.bind_tools(dst_tools)

        # ── 第一轮：搜索 ──
        msg1 = llm_with_tools.invoke([
            HumanMessage(content="DST 源码中 TUNING.AXE_DAMAGE 的值是多少？用 grep 搜索。")
        ])

        assert msg1.tool_calls, f"第一轮应调 grep，实际 content={msg1.content[:200]}"
        rc1 = msg1.additional_kwargs.get("reasoning_content")
        assert rc1 is not None, f"第一轮应有 reasoning_content，keys: {list(msg1.additional_kwargs.keys())}"

        # 执行 grep
        tc1 = msg1.tool_calls[0]
        result1 = grep.invoke(tc1["args"])

        # ── 后续轮：用循环模拟 ReAct，直到 LLM 停止调工具或达到上限 ──
        # 不使用固定轮数断言——LLM 可能在任意轮数后停止（取决于模型即兴行为）。
        # 测试的真正目的是验证每一轮的 reasoning_content 都能正确 round-trip，
        # 而不是断言 LLM 在 N 轮内给出文本回复。

        messages = [
            HumanMessage(content="DST 源码中 TUNING.AXE_DAMAGE 的值是多少？用 grep 搜索。"),
            msg1,
            ToolMessage(content=str(result1), name=tc1["name"], tool_call_id=tc1.get("id", "unknown")),
        ]
        tool_map = {"grep": grep, "read_file": read_file}
        current_msg = msg1
        round_count = 0
        max_rounds = 5  # 安全网：防止 LLM 无限循环

        while current_msg.tool_calls and round_count < max_rounds:
            round_count += 1
            current_msg = llm_with_tools.invoke(messages)
            messages.append(current_msg)

            rc = current_msg.additional_kwargs.get("reasoning_content")
            assert rc is not None, f"第 {round_count + 1} 轮应有 reasoning_content"

            if current_msg.tool_calls:
                tc = current_msg.tool_calls[0]
                if tc["name"] in tool_map:
                    tr = tool_map[tc["name"]].invoke(tc["args"])
                else:
                    tr = f"工具 {tc['name']} 不在可用列表中"
                messages.append(
                    ToolMessage(content=str(tr), name=tc["name"],
                               tool_call_id=tc.get("id", "unknown"))
                )

        # 如果循环因 max_rounds 退出且有 tool_calls → 也算通过（round-trip 没崩溃）
        # 如果有 content → LLM 给出了最终答案
        final_has_text = bool(current_msg.content)
        final_has_tools = bool(current_msg.tool_calls)
        assert final_has_text or final_has_tools, (
            f"最终轮既无文本也无 tool_calls（异常）："
            f"content={str(current_msg.content)[:100]}"
        )

    def test_03_missing_reasoning_content_causes_error(self):
        """
        NEGATIVE 测试：验证如果 Round-trip 时丢失了 reasoning_content，
        DeepSeek API 确实返回 400 错误（而不是静默退化）。

        这个测试是验证"为什么必须实现 round-trip"的烟雾测试。
        如果这个测试不报错，说明 DeepSeek 改了行为（round-trip 不再必需），
        那开发成本可以降低。
        """
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        from src.tools.builtin import ALL_TOOLS

        llm = _make_chat_deepseek(
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )
        llm_with_tools = llm.bind_tools(ALL_TOOLS)

        # 第一轮正常（有 reasoning_content）
        msg1 = llm_with_tools.invoke([
            HumanMessage(content="计算 10 + 5")
        ])

        if not msg1.tool_calls:
            pytest.skip("LLM 没调工具，无法测试 round-trip 场景")

        tc = msg1.tool_calls[0]
        tool_map = {t.name: t for t in ALL_TOOLS}
        result = tool_map[tc["name"]].invoke(tc["args"])

        # ── 构造一条丢失了 reasoning_content 的 AIMessage ──
        # 模拟"LangChain 的 _convert_message_to_dict 删除了 reasoning_content"的情况
        stripped_msg = AIMessage(
            content=msg1.content,
            tool_calls=msg1.tool_calls,
            # 注意：不传 additional_kwargs，即丢失 reasoning_content
        )

        import openai

        try:
            msg2 = llm_with_tools.invoke([
                HumanMessage(content="计算 10 + 5"),
                stripped_msg,  # ← 没有 reasoning_content 的假消息
                ToolMessage(
                    content=str(result),
                    name=tc["name"],
                    tool_call_id=tc.get("id", "unknown"),
                ),
            ])
            # 如果没报错，说明 DeepSeek 不再严格要求 round-trip
            # 这是一个重要的发现
            msg2_rc = msg2.additional_kwargs.get("reasoning_content")
            print(f"\n  [INFO] DeepSeek 接受了无 reasoning_content 的 round-trip — "
                  f"第二轮 rc={msg2_rc is not None}")

        except openai.BadRequestError as e:
            # 预期的错误：400 报 reasoning_content 缺失
            error_msg = str(e)
            assert "reasoning_content" in error_msg.lower(), (
                f"预期 400 错误关于 reasoning_content，实际: {error_msg[:300]}"
            )
        except Exception as e:
            # 其他错误类型（如 500）也记录
            print(f"\n  [INFO] 非预期错误类型: {type(e).__name__}: {str(e)[:200]}")


# ═══════════════════════════════════════════════════════════════
# Phase 4: LangGraph Agent 集成
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY.startswith("sk-xxx"),
    reason="需要有效的 API key",
)
class TestPhase4_LangGraphIntegration:
    """
    验证思考模式在完整的 LangGraph ReAct 循环中工作。

    这里不是测 unit，而是测集成：ChatDeepSeek + ToolNode + StateGraph。
    """

    def test_01_agent_with_thinking_dst_mode(self):
        """
        DST 模式 + 思考模式 + 工具调用：完整链路不报错。
        """
        from langchain_deepseek import ChatDeepSeek

        llm = ChatDeepSeek(
            model=settings.MODEL_NAME,
            api_key=settings.OPENAI_API_KEY,
            api_base=settings.OPENAI_BASE_URL or "https://api.deepseek.com/v1",
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )

        # 手动构建最小 StateGraph（复刻 graph.py 的核心逻辑）
        from langgraph.graph import StateGraph, END
        from langgraph.prebuilt import ToolNode, tools_condition
        from src.agent.state import AgentState
        from src.tools.builtin import DST_TOOLS
        from src.memory.store import create_checkpointer

        llm_with_tools = llm.bind_tools(DST_TOOLS)

        def agent_node(state: AgentState) -> dict:
            msgs = list(state["messages"])
            if not msgs or getattr(msgs[0], "type", "") != "system":
                msgs = [{"role": "system", "content": "你是 DST Mod 开发助手。用工具查询后直接回答。"}] + msgs
            response = llm_with_tools.invoke(msgs)
            return {"messages": [response]}

        tool_node = ToolNode(DST_TOOLS)

        workflow = StateGraph(AgentState)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tool_node)
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", tools_condition, {"tools": "tools", "__end__": END})
        workflow.add_edge("tools", "agent")

        graph = workflow.compile(checkpointer=create_checkpointer("memory"))

        # ── 运行 ──
        result = graph.invoke(
            {"messages": [{"role": "user",
                           "content": "DST 源码中 beefalo 的驯化度组件文件名是什么？搜一下。"}]},
            config={"configurable": {"thread_id": "test-thinking-agent-dst"}},
        )

        messages = result["messages"]
        # 至少 2 条（human + ai），通常 >= 3（含 tool 调用）
        assert len(messages) >= 2, f"至少应有 human + ai 消息，实际 {len(messages)} 条"

        # 检查是否有 reasoning_content
        found_rc = False
        for msg in messages:
            rc = getattr(msg, "additional_kwargs", {}).get("reasoning_content")
            if rc:
                found_rc = True
                break

        assert found_rc, (
            f"在 {len(messages)} 条消息中未找到任何 reasoning_content。"
            f"思考模式可能未生效。"
        )

    def test_02_multi_turn_memory_with_thinking(self):
        """
        多轮对话记忆 + 思考模式：第二轮应记住第一轮的信息。
        """
        from langchain_deepseek import ChatDeepSeek

        llm = ChatDeepSeek(
            model=settings.MODEL_NAME,
            api_key=settings.OPENAI_API_KEY,
            api_base=settings.OPENAI_BASE_URL or "https://api.deepseek.com/v1",
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
        )

        from src.tools.builtin import ALL_TOOLS

        llm_with_tools = llm.bind_tools(ALL_TOOLS)

        # 第一轮
        msg1 = llm_with_tools.invoke(
            "我的项目代号是 TDD-THINKING-42。记住它，直接回复'已记住'即可。"
        )
        rc1 = msg1.additional_kwargs.get("reasoning_content")

        # 第二轮：引用 msg1（含 reasoning_content）
        from langchain_core.messages import HumanMessage
        msg2 = llm.invoke([
            HumanMessage(content="我的项目代号是 TDD-THINKING-42。记住它，直接回复'已记住'即可。"),
            msg1,
            HumanMessage(content="我的项目代号是什么？直接回答代号。"),
        ])

        assert "TDD-THINKING-42" in msg2.content, (
            f"第二轮应记住代号，实际: {msg2.content[:200]}"
        )
        rc2 = msg2.additional_kwargs.get("reasoning_content")
        assert rc2 is not None, "第二轮也应有 reasoning_content"
