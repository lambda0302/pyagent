"""Desktop GUI launcher: start the local server and open the window.

Uses ``pywebview`` for a native window (WebView2 on Windows).  Falls back to
opening the default browser when ``--browser`` is given, when the env var
``PYAGENT_GUI_BROWSER=1`` is set, or when pywebview is not installed.
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
    """Serve the GUI and block until the window closes (or Ctrl+C in browser mode)."""
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
        webview.start()  # drives the native window on the main thread

    server.shutdown()
    return 0


def _webview_available() -> bool:
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    return True
