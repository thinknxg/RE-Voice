"""Customer-facing automation. This pipeline has no Frappe identity: it may only
create a Lead/Thread for the sender's own number and reply. It can never execute
an agent command."""

import frappe
from frappe import _
from frappe.utils import cstr, now_datetime

from re_voice.ai.matching import match_properties
from re_voice.channel import outbound
from re_voice.intent import entities as ent

FEEDBACK_OPTIONS = [
    ("visit_fb::Interested", _("Interested"), _("Ready to move ahead")),
    ("visit_fb::Need Discount", _("Need Discount"), _("Price is the blocker")),
    ("visit_fb::Looking Around", _("Looking Around"), _("Still comparing")),
    ("visit_fb::Not Interested", _("Not Interested"), _("Not a fit")),
]

CONSENT_NOTICE = _(
    "Hi! You're chatting with our property team. Messages and voice notes here are "
    "saved to our CRM so we can help you better. Reply STOP to opt out.")


def handle_customer_message(message, session):
    msg_type = message.get("type")
    phone = message.get("from")
    thread = _get_thread(phone, session, message.get("_profile_name"))

    if msg_type == "interactive":
        return _handle_feedback(message, thread, session)

    body, voice_message = _extract_body(message, phone)
    if not body:
        return None
    _append_message(thread, "Inbound", msg_type, body, voice_message)

    if cstr(body).strip().lower() in ("stop", "unsubscribe"):
        thread.db_set("stage", "Closed")
        outbound.send_text(phone, _("You've been opted out. Reply START to resume."),
                           force=True)
        return None

    if not session.consent_notified:
        outbound.send_text(phone, CONSENT_NOTICE, force=True)
        session.db_set("consent_notified", 1)

    return _auto_reply(body, thread, session)


def _get_thread(phone, session, profile_name=None):
    existing = frappe.db.get_value("Customer Thread", {"phone_number": phone}, "name")
    if existing:
        return frappe.get_doc("Customer Thread", existing)
    lead = _get_or_create_lead(phone, profile_name)
    thread = frappe.get_doc({
        "doctype": "Customer Thread", "phone_number": phone,
        "display_name": profile_name or phone, "lead": lead,
        "agent": frappe.db.get_value("RE Lead", lead, "assigned_agent"),
        "stage": "Enquiry",
    }).insert(ignore_permissions=True)
    session.db_set("lead", lead)
    return thread


def _get_or_create_lead(phone, profile_name=None):
    existing = frappe.db.get_value("RE Lead", {"mobile": phone}, "name")
    if existing:
        return existing
    lead = frappe.new_doc("RE Lead")
    lead.full_name = profile_name or phone
    lead.mobile = phone
    lead.source = frappe.db.exists("Lead Source RE", "WhatsApp") or None
    lead.insert(ignore_permissions=True)   # round-robin assignment fires in re_crm
    return lead.name


def _extract_body(message, phone):
    msg_type = message.get("type")
    if msg_type == "text":
        return (message.get("text") or {}).get("body", ""), None
    if msg_type == "audio":
        from re_voice.channel.media import download_media, save_media_file
        from re_voice.voice.asr import resolve_text, transcribe_voice_message
        audio = message.get("audio") or {}
        doc = frappe.get_doc({
            "doctype": "Voice Message", "from_number": phone,
            "media_id": audio.get("id"),
            "duration_seconds": audio.get("duration") or 0, "status": "Pending",
        }).insert(ignore_permissions=True)
        content, _mime, filename = download_media(audio.get("id"))
        if content:
            doc.db_set("audio_file",
                       save_media_file(content, filename, "Voice Message", doc.name))
            doc = transcribe_voice_message(doc.name)
            return resolve_text(doc), doc.name
        return None, doc.name
    return None, None


def _append_message(thread, direction, msg_type, body, voice_message=None,
                    template=None):
    thread.append("messages", {
        "direction": direction, "message_type": msg_type,
        "body": cstr(body)[:1000], "sent_at": now_datetime(),
        "voice_message": voice_message, "template_used": template,
    })
    thread.save(ignore_permissions=True)


