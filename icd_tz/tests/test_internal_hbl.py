# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from icd_tz.icd_tz.api.expense_release import get_wip_balance, release_expenses
from icd_tz.icd_tz.api.port_expenses import get_expense_rows
from icd_tz.tests.test_edi_movement import CONTAINER_NO, M_BL_NO, make_manifest, make_reception
from icd_tz.tests.test_port_expenses import (
	BOX_20,
	BOX_40,
	ITEMS,
	PRICE_LIST,
	RATES,
	get_criteria_row,
	make_buying_price_list,
	make_expense_item,
	set_expense_settings,
)
from icd_tz.tests.test_port_expenses import M_BL_NO as EXPENSE_M_BL_NO
from icd_tz.tests.test_port_expenses import make_manifest as make_expense_manifest
from icd_tz.tests.test_storage_contract import set_settings_storage_days

test_ignore = ["Company", "Cost Center"]

# three bills sharing one LCL box, none of them with a house bill
BILLS = {
	M_BL_NO: {
		"consignee_name": "_Test Shared Consignee A",
		"gross_volume": 30,
		"cargo_classification": "IM",
		"place_of_destination": "TZDAR",
	},
	"SHARED-BL-B": {
		"consignee_name": "_Test Shared Consignee B",
		"gross_volume": 6,
		"cargo_classification": "TR",
		"place_of_destination": "CDFBM",
	},
	"SHARED-BL-C": {
		"consignee_name": "_Test Shared Consignee C",
		"gross_volume": 14,
		"cargo_classification": "IM",
		"place_of_destination": "TZDAR",
	},
}


def make_shared_box_manifest():
	for bill in BILLS.values():
		if not frappe.db.exists("Consignee", bill["consignee_name"]):
			frappe.get_doc({"doctype": "Consignee", "consignee_name": bill["consignee_name"]}).insert(
				ignore_permissions=True
			)

	manifest = make_manifest()
	manifest.master_bl[0].update(BILLS[M_BL_NO])
	manifest.containers[0].freight_indicator = "LCL"
	for m_bl_no, bill in BILLS.items():
		if m_bl_no == M_BL_NO:
			continue

		manifest.append("master_bl", {"m_bl_no": m_bl_no, **bill})
		manifest.append(
			"containers",
			{
				"m_bl_no": m_bl_no,
				"container_no": CONTAINER_NO,
				"type_of_container": "C",
				"container_size": "45G1",
				"freight_indicator": "LCL",
			},
		)

	manifest.save(ignore_permissions=True)

	return manifest


def receive_shared_box():
	reception = make_reception(freight_indicator="LCL")
	reception.create_hbl_container(reception.create_mbl_container())

	return [
		frappe.get_doc("Container", name)
		for name in frappe.get_all(
			"Container", {"container_reception": reception.name}, pluck="name", order_by="creation"
		)
	]


