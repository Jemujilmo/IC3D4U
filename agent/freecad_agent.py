#!/usr/bin/env python3
"""
FreeCAD AI Agent — Phase 1
Translates natural language prompts into FreeCAD Python scripts via LM Studio.

Usage:
    python freecad_agent.py

Workflow:
    1. Type a description or command at the prompt.
    2. The agent calls LM Studio (local, free) and generates a FreeCAD script.
    3. The script is saved to:
         - output/generated_part.py       (always)
         - %APPDATA%/FreeCAD/Macro/       (if the folder exists)
    4. In FreeCAD: Macro menu → Macros → select "generated_part" → Execute
       OR open View → Panels → Python Console and paste the printed code.
"""

import re
import sys
import shutil
from pathlib import Path
from collections import deque

try:
    from openai import OpenAI
except ImportError:
    sys.exit(
        "[Error] 'openai' package not found.\n"
        "Run:  pip install openai\n"
    )

from config import (
    LM_STUDIO_BASE_URL,
    MODEL_NAME,
    MAX_TOKENS,
    TEMPERATURE,
    FREECAD_MACRO_DIR,
    MAX_HISTORY_TURNS,
)
from system_prompt import SYSTEM_PROMPT

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "generated_part.py"
MACRO_FILE = Path(FREECAD_MACRO_DIR) / "generated_part.FCMacro"

# ── LM Studio client ──────────────────────────────────────────────────────────
client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key="lm-studio")


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_code(text: str) -> str:
    """Pull the first ```python ... ``` block from the LLM response."""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Model ignored the formatting rule — return raw text as fallback
    return text.strip()


def save_and_deploy(code: str) -> None:
    """Write code to output dir and, if available, the FreeCAD macro folder."""
    OUTPUT_FILE.write_text(code, encoding="utf-8")

    macro_dir = Path(FREECAD_MACRO_DIR)
    if macro_dir.exists():
        MACRO_FILE.write_text(code, encoding="utf-8")
        print(f"\n[Saved] FreeCAD macro → {MACRO_FILE}")
        print("[Run]   FreeCAD: Macro menu → Macros → 'generated_part' → Execute")
    else:
        print(f"\n[Saved] {OUTPUT_FILE}")
        print("[Run]   Paste the code below into FreeCAD's Python Console")
        print("        (View → Panels → Python Console)")


def check_lm_studio() -> bool:
    """Quick connectivity check against LM Studio."""
    try:
        models = client.models.list()
        names = [m.id for m in models.data]
        if MODEL_NAME not in names:
            print(f"[Warning] Model '{MODEL_NAME}' not found in LM Studio.")
            print(f"          Available: {names}")
            print("          Update MODEL_NAME in config.py if needed.\n")
        return True
    except Exception as exc:
        print(f"[Error] Cannot reach LM Studio at {LM_STUDIO_BASE_URL}")
        print(f"        {exc}")
        print("        Make sure LM Studio is running and the server is started.")
        return False


# ── Main agent loop ───────────────────────────────────────────────────────────

def run():
    # Set terminal tab title so it's easy to find among other PowerShell tabs
    print("\033]0;FreeCAD Agent\007", end="", flush=True)

    print("\n╔══════════════════════════════════════════╗")
    print("║        FreeCAD AI Agent — Phase 1        ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  Model  : {MODEL_NAME}")
    print(f"  Server : {LM_STUDIO_BASE_URL}")
    print("  Type a part description or command.")
    print("  Commands: 'clear' (reset history) | 'exit' (quit)\n")

    if not check_lm_studio():
        sys.exit(1)

    # Sliding window: keep last N user/assistant turn pairs
    history: deque = deque(maxlen=MAX_HISTORY_TURNS * 2)

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not user_input:
            continue

        if user_input.lower() == "exit":
            print("Goodbye.")
            break

        if user_input.lower() == "clear":
            history.clear()
            print("[History cleared]\n")
            continue

        history.append({"role": "user", "content": user_input})

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history)

        print("\nGenerating", end="", flush=True)
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                stream=True,
            )

            # Stream tokens so the user sees output immediately
            full_reply = ""
            print(" ...")
            for chunk in response:
                delta = chunk.choices[0].delta.content or ""
                full_reply += delta
                print(delta, end="", flush=True)
            print()  # newline after stream ends

        except Exception as exc:
            print(f"\n[Error] LM Studio request failed: {exc}\n")
            history.pop()  # remove the failed user message
            continue

        history.append({"role": "assistant", "content": full_reply})

        code = extract_code(full_reply)

        print("\n─── Generated Code ────────────────────────")
        print(code)
        print("───────────────────────────────────────────")

        save_and_deploy(code)
        print()


if __name__ == "__main__":
    run()
