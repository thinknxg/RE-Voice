"""Inbound media retrieval from the Cloud API (two-step: metadata then binary)."""

import frappe


def download_media(media_id):
    """Returns (content_bytes, mime_type, filename) or (None, None, None)."""
    settings = frappe.get_cached_doc("WhatsApp Settings")
    token = settings.get_password("access_token")
    version = settings.api_version or "v19.0"
    try:
        meta = frappe.make_get_request(
            f"https://graph.facebook.com/{version}/{media_id}",
            headers={"Authorization": f"Bearer {token}"})
        url = meta.get("url")
        mime = meta.get("mime_type") or "audio/ogg"
        if not url:
            return None, None, None
        content = frappe.make_get_request(
            url, headers={"Authorization": f"Bearer {token}"}, as_json=False)
        if hasattr(content, "content"):
            content = content.content
        extension = "ogg" if "ogg" in mime else mime.split("/")[-1].split(";")[0]
        return content, mime, f"{media_id}.{extension}"
    except Exception:
        frappe.log_error(title="re_voice: media download failed",
                         message=f"media_id={media_id}")
        return None, None, None


def save_media_file(content, filename, attached_to_doctype=None, attached_to_name=None):
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "content": content,
        "is_private": 1,
        "attached_to_doctype": attached_to_doctype,
        "attached_to_name": attached_to_name,
    }).insert(ignore_permissions=True)
    return file_doc.file_url
