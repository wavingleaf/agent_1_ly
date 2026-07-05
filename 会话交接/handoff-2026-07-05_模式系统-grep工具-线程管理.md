# Handoff: agent_langchain_1_ly — 模式系统 + grep 工具 + 对话线程管理等全面改进

## 当前状态

本对话修改前版本为v0.1.0-demo，核心链路跑通。手写 StateGraph ReAct 循环，FastAPI SSE 流式，Canvas Debug 面板。已完成计划中优先级一和二的全部改动，工具集由 2 个教学工具扩展为 3 个（新增 grep），支持 DST/通用/Plan 三模式切换，对话线程可管理持久化，聊天窗支持 Markdown 渲染。**10 个 pytest 全部通过。**

## 起点：从计划文档出发

本会话从整理项目状态开始，通读了四份文档后制定了工作优先级：

- [README.md](README.md)
- [文档/控制台指令辅助编写_TODO.md](文档/控制台指令辅助编写_TODO.md)
- [文档/设计决策.md](文档/设计决策.md)
- [文档/参考项目对比分析.md](文档/参考项目对比分析.md)

计划文件：[C:\Users\ADMIN\.claude\plans\agent-readme-todo-handoff-majestic-harbor.md](C:\Users\ADMIN\.claude\plans\agent-readme-todo-handoff-majestic-harbor.md)

---

## 本会话完成的工作

### 1. 改进 1：SSE 断连后取消 Agent 任务

**问题**：用户关闭浏览器标签页后，后端 `graph.astream()` 仍在运行，白白消耗 token。

**方案**：`graph.astream()` 包装为 `asyncio.Task` + `asyncio.Queue`，客户端断连 → `GeneratorExit` → `finally` 触发 `agent_task.cancel()`。

**文件**：[src/main.py](src/main.py)

- 新增 `import asyncio`
- `chat_stream` 端点重写：`_run_agent()` 后台 task 将事件推入 `asyncio.Queue`，主循环从队列取事件 yield。`finally` 块检查 `agent_task.done()`，未完成则 `cancel()`。

**参考**：SuperMew 项目的 `agent_task.cancel()` 模式。

---

### 2. 改进 2：AsyncSqliteSaver 持久化长期记忆

**问题**：原先用 `MemorySaver`，进程重启后所有对话历史丢失。

**方案**：绕过 `from_conn_string()`（context manager 限制），直接传 `aiosqlite.Connection` 给 `AsyncSqliteSaver` 构造函数。在 FastAPI `lifespan` 中异步初始化。

**文件**：
- [src/memory/store.py](src/memory/store.py) — 新增 `create_async_checkpointer()`，用 `aiosqlite.connect()` 直传给 `AsyncSqliteSaver`
- [src/agent/graph.py](src/agent/graph.py) — `build_graph(checkpointer=None)` 支持运行时注入 checkpointer，新增 `init_graph()` 全局替换函数
- [src/main.py](src/main.py) — 新增 `lifespan`（`@asynccontextmanager`），启动时创建 `AsyncSqliteSaver` + 调用 `init_graph()`

**关键决策**：`/chat` 端点原用同步 `graph.invoke()`，升级到 AsyncSqliteSaver 后必须改用 `await graph.ainvoke()`，否则 500 报错。

---

### 3. DST_SOURCE_DIR 配置

**文件**：
- [src/config/settings.py](src/config/settings.py) — 新增 `DST_SOURCE_DIR: str = ""`
- [.env.example](.env.example) — 新增模板行
- [.env](.env) — 值：`d:/Github项目/mod流水线/DST本体scripts/scripts 修改日期20260604`

---

### 4. grep 工具集成

新建 [src/tools/grep_ly.py](src/tools/grep_ly.py)，定义 `@tool grep(pattern, context_lines, max_results)`：

- 递归收集 `.lua` 文件（跳过 `.git`、`__pycache__`）
- 子串匹配 + 上下文行输出
- 未配置 `DST_SOURCE_DIR` 时返回明确错误提示
- `src/tools/builtin.py` 中注册到 `ALL_TOOLS`

