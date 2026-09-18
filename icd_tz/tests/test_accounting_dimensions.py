# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate, nowdate

from icd_tz.icd_tz.api.accounting_dimensions import (
	ACCOUNTING_SECTION,
	DIMENSION_DISPLAY_ORDER,
	DIMENSIONS,
	GUARDED_DOCTYPES,
	build_dimension_name,
	get_container_dimensions,
	get_dimension_names,
	get_referencing_orders,
	get_referencing_vouchers,
)

CONTAINER_NO = "MSKU1234567"
LOOSE_CARGO_NO = "LOOSE0000001"
M_BL_NO = "MAEU123456789"
CONSIGNEE = "_Test ICD Dimension Consignee"


class TestAccountingDimensions(FrappeTestCase):
	def setUp(self):
		self.manifest = make_manifest()
		self.container_dimension = build_dimension_name(CONTAINER_NO, self.manifest.name)
		self.master_bl_dimension = build_dimension_name(M_BL_NO, self.manifest.name)

	def tearDown(self):
		frappe.db.rollback()

	def test_the_id_drops_the_series_prefix(self):
		self.assertEqual(build_dimension_name("MSKU1", "ICD-M-2026-00042"), "MSKU1:2026-00042")

	def test_the_id_keeps_the_amendment_suffix(self):
		self.assertEqual(build_dimension_name("MSKU1", "ICD-M-2026-00042-1"), "MSKU1:2026-00042-1")

	def test_the_id_needs_a_numeric_manifest_part(self):
		self.assertRaises(frappe.ValidationError, build_dimension_name, "MSKU1", "ICD-M-")

	def test_submit_creates_one_record_per_bill_of_lading(self):
		self.manifest.submit()

		master_bls = frappe.get_all("ICD Master BL", filters={"manifest": self.manifest.name}, pluck="name")
		self.assertEqual(master_bls, [self.master_bl_dimension])

	def test_submit_creates_one_record_per_manifested_unit(self):
		self.manifest.submit()

		containers = frappe.get_all(
			"ICD Container", filters={"manifest": self.manifest.name}, pluck="container_no"
		)
		self.assertEqual(sorted(containers), sorted([CONTAINER_NO, LOOSE_CARGO_NO]))

	def test_an_lcl_box_gets_one_container_record(self):
		"""Two house bills on one box, the box is moved and costed once"""

		self.manifest.submit()

		self.assertEqual(
			frappe.db.count("ICD Container", {"manifest": self.manifest.name, "container_no": CONTAINER_NO}),
			1,
		)

	def test_the_unit_type_distinguishes_loose_cargo_from_a_container(self):
		self.manifest.submit()
		loose_dimension = build_dimension_name(LOOSE_CARGO_NO, self.manifest.name)

		self.assertEqual(
			frappe.db.get_value("ICD Container", self.container_dimension, "type_of_container"), "C"
		)
		self.assertEqual(frappe.db.get_value("ICD Container", loose_dimension, "type_of_container"), "V")

	def test_container_carries_the_manifest_details(self):
		self.manifest.submit()
		container = frappe.get_doc("ICD Container", self.container_dimension)

		self.assertEqual(container.m_bl_no, M_BL_NO)
		self.assertEqual(container.master_bl, self.master_bl_dimension)
		self.assertEqual(container.consignee, CONSIGNEE)
		self.assertEqual(container.vessel_name, self.manifest.vessel_name)
		self.assertEqual(container.size, "20")
		self.assertEqual(container.arrival_date, getdate(self.manifest.arrival_date))
		self.assertEqual(container.posting_date, getdate(nowdate()))

	def test_master_bl_carries_the_consignee(self):
		self.manifest.submit()
		master_bl = frappe.get_doc("ICD Master BL", self.master_bl_dimension)

		self.assertEqual(master_bl.consignee, CONSIGNEE)
		self.assertEqual(master_bl.cargo_classification, "IM")
		self.assertEqual(master_bl.posting_date, getdate(nowdate()))
		self.assertNotEqual(master_bl.posting_date, getdate(self.manifest.arrival_date))

	def test_cancel_revokes_the_dimension_records(self):
		self.manifest.submit()
		self.manifest.cancel()

		self.assertEqual(frappe.db.count("ICD Container", {"manifest": self.manifest.name}), 0)
		self.assertEqual(frappe.db.count("ICD Master BL", {"manifest": self.manifest.name}), 0)

	def test_amendment_creates_its_own_records(self):
		self.manifest.submit()
		self.manifest.cancel()

		amended = frappe.copy_doc(self.manifest)
		amended.amended_from = self.manifest.name
		amended.docstatus = 0
		amended.insert()
		amended.submit()

		self.assertNotEqual(amended.name, self.manifest.name)
		self.assertEqual(
			frappe.db.count("ICD Container", {"manifest": amended.name}),
			2,
		)

	def test_a_manifest_without_gl_entries_has_no_posted_vouchers(self):
		self.manifest.submit()

		self.assertEqual(
			get_referencing_vouchers(self.manifest.name, get_dimension_names(self.manifest.name)), []
		)

	def test_an_order_blocks_cancellation_without_any_gl_entry(self):
		"""Neither order type reaches the ledger, both are caught on their dimension fields"""

		for doctype in ("Purchase Order", "Sales Order"):
			with self.subTest(doctype=doctype):
				manifest = make_manifest()
				manifest.submit()
				dimension = build_dimension_name(CONTAINER_NO, manifest.name)

				order = make_order(doctype, manifest, dimension)
				order.submit()

				dimension_names = get_dimension_names(manifest.name)
				self.assertEqual(get_referencing_orders(dimension_names), [(doctype, order.name)])
				self.assertEqual(get_referencing_vouchers(manifest.name, dimension_names), [])
				self.assertRaises(frappe.ValidationError, manifest.cancel)

	def test_a_draft_order_also_blocks_cancellation(self):
		"""frappe refuses to delete a record a draft document links to, so the guard must agree"""

		self.manifest.submit()
		order = make_order("Purchase Order", self.manifest, self.container_dimension)

		self.assertEqual(
			get_referencing_orders(get_dimension_names(self.manifest.name)),
			[("Purchase Order", order.name)],
		)
		self.assertRaises(frappe.ValidationError, self.manifest.cancel)

	def test_a_cancelled_invoice_still_blocks_cancellation(self):
		"""erpnext keeps the GL rows and only flags is_cancelled

		Ignoring them let the guard pass and then on_cancel died with a LinkExistsError
		naming a GL Entry the user cannot delete, leaving the manifest stuck forever.
		"""

		self.manifest.submit()
		invoice = make_purchase_invoice(self.manifest, self.container_dimension)
		invoice.submit()
		invoice.cancel()

		dimension_names = get_dimension_names(self.manifest.name)
		self.assertEqual(
			get_referencing_vouchers(self.manifest.name, dimension_names),
			[("Purchase Invoice", invoice.name)],
		)
		self.assertRaises(frappe.ValidationError, self.manifest.cancel)

	def test_one_container_under_two_bills_is_rejected(self):
		"""Costs booked on it could not be attributed to one bill, so the manifest is refused"""

		self.manifest.append(
			"containers",
			{"m_bl_no": "MAEU000000000", "container_no": CONTAINER_NO, "type_of_container": "C"},
		)
		self.manifest.save()

		self.assertRaises(frappe.ValidationError, self.manifest.submit)

	def test_the_duplicate_bill_message_carries_no_live_markup(self):
		"""msgprint renders HTML and these values come from the uploaded file"""

		self.manifest.append(
			"containers",
			{
				"m_bl_no": "<script>alert(1)</script>",
				"container_no": CONTAINER_NO,
				"type_of_container": "C",
			},
		)
		self.manifest.save()

		with self.assertRaises(frappe.ValidationError) as raised:
			self.manifest.submit()

		# frappe sanitizes Data fields on save, so the stored value is already escaped
		self.assertNotIn("<script>", str(raised.exception))

	def test_a_repeated_container_row_on_one_bill_is_tolerated(self):
		self.manifest.append(
			"containers",
			{"m_bl_no": M_BL_NO, "container_no": CONTAINER_NO, "type_of_container": "C"},
		)
		self.manifest.save()
		self.manifest.submit()

		self.assertEqual(
			frappe.db.count("ICD Container", {"manifest": self.manifest.name, "container_no": CONTAINER_NO}),
			1,
		)

	def test_both_dimensions_are_registered(self):
		for doctype, fieldname in DIMENSIONS.items():
			dimension = frappe.db.get_value(
				"Accounting Dimension", {"document_type": doctype}, ["fieldname", "disabled"], as_dict=True
			)
			self.assertIsNotNone(dimension, doctype)
			self.assertEqual(dimension.fieldname, fieldname)
			self.assertEqual(dimension.disabled, 0, f"{doctype} dimension is disabled")

	def test_the_dimension_fields_reach_the_purchase_doctypes(self):
		for doctype in ("Purchase Order", "Purchase Order Item", "Purchase Invoice", "GL Entry"):
			for fieldname in DIMENSIONS.values():
				self.assertTrue(frappe.db.has_column(doctype, fieldname), f"{doctype} is missing {fieldname}")

	def test_the_guarded_tables_index_the_dimension_fields(self):
		"""Without the index the cancel guard scans GL Entry, the largest table on the site"""

		for doctype in GUARDED_DOCTYPES:
			table = f"tab{doctype}"
			for fieldname in DIMENSIONS.values():
				self.assertTrue(
					frappe.db.has_index(table, f"{fieldname}_index"), f"{doctype}.{fieldname} is unindexed"
				)

	def test_the_dimension_fields_sit_in_the_accounting_dimensions_section(self):
		"""erpnext anchors one of them to a field some doctypes lack, which scattered them"""

		for doctype in ("Sales Order", "Sales Order Item", "Purchase Order", "Purchase Invoice Item"):
			with self.subTest(doctype=doctype):
				fields = frappe.get_meta(doctype).fields
				names = [field.fieldname for field in fields]
				self.assertIn(ACCOUNTING_SECTION, names)

				section_fields = get_section_fieldnames(fields, ACCOUNTING_SECTION)
				for fieldname in DIMENSION_DISPLAY_ORDER:
					if fieldname in names:
						self.assertIn(fieldname, section_fields, f"{doctype}.{fieldname} is outside")

	def test_users_cannot_create_dimension_records_from_the_form(self):
		for doctype in DIMENSIONS:
			self.assertEqual(frappe.get_meta(doctype).in_create, 1, doctype)

	def test_every_dimension_field_is_read_only(self):
		layout_fieldtypes = ("Section Break", "Column Break", "Tab Break")

		for doctype in DIMENSIONS:
			for field in frappe.get_meta(doctype).fields:
				if field.fieldtype in layout_fieldtypes:
					continue

				self.assertEqual(field.read_only, 1, f"{doctype}.{field.fieldname}")

	def test_charge_row_dimensions_resolve_to_the_records(self):
		self.manifest.submit()
		source = frappe._dict(
			{"manifest": self.manifest.name, "container_no": CONTAINER_NO, "m_bl_no": M_BL_NO}
		)

		self.assertEqual(
			get_container_dimensions(source),
			{"icd_container": self.container_dimension, "icd_master_bl": self.master_bl_dimension},
		)

	def test_charge_row_dimensions_stay_blank_for_an_unbackfilled_manifest(self):
		"""Manifests submitted before the dimensions existed must not break the order"""

		source = frappe._dict(
			{"manifest": "ICD-M-2019-00001", "container_no": CONTAINER_NO, "m_bl_no": M_BL_NO}
		)

		self.assertEqual(get_container_dimensions(source), {})


