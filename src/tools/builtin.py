"""
内置工具集

用 @tool 装饰器定义 Agent 可调用的工具函数。
LangChain v1.0 中，@tool 会自动将函数签名 + docstring 转换为
LLM 可理解的工具描述（function calling schema）。

注意：
- docstring 务必写清参数含义，LLM 靠它决定何时调用此工具
- 参数类型标注必须准确，框架据此生成 JSON Schema
"""

import datetime
from langchain.tools import tool


@tool
def get_current_time() -> str:
    """获取当前的日期和时间。

    只有在用户明确询问"现在几点""今天几号""当前时间"时才调用此工具。
    不要在其他场景下调用——如果不是明确问时间，说明用户需要的是其他工具。
    """
    now = datetime.datetime.now()
    return now.strftime("%Y年%m月%d日 %H:%M:%S（周%w）")


@tool
def calculator(expression: str) -> str:
    """计算数学表达式的值。

    Args:
        expression: 数学表达式字符串，如 "2 + 3 * 4" 或 "(100 - 20) / 8"

    返回值包含计算结果。
    如果表达式语法错误，会返回错误信息。
    """
    try:
        # 注意：eval 在生产环境不安全，这里只作为学习演示
        # 生产环境应使用受限的执行环境或专门的数学库
        result = eval(expression, {"__builtins__": {}}, {})
        return f"计算结果：{expression} = {result}"
    except Exception as e:
        return f"计算出错：{e}。请检查表达式语法，确保只包含数字和 + - * / ** // % ( ) 运算符。"


# 所有工具的列表 —— graph.py 中用来绑定到 LLM
from .grep_ly import grep

ALL_TOOLS = [get_current_time, calculator, grep]

# DST 模式的工具集 —— 去掉 get_current_time。
# DeepSeek-chat 的 function calling 路由能力有限，即使工具描述明确写了
# "不要在其他场景下调用"，仍偶尔会误调 get_current_time 来响应源码搜索请求。
# 从工具列表中直接移除是最可靠的解法——模型看不到这个工具，就不可能误调。
# 这也与 Claude Code 的设计一致：模式控制工具的可见性。
DST_TOOLS = [calculator, grep]

# Plan 模式的工具集 —— 当前为占位（项目尚无文件编辑工具）。
# 未来如果有修改文件/执行命令的工具，Plan 模式会从 ALL_TOOLS 中去掉这些，
# 实现"只读探索"。
PLAN_TOOLS = ALL_TOOLS