**设计要点**：grep 是确定性匹配（vs RAG 概率检索），LLM 提供候选、grep 提供验证。

---

### 5. 模式系统（DST 助手 / 通用助手 / Plan 占位）

**调研基础**：借鉴 Claude Code 的模式架构——权限矩阵、工具可见性、System Prompt 三层联动，Defense in Depth。

**架构**：后端 `ChatRequest` 新增 `mode` 字段 → configurable 传入 graph → `agent_node` 通过 `langgraph.config.get_config()` 读取 → 选择对应的 system prompt + 工具集。

**模式定义**（[src/agent/graph.py](src/agent/graph.py)）：

| 模式 | System Prompt | 工具集 |
|------|--------------|--------|
| `"dst"` | DST Mod 开发助手身份 + 工具路由规则 | `[calculator, grep]`（**不含** `get_current_time`——即使工具描述写了"不要在其他场景调用"，DeepSeek 仍偶尔误调，从工具列表移除是最可靠的解法） |
| `"general"` | 通用开发者助手 | `[get_current_time, calculator, grep]` |
| `"plan"` | 规划模式（占位） | `ALL_TOOLS`（占位，当前无编辑工具可移除） |

**前端**（[debug_ui.html](debug_ui.html)）：聊天窗标题栏新增 `<select id="mode-select">`，持久化到 `localStorage`（key: `agent_ui_mode`），DST 模式橙色边框、Plan 模式紫色边框。

**System Prompt 设计原则**：system prompt 和工具描述**双管齐下**——GPT-4/Claude 重 system prompt，DeepSeek 重 function calling schema，两边都要覆盖。

---

### 6. Markdown 渲染

聊天窗 AI 气泡由 `textContent` 改为 `renderMd()` HTML 渲染。在 [debug_ui.html](debug_ui.html) 底部实现轻量解析器（零依赖）：

- 代码块 `` ```...``` `` → `<pre><code>`
- 表格 `| col | col |` → `<table>`
- 标题 `##` / `###` → `<h3>` / `<h4>`
- 行内 `` `code` `` → `<code>`，`**bold**` → `<strong>`
- ASCII 框图（制表符 ┌─│等）→ `<pre class="ascii-art">`
- 流式安全：代码块仅完整闭合才渲染，未闭合时保留原文

CSS 在 `</style>` 前新增 `.content h3/h4/code/pre/table/ul/ol/p` 全套样式。

---

### 7. 对话线程管理

**替换了原有的单一 thread_id + localStorage 简单持久化**，改为完整的线程管理系统：

**数据存储**：
- `localStorage.agent_ui_threads`：`[{id, name, createdAt}]` 数组
- `localStorage.agent_ui_active_id`：当前活跃 thread_id
- 首次访问自动创建"默认对话"线程

**UI**（[debug_ui.html](debug_ui.html) 标题栏）：
- `<select id="thread-select">` — 下拉切换线程
- `✎` — 重命名（`prompt()` 弹窗）
- `🗑` — 删除（至少保留 1 个线程）
- `＋` — 新建（弹窗输入名称）

**历史加载**：新增 `GET /chat/history/{thread_id}` 端点（[src/main.py](src/main.py)），调用 `graph.aget_state(config)` 读取 checkpoint。前端 `loadThreadHistory(id)` 从消息列表重建聊天窗气泡 + 步骤数据（`_ownSteps`）。

**切换线程**：`switchThread(id)` → `loadThreadHistory(id)` → 完整恢复对话。后端对话数据在 `checkpoints.db` 中持久化，重启不丢失。

---

### 8. Debug 优化：点击用户气泡查看行为

- 用户消息气泡设为 `cursor: pointer`，点击触发 `selectUserMessage(bubble)`
- 实时消息：`onDone()` 中 `steps.slice()` 快照存入气泡 `_ownSteps`
- 历史消息：`loadThreadHistory()` 从消息列表重建 `_ownSteps`
- 点击时调用 `renderTimelineForSteps(list)` —— 替换全局 `steps`、重建时间线 DOM、更新统计条、触发 Canvas 重绘
- 右侧面板可逐步骤点击查看详情

