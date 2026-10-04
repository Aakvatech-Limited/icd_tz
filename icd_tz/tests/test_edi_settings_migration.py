# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from icd_tz.patches.migrate_edi_settings_to_edi_partner import (
	carry_master_switch,
	create_partner,
	drop_old_single,
)

test_ignore = ["Company", "Cost Center"]

OLD_SETTINGS = {
	"sender_id": "TZDARDSEL",
	"receiver_id": "cma",
	"enable_edi": 1,
	"connection_type": "SFTP",
	"url": "sftp.example.com",
	"port": 22,
	"user": "icduser",
	"authentication_method": "Password",
	"password": "s3cret",
	"authentication_key": "-----BEGIN KEY-----",
	"directory": "/in",
	"source_ip": "10.0.0.1",
	"receiver_email": "edi@example.com",
	"receiver_cc_email": "ops@example.com",
}


class TestEDISettingsMigration(FrappeTestCase):
	def setUp(self):
		# the site may already carry this shipping line, the rollback puts it back
		frappe.db.delete("EDI Partner", {"shipping_line_code": "CMA"})
		self.partners_before = frappe.db.count("EDI Partner")

	def tearDown(self):
		frappe.db.rollback()

	def test_the_partner_is_named_by_the_old_receiver_id(self):
		create_partner(OLD_SETTINGS)

		self.assertTrue(frappe.db.exists("EDI Partner", "CMA"))

	def test_every_channel_value_is_carried_over(self):
		create_partner(OLD_SETTINGS)
		partner = frappe.get_doc("EDI Partner", "CMA")

		self.assertEqual(partner.sender_id, "TZDARDSEL")
		self.assertEqual(partner.enable_edi, 1)
		self.assertEqual(partner.connection_type, "SFTP")
		self.assertEqual(partner.url, "sftp.example.com")
		self.assertEqual(partner.port, 22)
		self.assertEqual(partner.user, "icduser")
		self.assertEqual(partner.directory, "/in")
		self.assertEqual(partner.source_ip, "10.0.0.1")
		self.assertEqual(partner.receiver_email, "edi@example.com")
		self.assertEqual(partner.receiver_cc_email, "ops@example.com")

	def test_the_credentials_are_carried_over_and_stay_encrypted(self):
		create_partner(OLD_SETTINGS)
		partner = frappe.get_doc("EDI Partner", "CMA")

		self.assertEqual(partner.get_password("password"), "s3cret")
		self.assertEqual(partner.get_password("authentication_key"), "-----BEGIN KEY-----")

	def test_running_the_patch_twice_leaves_the_partner_alone(self):
		create_partner(OLD_SETTINGS)
		frappe.db.set_value("EDI Partner", "CMA", "url", "edited-by-hand.example.com")

		create_partner(OLD_SETTINGS)

		self.assertEqual(frappe.db.get_value("EDI Partner", "CMA", "url"), "edited-by-hand.example.com")
		self.assertEqual(frappe.db.count("EDI Partner", {"shipping_line_code": "CMA"}), 1)

	def test_no_partner_is_created_without_a_receiver_id(self):
		create_partner({**OLD_SETTINGS, "receiver_id": ""})

		self.assertEqual(frappe.db.count("EDI Partner"), self.partners_before)

	def test_the_master_switch_is_carried_into_icd_tz_settings(self):
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 0)

		carry_master_switch(OLD_SETTINGS)

		self.assertEqual(frappe.db.get_single_value("ICD TZ Settings", "enable_edi"), 1)

	def test_dropping_a_single_that_is_already_gone_is_harmless(self):
		drop_old_single()

		self.assertFalse(frappe.db.exists("DocType", "EDI Settings"))
