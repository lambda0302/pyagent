"""桌面 GUI 层：渲染器、本地 HTTP+SSE 服务、启动器与前端。

GUI 原样复用全部 ``core/`` 与 ``tools/``。它只新增一个渲染器协议的新实现
(:class:`GUIRenderer`)：把事件通过 SSE 推给浏览器，并阻塞等待用户的决定
（权限与 diff 确认），由几个小 HTTP 端点解除阻塞。
"""

from pyagent.gui.app import run_gui
from pyagent.gui.renderer import GUIRenderer, PendingRequest
from pyagent.gui.server import GuiServer

__all__ = ["GUIRenderer", "PendingRequest", "GuiServer", "run_gui"]
