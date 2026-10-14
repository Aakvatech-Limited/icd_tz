# Copyright (c) 2024, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

test_ignore = ["Company", "Cost Center"]


def make_manifest(containers, hbl_containers=()):
	manifest = frappe.new_doc("Manifest")
	for row in containers:
		manifest.append("containers", {"type_of_container": "C", **row})
	for container_no in hbl_containers:
		manifest.append("hbl_containers", {"container_no": container_no})
	return manifest


class TestManifestDashboard(FrappeTestCase):
	"""The reception progress card counts each container by its freight"""

	def test_an_lcl_container_without_house_bills_counts_as_lcl(self):
		manifest = make_manifest(
			[
				{"container_no": "FCLU0000001", "freight_indicator": "FCL"},
				{"container_no": "LCLU0000001", "freight_indicator": "LCL"},
			]
		)

		data = manifest.get_dashboard_data()

		self.assertEqual((data["total_fcl"], data["total_lcl"]), (1, 1))

	def test_a_container_with_house_bills_counts_as_lcl(self):
		manifest = make_manifest(
			[{"container_no": "HBLU0000001", "freight_indicator": "FCL"}], hbl_containers=["HBLU0000001"]
		)

		self.assertEqual(manifest.get_dashboard_data()["total_lcl"], 1)
