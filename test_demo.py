"""
Agent 功能验证脚本 —— 覆盖本轮所有改动

运行方式：
    cd d:/Github项目/agent项目/agent_langchain_1_ly
    D:/Apps/Python/python.exe test_demo.py

不需要启动 FastAPI 服务，直接调用 graph 验证。
"""

import sys
import asyncio
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

# ── 辅助输出 ──────────────────────────────────────────────────

CHECK = "✔"
CROSS = "✘"
SEP = "─" * 60


def hdr(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def ok(msg: str):
    print(f"  {CHECK}  {msg}")


def fail(msg: str):
    print(f"  {CROSS}  {msg}")


def info(key: str, value: str):
    print(f"  📌 {key}: {value}")


# ═══════════════════════════════════════════════════════════════
# 1. 配置与工具环境
# ═══════════════════════════════════════════════════════════════

hdr("1. 配置检查")

from src.config.settings import settings
from src.tools.builtin import ALL_TOOLS

info("MODEL_NAME", settings.MODEL_NAME)
info("OPENAI_BASE_URL", settings.OPENAI_BASE_URL or "(默认 OpenAI)")
info("DST_SOURCE_DIR", settings.DST_SOURCE_DIR or "(未配置)")
info("SQLITE_DB_PATH", settings.SQLITE_DB_PATH)
info("已注册工具数", str(len(ALL_TOOLS)))
for t in ALL_TOOLS:
    info("  └ 工具", f"{t.name}  —  {t.description.split(chr(10))[0][:60]}")

# ═══════════════════════════════════════════════════════════════
# 2. graph 编译与 checkpointer
# ═══════════════════════════════════════════════════════════════

hdr("2. graph 编译 + checkpointer 工厂")

from src.agent.graph import graph, build_graph
from src.memory.store import create_checkpointer, create_async_checkpointer

# 确认默认 graph 可用
assert "agent" in graph.nodes
ok("全局 graph 编译成功（节点: " + ", ".join(graph.nodes.keys()) + "）")

# 同步版 factory
mem = create_checkpointer("memory")
from langgraph.checkpoint.memory import MemorySaver
assert isinstance(mem, MemorySaver)
ok("MemorySaver 创建正常")

sqlite_cp = create_checkpointer("sqlite")
from langgraph.checkpoint.sqlite import SqliteSaver
assert isinstance(sqlite_cp, SqliteSaver)
ok("SqliteSaver（同步版）创建正常")

# 异步版 —— 需要 asyncio.run()
async def _check_async():
    cp = await create_async_checkpointer()
    return cp

async_cp = asyncio.run(_check_async())
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
assert isinstance(async_cp, AsyncSqliteSaver)
ok("AsyncSqliteSaver 创建正常")

# 可传入 checkpointer
g2 = build_graph(checkpointer=mem)
assert "agent" in g2.nodes
ok("build_graph(checkpointer=...) 可传入外部 checkpointer")

# ═══════════════════════════════════════════════════════════════
# 3. grep 工具（改进 4：业务工具集成）
# ═══════════════════════════════════════════════════════════════

hdr("3. grep 工具 — 在 DST 源码中精确搜索")

from src.tools.grep_ly import grep
from pathlib import Path

# 3a: 搜索已知存在的符号
print(f"\n  >>> grep(pattern='SetDomestication')\n")
result = grep.invoke({"pattern": "SetDomestication"})
print("  " + result.replace("\n", "\n  "))

if "未找到" not in result and "错误" not in result:
    ok("搜索 'SetDomestication' → 命中！domesticatable 组件存在")
else:
    fail("搜索 'SetDomestication' → 未命中或出错（检查 DST_SOURCE_DIR）")

# 3b: 搜索不存在的符号
print(f"\n  >>> grep(pattern='SymbolThatDoesNotExist_XyZ')\n")
result_nf = grep.invoke({"pattern": "SymbolThatDoesNotExist_XyZ"})
print("  " + result_nf.replace("\n", "\n  "))

if "未找到" in result_nf:
    ok("搜索不存在的符号 → 正确返回'未找到'")
else:
    fail("搜索不存在的符号 → 应该返回'未找到'")

# 3c: 搜索 TUNING 常量
print(f"\n  >>> grep(pattern='TUNING.AXE_DAMAGE', max_results=3)\n")
result_t = grep.invoke({"pattern": "TUNING.AXE_DAMAGE", "max_results": 3})
print("  " + result_t.replace("\n", "\n  "))

if "TUNING.AXE_DAMAGE" in result_t:
    ok("搜索 'TUNING.AXE_DAMAGE' → 找到 tuning.lua 中的值")
else:
    info("（结果）", "搜到匹配但可能不是 AXE_DAMAGE 的赋值行，见上")

# ═══════════════════════════════════════════════════════════════
# 4. Agent 调 grep 工具（端到端）
# ═══════════════════════════════════════════════════════════════

hdr("4. Agent 调用 grep 工具 — LLM 自主搜索源码")

print(f"\n  提问：'请帮我查一下 DST 源码中 SetDomestication 函数在哪里定义的'")
print(f"  预期：LLM 理解需求 → 决定调用 grep → 返回搜索结果\n")

result4 = graph.invoke(
    {"messages": [{"role": "user", "content": "请帮我查一下 DST 源码中 SetDomestication 函数在哪里定义的"}]},
    config={"configurable": {"thread_id": "demo-grep"}},
)

# 打印全部消息，展示 LLM → tool → LLM 的完整链路
tool_called = False
for i, msg in enumerate(result4["messages"]):
    role = getattr(msg, "type", "unknown")
    content = str(msg.content)[:200]
    print(f"  [{i}] {role}: {content}")
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"       🔧 调用工具: {tc['name']}({tc.get('args', {})})")
            if tc['name'] == 'grep':
                tool_called = True

