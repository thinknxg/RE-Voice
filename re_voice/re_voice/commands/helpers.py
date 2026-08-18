"""Conversation context: what 'this lead' and 'the second one' refer to."""

import frappe


def _session(phone):
    if frappe.db.exists("Conversation Session", phone):
        return frappe.get_doc("Conversation Session", phone)
    return None


def context(phone):
    session = _session(phone)
    if not session or not session.context:
        return {}
    return frappe.parse_json(session.context) or {}


def remember(phone, values):
    session = _session(phone)
    if not session:
        return
    merged = dict(context(phone), **values)
    session.db_set("context", frappe.as_json(merged))


def current_lead(phone):
    return context(phone).get("lead")


def current_deal(phone):
    return context(phone).get("deal")


def last_results(phone):
    return context(phone).get("results") or []
