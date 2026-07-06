# agent_langchain_1_ly

手写 StateGraph ReAct 循环 · FastAPI SSE 流式部署 · Canvas Debug 面板。

```
v0.3.0  |  LangChain 1.x · LangGraph 1.x · FastAPI · SQLite · DeepSeek V4  |  2026-07-06
```

## 项目定位

**当前阶段：教学级 Agent 骨架。** 代码 + Notebook + 可视化 Debug 面板逐层展示 Agent 的底层运行机制。

**远期目标：DST Mod 开发辅助工具。** 接入 grep 精确检索本地 DST 源码后，Agent 将能把"帮我把我的牛驯化度+7"这类自然语言需求转化为可执行的控制台命令。

## 项目状态

```
🟢 核心链路跑通     Agent 正确调工具并返回结果（DeepSeek V4 Pro API 验证通过）
🟢 Web Debug UI    聊天窗 + StateGraph 节点流转图 + 步骤时间线联动
🟢 SSE 流式输出     FastAPI StreamingResponse + 打字机效果
🟢 多轮对话记忆     AsyncSqliteSaver（持久化到磁盘）
🟢 6 个业务工具     grep · read_file · list_files · web_search · calculator · get_current_time
🟡 DST 垂直工具     dst_data_lookup（tuning_lookup + prefab_list + chinese_name_lookup 合并）
⚪ 远期功能         控制台指令辅助编写（3 阶段路线图）
```

## 快速开始

```bash
# 1. 安装依赖（Python ≥ 3.11）
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env：OPENAI_API_KEY=sk-xxx
#           OPENAI_BASE_URL=    （DeepSeek 等第三方 API 填这里）
#           MODEL_NAME=         （为空则默认 gpt-4o-mini）

# 3. 启动服务（修改 .env 后需手动重启，--reload 不监听 .env 变更）
uvicorn src.main:app --reload

# 4. 浏览器打开
#    http://localhost:8000        → 聊天 + Debug 界面
#    http://localhost:8000/docs   → Swagger API 文档
```

### 验证

```bash
# 选项 A：一键脚本（无需启动服务，直接调用 graph）
python test_demo.py

# 选项 B：curl 测试（需先启动服务）
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"现在几点？"}'

# 选项 C：SSE 流式测试
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"现在几点？"}' --no-buffer
```

## 已实现功能

### 核心架构

