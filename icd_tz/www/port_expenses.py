import frappe

no_cache = 1


def get_context(context):
	"""Boot payload the port expense page reads out of window at load"""

	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Please log in to view Port Expenses"), frappe.PermissionError)

	context.boot = {
		"default_route": "/port-expenses",
		"site_name": frappe.local.site,
		"csrf_token": frappe.sessions.get_csrf_token(),
	}

	return context
