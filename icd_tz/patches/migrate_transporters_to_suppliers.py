import frappe


def execute():
	# 1. Loop through all Transporters and create Suppliers
	transporters = frappe.get_all(
		"Transporter",
		fields=["name", "company_name", "phone", "email", "tin", "vrn", "disabled"],
	)

	for t in transporters:
		# Check if Supplier already exists
		if not frappe.db.exists("Supplier", t.company_name):
			supplier = frappe.new_doc("Supplier")
			supplier.supplier_name = t.company_name
			# Typically Transporter or Default supplier group
			supplier.supplier_group = (
				"Transporter" if frappe.db.exists("Supplier Group", "Transporter") else "All Supplier Groups"
			)
			supplier.is_transporter = 1
			supplier.disabled = t.disabled

			# Map optional fields if they exist on standard Supplier
			if hasattr(supplier, "tax_id") and t.tin:
				supplier.tax_id = t.tin

			supplier.flags.ignore_permissions = True
			supplier.flags.ignore_mandatory = True
			try:
				supplier.insert()
			except Exception as e:
				print(f"Error creating supplier {t.company_name}: {e}")

		else:
			# Ensure is_transporter is checked
			frappe.db.set_value("Supplier", t.company_name, "is_transporter", 1)

	# 2. Re-link existing records in Container Movement Order
	frappe.db.sql("""
        UPDATE `tabContainer Movement Order`
        SET transporter = (SELECT company_name FROM `tabTransporter` WHERE name = `tabContainer Movement Order`.transporter)
        WHERE transporter IS NOT NULL AND EXISTS (SELECT name FROM `tabTransporter` WHERE name = `tabContainer Movement Order`.transporter)
    """)

	# 3. Re-link existing records in Container Reception
	frappe.db.sql("""
        UPDATE `tabContainer Reception`
        SET transporter = (SELECT company_name FROM `tabTransporter` WHERE name = `tabContainer Reception`.transporter)
        WHERE transporter IS NOT NULL AND EXISTS (SELECT name FROM `tabTransporter` WHERE name = `tabContainer Reception`.transporter)
    """)

	# 4. Re-link Vehicle owner
	frappe.db.sql("""
        UPDATE `tabVehicle`
        SET vehicle_owner = (SELECT company_name FROM `tabTransporter` WHERE name = `tabVehicle`.vehicle_owner)
        WHERE vehicle_owner IS NOT NULL AND EXISTS (SELECT name FROM `tabTransporter` WHERE name = `tabVehicle`.vehicle_owner)
    """)

	# 5. Migrate Driver records (move vehicle_owner to transporter)
	# The vehicle_owner field points to Transporter, we need to map to Supplier name and save it into transporter field
	drivers = frappe.get_all("Driver", fields=["name", "vehicle_owner", "transporter"])
	for d in drivers:
		if d.vehicle_owner:
			transporter_doc = frappe.db.get_value("Transporter", d.vehicle_owner, "company_name")
			if transporter_doc:
				frappe.db.set_value("Driver", d.name, "transporter", transporter_doc)

	# Note: We already set hidden=1 for Driver-vehicle_owner via the JSON file.

	# 6. Delete old Property Setters that hid the transporter field on Driver
	frappe.db.delete(
		"Property Setter",
		{"name": ("in", ["Driver-transporter-hidden", "Driver-transporter-read_only"])},
	)
