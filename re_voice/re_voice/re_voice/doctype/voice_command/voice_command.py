import frappe
from frappe import _
from frappe.model.document import Document


class VoiceCommand(Document):
    def validate(self):
        """Catch a broken handler path at save time, not mid-conversation."""
        if not self.enabled:
            return
        try:
            frappe.get_attr(self.handler)
        except Exception:
            frappe.throw(_("Handler {0} could not be imported. Check the dotted path.")
                         .format(self.handler))
