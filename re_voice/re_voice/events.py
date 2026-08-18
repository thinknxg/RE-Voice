"""Document hooks — rescore on the events that actually move a lead."""

import frappe


def on_site_visit_update(doc, method=None):
    if not doc.outcome:
        return
    lead = frappe.db.get_value("RE Deal", doc.deal, "lead")
    if lead and frappe.db.get_single_value("AI Settings", "enable_scoring"):
        frappe.enqueue("re_voice.ai.scoring.recompute_lead_score", queue="long",
                       lead_name=lead, enqueue_after_commit=True)


def on_lead_insert(doc, method=None):
    if frappe.db.get_single_value("AI Settings", "enable_scoring"):
        frappe.enqueue("re_voice.ai.scoring.recompute_lead_score", queue="long",
                       lead_name=doc.name, enqueue_after_commit=True)
