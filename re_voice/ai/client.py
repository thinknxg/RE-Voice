"""Single LLM entry point with budget enforcement and usage logging.

Every AI call in re_voice goes through llm_complete so that cost is observable
and the monthly cap degrades the system gracefully rather than silently."""

import frappe
from frappe import _
from frappe.utils import cstr, flt, get_first_day, get_last_day, nowdate


def budget_available():
    settings = frappe.get_cached_doc("AI Settings")
    if not settings.monthly_budget:
        return True
    spend = frappe.db.sql("""
        SELECT COALESCE(SUM(cost), 0) FROM `tabVoice Usage Log`
        WHERE DATE(creation) BETWEEN %s AND %s
    """, (get_first_day(nowdate()), get_last_day(nowdate())))[0][0]
    return flt(spend) < flt(settings.monthly_budget)


def log_usage(task, provider, audio_seconds=0, input_tokens=0, output_tokens=0,
              cost=0, reference_doctype=None, reference_name=None):
    frappe.get_doc({
        "doctype": "Voice Usage Log", "task": task, "provider": provider,
        "audio_seconds": audio_seconds, "input_tokens": input_tokens,
        "output_tokens": output_tokens, "cost": cost,
        "reference_doctype": reference_doctype, "reference_name": reference_name,
    }).insert(ignore_permissions=True)


def llm_complete(prompt, system=None, task="Intent", json_mode=False,
                 reference_doctype=None, reference_name=None):
    """Returns the model's text, or None when disabled / over budget / failed.
    Callers must handle None — that is the graceful-degradation path."""
    settings = frappe.get_cached_doc("AI Settings")
    if not settings.llm_enabled or settings.llm_provider == "None":
        return None
    if not budget_available():
        frappe.log_error(title="re_voice: monthly AI budget exhausted",
                         message=f"task={task}; falling back to deterministic path")
        return None

    try:
        text, usage = _call_provider(settings, prompt, system, json_mode)
        log_usage(task, settings.llm_provider,
                  input_tokens=usage.get("input_tokens", 0),
                  output_tokens=usage.get("output_tokens", 0),
                  cost=usage.get("cost", 0),
                  reference_doctype=reference_doctype,
                  reference_name=reference_name)
        return text
    except Exception:
        frappe.log_error(title="re_voice: LLM call failed", message=f"task={task}")
        return None


def _call_provider(settings, prompt, system, json_mode):
    provider = settings.llm_provider
    key = settings.get_password("api_key")

    if provider == "Anthropic":
        body = {"model": settings.llm_model or "claude-sonnet-4-6",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        response = frappe.make_post_request(
            settings.llm_endpoint or "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            data=frappe.as_json(body))
        text = "".join(block.get("text", "")
                       for block in response.get("content", [])
                       if block.get("type") == "text")
        usage = response.get("usage", {})
        return text, {"input_tokens": usage.get("input_tokens", 0),
                      "output_tokens": usage.get("output_tokens", 0)}

    # OpenAI-compatible (also covers "Custom" endpoints)
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    body = {"model": settings.llm_model or "gpt-4o-mini", "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    response = frappe.make_post_request(
        settings.llm_endpoint or "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        data=frappe.as_json(body))
    text = response["choices"][0]["message"]["content"]
    usage = response.get("usage", {})
    return text, {"input_tokens": usage.get("prompt_tokens", 0),
                  "output_tokens": usage.get("completion_tokens", 0)}


def parse_json_response(text):
    """LLMs wrap JSON in prose or fences more often than they should."""
    import json
    import re
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", cstr(text).strip(),
                     flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
    return None
