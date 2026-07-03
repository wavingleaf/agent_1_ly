---
name: 加急TODO
description: README 核对过程中发现的与代码现状冲突、需尽快处理的事项，不包括新功能
metadata:
  type: project
---

# 加急 TODO

> 来源：2026-07-04 grill-with-docs 核对 README 时发现。
> 状态：✅ 全部完成（2026-07-04）。

---

## ✅ 1. 设计决策.md — 3 条 ADR 已过时

- [x] 决策 3/4/5/9 → 总览表标注 ~~已废弃~~，正文移入"历史决策"附录
- [x] 决策 7 → 补充现状：当前 MemorySaver，AsyncSqliteSaver 列入改进 #2
- [x] ADR 1 结论段落 → 去掉 create_agent() + Middleware 引用
- [x] ADR 10 src 树 → 移除 middleware 残留

---

## ✅ 2. middleware.py — 死代码

- [x] 已删除 `src/agent/middleware.py`
- [x] README 目录树已移除其引用（已提前完成）

---

## ✅ 3. 踩坑记录过时

- [x] 04 从 🟢"已避免" → ⚪"已废弃"，README 索引同步
- [x] 坑列表底部新增"历史记录"区 |

---

## ✅ 4. notebook 03 与代码现状不一致

- [x] 已在 notebook 顶部插入废弃标注（markdown cell）

---

## ✅ 5. 设计决策.md 路径引用

- [x] 2 处 RAG 项目引用均为跨项目描述性引用，不存在本仓库内的断裂链接，无需修改
