"""
配置管理模块

使用 pydantic-settings 从 .env 文件和环境变量中加载配置。
所有配置项集中在这里，方便修改和查阅。

依赖 pip install pydantic-settings python-dotenv
"""

from pathlib import Path
from pydantic_settings import BaseSettings

# 项目根目录 —— 从本文件位置向上两层（src/config/ → src/ → 项目根）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """
    应用配置类

    pydantic-settings 会自动按以下优先级读取：
    1. 环境变量（最高）
    2. .env 文件
    3. 字段默认值（最低）
    """

    # --- LLM 提供商配置 ---
    # 用哪个模型提供商的 API。
    # LangChain v1.0 通过 ChatModel 抽象屏蔽了提供商差异。
    OPENAI_API_KEY: str = "sk-xxx"
    OPENAI_BASE_URL: str = ""  # 留空则用 OpenAI 官方；代理/中转服务填这里

    # --- 模型配置 ---
    # 模型名称使用 LangChain 的 "provider:model" 格式（也可直接用 model ID）
    MODEL_NAME: str = "gpt-4o-mini"

    # --- Agent 配置 ---
    # 对话历史最大条数（防止 token 超限）
    MAX_HISTORY_MESSAGES: int = 20

    # --- 持久化配置 ---
    # SQLite 数据库路径（存储 checkpoint）
    SQLITE_DB_PATH: str = "checkpoints.db"

    # --- DST 源码目录 ---
    # 从游戏安装目录 scripts.zip 解压出的 Lua 脚本所在路径。
    # grep/read_file/list_files 工具将在此目录下执行文件操作。
    # 为空时相关工具不执行，返回"未配置源码目录"提示。
    DST_SOURCE_DIR: str = ""

    # --- DST 元数据目录 ---
    # 存放 prefablist.lua / tuning.lua / chinese_s.po 等结构化元数据文件的目录。
    # dst_data_lookup 工具将直接读取此目录下的特定文件（不递归搜索）。
    # 为空时 dst_data_lookup 返回"未配置"提示，其余工具不受影响。
    DST_META_DIR: str = ""

    # --- 联网搜索代理 ---
    # DuckDuckGo 在中国大陆网络环境下直连超时/返回空。
    # 通过代理访问可解决。支持 http/https/socks5h 协议。
    # 例如 Clash 默认: socks5h://127.0.0.1:7890
    # 为空则直连搜索（可能不可用）。
    DDG_PROXY: str = ""

    # --- 思考模式配置 ---
    # DeepSeek V4 支持三个推理档位：none（跳过推理链）/ high（开启）/ max（最强推理）
    # 仅在使用 ChatDeepSeek 适配器时生效。
    # none → 不开启思考模式（最快、最省 token）
    # high → 开启推理链（推荐，适合工具调用场景）
    # max  → 最深推理（token 消耗最大，仅用于极复杂任务）
    REASONING_EFFORT: str = "none"

    model_config = {
        "env_file": str(_PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
    }


# 全局单例 —— 其他模块从此处 import
settings = Settings()
