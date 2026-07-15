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

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import datetime
import uuid as _uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

# 导入 graph 模块（而非 graph 变量）——
# lifespan 启动时会用 AsyncSqliteSaver 替换 graph_mod.graph，
# 通过模块属性访问确保始终拿到最新实例。
from .agent import graph as graph_mod


# ============================================================================
# 消息序列化辅助 —— 已提取到 src/utils/serialization_ly.py 共享模块
# 终端测试（test_demo.py / pytest）和 FastAPI 共用同一套序列化逻辑，
# 确保浏览器导出和终端导出的 JSON 格式一致。
# ============================================================================

from .utils.serialization_ly import (
    msg_to_dict as _msg_to_dict,
    serialize_event as _serialize_event,
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent.api")


# ============================================================================
# FastAPI 生命周期：启动时用 AsyncSqliteSaver 替换 MemorySaver
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。

    启动时：创建 AsyncSqliteSaver，重新编译 graph，
           使对话历史持久化到 SQLite 磁盘文件。
    关闭时：（AsyncSqliteSaver 的连接由 aiosqlite 自动管理）

    为什么在 lifespan 中做而非模块级 import 时做：
    - aiosqlite.connect() 是 async 调用，不能在同步上下文中执行
    - FastAPI lifespan 是官方推荐的异步初始化入口
    """
    from .memory.store import create_async_checkpointer
    from .agent.graph import init_graph

    checkpointer = await create_async_checkpointer()
    init_graph(checkpointer=checkpointer)
    logger.info("AsyncSqliteSaver 初始化完成，对话历史将持久化到磁盘")
    yield
    logger.info("Agent 服务关闭")


app = FastAPI(title="LangChain Agent API", version="0.1.0", lifespan=lifespan)


# ============================================================================
# 请求/响应模型
# ============================================================================

class ChatRequest(BaseModel):
    """
    聊天请求体。

    thread_id 用于隔离不同会话——同一个前端用户可以开多个对话线程。
    不传则默认 "default"。

    mode 控制 Agent 的行为模式：
    - "general"（默认）：通用开发者助手
    - "dst"：DST（饥荒联机版）Mod 开发助手
    - "plan"：规划模式（占位，当前仅影响回答风格）
    """
    message: str
    thread_id: str = "default"
    mode: str = "general"


class HealthResponse(BaseModel):
    status: str
    version: str


# ============================================================================
# 辅助：读取对话历史
# ============================================================================

async def _load_history(thread_id: str):
    """
    读取指定线程的对话历史。

    LangGraph 的 checkpointer 在每个 superstep 后自动保存 State。
    graph.aget_state() 返回最新的 checkpoint 快照，无需 invoke。
    """
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state = await graph_mod.graph.aget_state(config)
        if state is None or not state.values:
            return []
        msgs = state.values.get("messages", [])
        return [_msg_to_dict(m) for m in msgs]
    except Exception as exc:
        logger.warning("读取历史失败 [thread=%s]: %s", thread_id, exc)
        return []


@app.get("/chat/history/{thread_id}")
async def chat_history(thread_id: str):
    """读取指定对话线程的历史消息（页面刷新/切换线程时调用）"""
    history = await _load_history(thread_id)
    return {"thread_id": thread_id, "message_count": len(history), "messages": history}


# ============================================================================
# 对话导出/导入
# ============================================================================

# 导出请求仅需 thread_id（由前端从 localStorage 取线程名一并打包）
# 导入请求体定义见下方 endpoint

@app.get("/chat/export/{thread_id}")
async def export_thread(thread_id: str):
    """
    导出指定对话线程为 JSON 文件。

    返回格式包含元数据（版本、导出时间、thread_id、线程名）和消息列表，
    可用于备份、跨设备迁移、问题复现等场景。
    前端将线程名称通过 query 参数传入（因为线程名只存在 localStorage 中）。
    """
    history = await _load_history(thread_id)
    return {
        "version": "0.3.0",
        "exported_at": datetime.datetime.now().isoformat(),
        "thread_id": thread_id,
        "message_count": len(history),
        "messages": history,
    }


class ImportRequest(BaseModel):
    """导入对话线程的请求体"""
    thread_name: str = "导入的对话"
    messages: list[dict]


@app.post("/chat/import")
async def import_thread(req: ImportRequest):
    """
    导入一个对话线程。

    将导出的消息列表写入新的 checkpoint 线程，返回新的 thread_id。
    前端收到后创建对应的 localStorage 条目并切换到此线程。

    消息还原：将 JSON dict 转回 LangChain 原生消息对象，
    然后通过 graph.aupdate_state() 写入 checkpointer。
    """
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    rebuilt = []
    for m in req.messages:
        mtype = m.get("type", "")
        content = m.get("content", "")

        if mtype == "human":
            rebuilt.append(HumanMessage(content=content))
        elif mtype == "ai":
            tool_calls = m.get("tool_calls")
            reasoning = m.get("reasoning_content")
            # 导入时需保留 reasoning_content —— 它在 additional_kwargs 中，
            # 否则后续工具调用回合会丢失思考链，前端也无法展示思考过程。
            additional_kwargs = {}
            if reasoning:
                additional_kwargs["reasoning_content"] = reasoning
            msg = AIMessage(content=content, additional_kwargs=additional_kwargs)
            if tool_calls:
                # tool_calls 在 dict 中不带 id，还原时需要重新分配以便 ToolMessage 关联
                normalized = []
                for tc in tool_calls:
                    tc_id = str(_uuid.uuid4())[:8]
                    normalized.append({
                        "id": tc_id,
                        "name": tc.get("name", ""),
                        "args": tc.get("args", {}),
                    })
                msg.tool_calls = normalized
            rebuilt.append(msg)
        elif mtype == "tool":
            name = m.get("name", "unknown_tool")
            # ToolMessage 需要 tool_call_id 来关联到对应的 AIMessage.tool_calls
            # 导入时 id 可能丢失（旧版导出格式不保存 id），使用占位 id
            msg = ToolMessage(content=content, name=name, tool_call_id="imported")
            rebuilt.append(msg)
        else:
            # 未知类型，跳过（避免污染 checkpoint）
            logger.warning("导入时跳过未知消息类型: %s", mtype)

    if not rebuilt:
        raise HTTPException(status_code=400, detail="没有可导入的有效消息")

    # 写入 checkpointer：用新 thread_id 将消息写入空的 checkpoint
    new_thread_id = "import-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(_uuid.uuid4())[:8]
    config = {"configurable": {"thread_id": new_thread_id}}

    try:
        await graph_mod.graph.aupdate_state(config, {"messages": rebuilt})
        logger.info("导入成功: thread=%s, %d 条消息", new_thread_id, len(rebuilt))
    except Exception as exc:
        logger.error("导入失败: %s", exc)
        raise HTTPException(status_code=500, detail=f"写入 checkpoint 失败: {exc}")

    return {
        "thread_id": new_thread_id,
        "thread_name": req.thread_name,
        "message_count": len(rebuilt),
    }


# ============================================================================
# 路由
# ============================================================================

# 项目根目录 —— 用于读取静态文件
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@app.get("/", response_class=HTMLResponse)
async def index():
    """聊天 + Debug 界面"""
    html_path = _PROJECT_ROOT / "debug_ui.html"
    return HTMLResponse(
        html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


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
    config = {"configurable": {"thread_id": req.thread_id, "mode": req.mode}}
    logger.info("[/chat/stream] mode=%s thread=%s", req.mode, req.thread_id)

    async def event_generator():
        """
        async 生成器 —— 每次 yield 推送一条 SSE 事件到客户端。

        采用 stream_mode=["updates", "messages"] 组合：
        - "updates"   让前端知道"哪个节点完成了"（用于进度条）
        - "messages"  让前端做逐 token 渲染（打字机效果）

        Debug 改进（2026-07-04）：graph.astream() 包装为 asyncio.Task。
        当客户端断连（关闭标签页）时，finally 块会 cancel 掉任务，
        避免后端继续调用 LLM 白白消耗 token。
        参考：SuperMew 项目的 agent_task.cancel() 模式。
        """
        logger.info(
            "开始流式处理 [thread=%s]: %s",
            req.thread_id,
            req.message[:50] + "..." if len(req.message) > 50 else req.message,
        )

        # asyncio.Queue 作为后台 Agent 任务与 SSE 生成器之间的桥梁
        q: asyncio.Queue = asyncio.Queue()

        async def _run_agent():
            """后台任务：运行 graph.astream()，将事件逐个推入队列"""
            try:
                async for event in graph_mod.graph.astream(
                    {"messages": [{"role": "user", "content": req.message}]},
                    config=config,
                    stream_mode=["updates", "messages"],
                ):
                    await q.put(("event", event))
                await q.put(("done", None))
            except asyncio.CancelledError:
                logger.info("Agent 任务被取消 [thread=%s]", req.thread_id)
                # 不 raise —— 被取消是预期行为，静默处理
            except Exception as exc:
                await q.put(("error", exc))

        # 将 Agent 推理包装为 Task，以便在客户端断连时能 cancel
        agent_task = asyncio.create_task(_run_agent())

        try:
            while True:
                kind, value = await q.get()
                if kind == "done":
                    break
                elif kind == "error":
                    logger.error("流式处理出错: %s", value)
                    yield f"data: {json.dumps({'error': str(value)}, ensure_ascii=False)}\n\n"
                    break
                else:
                    # value 是 graph.astream() 产出的 (mode, payload) 元组
                    yield f"data: {_serialize_event(value)}\n\n"

        finally:
            # 关键：客户端断连 → GeneratorExit → finally 触发 → cancel 后台任务
            if not agent_task.done():
                agent_task.cancel()
                logger.info("SSE 断连，已取消 Agent 任务 [thread=%s]", req.thread_id)

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

    注意：lifespan 已将 graph 升级为 AsyncSqliteSaver，必须用 ainvoke()
    而非 invoke()，否则同步调用异步 checkpointer 会 500 报错。
    """
    config = {"configurable": {"thread_id": req.thread_id, "mode": req.mode}}
    logger.info("[/chat] mode=%s thread=%s", req.mode, req.thread_id)

    result = await graph_mod.graph.ainvoke(
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
