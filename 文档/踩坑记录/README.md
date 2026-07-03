# 踩坑记录 — agent_langchain_1_ly

本项目在搭建 LangChain Agent 过程中踩过的技术坑。每个坑单独成文，按时间顺序编号。

---

## 阅读指引（先看这里）

### 🔴 极易误触（1 个）

**无需修改代码就会反复触发**，且报错信息不明显。优先阅读。

| # | 标题 | 触发条件 |
|---|------|---------|
| 01 | Python PATH 冲突：Anaconda 3.7 覆盖 3.12 | 任何 `python` 命令——系统默认指向 3.7，LangChain 不兼容 |

### 🟡 使用方式依赖（1 个）

走正确方式就安全，直接手动调用则触发。

| # | 标题 | 安全做法 | 触发条件 |
|---|------|---------|---------|
| 02 | Windows 终端 GBK 编码报错 | IDE 内或 VSCode 终端运行 | 直接用 Windows 命令提示符/PowerShell 运行脚本 |

### 🟢 已避免 / 开发过程坑（2 个）

修复已写入代码，**正常使用无需关心**。除非你要修改核心脚本，否则不会重新触发。

| # | 标题 | 修复方式 |
|---|------|---------|
| 03 | SqliteSaver.from_conn_string 返回 context manager | `store.py` 改为直接传 `sqlite3.Connection` 对象 |
| 05 | langgraph-checkpoint-sqlite 需单独安装 | 已加入 `requirements.txt` |

### ⚪ 已废弃（1 个）

项目架构已变，此坑不再触发。

| # | 标题 | 废弃原因 |
|---|------|---------|
| 04 | create_agent 图节点名：model vs agent | `create_agent()` 已从项目中移除（2026-07-04），现仅用手写 StateGraph |

---

## 通用教训

1. **Windows 中文环境的 PATH 陷阱** — Anaconda、系统自带 Python、手动安装的 Python 可能同时存在，`python` 命令的指向不可靠
2. **LangChain/LangGraph 生态拆包细** — `langgraph`、`langgraph-checkpoint-sqlite`、`langgraph-prebuilt` 是独立 pip 包，缺一个报错信息不清晰
3. **LangGraph 1.2 的 checkpointer API 变化** — `from_conn_string()` 从直接返回实例改成了 context manager 模式，旧教程会误导
4. **先做最小化验证** — 每次配置变更后用 3 行代码测试导入，比跑全流程快得多

---

## 坑列表（完整）

| # | 标题 | 领域 | 一句话 |
|---|------|------|--------|
| 01 | [Python PATH 冲突：Anaconda 3.7 覆盖 3.12](01_Python_PATH冲突_Anaconda37.md) | 环境 | 默认 `python` 指向 3.7，LangChain ≥3.11 要求不满足 |
| 02 | [Windows 终端 GBK 编码报错](02_Windows终端GBK编码报错.md) | 环境 | emoji/中文输出时 `UnicodeEncodeError: 'gbk'` |
| 03 | [SqliteSaver.from_conn_string 返回 context manager](03_SqliteSaver_context_manager.md) | LangGraph | pip 从字符串创建 checkpointer 需要 `with` 语句或手动传 Connection |
| 05 | [langgraph-checkpoint-sqlite 需单独安装](05_checkpoint_sqlite需单独安装.md) | 依赖管理 | `langgraph` 核心包不含 SQLite checkpointer，需额外 pip install |

### 历史记录

| # | 标题 | 说明 |
|---|------|------|
| 04 | [create_agent 图节点名：model vs agent](04_create_agent节点命名.md) | `create_agent()` 已于 2026-07-04 移除，此坑不再触发 |
