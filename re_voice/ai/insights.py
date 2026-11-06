"""Sentiment and conversation summarization."""

import frappe
from frappe import _
from frappe.utils import cstr, flt, now_datetime

from re_voice.ai.client import llm_complete, parse_json_response

SENTIMENT_SYSTEM = (
    "You assess a property buyer's sentiment from their messages. Reply with JSON "
    'only: {"label": "Positive|Neutral|Negative", "confidence": <0-100>, '
    '"rationale": "<one short sentence>"}.')

SUMMARY_SYSTEM = (
    "You summarize a real-estate sales conversation for the agent's CRM. Be terse "
    "and factual. Cover: requirement, budget, objections, agreed next step. "
    "Four short lines maximum. No preamble.")


def analyse_sentiment(thread_name):
    if not frappe.db.get_single_value("AI Settings", "enable_sentiment"):
        return None
    thread = frappe.get_doc("Customer Thread", thread_name)
    inbound = [m.body for m in thread.messages if m.direction == "Inbound" and m.body]
    if not inbound:
        return None
    raw = llm_complete("\n".join(inbound[-15:]), system=SENTIMENT_SYSTEM,
                       task="Sentiment", json_mode=True,
                       reference_doctype="Customer Thread", reference_name=thread_name)
    parsed = parse_json_response(raw)
    if not parsed or parsed.get("label") not in ("Positive", "Neutral", "Negative"):
        return None

    reading = frappe.get_doc({
        "doctype": "Sentiment Reading", "customer_thread": thread_name,
        "lead": thread.lead, "label": parsed["label"],
        "confidence": flt(parsed.get("confidence") or 0),
        "rationale": cstr(parsed.get("rationale"))[:500],
        "model": frappe.db.get_single_value("AI Settings", "llm_model"),
    }).insert(ignore_permissions=True)
    if thread.lead:
        frappe.db.set_value("RE Lead", thread.lead,
                            {"sentiment": parsed["label"],
                             "sentiment_confidence": flt(parsed.get("confidence") or 0)},
                            update_modified=False)
    return reading.name


def summarize_thread(thread_name, post_to_lead=True):
    if not frappe.db.get_single_value("AI Settings", "enable_summary"):
        return None
    thread = frappe.get_doc("Customer Thread", thread_name)
    if not thread.messages:
        return None
    transcript = "\n".join(
        f"{m.direction}: {m.body}" for m in thread.messages[-40:] if m.body)
    summary = llm_complete(transcript, system=SUMMARY_SYSTEM, task="Summary",
                           reference_doctype="Customer Thread",
                           reference_name=thread_name)
    if not summary:
        return None
    thread.db_set("last_summary", cstr(summary)[:1000])
    thread.db_set("summary_updated_on", now_datetime())
    if post_to_lead and thread.lead:
        frappe.get_doc("RE Lead", thread.lead).add_comment(
            "Comment", _("Conversation summary:\n{0}").format(summary))
    return summary


def summarize_command(intent, entities):
    """Voice command handler: 'summarize this lead'."""
    from re_voice.commands.helpers import current_lead
    lead_name = entities.get("lead") or current_lead(intent.from_number)
    if not lead_name:
        return {"reply": _("Which lead should I summarize?")}
    thread = frappe.db.get_value("Customer Thread", {"lead": lead_name}, "name")
    if not thread:
        return {"reply": _("No WhatsApp conversation is linked to that lead yet.")}
    summary = summarize_thread(thread)
    return {"doctype": "RE Lead", "name": lead_name,
            "reply": summary or _("Summarization is unavailable right now.")}