class TestInternalHBL(FrappeTestCase):
	"""Every bill sharing an LCL box gets its own cargo record under an ICD house bill"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		set_settings_storage_days()
		make_shared_box_manifest()
		containers = receive_shared_box()
		self.box = containers[0]
		self.cargo = {row.m_bl_no: row for row in containers[1:]}

	def tearDown(self):
		frappe.db.rollback()

	def test_each_bill_gets_one_cargo_record(self):
		self.assertEqual(sorted(self.cargo), sorted(BILLS))
		self.assertEqual({row.has_hbl for row in self.cargo.values()}, {1})

	def test_each_record_has_its_own_internal_house_bill(self):
		h_bl_nos = [row.h_bl_no for row in self.cargo.values()]

		self.assertEqual(len(set(h_bl_nos)), len(BILLS))
		self.assertTrue(all(h_bl_no.startswith("ICD-HBL-") for h_bl_no in h_bl_nos))

	def test_the_volume_is_each_bills_own(self):
		self.assertEqual(
			{m_bl_no: row.gross_volume for m_bl_no, row in self.cargo.items()},
			{m_bl_no: bill["gross_volume"] for m_bl_no, bill in BILLS.items()},
		)

	def test_the_consignee_is_each_bills_own(self):
		self.assertEqual(
			{m_bl_no: row.consignee for m_bl_no, row in self.cargo.items()},
			{m_bl_no: bill["consignee_name"] for m_bl_no, bill in BILLS.items()},
		)

	def test_cargo_type_and_destination_are_each_bills_own(self):
		self.assertEqual(
			(self.cargo["SHARED-BL-B"].cargo_type, self.cargo["SHARED-BL-B"].place_of_destination),
			("Transit", "DRC"),
		)
		self.assertEqual(
			(self.cargo[M_BL_NO].cargo_type, self.cargo[M_BL_NO].place_of_destination), ("Local", "Local")
		)

	def test_a_box_repeated_under_one_bill_gets_one_record(self):
		manifest = frappe.get_doc("Manifest", frappe.db.get_value("Manifest", {}, "name"))
		manifest.append(
			"containers",
			{
				"m_bl_no": M_BL_NO,
				"container_no": CONTAINER_NO,
				"type_of_container": "C",
				"freight_indicator": "LCL",
			},
		)
		manifest.save(ignore_permissions=True)

		cargo = receive_shared_box()[1:]

		self.assertEqual(sorted(row.m_bl_no for row in cargo), sorted(BILLS))

	def test_a_bill_missing_from_the_master_bl_sheet_is_refused(self):
		manifest = frappe.get_doc("Manifest", frappe.db.get_value("Manifest", {}, "name"))
		manifest.append(
			"containers",
			{
				"m_bl_no": "UNLISTED-BL",
				"container_no": CONTAINER_NO,
				"type_of_container": "C",
				"freight_indicator": "LCL",
			},
		)
		manifest.save(ignore_permissions=True)

		self.assertRaises(frappe.ValidationError, receive_shared_box)

	def test_the_box_is_left_empty(self):
		self.assertEqual(self.box.is_empty_container, 1)
		self.assertEqual(self.box.has_hbl, 0)


class TestSharedBoxRelease(FrappeTestCase):
	"""Each consignee's invoice releases what WIP holds against its own bill"""

	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		accounts = frappe.get_all(
			"Account",
			{"company": self.company, "is_group": 0, "root_type": "Expense"},
			pluck="name",
			limit=2,
		)
		if len(accounts) < 2:
			self.skipTest(f"{self.company} has fewer than two postable expense accounts")

		self.cogs, self.wip = accounts
		self.cost_center = frappe.db.get_value(
			"Cost Center", {"company": self.company, "is_group": 0}, "name"
		)
		self.item = frappe.get_single("ICD TZ Settings").expense_types[0].expense_item
		frappe.db.set_single_value(
			"ICD TZ Settings",
			{"enable_wip_for_expenses": 1, "wip_account": self.wip, "cogs_account": self.cogs},
		)
		self.manifest = make_manifest()
		self.bills = {m_bl_no: self.make_dimension("ICD Master BL", m_bl_no=m_bl_no) for m_bl_no in BILLS}
		self.box = self.make_dimension(
			"ICD Container", container_no=CONTAINER_NO, master_bl=self.bills[M_BL_NO]
		)

	def tearDown(self):
		frappe.clear_document_cache("ICD TZ Settings", "ICD TZ Settings")
		frappe.db.rollback()

	def make_dimension(self, doctype, **values):
		record = frappe.new_doc(doctype)
		record.update({"manifest": self.manifest.name, "company": self.company, **values})
		record.flags.ignore_mandatory = True
		record.insert(ignore_permissions=True)

		return record.name

	def make_invoice(self, doctype, m_bl_no, rate, **line):
		invoice = frappe.new_doc(doctype)
		invoice.update(
			{
				"company": self.company,
				"posting_date": nowdate(),
				"due_date": nowdate(),
				"supplier": frappe.db.get_value("Supplier", {}, "name"),
				"customer": frappe.db.get_value("Customer", {}, "name"),
			}
		)
		invoice.append(
			"items",
			{
				"item_code": self.item,
				"qty": 1,
				"rate": rate,
				"icd_container": self.box,
				"icd_master_bl": self.bills[m_bl_no],
				"cost_center": self.cost_center,
				**line,
			},
		)
		invoice.flags.ignore_permissions = True
		invoice.flags.ignore_mandatory = True
		invoice.insert()
		invoice.submit()

		return invoice

	def hold_in_wip(self, m_bl_no, amount):
		self.make_invoice("Purchase Invoice", m_bl_no, amount, expense_account=self.wip)

	def bill(self, m_bl_no):
		invoice = self.make_invoice("Sales Invoice", m_bl_no, 400000)
		release_expenses(invoice.name)

		return frappe.db.get_value(
			"Journal Entry Account",
			{
				"parent": frappe.db.get_value(
					"Journal Entry", {"icd_sales_invoice": invoice.name, "docstatus": 1}
				),
				"account": self.cogs,
			},
			"debit",
		)

	def test_each_invoice_releases_only_its_own_bill(self):
		# the box charges sit on the first bill, the Transit Shore on the Transit bill
		self.hold_in_wip(M_BL_NO, 100000)
		self.hold_in_wip("SHARED-BL-B", 20000)

		released = [self.bill(m_bl_no) for m_bl_no in BILLS]

		self.assertEqual(released, [100000, 20000, None])
		self.assertEqual(get_wip_balance({"icd_container": self.box}, self.wip), 0)

	def test_the_second_invoice_does_not_release_the_first_bills_charges_again(self):
		self.hold_in_wip(M_BL_NO, 100000)
		self.bill(M_BL_NO)

		self.assertIsNone(self.bill("SHARED-BL-B"))
		self.assertEqual(get_wip_balance({"icd_container": self.box}, self.wip), 0)


