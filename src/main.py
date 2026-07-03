"""
FastAPI 入口 — SSE 流式 Agent 服务

这是 2025-2026 年 LangChain Agent 部署的事实标准架构：

    FastAPI (外部接口层) → LangGraph (Agent 编排层) → LLM + Tools (执行层)

关键设计决策：
- 用 SSE (Server-Sent Events) 而非 WebSocket
  理由：更简单、HTTP/2 兼容、单向推送满足 Agent 输出需求
- 用 astream() 逐事件推送，前端可以实时看到 Agent 的思考过程
- 用 thread_id 隔离不同会话（同一个 thread_id 的多次请求共享对话历史）

启动方式（在项目根目录执行）：
    uvicorn src.main:app --reload

测试（另开终端）：
    curl -X POST http://localhost:8000/chat/stream \
      -H "Content-Type: application/json" \
      -d '{"message": "现在几点？"}' \
      --no-buffer
"""

import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

from .agent.graph import graph  # MemorySaver：支持 astream()；需要持久化时换 SqliteSaver + 同步 invoke()


# ============================================================================
# 消息序列化辅助 —— 把 LangChain 消息对象转为前端可解析的纯 dict
# ============================================================================

def _msg_to_dict(msg) -> dict:
    """
    将任意 LangChain 消息对象转为 JSON-safe 的 dict。

    json.dumps 的 default=str 会把 AIMessage 转成类似
    "content='你好' additional_kwargs={} ..." 的字符串，
    前端无法从中提取 type/content/tool_calls 字段。
    这个函数手动提取关键字段，确保前端拿到结构化数据。
    """
    d = {"type": getattr(msg, "type", "unknown")}

    # 文本内容
    content = getattr(msg, "content", "")
    if isinstance(content, list):
        # Anthropic/某些模型返回 content blocks 列表
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

    # 工具名（ToolMessage 上）
    name = getattr(msg, "name", None)
    if name:
        d["name"] = name

    return d


def _serialize_event(event) -> str:
    """
    将 LangGraph astream 产出的 event 转为 JSON 字符串。

    两种 event 格式：
    1. (mode, payload) 元组 — stream_mode 为列表时（如 ['updates','messages']）
       - 'updates' mode: payload = {节点名: {messages: [AIMessage, ...]}}
       - 'messages' mode: payload = (AIMessageChunk, metadata)
    2. 裸 dict — stream_mode 为单字符串时（如 'updates'）
       event = {节点名: {messages: [AIMessage, ...]}}
    """
    # 检测事件格式
    if isinstance(event, tuple) and len(event) >= 2:
        mode, payload = event[0], event[1]

        if mode == "updates" and isinstance(payload, dict):
            # payload 中每个节点更新里的 messages 列表需要转 dict
            clean_payload = {}
            for node_name, update in payload.items():
                if isinstance(update, dict) and "messages" in update:
                    clean_update = dict(update)
                    clean_update["messages"] = [
                        _msg_to_dict(m) for m in update["messages"]
                    ]
                    clean_payload[node_name] = clean_update
                else:
                    clean_payload[node_name] = update
            return json.dumps([mode, clean_payload], ensure_ascii=False)

        elif mode == "messages" and isinstance(payload, tuple) and len(payload) >= 1:
            # payload = (AIMessageChunk, metadata_dict)
            msg, metadata = payload[0], payload[1] if len(payload) > 1 else {}
            clean_msg = _msg_to_dict(msg)
            return json.dumps([mode, [clean_msg, metadata]], ensure_ascii=False)

        else:
            # 其他 tuple 格式 —— 逐个尝试转换
            return json.dumps([mode, _clean_any(payload)], ensure_ascii=False)

    elif isinstance(event, dict):
        # 单 stream_mode 字符串时的裸 dict
        clean = {}
        for node_name, update in event.items():
            if isinstance(update, dict) and "messages" in update:
                clean_update = dict(update)
                clean_update["messages"] = [
                    _msg_to_dict(m) for m in update["messages"]
                ]
                clean[node_name] = clean_update
            else:
                clean[node_name] = update
        return json.dumps(clean, ensure_ascii=False)

    else:
        return json.dumps(event, default=str, ensure_ascii=False)


