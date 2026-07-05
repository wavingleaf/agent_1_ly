"""
grep 工具 —— 在 DST 源码中做精确字符串搜索

这是"控制台指令辅助编写"功能的核心工具。LLM 推理出候选搜索词后，
通过本工具在本地 DST 源码中验证这些符号是否真的存在。

与 RAG 向量检索的区别：
- grep 是确定性匹配 —— 搜 SetDomestication 就一定只返回包含这个字符串的行
- RAG 是概率性匹配 —— 可能漏掉精确的函数名定义
- grep 不依赖预建索引，直接读文件系统

工具签名设计原则：
- pattern 是唯一必填参数（Agent 从需求中推理出的搜索词）
- context_lines 默认 2 —— 足够看到方法签名和相邻字段
- max_results 默认 30 —— 防止单次搜索淹没 LLM 上下文窗口
"""

import os
import re
import fnmatch
import logging
from pathlib import Path
from langchain_core.tools import tool

from ..config.settings import settings

logger = logging.getLogger("agent.tools.grep")

# 只搜索 Lua 源码文件
_LUA_GLOB = "*.lua"


def _collect_lua_files(root: Path) -> list[Path]:
    """
    递归收集指定目录下的所有 .lua 文件。
    跳过 .git、__pycache__ 等无关目录。
    """
    if not root.is_dir():
        return []

    lua_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过无关目录（原地修改 dirnames 可阻止 os.walk 进入）
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for f in filenames:
            if fnmatch.fnmatch(f, _LUA_GLOB):
                lua_files.append(Path(dirpath) / f)

    return lua_files


def _search_file(filepath: Path, pattern: str, context_lines: int) -> list[dict]:
    """
    在单个文件中搜索模式串，返回匹配行及其上下文。

    Args:
        filepath: Lua 源文件路径
        pattern: 搜索的字符串（子串匹配，非正则）
        context_lines: 匹配行前后各取几行作为上下文

    Returns:
        [{"line": 行号, "content": 匹配行内容, "context": [(行号, 内容), ...]}, ...]
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []

    matches = []
    for i, line in enumerate(lines):
        if pattern in line:
            line_num = i + 1  # 转为人读的 1-based 行号
            ctx_start = max(0, i - context_lines)
            ctx_end = min(len(lines), i + context_lines + 1)
            context = [
                (j + 1, lines[j].rstrip("\n"))
                for j in range(ctx_start, ctx_end)
            ]
            matches.append({
                "line": line_num,
                "content": line.rstrip("\n"),
                "context": context,
            })

    return matches


@tool
def grep(pattern: str, context_lines: int = 2, max_results: int = 30) -> str:
    """
    在源码目录中搜索指定的字符串，返回匹配行及上下文。

    搜索范围：DST_SOURCE_DIR（.env 中配置）指向的目录，递归搜索所有源码文件。

    当用户要求以下操作时，必须优先使用本工具：
    - 查找某函数/组件/常量/命令的定义位置
    - 搜索源码中是否包含某个符号或关键词
    - 查看某段代码的实现

    用户提到"查/搜/找/看看/在哪/定义/源码/代码/函数/组件/命令/API"等词时，
    优先使用本工具而非其他工具。不要调用 get_current_time 来响应源码搜索请求。

    Args:
        pattern: 要搜索的字符串（子串匹配，大小写敏感）。
        context_lines: 每个匹配行前后显示几行上下文（默认 2）。
        max_results: 最多返回几条匹配结果（默认 30）。
    """
    if not settings.DST_SOURCE_DIR:
        return (
            "错误：未配置 DST 源码目录。\n"
            "请在 .env 中设置 DST_SOURCE_DIR 指向 DST scripts.zip 解压后的目录。\n"
            "例如：DST_SOURCE_DIR=D:/Games/DST/scripts"
        )

    root = Path(settings.DST_SOURCE_DIR)
    if not root.is_dir():
        return (
            f"错误：DST 源码目录不存在或不可访问：{settings.DST_SOURCE_DIR}\n"
            "请检查 .env 中的 DST_SOURCE_DIR 配置是否正确。"
        )

    logger.info("grep 搜索: pattern=%r, root=%s", pattern, root)

    lua_files = _collect_lua_files(root)
    if not lua_files:
        return f"错误：在 {root} 下未找到任何 .lua 文件。"

    results = []
    for fp in lua_files:
        matches = _search_file(fp, pattern, context_lines)
        for m in matches:
            rel_path = fp.relative_to(root)
            results.append((rel_path, m))
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return f"未找到包含 '{pattern}' 的文件（在 {len(lua_files)} 个 Lua 文件中搜索）。"

    # 格式化输出
    out_lines = [
        f"在 {len(lua_files)} 个 Lua 文件中搜索 '{pattern}'，"
        f"找到 {len(results)} 条匹配"
        + (f"（已达上限 {max_results} 条）" if len(results) >= max_results else "")
        + "：\n",
    ]

    for rel_path, m in results:
        out_lines.append(f"━━━ {rel_path}:{m['line']} ━━━")
        for ctx_line_num, ctx_line in m["context"]:
            marker = "▶" if ctx_line_num == m["line"] else " "
            out_lines.append(f"  {marker} {ctx_line_num:5d} | {ctx_line}")
        out_lines.append("")

    return "\n".join(out_lines)