---

### 9. 工具气泡截断优化

- 聊天窗工具气泡：截断到 **100 字符** + `…`（原 200）
- CSS：`font-size: 0.78em; font-family: inherit`（正常字体替代等宽字体，自然控制行数）
- 右侧步骤详情「工具返回值」：完整显示，`max-height: 300px; overflow-y: auto; white-space: pre-wrap`

---

### 10. 步骤排序修复

LLM 产出内容时 `content`（前导文字）先于 `tool_calls`（调工具决策）。`processEvent` 将 `if/else if` 改为两个独立的 `if`，`loadThreadHistory` 同步修复。DeepSeek 调工具时 `content=""`（空），所以看不到前导文字步骤——不是 bug，是模型行为特征。

---

### 11. 其他修复

| 问题 | 根因 | 修复 |
|------|------|------|
| DST 模式仍调 `get_current_time` | `config: RunnableConfig = None` 参数 LangGraph 不会自动注入，config 始终为 None，mode 回退到 general | 改用 `from langgraph.config import get_config()` 显式获取 |
| StateGraph Canvas 不渲染 | `redraw()` 在 `<script>` 底部同步调用时 CSS Flex 布局未完成，`clientHeight=0` | 改用 `requestAnimationFrame(() => requestAnimationFrame(() => redraw()))` |
| `--reload` 重启导致 400 错误 | checkpoint 保存了 AIMessage(tool_calls=[...]) 但缺少对应 ToolMessage | `agent_node` 中检测孤立的 tool_calls，自动剥离 |
| 集成测试被误 skip | `os.getenv("OPENAI_API_KEY")` 读不到 `.env` 值 | 改用 `settings.OPENAI_API_KEY`（pydantic-settings 自动读 `.env`） |
| `debug_ui.html` 浏览器缓存 | 无缓存头 | `index()` 加 `Cache-Control: no-cache, no-store, must-revalidate` |

---

## 关键决策

1. **DST 模式移除 `get_current_time`**：DeepSeek function calling 路由能力有限，工具描述再清晰仍偶尔误调。从工具列表直接移除是最可靠的解法，与 Claude Code "模式控制工具可见性" 一致。

2. **grep 输出完整喂给 LLM，不做系统层截断**：曾尝试截断到 250 字符，但意识到 grep 的消费者是 LLM，截断是自残分析能力。最终改为 system prompt 轻量引导"优先简洁总结"。

3. **线程管理用 localStorage + SQLite 双层**：前端线程元数据（名称、创建时间）存 localStorage，对话内容存 SQLite（AsyncSqliteSaver）。删除线程只移出前端列表，SQLite 数据不清理（孤儿记录不占显著空间）。

4. **SSE streaming 中过滤 ToolMessage**：`stream_mode=["updates", "messages"]` 的 messages 模式推送所有消息类型的 chunk。只将 `type=ai/AIMessageChunk` 的 content 拼入 `streamedContent`，过滤掉 `type=tool` 的 chunk，防止工具结果混入 AI 气泡。

---

## 踩坑记录

### `RunnableConfig` 参数不会被 LangGraph 注入

`def agent_node(state: AgentState, config: RunnableConfig = None)` — config 始终为 None。
正确做法：`from langgraph.config import get_config; config = get_config()`

### `invoke()` vs `ainvoke()` 与 AsyncSqliteSaver 的兼容性

AsyncSqliteSaver 下同步 `graph.invoke()` 会 500 报错，必须用 `await graph.ainvoke()`。`/chat/stream` 端点用 `graph.astream()` 天然兼容。

### `--reload` 重启导致 checkpoint 不完整

uvicorn `--reload` 在 tool 节点执行中途重启进程，AIMessage 的 tool_calls 写入 checkpoint 但 ToolMessage 缺失。发给 LLM 触发 `400: tool_calls must be followed by tool messages`。修复：`agent_node` 在构造消息前检测并修复。

