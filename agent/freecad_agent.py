#!/usr/bin/env python3
"""
FreeCAD AI Agent — Phase 2
Translates natural language prompts into FreeCAD Python scripts via LM Studio.

Phase 2 additions:
  - Persistent conversation history (history.json) survives restarts
  - Part versioning: every generation saved to output/parts/
  - Auto-deploys watcher_macro to FreeCAD; run it once for live auto-execute
"""

import json
import re
import shutil
import sys
from datetime import datetime
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
from system_prompt import DESIGN_INTAKE_PROMPT, SYSTEM_PROMPT

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent
AGENT_DIR   = Path(__file__).parent
OUTPUT_DIR  = ROOT / "output"
PARTS_DIR   = OUTPUT_DIR / "parts"
HISTORY_FILE = AGENT_DIR / "history.json"
WATCHER_SRC  = AGENT_DIR / "watcher_macro.py"

OUTPUT_DIR.mkdir(exist_ok=True)
PARTS_DIR.mkdir(exist_ok=True)

OUTPUT_FILE  = OUTPUT_DIR / "generated_part.py"
MACRO_FILE   = Path(FREECAD_MACRO_DIR) / "generated_part.FCMacro"
WATCHER_DEST = Path(FREECAD_MACRO_DIR) / "watcher.FCMacro"

# ── LM Studio client ──────────────────────────────────────────────────────────
client = OpenAI(base_url=LM_STUDIO_BASE_URL, api_key="lm-studio")


# ── History ──────────────────────────────────────────────────────────────────

def load_history() -> list:
    """Load saved conversation history from disk."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_history(history: deque) -> None:
    """Persist conversation history to disk."""
    HISTORY_FILE.write_text(
        json.dumps(list(history), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def clear_history(history: deque) -> None:
    history.clear()
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
    print("[History cleared]\n")


# ── Watcher deployment ────────────────────────────────────────────────────────

def deploy_watcher() -> None:
    """Copy watcher_macro.py to FreeCAD's macro folder as watcher.FCMacro."""
    macro_dir = Path(FREECAD_MACRO_DIR)
    if not macro_dir.exists() or not WATCHER_SRC.exists():
        return
    shutil.copy2(WATCHER_SRC, WATCHER_DEST)


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_code(text: str) -> str:
    """Pull the first ```python ... ``` block from the LLM response."""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Model ignored the formatting rule — return raw text as fallback
    return text.strip()


def extract_json(text: str) -> dict:
    """Parse the first JSON object from the LLM response."""
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(stripped[start:end + 1])


def get_design_plan(history: list) -> dict:
    """Run the intake pass and return the structured design plan."""
    messages = [{"role": "system", "content": DESIGN_INTAKE_PROMPT}]
    messages += history[-(MAX_HISTORY_TURNS * 2):]

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    return extract_json(resp.choices[0].message.content)


def can_generate(plan: dict) -> bool:
    """Return True when the normalized spec may pass into code generation."""
    return (
        plan.get("action") == "proceed"
        and plan.get("readiness") in {"ready", "assumptions_allowed"}
        and isinstance(plan.get("normalizedSpec"), dict)
    )


def render_questions(plan: dict) -> str:
    """Format intake questions for the terminal."""
    questions = plan.get("questions") or []
    lines = []
    user_message = plan.get("userMessage")
    if user_message:
        lines.append(str(user_message))
    else:
        lines.append("I need a little more detail before generating CAD:")

    for index, question in enumerate(questions[:3], start=1):
        text = question.get("text", "Please provide more detail.")
        question_id = question.get("id", "unknown")
        expects = question.get("expects", "string")
        lines.append(f"{index}. {text} (id: {question_id}, expects: {expects})")

    return "\n".join(lines)


def design_plan_history_message(plan: dict) -> str:
    """Store structured intake state in chat history for the next turn."""
    return "Design intake result JSON:\n" + json.dumps(
        plan, indent=2, ensure_ascii=False
    )


def build_codegen_messages(history: deque, plan: dict) -> list:
    """Build the existing code-gen prompt using normalizedSpec as source of truth."""
    normalized_spec = plan.get("normalizedSpec", {})
    spec_text = json.dumps(normalized_spec, indent=2, ensure_ascii=False)
    spec_prompt = (
        "Generate a complete FreeCAD Python script from this normalized design spec. "
        "Use the JSON as the source of truth and follow the system output rules.\n\n"
        f"NORMALIZED_SPEC_JSON:\n{spec_text}"
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += list(history)[-(MAX_HISTORY_TURNS * 2):]
    messages.append({"role": "user", "content": spec_prompt})
    return messages


def save_and_deploy(code: str) -> None:
    """Write code to output, versioned parts dir, and FreeCAD macro folder."""
    # Primary output
    OUTPUT_FILE.write_text(code, encoding="utf-8")

    # Versioned snapshot
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_file = PARTS_DIR / f"part_{timestamp}.py"
    version_file.write_text(code, encoding="utf-8")

    macro_dir = Path(FREECAD_MACRO_DIR)
    if macro_dir.exists():
        MACRO_FILE.write_text(code, encoding="utf-8")
        print(f"\n[Saved] FreeCAD macro  → {MACRO_FILE}")
        print(f"[Saved] Version        → {version_file.name}")
        print("[Auto]  Watcher will execute it instantly if running.")
        print("[Manual] Macro menu → Macros → 'generated_part' → Execute")
    else:
        print(f"\n[Saved] {OUTPUT_FILE}")
        print(f"[Saved] Version → {version_file.name}")
        print("[Run]   Paste the code into FreeCAD's Python Console")


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
    print("║        FreeCAD AI Agent — Phase 2        ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  Model  : {MODEL_NAME}")
    print(f"  Server : {LM_STUDIO_BASE_URL}")
    print("  Commands: 'clear' (reset history) | 'exit' (quit)\n")

    if not check_lm_studio():
        sys.exit(1)

    # Deploy watcher macro to FreeCAD (silent — only copies the file)
    deploy_watcher()

    # Load persisted history, capped to the sliding window size
    saved = load_history()
    history: deque = deque(saved[-(MAX_HISTORY_TURNS * 2):], maxlen=MAX_HISTORY_TURNS * 2)
    if history:
        print(f"[History] Resumed {len(history) // 2} previous turn(s). Type 'clear' to reset.\n")

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
            clear_history(history)
            continue

        history.append({"role": "user", "content": user_input})

        print("\nPlanning", end="", flush=True)
        try:
            plan = get_design_plan(list(history))
        except Exception as exc:
            print(f"\n[Error] LM Studio intake request failed: {exc}\n")
            history.pop()  # remove the failed user message
            continue

        if not can_generate(plan):
            reply = render_questions(plan)
            print(" ...\n" + reply + "\n")
            history.append({"role": "assistant", "content": design_plan_history_message(plan)})
            save_history(history)
            continue

        messages = build_codegen_messages(history, plan)

        print(" ... ready.\nGenerating", end="", flush=True)
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
        save_history(history)

        code = extract_code(full_reply)

        print("\n─── Generated Code ────────────────────────")
        print(code)
        print("───────────────────────────────────────────")

        save_and_deploy(code)
        print()


if __name__ == "__main__":
    run()
