"""Agent pipeline: transcript -> intent -> (confirm) -> execute as the agent.

Execution always runs inside frappe.set_user(agent.user), so desk permissions,
User Permissions and the audit trail apply exactly as they would by hand."""

import frappe
from frappe import _
from frappe.utils import cstr, flt

from re_voice.channel import outbound
from re_voice.intent import entities as ent
from re_voice.intent import llm, matcher
from re_voice.intent.registry import command_entities, enabled_commands

MAX_CLARIFY_OPTIONS = 3


# ------------------------------------------------------------------ entry

def handle_agent_message(message, agent, session):
    msg_type = message.get("type")
    phone = message.get("from")

    if msg_type == "interactive":
        return _handle_interactive(message, agent, session)

    if msg_type == "audio":
        voice_message = _ingest_audio(message, agent)
        if not voice_message or voice_message.status == "Failed":
            outbound.reply(phone, _("I couldn't process that voice note. "
                                    "Please try again or type the command."))
            return None
        from re_voice.voice.asr import resolve_text
        transcript, channel = resolve_text(voice_message), "Voice"
    elif msg_type == "text":
        voice_message, channel = None, "Text"
        transcript = (message.get("text") or {}).get("body", "")
    else:
        outbound.reply(phone, _("Send a voice note or text command."))
        return None

    return route_transcript(transcript, agent, session, voice_message, channel)


def _ingest_audio(message, agent):
    from re_voice.channel.media import download_media, save_media_file
    from re_voice.voice.asr import transcribe_voice_message

    audio = message.get("audio") or {}
    doc = frappe.get_doc({
        "doctype": "Voice Message",
        "from_number": message.get("from"),
        "media_id": audio.get("id"),
        "duration_seconds": audio.get("duration") or 0,
        "status": "Pending",
    }).insert(ignore_permissions=True)

    content, _mime, filename = download_media(audio.get("id"))
    if not content:
        doc.db_set("status", "Failed")
        doc.db_set("error", "Media download failed")
        return doc.reload()
    doc.db_set("audio_file", save_media_file(content, filename, "Voice Message", doc.name))
    return transcribe_voice_message(doc.name)


# ------------------------------------------------------------------ routing

def route_transcript(transcript, agent, session, voice_message=None, channel="Voice"):
    phone = session.phone_number
    transcript = cstr(transcript).strip()
    if not transcript:
        outbound.reply(phone, _("I didn't catch that — could you repeat it?"))
        return None

    intent = frappe.get_doc({
        "doctype": "Voice Intent", "from_number": phone, "agent": agent,
        "voice_message": voice_message.name if voice_message else None,
        "transcript": transcript[:2000], "channel": channel, "status": "Parsed",
    }).insert(ignore_permissions=True)
    if voice_message:
        voice_message.db_set("voice_intent", intent.name)

    commands = enabled_commands(agent_only=True)
    name, confidence = matcher.match(transcript, commands)
    resolver = "Keyword"

    if not name:
        name, llm_entities, confidence = llm.classify(transcript, commands, intent.name)
        resolver = "LLM"
    else:
        llm_entities = {}

    threshold = flt(frappe.db.get_single_value(
        "AI Settings", "llm_confidence_threshold") or 0.6)
    if not name or confidence < threshold:
        return _ask_for_clarification(intent, transcript, commands, phone)

    intent.db_set("command", name)
    intent.db_set("resolver", resolver)
    intent.db_set("confidence", confidence)

    parsed = _extract_entities(name, transcript, session, llm_entities)
    intent.db_set("entities", frappe.as_json(parsed))

    needs_confirmation = frappe.db.get_value("Voice Command", name, "needs_confirmation")
    if needs_confirmation:
        return _request_confirmation(intent, name, parsed, session)
    return execute(intent.name)


def _extract_entities(command_name, transcript, session, llm_entities=None):
    """Deterministic extraction wins; LLM values fill the gaps."""
    locale = _locale(session)
    parsed = dict(llm_entities or {})
    for spec in command_entities(command_name):
        value = None
        kind = spec.entity_type
        if kind == "Money":
            value = ent.parse_money(transcript, locale.get("number_system"))
        elif kind == "UnitType":
            value = ent.parse_unit_type(transcript)
        elif kind == "Integer":
            value = ent.parse_bedrooms(transcript)
        elif kind in ("Date", "DateTime"):
            resolved = ent.parse_datetime(transcript)
            value = resolved.strftime("%Y-%m-%d %H:%M:%S") if resolved else None
        elif kind == "Text" and spec.entity_name in ("name", "full_name"):
            value = ent.parse_name(transcript)
        elif kind == "Text" and spec.entity_name in ("mobile", "phone"):
            value = ent.parse_phone(transcript)
        if value is not None:
            parsed[spec.entity_name] = value
    return parsed


def _locale(session):
    profile = session.locale_profile and frappe.db.get_value(
        "Voice Locale Profile", session.locale_profile,
        ["number_system", "unit_vocabulary", "languages"], as_dict=True)
    return profile or {"number_system": "International"}


