"""Site visits, reminders and tasks."""

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, nowdate

from re_voice.commands.helpers import current_deal, last_results, remember


def book_visit(intent, entities):
    deal_name = entities.get("deal") or current_deal(intent.from_number)
    if not deal_name:
        return {"reply": _("Which deal is the visit for? Open or create the deal first.")}
    when = entities.get("datetime") or entities.get("date")
    if not when:
        return {"reply": _("When should I book it? For example 'tomorrow at 4pm'.")}
    unit = entities.get("unit") or frappe.db.get_value("RE Deal", deal_name, "unit")
    if not unit:
        results = last_results(intent.from_number)
        unit = results[0] if results else None
    if not unit:
        return {"reply": _("Which property? Search for one first, then book the visit.")}

    visit = frappe.new_doc("Site Visit")
    visit.deal = deal_name
    visit.unit = unit
    visit.visit_datetime = get_datetime(when)
    visit.agent = intent.agent
    visit.insert()
    frappe.db.set_value("RE Deal", deal_name, "pipeline_stage", "Site Visit Scheduled")
    return {"doctype": "Site Visit", "name": visit.name,
            "reply": _("Visit booked: {0} at {1} on {2}.").format(
                unit, frappe.format(visit.visit_datetime, {"fieldtype": "Datetime"}),
                deal_name)}


def cancel_visit(intent, entities):
    deal_name = entities.get("deal") or current_deal(intent.from_number)
    visit = entities.get("visit") or frappe.db.get_value(
        "Site Visit", {"deal": deal_name, "outcome": ["in", ["", None]]},
        "name", order_by="visit_datetime desc")
    if not visit:
        return {"reply": _("I couldn't find an upcoming visit to cancel.")}
    frappe.db.set_value("Site Visit", visit, "outcome", "No Show")
    frappe.get_doc("Site Visit", visit).add_comment(
        "Comment", _("Cancelled via voice command."))
    return {"doctype": "Site Visit", "name": visit,
            "reply": _("Visit {0} cancelled.").format(visit)}


def schedule_reminder(intent, entities):
    when = entities.get("datetime") or entities.get("date") or \
        add_to_date(nowdate(), days=1)
    description = entities.get("notes") or intent.transcript
    reference = current_deal(intent.from_number)
    todo = frappe.get_doc({
        "doctype": "ToDo",
        "allocated_to": frappe.session.user,
        "date": get_datetime(when).date() if when else nowdate(),
        "description": description[:500],
        "reference_type": "RE Deal" if reference else None,
        "reference_name": reference,
    }).insert()
    return {"doctype": "ToDo", "name": todo.name,
            "reply": _("Reminder set for {0}.").format(
                frappe.format(todo.date, {"fieldtype": "Date"}))}


create_task = schedule_reminder
