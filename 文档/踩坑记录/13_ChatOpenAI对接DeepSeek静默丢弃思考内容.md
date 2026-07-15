# 13 — ChatOpenAI 对接 DeepSeek 时静默丢弃 reasoning_content

**领域**：LLM 适配器 · **触发条件**：用 `ChatOpenAI(base_url="api.deepseek.com")` 对接 DeepSeek V4 模型

---

## 问题现象

三轮对比测试（2026-07-15）中发现：Round 1（ChatOpenAI）和 Round 2（ChatDeepSeek）跑的明明是同一个 `deepseek-v4-pro` 模型，但 Round 1 所有 `AIMessage.additional_kwargs` 中都没有 `reasoning_content`，而 Round 2 有。

进一步排查：**V4-Pro 默认就是思考模式**——服务端一直在产生推理内容，只是 Round 1 的适配器把它丢了。

---

## 根因

`langchain-openai` 的 `ChatOpenAI` 源码有明确声明（`chat_models/base.py:5-11`）：

> ChatOpenAI targets official OpenAI API specifications only. Non-standard response fields added by third-party providers (e.g., `reasoning_content`, `reasoning_details`) are **not** extracted or preserved.

`_convert_dict_to_message` 和 `_convert_delta_to_message_chunk` 只处理 OpenAI 官方字段，DeepSeek 专有的 `reasoning_content` 直接被跳过。

---

## 修复

替换为 `langchain-deepseek` 包中的 `ChatDeepSeek`。它继承 `ChatOpenAI`，但在三个关键位置做了覆盖：

| 方向 | 方法 | 做了什么 |
|------|------|------|
| 接收（非流式） | `_create_chat_result` | 从 `response.choices[0].message.reasoning_content` 提取 → `AIMessage.additional_kwargs["reasoning_content"]` |
| 接收（流式） | `_convert_chunk_to_generation_chunk` | 从 delta 的 `reasoning_content` 提取 → chunk 的 `additional_kwargs` |
| 发送（round-trip） | `_get_request_payload` | 依赖父类的 `_convert_message_to_dict`，实测 V4-Pro 接受无 reasoning_content 的 round-trip（不报 400） |

**附带坑**：`ChatDeepSeek` 的 `api_key` 从 `DEEPSEEK_API_KEY` 环境变量读取，`api_base` 从 `DEEPSEEK_API_BASE` 读取。项目用的是 `OPENAI_API_KEY` / `OPENAI_BASE_URL`，构造时需显式传入：

```python
ChatDeepSeek(
    model=settings.MODEL_NAME,
    api_key=settings.OPENAI_API_KEY,
    api_base=settings.OPENAI_BASE_URL,
)
```

---

## 教训

1. **不要用通用适配器对接有专有字段的 provider**。自己写 `@tool` 不用 LangChain 内置 `DuckDuckGoSearchResults` 的原则（#03 踩坑记录的教训 6 的延伸），同样适用 LLM 适配器：provider 专属包覆盖了非标准字段，通用包不会有
2. **"没报错" ≠ "没数据"**。V4-Pro 默认思考模式，`ChatOpenAI` 不报错只是扔了推理内容——你甚至不知道自己在丢东西。`pip show langchain-openai` 看一眼版本和包文档的 API scope 声明就能避免
