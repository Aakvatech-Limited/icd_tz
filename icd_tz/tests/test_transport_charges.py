# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from icd_tz.icd_tz.api.port_expenses import TRANSPORT_EXPENSE_TYPE
from icd_tz.icd_tz.api.purchase_invoice import set_wip_account, validate_no_zero_rate
from icd_tz.icd_tz.api.transport_charges import (
	clear_transport_invoice,
	get_transport_services,
	stamp_transport_invoice,
	validate_reception_transport_unpaid,
)
from icd_tz.icd_tz.doctype.icd_container.icd_container import PENDING_STATUS, RECEIVED_STATUS
from icd_tz.tests.test_edi_movement import CONTAINER_NO, M_BL_NO, make_manifest, make_reception
from icd_tz.tests.test_port_expenses import get_expense_account, make_buying_price_list, make_item_price

test_ignore = ["Company", "Cost Center"]

TRANSPORT_ITEM = "_Test Transport Charge Item"
LOCAL_40FT_ITEM = "_Test Local 40ft Transport Item"
TRANSPORTER = "_Test Transport Supplier"
OTHER_TRANSPORTER = "_Test Other Transport Supplier"
PRICE_LIST = "_Test Transport Buying"


def make_record(doctype: str, name: str, values: dict) -> str:
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)

	return name


def make_transport_item(item_code: str = TRANSPORT_ITEM) -> str:
	make_record(
		"Item Group",
		"ICD Services",
		{"item_group_name": "ICD Services", "parent_item_group": "All Item Groups"},
	)

	return make_record(
		"Item",
		item_code,
		{
			"item_code": item_code,
			"item_name": item_code,
			"item_group": "ICD Services",
			"is_stock_item": 0,
			"is_purchase_item": 1,
		},
	)


def make_supplier(name: str) -> str:
	return make_record(
		"Supplier",
		name,
		{
			"supplier_name": name,
			"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"),
		},
	)


def set_transport_rows(*rows: dict):
	"""Replace the Transport rows of the expense criteria"""

	settings_doc = frappe.get_doc("ICD TZ Settings")
	settings_doc.expense_types = [
		row for row in settings_doc.expense_types if row.expense_type != TRANSPORT_EXPENSE_TYPE
	]
	for row in rows:
		settings_doc.append("expense_types", {"expense_type": TRANSPORT_EXPENSE_TYPE, **row})

	settings_doc.flags.ignore_mandatory = True
	settings_doc.save()
	frappe.clear_cache(doctype="ICD TZ Settings")


