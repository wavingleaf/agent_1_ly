"""
配置管理模块

使用 pydantic-settings 从 .env 文件和环境变量中加载配置。
所有配置项集中在这里，方便修改和查阅。

依赖 pip install pydantic-settings python-dotenv
"""

from pydantic_settings import BaseSettings


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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# 全局单例 —— 其他模块从此处 import
settings = Settings()
