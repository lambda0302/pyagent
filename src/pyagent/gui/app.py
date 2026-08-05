"""桌面 GUI 启动器：启动本地服务并打开窗口。

使用 ``pywebview`` 打开原生窗口（Windows 上用 WebView2）。当给定 ``--browser``、
设置环境变量 ``PYAGENT_GUI_BROWSER=1``、或 pywebview 未安装时，回退为用默认
浏览器打开。
"""

from __future__ import annotations

import threading
import time
import webbrowser
from pathlib import Path

from pyagent.config import Config
from pyagent.gui.server import GuiServer


def run_gui(
    config: Config,
    session_dir: Path,
    cwd: Path,
    use_browser: bool = False,
    port: int = 0,
) -> int:
    """提供 GUI 服务并阻塞，直到窗口关闭（浏览器模式下直到 Ctrl+C）。"""
    server = GuiServer(config, session_dir, cwd, port=port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.port}"

    if use_browser or not _webview_available():
        webbrowser.open(url)
        print(f"pyagent GUI: open {url}  (Ctrl+C to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        import webview

        webview.create_window("pyagent", url, min_size=(900, 620))
        webview.start()  # 在主线程驱动原生窗口

    server.shutdown()
    return 0


def _webview_available() -> bool:
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True
