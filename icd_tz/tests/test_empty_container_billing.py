# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from icd_tz.icd_tz.api.sales_order import (
	get_empty_container_services,
	is_empty_container_order,
	make_empty_container_sales_order,
	validate_empty_containers_are_billed_apart,
)
from icd_tz.icd_tz.api.utils import get_cargo_container_ids
from icd_tz.tests.test_edi_movement import CONTAINER_NO, M_BL_NO, make_manifest, make_reception

test_ignore = ["Company", "Cost Center"]


def make_order_for(*container_ids):
	# frappe._dict cannot carry an "items" attribute, it shadows the dict method
	return SimpleNamespace(items=[frappe._dict(container_id=container_id) for container_id in container_ids])


class TestEmptyContainerBilling(FrappeTestCase):
	"""Keeping the shipping line debt off the consignee invoice"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		make_manifest()
		self.reception = make_reception()

	def tearDown(self):
		frappe.db.rollback()

	def make_container(self, is_empty_container=0, has_hbl=0, m_bl_no=M_BL_NO):
		container = frappe.new_doc("Container")
		container.update(
			{
				"container_reception": self.reception.name,
				"container_no": CONTAINER_NO,
				"m_bl_no": m_bl_no,
				"size": "45G1",
				"status": "In Yard",
				"has_hbl": has_hbl,
				"is_empty_container": is_empty_container,
			}
		)
		container.append("container_dates", {"date": nowdate()})
		container.flags.ignore_mandatory = True
		container.insert(ignore_permissions=True)

		return container.name

	# --- keeping the two debts apart -------------------------------------

	def test_an_order_billing_only_empty_containers_is_allowed(self):
		doc = make_order_for(self.make_container(1), self.make_container(1))

		validate_empty_containers_are_billed_apart(doc)
		self.assertTrue(is_empty_container_order(doc))

	def test_an_order_billing_only_cargo_is_allowed(self):
		doc = make_order_for(self.make_container(0), self.make_container(0))

		validate_empty_containers_are_billed_apart(doc)
		self.assertFalse(is_empty_container_order(doc))

	def test_an_order_mixing_an_empty_container_with_cargo_is_refused(self):
		# Update Items must refill this one from the consignee cargo, not the shipping line
		doc = make_order_for(self.make_container(1), self.make_container(0))

		self.assertRaises(frappe.ValidationError, validate_empty_containers_are_billed_apart, doc)
		self.assertFalse(is_empty_container_order(doc))

	def test_an_order_with_no_containers_is_not_an_empty_container_order(self):
		self.assertFalse(is_empty_container_order(make_order_for()))

	# --- what the M BL covers --------------------------------------------

	def test_the_cargo_of_an_m_bl_excludes_the_empty_box_and_house_bills(self):
		cargo = self.make_container(0)
		self.make_container(is_empty_container=1)
		self.make_container(has_hbl=1)

		self.assertEqual(get_cargo_container_ids(M_BL_NO), [cargo])

	# --- billing the shipping line ---------------------------------------

	def test_billing_empty_containers_needs_a_customer(self):
		self.assertRaises(frappe.ValidationError, make_empty_container_sales_order, M_BL_NO, None)

	def test_billing_empty_containers_needs_an_m_bl_no(self):
		self.assertRaises(frappe.ValidationError, make_empty_container_sales_order, None, "_Test Customer")

	def test_an_m_bl_with_nothing_owing_is_reported_rather_than_ordered(self):
		self.make_container(is_empty_container=1)

		self.assertRaises(frappe.ValidationError, make_empty_container_sales_order, M_BL_NO, "_Test Customer")

	def test_a_container_with_no_chargeable_days_raises_no_storage_row(self):
		self.make_container(is_empty_container=1)

		self.assertEqual(get_empty_container_services(M_BL_NO), [])

	def test_the_cargo_of_an_m_bl_is_never_read_as_empty_container_storage(self):
		self.make_container(is_empty_container=0)

		self.assertEqual(get_empty_container_services(M_BL_NO), [])


class TestEmptyContainerIsNotServiced(FrappeTestCase):
	"""An empty box owes storage and nothing else"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		make_manifest()
		self.reception = make_reception()

	def tearDown(self):
		frappe.db.rollback()

	def make_container(self, is_empty_container):
		container = frappe.new_doc("Container")
		container.update(
			{
				"container_reception": self.reception.name,
				"container_no": CONTAINER_NO,
				"m_bl_no": M_BL_NO,
				"size": "45G1",
				"status": "In Yard",
				"is_empty_container": is_empty_container,
			}
		)
		container.append("container_dates", {"date": nowdate()})
		container.flags.ignore_mandatory = True
		container.insert(ignore_permissions=True)

		return container.name

	def make_service_order(self, container_id):
		service_order = frappe.new_doc("Service Order")
		service_order.update({"container_id": container_id, "container_no": CONTAINER_NO})
		service_order.flags.ignore_mandatory = True

		return service_order

	def test_a_service_order_is_refused_for_an_empty_container(self):
		# shore handling, corridor levy, stripping and the rest cannot arise on a box
		# that holds no cargo, so it must not reach a Service Order by any route
		service_order = self.make_service_order(self.make_container(1))

		self.assertRaises(frappe.ValidationError, service_order.insert, ignore_permissions=True)

	def test_a_cargo_container_passes_the_guard(self):
		# the rest of the insert prices every service, which needs the criteria
		# configured, so the guard itself is what this asserts
		service_order = self.make_service_order(self.make_container(0))

		service_order.validate_not_an_empty_container()

	def test_the_guard_ignores_an_order_with_no_container(self):
		frappe.new_doc("Service Order").validate_not_an_empty_container()


class TestEmptyContainerOrderGuards(FrappeTestCase):
	"""Refusing a second bill for storage days already on a draft"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		make_manifest()
		self.reception = make_reception()

	def tearDown(self):
		frappe.db.rollback()

	def test_a_draft_order_already_billing_the_box_blocks_another(self):
		from icd_tz.icd_tz.api.sales_order import validate_no_draft_empty_container_order

		container = frappe.new_doc("Container")
		container.update(
			{
				"container_reception": self.reception.name,
				"container_no": CONTAINER_NO,
				"m_bl_no": M_BL_NO,
				"status": "In Yard",
				"is_empty_container": 1,
			}
		)
		container.append("container_dates", {"date": nowdate()})
		container.flags.ignore_mandatory = True
		container.insert(ignore_permissions=True)

		# nothing drafted yet, so the guard lets it through
		validate_no_draft_empty_container_order({container.name})

		order = frappe.new_doc("Sales Order")
		order.update({"customer": "_Test Customer", "transaction_date": nowdate()})
		order.append("items", {"item_code": "_Test Item", "qty": 1, "container_id": container.name})
		order.flags.ignore_mandatory = True
		order.flags.ignore_validate = True
		order.insert(ignore_permissions=True)

		self.assertRaises(frappe.ValidationError, validate_no_draft_empty_container_order, {container.name})
