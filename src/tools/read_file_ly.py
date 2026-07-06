"""
read_file 工具 —— 读取指定文件的完整内容（支持行范围截断）

这是 grep 的最佳搭档工具：
- grep 找位置（返回文件路径 + 行号 + 2 行上下文）
- read_file 读内容（打开该文件，阅读完整函数体）

与 grep 的分工明确：
- grep：定位 —— 在 4000+ 个 Lua 文件中找到"SetDomestication 在哪"
- read_file：阅读 —— 打开具体文件，读取方法签名、逻辑、调用方式

工具签名设计原则：
- file_path 是唯一必填参数（Agent 从 grep 结果中获取路径）
- start_line / end_line 支持截断读取，避免大文件撑爆上下文窗口
- 默认不截断时，大文件自动只返回前 500 行 + 提示
"""

import logging
from typing import Annotated
from pathlib import Path

from langchain_core.tools import tool, InjectedToolArg

from ..config.settings import settings

logger = logging.getLogger("agent.tools.read_file")

# 超过此行数的文件，若不指定行范围则只返回前 N 行
_LARGE_FILE_THRESHOLD = 2000
_LARGE_FILE_TRUNCATE = 500


def _resolve_path(file_path: str, source_dir: str = "") -> Path:
    """
    解析文件路径：绝对路径直接用，相对路径拼到 source_dir 下。

    Args:
        file_path: 要解析的文件路径
        source_dir: 源码根目录。为空时从 settings.DST_SOURCE_DIR 读取。

    Raises:
        FileNotFoundError: 未配置源码目录且给了相对路径
    """
    p = Path(file_path)
    if p.is_absolute():
        return p
    base = source_dir or settings.DST_SOURCE_DIR
    if not base:
        raise FileNotFoundError(
            "未配置 DST 源码目录，无法解析相对路径。"
            "请在 .env 中设置 DST_SOURCE_DIR，或提供绝对路径。"
        )
    return Path(base) / file_path


@tool
def read_file(
    file_path: str,
    start_line: int = 1,
    end_line: int = 0,
    source_dir: Annotated[str, InjectedToolArg] = "",  # 运行时注入，不出现在 LLM 的 tool schema 中
) -> str:
    """
    读取指定文件的内容，支持按行号范围截断。

    通常在 grep 搜索到匹配位置后，用本工具打开具体文件阅读完整函数体。
    grep 告诉你"在哪"，read_file 告诉你"是什么"。

    使用场景：
    - grep 返回了某文件中的匹配行，需要查看该行所在的完整函数
    - 用户要求"打开 xxx 文件看看"
    - 需要确认某个函数的签名和调用方式

    注意：本工具只读不写，不会修改任何文件。

    Args:
        file_path: 文件路径。可以是相对于 DST 源码目录的路径（如 "components/domesticatable.lua"），
                   也可以是绝对路径。grep 返回的路径可直接传入。
        start_line: 开始读取的行号（1-based，默认从第 1 行开始）。
        end_line: 结束读取的行号（1-based，默认 0 表示读到文件末尾）。
                  例如 start_line=10, end_line=50 读取第 10~50 行。
    """
    logger.info("read_file: %s [%d:%d]", file_path, start_line, end_line)

    # 解析路径（source_dir 如未注入则为空字符串，内部 fallback 到 settings）
    try:
        full_path = _resolve_path(file_path, source_dir or "")
    except FileNotFoundError as e:
        return str(e)

    # 检查文件是否存在
    if not full_path.exists():
        return f"错误：文件不存在 → {full_path}"
    if not full_path.is_file():
        return f"错误：路径不是文件 → {full_path}"

    # 读取文件
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except PermissionError:
        return f"错误：没有读取权限 → {full_path}"
    except Exception as e:
        return f"错误：读取文件失败 → {full_path}（{type(e).__name__}: {e}）"

    total_lines = len(lines)
    if total_lines == 0:
        return f"（空文件）{full_path}"

    # 处理行范围
    use_truncate = False
    if end_line == 0:
        end_line = total_lines
    if start_line < 1:
        start_line = 1
    if end_line > total_lines:
        end_line = total_lines

    # 大文件保护：未主动指定行范围时，只返回前 N 行
    if total_lines > _LARGE_FILE_THRESHOLD and start_line == 1 and end_line == total_lines:
        end_line = _LARGE_FILE_TRUNCATE
        use_truncate = True

    # 格式化为带行号的输出
    out_lines = [
        f"📄 {full_path}（共 {total_lines} 行）",
        f"   显示第 {start_line}～{end_line} 行：",
        "",
    ]
    # 行号宽度：按最大行号计算，最少 4 位
    num_width = max(4, len(str(end_line)))
    for i in range(start_line - 1, end_line):
        line_num = i + 1
        out_lines.append(f"  {line_num:>{num_width}} | {lines[i].rstrip()}")

    out_lines.append("")

    if use_truncate:
        out_lines.append(
            f"(文件共 {total_lines} 行，较大。"
            f"当前仅显示前 {_LARGE_FILE_TRUNCATE} 行。"
            f"如需查看后续内容，请指定 start_line 和 end_line。)"
        )

    return "\n".join(out_lines)
