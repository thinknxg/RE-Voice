"""Speech-to-text and translation. Preserves all four layers the brief requires:
original audio -> native transcript -> English translation -> CRM note."""

import frappe
from frappe import _
from frappe.utils import cstr, get_files_path

from re_voice.ai.client import llm_complete, log_usage


def transcribe_voice_message(voice_message):
    """Fills transcript / translation / detected_language on a Voice Message."""
    doc = frappe.get_doc("Voice Message", voice_message)
    settings = frappe.get_cached_doc("AI Settings")
    if not settings.voice_enabled or settings.asr_provider == "None":
        doc.db_set("status", "Failed")
        doc.db_set("error", "Voice processing disabled in AI Settings")
        return doc

    doc.db_set("status", "Transcribing")
    try:
        text, language = _run_asr(doc, settings)
        doc.db_set("transcript", cstr(text)[:2000])
        doc.db_set("detected_language", language)
        if language and not language.startswith("en") and settings.enable_translation:
            doc.db_set("translation", translate_to_english(text, language, doc.name))
        doc.db_set("status", "Transcribed")
        log_usage("ASR", settings.asr_provider,
                  audio_seconds=doc.duration_seconds or 0,
                  cost=(doc.duration_seconds or 0) / 60.0 *
                       float(settings.asr_cost_per_minute or 0),
                  reference_doctype="Voice Message", reference_name=doc.name)
    except Exception:
        doc.db_set("status", "Failed")
        doc.db_set("error", frappe.get_traceback()[-500:])
        frappe.log_error(title="re_voice: ASR failed", message=doc.name)
    return doc.reload()


def _run_asr(doc, settings):
    """Returns (text, language_code). Two providers, one shape."""
    file_path = frappe.get_doc("File", {"file_url": doc.audio_file}).get_full_path()

    if settings.asr_provider == "Local Whisper":
        endpoint = (settings.asr_endpoint or "").rstrip("/")
        with open(file_path, "rb") as handle:
            response = frappe.make_post_request(
                f"{endpoint}/asr?task=transcribe&output=json",
                files={"audio_file": handle})
        return response.get("text", ""), response.get("language")

    # OpenAI-compatible Whisper API
    with open(file_path, "rb") as handle:
        response = frappe.make_post_request(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.get_password('api_key')}"},
            data={"model": settings.asr_model or "whisper-1",
                  "response_format": "verbose_json"},
            files={"file": handle})
    return response.get("text", ""), response.get("language")


def translate_to_english(text, source_language, reference=None):
    """Translation via the configured LLM; the native transcript is never replaced."""
    prompt = (
        f"Translate the following {source_language} text to English. "
        f"Return only the translation, no commentary.\n\n{text}")
    result = llm_complete(prompt, task="Translation",
                          reference_doctype="Voice Message", reference_name=reference)
    return cstr(result)[:2000] if result else None


def resolve_text(voice_message_doc):
    """The text the intent engine should act on: English if available, else native."""
    return (voice_message_doc.translation or voice_message_doc.transcript or "").strip()
