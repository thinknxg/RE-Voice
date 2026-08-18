"""Outbound WhatsApp: text, interactive buttons/lists, media and templates.

Builds on re_crm's WhatsApp Settings. Every send respects the 24-hour customer
service window: free-form outside it is refused and a template is required."""

import frappe
from frappe import _
from frappe.utils import cstr, now_datetime

BUTTON_LIMIT = 3          # Meta hard limit
LIST_ROW_LIMIT = 10       # Meta hard limit
LIST_TITLE_CHARS = 24


def _settings():
    return frappe.get_cached_doc("WhatsApp Settings")


def _api(payload, reference=None):
    """POST to the Cloud API. Logs to WhatsApp Webhook Log as an outbound record."""
    settings = _settings()
    log = frappe.get_doc({
        "doctype": "WhatsApp Webhook Log",
        "from_number": payload.get("to"),
        "message_type": payload.get("type"),
        "direction": "Outbound",
        "status": "Processing",
        "payload": frappe.as_json(payload),
    }).insert(ignore_permissions=True)

    if not settings.enabled:
        log.db_set("status", "Ignored")
        log.db_set("error", "WhatsApp Settings disabled")
        return None
    try:
        url = (f"https://graph.facebook.com/{settings.api_version or 'v19.0'}/"
               f"{settings.phone_number_id}/messages")
        response = frappe.make_post_request(
            url,
            headers={"Authorization": f"Bearer {settings.get_password('access_token')}",
                     "Content-Type": "application/json"},
            data=frappe.as_json(dict(payload, messaging_product="whatsapp")))
        log.db_set("status", "Processed")
        return response
    except Exception:
        log.db_set("status", "Failed")
        log.db_set("error", frappe.get_traceback()[-500:])
        frappe.log_error(title="re_voice: outbound send failed",
                         message=f"Log {log.name} / ref {reference}")
        return None


def window_open(phone_number):
    """True when a free-form (non-template) message may be sent."""
    expires = frappe.db.get_value("Conversation Session", phone_number,
                                  "window_expires_at")
    return bool(expires and now_datetime() < expires)


def send_text(to, body, force=False):
    """Free-form text. Refused outside the 24h window unless force=True (agent
    channel, where the agent has just messaged us)."""
    if not (force or window_open(to)):
        frappe.log_error(
            title="re_voice: free-form blocked by 24h window",
            message=f"to={to}; use send_template() instead")
        return None
    return _api({"to": to, "type": "text",
                 "text": {"preview_url": False, "body": cstr(body)[:4000]}})


def send_buttons(to, body, buttons, force=False):
    """buttons: list of (id, title). Max 3 — beyond that use send_list()."""
    if len(buttons) > BUTTON_LIMIT:
        return send_list(to, body, _("Choose"), [(bid, title, "")
                                                 for bid, title in buttons], force=force)
    if not (force or window_open(to)):
        return None
    return _api({
        "to": to, "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": cstr(body)[:1024]},
            "action": {"buttons": [
                {"type": "reply",
                 "reply": {"id": cstr(bid)[:256], "title": cstr(title)[:20]}}
                for bid, title in buttons]},
        }})


def send_list(to, body, button_label, rows, header=None, force=False):
    """rows: list of (id, title, description). Max 10."""
    if not (force or window_open(to)):
        return None
    payload_rows = [{"id": cstr(rid)[:200],
                     "title": cstr(title)[:LIST_TITLE_CHARS],
                     "description": cstr(desc)[:72]}
                    for rid, title, desc in rows[:LIST_ROW_LIMIT]]
    interactive = {
        "type": "list",
        "body": {"text": cstr(body)[:1024]},
        "action": {"button": cstr(button_label)[:20],
                   "sections": [{"title": _("Options"), "rows": payload_rows}]},
    }
    if header:
        interactive["header"] = {"type": "text", "text": cstr(header)[:60]}
    return _api({"to": to, "type": "interactive", "interactive": interactive})


def send_document(to, file_url, filename, caption=None, force=False):
    if not (force or window_open(to)):
        return None
    document = {"link": file_url, "filename": cstr(filename)[:200]}
    if caption:
        document["caption"] = cstr(caption)[:1000]
    return _api({"to": to, "type": "document", "document": document})


def send_location(to, latitude, longitude, name=None, address=None, force=False):
    if not (force or window_open(to)):
        return None
    location = {"latitude": latitude, "longitude": longitude}
    if name:
        location["name"] = cstr(name)[:100]
    if address:
        location["address"] = cstr(address)[:200]
    return _api({"to": to, "type": "location", "location": location})


def send_template(to, template_name, variables=None):
    """The only send permitted outside the 24-hour window."""
    template = frappe.db.get_value("WhatsApp Template", template_name,
                                   ["template_name", "language_code",
                                    "approval_status"], as_dict=True)
    if not template:
        frappe.log_error(title="re_voice: unknown template",
                         message=f"{template_name} is not registered")
        return None
    if template.approval_status != "Approved":
        frappe.log_error(
            title="re_voice: template not approved",
            message=f"{template_name} is {template.approval_status}; Meta will reject it")
        return None
    components = []
    if variables:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": cstr(v)[:1000]} for v in variables],
        })
    return _api({
        "to": to, "type": "template",
        "template": {"name": template.template_name,
                     "language": {"code": template.language_code or "en"},
                     "components": components},
    })


def reply(to, body, buttons=None, force=True):
    """Convenience for agent-channel replies (always inside the window)."""
    if buttons:
        return send_buttons(to, body, buttons, force=force)
    return send_text(to, body, force=force)
