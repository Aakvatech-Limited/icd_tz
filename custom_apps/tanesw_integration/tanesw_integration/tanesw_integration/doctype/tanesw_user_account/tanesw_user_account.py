import frappe
from frappe import _
from frappe.model.document import Document


class TANeSWUserAccount(Document):
	def validate(self):
		if self.user == "Guest":
			frappe.throw(_("Guest cannot have a TANeSW user account"))
		self.tanesw_id = (self.tanesw_id or "").strip()
		if " " in self.tanesw_id:
			frappe.throw(_("TANeSW ID cannot contain spaces — enter your TANeSW portal user name"))

	def on_update(self):
		# New ID/password: drop the cached token and any remembered login failure, so the next call logs in again.
		from tanesw_integration.credentials import build_token_cache_key

		key = build_token_cache_key(self.user, self.company_code, self.role_code)
		frappe.cache.delete_value(key)
		frappe.cache.delete_value(f"{key}:login-failed")
