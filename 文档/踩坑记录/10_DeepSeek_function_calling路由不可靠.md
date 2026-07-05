# 10 — DeepSeek function calling 路由不可靠，工具描述写了"不要调用"仍误调

**领域**：LLM 行为 · **触发条件**：DeepSeek-chat 模型 + 多个工具的 function calling 场景

---

## 问题现象

用户问"帮我查 DST 源码中 SetDomestication 函数在哪定义"，Agent 应调用 grep 搜索源码，但实际调用了 `get_current_time`。即使：

1. 工具 docstring 中明确写了"**不要在其他场景下调用**——如果不是明确问时间，说明用户需要的是其他工具"
2. System Prompt 中写了完整路由规则，包括"问源码用 grep，问时间用 get_current_time"

DeepSeek 仍然偶尔误调时间工具。

---

## 根因

不同模型对 function calling 的信号来源权重不同：

| 模型 | System Prompt 权重 | 工具 Docstring 权重 |
|------|:---:|:---:|
| GPT-4 / Claude | 🔴 高（认真读) | 🟡 中 |
| DeepSeek-chat | 🟡 中→低 | 🔴 高（主要看 schema） |

DeepSeek 的 RLHF 训练更侧重 function calling schema 而非 system message。即使工具描述和 system prompt 都给出了限制，它仍可能基于 schema 的"语义相似度"选错工具。

---

## 修复

**从工具列表中直接移除**——不是靠 prompt 约束，而是靠工具可见性控制。

```python
# DST 模式不暴露 get_current_time
DST_TOOLS = [calculator, grep]  # ← 没有 get_current_time
MODE_TOOLS = {
    "dst": DST_TOOLS,
    "general": ALL_TOOLS,  # ← 三个工具都在
}
```

模型看不到这个工具，就不存在误调的路径。这与 Claude Code 的模式设计一致——**模式控制工具的可见性，而非仅靠 prompt 指令**。prompt 约束是软性的，工具列表是硬性的。Defense in Depth 原则：两层都应该有，但当软约束失效时，硬约束兜底。

---

## 教训

- system prompt 和工具描述都要写好（双管齐下），但不能依赖它们在所有模型上都生效
- 工具列表移除是最可靠的"该工具不可用"的保证——这不受模型遵循度影响
- 用户可切换模式来获得不同的工具集——通用模式保留所有工具，DST 模式精简
- 这个问题不限于 DeepSeek——所有 function calling 模型都有概率性路由错误，只是概率不同
