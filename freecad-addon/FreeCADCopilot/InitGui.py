"""
FreeCAD AI Copilot — InitGui.py

Loaded automatically by FreeCAD when its GUI starts (placed in
%APPDATA%/FreeCAD/Mod/FreeCADCopilot/).

Adds a persistent dockable AI chat panel to the right side of the
main window. Works alongside any workbench without requiring a
workbench switch.
"""

import os
import sys

import FreeCAD
import FreeCADGui
from PySide6 import QtCore


def _resolve_addon_dir():
    """Locate this addon even when FreeCAD executes InitGui without __file__."""
    file_path = globals().get("__file__")
    if file_path:
        return os.path.dirname(os.path.abspath(file_path))

    spec = globals().get("__spec__")
    origin = getattr(spec, "origin", None)
    if origin:
        return os.path.dirname(os.path.abspath(origin))

    candidates = [
        os.path.join(FreeCAD.getUserAppDataDir(), "Mod", "FreeCADCopilot"),
        os.path.join(
            os.environ.get("APPDATA", ""),
            "FreeCAD",
            "v1-1",
            "Mod",
            "FreeCADCopilot",
        ),
    ]
    for candidate in candidates:
        if os.path.exists(os.path.join(candidate, "copilot_panel.py")):
            return candidate

    raise RuntimeError("Could not locate FreeCADCopilot addon directory")


_ADDON_DIR = _resolve_addon_dir()


def _launch_copilot(addon_dir=_ADDON_DIR):
    """
    Deferred startup so FreeCAD's main window is fully constructed
    before we try to attach a dock widget.
    """
    try:
        mw = FreeCADGui.getMainWindow()
        if mw is None:
            # Main window not ready yet — retry in 500 ms
            QtCore.QTimer.singleShot(500, _launch_copilot)
            return

        # Guard against double-loading (e.g. after workbench reload)
        from PySide6.QtWidgets import QDockWidget
        for dock in mw.findChildren(QDockWidget):
            if dock.objectName() == "FreeCADAICopilot":
                return

        # Ensure this addon's directory is on sys.path so sibling
        # modules (copilot_panel, agent_core, system_prompt) import cleanly.
        if addon_dir not in sys.path:
            sys.path.insert(0, addon_dir)

        from copilot_panel import CopilotDock
        from PySide6.QtCore import Qt
        dock = CopilotDock(mw)
        area = Qt.DockWidgetArea.RightDockWidgetArea
        mw.addDockWidget(area, dock)

        FreeCAD.Console.PrintMessage("[AI Copilot] Panel ready.\n")

    except Exception as exc:
        FreeCAD.Console.PrintWarning(f"[AI Copilot] Failed to load: {exc}\n")


# Delay 800 ms — enough for FreeCAD's splash + main window to settle
QtCore.QTimer.singleShot(800, _launch_copilot)
