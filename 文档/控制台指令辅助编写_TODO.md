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

### 改进 1：SSE 断连后取消 Agent 任务（~15 行）✅ 已完成（2026-07-05）

**已于 2026-07-05 实现。** 见 [src/main.py](../src/main.py) `chat_stream` 端点：`asyncio.Task` + `asyncio.Queue` 包装 `graph.astream()`，断连时 `finally` 中 `agent_task.cancel()`。

参考：SuperMew 项目的 `agent_task.cancel()` 模式。

---

### 改进 2：AsyncSqliteSaver 持久化长期记忆（~20 行）✅ 已完成（2026-07-05）

**已于 2026-07-05 实现。** 见 [src/memory/store.py](../src/memory/store.py) `create_async_checkpointer()`，[src/main.py](../src/main.py) `lifespan` 中初始化。异步版 checkpointer 直接传 `aiosqlite.Connection` 绕过 context manager 限制。

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

## 待添加工具

当前 Agent 有 3 个工具：`get_current_time`、`calculator`、`grep`。grep 是唯一业务工具，但其能力边界有限——只搜字符串，不能读完整文件、不能查结构化数据。以下按优先级列出需要添加的工具。

### 常见工具

这些工具与 DST 领域无关，是开发助手的通用能力。

| # | 工具 | 功能 | 为什么需要 | 实现复杂度 |
|---|------|------|-----------|:--:|
| 1 | **read_file** | 读取指定文件的完整内容（可选行范围截断） | grep 只给 2 行上下文，Agent 看不到完整函数体。grep 找位置，read_file 读内容——两者是搭档。 | 低（~40 行） |
| 2 | **list_files** | 列出指定目录的文件和子目录 | Agent 不知道源码目录结构长什么样、组件放在 `components/` 还是 `scripts/`。list_files 让 Agent 在搜之前就知道去哪搜。 | 低（~30 行） |
| 3 | **web_search** | 联网搜索 DST Wiki、Klei 论坛、Mod 社区 | LLM 训练数据中的 DST API 可能过时。联网搜索能帮 Agent 知道"该搜什么关键词"，但不替代 grep（grep 是地面真相）。 | 中（需搜索 API，如 Tavily/SerpAPI，或利用 DeepSeek 内置搜索） |

### 垂直领域工具

这些工具针对 DST Mod 开发场景，利用项目内已有的数据文件做结构化查询。

| # | 工具 | 功能 | 数据源 | 与 grep 的关系 | 实现复杂度 |
|---|------|------|--------|:---:|:--:|
| 4 | **tuning_lookup** | 输入常量名（如 `AXE_DAMAGE`），返回定义值和计算表达式 | [tuning.lua](d:/Github项目/mod流水线/github同步/命名、参数记录/DST本体/tuning.lua) — 逐行解析 `KEY = value,` 键值对 | grep 只能搜到引用处（`SetDamage(TUNING.AXE_DAMAGE)`），找不到定义值（`= wilson_attack*.8`）。tuning_lookup 直接解析定义。 | 低（~50 行） |
| 5 | **prefab_list** | 输入名称，返回该 prefab 是否存在于游戏中及基本信息 | [prefablist.lua](d:/Github项目/mod流水线/github同步/命名、参数记录/DST本体/prefablist.lua) — 纯数组，`"axe"`, `"beefalo"`, … | grep 也能搜，但专用工具更快且不会漏。用户问"给我一把斧子"→ Agent 用它确认 `axe` 是合法 prefab。 | 低（~40 行） |
| 6 | **chinese_name_lookup** | 输入中文名（如"牛"），返回对应的 prefab ID（`beefalo`） | [chinese_s.po](d:/Github项目/mod流水线/github同步/命名、参数记录/DST本体/chinese_s.po)（42 万行翻译文件）→ [prefablist.lua](d:/Github项目/mod流水线/github同步/命名、参数记录/DST本体/prefablist.lua) | 本质是两阶段 grep：在 .po 中搜中文词 → 提取英文 msgid → 在 prefablist 中匹配。用户说"帮我的牛驯化度+7"，Agent 需要知道"牛"→`beefalo`→`domesticatable`。 | 中（~80 行，需启发式匹配） |

**工具 4～6 都是 `grep_ly.py` 的垂直定制变体**——不扫描 4000 个 Lua 文件，只读已知的单个数据文件做解析。彼此独立，可以放在同一个文件 `src/tools/dst_data_ly.py` 中，共用 `Path.read_text()` 读文件。

### 建议实现顺序

```
1. read_file     ← grep 的最佳搭档，立即提升分析能力
2. list_files    ← 让 Agent 知道目录结构
3. tuning_lookup ← 数据源格式规整，代码量小
4. prefab_list   ← 同上
5. chinese_name_lookup ← 控制台指令第一阶段的关键依赖（中文需求 → prefab ID）
6. web_search    ← 需要选择搜索 API
```

---

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
