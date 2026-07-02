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

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .agent.graph import graph_persistent  # SqliteSaver：进程重启后保留记忆

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
            async for event in graph_persistent.astream(
                {"messages": [{"role": "user", "content": req.message}]},
                config=config,
                stream_mode=["updates", "messages"],
            ):
                # event 格式：(mode, payload) 元组
                # 转为 JSON 注意：AIMessage 等对象不能直接 json.dumps
                # 用 default=str 兜底
                yield f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"

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

    result = graph_persistent.invoke(
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