if tool_called:
    ok("LLM 正确识别需求，调用了 grep 工具")
else:
    fail("LLM 没有调用 grep（检查 model 是否支持 function calling）")

# ═══════════════════════════════════════════════════════════════
# 5. 多轮对话记忆（MemorySaver 验证）
# ═══════════════════════════════════════════════════════════════

hdr("5. 多轮对话记忆")

config_mem = {"configurable": {"thread_id": "demo-mem"}}

# 第一轮：告诉 Agent 一个事实
name = f"测试员_{datetime.now().strftime('%H%M%S')}"
graph.invoke(
    {"messages": [{"role": "user", "content": f"我的名字叫{name}，请记住"}]},
    config=config_mem,
)
ok(f"第1轮完成 — 已告诉 Agent 名字是 '{name}'")

# 第二轮：问名字
result_mem = graph.invoke(
    {"messages": [{"role": "user", "content": "我叫什么名字？直接回答名字即可"}]},
    config=config_mem,
)
for msg in reversed(result_mem["messages"]):
    if getattr(msg, "type", "") == "ai" and msg.content:
        reply = msg.content
        print(f"  Agent 回答: {reply}")
        if name in reply:
            ok(f"第2轮 — Agent 记住了名字 '{name}'")
        else:
            fail(f"第2轮 — Agent 没记住名字（期望: {name}, 实际: {reply[:80]}）")
        break

# 第三轮：不同 thread_id 看不到之前的内容
result_other = graph.invoke(
    {"messages": [{"role": "user", "content": "我叫什么名字？直接回答"}]},
    config={"configurable": {"thread_id": "demo-mem-other"}},
)
for msg in reversed(result_other["messages"]):
    if getattr(msg, "type", "") == "ai" and msg.content:
        reply = msg.content
        if name not in reply:
            ok(f"第3轮 — 不同 thread_id 看不到 '{name}'（正确隔离）")
        else:
            fail(f"第3轮 — 不同 thread_id 竟然知道 '{name}'（隔离失效）")
        break

# ═══════════════════════════════════════════════════════════════
# 6. 工具调用（get_current_time + calculator）
# ═══════════════════════════════════════════════════════════════

hdr("6. 经典工具调用（get_current_time / calculator）")

# 6a: 问时间
print("\n  >>> 提问：'现在几点了？'\n")
result_tc = graph.invoke(
    {"messages": [{"role": "user", "content": "现在几点了？告诉我完整时间"}]},
    config={"configurable": {"thread_id": "demo-tc"}},
)
for msg in result_tc["messages"]:
    role = getattr(msg, "type", "unknown")
    content = str(msg.content)[:120]
    print(f"  [{role}] {content}")
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"       🔧 {tc['name']}({tc.get('args', {})})")

# 6b: 计算
print(f"\n  {'─'*50}")
print("\n  >>> 提问：'帮我算一下 sqrt(144) + 8*7'\n")
result_calc = graph.invoke(
    {"messages": [{"role": "user", "content": "帮我算一下 sqrt(144) + 8*7"}]},
    config={"configurable": {"thread_id": "demo-calc"}},
)
for msg in result_calc["messages"]:
    role = getattr(msg, "type", "unknown")
    content = str(msg.content)[:120]
    print(f"  [{role}] {content}")
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"       🔧 {tc['name']}({tc.get('args', {})})")

# ═══════════════════════════════════════════════════════════════
# 7. SSE 断连取消机制（演示）
# ═══════════════════════════════════════════════════════════════

hdr("7. SSE 断连取消 — 机制演示")

