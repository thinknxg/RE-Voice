#!/usr/bin/env python3
"""re_voice DocType JSON generator (Frappe v16). Controllers are hand-maintained."""
import json, os, re

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODULE = "RE Voice"
DOCTYPE_DIR = os.path.join(APP_ROOT, "re_voice", "re_voice", "doctype")
TS = "2026-01-01 00:00:00.000000"


def scrub(n): return re.sub(r"[\s-]+", "_", n.strip().lower())


def f(fieldname, fieldtype="Data", label=None, **kw):
    d = {"fieldname": fieldname, "fieldtype": fieldtype,
         "label": label or fieldname.replace("_", " ").title()}
    d.update(kw); return d


def sb(fieldname, label="", **kw): return f(fieldname, "Section Break", label, **kw)
def cb(i): return f(f"col_break_{i}", "Column Break", "")


def perm(role, **kw):
    base = {"role": role, "read": 1, "write": 1, "create": 1, "email": 1,
            "print": 1, "report": 1, "export": 1, "share": 1}
    base.update(kw); return base


MGR = [perm("RE Manager", delete=1), perm("System Manager", delete=1)]
OPS = MGR + [perm("RE Sales Manager"), perm("RE Sales Agent", write=0, create=0)]


def dt(name, fields, autoname=None, istable=0, issingle=0, title_field=None,
       perms=None, search_fields=None, track_changes=1):
    doc = {
        "actions": [], "allow_rename": 0, "autoname": autoname or "",
        "creation": TS, "doctype": "DocType", "editable_grid": 1, "engine": "InnoDB",
        "field_order": [x["fieldname"] for x in fields], "fields": fields,
        "index_web_pages_for_search": 0, "is_submittable": 0, "issingle": issingle,
        "istable": istable, "links": [], "modified": TS,
        "modified_by": "Administrator", "module": MODULE, "name": name,
        "owner": "Administrator",
        "naming_rule": "Expression" if (autoname or "").startswith("format:") else "",
        "permissions": [] if istable else (perms or MGR),
        "sort_field": "modified", "sort_order": "DESC", "states": [],
        "track_changes": track_changes,
    }
    if title_field: doc["title_field"] = title_field
    if search_fields: doc["search_fields"] = search_fields
    folder = os.path.join(DOCTYPE_DIR, scrub(name))
    os.makedirs(folder, exist_ok=True)
    init = os.path.join(folder, "__init__.py")
    if not os.path.exists(init): open(init, "w").close()
    with open(os.path.join(folder, f"{scrub(name)}.json"), "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True); fh.write("\n")
    print(f"  wrote {name}")


# ------------------------------------------------------------------ settings

def gen_ai_settings():
    dt("AI Settings", issingle=1, fields=[
        sb("gate_sb", "Enablement"),
        f("voice_enabled", "Check", label="Enable Voice Processing", default=0),
        f("llm_enabled", "Check", label="Enable LLM Intent Fallback", default=0),
        cb(1),
        f("monthly_budget", "Currency", label="Monthly AI Budget",
          description="When exceeded, Tier-1 commands keep working and LLM calls stop"),
        f("month_spend", "Currency", read_only=1, label="Spend This Month"),
        sb("asr_sb", "Speech to Text"),
        f("asr_provider", "Select", options="OpenAI Whisper API\nLocal Whisper\nNone",
          default="None"),
        f("asr_endpoint", "Data",
          description="Base URL for local Whisper, e.g. http://localhost:9000"),
        cb(2),
        f("asr_model", "Data", default="whisper-1"),
        f("asr_cost_per_minute", "Currency", default=0),
        sb("llm_sb", "Language Model"),
        f("llm_provider", "Select", options="Anthropic\nOpenAI\nCustom\nNone",
          default="None"),
        f("llm_endpoint", "Data"),
        f("llm_model", "Data"),
        cb(3),
        f("api_key", "Password"),
        f("llm_confidence_threshold", "Float", default=0.6,
          description="Below this, ask the user to clarify instead of acting"),
        sb("task_sb", "Task Toggles"),
        f("enable_translation", "Check", default=1),
        f("enable_sentiment", "Check", default=1),
        cb(4),
        f("enable_summary", "Check", default=1),
        f("enable_scoring", "Check", default=1),
        sb("retention_sb", "Retention"),
        f("audio_retention_days", "Int", default=90,
          description="Voice Message audio files are purged after this many days; "
                      "transcripts are kept"),
    ])


def gen_locale_profile():
    dt("Voice Locale Profile", autoname="field:locale_name",
       title_field="locale_name",
       fields=[
           f("locale_name", "Data", reqd=1, unique=1, in_list_view=1),
           f("is_default", "Check", in_list_view=1),
           f("languages", "Small Text", default="en",
             description="Comma-separated ISO codes accepted for ASR, e.g. en,ml,hi,ar"),
           f("number_system", "Select", options="International\nIndian",
             default="International", in_list_view=1,
             description="Indian enables lakh/crore parsing and formatting"),
           f("unit_vocabulary", "Select", options="BR\nBHK", default="BR",
             description="Whether '2 BHK' or '2BR' is the spoken form"),
           f("currency", "Link", options="Currency"),
           f("timezone", "Data", default="Asia/Muscat"),
       ], perms=MGR)


def gen_whatsapp_template():
    dt("WhatsApp Template", autoname="field:template_name",
       title_field="template_name",
       fields=[
           f("template_name", "Data", reqd=1, unique=1, in_list_view=1,
             description="Exact template name registered with Meta"),
           f("language_code", "Data", default="en", reqd=1),
           f("purpose", "Select", in_list_view=1, in_standard_filter=1,
             options="\nPost Visit Feedback\nFollow Up\nLead Welcome\n"
                     "Visit Reminder\nOther"),
           f("approval_status", "Select", options="Draft\nSubmitted\nApproved\nRejected",
             default="Draft", in_list_view=1),
           f("body_preview", "Small Text",
             description="Copy of the approved body; used to preview, not to send"),
           f("variable_map", "Small Text",
             description="JSON list naming each {{n}} variable, e.g. "
                         "[\"customer_name\", \"unit_title\"]"),
       ], perms=MGR)


# ------------------------------------------------------------------ channel

def gen_webhook_log():
    dt("WhatsApp Webhook Log", autoname="format:WHL-{######}",
       search_fields="message_id,from_number",
       fields=[
           f("message_id", "Data", unique=1, in_list_view=1,
             description="Meta message id; used to drop duplicate deliveries"),
           f("from_number", "Data", in_list_view=1, in_standard_filter=1),
           f("message_type", "Data", in_list_view=1),
           f("direction", "Select", options="Inbound\nOutbound", default="Inbound"),
           f("status", "Select", default="Received", in_list_view=1,
             in_standard_filter=1,
             options="Received\nProcessing\nProcessed\nIgnored\nFailed"),
           f("actor", "Select", options="\nAgent\nCustomer\nUnknown",
             in_standard_filter=1),
           f("payload", "Code", options="JSON"),
           f("error", "Small Text", read_only=1),
       ], perms=MGR)


def gen_conversation_session():
    dt("Conversation Session", autoname="field:phone_number",
       title_field="phone_number",
       fields=[
           sb("who_sb", "Party"),
           f("phone_number", "Data", reqd=1, unique=1, in_list_view=1),
           f("actor_type", "Select", options="Agent\nCustomer", default="Customer",
             in_list_view=1, in_standard_filter=1),
           f("agent", "Link", options="RE Agent"),
           f("lead", "Link", options="RE Lead"),
           cb(1),
           f("locale_profile", "Link", options="Voice Locale Profile"),
           f("last_inbound_at", "Datetime", read_only=1),
           f("window_expires_at", "Datetime", read_only=1,
             description="Free-form outbound is only permitted before this time"),
           sb("state_sb", "State"),
           f("pending_intent", "Link", options="Voice Intent", read_only=1,
             description="Awaiting a Confirm/Cancel tap"),
           f("context", "Code", options="JSON",
             description="Last search results and referenced documents, for follow-ups "
                         "like 'book a visit for the second one'"),
           f("consent_notified", "Check", read_only=1),
       ], perms=OPS)


# ------------------------------------------------------------------ voice

def gen_voice_message():
    dt("Voice Message", autoname="format:VM-{######}",
       search_fields="from_number,transcript",
       fields=[
           sb("src_sb", "Source"),
           f("from_number", "Data", in_list_view=1),
           f("media_id", "Data"),
           f("audio_file", "Attach", label="Original Audio"),
           cb(1),
           f("duration_seconds", "Float"),
           f("detected_language", "Data", in_list_view=1),
           f("status", "Select", default="Pending", in_list_view=1,
             in_standard_filter=1,
             options="Pending\nTranscribing\nTranscribed\nFailed\nAudio Purged"),
           sb("text_sb", "Transcription"),
           f("transcript", "Small Text", label="Native Transcript"),
           f("translation", "Small Text", label="English Translation"),
           sb("link_sb", "Links"),
           f("voice_intent", "Link", options="Voice Intent", read_only=1),
           f("reference_doctype", "Data", read_only=1),
           cb(2),
           f("reference_name", "Data", read_only=1),
           f("error", "Small Text", read_only=1),
       ], perms=OPS)


def gen_usage_log():
    dt("Voice Usage Log", autoname="format:VUL-{######}",
       fields=[
           f("task", "Select", in_list_view=1, in_standard_filter=1,
             options="\nASR\nIntent\nSummary\nSentiment\nTranslation\nMatching"),
           f("provider", "Data", in_list_view=1),
           f("audio_seconds", "Float"),
           f("input_tokens", "Int"),
           f("output_tokens", "Int"),
           f("cost", "Currency", in_list_view=1),
           f("reference_doctype", "Data"),
           f("reference_name", "Data"),
       ], perms=MGR)


# ------------------------------------------------------------------ intent

def gen_command_entity():
    dt("Command Entity", istable=1, fields=[
        f("entity_name", "Data", reqd=1, in_list_view=1),
        f("entity_type", "Select", reqd=1, in_list_view=1,
          options="\nText\nMoney\nInteger\nDate\nDateTime\nUnitType\nLink\nSelect"),
        f("target_field", "Data", in_list_view=1,
          description="Fieldname on the target DocType this entity fills"),
        f("options", "Data", description="Link target or Select options"),
        f("is_required", "Check", in_list_view=1),
    ])


def gen_voice_command():
    dt("Voice Command", autoname="field:command_name",
       title_field="command_name",
       search_fields="command_name,sample_phrases",
       fields=[
           sb("cmd_sb", "Command"),
           f("command_name", "Data", reqd=1, unique=1, in_list_view=1),
           f("command_group", "Select", in_list_view=1, in_standard_filter=1,
             options="\nLead Lifecycle\nScheduling\nContent\nQuery\nCapture\nComms"),
           f("enabled", "Check", default=1, in_list_view=1),
           cb(1),
           f("handler", "Data", reqd=1,
             description="Dotted path to the handler function"),
           f("needs_confirmation", "Check", in_list_view=1,
             description="Destructive or irreversible — require a Confirm tap"),
           f("agent_only", "Check", default=1),
           sb("match_sb", "Matching"),
           f("keywords", "Small Text",
             description="Comma-separated trigger keywords for the fast matcher"),
           f("sample_phrases", "Small Text",
             description="One phrase per line; used by both matcher tiers"),
           f("description", "Small Text",
             description="Shown to the LLM as the tool description"),
           sb("ent_sb", "Entities"),
           f("entities", "Table", options="Command Entity"),
       ], perms=MGR)


def gen_voice_intent():
    dt("Voice Intent", autoname="format:VI-{######}",
       search_fields="transcript,command",
       fields=[
           sb("in_sb", "Input"),
           f("from_number", "Data", in_list_view=1),
           f("agent", "Link", options="RE Agent", in_standard_filter=1),
           f("voice_message", "Link", options="Voice Message"),
           cb(1),
           f("transcript", "Small Text"),
           f("channel", "Select", options="Voice\nText\nInteractive", default="Voice"),
           sb("parse_sb", "Parse"),
           f("command", "Link", options="Voice Command", in_list_view=1,
             in_standard_filter=1),
           f("resolver", "Select", options="\nKeyword\nLLM\nInteractive",
             description="Which tier resolved this intent"),
           f("confidence", "Float", in_list_view=1),
           cb(2),
           f("entities", "Code", options="JSON"),
           f("status", "Select", default="Parsed", in_list_view=1, in_standard_filter=1,
             options="Parsed\nAwaiting Confirmation\nExecuted\nCancelled\n"
                     "Clarifying\nUnrecognised\nFailed"),
           sb("out_sb", "Result"),
           f("reference_doctype", "Data", read_only=1),
           f("reference_name", "Data", read_only=1),
           cb(3),
           f("reply_sent", "Small Text", read_only=1),
           f("error", "Small Text", read_only=1),
       ], perms=OPS)


# ------------------------------------------------------------------ customer

def gen_thread_message():
    dt("Thread Message", istable=1, fields=[
        f("direction", "Select", options="Inbound\nOutbound", reqd=1, in_list_view=1),
        f("message_type", "Data", in_list_view=1),
        f("body", "Small Text", in_list_view=1),
        f("sent_at", "Datetime", in_list_view=1),
        f("template_used", "Link", options="WhatsApp Template"),
        f("voice_message", "Link", options="Voice Message"),
    ])


def gen_customer_thread():
    dt("Customer Thread", autoname="format:CT-{######}",
       title_field="display_name",
       search_fields="phone_number,lead",
       fields=[
           sb("who_sb", "Party"),
           f("display_name", "Data", in_list_view=1),
           f("phone_number", "Data", reqd=1, in_list_view=1, in_standard_filter=1),
           f("lead", "Link", options="RE Lead", in_list_view=1),
           cb(1),
           f("deal", "Link", options="RE Deal"),
           f("agent", "Link", options="RE Agent", in_standard_filter=1),
           f("language", "Data"),
           sb("state_sb", "State"),
           f("stage", "Select", default="Enquiry", in_standard_filter=1,
             options="Enquiry\nOptions Sent\nVisit Scheduled\nPost Visit\n"
                     "Negotiation\nClosed"),
           f("last_summary", "Small Text", read_only=1),
           f("summary_updated_on", "Datetime", read_only=1),
           sb("msg_sb", "Messages"),
           f("messages", "Table", options="Thread Message"),
       ], perms=OPS)


def gen_sentiment_reading():
    dt("Sentiment Reading", autoname="format:SR-{######}",
       fields=[
           f("customer_thread", "Link", options="Customer Thread", in_list_view=1),
           f("lead", "Link", options="RE Lead", in_standard_filter=1),
           f("label", "Select", options="\nPositive\nNeutral\nNegative",
             in_list_view=1, in_standard_filter=1),
           f("confidence", "Percent", in_list_view=1),
           f("rationale", "Small Text"),
           f("model", "Data", read_only=1),
           f("overridden_by_agent", "Check"),
       ], perms=OPS)


# ------------------------------------------------------------------ scoring

def gen_score_model():
    dt("Lead Score Model", issingle=1, fields=[
        sb("w_sb", "Signal Weights"),
        f("weight_budget", "Int", default=30, label="Budget Fit"),
        f("weight_frequency", "Int", default=20, label="Conversation Frequency"),
        f("weight_visits", "Int", default=25, label="Site Visits"),
        cb(1),
        f("weight_response", "Int", default=15, label="Response Speed"),
        f("weight_loan", "Int", default=10, label="Loan Requirement"),
        sb("band_sb", "Bands"),
        f("hot_threshold", "Int", default=75),
        f("warm_threshold", "Int", default=45),
        sb("param_sb", "Parameters"),
        f("frequency_window_days", "Int", default=14),
        f("frequency_target", "Int", default=6,
          description="Inbound messages in the window that count as full marks"),
        cb(2),
        f("response_target_minutes", "Int", default=60,
          description="Median reply latency at or below this scores full marks"),
        f("visits_target", "Int", default=2),
    ], perms=[perm("RE Manager"), perm("RE Sales Manager"), perm("System Manager")])


def gen_score_log():
    dt("Lead Score Log", autoname="format:LSL-{######}",
       fields=[
           f("lead", "Link", options="RE Lead", reqd=1, in_list_view=1,
             in_standard_filter=1),
           f("total_score", "Int", in_list_view=1),
           f("band", "Select", options="\nHot\nWarm\nCold", in_list_view=1,
             in_standard_filter=1),
           sb("comp_sb", "Components"),
           f("score_budget", "Int"),
           f("score_frequency", "Int"),
           f("score_visits", "Int"),
           cb(1),
           f("score_response", "Int"),
           f("score_loan", "Int"),
           sb("why_sb", ""),
           f("reason", "Small Text", label="Why this score"),
       ], perms=OPS)


ALL = [gen_ai_settings, gen_locale_profile, gen_whatsapp_template, gen_webhook_log,
       gen_conversation_session, gen_voice_message, gen_usage_log, gen_command_entity,
       gen_voice_command, gen_voice_intent, gen_thread_message, gen_customer_thread,
       gen_sentiment_reading, gen_score_model, gen_score_log]

if __name__ == "__main__":
    os.makedirs(DOCTYPE_DIR, exist_ok=True)
    init = os.path.join(DOCTYPE_DIR, "__init__.py")
    if not os.path.exists(init): open(init, "w").close()
    print(f"Generating {len(ALL)} DocTypes")
    for gen in ALL:
        gen()
    print("Done.")
