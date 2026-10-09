# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, nowdate

from icd_tz.icd_tz.report.pending_transporter_invoices.pending_transporter_invoices import execute
from icd_tz.tests.test_port_expenses import make_item_price
from icd_tz.tests.test_transport_charges import PRICE_LIST, TransportTestCase, set_transport_rows

test_ignore = ["Company", "Cost Center"]


class TestPendingTransporterInvoices(TransportTestCase):
	def get_row(self, transporter=None, manifest=None) -> dict | None:
		_columns, rows = execute(
			{
				"company": self.company,
				"from_date": add_days(nowdate(), -1),
				"to_date": nowdate(),
				"transporter": transporter,
				"manifest": manifest,
			}
		)

		return next((row for row in rows if row["icd_container"] == self.container), None)

	def test_a_priced_container_shows_its_item_rate_and_price_list(self):
		make_item_price(self.item, PRICE_LIST, 150000)

		row = self.get_row(self.supplier)

		self.assertEqual(row["transport_item"], self.item)
		self.assertEqual(row["rate"], 150000)
		self.assertEqual(row["price_list"], PRICE_LIST)

	def test_an_unpriced_item_has_no_rate(self):
		self.assertIsNone(self.get_row()["rate"])

	def test_a_container_no_transport_row_matches_has_no_item_or_rate(self):
		set_transport_rows({"expense_item": self.item, "size": "40ft"})

		row = self.get_row()

		self.assertIsNone(row["transport_item"])
		self.assertIsNone(row["rate"])

	def test_a_container_with_no_transporter_shows_only_without_the_filter(self):
		frappe.db.set_value("ICD Container", self.container, "transporter", None)

		self.assertIsNone(self.get_row()["price_list"])
		self.assertIsNone(self.get_row(self.supplier))

	def test_the_manifest_filter_keeps_only_its_containers(self):
		self.assertIsNotNone(self.get_row(manifest=self.manifest.name))
		self.assertIsNone(self.get_row(manifest="NO-SUCH-MANIFEST"))

	def test_a_paid_container_is_left_out(self):
		frappe.db.set_value("ICD Container", self.container, "transport_purchase_invoice", "PI-PAID")

		self.assertIsNone(self.get_row())
