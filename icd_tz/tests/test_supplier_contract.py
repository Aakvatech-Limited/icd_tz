# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from icd_tz.icd_tz.api.contract import SUPPLIER_PARTY_TYPE, get_active_contract
from icd_tz.tests.test_port_expenses import make_buying_price_list
from icd_tz.tests.test_storage_contract import create_price_list, make_contract
from icd_tz.tests.test_transport_charges import make_supplier

SUPPLIER = "_Test Contract Supplier"
BUYING_PRICE_LIST = "_Test Supplier Contract Buying"


class TestSupplierContract(FrappeTestCase):
	def setUp(self):
		self.supplier = make_supplier(SUPPLIER)
		self.price_list = make_buying_price_list(BUYING_PRICE_LIST)

	def tearDown(self):
		frappe.db.rollback()

	def make_contract(self, **kwargs):
		return make_contract(self.supplier, party_type=SUPPLIER_PARTY_TYPE, **kwargs)

	def set_transporter(self):
		frappe.db.set_value("Supplier", self.supplier, "is_transporter", 1)

	def test_a_supplier_contract_keeps_rate_based_but_not_storage_days(self):
		contract = self.make_contract(is_rate_based=1, price_list=self.price_list, is_storage_days_based=1)
		contract.insert()

		self.assertEqual(contract.is_rate_based, 1)
		self.assertEqual(contract.price_list, self.price_list)
		self.assertEqual(contract.is_storage_days_based, 0)

	def test_a_supplier_contract_needs_a_period(self):
		contract = self.make_contract(end_date=None)

		self.assertRaisesRegex(frappe.ValidationError, "Supplier Contracts", contract.insert)

	def test_supplier_contracts_cannot_overlap(self):
		self.make_contract().insert()

		overlapping = self.make_contract(start_date=add_days(nowdate(), 30))

		self.assertRaisesRegex(frappe.ValidationError, "overlapping", overlapping.insert)

	def test_a_supplier_contract_refuses_a_selling_price_list(self):
		contract = self.make_contract(is_rate_based=1, price_list=create_price_list("_Test ICD Selling List"))

		self.assertRaisesRegex(frappe.ValidationError, "not a buying price list", contract.insert)

	def test_a_supplier_contract_does_not_need_a_price_list(self):
		contract = self.make_contract(is_rate_based=1)
		contract.insert()
		contract.submit()

		self.assertEqual(contract.docstatus, 1)

	def test_a_transporter_contract_needs_rate_based_and_a_price_list(self):
		self.set_transporter()

		contract = self.make_contract(is_rate_based=1)
		contract.insert()
		self.assertRaisesRegex(frappe.ValidationError, "contract of transporter", contract.submit)

		contract.reload()
		contract.price_list = self.price_list
		contract.save()
		contract.submit()
		self.assertEqual(contract.docstatus, 1)

	def test_the_active_contract_is_read_on_the_given_date(self):
		contract = self.make_contract(
			is_rate_based=1,
			price_list=self.price_list,
			start_date=add_days(nowdate(), -60),
			end_date=add_days(nowdate(), -31),
		)
		contract.insert()
		contract.submit()

		self.assertEqual(get_active_contract(SUPPLIER_PARTY_TYPE, self.supplier), {})
		self.assertEqual(
			get_active_contract(SUPPLIER_PARTY_TYPE, self.supplier, add_days(nowdate(), -45))["name"],
			contract.name,
		)
