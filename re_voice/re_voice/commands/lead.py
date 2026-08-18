"""Lead lifecycle handlers. Each takes (intent, entities) and returns
{"doctype", "name", "reply", "buttons"?}."""

import frappe
from frappe import _
from frappe.utils import flt

from re_voice.commands.helpers import current_lead, current_deal, remember


def create_lead(intent, entities):
    name = entities.get("name") or entities.get("full_name")
    mobile = entities.get("mobile") or entities.get("phone")
    if not (name and mobile):
        return {"reply": _("I need a name and a mobile number. Try: "
                           "'create lead named Rahul, number 9123456789'.")}
    lead = frappe.new_doc("RE Lead")
    lead.full_name = name
    lead.mobile = mobile
    lead.source = frappe.db.exists("Lead Source RE", "WhatsApp") or None
    lead.assigned_agent = intent.agent
    if entities.get("budget"):
        lead.budget_max = flt(entities["budget"])
    if entities.get("unit_type"):
        lead.preferred_property_type = _map_property_type(entities["unit_type"])
    if entities.get("location"):
        lead.preferred_location = entities["location"]
    lead.insert()
    remember(intent.from_number, {"lead": lead.name})
    return {"doctype": "RE Lead", "name": lead.name,
            "reply": _("Lead {0} created for {1}.").format(lead.name, name)}


def _map_property_type(unit_type):
    if unit_type in ("Shop", "Office", "Warehouse", "Villa"):
        return unit_type
    return "Apartment"


def update_lead(intent, entities):
    lead_name = entities.get("lead") or current_lead(intent.from_number)
    if not lead_name:
        return {"reply": _("Which lead? Mention the name or open one first.")}
    lead = frappe.get_doc("RE Lead", lead_name)
    changed = []
    if entities.get("budget"):
        lead.budget_max = flt(entities["budget"])
        changed.append(_("budget"))
    if entities.get("unit_type"):
        lead.preferred_property_type = _map_property_type(entities["unit_type"])
        changed.append(_("property type"))
    if entities.get("location"):
        lead.preferred_location = entities["location"]
        changed.append(_("location"))
    if entities.get("notes"):
        lead.notes = f"{lead.notes or ''}\n{entities['notes']}".strip()
        changed.append(_("notes"))
    if not changed:
        return {"reply": _("Nothing to update — tell me the budget, type or area.")}
    lead.save()
    return {"doctype": "RE Lead", "name": lead.name,
            "reply": _("Updated {0} on {1}.").format(", ".join(changed), lead.name)}


def add_note(intent, entities):
    """Voice note -> CRM note, preserving the native transcript alongside English."""
    reference = current_deal(intent.from_number) or current_lead(intent.from_number)
    if not reference:
        return {"reply": _("Open a lead or deal first, then send the note.")}
    doctype = "RE Deal" if reference.startswith("DEAL") else "RE Lead"
    body = intent.transcript
    if intent.voice_message:
        voice = frappe.db.get_value("Voice Message", intent.voice_message,
                                    ["transcript", "translation", "detected_language"],
                                    as_dict=True)
        if voice and voice.translation:
            body = (f"{voice.translation}\n\n"
                    f"[{voice.detected_language}] {voice.transcript}")
    frappe.get_doc(doctype, reference).add_comment("Comment", body)
    return {"doctype": doctype, "name": reference,
            "reply": _("Note added to {0}.").format(reference)}


def qualify_lead(intent, entities):
    lead_name = entities.get("lead") or current_lead(intent.from_number)
    if not lead_name:
        return {"reply": _("Which lead should I qualify?")}
    lead = frappe.get_doc("RE Lead", lead_name)
    lead.status = "Qualified"
    lead.save()
    from re_voice.ai.scoring import recompute_lead_score
    score = recompute_lead_score(lead.name)
    return {"doctype": "RE Lead", "name": lead.name,
            "reply": _("{0} marked Qualified. Score {1} ({2}).").format(
                lead.name, score.get("total"), score.get("band"))}


def _set_stage(intent, entities, stage, requires_reason=False):
    deal_name = entities.get("deal") or current_deal(intent.from_number)
    if not deal_name:
        return {"reply": _("Which deal? Say the client name or open the deal first.")}
    deal = frappe.get_doc("RE Deal", deal_name)
    if requires_reason:
        deal.lost_reason = entities.get("reason") or _("Marked via voice command")
    deal.pipeline_stage = stage
    deal.save()
    return {"doctype": "RE Deal", "name": deal.name,
            "reply": _("Deal {0} moved to {1}.").format(deal.name, stage)}


def mark_won(intent, entities):
    deal_name = entities.get("deal") or current_deal(intent.from_number)
    if deal_name and not frappe.db.get_value("RE Deal", deal_name, "lease_contract"):
        return {"reply": _("That deal needs a submitted Lease Contract before it can "
                           "be marked Won. Create the lease first.")}
    return _set_stage(intent, entities, "Won")


def mark_lost(intent, entities):
    return _set_stage(intent, entities, "Lost", requires_reason=True)


def close_lead(intent, entities):
    lead_name = entities.get("lead") or current_lead(intent.from_number)
    if not lead_name:
        return {"reply": _("Which lead should I close?")}
    frappe.db.set_value("RE Lead", lead_name, "status", "Disqualified")
    return {"doctype": "RE Lead", "name": lead_name,
            "reply": _("Lead {0} closed.").format(lead_name)}


def assign_agent(intent, entities):
    target = entities.get("agent")
    deal_name = entities.get("deal") or current_deal(intent.from_number)
    lead_name = entities.get("lead") or current_lead(intent.from_number)
    if not target:
        return {"reply": _("Which agent should I assign it to?")}
    agent = frappe.db.get_value("RE Agent", {"agent_name": ["like", f"%{target}%"],
                                             "is_active": 1})
    if not agent:
        return {"reply": _("I couldn't find an active agent called {0}.").format(target)}
    if deal_name:
        frappe.db.set_value("RE Deal", deal_name, "assigned_agent", agent)
        reference, doctype = deal_name, "RE Deal"
    elif lead_name:
        frappe.db.set_value("RE Lead", lead_name, "assigned_agent", agent)
        reference, doctype = lead_name, "RE Lead"
    else:
        return {"reply": _("Open a lead or deal first.")}
    return {"doctype": doctype, "name": reference,
            "reply": _("{0} assigned to {1}.").format(reference, target)}


transfer_lead = assign_agent
