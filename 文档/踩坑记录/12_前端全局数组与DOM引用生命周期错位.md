# 12 — 前端全局数组的生命周期与 DOM 引用的归属关系错位

**领域**：前端架构 · **触发条件**：全局数组每次操作清空重建，DOM 元素上存储索引引用

---

## 问题现象

点击用户气泡查看该消息触发的 agent 行为时，始终显示最新一条消息的步骤。即使点击的是第 1 条消息，右侧面板也显示第 3 条消息的工具调用链。

---

## 根因

全局 `steps` 数组的生命周期与 DOM 引用不匹配：

```
发送消息 1 时：
  steps = [input_1, agent, tool, agent_final, done]    ← steps 长度 = 5
  气泡 1._stepStart = 0    ← "我的步骤从索引 0 开始"

发送消息 2 时：
  steps = []    ← ❌ send() 清空了 steps
  steps = [input_2, agent, tool, agent_final, done]    ← steps 长度 = 5，但索引
                                                          区间和消息 1 相同

点击气泡 1 → selectUserMessage 从 steps[0] 开始遍历 → 但 steps[0] 现在是消息 2 的内容
```

**核心矛盾**：DOM 上存储的索引引用了一个会随时间变化的全局数组。索引本身正确，但索引指向的数据被后续操作覆盖了。

---

## 修复

**不给 DOM 存储索引，给它存储数据副本**：

```javascript
// ❌ 错误：存索引——全局数组被清空后索引指向错误数据
humanBubble._stepStart = steps.length;

// ✅ 正确：存数据快照——不受后续 send() 的影响
function onDone(aiBubble) {
    // ... 处理流结束 ...
    if (aiBubble._humanBubble) {
        aiBubble._humanBubble._ownSteps = steps.slice();  // 浅拷贝足够——step 对象不会被修改
    }
}

function selectUserMessage(bubble) {
    var ownedSteps = bubble._ownSteps;  // 直接从 DOM 读取，不走全局数组
    // ...
}
```

点击气泡时直接读 `bubble._ownSteps`，不碰全局 `steps`。每条消息有自己完全独立的步骤快照。

---

## 教训

- **DOM 上存引用（索引/ID）的前提是引用的目标集合只增不减**。如果目标集合会被清空（`steps = []`），引用的有效性就消失了
- **DOM 上存数据副本比存引用更安全**——代价是内存翻倍（每条消息的 steps 独立存储），但对于 UI 事件绑定场景，这种隔离是值得的
- 这是一个通用的模式：`列表被反复清空重建 + DOM 需要记住元素在某时刻的列表状态` → 存快照，不存索引
- `slice()` 浅拷贝在这里是安全的——step 对象创建后不会被修改，不需要深拷贝
