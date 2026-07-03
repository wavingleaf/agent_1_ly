# 01 — Python PATH 冲突：Anaconda 3.7 覆盖 3.12

## 症状

- `python` 命令执行代码时，报 `ModuleNotFoundError: No module named 'pydantic_settings'` 等包缺失错误
- `python --version` 显示 `Python 3.7.0`，但已用 `pip install` 装好依赖
- import langgraph 时各种语法错误（LangGraph 使用的 `str | None` 等 Python 3.10+ 语法在 3.7 中不支持）

## 根因

**多个 Python 安装冲突。** 系统中同时存在：

| 路径 | 版本 | 来源 |
|------|------|------|
| `D:\Apps\Anaconda3\python.exe` | 3.7.0 | Anaconda（安装最早，PATH 最靠前） |
| `D:\Apps\Python\python.exe` | 3.12.6 | 独立安装（PATH 靠后或未加入） |
| `C:\Users\...\WindowsApps\python.exe` | 系统 | Windows App Store（PATH 中间） |

终端输入 `python` 时，系统按 PATH 顺序查找，命中 Anaconda 的 3.7。但 `pip` 命令安装到了 `D:\Apps\Python\` 的 3.12 site-packages。**安装的 Python 和运行的 Python 不是同一个。**

## 修复

在项目内始终使用完整路径：

```bash
# ❌ 不可靠
python -c "from src.agent.graph import graph"

# ✅ 可靠
"d:/Apps/Python/python" -c "from src.agent.graph import graph"
```

更根本的方案：用虚拟环境隔离。

```bash
"d:/Apps/Python/python" -m venv .venv
# Windows 激活
.venv\Scripts\activate
# 现在 python 和 pip 都指向项目本地 3.12
```

## 影响范围

- **所有** `python`/`pip` 命令——只要不写完整路径或不用 venv，就会用错版本
- 本项目的 notebook 也需要注意 kernel 选择（VS Code 中默认可能选 Anaconda 3.7）
- CI/定时任务如果用 `python` 短命令，同样会踩坑

## 检测方法

```bash
# 快速确认当前 python 版本和路径
python --version && python -c "import sys; print(sys.executable)"
```
