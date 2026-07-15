"""
消息序列化辅助模块 —— 将 LangChain 消息对象转换为 JSON-safe 的纯 dict。

供两个场景共享使用：
1. FastAPI SSE 流式输出（main.py 的 _serialize_event 内部调用）
2. 终端测试的对话导出（test_demo.py / conftest.py / 独立导出脚本）

提取为共享模块的原因：
- main.py 的 _msg_to_dict 是私有函数，终端测试无法复用同一套序列化逻辑
- 浏览器导出和终端导出使用同一套 format，保证格式一致性
- 避免"终端测试生成的 JSON 格式与浏览器不同"导致的对比困难
"""

import json


def msg_to_dict(msg) -> dict:
    """
    将任意 LangChain 消息对象转为 JSON-safe 的 dict。

    json.dumps 的 default=str 会把 AIMessage 转成类似
    "content='你好' additional_kwargs={} ..." 的字符串，
    前端无法从中提取 type/content/tool_calls 字段。
    这个函数手动提取关键字段，确保前端/导出拿到结构化数据。

    Args:
        msg: LangChain 消息对象（HumanMessage / AIMessage / ToolMessage / SystemMessage）

    Returns:
        包含 type、content 的纯 dict；AIMessage 额外含 tool_calls；
        ToolMessage 额外含 name
    """
    d = {"type": getattr(msg, "type", "unknown")}

    # 文本内容 —— 处理 content blocks 列表（Anthropic/某些模型返回格式）
    content = getattr(msg, "content", "")
    if isinstance(content, list):
        d["content"] = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    else:
        d["content"] = str(content) if content else ""

    # 工具调用（AIMessage 上）
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        d["tool_calls"] = [
            {
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            }
            for tc in tool_calls
        ]

    # 推理内容（DeepSeek V4 思考模式下的 reasoning_content）
    # 存储在 AIMessage.additional_kwargs 中，
    # 对排查工具选择原因和 Debug 思考链很有价值。
    additional_kwargs = getattr(msg, "additional_kwargs", None)
    if additional_kwargs and "reasoning_content" in additional_kwargs:
        d["reasoning_content"] = additional_kwargs["reasoning_content"]

    # Token 用量（DeepSeek 在 AIMessage.usage_metadata 中提供了完整的
    # token 计数，含 reasoning token 的实际数量，
    # 比前端用字符数估算准确得多）
    usage_metadata = getattr(msg, "usage_metadata", None)
    if usage_metadata:
        d["usage_metadata"] = dict(usage_metadata) if isinstance(usage_metadata, dict) else {}
        # 兼容 AIMessage 的 usage_metadata 以对象形式返回的情况
        if not isinstance(usage_metadata, dict):
            try:
                d["usage_metadata"] = {
                    "input_tokens": getattr(usage_metadata, "input_tokens", None),
                    "output_tokens": getattr(usage_metadata, "output_tokens", None),
                    "total_tokens": getattr(usage_metadata, "total_tokens", None),
                    "output_token_details": getattr(usage_metadata, "output_token_details", None),
                }
            except Exception:
                d["usage_metadata"] = {}

    # 工具名（ToolMessage 上）
    name = getattr(msg, "name", None)
    if name:
        d["name"] = name

    return d


def clean_any(obj):
    """
    递归清理 dict/list 中的 LangChain 消息对象，转为 JSON-safe 的纯 dict。

    用于处理 _serialize_event 中非标准结构的 payload——
    如果 payload 包含嵌套的 LangChain 消息对象，逐个转换。
    """
    if hasattr(obj, "type") and hasattr(obj, "content"):
        return msg_to_dict(obj)
    if isinstance(obj, dict):
        return {k: clean_any(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_any(v) for v in obj]
    return obj


def serialize_event(event) -> str:
    """
    将 LangGraph astream 产出的 event 转为 JSON 字符串。

    两种 event 格式：
    1. (mode, payload) 元组 — stream_mode 为列表时（如 ['updates','messages']）
       - 'updates' mode: payload = {节点名: {messages: [AIMessage, ...]}}
       - 'messages' mode: payload = (AIMessageChunk, metadata)
    2. 裸 dict — stream_mode 为单字符串时（如 'updates'）
       event = {节点名: {messages: [AIMessage, ...]}}

    Returns:
        JSON 字符串，ensure_ascii=False（中文不转义）
    """
    if isinstance(event, tuple) and len(event) >= 2:
        mode, payload = event[0], event[1]

        if mode == "updates" and isinstance(payload, dict):
            clean_payload = {}
            for node_name, update in payload.items():
                if isinstance(update, dict) and "messages" in update:
                    clean_update = dict(update)
                    clean_update["messages"] = [
                        msg_to_dict(m) for m in update["messages"]
                    ]
                    clean_payload[node_name] = clean_update
                else:
                    clean_payload[node_name] = update
            return json.dumps([mode, clean_payload], ensure_ascii=False)

        elif mode == "messages" and isinstance(payload, tuple) and len(payload) >= 1:
            msg, metadata = payload[0], payload[1] if len(payload) > 1 else {}
            clean_msg = msg_to_dict(msg)
            return json.dumps([mode, [clean_msg, metadata]], ensure_ascii=False)

        else:
            return json.dumps([mode, clean_any(payload)], ensure_ascii=False)

    elif isinstance(event, dict):
        clean = {}
        for node_name, update in event.items():
            if isinstance(update, dict) and "messages" in update:
                clean_update = dict(update)
                clean_update["messages"] = [
                    msg_to_dict(m) for m in update["messages"]
                ]
                clean[node_name] = clean_update
            else:
                clean[node_name] = update
        return json.dumps(clean, ensure_ascii=False)

    else:
        return json.dumps(event, default=str, ensure_ascii=False)


def messages_to_export(messages: list, thread_id: str, version: str = "0.3.0") -> dict:
    """
    将 LangChain 消息列表转为"浏览器导出格式"的 dict，可直接 json.dump 写入文件。

    与 GET /chat/export/{thread_id} 的返回格式完全一致：
    {
        "version": "0.3.0",
        "exported_at": "2026-07-07T...",
        "thread_id": "test-demo",
        "message_count": 5,
        "messages": [{type, content, ...}, ...]
    }

    Args:
        messages: graph.invoke() 返回的 result["messages"] 列表
        thread_id: 线程标识
        version: 项目版本号

    Returns:
        JSON-safe 的 dict

    用法（终端测试中）：
        from src.utils.serialization_ly import messages_to_export
        import json, pathlib

        result = graph.invoke(...)
        export = messages_to_export(result["messages"], thread_id="test-p1-1")
        pathlib.Path("导出/test.json").write_text(
            json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    """
    import datetime

    return {
        "version": version,
        "exported_at": datetime.datetime.now().isoformat(),
        "thread_id": thread_id,
        "message_count": len(messages),
        "messages": [msg_to_dict(m) for m in messages],
    }
