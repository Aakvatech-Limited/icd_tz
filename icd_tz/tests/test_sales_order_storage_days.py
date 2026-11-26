# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from icd_tz.icd_tz.api.sales_order import validate_storage_delivery_date
from icd_tz.tests.test_container_income_refs import make_reception_containers, with_settings
from icd_tz.tests.test_icd_services import services_settings

test_ignore = ["Company", "Cost Center"]


def day(offset: int):
	return getdate(add_days(nowdate(), offset))


class TestContainerStayEnd(FrappeTestCase):
	"""Update Items keeps a container's storage days up to the Sales Order delivery date"""

	def tearDown(self):
		frappe.db.rollback()

	def container_with_days(self, *offsets, invoiced=()):
		mbl, _ = make_reception_containers(cargo_type="Local")
		container = frappe.get_doc("Container", mbl)
		container.container_dates = []
		for offset in offsets:
			sales_invoice = "_T-SINV-ST" if offset in invoiced else None
			container.append("container_dates", {"date": day(offset), "sales_invoice": sales_invoice})

		with with_settings(services_settings()):
			container.save(ignore_permissions=True)
		return container

	def set_end(self, container, offset):
		with with_settings(services_settings()):
			container.set_container_stay_end(day(offset))

		return [getdate(row.date) for row in frappe.get_doc("Container", container.name).container_dates]

	def test_an_earlier_delivery_date_drops_the_later_days(self):
		container = self.container_with_days(-1, 0, 1, 2, 3, 4)

		self.assertEqual(self.set_end(container, 1), [day(-1), day(0), day(1)])

	def test_a_later_delivery_date_adds_the_missing_days(self):
		container = self.container_with_days(-1, 0)

		self.assertEqual(self.set_end(container, 2), [day(-1), day(0), day(1), day(2)])

	def test_an_invoiced_day_is_kept(self):
		container = self.container_with_days(0, 1, 2, invoiced=(1, 2))

		self.assertEqual(self.set_end(container, 0), [day(0), day(1), day(2)])


class TestStorageDeliveryDate(FrappeTestCase):
	"""An ICD Sales Order bills storage up to a delivery date that is not in the past"""

	def order(self, delivery_offset: int, **values):
		return frappe._dict({"m_bl_no": None, "h_bl_no": None, **values}, delivery_date=day(delivery_offset))

	def test_a_past_delivery_date_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			validate_storage_delivery_date(self.order(-1, m_bl_no="_T-MBL"))

	def test_today_and_later_are_accepted(self):
		validate_storage_delivery_date(self.order(0, h_bl_no="_T-HBL"))
		validate_storage_delivery_date(self.order(3, m_bl_no="_T-MBL"))

	def test_an_order_without_a_bill_of_lading_is_not_checked(self):
		validate_storage_delivery_date(self.order(-1))
