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

### 🟢 已避免 / 开发过程坑（2+8 个）

修复已写入代码，**正常使用无需关心**。除非你要修改核心脚本，否则不会重新触发。

| # | 标题 | 修复方式 |
|---|------|---------|
| 03 | SqliteSaver.from_conn_string 返回 context manager | `store.py` 改为直接传 `sqlite3.Connection` 对象 |
| 05 | langgraph-checkpoint-sqlite 需单独安装 | 已加入 `requirements.txt` |
| 06 | RunnableConfig 参数不被 LangGraph 注入 | 改用 `langgraph.config.get_config()` |
| 07 | AsyncSqliteSaver 下同步 invoke() 500 报错 | `/chat` 端点改为 `await graph.ainvoke()` |
| 08 | uvicorn --reload 中断 checkpoint 完整性 | `agent_node` 检测并剥离孤立的 tool_calls |
| 09 | SSE stream_mode messages 混入 ToolMessage | 前端过滤 `type=tool` 的 chunk |
| 10 | DeepSeek function calling 路由不可靠 | 从工具列表移除代替 prompt 约束 |
| 11 | Canvas 初始化时 CSS Flex 布局未完成 | 用双层 `requestAnimationFrame` 延迟首次绘制 |
| 12 | 全局数组生命周期与 DOM 引用错位 | DOM 存数据快照（`steps.slice()`）而非索引 |
| 13 | ChatOpenAI 对接 DeepSeek 静默丢弃思考内容 | 切换为 `ChatDeepSeek`（`langchain-deepseek` 包） |
| 14 | SSE updates 累积 state 导致 DOM 重复渲染 | 按内容去重（`Set`）+ flex-shrink 防御 |
| 15 | uvicorn --reload + watchfiles 在 Windows 上不自启 | 创建 `启动服务.py` 独立启动脚本，手动重启 |

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
5. **LangGraph StateGraph 不吃 RunnableConfig 参数** — `def node(state, config)` 中 config 始终为 None；必须用 `get_config()`
6. **异步 checkpointer 与 invoke/ainvoke 的不兼容** — `invoke()` 同步 / `ainvoke()` 异步，错了直接 500
7. **uvicorn --reload 和 checkpoint 是竞态关系** — tool 执行中途重启产生截断 checkpoint，需对消息做完整性检测
8. **SSE stream_mode 两个数据流的过滤需求不同** — `messages` 流需手动按 type 过滤，`updates` 流已自带 role 区分
9. **Prompt 约束是软性的，工具列表是硬性的** — 不同模型对 prompt 的遵循度不同，从工具列表移除是唯一确定性保证
10. **Canvas 控件永远不要假设 script 执行时 DOM 尺寸已知** — Flex/Grid 布局是异步的，双层 rAF 是标准解法
11. **DOM 上存数据副本比存索引/ID 引用更安全** — 全局数组每次 `send()` 清空重建时，索引引用的归属关系会错位
12. **多个数据源共享一个渲染目标时，必须检查每条路径的过滤逻辑** — SSE 的 `messages` 和 `updates` 两种流都写入同一个 `streamedContent` 变量，但类型不同、过滤需求不同
13. **不要用通用适配器对接有专有字段的 provider** — `ChatOpenAI` 对接 DeepSeek 时静默丢弃 `reasoning_content`，用 `ChatDeepSeek` 专有包是唯一正确做法
14. **SSE updates 是累积的，不是增量的** — 任何基于 `updates` 可追加的 DOM 渲染（卡片、进度条）都必须去重，否则同一数据会被重复插入多次
15. **Windows 上不信任 `--reload`** — uvicorn/watchfiles 在 Windows 上有子进程 spawn 失败 bug（关闭后不重启），用独立启动脚本 + `reload=False` + 手动重启更稳定

---

## 坑列表（完整）

| # | 标题 | 领域 | 一句话 |
|---|------|------|--------|
| 01 | [Python PATH 冲突：Anaconda 3.7 覆盖 3.12](01_Python_PATH冲突_Anaconda37.md) | 环境 | 默认 `python` 指向 3.7，LangChain ≥ 3.11 要求不满足 |
| 02 | [Windows 终端 GBK 编码报错](02_Windows终端GBK编码报错.md) | 环境 | emoji/中文输出时 `UnicodeEncodeError: 'gbk'` |
| 03 | [SqliteSaver.from_conn_string 返回 context manager](03_SqliteSaver_context_manager.md) | LangGraph | 从字符串创建 checkpointer 需要 `with` 语句或手动传 Connection |
| 05 | [langgraph-checkpoint-sqlite 需单独安装](05_checkpoint_sqlite需单独安装.md) | 依赖管理 | `langgraph` 核心包不含 SQLite checkpointer |
| 06 | [RunnableConfig 参数不被 LangGraph 注入](06_RunnableConfig参数不被LangGraph注入.md) | LangGraph | `def node(state, config)` 中 config 始终为 None |
| 07 | [AsyncSqliteSaver 下 invoke() 500 报错](07_AsyncSqliteSaver下invoke报500.md) | LangGraph + FastAPI | 异步 checkpointer 必须用 `ainvoke()` |
| 08 | [uvicorn --reload 中断 checkpoint 完整性](08_uvicorn_reload中断checkpoint完整性.md) | LangGraph + uvicorn | tool 执行中途重启，checkpoint 截断，LLM 返回 400 |
| 09 | [SSE stream_mode messages 混入 ToolMessage](09_SSE_stream_mode_messages混入ToolMessage.md) | LangGraph + 前端 | `messages` 流推送所有消息类型，需手动过滤 |
| 10 | [DeepSeek function calling 路由不可靠](10_DeepSeek_function_calling路由不可靠.md) | LLM 行为 | 从工具列表移除代替 prompt 约束 |
| 11 | [Canvas 双层 rAF 初始化](11_Canvas双层rAF初始化.md) | 前端 Canvas | Flex 布局未完成时 `clientHeight=0`，双层 rAF 延迟首绘 |
| 12 | [全局数组与 DOM 引用生命周期错位](12_前端全局数组与DOM引用生命周期错位.md) | 前端架构 | DOM 存快照而非索引，因为全局数组会被后续操作清空 |
| 13 | [ChatOpenAI 对接 DeepSeek 静默丢弃思考内容](13_ChatOpenAI对接DeepSeek静默丢弃思考内容.md) | LLM 适配器 | 通用适配器丢弃 provider 专属字段，需用 ChatDeepSeek |
| 14 | [SSE updates 累积 state 导致 DOM 重复渲染](14_SSE_updates推送累积state导致DOM重复渲染.md) | LangGraph + 前端 | updates 推送完整历史而非增量，追加式渲染需去重 |
| 15 | [uvicorn --reload + watchfiles 在 Windows 上关闭后不自启](15_uvicorn_reload_watchfiles_windows不自启.md) | 环境 | 文件变更后旧进程关闭但新进程不 spawn，创建启动脚本规避 |

### 历史记录

| # | 标题 | 说明 |
|---|------|------|
| 04 | [create_agent 图节点名：model vs agent](04_create_agent节点命名.md) | `create_agent()` 已于 2026-07-04 移除，此坑不再触发 |
