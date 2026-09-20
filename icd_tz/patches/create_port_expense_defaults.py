import frappe

DEFAULT_BANDS = (("Single", 1, 7), ("Double", 8, 9999999))


def execute():
	"""Seed the port storage day bands, which are the same wherever the ICD operates

	Neither the expense criteria nor the buying price list are seeded: both are
	client data, and a wrong guess would silently price a purchase order.
	"""

	settings_doc = frappe.get_single("ICD TZ Settings")
	if settings_doc.port_storage_days:
		return

	for charge, from_day, to_day in DEFAULT_BANDS:
		settings_doc.append("port_storage_days", {"charge": charge, "from": from_day, "to": to_day})

	settings_doc.flags.ignore_permissions = True
	settings_doc.flags.ignore_mandatory = True
	settings_doc.save()

	print(f"Seeded {len(DEFAULT_BANDS)} Port Storage Day band(s)")
