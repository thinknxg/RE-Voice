app_name = "re_voice"
app_title = "RE Voice"
app_publisher = "Kreatao"
app_description = "Voice-first, WhatsApp-centric Real Estate CRM layer"
app_email = "dev@kreatao.com"
app_license = "MIT"

required_apps = ["erpnext", "re_core", "re_crm"]

after_install = "re_voice.install.after_install"

fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "RE Voice"]]},
    {"dt": "Role", "filters": [["name", "in", ["Voice Ops Manager"]]]},
    {"dt": "Workspace", "filters": [["name", "in", ["Voice CRM"]]]},
]

scheduler_events = {
    "hourly": [
        "re_voice.tasks.post_visit_feedback_prompts",
    ],
    "daily": [
        "re_voice.tasks.nightly_scoring",
        "re_voice.tasks.refresh_thread_summaries",
        "re_voice.tasks.purge_expired_audio",
        "re_voice.tasks.reset_monthly_spend",
    ],
}

doc_events = {
    "Site Visit": {
        "on_update": "re_voice.events.on_site_visit_update",
    },
    "RE Lead": {
        "after_insert": "re_voice.events.on_lead_insert",
    },
}
