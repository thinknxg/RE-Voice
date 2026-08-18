"""Tier-2 intent resolution via the configured LLM."""

import frappe
from frappe.utils import flt

from re_voice.ai.client import llm_complete, parse_json_response
from re_voice.intent.registry import as_tool_schema

SYSTEM = (
    "You classify a real-estate agent's spoken command into exactly one command "
    "from the provided registry and extract its entities. Reply with JSON only: "
    '{"command": "<exact registry name or null>", "entities": {...}, '
    '"confidence": <0-1>}. Use null when nothing fits. Never invent a command name.')


def classify(transcript, commands, reference=None):
    """Returns (command_name, entities_dict, confidence)."""
    if not commands:
        return None, {}, 0.0
    prompt = (f"Registry:\n{as_tool_schema(commands)}\n\n"
              f"Agent said: \"{transcript}\"\n\nJSON:")
    raw = llm_complete(prompt, system=SYSTEM, task="Intent", json_mode=True,
                       reference_doctype="Voice Intent", reference_name=reference)
    parsed = parse_json_response(raw)
    if not parsed:
        return None, {}, 0.0

    name = parsed.get("command")
    valid = {c["command_name"] for c in commands}
    if name not in valid:   # guard against hallucinated command names
        return None, {}, 0.0
    return name, parsed.get("entities") or {}, flt(parsed.get("confidence") or 0.0)
