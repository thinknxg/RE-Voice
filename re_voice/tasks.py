"""Scheduled jobs for re_voice."""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, now_datetime, nowdate


def post_visit_feedback_prompts():
    """T+3h after a visit, ask for feedback. Uses an approved template when the
    24-hour window has closed — which it usually has."""
    from re_voice.channel import outbound
    from re_voice.customer.pipeline import FEEDBACK_OPTIONS

    now = now_datetime()
    window_start = add_to_date(now, hours=-6)
    window_end = add_to_date(now, hours=-3)
    visits = frappe.get_all(
        "Site Visit",
        filters={"outcome": ["in", ["", None]],
                 "visit_datetime": ["between", [window_start, window_end]]},
        fields=["name", "deal", "unit", "client_mobile"])

    for visit in visits:
        number = visit.client_mobile or frappe.db.get_value(
            "RE Deal", visit.deal, "mobile")
        if not number or frappe.db.exists("Sentiment Reading",
                                          {"customer_thread": visit.name}):
            continue
        if outbound.window_open(number):
            outbound.send_list(number, _("How was the visit?"), _("Choose"),
                               FEEDBACK_OPTIONS)
        else:
            template = frappe.db.get_value(
                "WhatsApp Template",
                {"purpose": "Post Visit Feedback", "approval_status": "Approved"},
                "name")
            if template:
                outbound.send_template(number, template,
                                       [frappe.db.get_value("RE Deal", visit.deal,
                                                            "tenant_name") or ""])
            else:
                frappe.log_error(
                    title="re_voice: no approved post-visit template",
                    message=f"Visit {visit.name} outside the 24h window and no "
                            f"approved template is registered.")


def nightly_scoring():
    from re_voice.ai.scoring import recompute_all_scores
    recompute_all_scores()


def refresh_thread_summaries():
    """Summarize threads that moved today, so managers read a brief not a log."""
    if not frappe.db.get_single_value("AI Settings", "enable_summary"):
        return
    from re_voice.ai.insights import summarize_thread
    threads = frappe.get_all(
        "Customer Thread",
        filters={"modified": [">=", nowdate()],
                 "stage": ["in", ["Options Sent", "Visit Scheduled", "Post Visit",
                                   "Negotiation"]]},
        pluck="name", limit=100)
    for name in threads:
        try:
            summarize_thread(name, post_to_lead=False)
        except Exception:
            frappe.log_error(title="re_voice: summary failed", message=name)


def purge_expired_audio():
    """Delete audio files past the retention window; transcripts are retained."""
    days = frappe.db.get_single_value("AI Settings", "audio_retention_days")
    if not days:
        return
    cutoff = add_days(nowdate(), -int(days))
    stale = frappe.get_all("Voice Message",
                           filters={"creation": ["<", cutoff],
                                    "audio_file": ["!=", ""],
                                    "status": ["!=", "Audio Purged"]},
                           fields=["name", "audio_file"], limit=500)
    for row in stale:
        try:
            for file_name in frappe.get_all("File",
                                            filters={"file_url": row.audio_file},
                                            pluck="name"):
                frappe.delete_doc("File", file_name, ignore_permissions=True,
                                  delete_permanently=True)
            frappe.db.set_value("Voice Message", row.name,
                                {"audio_file": None, "status": "Audio Purged"})
        except Exception:
            frappe.log_error(title="re_voice: audio purge failed", message=row.name)


def reset_monthly_spend():
    """Runs on the 1st; the usage log keeps history, this is just the display field."""
    if nowdate().endswith("-01"):
        frappe.db.set_single_value("AI Settings", "month_spend", 0)
