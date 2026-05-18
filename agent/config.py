"""
Configuration for FreeCAD AI Agent
Adjust these values to match your local setup.
"""

import os
from pathlib import Path

# ── LM Studio ────────────────────────────────────────────────────────────────
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
# Must match the model identifier shown in LM Studio (Developer tab → model name)
MODEL_NAME = "qwen3-coder-30b-a3b-instruct"
# Increase this in LM Studio model settings → context length (recommend 8192+)
MAX_TOKENS = 3000
TEMPERATURE = 0.1  # Low = more deterministic code output

# ── FreeCAD ───────────────────────────────────────────────────────────────────
# Macro directory — FreeCAD watches this folder (Macro menu → Macros)
# FreeCAD 1.1.x uses a versioned subfolder
FREECAD_MACRO_DIR = Path(os.environ.get("APPDATA", "")) / "FreeCAD" / "v1-1" / "Macro"

# Path to FreeCADCmd.exe for optional headless execution
FREECAD_CMD = Path(r"C:\Program Files\FreeCAD 1.1\bin\FreeCADCmd.exe")

# ── Agent behaviour ───────────────────────────────────────────────────────────
# How many previous exchanges to keep in context (keep low given 4096 ctx limit)
MAX_HISTORY_TURNS = 3
