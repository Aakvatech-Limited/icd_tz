import frappe

CHARGES = ("Free", "Single", "Double")


def execute():
	"""Put the three port storage charges in front of the user to fill in

	The day ranges are a terminal tariff, so they are left blank on purpose and
	the fields stay mandatory: the rows say which charges the ICD expects, and
	the user confirms the days before the settings will save.

	Neither the expense criteria nor the buying price list are seeded either,
	for the same reason: both are client data, and a wrong guess would silently
	price a purchase order.
	"""

	settings_doc = frappe.get_single("ICD TZ Settings")
	if settings_doc.port_storage_days:
		return

	for charge in CHARGES:
		settings_doc.append("port_storage_days", {"charge": charge})

	settings_doc.flags.ignore_permissions = True
	settings_doc.flags.ignore_mandatory = True
	settings_doc.flags.ignore_validate = True
	settings_doc.save()

	print(f"Added {len(CHARGES)} Port Storage Day charge(s) for the day ranges to be filled in")
