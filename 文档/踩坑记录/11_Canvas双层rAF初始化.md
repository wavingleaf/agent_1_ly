# 11 — Canvas 初始化时 CSS Flex 布局未完成，clientHeight=0 导致不渲染

**领域**：前端 Canvas · **触发条件**：`<script>` 底部直接调用 `redraw()`，Canvas 依赖容器尺寸

---

## 问题现象

StateGraph 节点流转图的 Canvas 在页面加载后一片空白，无任何报错。拖拽窗口改变大小后 Canvas 正常显示——说明渲染逻辑本身没问题，只是首次绘制失败。

---

## 根因

`<script>` 标签中直接调用 `redraw()` 时，CSS Flex 布局尚未计算完毕。Canvas 的父容器 `<div id="graph-canvas-wrap">` 的 `clientHeight` 仍为 0，`layoutCanvas()` 检测到 `W < 10 || H < 10` 后直接 `return`，不绘制。

浏览器渲染管线顺序：

```
HTML 解析 → CSSOM 构建 → 布局（layout）→ 绘制（paint）
                              ↑
                        redraw() 在这一步之前被调用了
```

`window.onload` 和 `DOMContentLoaded` 只保证 DOM 解析完成，**不保证** CSS Flex 布局的尺寸计算完成。Flex 容器的高度计算是异步的。

---

## 修复

用双层 `requestAnimationFrame` 延迟首次绘制：

```javascript
// ❌ 错误：CSS Flex 布局未完成，clientHeight=0
redraw();

// ✅ 正确：双层 rAF 确保浏览器的布局/绘制管线至少执行了一帧
requestAnimationFrame(() => requestAnimationFrame(() => redraw()));
```

- 第一层 `rAF`：排队在下一帧开始前执行
- 第二层 `rAF`：排队在再下一帧开始前执行——此时首帧的布局计算已确定完成

原代码中已有的 `setTimeout(redraw, 200)` 和 `ResizeObserver` 是后备方案，但不能保证首次渲染——如果 200ms 内用户没有触发 resize，首次绘制仍然失败。

---

## 教训

- Canvas 控件**永远**不要假设在 script 执行时 DOM 尺寸已知——Flex/Grid 布局是异步的
- `clientHeight` 为 0 时静默返回是正确的（防止 NaN 坐标），但要保证调用时机在布局完成后
- 双层 `rAF` 是处理此问题的标准模式（MDN 推荐），比 `setTimeout` 更可靠
- `window resize` 事件和 `ResizeObserver` 是后备，不能替代正确的初始化时序
