"""快速验证：Agent 基本功能是否正常"""
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 确保能 import src 包
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from src.agent.graph import graph

print("=" * 50)
print("测试 1：简单问答（不触发工具）")
print("=" * 50)
result = graph.invoke(
    {"messages": [{"role": "user", "content": "1+1等于几？"}]},
    config={"configurable": {"thread_id": "test-1"}},
)
for msg in result["messages"]:
    role = getattr(msg, "type", "unknown")
    print(f"  [{role}] {msg.content}")
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"    -> 调用工具: {tc['name']}({tc['args']})")

print()
print("=" * 50)
print("测试 2：触发工具调用（问时间）")
print("=" * 50)
result = graph.invoke(
    {"messages": [{"role": "user", "content": "现在几点？"}]},
    config={"configurable": {"thread_id": "test-2"}},
)
for msg in result["messages"]:
    role = getattr(msg, "type", "unknown")
    print(f"  [{role}] {msg.content}")
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"    -> 调用工具: {tc['name']}({tc['args']})")

print()
print("=" * 50)
print("测试 3：多轮对话记忆")
print("=" * 50)
config = {"configurable": {"thread_id": "test-memory"}}
graph.invoke(
    {"messages": [{"role": "user", "content": "我叫小明"}]},
    config=config,
)
result = graph.invoke(
    {"messages": [{"role": "user", "content": "我叫什么名字？"}]},
    config=config,
)
for msg in reversed(result["messages"]):
    if getattr(msg, "type", "") == "ai" and msg.content:
        print(f"  Agent 回答: {msg.content}")
        break

print()
print("=" * 50)
print("测试 4：流式输出（astream + SSE 格式）")
print("=" * 50)
import asyncio

async def stream_test():
    async for event in graph.astream(
        {"messages": [{"role": "user", "content": "算一下 3*7"}]},
        config={"configurable": {"thread_id": "test-stream"}},
        stream_mode="updates",
    ):
        for node_name, update in event.items():
            if "messages" in update:
                last_msg = update["messages"][-1]
                role = getattr(last_msg, "type", "unknown")
                content = str(last_msg.content)[:100]
                print(f"  [stream/{node_name}] {role}: {content}")

asyncio.run(stream_test())

print()
print("=" * 50)
print("全部测试通过")
print("=" * 50)
