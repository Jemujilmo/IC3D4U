"""
FreeCAD Auto-Execute Watcher — AI Agent Integration
====================================================
Run this macro ONCE after opening FreeCAD:
    Macro menu → Macros → watcher → Execute

It monitors generated_part.FCMacro and automatically re-executes it
whenever the AI agent saves a new or updated part. The previous document
is closed first so you never accumulate stale tabs.

To stop:  restart FreeCAD, or run in the Python Console:
    del FreeCAD._agent_watcher
"""

import os
from pathlib import Path

try:
    from PySide6 import QtCore
except ImportError:
    from PySide2 import QtCore

WATCH_FILE = (
    Path(os.environ.get("APPDATA", "")) / "FreeCAD" / "v1-1" / "Macro" / "generated_part.FCMacro"
)

# The generated scripts always create a document with this label.
# The watcher closes it before re-running so tabs don't accumulate.
AGENT_DOC_NAME = "AIAgentPart"


def _execute_generated_part() -> None:
    if not WATCH_FILE.exists():
        FreeCAD.Console.PrintWarning(f"[Agent] File not found: {WATCH_FILE}\n")
        return

    # Close the previous agent document cleanly
    for name, doc in list(FreeCAD.listDocuments().items()):
        if doc.Label == AGENT_DOC_NAME:
            FreeCAD.closeDocument(name)

    try:
        code = WATCH_FILE.read_text(encoding="utf-8")
        exec(compile(code, str(WATCH_FILE), "exec"), globals())  # noqa: S102
        FreeCAD.Console.PrintMessage("[Agent] Part updated successfully.\n")
    except Exception as exc:
        FreeCAD.Console.PrintError(f"[Agent] Error executing part: {exc}\n")


class _AgentWatcher(QtCore.QObject):
    def __init__(self) -> None:
        super().__init__()
        self._fs = QtCore.QFileSystemWatcher()
        if WATCH_FILE.exists():
            self._fs.addPath(str(WATCH_FILE))
        self._fs.fileChanged.connect(self._on_changed)
        FreeCAD.Console.PrintMessage(
            f"[Agent] Watcher active. Monitoring:\n        {WATCH_FILE}\n"
        )

    def _on_changed(self, _path: str) -> None:
        # Small delay ensures the file write is fully flushed on Windows
        QtCore.QTimer.singleShot(300, self._reattach)
        QtCore.QTimer.singleShot(400, _execute_generated_part)

    def _reattach(self) -> None:
        """Re-add path if the file was replaced (Python overwrites atomically)."""
        if WATCH_FILE.exists() and str(WATCH_FILE) not in self._fs.files():
            self._fs.addPath(str(WATCH_FILE))


# Attach to FreeCAD app to prevent garbage collection
if hasattr(FreeCAD, "_agent_watcher"):
    FreeCAD.Console.PrintMessage("[Agent] Restarting watcher...\n")
    del FreeCAD._agent_watcher

FreeCAD._agent_watcher = _AgentWatcher()