def _ask_for_clarification(intent, transcript, commands, phone):
    intent.db_set("status", "Clarifying")
    ranked = []
    for command in commands:
        _n, score = matcher.match(transcript, [command])
        ranked.append((command["command_name"], score))
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    options = [(f"intent::{intent.name}::{name}", name[:20])
               for name, score in ranked[:MAX_CLARIFY_OPTIONS] if score > 0]
    if not options:
        intent.db_set("status", "Unrecognised")
        outbound.reply(phone, _("I didn't recognise that command. Say 'help' for "
                                "the list of things I can do."))
        return None
    session_doc = frappe.get_doc("Conversation Session", phone)
    session_doc.db_set("pending_intent", intent.name)
    outbound.send_buttons(phone, _("Did you mean:"), options, force=True)
    return None


def _request_confirmation(intent, command_name, parsed, session):
    intent.db_set("status", "Awaiting Confirmation")
    session.db_set("pending_intent", intent.name)
    detail = ", ".join(f"{k}: {v}" for k, v in parsed.items() if v) or _("no details")
    outbound.send_buttons(
        session.phone_number,
        _("Confirm **{0}**?\n{1}").format(command_name, detail),
        [(f"confirm::{intent.name}", _("Confirm")),
         (f"cancel::{intent.name}", _("Cancel"))],
        force=True)
    return None


def _owned_intent(intent_name, agent, allowed_statuses):
    # Return the Voice Intent only if it belongs to this agent and is still
    # in one of the expected states; otherwise None (expired / replayed / foreign).
    row = frappe.db.get_value("Voice Intent", intent_name,
                              ["name", "agent", "status"], as_dict=True)
    if not row or row.agent != agent or row.status not in allowed_statuses:
        return None
    return frappe.get_doc("Voice Intent", intent_name)


def _handle_interactive(message, agent, session):
    interactive = message.get("interactive") or {}
    reply_id = ((interactive.get("button_reply") or {}).get("id")
                or (interactive.get("list_reply") or {}).get("id") or "")
    phone = message.get("from")

    if reply_id.startswith("confirm::"):
        intent_name = reply_id.split("::", 1)[1]
        session.db_set("pending_intent", None)
        if not _owned_intent(intent_name, agent, ("Awaiting Confirmation",)):
            outbound.reply(phone, _("That confirmation has expired or was already used."))
            return None
        return execute(intent_name)
    if reply_id.startswith("cancel::"):
        intent_name = reply_id.split("::", 1)[1]
        if not _owned_intent(intent_name, agent, ("Awaiting Confirmation",)):
            outbound.reply(phone, _("That confirmation has expired or was already used."))
            return None
        frappe.db.set_value("Voice Intent", intent_name, "status", "Cancelled")
        session.db_set("pending_intent", None)
        outbound.reply(phone, _("Cancelled — nothing was changed."))
        return None
    if reply_id.startswith("intent::"):
        _, intent_name, command_name = reply_id.split("::", 2)
        intent = _owned_intent(intent_name, agent, ("Clarifying",))
        if not intent:
            outbound.reply(phone, _("That option has expired. Please send the command again."))
            return None
        intent.db_set("command", command_name)
        intent.db_set("resolver", "Interactive")
        intent.db_set("confidence", 1.0)
        intent.db_set("entities", frappe.as_json(
            _extract_entities(command_name, intent.transcript, session)))
        session.db_set("pending_intent", None)
        if frappe.db.get_value("Voice Command", command_name, "needs_confirmation"):
            return _request_confirmation(intent, command_name,
                                         frappe.parse_json(intent.entities), session)
        return execute(intent.name)

    outbound.reply(phone, _("That option has expired. Please send the command again."))
    return None


# ------------------------------------------------------------------ execution

def execute(intent_name):
    """Run the handler as the agent's user so permissions and audit apply."""
    intent = frappe.get_doc("Voice Intent", intent_name)
    handler_path = frappe.db.get_value("Voice Command", intent.command, "handler")
    user = frappe.db.get_value("RE Agent", intent.agent, "user")
    if not (handler_path and user):
        intent.db_set("status", "Failed")
        intent.db_set("error", "Handler or agent user not configured")
        return None

    # Atomic claim: only one caller can move the intent out of a pending state.
    frappe.db.sql("""UPDATE `tabVoice Intent` SET status = 'Executed'
                     WHERE name = %s
                       AND status IN ('Parsed', 'Awaiting Confirmation', 'Clarifying')""",
                  intent_name)
    if not frappe.db.sql("SELECT ROW_COUNT()")[0][0]:
        outbound.reply(intent.from_number,
                       _("That command was already processed."))
        return None
    frappe.db.commit()

    original_user = frappe.session.user
    try:
        frappe.set_user(user)
        handler = frappe.get_attr(handler_path)
        result = handler(intent, frappe.parse_json(intent.entities or "{}")) or {}
        intent.db_set("status", "Executed")
        if result.get("doctype"):
            intent.db_set("reference_doctype", result["doctype"])
            intent.db_set("reference_name", result.get("name"))
        if result.get("reply"):
            intent.db_set("reply_sent", cstr(result["reply"])[:1000])
            outbound.reply(intent.from_number, result["reply"],
                           buttons=result.get("buttons"))
        return result
    except frappe.PermissionError:
        intent.db_set("status", "Failed")
        intent.db_set("error", "Permission denied")
        outbound.reply(intent.from_number,
                       _("You don't have permission for that action."))
        return None
    except Exception:
        intent.db_set("status", "Failed")
        intent.db_set("error", frappe.get_traceback()[-500:])
        outbound.reply(intent.from_number,
                       _("Something went wrong running that command. "
                         "It has been logged."))
        frappe.log_error(title="re_voice: command execution failed", message=intent_name)
        return None
    finally:
        frappe.set_user(original_user)
