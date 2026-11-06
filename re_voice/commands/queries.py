"""Read-only commands. Results come back as WhatsApp list messages (max 10 rows)."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from re_voice.channel import outbound
from re_voice.commands.helpers import current_lead, remember

MAX_ROWS = 10


def search_property(intent, entities):
    filters = {"is_published": 1}
    if entities.get("unit_type"):
        filters["unit_type"] = entities["unit_type"]
    if entities.get("bedrooms"):
        filters["bedrooms"] = [">=", entities["bedrooms"]]
    if entities.get("location"):
        filters["locality"] = ["like", f"%{entities['location']}%"]
    budget = flt(entities.get("budget") or 0)
    if budget:
        filters["headline_price"] = ["<=", budget * 1.1]  # 10% tolerance

    listings = frappe.get_all(
        "Listing", filters=filters,
        fields=["name", "title", "headline_price", "unit_type", "locality", "unit"],
        order_by="featured desc, headline_price asc", page_length=MAX_ROWS)
    if not listings:
        return {"reply": _("No published properties match that. Try a wider budget "
                           "or a different area.")}

    remember(intent.from_number, {"results": [l.unit for l in listings]})
    rows = [(f"unit::{l.unit}", l.title[:24],
             f"{frappe.utils.fmt_money(l.headline_price)} · {l.locality or ''}")
            for l in listings]
    outbound.send_list(intent.from_number,
                       _("{0} matching properties:").format(len(listings)),
                       _("View"), rows, force=True)
    return {"doctype": "Listing", "name": listings[0].name}


def find_similar(intent, entities):
    from re_voice.commands.helpers import last_results
    results = last_results(intent.from_number)
    if not results:
        return {"reply": _("Search for a property first, then ask for similar ones.")}
    reference = frappe.db.get_value("Unit", results[0],
                                    ["unit_type", "bedrooms", "property"], as_dict=True)
    return search_property(intent, {"unit_type": reference.unit_type,
                                    "bedrooms": reference.bedrooms})


def todays_followups(intent, entities):
    todos = frappe.get_all(
        "ToDo", filters={"allocated_to": frappe.session.user, "status": "Open",
                         "date": ["<=", nowdate()]},
        fields=["name", "description", "reference_name"],
        order_by="date asc", page_length=MAX_ROWS)
    if not todos:
        return {"reply": _("Nothing due today — you're clear.")}
    lines = "\n".join(f"• {t.description[:60]}" for t in todos)
    return {"reply": _("{0} follow-ups due:\n{1}").format(len(todos), lines)}


def pending_leads(intent, entities):
    leads = frappe.get_all(
        "RE Lead", filters={"assigned_agent": intent.agent,
                            "status": ["in", ["New", "Contacted"]]},
        fields=["name", "full_name", "mobile", "lead_score"],
        order_by="lead_score desc, creation asc", page_length=MAX_ROWS)
    if not leads:
        return {"reply": _("No pending leads assigned to you.")}
    lines = "\n".join(
        f"• {l.full_name} ({l.mobile}) — score {l.lead_score or 0}" for l in leads)
    return {"reply": _("{0} pending leads:\n{1}").format(len(leads), lines)}


def call_customer(intent, entities):
    """The server cannot place calls — reply with a tap-to-dial link."""
    lead_name = entities.get("lead") or current_lead(intent.from_number)
    mobile = entities.get("mobile") or (
        lead_name and frappe.db.get_value("RE Lead", lead_name, "mobile"))
    if not mobile:
        return {"reply": _("I don't have a number for that contact.")}
    return {"reply": _("Tap to call: tel:{0}").format(mobile)}
