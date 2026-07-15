"""
思考模式三轮对比测试 — 命令行驱动版

用法：
    python test_thinking_comparison.py "Round 1: ChatOpenAI 基线"  r1-baseline
    python test_thinking_comparison.py "Round 2: ChatDeepSeek"     r2-chatdeepseek
    python test_thinking_comparison.py "Round 3: 思考模式"         r3-thinking

每轮用相同的 4 条 DST 问题，导出对话 JSON 到 文档/测试记录/思考模式三轮对比/
"""

import sys
import json as _json
from datetime import datetime
from pathlib import Path as _Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(_Path(__file__).resolve().parent))

from src.config.settings import settings
from src.utils.serialization_ly import messages_to_export

# ═══════════════════════════════════════════════════════════════
# 固定测试问题
# ═══════════════════════════════════════════════════════════════

QUESTIONS = [
    {
        "id": "Q1-simple-grep",
        "mode": "dst",
        "content": "DST 源码中 beefalo 的驯化度组件文件叫什么？",
    },
    {
        "id": "Q2-grep-then-read",
        "mode": "dst",
        "content": "查一下 DST 源码中 SetDomesticationTrigger 函数在哪个文件哪一行，然后读它周围10行代码",
    },
    {
        "id": "Q3-ambiguous-grep",
        "mode": "dst",
        "content": "斧子的伤害值是多少？帮我从源码中查",
    },
    {
        "id": "Q4-calc-mixed",
        "mode": "dst",
        "content": "如果 TUNING.AXE_DAMAGE 的值翻倍是多少？先查源码再算",
    },
]

_EXPORT_DIR = _Path(__file__).resolve().parent / "文档" / "测试记录" / "思考模式三轮对比"
_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

CHECK = "✔"
CROSS = "✘"


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


def run_round(round_label: str, export_prefix: str):
    """加载当前 graph 实例，跑全部问题，导出 JSON。"""
    import importlib
    import src.agent.graph as graph_mod
    importlib.reload(graph_mod)
    graph = graph_mod.graph

    # 探测当前 graph 使用的是什么模型类
    from langchain_openai import ChatOpenAI
    from langchain_deepseek import ChatDeepSeek

    hdr(round_label)

    info("MODEL_NAME", settings.MODEL_NAME)
    info("API", settings.OPENAI_BASE_URL)

    results = {}
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for q in QUESTIONS:
        qid = q["id"]
        thread_id = f"cmp-{export_prefix}-{qid}"
        config = {"configurable": {"thread_id": thread_id, "mode": q["mode"]}}

        print(f"\n  >>> {qid}: {q['content']}\n")

        result = graph.invoke(
            {"messages": [{"role": "user", "content": q["content"]}]},
            config=config,
        )

        messages = result["messages"]

        # 打印消息摘要
        tool_sequence = []
        has_reasoning = False
        for i, msg in enumerate(messages):
            role = getattr(msg, "type", "unknown")
            content = str(msg.content)[:120]
            print(f"  [{i}] {role}: {content}")
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tname = tc["name"]
                    targs = str(tc.get("args", {}))[:100]
                    print(f"       🔧 {tname}({targs})")
                    tool_sequence.append(tname)
            rc = getattr(msg, "additional_kwargs", {}).get("reasoning_content")
            if rc:
                has_reasoning = True
                print(f"       🧠 reasoning: {str(rc)[:150]}...")

        info("工具序列", " → ".join(tool_sequence) if tool_sequence else "(无工具)")
        info("含reasoning", "是" if has_reasoning else "否")

        # 导出 JSON
        export_data = messages_to_export(messages, thread_id=thread_id)
        # 在导出中加一个标记，表明这是哪一轮的
        export_data["_round"] = export_prefix
        fname = f"{export_prefix}_{qid}_{timestamp}.json"
        export_path = _EXPORT_DIR / fname
        export_path.write_text(
            _json.dumps(export_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        ok(f"已导出 → {export_path.name}（{export_data['message_count']} 条消息）")

        results[qid] = {
            "tool_sequence": tool_sequence,
            "has_reasoning": has_reasoning,
            "message_count": len(messages),
        }

    return results


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python test_thinking_comparison.py <轮次描述> <导出前缀>")
        print("示例: python test_thinking_comparison.py 'Round 1: ChatOpenAI' r1-baseline")
        sys.exit(1)

    round_label = sys.argv[1]
    export_prefix = sys.argv[2]

    print(f"\n{'█' * 60}")
    print(f"  MODEL_NAME: {settings.MODEL_NAME}")
    print(f"  导出前缀: {export_prefix}")
    print(f"  导出目录: {_EXPORT_DIR}")
    print(f"{'█' * 60}")

    run_round(round_label, export_prefix)
