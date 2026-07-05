# 09 — SSE stream_mode["updates","messages"] 混入 ToolMessage 导致聊天窗显示工具结果

**领域**：LangGraph astream + 前端 · **触发条件**：使用 `stream_mode=["updates", "messages"]` 时

---

## 问题现象

AI 回答气泡中出现 grep 的原始输出文本：

```
在 3982 个 Lua 文件中搜索 'SetDomestication'，找到 2 条匹配：
━━━ components\domesticatable.lua:48 ━━━
▶  48 | function Domesticatable:SetDomesticationTrigger(fn)
```

这不是 LLM 生成的回答——是工具返回的原始结果混进了 AI 气泡的 `streamedContent` 中。

---

## 根因

`graph.astream(stream_mode=["updates", "messages"])` 的 **messages** 模式会推送**所有**消息类型的 chunk，包括：
- `AIMessageChunk`（LLM 逐 token 输出）← 应该渲染到 AI 气泡
- `ToolMessage`（工具返回结果）← **不应该**渲染到 AI 气泡，但代码没过滤

原代码：

```javascript
// ❌ 错误：所有 chunk 的 content 都拼入 AI 气泡
if (mode === 'messages') {
    const m = payload[0];
    streamedContent += (m && m.content) || '';
    aiBubble.querySelector('.content').textContent = streamedContent;
}
```

---

## 修复

只将 `type === 'ai'` 或 `type === 'AIMessageChunk'` 的 chunk 拼入 AI 气泡：

```javascript
// ✅ 正确：过滤掉 ToolMessage 的 chunk
if (mode === 'messages') {
    const m = payload[0];
    const isAIChunk = m && (m.type === 'ai' || m.type === 'AIMessageChunk');
    if (isAIChunk && m.content) {
        streamedContent += m.content;
        aiBubble.querySelector('.content').innerHTML = renderMd(streamedContent);
    }
}
```

**重要**：`updates` 模式不受影响——它的 payload 中已经按 `role` 字段区分了 `ai` / `tool` 类型，前端在 `processEvent` 中分别渲染。只有 `messages` 模式需要手动过滤。

---

## 教训

- `stream_mode=["updates", "messages"]` 是两个独立的数据流，各有各的消息类型分布
- `messages` 模式的 payload 是原始 LangChain 消息对象，需要检查 `type` 字段判断来源
- 一开始只关注了 `updates` 模式的渲染逻辑，忽略了 `messages` 模式也在写入同一个 `streamedContent` 变量
