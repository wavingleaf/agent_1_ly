---
name: 控制台指令辅助编写
description: Agent 高级功能 TODO：辅助编写 DST 控制台指令，通过 grep 精确检索源码，处理需求模糊、不完整、不正确的场景
metadata:
  type: project
---

# Agent 高级功能 TODO：DST 控制台指令辅助编写

## 功能描述

用户用自然语言描述"想对游戏做什么"，Agent 将其转化为可执行的控制台命令。

**示例场景**：用户说"帮我把我的牛驯化度+7"，Agent 需完成：
1. 识别"我的牛"的判定方式（提醒用户把牛带到身边 → 用 `GetClosestInst` 选取最近
   `beefalo` 实体）
2. 查询驯化度相关代码（`domesticatable` 组件 → `SetDomestication` /
   `GetDomestication`）
3. 组装完整控制台命令

## 核心策略：grep 精确检索，不走 RAG

本项目**不依赖 RAG 知识库**（RAG 项目目前仍有多项待优化，不应作为本功能的依赖项）。改为用 `grep`/`rg` 等工具对「本地的DST源码文件」做**精确字符串匹配**。

**为什么 grep 更适合这个场景：**

| 维度 | RAG 向量检索 | grep 精确匹配 |
|------|------------|-------------|
| 查函数名/方法名 | 可能漏（语义近似 ≠ 字符串匹配） | **精准命中** `function X:SetDomestication` |
| 查组件字段 | 向量不区分 `inst.` 和 `self.` | **行号+上下文**一目了然 |
| 结果可靠性 | 概率性，可能遗漏关键定义 | **确定性**，只要字符串匹配就能找到 |
| 依赖条件 | 需预建索引、embedding 模型、ChromaDB | 仅需文件系统 + `rg` |

---

### 关键澄清：LLM 提供「候选」，grep 提供「验证」

从"驯化度+7"推理出搜索 `domesticatable|SetDomestication|GetDomestication`，LLM **不是在查文档**——它是在**基于训练语料做统计推断**。模型在训练时见过 DST 的 Lua 源码、Wiki 讨论、Mod 社区帖子，所以"驯化度"和 `domesticatable` 在它的参数空间中形成了高概率关联。

**但这个推断是不可靠的。** 具体来说有三种风险：

| 风险 | 示例 | 后果 |
|------|------|------|
| **语料过时** | 游戏版本迭代后 `SetDomestication` 改名为 `SetDomesticationPercent`，但训练数据中是旧版 | grep 搜不到目标符号 |
| **语料不全** | 某个冷门组件（如 `terraformer`）根本没出现在训练语料中 | LLM 完全不知道要搜什么 |
| **幻觉** | LLM 把另一个 Lua 项目（如 World of Warcraft 插件）的 API 安到了 DST 头上 | grep 搜到的是无关代码或空结果 |

**因此工作流不是单次"推理→搜索→完成"，而是循环验证：**

```
用户需求
  → LLM 推理候选搜索词（基于训练语料 + 中英文术语常识）
  → grep 验证：候选符号是否真的存在于本地源码中？
  → 命中 → 阅读上下文 → 确认方法签名 → 拼装命令
  → 未命中 → LLM 换一组搜索策略重试
       （例如：搜更宽泛的关键词 "domestication"、搜组件文件名 "domesticatable.lua"、
        搜中文注释中的"驯化"、搜可能相关的 TUNING 常量）
```

LLM 的角色是**提出假设**，不是**给出答案**。grep 才是最终裁决——本地源码是唯一的地面真相（ground truth）。

这决定了工具链需求：Agent 必须能够**多轮 grep**（第一轮命中率不高时应自动调整搜索词重试），而不是一次 grep 失败就放弃。

---

## 核心困境

### 困境 1：需求不明确

用户说"帮我把我的牛驯化度+7"，但实际需求是：
- 选取距离玩家最近的一只牛（`GetClosestInst(ThePlayer, "beefalo")`）
- 判断它是否正在被驯化（检查 `components.domesticatable` 是否存在）
- 获取当前驯化度值，加 7 后设为新值

Agent 必须**推演缺失步骤**，不能只翻译用户原话。

### 困境 2：需求可能不正确

"我的牛"是个模糊概念。DST 中没有"属于某玩家的牛"。Agent 需：
- 识别歧义（"我的"="正在驯化中"还是"离我最近"？）
- 向用户确认判定逻辑，给出可行方案
- 提醒用户操作前提（"把牛带到你身边再执行"）

### 困境 3：需要精准代码查询

控制台指令分两类：
| 类型 | 示例 | 实现方式 |
|------|------|---------|
| **常见命令**（有现成） | `c_godmode()`、`c_give("meat")` | 直接给出 |
| **代码级操作**（无现成） | 修改某头牛的驯化度 | 查组件源码 → 拼装 Lua 表达式 |

Agent 需要：
1. LLM 理解需求后，推理出需要查询的**关键符号**（函数名、组件名、字段名）—— 例如从"驯化度+7"推理出需要查 `domesticatable` 组件、`SetDomestication` / `GetDomestication` 方法
2. 用 grep 在源码中精确搜索这些符号，获取**行号 + 文件路径 + 上下文**
3. 阅读 grep 返回的上下文，确认方法签名和调用方式
4. 将结果格式化为控制台可粘贴的形式

## 近期可做的改进（低投入、高收益）

### 改进 1：SSE 断连后取消 Agent 任务（~15 行）

**现状**：用户关闭浏览器标签页后，后端的 `graph.astream()` 仍在运行，LLM 继续推理直到完成，白白消耗 token。

