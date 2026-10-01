# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from icd_tz.icd_tz.api.sales_order import make_sales_order, validate_no_draft_sales_order
from icd_tz.tests.test_edi_movement import CONTAINER_NO, M_BL_NO, make_manifest, make_reception

test_ignore = ["Company", "Cost Center"]

H_BL_NO = "HBL-DRAFT-GUARD-01"
SALES_ORDER_API = "icd_tz.icd_tz.api.sales_order"


def make_container(container_reception: str, is_empty_container: int = 0) -> str:
	container = frappe.new_doc("Container")
	container.update(
		{
			"container_reception": container_reception,
			"container_no": CONTAINER_NO,
			"m_bl_no": M_BL_NO,
			"status": "In Yard",
			"is_empty_container": is_empty_container,
		}
	)
	container.append("container_dates", {"date": nowdate()})
	container.flags.ignore_mandatory = True
	container.insert(ignore_permissions=True)

	return container.name


def make_draft_order(container_id: str, m_bl_no: str = M_BL_NO, h_bl_no: str | None = None):
	order = frappe.new_doc("Sales Order")
	order.update(
		{
			"customer": "_Test Customer",
			"transaction_date": nowdate(),
			"m_bl_no": m_bl_no,
			"h_bl_no": h_bl_no,
		}
	)
	order.append("items", {"item_code": "_Test Item", "qty": 1, "container_id": container_id})
	order.flags.ignore_mandatory = True
	order.flags.ignore_validate = True
	order.insert(ignore_permissions=True)

	return order


class TestDraftSalesOrderGuard(FrappeTestCase):
	"""Refusing a second order while a draft for the same BL bills the same container"""

	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		make_manifest()
		self.reception = make_reception()

	def tearDown(self):
		frappe.db.rollback()

	def test_nothing_drafted_lets_the_order_through(self):
		validate_no_draft_sales_order({make_container(self.reception.name)}, m_bl_no=M_BL_NO)

	def test_a_draft_for_the_same_m_bl_and_container_blocks(self):
		container_id = make_container(self.reception.name)
		make_draft_order(container_id)

		self.assertRaises(
			frappe.ValidationError, validate_no_draft_sales_order, {container_id}, m_bl_no=M_BL_NO
		)

	def test_a_draft_for_the_same_h_bl_and_container_blocks(self):
		container_id = make_container(self.reception.name)
		make_draft_order(container_id, h_bl_no=H_BL_NO)

		self.assertRaises(
			frappe.ValidationError, validate_no_draft_sales_order, {container_id}, h_bl_no=H_BL_NO
		)

	def test_a_draft_for_the_same_m_bl_but_other_containers_is_allowed(self):
		make_draft_order(make_container(self.reception.name))

		validate_no_draft_sales_order({make_container(self.reception.name)}, m_bl_no=M_BL_NO)

	def test_a_draft_for_another_bl_with_the_same_container_is_allowed(self):
		container_id = make_container(self.reception.name)
		make_draft_order(container_id, m_bl_no="OTHER-MBL")

		validate_no_draft_sales_order({container_id}, m_bl_no=M_BL_NO)

	def test_a_draft_for_another_h_bl_with_the_same_container_is_allowed(self):
		container_id = make_container(self.reception.name)
		make_draft_order(container_id, h_bl_no="OTHER-HBL")

		validate_no_draft_sales_order({container_id}, h_bl_no=H_BL_NO)

	def test_a_cancelled_order_does_not_block(self):
		container_id = make_container(self.reception.name)
		order = make_draft_order(container_id)
		order.db_set("docstatus", 2)

		validate_no_draft_sales_order({container_id}, m_bl_no=M_BL_NO)

	def test_the_error_names_the_draft_and_points_to_update_items(self):
		container_id = make_container(self.reception.name)
		order = make_draft_order(container_id)

		with self.assertRaises(frappe.ValidationError) as error:
			validate_no_draft_sales_order({container_id}, m_bl_no=M_BL_NO)

		self.assertIn(order.name, str(error.exception))
		self.assertIn("Update Items", str(error.exception))

	def test_make_sales_order_refuses_before_building_a_second_order(self):
		container_id = make_container(self.reception.name)
		make_draft_order(container_id)
		storage_row = {"item_code": "_Test Item", "qty": 1, "container_id": container_id}

		with (
			patch(f"{SALES_ORDER_API}.get_storage_services", return_value=[storage_row]),
			patch(f"{SALES_ORDER_API}.get_service_order_items", return_value=([], [])),
			patch(f"{SALES_ORDER_API}.build_sales_order") as build_sales_order,
		):
			self.assertRaises(frappe.ValidationError, make_sales_order, m_bl_no=M_BL_NO)

		build_sales_order.assert_not_called()