| 功能 | 说明 | 值得溯源 |
|------|------|---------|
| **手写 StateGraph ReAct 循环** | agent ↔ tools 循环，条件边路由，agent_node 内嵌日志 | [langgraph-101](https://github.com/langchain-ai/langgraph-101) 官方教程 |
| **SSE 流式 + 打字机效果** | FastAPI StreamingResponse + `stream_mode=["updates","messages"]` | [fastapi-langgraph-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) |
| **SSE 断连自动取消任务** | 客户端关闭标签页时 cancel 后台 Agent 任务，不浪费 token | SuperMew `agent_task.cancel()` 模式 |
| **AsyncSqliteSaver 持久化** | 对话历史持久化到磁盘，进程重启后不丢失（lifespan 初始化） | [控制台指令辅助编写_TODO.md](文档/控制台指令辅助编写_TODO.md) 改进 #2 |
| **三模式系统（dst/general/plan）** | 不同模式对应不同 System Prompt + 工具集，避免 DeepSeek 误调无关工具 | Claude Code 权限矩阵设计 |
| **6 个业务工具** | grep · read_file · list_files · web_search · calculator · get_current_time，按模式分配可见性。grep 支持 `subdir` 限定子目录搜索，web_search 支持 Clash 代理 | grep 精确检索优于 RAG（见 [设计决策.md](文档/设计决策.md) 决策 11） |
| **对话导出/导入** | 导出当前线程为 JSON 文件，导入恢复对话（含 tool_calls 重建） | — |

### Debug 工具链

| 功能 | 说明 |
|------|------|
| **Web Chat UI** | 纯 HTML/CSS/JS 单文件，零框架依赖 |
| **StateGraph 节点流转图** | Canvas 可拖拽/缩放，选中步骤后联动高亮 |
| **步骤时间线** | 左右分栏：左侧步骤列表 + 右侧选中步骤的完整 transition 信息 |
| **raw SSE 事件面板** | 可折叠查看服务端推送的原始事件 JSON |
| **统计条** | 循环次数 / 工具调用次数 / 消息数 / 耗时 |

### Notebook 学习路径

见 `文档/notebooks/` 目录（01 → 04，从 `create_agent()` 入门到手写 StateGraph，再到中间件和 FastAPI 部署）。

## 参考项目对照

本项目吸收了 [langgraph-101](https://github.com/langchain-ai/langgraph-101)、[agent-craft](https://github.com/Annyfee/agent-craft)、[fastapi-langgraph-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template) 等项目的设计，详见 [参考项目对比分析.md](文档/参考项目对比分析.md)。

## 架构

```
┌──────────────────────────────────┐
│  API 层      FastAPI             │  /chat  /chat/stream  /health  /chat/history
│              SSE 流式推送         │
├──────────────────────────────────┤
│  Agent 编排层 LangGraph          │  StateGraph · ReAct · 条件边 · checkpointer
├──────────────────────────────────┤
│  工具层      @tool               │  grep / read_file / list_files / web_search
│              (按模式分配)         │  calculator / get_current_time
├──────────────────────────────────┤
│  记忆层      AsyncSqliteSaver  │  持久化多轮记忆（重启不丢失）
└──────────────────────────────────┘
```

设计决策详见 [设计决策.md](文档/设计决策.md)（12 个 ADR，覆盖 SSE vs WebSocket、SqliteSaver 选型、grep 精确检索 vs RAG 等）。

## TODO

远期目标：**DST 控制台指令辅助编写**——自然语言 → grep 精确检索源码 → 可执行的控制台命令。详见 [控制台指令辅助编写_TODO.md](文档/控制台指令辅助编写_TODO.md)。

## 已知限制

- DuckDuckGo 搜索结果有长查询匹配差和噪音问题（已通过 DDG_PROXY 代理解决连通性）
- 前端未工程化：`debug_ui.html` 是单文件裸 JS/CSS/Canvas，功能增长后需考虑拆分
- 测试依赖网络：集成测试需要有效的 API key，web_search 需要代理或国外网络

## 项目文件

```
.
├── .env.example            API Key 模板
├── requirements.txt        LangChain + LangGraph + FastAPI + SQLite
├── debug_ui.html           Web 聊天 + Debug 面板（单文件）
├── test_demo.py            一键验证脚本（4 项测试）
│
├── src/
│   ├── main.py             FastAPI 服务入口
│   ├── agent/              Agent 编排（state + graph）
│   ├── config/             配置管理（pydantic-settings）
│   ├── tools/              工具定义（@tool）
│   └── memory/             持久化（checkpointer factory）
│
├── tests/                  Pytest 单元测试
├── 文档/
│   ├── 设计决策.md
│   ├── 参考项目对比分析.md
│   ├── 用户测试案例v0.2.0.md
│   ├── 用户测试案例v0.3.0.md
│   ├── 控制台指令辅助编写_TODO.md
│   ├── notebooks/          学习 Notebook（01 → 04）
│   └── 踩坑记录/            5 篇技术踩坑文档
```

## 相关文档

| 文档 | 文件 | 内容 |
|------|------|------|
| 设计决策（ADR） | [设计决策.md](文档/设计决策.md) | 12 个架构决策 |
| 参考项目对比分析 | [参考项目对比分析.md](文档/参考项目对比分析.md) | 6+1 个参考项目的详细对照 |
| Agent 行为模拟器 | [agent项目介绍.html](文档/agent项目介绍.html) | 独立 HTML，可交互逐步骤播放 |

---

> **许可**：MIT  ·  **当前阶段**：教学骨架，核心链路 + Debug 工具链可用  ·  **远期**：DST Mod 控制台指令辅助工具