print("""
  这个功能在 test_demo.py 中无法直接观察（需要模拟 HTTP 断连），
  但你可以用以下手动步骤验证：

  1. 启动服务：
     uvicorn src.main:app --reload

  2. 浏览器打开 http://localhost:8000 ，发一条需要工具调用的消息，
     例如："帮我用 grep 搜索 SetDomestication"

  3. 在回答还没完成时关闭浏览器标签页

  4. 观察启动 uvicorn 的终端：
     - 如果看到 "SSE 断连，已取消 Agent 任务 [thread=default]"
       → 改进生效了，LLM 不会继续消耗 token
     - 如果没有这条日志 → 检查 main.py 的 lifespan 是否加载成功

  原理：graph.astream() 包装为 asyncio.Task，
  客户端断连 → finally 触发 → agent_task.cancel()
""")

info("验证方式", "启动服务后关闭标签页，观察终端日志")

# ═══════════════════════════════════════════════════════════════
# 8. 对话导出 —— 终端测试生成完整的对话历史 JSON
# ═══════════════════════════════════════════════════════════════

hdr("8. 对话导出 — 生成终端测试对话记录 JSON")

import json as _json
from pathlib import Path as _Path
from src.utils.serialization_ly import messages_to_export

# 导出目录
_EXPORT_DIR = _Path(__file__).resolve().parent / "文档" / "测试记录" / "终端对话导出"
_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── 8a: DST 模式完整 ReAct 对话（含工具调用）──
print("\n  >>> DST 模式：'beefalo 的驯化度组件文件叫什么？列出该文件前30行'\n")

_export_config = {"configurable": {"thread_id": "export-dst-demo", "mode": "dst"}}
result_export = graph.invoke(
    {"messages": [{"role": "user", "content": "beefalo 的驯化度组件文件叫什么？列出该文件前30行"}]},
    config=_export_config,
)

# 打印消息摘要
for i, msg in enumerate(result_export["messages"]):
    role = getattr(msg, "type", "unknown")
    content = str(msg.content)[:150]
    print(f"  [{i}] {role}: {content}")
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"       🔧 {tc['name']}({tc.get('args', {})})")

# 导出 JSON
export_data = messages_to_export(result_export["messages"], thread_id="export-dst-demo")
export_path = _EXPORT_DIR / f"dst-demo-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
export_path.write_text(_json.dumps(export_data, ensure_ascii=False, indent=2), encoding="utf-8")
ok(f"DST 模式对话已导出 → {export_path}（{export_data['message_count']} 条消息）")

# ── 8b: 多轮记忆对话导出 ──
# 复用 section 5 的 thread_id "demo-mem"，从 checkpointer 读取完整历史
print(f"\n  >>> 导出多轮记忆对话（thread_id=demo-mem）\n")

# graph.aget_state() 是异步的，这里用同步版 graph.get_state()
state_mem = graph.get_state({"configurable": {"thread_id": "demo-mem"}})
if state_mem and state_mem.values:
    msgs_mem = state_mem.values.get("messages", [])
    export_mem = messages_to_export(msgs_mem, thread_id="demo-mem")
    export_mem_path = _EXPORT_DIR / f"multi-turn-memory-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    export_mem_path.write_text(_json.dumps(export_mem, ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"多轮记忆对话已导出 → {export_mem_path}（{export_mem['message_count']} 条消息）")
else:
    info("多轮记忆", "无 checkpoint 数据（MemorySaver 在脚本中不跨 graph 实例持久化，这是预期行为）")

# ── 8c: 格式对照 —— 终端导出 vs 浏览器导出 ──
print(f"""
  终端导出的 JSON 格式与浏览器 GET /chat/export/{{thread_id}} 完全一致：

  {{
    "version": "0.3.0",
    "exported_at": "2026-07-07T...",
    "thread_id": "export-dst-demo",
    "message_count": {export_data['message_count']},
    "messages": [
      {{"type": "human", "content": "beefalo 的驯化度..."}},
      {{"type": "ai", "content": "", "tool_calls": [{{"name": "grep", "args": {{...}}}}]}},
      {{"type": "tool", "name": "grep", "content": "📂 ..."}},
      {{"type": "ai", "content": "beefalo 的驯化度组件是..."}}
    ]
  }}

  终端测试的优势：
  - 不需要启动 FastAPI 服务
  - 不需要浏览器手动操作
  - 可脚本化批量导出、用于回归对比（如 P1-1 docstring 互斥化前后）
""")

# ═══════════════════════════════════════════════════════════════
# 总结
# ═══════════════════════════════════════════════════════════════

print(f"\n{'█' * 60}")
print(f"  全部 demo 验证完成 — {datetime.now().strftime('%H:%M:%S')}")
print(f"  覆盖：grep工具 / Agent调grep / 多轮记忆 / 工具调用 / SSE断连说明 / 对话导出")
print(f"{'█' * 60}\n")
