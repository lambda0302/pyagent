"""Desktop GUI layer: renderer, local HTTP+SSE server, launcher and frontend.

The GUI reuses all of ``core/`` and ``tools/`` unchanged.  It only adds a new
implementation of the renderer protocol (:class:`GUIRenderer`) that pushes
events to the browser over SSE and blocks on user decisions (permissions and
diff confirmations), resolved through small HTTP endpoints.
"""

from pyagent.gui.app import run_gui
from pyagent.gui.renderer import GUIRenderer, PendingRequest
from pyagent.gui.server import GuiServer

__all__ = ["GUIRenderer", "PendingRequest", "GuiServer", "run_gui"]
