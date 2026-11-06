"""Content sends: brochure, price list, location, quotation, booking form."""

import frappe
from frappe import _
from frappe.utils import get_url

from re_voice.channel import outbound
from re_voice.commands.helpers import current_deal, current_lead, last_results


def _customer_number(intent, entities):
    lead_name = entities.get("lead") or current_lead(intent.from_number)
    if lead_name:
        return frappe.db.get_value("RE Lead", lead_name, "mobile"), lead_name
    deal_name = current_deal(intent.from_number)
    if deal_name:
        return frappe.db.get_value("RE Deal", deal_name, "mobile"), deal_name
    return None, None


def _send_or_warn(number, sender):
    """Content to a customer must respect the 24-hour window."""
    if outbound.window_open(number):
        sender(force=False)
        return None
    return _("That customer is outside the 24-hour reply window, so I can only "
             "send an approved template. Ask them to message first, or use a "
             "follow-up template.")


def share_location(intent, entities):
    number, reference = _customer_number(intent, entities)
    if not number:
        return {"reply": _("Open a lead or deal first.")}
    results = last_results(intent.from_number)
    unit = entities.get("unit") or (results[0] if results else None)
    if not unit:
        return {"reply": _("Which property's location? Search for one first.")}
    prop = frappe.db.get_value("Unit", unit, "property")
    geo = frappe.db.get_value("Property", prop,
                              ["latitude", "longitude", "property_name",
                               "address_line"], as_dict=True)
    if not (geo and geo.latitude and geo.longitude):
        return {"reply": _("That property has no map coordinates saved.")}
    blocked = _send_or_warn(number, lambda force: outbound.send_location(
        number, geo.latitude, geo.longitude, geo.property_name, geo.address_line,
        force=force))
    return {"reply": blocked or _("Location sent to {0}.").format(reference)}


def _send_attachment(intent, entities, doctype_hint, label):
    number, reference = _customer_number(intent, entities)
    if not number:
        return {"reply": _("Open a lead or deal first.")}
    results = last_results(intent.from_number)
    unit = entities.get("unit") or (results[0] if results else None)
    prop = unit and frappe.db.get_value("Unit", unit, "property")
    attachment = None
    if prop:
        attachment = frappe.db.get_value(
            "File", {"attached_to_doctype": "Property", "attached_to_name": prop,
                     "file_name": ["like", f"%{doctype_hint}%"]}, "file_url")
    if not attachment:
        return {"reply": _("No {0} is attached to that property yet. Upload one to "
                           "the Property record first.").format(label)}
    blocked = _send_or_warn(number, lambda force: outbound.send_document(
        number, get_url(attachment), f"{label}.pdf", force=force))
    return {"reply": blocked or _("{0} sent to {1}.").format(label, reference)}


def send_brochure(intent, entities):
    return _send_attachment(intent, entities, "brochure", _("Brochure"))


def send_price_list(intent, entities):
    return _send_attachment(intent, entities, "price", _("Price List"))


def generate_quotation(intent, entities):
    """Creates a draft ERPNext Quotation — never submitted by voice."""
    lead_name = entities.get("lead") or current_lead(intent.from_number)
    if not lead_name:
        return {"reply": _("Which lead is the quotation for?")}
    lead = frappe.db.get_value("RE Lead", lead_name,
                               ["full_name", "unit_of_interest"], as_dict=True)
    unit = entities.get("unit") or lead.unit_of_interest
    if not unit:
        return {"reply": _("Which property should I quote?")}
    rate = frappe.db.get_value("Unit", unit, "annual_rent") or 0
    rent_item = frappe.db.get_single_value("Property Settings", "rent_item")
    if not rent_item:
        return {"reply": _("Set the Rent Item in Property Settings first.")}
    quotation = frappe.new_doc("Quotation")
    quotation.quotation_to = "Lead"
    quotation.party_name = lead_name
    quotation.append("items", {"item_code": rent_item, "qty": 1, "rate": rate,
                               "description": _("Annual rent — {0}").format(unit)})
    quotation.insert()
    return {"doctype": "Quotation", "name": quotation.name,
            "reply": _("Draft quotation {0} created for {1}. Review and send it "
                       "from the desk.").format(quotation.name, lead.full_name)}


def generate_booking_form(intent, entities):
    """Creates a draft Reservation — submission stays a deliberate desk action."""
    deal_name = entities.get("deal") or current_deal(intent.from_number)
    if not deal_name:
        return {"reply": _("Which deal is the booking for?")}
    deal = frappe.db.get_value("RE Deal", deal_name, ["unit", "tenant_name"],
                               as_dict=True)
    if not deal.unit:
        return {"reply": _("That deal has no unit selected.")}
    from frappe.utils import add_days, nowdate
    reservation = frappe.new_doc("Reservation")
    reservation.deal = deal_name
    reservation.unit = deal.unit
    reservation.booking_fee = entities.get("budget") or 0
    reservation.valid_till = add_days(nowdate(), 7)
    reservation.insert()
    return {"doctype": "Reservation", "name": reservation.name,
            "reply": _("Draft booking form {0} created for {1}. Submit it from the "
                       "desk to block the unit.").format(reservation.name,
                                                         deal.tenant_name)}
