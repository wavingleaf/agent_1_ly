# 15 — uvicorn --reload + watchfiles 在 Windows 上关闭后不自启

**领域**：环境 · **触发条件**：Windows 11 + uvicorn 0.49.0 + watchfiles 1.2.0 + `--reload` 参数

---

## 问题现象

修改 `.py` 文件后，uvicorn 成功检测到变更、关闭旧进程，但新进程不 spawn。终端输出：

```
WARNING:  WatchFiles detected changes in 'src\agent\graph.py'. Reloading...
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [25056]
```

然后静默终止——没有报错、没有新进程、没有后续输出。

---

## 排查

1. `D:/Apps/Python/python.exe -c "from src.main import app"` → `OK` —— 语法和 import 无错误
2. uvicorn 0.49.0 已移除 `--reload-method` 参数（之前版本支持 `stat` / `watchfiles` 切换）
3. watchfiles 1.2.0 是唯一可用的 file watcher，无法切换
4. 同样的 uvicorn/watchfiles 组合在 macOS/Linux 上未出现此问题

结论：watchfiles 在 Windows 上的子进程 spawn 有 bug —— 父进程关闭后，`subprocess.Popen` 或 `os.spawn` 类调用静默失败。

---

## 修复

创建 `启动服务.py` 一键启动脚本，不使用 `--reload`：

```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
```

需要重启时 `Ctrl+C` 后重新运行脚本。VSCode 中右键"在终端中运行 Python 文件"即可。

（曾尝试 `--reload-delay 2.0`，无效；`--reload-method stat` 在该版本中不存在）

---

## 教训

1. **Windows 上不信任 `--reload`**。uvicorn/watchfiles 组合在 Windows 上的可靠性不如 Linux/macOS。本地开发用独立启动脚本 + 手动重启是更稳定的选择
2. **`Ctrl+C` 后重跑脚本只多一秒**。改动频率不高时，这比花时间排查 watchfiles bug 更高效
3. **`--reload` 只监听 `.py` 文件**。改 `.env` 后即使 reload 正常工作也不会自动重启，需要额外 touch `.py` 文件。用独立启动脚本可以规避这一点
