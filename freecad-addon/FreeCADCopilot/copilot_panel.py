"""
FreeCAD AI Copilot — copilot_panel.py

Dockable PySide2 chat panel.  Sends natural-language prompts to
LM Studio, receives a Python script, and executes it live inside
FreeCAD's own Python interpreter so the 3D viewport updates
immediately — no file-save / watcher loop needed.
"""

import html
import os

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtGui, QtWidgets

from agent_core import extract_code, get_completion

# ── Stylesheet ─────────────────────────────────────────────────────────────────
_STYLE = """
QDockWidget::title {
    background: #2d2d2d;
    padding: 4px;
    font-weight: bold;
}
QWidget#copilot_root {
    background: #1e1e1e;
}
QTextEdit {
    background: #1e1e1e;
    color: #d4d4d4;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
    border: none;
    padding: 4px;
}
QPlainTextEdit {
    background: #252526;
    color: #d4d4d4;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 6px;
}
QPushButton#send_btn {
    background: #0e639c;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#send_btn:hover  { background: #1177bb; }
QPushButton#send_btn:disabled { background: #3c3c3c; color: #666; }
QPushButton#clear_btn {
    background: #3c3c3c;
    color: #ccc;
    border: none;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
}
QPushButton#clear_btn:hover { background: #505050; }
QLabel#status_label {
    color: #888;
    font-size: 11px;
    font-style: italic;
}
"""


# ── Worker thread ──────────────────────────────────────────────────────────────

class _Worker(QtCore.QThread):
    """Calls LM Studio off the main thread so the UI stays responsive."""

    result = QtCore.Signal(str)   # raw model reply
    error  = QtCore.Signal(str)   # error message string

    def __init__(self, history: list, parent=None):
        super().__init__(parent)
        self._history = history

    def run(self):
        try:
            reply = get_completion(self._history)
            self.result.emit(reply)
        except Exception as exc:
            self.error.emit(str(exc))


# ── Dock widget ────────────────────────────────────────────────────────────────

class CopilotDock(QtWidgets.QDockWidget):

    def __init__(self, parent=None):
        super().__init__("✦ AI Copilot", parent)
        self.setObjectName("FreeCADAICopilot")
        self.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea |
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setMinimumWidth(320)

        self._history: list = []
        self._worker: _Worker | None = None

        self._build_ui()
        self.setStyleSheet(_STYLE)
        self._append("system",
                      "AI Copilot connected to LM Studio.<br>"
                      "Describe the part you want. I may ask targeted design "
                      "questions before generating CAD.")

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QtWidgets.QWidget()
        root.setObjectName("copilot_root")
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Chat history display
        self._chat = QtWidgets.QTextEdit()
        self._chat.setReadOnly(True)
        layout.addWidget(self._chat, stretch=1)

        # Status / top controls row
        ctrl_row = QtWidgets.QHBoxLayout()
        self._status = QtWidgets.QLabel("Ready")
        self._status.setObjectName("status_label")
        ctrl_row.addWidget(self._status)
        ctrl_row.addStretch()
        clr = QtWidgets.QPushButton("Clear")
        clr.setObjectName("clear_btn")
        clr.setFixedWidth(55)
        clr.clicked.connect(self._on_clear)
        ctrl_row.addWidget(clr)
        layout.addLayout(ctrl_row)

        # Prompt input
        self._input = QtWidgets.QPlainTextEdit()
        self._input.setPlaceholderText(
            "Describe your part, constraints, or change...  (Ctrl+Enter to send)"
        )
        self._input.setFixedHeight(80)
        self._input.installEventFilter(self)
        layout.addWidget(self._input)

        # Send button
        self._send_btn = QtWidgets.QPushButton("Send  ▶")
        self._send_btn.setObjectName("send_btn")
        self._send_btn.clicked.connect(self._on_send)
        layout.addWidget(self._send_btn)

        self.setWidget(root)

    def eventFilter(self, obj, event):
        """Ctrl+Enter in the input box → send."""
        if (obj is self._input
                and event.type() == QtCore.QEvent.Type.KeyPress
                and event.key() == QtCore.Qt.Key.Key_Return
                and event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier):
            self._on_send()
            return True
        return super().eventFilter(obj, event)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_send(self):
        prompt = self._input.toPlainText().strip()
        if not prompt or self._worker is not None:
            return

        self._input.clear()
        self._append("user", prompt)
        self._history.append({"role": "user", "content": prompt})

        self._set_busy(True)

        self._worker = _Worker(list(self._history), self)
        self._worker.result.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.result.connect(lambda _: self._set_busy(False))
        self._worker.error.connect(lambda _: self._set_busy(False))
        self._worker.start()

    def _on_result(self, reply: str):
        code = extract_code(reply)
        self._history.append({"role": "assistant", "content": reply})
        self._worker = None

        if code:
            # Show a condensed preview (first 8 lines) then run it
            preview = "\n".join(code.splitlines()[:8])
            if len(code.splitlines()) > 8:
                preview += "\n..."
            self._append("assistant", f"<pre>{html.escape(preview)}</pre>")
            self._run_code(code)
        else:
            # Model replied with prose — show it as-is
            self._append("assistant", html.escape(reply))

    def _on_error(self, msg: str):
        self._worker = None
        self._append("error", f"LM Studio error: {html.escape(msg)}<br>"
                               "Is LM Studio running on port 1234?")

    def _on_clear(self):
        self._history.clear()
        self._chat.clear()
        self._append("system", "History cleared.")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        self._send_btn.setEnabled(not busy)
        self._send_btn.setText("Planning..." if busy else "Send  ▶")
        self._status.setText("Checking design readiness..." if busy else "Ready")

    def _append(self, role: str, text: str):
        palette = {
            "user":      ("#4fc1ff", "You"),
            "assistant": ("#4ec9b0", "Copilot"),
            "error":     ("#f44747", "Error"),
            "system":    ("#888888", "System"),
        }
        colour, label = palette.get(role, ("#d4d4d4", role))
        self._chat.append(
            f'<p style="margin:4px 0">'
            f'<b style="color:{colour}">{label}:</b>&nbsp;'
            f'<span style="color:#d4d4d4">{text}</span></p>'
        )
        # Auto-scroll to bottom
        sb = self._chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _run_code(self, code: str):
        """Execute the generated script live inside FreeCAD."""
        # Build a minimal globals dict so the script's imports resolve
        # against FreeCAD's already-loaded modules.
        import sys
        g = {
            "__builtins__": __builtins__,
            "FreeCAD":      FreeCAD,
            "FreeCADGui":   FreeCADGui,
        }
        for mod in ("Part", "Sketcher", "Draft", "Arch"):
            if mod in sys.modules:
                g[mod] = sys.modules[mod]

        try:
            exec(compile(code, "<copilot>", "exec"), g)  # noqa: S102
            FreeCADGui.updateGui()
            self._append("system", "✓ Executed — viewport updated.")
        except Exception as exc:
            self._append("error", f"Execution failed:<br><pre>{html.escape(str(exc))}</pre>")
