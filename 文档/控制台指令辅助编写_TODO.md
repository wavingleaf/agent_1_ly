---
name: 控制台指令辅助编写
description: Agent 高级功能 TODO：辅助编写 DST 控制台指令，通过 grep 精确检索源码，处理需求模糊、不完整、不正确的场景
metadata:
  type: project
---

# Agent 高级功能 TODO：DST 控制台指令辅助编写

> **设计决策**：grep 精确检索优于 RAG 的理由、LLM 候选→grep 验证的循环模型、
> 三种风险评估，详见 [设计决策.md](设计决策.md) 决策 11。

## 已完成 ✅

| # | 项目 | 完成日期 | 文件 |
|---|------|---------|------|
| 1 | SSE 断连后取消 Agent 任务（`asyncio.Task.cancel()`） | 2026-07-05 | [src/main.py](../src/main.py) |
| 2 | AsyncSqliteSaver 持久化长期记忆 | 2026-07-05 | [src/memory/store.py](../src/memory/store.py) |
| 3 | grep 工具（递归搜索 .lua 文件，支持 subdir 限定子目录） | 2026-07-05 | [src/tools/grep_ly.py](../src/tools/grep_ly.py) |
| 4 | 模式系统（dst / general / plan） | 2026-07-05 | [src/agent/graph.py](../src/agent/graph.py) |
| 5 | 对话线程管理 + 前端 Markdown 渲染 | 2026-07-05 | [debug_ui.html](../debug_ui.html) |
| 6 | read_file 工具（读取文件 + 行范围截断） | 2026-07-06 | [src/tools/read_file_ly.py](../src/tools/read_file_ly.py) |
| 7 | list_files 工具（浏览目录结构） | 2026-07-06 | [src/tools/list_files_ly.py](../src/tools/list_files_ly.py) |
| 8 | web_search 工具（DuckDuckGo 联网搜索，支持 DDG_PROXY 代理） | 2026-07-06 | [src/tools/web_search_ly.py](../src/tools/web_search_ly.py) |
| 9 | `InjectedToolArg` 改造（grep/read_file/list_files 签名注入 `source_dir`） | 2026-07-06 | [src/tools/](../src/tools/) |
| 10 | 模型切换：`deepseek-chat` → `deepseek-v4-pro` | 2026-07-06 | [.env](../.env) |
| 11 | `DST_META_DIR` 配置（settings.py / .env / .env.example） | 2026-07-06 | [src/config/settings.py](../src/config/settings.py) |
| 12 | grep `subdir` 参数（支持限定子目录搜索范围） | 2026-07-06 | [src/tools/grep_ly.py](../src/tools/grep_ly.py) |
| 13 | web_search DDG_PROXY 代理 + 指数退避重试 | 2026-07-06 | [src/tools/web_search_ly.py](../src/tools/web_search_ly.py) |
| 14 | AI 气泡实时渲染修复（_placeholder 置位时机） | 2026-07-06 | [debug_ui.html](../debug_ui.html) |
| 15 | 对话导出/导入（单线程 JSON 文件） | 2026-07-06 | [src/main.py](../src/main.py), [debug_ui.html](../debug_ui.html) |

---

## 待完成（按优先级排序）

### 🟡 P1 — 工具增强

#### 1. 工具 docstring 互斥化

- **目标**：DeepSeek 对工具 Schema 做字面解析，`grep` vs `read_file` vs `list_files` 的描述中
  都出现了"函数/组件/源码"，LLM 可能选错。改为用"你当前知道什么"来区分：
  - `grep`：不知道文件在哪 → 用关键词搜索
  - `read_file`：已知文件路径 → 打开阅读内容
  - `list_files`：已知目录名 → 浏览列表
- **改动量**：每个工具的 docstring ~5 行
- **涉及文件**：`src/tools/grep_ly.py`、`src/tools/read_file_ly.py`、`src/tools/list_files_ly.py`

#### 2. `dst_data_lookup` 工具

- **目标**：将原本计划中的 `tuning_lookup` + `prefab_list` + `chinese_name_lookup` 三个工具
  **合并为一个**，避免工具数量膨胀导致 DeepSeek 路由精度下降（见下方工具数量分析）。
- **签名**：
  ```python
  @tool
  def dst_data_lookup(pattern: str, category: str = "auto") -> str:
  ```
  - `pattern`：子串匹配（与 grep 一致，暂不用正则）
  - `category`：`"tuning"` / `"prefab"` / `"chinese"` / `"auto"`（默认，自动判断）

- **三个数据源及其路径**：
  | 数据源 | 路径（相对于 `mod流水线/` 目录） | 解析方式 |
  |--------|------|---------|
  | `tuning.lua` | `github同步/命名、参数记录/DST本体/tuning.lua` | 逐行正则匹配 `KEY = value,` |
  | `prefablist.lua` | `github同步/命名、参数记录/DST本体/prefablist.lua` | 正则提取数组元素 |
  | `chinese_s.po` | `github同步/命名、参数记录/DST本体/chinese_s.po` | 正则匹配完整条目块（详见下方） |

  **注意**：这三个数据源不在 `DST_SOURCE_DIR` 下。已新增 `DST_META_DIR` 配置
  （2026-07-06），`.env` / `settings.py` / `.env.example` 均已就位。实现时用 `Annotated[str, InjectedToolArg]`
  注入，与 grep/read_file/list_files 的 `source_dir` 模式一致。

