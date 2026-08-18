"""Transparent lead scoring. Every score persists its components and a plain
reason string — an agent must be able to see why a lead is 82."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, nowdate

BANDS = ("Hot", "Warm", "Cold")


def recompute_lead_score(lead_name):
    model = frappe.get_cached_doc("Lead Score Model")
    lead = frappe.get_doc("RE Lead", lead_name)

    budget = _budget_fit(lead)
    frequency = _frequency(lead, model)
    visits = _visits(lead, model)
    response = _response_speed(lead, model)
    loan = 1.0 if lead.get("loan_required") else 0.0

    components = {
        "score_budget": round(budget * cint(model.weight_budget)),
        "score_frequency": round(frequency * cint(model.weight_frequency)),
        "score_visits": round(visits * cint(model.weight_visits)),
        "score_response": round(response * cint(model.weight_response)),
        "score_loan": round(loan * cint(model.weight_loan)),
    }
    total = sum(components.values())
    band = ("Hot" if total >= cint(model.hot_threshold)
            else "Warm" if total >= cint(model.warm_threshold) else "Cold")

    reason = _(
        "Budget {0}/{1}, conversation {2}/{3}, visits {4}/{5}, response {6}/{7}, "
        "loan {8}/{9}.").format(
        components["score_budget"], model.weight_budget,
        components["score_frequency"], model.weight_frequency,
        components["score_visits"], model.weight_visits,
        components["score_response"], model.weight_response,
        components["score_loan"], model.weight_loan)

    frappe.get_doc(dict({"doctype": "Lead Score Log", "lead": lead_name,
                         "total_score": total, "band": band, "reason": reason},
                        **components)).insert(ignore_permissions=True)
    frappe.db.set_value("RE Lead", lead_name,
                        {"lead_score": total, "score_band": band},
                        update_modified=False)
    return {"total": total, "band": band, "reason": reason, **components}


def _budget_fit(lead):
    """Does stated budget reach available inventory? No budget = unknown, not zero."""
    budget = flt(lead.budget_max or lead.budget_min)
    if not budget:
        return 0.3
    cheapest = frappe.db.sql("""
        SELECT MIN(headline_price) FROM `tabListing` WHERE is_published = 1
    """)[0][0]
    if not cheapest:
        return 0.5
    if budget >= flt(cheapest) * 1.25:
        return 1.0
    if budget >= flt(cheapest):
        return 0.75
    if budget >= flt(cheapest) * 0.8:
        return 0.4
    return 0.1


def _frequency(lead, model):
    thread = frappe.db.get_value("Customer Thread", {"lead": lead.name}, "name")
    if not thread:
        return 0.0
    since = add_days(nowdate(), -cint(model.frequency_window_days or 14))
    count = frappe.db.count("Thread Message",
                            {"parent": thread, "direction": "Inbound",
                             "sent_at": [">=", since]})
    target = max(cint(model.frequency_target or 6), 1)
    return min(count / target, 1.0)


def _visits(lead, model):
    deal = frappe.db.get_value("RE Deal", {"lead": lead.name}, "name")
    if not deal:
        return 0.0
    visits = frappe.get_all("Site Visit", filters={"deal": deal}, fields=["outcome"])
    if not visits:
        return 0.0
    target = max(cint(model.visits_target or 2), 1)
    base = min(len(visits) / target, 1.0)
    if any(v.outcome == "Interested" for v in visits):
        return min(base + 0.25, 1.0)
    if all(v.outcome == "Not Interested" for v in visits if v.outcome):
        return base * 0.3
    return base


def _response_speed(lead, model):
    thread = frappe.db.get_value("Customer Thread", {"lead": lead.name}, "name")
    if not thread:
        return 0.0
    rows = frappe.get_all("Thread Message", filters={"parent": thread},
                          fields=["direction", "sent_at"], order_by="sent_at asc")
    gaps = []
    last_outbound = None
    for row in rows:
        if row.direction == "Outbound":
            last_outbound = row.sent_at
        elif last_outbound and row.sent_at:
            gaps.append((row.sent_at - last_outbound).total_seconds() / 60.0)
            last_outbound = None
    if not gaps:
        return 0.0
    gaps.sort()
    median = gaps[len(gaps) // 2]
    target = max(cint(model.response_target_minutes or 60), 1)
    return 1.0 if median <= target else max(0.0, min(target / median, 1.0))


def recompute_all_scores():
    """Nightly sweep over leads that are still in play."""
    if not frappe.db.get_single_value("AI Settings", "enable_scoring"):
        return
    for name in frappe.get_all("RE Lead",
                               filters={"status": ["in", ["New", "Contacted",
                                                          "Qualified"]]},
                               pluck="name"):
        try:
            recompute_lead_score(name)
        except Exception:
            frappe.log_error(title="re_voice: scoring failed", message=name)