def make_manifest():
	manifest = frappe.new_doc("Manifest")
	manifest.update(
		{
			"manifest": "/private/files/_test_icd_manifest.xlsx",
			"company": get_company(),
			"mrn": "_TEST-MRN-001",
			"vessel_name": "_Test Vessel",
			"voyage_no": "V-001",
			"arrival_date": "2026-09-01",
			"port": "DP WORLD",
		}
	)

	manifest.append(
		"master_bl",
		{
			"m_bl_no": M_BL_NO,
			"cargo_classification": "IM",
			"place_of_destination": "TZDAR",
			"place_of_delivery": "WITZDL019",
			"port_of_loading": "CNSHA",
			"number_of_containers": "2",
			"cargo_description": "_Test cargo",
			"consignee_name": CONSIGNEE,
			"consignee_tin": "123456789",
			"shipping_agent_code": "MAEU",
			"shipping_agent_name": "_Test Shipping Agent",
		},
	)

	for container_no, type_of_container, size in (
		(CONTAINER_NO, "C", "20"),
		(LOOSE_CARGO_NO, "V", ""),
	):
		manifest.append(
			"containers",
			{
				"m_bl_no": M_BL_NO,
				"container_no": container_no,
				"type_of_container": type_of_container,
				"container_size": size,
				"freight_indicator": "FCL",
				"no_of_packages": "10",
				"package_unit": "PK",
				"weight": "12000",
				"weight_unit": "KG",
			},
		)

	# one box, two house bills: the LCL case
	for h_bl_no in ("HBL-001", "HBL-002"):
		manifest.append(
			"hbl_containers",
			{
				"m_bl_no": M_BL_NO,
				"h_bl_no": h_bl_no,
				"container_no": CONTAINER_NO,
				"type_of_container": "C",
				"container_size": "20",
			},
		)
		manifest.append(
			"house_bl",
			{"m_bl_no": M_BL_NO, "h_bl_no": h_bl_no, "consignee_name": CONSIGNEE},
		)

	manifest.insert()
	return manifest