class TestSharedBoxPortExpenses(FrappeTestCase):
	"""A shared box pays a one off charge again for each cargo type priced on another row"""

	def setUp(self):
		make_buying_price_list()
		for expense_type, item_code in ITEMS.items():
			make_expense_item(item_code, RATES[expense_type])

		set_expense_settings()
		manifest = make_expense_manifest()
		manifest.containers[0].freight_indicator = "LCL"
		for m_bl_no, cargo_classification in (("SHARED-BL-T", "TR"), ("SHARED-BL-L", "IM")):
			manifest.append("master_bl", {"m_bl_no": m_bl_no, "cargo_classification": cargo_classification})
			manifest.append(
				"containers",
				{
					"m_bl_no": m_bl_no,
					"container_no": BOX_20,
					"type_of_container": "C",
					"container_size": "20",
					"freight_indicator": "LCL",
				},
			)

		manifest.save()
		manifest.submit()
		self.manifest = manifest.name
		self.rows = get_expense_rows(manifest.name, PRICE_LIST)

	def tearDown(self):
		frappe.db.rollback()

	def get_lines(self, expense_type, size):
		criteria_row = get_criteria_row(expense_type, size)
		row = next(row for row in self.rows if row["criteria_row"] == criteria_row)

		return sorted(
			(line["container_no"], line["icd_master_bl"].split(":")[0]) for line in row["containers"]
		)

	def test_each_cargo_type_pays_its_own_shore(self):
		self.assertEqual(self.get_lines("Shore", "20ft"), [(BOX_20, EXPENSE_M_BL_NO)])
		self.assertEqual(self.get_lines("Shore", ""), [(BOX_20, "SHARED-BL-T"), (BOX_40, EXPENSE_M_BL_NO)])

	def test_a_charge_only_one_cargo_type_pays_goes_on_that_bill(self):
		self.assertEqual(self.get_lines("Levy", ""), [(BOX_20, "SHARED-BL-T")])

	def test_a_charge_priced_alike_is_paid_once_on_the_first_bill(self):
		self.assertEqual(
			self.get_lines("Removal", ""), [(BOX_20, EXPENSE_M_BL_NO), (BOX_40, EXPENSE_M_BL_NO)]
		)

	def test_the_box_record_keeps_the_first_bill(self):
		master_bl = frappe.db.get_value(
			"ICD Container", {"manifest": self.manifest, "container_no": BOX_20}, "master_bl"
		)

		self.assertTrue(master_bl.startswith(EXPENSE_M_BL_NO))
