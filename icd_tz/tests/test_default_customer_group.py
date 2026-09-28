# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.utils import get_default_customer_group

test_ignore = ["Company", "Cost Center"]

ROOT_GROUP = "All Customer Groups"
TEST_GROUP = "_Test ICD Customer Group"


class TestDefaultCustomerGroup(FrappeTestCase):
	"""Auto-created customers always get a non-group Customer Group"""

	def setUp(self):
		if not frappe.db.exists("Customer Group", TEST_GROUP):
			frappe.get_doc(
				{
					"doctype": "Customer Group",
					"customer_group_name": TEST_GROUP,
					"parent_customer_group": ROOT_GROUP,
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def test_the_selling_settings_group_is_used(self):
		frappe.db.set_single_value("Selling Settings", "customer_group", TEST_GROUP)

		self.assertEqual(get_default_customer_group(), TEST_GROUP)

	def test_a_group_node_in_selling_settings_is_skipped(self):
		frappe.db.set_single_value("Selling Settings", "customer_group", ROOT_GROUP)

		customer_group = get_default_customer_group()

		self.assertNotEqual(customer_group, ROOT_GROUP)
		self.assertEqual(frappe.db.get_value("Customer Group", customer_group, "is_group"), 0)

	def test_no_non_group_customer_group_is_rejected(self):
		frappe.db.set_single_value("Selling Settings", "customer_group", ROOT_GROUP)
		frappe.db.set_value("Customer Group", {"is_group": 0}, "is_group", 1)

		self.assertRaises(frappe.ValidationError, get_default_customer_group)