- **`chinese_s.po` 正则解析方案**：

  `.po` 文件中一个物品名称条目的结构：
  ```
  msgctxt "STRINGS.NAMES.BEEFALO"
  msgid "Beefalo"
  msgstr "牛"
  ```

  物品描述条目结构：
  ```
  msgctxt "STRINGS.CHARACTERS.WILSON.DESCRIBE.BEEFALO"
  msgid "It's a beefalo."
  msgstr "这是一头牛。"
  ```

  关键发现：**`msgctxt` 行本身就编码了条目类型**，不需要"匹配前三行"这类脆弱的相对偏移。

  ```python
  # 匹配完整条目块：msgctxt + msgid + msgstr 三行一组
  _ENTRY_PATTERN = re.compile(
      r'^msgctxt "(STRINGS\..*?\.(\w+))"\n'
      r'^msgid "([^"]*)"\n'
      r'^msgstr "([^"]*)"',
      re.MULTILINE
  )
  # → 返回 [(msgctxt, prefab_id, msgid, msgstr), ...]

  # category="chinese" 时，在 msgstr 中搜 pattern，
  # 只返回 msgctxt 含 "STRINGS.NAMES." 的条目（物品名称），
  # 过滤掉含 "DESCRIBE" 的（物品描述）和其他类型。
  ```

  这样做的好处：不需要交叉验证 `prefablist.lua`（msgctxt 中的 `.NAMES.xxx` 已经是 prefab ID），
  一道正则同时完成解析和类型过滤。

- **实现复杂度**：~120 行（`src/tools/dst_data_lookup_ly.py`）
- **预计改动量**：0 行（不增加工具数，替代 3 个计划工具的位置）

#### 3. 工具数量 A/B 测试

- **背景**：实测数据显示 DeepSeek V3 在 6 工具时路由准确率约 68%。
  V4-Pro 更聪明但没有独立的路由精度基准。需要在真实场景下测试。
- **方法**：DST 模式分别测试 4 工具（核心集）和 6 工具（完整集），
  各发 20 条 DST 相关查询，统计选错工具的次数。
- **时机**：`dst_data_lookup` 实现完毕后做
- **4 工具核心集**：grep + read_file + calculator + dst_data_lookup
  （去掉 list_files 和 web_search，它们的使用场景是兜底，在 general 模式下可用）

---

### 🟠 P2 — 核心功能链路

#### 4. 混合模式 StateGraph + Agent 子图

- 外层手写 StateGraph 做编排（意图分类、校验），内层 `create_agent()` 子图做工具调用循环
- 在控制台指令辅助第一阶段实现时按需评估
- 预计改动量：~50 行

#### 5. web_search 质量验证

- 测试 DuckDuckGo 后端对 DST 相关查询的搜索结果质量（Wiki、Klei 论坛覆盖率）
- **已解决**：DDG_PROXY 代理链路已打通（2026-07-06），不再有连接超时问题
- **剩余问题**：DuckDuckGo 对长查询匹配差、搜索结果噪音大（不是代码 bug，是搜索引擎局限）
- 如果后续质量无法满足需求，备选 Brave Search（需免费 API key）

---

### ⚪ P3 — 远期功能（控制台指令辅助三阶段）

#### 第一阶段：grep 驱动链路

- Agent 接收自然语言需求 → LLM 推理候选搜索词 → grep 验证 → read_file 读源码 → 拼装命令
- 前置依赖：P0 和 P1 全部完成

#### 第二阶段：歧义检测与确认

- 识别模糊指代（"我的""最近的""那个"）→ 主动向用户提问确认 → 给出多个可选方案

#### 第三阶段：代码级操作自动化

- 自动拼装合法的 Lua 表达式 → 检查命令安全性（只读 vs 修改）

---

## 核心困境

### 困境 1：需求不明确

用户说"帮我把我的牛驯化度+7"，但实际需求是：
- 选取距离玩家最近的一只牛（`GetClosestInst(ThePlayer, "beefalo")`）
- 判断它是否正在被驯化（检查 `components.domesticatable` 是否存在）
- 获取当前驯化度值，加 7 后设为新值

### 困境 2：需求可能不正确

"我的牛"是个模糊概念。DST 中没有"属于某玩家的牛"。"我的" = "正在驯化中"还是"离我最近"？

### 困境 3：需要精准代码查询

Agent 需要：LLM 推理关键符号 → grep 精确搜索 → read_file 阅读上下文 → 拼装命令。

---

## 参考

- 需求模糊处理：采用"先定位术语、再精确检索"的两阶段策略
- 代码查询：依赖「本地的DST源码文件」
- grep 工具：Windows 下可用 `rg`（ripgrep）或 Python 内建子串匹配
