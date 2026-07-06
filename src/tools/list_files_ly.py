"""
list_files 工具 —— 列出指定目录下的文件和子目录

让 Agent 在搜索之前就能了解源码目录结构。
例如：组件放在 components/ 还是 scripts/？有哪些子目录？

与 grep 的分工：
- list_files：浏览目录结构，知道"去哪搜"
- grep：精确搜索文件内容，知道"在哪行"
"""

import logging
from typing import Annotated
from pathlib import Path

from langchain_core.tools import tool, InjectedToolArg

from ..config.settings import settings

logger = logging.getLogger("agent.tools.list_files")

# 最多返回的条目数
_MAX_ENTRIES = 200


def _resolve_dir(directory: str, source_dir: str = "") -> Path:
    """
    解析目录路径：绝对路径直接用，相对路径拼到 source_dir 下。

    Args:
        directory: 目录路径
        source_dir: 源码根目录。为空时从 settings.DST_SOURCE_DIR 读取。
    """
    p = Path(directory) if directory else Path(".")
    if p.is_absolute():
        return p
    base = source_dir or settings.DST_SOURCE_DIR
    if not base:
        raise FileNotFoundError(
            "未配置 DST 源码目录，无法解析相对路径。"
            "请在 .env 中设置 DST_SOURCE_DIR，或提供绝对路径。"
        )
    return Path(base) / p


def _is_hidden(name: str) -> bool:
    """判断是否为应跳过的隐藏/无关目录。"""
    return name.startswith(".") or name == "__pycache__"


@tool
def list_files(
    directory: str = "",
    source_dir: Annotated[str, InjectedToolArg] = "",  # 运行时注入，不出现在 LLM 的 tool schema 中
) -> str:
    """
    列出指定目录下的文件和子目录（不递归）。

    在搜索源码之前，建议先用本工具了解目录结构。
    例如用户问"components 下有哪些文件"时，用本工具比用 grep 更快更直接。

    使用场景：
    - 用户问"xx 目录下有什么"
    - grep 搜不到时，需要了解目录结构以调整搜索路径
    - 不确定某个组件放在哪个目录

    Args:
        directory: 要列出的目录路径。空字符串表示源码根目录。
                   可以是相对路径（相对于 DST 源码目录）或绝对路径。
                   例如："" → 根目录，"components" → components 子目录。
    """
    logger.info("list_files: directory=%r", directory)

    # 解析路径（source_dir 如未注入则为空字符串，内部 fallback 到 settings）
    try:
        dir_path = _resolve_dir(directory, source_dir or "")
    except FileNotFoundError as e:
        return str(e)

    # 检查目录是否存在
    if not dir_path.exists():
        return f"错误：目录不存在 → {dir_path}"
    if not dir_path.is_dir():
        return f"错误：路径不是目录 → {dir_path}"

    # 收集条目
    try:
        entries = list(dir_path.iterdir())
    except PermissionError:
        return f"错误：没有读取权限 → {dir_path}"
    except Exception as e:
        return f"错误：读取目录失败 → {dir_path}（{type(e).__name__}: {e}）"

    if not entries:
        return f"（空目录）{dir_path}"

    # 分类：目录在前、文件在后，各自按字母排序
    dirs = sorted(
        [e for e in entries if e.is_dir() and not _is_hidden(e.name)],
        key=lambda x: x.name.lower(),
    )
    files = sorted(
        [e for e in entries if e.is_file() and not _is_hidden(e.name)],
        key=lambda x: x.name.lower(),
    )

    total = len(dirs) + len(files)
    out_lines = [f"📁 {dir_path}（{total} 个条目）", ""]

    count = 0
    truncated = False

    for d in dirs:
        count += 1
        if count > _MAX_ENTRIES:
            truncated = True
            break
        out_lines.append(f"  📁 {d.name}/")

    for f in files:
        count += 1
        if count > _MAX_ENTRIES:
            truncated = True
            break
        size = f.stat().st_size
        out_lines.append(f"  📄 {f.name}  ({_format_size(size)})")

    if truncated:
        out_lines.append(f"  …（共 {total} 个条目，已截断显示前 {_MAX_ENTRIES} 条。请指定子目录缩小范围）")

    return "\n".join(out_lines)


def _format_size(size_bytes: int) -> str:
    """格式化文件大小为可读形式。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
