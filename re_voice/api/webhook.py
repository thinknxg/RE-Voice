"""Meta Cloud API webhook. ACK fast, verify hard, process in the background.

Security posture:
  - GET verification uses the configured verify token.
  - POST requires a valid X-Hub-Signature-256 HMAC over the raw body.
  - Sender classification happens before any handler runs; a number that does not
    match an active, voice-enabled RE Agent can never reach a command handler.
"""

import hashlib
import hmac

import frappe
from frappe import _
from frappe.utils import cstr


@frappe.whitelist(allow_guest=True)
def verify():
    """GET handshake from Meta when the callback URL is registered."""
    args = frappe.form_dict
    settings = frappe.get_cached_doc("WhatsApp Settings")
    expected = getattr(settings, "webhook_verify_token", None) or \
        frappe.conf.get("whatsapp_verify_token")
    if args.get("hub.mode") == "subscribe" and expected and \
            hmac.compare_digest(cstr(args.get("hub.verify_token")), cstr(expected)):
        frappe.local.response["type"] = "page"
        frappe.local.response["page_name"] = cstr(args.get("hub.challenge"))
        return cstr(args.get("hub.challenge"))
    raise frappe.PermissionError(_("Webhook verification failed."))


def _signature_valid(raw_body):
    app_secret = frappe.conf.get("whatsapp_app_secret")
    if not app_secret:
        # Fail closed: an unsigned webhook endpoint is an open write path.
        frappe.log_error(title="re_voice: whatsapp_app_secret not set in site config",
                         message="Inbound webhook rejected — configure the app secret.")
        return False
    header = frappe.get_request_header("X-Hub-Signature-256") or ""
    if not header.startswith("sha256="):
        return False
    digest = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, header.split("=", 1)[1])


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive():
    """Entry point. Persists, ACKs, and queues — never processes inline."""
    raw = frappe.request.get_data() or b""
    if not _signature_valid(raw):
        raise frappe.PermissionError(_("Invalid webhook signature."))

    payload = frappe.parse_json(raw.decode("utf-8") or "{}")
    for message in _iter_messages(payload):
        _enqueue_message(message)
    return {"status": "ok"}


def _iter_messages(payload):
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name")
                        for c in value.get("contacts", []) or []}
            for message in value.get("messages", []) or []:
                message["_profile_name"] = contacts.get(message.get("from"))
                yield message


def _enqueue_message(message):
    message_id = message.get("id")
    if not message_id or frappe.db.exists("WhatsApp Webhook Log",
                                          {"message_id": message_id}):
        return  # Meta retries aggressively; dedupe on message id
    log = frappe.get_doc({
        "doctype": "WhatsApp Webhook Log",
        "message_id": message_id,
        "from_number": message.get("from"),
        "message_type": message.get("type"),
        "direction": "Inbound",
        "status": "Received",
        "payload": frappe.as_json(message),
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.enqueue("re_voice.api.webhook.process_log", queue="short",
                   job_name=f"wa-{message_id}", log_name=log.name,
                   enqueue_after_commit=True)


def process_log(log_name):
    """Background worker: classify the sender, then route."""
    from re_voice.customer.pipeline import handle_customer_message
    from re_voice.intent.dispatcher import handle_agent_message

    log = frappe.get_doc("WhatsApp Webhook Log", log_name)
    log.db_set("status", "Processing")
    try:
        message = frappe.parse_json(log.payload)
        phone = message.get("from")
        agent = _resolve_agent(phone)
        log.db_set("actor", "Agent" if agent else "Customer")

        session = _touch_session(phone, agent, message.get("_profile_name"))
        if agent:
            handle_agent_message(message, agent, session)
        else:
            handle_customer_message(message, session)
        log.db_set("status", "Processed")
    except Exception:
        log.db_set("status", "Failed")
        log.db_set("error", frappe.get_traceback()[-500:])
        frappe.log_error(title="re_voice: message processing failed", message=log_name)


def _resolve_agent(phone):
    """A command sender must be an active, voice-enabled RE Agent whose number
    matches. Anything else is a customer."""
    if not phone:
        return None
    digits = cstr(phone).lstrip("+")
    candidates = frappe.db.sql("""
        SELECT name FROM `tabRE Agent`
        WHERE is_active = 1 AND IFNULL(voice_enabled, 0) = 1
          AND REPLACE(REPLACE(REPLACE(IFNULL(whatsapp_number, mobile), '+', ''),
                              ' ', ''), '-', '') = %s
    """, digits, as_dict=True)
    return candidates[0].name if candidates else None


def _touch_session(phone, agent, profile_name=None):
    """Create or refresh the session and roll the 24-hour service window."""
    from frappe.utils import add_to_date, now_datetime
    if frappe.db.exists("Conversation Session", phone):
        session = frappe.get_doc("Conversation Session", phone)
    else:
        session = frappe.new_doc("Conversation Session")
        session.phone_number = phone
        session.locale_profile = frappe.db.get_value(
            "Voice Locale Profile", {"is_default": 1}, "name")
        session.insert(ignore_permissions=True)
    session.db_set("actor_type", "Agent" if agent else "Customer")
    if agent:
        session.db_set("agent", agent)
    now = now_datetime()
    session.db_set("last_inbound_at", now)
    session.db_set("window_expires_at", add_to_date(now, hours=24))
    return session.reload()
