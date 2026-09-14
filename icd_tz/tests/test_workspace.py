# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

test_ignore = ["Company", "Cost Center"]

WORKSPACE = "ICD"


class TestICDWorkspace(FrappeTestCase):
	def test_every_link_names_a_doctype_that_exists(self):
		"""One link to a missing doctype makes the whole workspace render no cards"""

		links = frappe.get_all(
			"Workspace Link",
			filters={"parent": WORKSPACE, "type": "Link"},
			fields=["label", "link_to"],
		)
		self.assertTrue(links, f"the {WORKSPACE} workspace has no links")

		missing = [
			f"{link.label} -> {link.link_to}"
			for link in links
			if link.link_to and not frappe.db.exists("DocType", link.link_to)
		]

		self.assertEqual(missing, [], f"{WORKSPACE} workspace links to doctypes that do not exist")

	def test_the_workspace_still_renders_its_cards(self):
		from frappe.desk.desktop import get_desktop_page

		frappe.set_user("Administrator")
		page = get_desktop_page(frappe.as_json({"name": WORKSPACE}))

		self.assertTrue(page.get("cards", {}).get("items"), f"the {WORKSPACE} workspace renders no cards")
