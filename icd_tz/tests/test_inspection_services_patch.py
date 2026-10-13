# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.patches import move_inspection_services_to_container
from icd_tz.tests.test_container_income_refs import get_container, insert, make_reception_containers
from icd_tz.tests.utils import insert_inspection_service, skip_without_inspection_services

test_ignore = ["Company", "Cost Center"]

CHARGE_FIELDS = [
	"has_lift_on_off_charge",
	"lo_sales_invoice",
	"has_change_of_status_charge",
	"cs_sales_invoice",
]


class TestInspectionServicesPatch(FrappeTestCase):
	"""The Lift and Change of Status rows of old inspections move to the Container"""

	def setUp(self):
		skip_without_inspection_services(self)

	def tearDown(self):
		frappe.db.rollback()

	def get_charges(self, container_id) -> list:
		container = get_container(container_id)
		return [container[field] for field in CHARGE_FIELDS]

	def test_each_service_moves_with_its_submitted_invoice(self):
		paid, unpaid = make_reception_containers()
		insert("Sales Invoice", name="_T-SINV-LIFT", docstatus=1)
		insert("Sales Invoice", name="_T-SINV-CS", docstatus=1)
		insert_inspection_service(paid, "Lift Off 20ft", sales_invoice="_T-SINV-LIFT")
		insert_inspection_service(paid, "Change of Status", sales_invoice="_T-SINV-CS")
		insert_inspection_service(unpaid, "LIFT ON")
		insert_inspection_service(unpaid, "STATUS CHANGE to LCL")

		move_inspection_services_to_container.execute()

		self.assertEqual(self.get_charges(paid), [1, "_T-SINV-LIFT", 1, "_T-SINV-CS"])
		self.assertEqual(self.get_charges(unpaid), [1, None, 1, None])

	def test_a_change_of_status_fills_the_inspection(self):
		container_id, _ = make_reception_containers()
		inspection = insert_inspection_service(
			container_id, "Change of Status", volume=12.5, counted_packages=40
		)

		move_inspection_services_to_container.execute()

		self.assertEqual(
			frappe.db.get_value(
				"Container Inspection", inspection, ["container_status", "volume", "counted_packages"]
			),
			("LCL", 12.5, 40),
		)

	def test_a_cancelled_invoice_is_not_copied(self):
		container_id, _ = make_reception_containers()
		insert("Sales Invoice", name="_T-SINV-LIFT", docstatus=2)
		insert_inspection_service(container_id, "Lift Off", sales_invoice="_T-SINV-LIFT")

		move_inspection_services_to_container.execute()

		self.assertEqual(self.get_charges(container_id), [1, None, 0, None])

	def test_other_services_and_draft_inspections_change_nothing(self):
		mbl, hbl = make_reception_containers()
		insert_inspection_service(mbl, "Stripping")
		insert_inspection_service(hbl, "Change of Status", docstatus=0)

		move_inspection_services_to_container.execute()

		self.assertEqual(self.get_charges(mbl), [0, None, 0, None])
		self.assertEqual(self.get_charges(hbl), [0, None, 0, None])
