"""Command registry access — the single source of truth for both matcher tiers."""

import frappe


def enabled_commands(agent_only=None):
    filters = {"enabled": 1}
    if agent_only is not None:
        filters["agent_only"] = 1 if agent_only else 0
    return frappe.get_all(
        "Voice Command", filters=filters,
        fields=["name as command_name", "command_group", "handler",
                "needs_confirmation", "keywords", "sample_phrases", "description"])


def command_entities(command_name):
    return frappe.get_all(
        "Command Entity", filters={"parent": command_name},
        fields=["entity_name", "entity_type", "target_field", "options",
                "is_required"], order_by="idx asc")


def as_tool_schema(commands):
    """Render the registry for the LLM tier."""
    lines = []
    for command in commands:
        entities = command_entities(command["command_name"])
        entity_text = ", ".join(
            f"{e.entity_name}:{e.entity_type}"
            f"{'(required)' if e.is_required else ''}" for e in entities) or "none"
        lines.append(
            f"- {command['command_name']}: {command.get('description') or ''} "
            f"| entities: {entity_text}")
    return "\n".join(lines)
