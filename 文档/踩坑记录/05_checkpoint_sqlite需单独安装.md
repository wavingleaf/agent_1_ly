# 05 — langgraph-checkpoint-sqlite 需单独安装

## 症状

```python
from langgraph.checkpoint.sqlite import SqliteSaver
# ModuleNotFoundError: No module named 'langgraph.checkpoint.sqlite'
```

但 `pip list` 显示 `langgraph 1.2.6` 已安装。

## 根因

LangGraph 核心包不包含 SQLite checkpointer。`langgraph.checkpoint` 目录下只有 `memory`（内置）和 `base`（抽象类）。SQLite 和 Postgres 的 checkpointer 是**独立的 pip 包**：

| 功能 | pip 包名 | import 路径 |
|------|---------|------------|
| 内存（内置） | `langgraph` | `langgraph.checkpoint.memory` |
| SQLite | `langgraph-checkpoint-sqlite` | `langgraph.checkpoint.sqlite` |
| Postgres | `langgraph-checkpoint-postgres` | `langgraph.checkpoint.postgres` |

安装 `langgraph` 时不会自动安装这些扩展。

## 修复

```bash
pip install langgraph-checkpoint-sqlite
```

已在 `requirements.txt` 中明确声明此依赖，避免遗漏。

## 为什么这么设计

LangGraph 团队把各数据库后端的 checkpointer 拆成独立包，是为了：
1. 减小核心包的体积（不需要 SQLite 的人不用装它）
2. 各后端可独立发版（`langgraph-checkpoint-sqlite` 更新不影响 `langgraph` 的稳定性）

代价就是初次安装时容易遗漏——`ModuleNotFoundError` 的报错信息很明确（哪个模块找不到），但容易误以为是安装问题而非包分拆问题。

## 检测方法

```bash
pip list | grep langgraph
# 预期输出（4 个包）：
# langgraph
# langgraph-checkpoint
# langgraph-checkpoint-sqlite  ← 这个必须有
# langgraph-prebuilt
```
