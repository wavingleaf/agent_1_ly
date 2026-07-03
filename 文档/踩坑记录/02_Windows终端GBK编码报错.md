# 02 — Windows 终端 GBK 编码报错

> 同类坑：RAG 项目 [04_Windows终端GBK编码报错](../../../../RAG项目/agent_RAG_1_ly/文档/踩坑记录/04_Windows终端GBK编码报错.md)

## 症状

- Python 脚本 `print()` 输出含中文或 emoji 的字符串时报错
- `UnicodeEncodeError: 'gbk' codec can't encode character '✅' in position 9: illegal multibyte sequence`
- 本项目中首次出现在验证导入的测试命令中（用了 `✅` emoji）

## 根因

Windows 中文版系统的终端默认编码是 GBK（CP936）。Python 的 `sys.stdout` 继承终端编码，遇到 GBK 编码表中不存在的字符（如 emoji）就崩溃。

但注意——**import 本身成功了**，只是 print 时崩溃。日志/显示逻辑有问题，核心功能没问题。

## 修复

在 `src/main.py` 顶部已加入：

```python
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

对于 notebook 或 ad-hoc 脚本，可以：

```bash
# 临时方案：这条命令切换到 UTF-8（每次开终端都要执行）
chcp 65001
```

或者直接避免在 `print()` 中用 emoji（用 `[OK]` 替代 `✅`）。

## 影响范围

- 直接用 Windows 命令提示符/PowerShell 运行的任何脚本
- 当前 main.py 已修复（有 `sys.stdout.reconfigure`），但 notebook 内 ad-hoc 测试仍然可能触发