class TransportTestCase(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		self.item = make_transport_item()
		self.supplier = make_supplier(TRANSPORTER)
		make_buying_price_list(PRICE_LIST)
		frappe.db.set_single_value(
			"ICD TZ Settings",
			{
				"default_buying_price_list": PRICE_LIST,
				"enable_wip_for_expenses": 0,
				"received_date_threshold_hours": 48,
			},
		)
		set_transport_rows({"expense_item": self.item})
		self.manifest = make_manifest()
		self.manifest.db_set("company", self.company)
		self.container = self.make_icd_container()
		self.reception = make_reception(
			manifest=self.manifest.name, transporter=self.supplier, company=self.company
		)
		# on_submit also creates yard records the transport lines never read, so only
		# the part that records the receipt on the ICD Container is run
		self.reception.db_set("docstatus", 1)
		self.reception.set_icd_container_status(
			RECEIVED_STATUS, add_days(nowdate(), -1), self.reception.transporter
		)

	def tearDown(self):
		# FrappeTestCase only rolls back once per class, and every test makes the same container
		frappe.db.rollback()
		frappe.clear_document_cache("ICD TZ Settings", "ICD TZ Settings")

	def make_icd_container(self) -> str:
		master_bl = frappe.new_doc("ICD Master BL")
		master_bl.update({"m_bl_no": M_BL_NO, "manifest": self.manifest.name, "company": self.company})
		master_bl.flags.ignore_mandatory = True
		master_bl.insert(ignore_permissions=True)

		container = frappe.new_doc("ICD Container")
		container.update(
			{
				"container_no": CONTAINER_NO,
				"manifest": self.manifest.name,
				"master_bl": master_bl.name,
				"company": self.company,
				"posting_date": add_days(nowdate(), -3),
			}
		)
		container.flags.ignore_mandatory = True
		container.insert(ignore_permissions=True)

		return container.name

	def get_services(self, supplier=None, from_date=None, to_date=None, purchase_invoice=None) -> dict:
		return get_transport_services(
			self.company,
			supplier or self.supplier,
			from_date or add_days(nowdate(), -1),
			to_date or nowdate(),
			purchase_invoice,
		)

	def make_invoice_doc(self, name="PI-TEST-1", supplier=None, item_code=None) -> SimpleNamespace:
		# frappe._dict cannot carry an "items" attribute, it shadows the dict method
		return SimpleNamespace(
			name=name,
			company=self.company,
			supplier=supplier or self.supplier,
			items=[
				frappe._dict(item_code=item_code or self.item, icd_container=self.container, idx=1, rate=1)
			],
		)

	def make_invoice(self, rate: float):
		invoice = frappe.new_doc("Purchase Invoice")
		invoice.update({"supplier": self.supplier, "company": self.company, "posting_date": nowdate()})
		invoice.append(
			"items",
			{
				**self.get_services()["items"][0],
				"rate": rate,
				"expense_account": get_expense_account(self.company),
				"cost_center": frappe.db.get_value(
					"Cost Center", {"company": self.company, "is_group": 0}, "name"
				),
			},
		)
		invoice.flags.ignore_permissions = True
		invoice.flags.ignore_mandatory = True
		invoice.insert()

		return invoice

	def get_paid_invoice(self):
		return frappe.db.get_value("ICD Container", self.container, "transport_purchase_invoice")


class TestGetTransportServices(TransportTestCase):
	"""Lines the Get Transport Services dialog puts on the invoice"""

	def test_one_line_per_container_carries_its_dimensions(self):
		make_item_price(self.item, PRICE_LIST, 150000)

		services = self.get_services()

		self.assertEqual(services["buying_price_list"], PRICE_LIST)
		self.assertEqual(len(services["items"]), 1)
		line = services["items"][0]
		self.assertEqual(line["item_code"], self.item)
		self.assertEqual(line["qty"], 1)
		self.assertEqual(line["rate"], 150000)
		self.assertEqual(line["manifest"], self.manifest.name)
		self.assertEqual(line["icd_container"], self.container)
		self.assertEqual(
			line["icd_master_bl"], frappe.db.get_value("ICD Container", self.container, "master_bl")
		)

	def test_an_unpriced_item_comes_with_a_zero_rate(self):
		# the user fills it in, and submit refuses a zero rate
		self.assertEqual(self.get_services()["items"][0]["rate"], 0)

	def test_another_transporter_gets_nothing(self):
		self.assertRaises(frappe.ValidationError, self.get_services, make_supplier(OTHER_TRANSPORTER))

	def test_the_receipt_is_recorded_on_the_icd_container(self):
		received = frappe.db.get_value(
			"ICD Container", self.container, ["transporter", "received_date", "posting_date"], as_dict=True
		)

		self.assertEqual(received.transporter, self.supplier)
		# the day it came in, never the day the record was made from the manifest
		self.assertEqual(str(received.received_date), add_days(nowdate(), -1))
		self.assertNotEqual(received.received_date, received.posting_date)

	def test_the_period_is_matched_on_the_received_date(self):
		self.assertRaises(frappe.ValidationError, self.get_services, from_date=nowdate(), to_date=nowdate())
		self.assertEqual(
			len(
				self.get_services(from_date=add_days(nowdate(), -1), to_date=add_days(nowdate(), -1))["items"]
			),
			1,
		)

	def test_a_cancelled_reception_is_left_out(self):
		self.reception.set_icd_container_status(PENDING_STATUS)

		self.assertFalse(frappe.db.get_value("ICD Container", self.container, "transporter"))
		self.assertRaises(frappe.ValidationError, self.get_services)

	def test_a_container_already_paid_is_left_out(self):
		frappe.db.set_value("ICD Container", self.container, "transport_purchase_invoice", "PI-PAID")

		self.assertRaises(frappe.ValidationError, self.get_services)

	def test_a_container_freed_by_a_cancelled_invoice_shows_again(self):
		# cancel clears the invoice to an empty string, not to NULL
		frappe.db.set_value("ICD Container", self.container, "transport_purchase_invoice", "")

		self.assertEqual(self.get_services()["items"][0]["icd_container"], self.container)

	def test_from_date_after_to_date_is_refused(self):
		self.assertRaises(
			frappe.ValidationError, self.get_services, from_date=nowdate(), to_date=add_days(nowdate(), -1)
		)

	def test_a_container_no_transport_row_matches_is_refused(self):
		set_transport_rows({"expense_item": self.item, "size": "40ft"})

		self.assertRaisesRegex(frappe.ValidationError, f"{CONTAINER_NO} \\(-, DP WORLD\\)", self.get_services)

	def test_the_most_specific_transport_row_picks_the_item(self):
		specific_item = make_transport_item(LOCAL_40FT_ITEM)
		make_item_price(specific_item, PRICE_LIST, 90000)
		set_transport_rows(
			{"expense_item": self.item},
			{"expense_item": specific_item, "size": "40ft", "cargo_type": "Local", "port": "DP WORLD"},
		)
		frappe.db.set_value("ICD Container", self.container, "size", "40")
		master_bl = frappe.db.get_value("ICD Container", self.container, "master_bl")
		frappe.db.set_value("ICD Master BL", master_bl, "cargo_classification", "IM")

		line = self.get_services()["items"][0]

		self.assertEqual(line["item_code"], specific_item)
		self.assertEqual(line["rate"], 90000)

	def test_another_draft_carrying_the_container_blocks_the_fetch(self):
		draft = self.make_invoice(rate=100).name

		self.assertRaises(frappe.ValidationError, self.get_services)
		# refetching into that same draft replaces its own lines
		self.assertEqual(len(self.get_services(purchase_invoice=draft)["items"]), 1)


class TestTransportInvoiceStamp(TransportTestCase):
	"""Marking the ICD Container once its transport is paid"""

	def test_submitting_and_cancelling_the_invoice(self):
		invoice = self.make_invoice(rate=100)

		invoice.submit()
		self.assertEqual(self.get_paid_invoice(), invoice.name)
		self.assertRaisesRegex(frappe.ValidationError, "Cancel that invoice first", self.reception.cancel)

		invoice.cancel()
		self.assertFalse(self.get_paid_invoice())

	def test_a_zero_rate_invoice_is_not_submitted(self):
		invoice = self.make_invoice(rate=0)

		self.assertRaisesRegex(frappe.ValidationError, "Set a rate on row 1", invoice.submit)
		self.assertFalse(self.get_paid_invoice())

	def test_submit_marks_the_container(self):
		stamp_transport_invoice(self.make_invoice_doc())

		self.assertEqual(self.get_paid_invoice(), "PI-TEST-1")

	def test_a_container_cannot_be_paid_twice(self):
		stamp_transport_invoice(self.make_invoice_doc())

		self.assertRaises(frappe.ValidationError, stamp_transport_invoice, self.make_invoice_doc("PI-TEST-2"))
		self.assertEqual(self.get_paid_invoice(), "PI-TEST-1")

	def test_a_container_of_another_transporter_is_refused(self):
		doc = self.make_invoice_doc(supplier=make_supplier(OTHER_TRANSPORTER))

		self.assertRaises(frappe.ValidationError, stamp_transport_invoice, doc)
		self.assertFalse(self.get_paid_invoice())

	def test_a_line_on_any_transport_item_marks_the_container(self):
		other_item = make_transport_item(LOCAL_40FT_ITEM)
		set_transport_rows({"expense_item": self.item}, {"expense_item": other_item, "size": "40ft"})

		stamp_transport_invoice(self.make_invoice_doc(item_code=other_item))

		self.assertEqual(self.get_paid_invoice(), "PI-TEST-1")

	def test_a_line_of_another_item_marks_nothing(self):
		stamp_transport_invoice(self.make_invoice_doc(item_code="Some Other Item"))

		self.assertFalse(self.get_paid_invoice())

	def test_cancel_clears_only_its_own_mark(self):
		stamp_transport_invoice(self.make_invoice_doc())

		clear_transport_invoice(self.make_invoice_doc("PI-TEST-2"))
		self.assertEqual(self.get_paid_invoice(), "PI-TEST-1")

		clear_transport_invoice(self.make_invoice_doc())
		self.assertFalse(self.get_paid_invoice())

	def test_a_paid_reception_cannot_be_cancelled(self):
		validate_reception_transport_unpaid(self.manifest.name, CONTAINER_NO)
		stamp_transport_invoice(self.make_invoice_doc())

		self.assertRaises(
			frappe.ValidationError, validate_reception_transport_unpaid, self.manifest.name, CONTAINER_NO
		)

	def test_a_transport_line_is_held_on_wip(self):
		wip = frappe.db.get_value(
			"Account", {"company": self.company, "is_group": 0, "root_type": "Asset"}, "name"
		)
		frappe.db.set_single_value("ICD TZ Settings", {"enable_wip_for_expenses": 1, "wip_account": wip})
		doc = self.make_invoice_doc()

		set_wip_account(doc)

		self.assertEqual(doc.items[0].expense_account, wip)


class TestZeroRate(FrappeTestCase):
	"""Every purchase invoice line needs a rate before submit"""

	def make_doc(self, *rates):
		return SimpleNamespace(
			items=[frappe._dict(idx=index, rate=rate) for index, rate in enumerate(rates, start=1)]
		)

	def test_a_zero_rate_line_blocks_submit(self):
		self.assertRaises(frappe.ValidationError, validate_no_zero_rate, self.make_doc(100, 0))

	def test_priced_lines_pass(self):
		validate_no_zero_rate(self.make_doc(100, 250))
