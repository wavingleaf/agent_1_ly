"""
一键启动 Agent 服务

用法：在 VSCode 中右键 → "在终端中运行 Python 文件"，或：
    D:/Apps/Python/python.exe 启动服务_ly.py

不带 --reload（uvicorn + watchfiles 在 Windows 下有时不重启）。
需要重启时 Ctrl+C 后重新运行本脚本即可。
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