def _clean_any(obj):
    """递归清理 dict/list 中的 LangChain 消息对象"""
    if hasattr(obj, "type") and hasattr(obj, "content"):
        return _msg_to_dict(obj)
    if isinstance(obj, dict):
        return {k: _clean_any(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_any(v) for v in obj]
    return obj

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent.api")

app = FastAPI(title="LangChain Agent API", version="0.1.0")


# ============================================================================
# 请求/响应模型
# ============================================================================

class ChatRequest(BaseModel):
    """
    聊天请求体。

    thread_id 用于隔离不同会话——同一个前端用户可以开多个对话线程。
    不传则默认 "default"。
    """
    message: str
    thread_id: str = "default"


class HealthResponse(BaseModel):
    status: str
    version: str


# ============================================================================
# 路由
# ============================================================================

# 项目根目录 —— 用于读取静态文件
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@app.get("/", response_class=HTMLResponse)
async def index():
    """聊天 + Debug 界面"""
    html_path = _PROJECT_ROOT / "debug_ui.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查端点"""
    return HealthResponse(status="ok", version="0.1.0")


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    SSE 流式聊天端点。

    SSE 协议简介：
    - 每条消息以 "data: " 开头，以 "\n\n" 结尾
    - 浏览器用 EventSource API 自动解析
    - 通过 HTTP（不是 WebSocket），兼容所有反向代理
    - "data: [DONE]" 表示流结束

    事件类型（由 stream_mode 决定）：
    - "updates" — 节点执行完毕时的状态变更（可以拿到完整消息）
    - "messages" — LLM 逐 token 输出（打字机效果）
    """
    config = {"configurable": {"thread_id": req.thread_id}}

    async def event_generator():
        """
        async 生成器 —— 每次 yield 推送一条 SSE 事件到客户端。

        采用 stream_mode=["updates", "messages"] 组合：
        - "updates"   让前端知道"哪个节点完成了"（用于进度条）
        - "messages"  让前端做逐 token 渲染（打字机效果）
        """
        logger.info(
            "开始流式处理 [thread=%s]: %s",
            req.thread_id,
            req.message[:50] + "..." if len(req.message) > 50 else req.message,
        )

        try:
            async for event in graph.astream(
                {"messages": [{"role": "user", "content": req.message}]},
                config=config,
                stream_mode=["updates", "messages"],
            ):
                # event 格式：(mode, payload) 元组
                # 转为 JSON 注意：AIMessage 等对象不能直接 json.dumps
                # 用 default=str 兜底
                yield f"data: {_serialize_event(event)}\n\n"

        except Exception as exc:
            logger.error("流式处理出错: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"
        logger.info("流式处理完成 [thread=%s]", req.thread_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",       # 禁止浏览器/代理缓存
            "Connection": "keep-alive",        # 保持 TCP 连接
            "X-Accel-Buffering": "no",         # 关键！禁止 nginx 缓冲 SSE 流
        },
    )


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    非流式聊天端点（用于对比调试）。

    返回完整结果，适合 curl 快速测试。
    """
    config = {"configurable": {"thread_id": req.thread_id}}

    result = graph.invoke(
        {"messages": [{"role": "user", "content": req.message}]},
        config=config,
    )

    # 提取最终回答
    final_answer = ""
    for msg in reversed(result["messages"]):
        if getattr(msg, "type", "") == "ai" and msg.content:
            final_answer = msg.content
            break

    return {
        "thread_id": req.thread_id,
        "answer": final_answer,
        "message_count": len(result["messages"]),
    }


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