def make_order(doctype: str, manifest, container_dimension):
	"""A cost or charge booked against the container before it is received"""

	order = frappe.new_doc(doctype)
	order.company = manifest.company
	order.transaction_date = manifest.arrival_date

	if doctype == "Purchase Order":
		date_field = "schedule_date"
		order.supplier = get_supplier()
	else:
		date_field = "delivery_date"
		order.customer = get_customer()

	order.set(date_field, manifest.arrival_date)
	order.append(
		"items",
		{
			"item_code": get_service_item(),
			"qty": 1,
			"rate": 150000,
			date_field: manifest.arrival_date,
			"icd_container": container_dimension,
		},
	)
	order.insert()
	return order


def make_purchase_invoice(manifest, container_dimension):
	"""A posted cost, so it reaches the ledger unlike an order"""

	invoice = frappe.new_doc("Purchase Invoice")
	invoice.update(
		{"supplier": get_supplier(), "company": manifest.company, "posting_date": manifest.arrival_date}
	)
	invoice.append(
		"items",
		{
			"item_code": get_service_item(),
			"qty": 1,
			"rate": 150000,
			"expense_account": get_expense_account(manifest.company),
			"icd_container": container_dimension,
		},
	)
	invoice.insert()
	return invoice


def get_section_fieldnames(fields, section: str) -> list:
	"""Fieldnames between a section break and the next one"""

	start = [field.fieldname for field in fields].index(section)

	names = []
	for field in fields[start + 1 :]:
		if field.fieldtype == "Section Break":
			break

		names.append(field.fieldname)

	return names


def get_customer() -> str:
	customer = frappe.db.get_value("Customer", {}, "name")
	if customer:
		return customer

	return frappe.get_doc({"doctype": "Customer", "customer_name": "_Test ICD Consignee"}).insert().name


def get_expense_account(company: str) -> str:
	return frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name")


def get_supplier():
	supplier = frappe.db.get_value("Supplier", {}, "name")
	if supplier:
		return supplier

	return frappe.get_doc({"doctype": "Supplier", "supplier_name": "_Test ICD Transporter"}).insert().name


def get_service_item():
	item = frappe.db.get_value("Item", {"is_stock_item": 0}, "name")
	if not item:
		frappe.throw("No service Item on the test site")

	return item


def get_company():
	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		frappe.throw("No Company on the test site")

	return company
