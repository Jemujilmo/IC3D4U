"""
FreeCAD AI Copilot — agent_core.py

Thin wrapper around LM Studio's OpenAI-compatible chat API.
Called from copilot_panel._Worker (background QThread) so it
never blocks FreeCAD's main thread.
"""

import json
import re

from openai import OpenAI

from system_prompt import DESIGN_INTAKE_PROMPT, SYSTEM_PROMPT

# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL    = "http://localhost:1234/v1"
MODEL       = "qwen3-coder-30b-a3b-instruct"
MAX_TOKENS  = 4096
TEMPERATURE = 0.1
MAX_TURNS   = 6   # keep last N user/assistant exchanges in the context window

_client = OpenAI(base_url=BASE_URL, api_key="lm-studio")


# ── Public API ─────────────────────────────────────────────────────────────────

def get_completion(history: list) -> str:
    """
    Run design intake first. If the normalized spec is ready, generate
    FreeCAD code; otherwise return targeted clarification questions.

    Parameters
    ----------
    history : list of {"role": str, "content": str}
        The full conversation so far (system message is prepended here).
    """
    recent_history = history[-(MAX_TURNS * 2):]
    plan = _get_design_plan(recent_history)
    if not _can_generate(plan):
        return _render_questions(plan)

    messages = _build_codegen_messages(recent_history, plan)
    resp = _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    return resp.choices[0].message.content


def extract_code(text: str) -> str:
    """
    Pull the first ```python … ``` block from the model's reply.
    Returns an empty string if no fenced block is found and the reply
    does not look like a bare Python script.
    """
    match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fallback: treat the whole reply as code if it opens with a
    # recognisable Python token (model skipped the fence).
    stripped = text.strip()
    if stripped.startswith(("import ", "FreeCAD", "doc =", "#")):
        return stripped

    return ""


def _get_design_plan(history: list) -> dict:
    messages = [{"role": "system", "content": DESIGN_INTAKE_PROMPT}]
    messages += history

    resp = _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    return _extract_json(resp.choices[0].message.content)


def _extract_json(text: str) -> dict:
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


def _can_generate(plan: dict) -> bool:
    return (
        plan.get("action") == "proceed"
        and plan.get("readiness") in {"ready", "assumptions_allowed"}
        and isinstance(plan.get("normalizedSpec"), dict)
    )


def _render_questions(plan: dict) -> str:
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


def _build_codegen_messages(history: list, plan: dict) -> list:
    normalized_spec = plan.get("normalizedSpec", {})
    spec_text = json.dumps(normalized_spec, indent=2, ensure_ascii=False)
    spec_prompt = (
        "Generate a complete FreeCAD Python script from this normalized design spec. "
        "Use the JSON as the source of truth and follow the system output rules.\n\n"
        f"NORMALIZED_SPEC_JSON:\n{spec_text}"
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history
    messages.append({"role": "user", "content": spec_prompt})
    return messages