**方案**：在 `main.py` 的 `event_generator` 中，将 `graph.astream()` 包装为 `asyncio.Task`，在 `finally` 块里 `task.cancel()`。当 SSE 连接断开 → `GeneratorExit` → `finally` 触发 → cancel 掉 LLM 推理。

```python
# 伪代码
async def event_generator():
    task = asyncio.create_task(stream_graph())
    try:
        async for event in task: yield event
    finally:
        task.cancel()  # 用户断连 = 不继续烧 token
```

- [ ] 完成后记入 README 的「已实现功能」
- 参考：SuperMew 项目的 `chat/service.py` 中 `agent_task.cancel()` 模式

---

### 改进 2：AsyncSqliteSaver 持久化长期记忆（~20 行）

**现状**：服务端用 `MemorySaver`，进程重启后所有对话历史丢失。之前尝试 `SqliteSaver.from_conn_string()` 失败——它是 context manager，无法在模块级全局使用。`AsyncSqliteSaver` 同理。

**方案**：绕开 `from_conn_string()`，直接传 `aiosqlite.Connection` 给 `AsyncSqliteSaver` 构造函数：

```python
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

conn = await aiosqlite.connect("checkpoints.db")
checkpointer = AsyncSqliteSaver(conn)
graph = workflow.compile(checkpointer=checkpointer)
# astream 正常运行，对话历史持久化到磁盘
```

`aiosqlite` 已作为 `langgraph-checkpoint-sqlite` 的依赖安装。改动位置：`src/memory/store.py` 新增 `create_async_checkpointer`，`src/main.py` 在 FastAPI lifespan 中初始化 graph。

- [ ] 完成后将 README 项目状态行改为"🟢 多轮对话记忆（SqliteSaver，持久化）"

---

### 改进 3：混合模式 — 外层 StateGraph + 内层 Agent 子图（~50 行）

**背景**：[LangChain 官方文档](https://docs.langchain.com/oss/python/langchain/middleware/overview) 和 [论坛讨论](https://forum.langchain.com/t/i-am-gonna-use-langchain-builtin-middleware-in-custom-state-graph/2414/2) 确认：`create_agent()` 的中间件（`before_model`、`after_model`、`wrap_tool_call` 等）只能用于 `create_agent()` 路线，手写 StateGraph 没有等价机制。

但两条路线可以**混合使用**——这是官方推荐的生产级模式。外层用自定义 StateGraph 做编排（路由、分类、校验、审批），内层将 `create_agent()`（带中间件）作为子图嵌入，负责 LLM 工具调用循环。

```
自定义 StateGraph（外层）
┌──────────────────────────────────────────────────┐
│  ┌──────────┐     ┌──────────────────────────┐   │
│  │ classify  │────→│  create_agent() 子图      │   │
│  │ 意图分类  │     │  model → tools → model    │ ← 工具调用发生在这里
│  └──────────┘     │  (带 middleware)          │   │
│                   └──────────┬───────────────┘   │
│                   ┌──────────▼──────────────┐    │
│                   │  审核 / 校验 / 分支        │    │
│                   └─────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

- 当前项目（手写 StateGraph）是"学习骨架"，外层编排逻辑直接写在 `graph.py` 里
- 当控制台指令辅助功能需要意图分类 + grep 检索 + 结果验证等复杂编排时，混合模式会让结构更清晰
- [ ] 在控制台指令辅助的第一阶段实现时评估是否需要混合模式

## 实现阶段

### 第一阶段：基础链路（grep 驱动）

- Agent 接收自然语言需求
- LLM 推理：从需求中提取关键符号（组件名/方法名/字段名）→ 用 `grep` 精确搜索 → 阅读搜索结果的上下文 → 拼装命令
- 示例链路：`"驯化度+7" → 想到查 "SetDomestication\|GetDomestication\|domesticatable" → grep → 找到方法签名 → 拼装 ThePlayer.components.domesticatable:SetDomestication(...)`
- 输出推理过程（需求分析 → 缺失步骤推演 → 符号推断 → grep 查询 → 命令拼装）

### 第二阶段：歧义检测与确认

- 识别模糊指代（"我的""最近的""那个"）
- 主动向用户提问确认
- 给出多个可选方案供用户选择

### 第三阶段：代码级操作自动化

- 查询 DST 源码中的组件方法签名
- 自动拼装合法的 Lua 表达式
- 检查命令安全性（只读 vs 修改）

## 参考

- 需求模糊处理：采用"先定位术语、再精确检索"的两阶段策略——LLM 从自然语言中提取关键符号 → grep 精确命中定义位置 → 阅读上下文后拼装命令
- 代码查询：依赖「本地的DST源码文件」（游戏安装目录 `scripts.zip` 解压出的 Lua 脚本）
- 常见控制台命令：项目 `mod流水线/` 下可能有收录
- grep 工具：Windows 下可用 `rg`（ripgrep）或 Git Bash 自带的 `grep`

**Why:** 这是 LangChain Agent 项目的核心实战场景——将 Agent 的"LLM 推理 → 符号推断 → grep 精确搜索 → 代码阅读 → 多步骤命令拼装 → 用户交互"能力在 DST Mod 开发中落地。

**How to apply:** 作为 agent项目 的远期 TODO。当前 agent_langchain_1_ly 的 StateGraph 架构已支持多节点条件路由，本功能需要新增：grep 工具（Agent 可调用）、源码目录配置、需求分解节点、用户确认交互节点。