### 前端全局变量与消息生命周期的错位

`steps` 数组每次 `send()` 清空，旧气泡存索引会失效。改为 `onDone()` 时 `steps.slice()` 快照存入气泡 DOM `_ownSteps`。

---

## 关键文件索引

| 文件 | 角色 | 变更程度 |
|------|------|:--:|
| [src/agent/graph.py](src/agent/graph.py) | 核心编排：3 套 system prompt、模式路由、config 读取、checkpoint 修复逻辑 | 🔴 重写 |
| [src/main.py](src/main.py) | FastAPI 入口：SSE 断连取消、lifespan、`/chat/history` 端点、`ainvoke` 修复、缓存头 | 🔴 重写 |
| [src/tools/grep_ly.py](src/tools/grep_ly.py) | grep 工具：递归文件搜索、格式化输出 | 🟢 **新** |
| [src/tools/builtin.py](src/tools/builtin.py) | 工具注册：新增 grep、`DST_TOOLS`、`PLAN_TOOLS` | 🟡 修改 |
| [src/memory/store.py](src/memory/store.py) | 新增 `create_async_checkpointer()` | 🟡 修改 |
| [src/config/settings.py](src/config/settings.py) | 新增 `DST_SOURCE_DIR` | 🟡 修改 |
| [debug_ui.html](debug_ui.html) | 前端全部：模式下拉框、线程管理、Markdown 渲染、气泡点击、步骤排序、Canvas 渲染 | 🔴 重写 |
| [.env](.env) | 新增 `DST_SOURCE_DIR` | 🟡 修改 |
| [.env.example](.env.example) | 新增 `DST_SOURCE_DIR` 模板 | 🟡 修改 |
| [tests/test_agent.py](tests/test_agent.py) | 新增 grep 测试、`DST_TOOLS` 校验、skipif 修复 | 🟡 修改 |
| [README.md](README.md) | 状态行更新、功能表新增、已知限制更新 | 🟡 修改 |
| [文档/浏览器手动验证指南.md](文档/浏览器手动验证指南.md) | 8 个测试覆盖全部功能，每项标注模式和预期 | 🟢 **新** |

---

## 下一步

按优先级：

1. **测试验证**：重启 uvicorn → 浏览器打开 → 对照 [文档/浏览器手动验证指南.md](文档/浏览器手动验证指南.md) 逐条测试（特别是测试 1 DST 模式 grep、测试 2 模式对比）
2. **改进 3：混合模式 StateGraph + Agent 子图**：[src/agent/graph.py](src/agent/graph.py) 约 50 行，控制台指令辅助第一阶段时按需评估
3. **ReAct 最大轮数限制**：当前 DeepSeek 有时会调 4 轮 grep 才停，浪费 token
4. **控制台指令辅助第一阶段**：grep 工具已就位，需要新增"需求分解节点"实现 LLM 推理 → grep 验证 → 命令拼装的完整链路
5. **CI 配置 + `stream_mode=["custom"]` 进度推送**（参考项目对比分析第一梯队）

---

## Suggested Skills

1. **继续开发**：启动服务后在浏览器对照验证指南逐条测试，确认所有改动在页面上都能正常观察到效果。关键文件：[文档/浏览器手动验证指南.md](文档/浏览器手动验证指南.md)
2. **排查路由问题**：若 DST 模式仍误调时间工具，查终端日志中 `agent_node mode=dst tools=[...]` 行——确认 get_config() 正确读取了 mode。关键文件：[src/agent/graph.py](src/agent/graph.py)
3. **功能摘抄**：如需从其他 LangGraph 项目借鉴 ReAct 轮数限制或混合模式实现，可调用此 skill。关键文件：[src/agent/graph.py](src/agent/graph.py)
4. **verify**：新增功能或修复后，运行 `D:/Apps/Python/python.exe -m pytest tests/test_agent.py -v` 确认 10 passed。
5. **code-review / simplify**：`debug_ui.html` 当前约 650 行，如需拆分重构可调用。