def _auto_reply(body, thread, session):
    """Availability question -> up to three matching options + a visit prompt."""
    locale = frappe.db.get_value("Voice Locale Profile", session.locale_profile,
                                 "number_system") or "International"
    unit_type = ent.parse_unit_type(body)
    budget = ent.parse_money(body, locale)
    lowered = cstr(body).lower()
    asking = any(word in lowered for word in
                 ("available", "availability", "looking", "need", "want", "show",
                  "bhk", "bedroom", "rent", "buy", "flat", "apartment", "villa"))
    if not (asking or unit_type):
        return None

    if thread.lead:
        updates = {}
        if budget:
            updates["budget_max"] = budget
        if unit_type:
            updates["preferred_property_type"] = (
                unit_type if unit_type in ("Shop", "Office", "Warehouse", "Villa")
                else "Apartment")
        if updates:
            frappe.db.set_value("RE Lead", thread.lead, updates, update_modified=False)

    matches = match_properties(body, unit_type=unit_type,
                               bedrooms=ent.parse_bedrooms(body), budget=budget,
                               limit=3)
    phone = thread.phone_number
    if not matches:
        outbound.send_text(phone, _(
            "Thanks! I don't have an exact match right now — an agent will call you "
            "shortly with options."), force=True)
        _append_message(thread, "Outbound", "text", "no-match acknowledgement")
        return None

    lines = "\n".join(
        f"🏠 {m['title']} — {frappe.utils.fmt_money(m['headline_price'])}"
        f" ({m['reason']})" for m in matches)
    outbound.send_text(phone, _("Yes — these are available:\n\n{0}").format(lines),
                       force=True)
    outbound.send_buttons(phone, _("Would you like to schedule a visit?"),
                          [("visit_yes", _("Yes, schedule")),
                           ("visit_no", _("Not now"))], force=True)
    _append_message(thread, "Outbound", "text", lines)
    thread.db_set("stage", "Options Sent")
    frappe.db.set_value("Conversation Session", phone, "context",
                        frappe.as_json({"results": [m["unit"] for m in matches]}))
    return matches


def _handle_feedback(message, thread, session):
    interactive = message.get("interactive") or {}
    reply_id = ((interactive.get("button_reply") or {}).get("id")
                or (interactive.get("list_reply") or {}).get("id") or "")
    phone = thread.phone_number

    if reply_id.startswith("visit_fb::"):
        outcome = reply_id.split("::", 1)[1]
        return _record_visit_feedback(thread, outcome)

    if reply_id == "visit_yes":
        thread.db_set("stage", "Visit Scheduled")
        agent_name = thread.agent and frappe.db.get_value("RE Agent", thread.agent,
                                                          "agent_name")
        outbound.send_text(phone, _(
            "Great — {0} will call you shortly to confirm a time.").format(
                agent_name or _("our agent")), force=True)
        if thread.agent:
            _notify_agent(thread, _("wants to schedule a visit"))
        return None

    if reply_id == "visit_no":
        outbound.send_text(phone, _("No problem — I'll keep you posted on new "
                                    "listings."), force=True)
        return None
    return None


def _record_visit_feedback(thread, outcome):
    """Post-visit tap updates the Site Visit, the Deal stage, and sentiment."""
    deal = thread.deal or frappe.db.get_value("RE Deal", {"lead": thread.lead}, "name")
    visit = deal and frappe.db.get_value(
        "Site Visit", {"deal": deal}, "name", order_by="visit_datetime desc")
    if visit:
        frappe.db.set_value("Site Visit", visit,
                            {"outcome": outcome,
                             "feedback": _("Captured via WhatsApp feedback prompt")})
    if deal:
        if outcome == "Interested":
            frappe.db.set_value("RE Deal", deal, "pipeline_stage", "Negotiation")
        elif outcome == "Not Interested":
            frappe.db.set_value("RE Deal", deal,
                                {"pipeline_stage": "Lost",
                                 "lost_reason": _("Not interested after site visit")})
        elif outcome == "Need Discount":
            frappe.db.set_value("RE Deal", deal, "pipeline_stage", "Negotiation")
    thread.db_set("stage", "Post Visit")
    _append_message(thread, "Inbound", "interactive", f"Visit feedback: {outcome}")

    outbound.send_text(thread.phone_number,
                       _("Thank you — noted. Your agent will follow up."), force=True)
    if thread.agent:
        _notify_agent(thread, _("gave visit feedback: {0}").format(outcome))
    from re_voice.ai.insights import analyse_sentiment
    frappe.enqueue("re_voice.ai.insights.analyse_sentiment", queue="long",
                   thread_name=thread.name, enqueue_after_commit=True)
    if thread.lead:
        from re_voice.ai.scoring import recompute_lead_score
        recompute_lead_score(thread.lead)
    return outcome


def _notify_agent(thread, what):
    agent_number = frappe.db.get_value("RE Agent", thread.agent,
                                       ["whatsapp_number", "mobile"], as_dict=True)
    number = agent_number and (agent_number.whatsapp_number or agent_number.mobile)
    if number and outbound.window_open(number):
        outbound.send_text(number, _("{0} ({1}) {2}.").format(
            thread.display_name, thread.phone_number, what))
    user = frappe.db.get_value("RE Agent", thread.agent, "user")
    if user:
        frappe.get_doc({
            "doctype": "Notification Log", "for_user": user, "type": "Alert",
            "document_type": "Customer Thread", "document_name": thread.name,
            "subject": _("{0} {1}").format(thread.display_name, what),
        }).insert(ignore_permissions=True)
