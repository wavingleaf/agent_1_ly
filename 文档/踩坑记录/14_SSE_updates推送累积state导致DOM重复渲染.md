# 14 — SSE updates 模式推送累积 state 导致 DOM 重复渲染

**领域**：LangGraph + 前端 · **触发条件**：在 SSE `stream_mode="updates"` 事件处理中向 DOM 追加非消息气泡类元素（如思考卡片），不做去重

---

## 问题现象

v0.4.0 开发中，前端在聊天区新增了"🧠 思考"折叠卡片。SSE 实时流中，前三个卡片正常显示，第四个开始被 flex 布局压缩为一条横线，无法展开。

---

## 根因

LangGraph 的 `stream_mode="updates"` **每次 superstep 推送的是完整的累计 state**，而非仅本轮新增的消息。例如：

```
Step 1: agent 节点完成 → updates.messages = [Human, AI(tool_calls)]
Step 2: tools 节点完成 → updates.messages = [Human, AI(tool_calls), ToolMessage]
Step 3: agent 节点完成 → updates.messages = [Human, AI(tool_calls), ToolMessage, AI(content)]
```

`processEvent` 每次收到 `updates` 都遍历全部消息，发现 `msg.reasoning_content` 存在就调用 `addThinkingBlock()`。同一段推理内容（如 `"用户想搜索 AXE_DAMAGE..."` ）在多个 `updates` 事件中重复出现，导致 DOM 中插入了 4-5 份相同的 `<details>` 元素。

`#messages` 是 `display:flex; flex-direction:column`，多个重复的思考块累积到 flex 容器的可用空间上限后，后续元素被挤压——表现就是逐步变窄，最终塌陷为一条线。

---

## 修复

用 `Set` 按 `reasoning_content` 内容去重：

```javascript
// send() 中初始化
renderedReasonings = new Set();

// processEvent 中
if (msg.reasoning_content && !renderedReasonings.has(msg.reasoning_content)) {
    renderedReasonings.add(msg.reasoning_content);
    addThinkingBlock(msg.reasoning_content, msg.usage_metadata);
}
```

CSS 侧也加了 `flex-shrink: 0` + `min-height: 44px` 作为防御（即使未来去重逻辑有 bug，也不会塌成线）。

---

## 教训

1. **SSE updates 是累积的，不是增量的**。任何基于 `updates` 的消息处理必须有去重逻辑——同一份数据会出现在多个事件中
2. **有状态渲染用 Set/Map，无状态渲染（纯展示）不受影响**。消息气泡由 `addMsg` 创建，LangGraph 的 checkpoint 每次恢复时重建 DOM 是从零开始的，不涉及去重。但思考块、进度条、统计数字这类"追加式"渲染，必须去重
3. **Flex 容器 + `overflow:hidden` + 无 `flex-shrink:0` = 随时可能塌缩**。给任何"不应被压缩"的子元素加 `flex-shrink: 0` 是低成本防御
