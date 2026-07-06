"""
web_search 工具 —— 联网搜索 DST Wiki、Klei 论坛、Mod 社区等公开资源

使用 DuckDuckGo 即时搜索作为后端，免费无需 API key。
搜索结果的定位是"辅助"而非"裁决"——LLM 用它发现候选关键词，
最终验证靠 grep/read_file 在本地源码中确认。

与 grep 的角色分工：
- web_search：联网查找 DST API 文档、Wiki 讨论、社区帖子 → 提供候选方向
- grep：精确搜索本地源码中的函数定义、方法签名 → 提供地面真相

备选后端（已调研）：
- Brave Search：需免费注册 API key，搜索质量更好
- SearXNG：需自托管 Docker 实例，隐私最大化

网络支持：
- 通过 DDG_PROXY 环境变量配置代理（如 Clash: socks5h://127.0.0.1:7890）
- 支持指数退避重试（最多 3 次），应对间歇性网络波动
"""

import logging
import time

from langchain_core.tools import tool

from ..config.settings import settings

logger = logging.getLogger("agent.tools.web_search")

# 默认返回结果数
_DEFAULT_MAX_RESULTS = 5
# 最大允许的结果数（防止 LLM 传超大值）
_MAX_ALLOWED = 10
# 最大重试次数
_MAX_RETRIES = 3


@tool
def web_search(
    query: str,
    max_results: int = _DEFAULT_MAX_RESULTS,
) -> str:
    """
    联网搜索 DST（饥荒联机版）相关的公开文档、Wiki、论坛帖子和 Mod 社区资源。

    使用场景：
    - 用户问"DST 的 xxx API 怎么用"，且本地源码中搜不到
    - 需要了解某个游戏机制的更新历史或社区讨论
    - 查找 Klei 官方文档或 Wiki 中记录的功能说明

    重要：本工具的定位是"辅助发现关键词"，不是最终答案。
    - 联网搜索告诉你"该搜什么"，本地 grep/read_file 告诉你"实际是什么"。
    - 如果 web_search 找到了某个 API 名称，请用 grep 在本地源码中验证它是否真实存在。
    - 永远不要用它来搜索代码——代码搜索用 grep。

    Args:
        query: 搜索关键词。建议用英文（DST 文档大多是英文），
               例如 "DST beefalo domestication SetDomestication API"。
        max_results: 最多返回几条搜索结果（默认 5，最大 10）。
    """
    # 限制 max_results 范围
    max_results = min(max(max_results, 1), _MAX_ALLOWED)

    logger.info("web_search: query=%r, max_results=%d", query, max_results)

    # 尝试导入 duckduckgo_search
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return (
            "错误：未安装 duckduckgo_search 库，无法进行联网搜索。\n"
            "请在终端运行：pip install duckduckgo_search\n"
            "安装后重启服务即可使用联网搜索功能。"
        )

    # DDGS 构造参数：代理 + 超时
    # 在中国大陆网络环境下，DuckDuckGo 直连超时/返回空，需要通过代理访问。
    # 代理地址在 .env 中配置 DDG_PROXY，如 socks5h://127.0.0.1:7890（Clash 默认端口）。
    ddgs_kwargs: dict = {"timeout": 30}
    proxy_url = settings.DDG_PROXY
    if proxy_url:
        ddgs_kwargs["proxy"] = proxy_url
        logger.info("web_search: 使用代理 %s", proxy_url)
    else:
        logger.info("web_search: 未配置 DDG_PROXY，直连搜索")

    # 指数退避重试：应对 DuckDuckGo 在中国大陆网络下的间歇性超时/限流
    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with DDGS(**ddgs_kwargs) as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            last_error = e
            logger.warning("web_search 第 %d/%d 次失败: %s", attempt + 1, _MAX_RETRIES + 1, e)
            if attempt < _MAX_RETRIES:
                delay = 2 ** attempt  # 1s, 2s, 4s
                logger.info("web_search: %ds 后重试…", delay)
                time.sleep(delay)
            continue

        if not results:
            logger.info("web_search: 返回空结果")
            return f"未找到与 '{query}' 相关的搜索结果。\n建议：尝试更简短的关键词，或换用英文搜索。"

        # 成功：格式化输出
        out_lines = [
            f"🔍 搜索 '{query}'，找到 {len(results)} 条结果：",
            "",
        ]
        for i, r in enumerate(results, 1):
            title = r.get("title", "(无标题)")
            href = r.get("href", "")
            body = r.get("body", "")
            if len(body) > 300:
                body = body[:300] + "…"
            out_lines.append(f"{i}. **{title}**")
            if href:
                out_lines.append(f"   {href}")
            out_lines.append(f"   {body}")
            out_lines.append("")

        return "\n".join(out_lines)

    # 所有重试都失败
    return (
        f"搜索失败（已重试 {_MAX_RETRIES} 次）：{type(last_error).__name__}: {last_error}\n"
        "请稍后重试，或尝试不同的搜索关键词。\n"
        "提示：如果持续失败，请检查 DDG_PROXY 配置是否正确（在中国大陆网络环境下通常需要代理）。"
    )
