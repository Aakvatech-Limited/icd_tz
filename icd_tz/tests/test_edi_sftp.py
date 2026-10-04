# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import io
from unittest.mock import MagicMock, patch

import frappe
import paramiko
from frappe.tests.utils import FrappeTestCase

from icd_tz.icd_tz.api.edi.sftp import SFTPConnection, get_pem_text, get_private_key

test_ignore = ["Company", "Cost Center"]


class TestEDISFTP(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		key_file = io.StringIO()
		paramiko.RSAKey.generate(1024).write_private_key(key_file)
		cls.key_text = key_file.getvalue()

	def setUp(self):
		frappe.db.delete("EDI Partner", {"shipping_line_code": "ZSFTP"})
		self.partner = frappe.get_doc(
			{
				"doctype": "EDI Partner",
				"shipping_line_code": "ZSFTP",
				"connection_type": "SFTP",
				"url": "sftp.example.com",
				"port": 2222,
				"user": "edi",
				"directory": "/inbox",
				"authentication_method": "Password",
				"password": "secret",
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	# --- private key ------------------------------------------------------

	def test_a_key_pasted_without_line_breaks_is_read(self):
		self.assertIsInstance(get_private_key(self.key_text.replace("\n", "")), paramiko.RSAKey)

	def test_a_key_with_line_breaks_turned_to_spaces_is_read(self):
		self.assertIsInstance(get_private_key(self.key_text.replace("\n", " ")), paramiko.RSAKey)

	def test_pem_lines_are_rebuilt(self):
		lines = get_pem_text(self.key_text.replace("\n", "")).splitlines()

		self.assertEqual(lines[0], "-----BEGIN RSA PRIVATE KEY-----")
		self.assertEqual(lines[-1], "-----END RSA PRIVATE KEY-----")
		self.assertTrue(all(len(line) <= 64 for line in lines[1:-1]))

	def test_the_key_field_takes_a_whole_private_key(self):
		# the form clips a paste at the field length, and a 4096 bit RSA key runs to about 3400 characters
		field = frappe.get_meta("EDI Partner").get_field("authentication_key")

		self.assertEqual(field.fieldtype, "Password")
		self.assertGreaterEqual(field.length, 4096)

	def test_text_that_is_not_a_key_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			get_private_key("not a key")

	def test_a_missing_key_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			get_private_key(None)

	# --- connect arguments --------------------------------------------------

	def test_password_login_sends_the_stored_password(self):
		arguments = SFTPConnection(self.partner).get_connect_arguments()

		self.assertEqual(arguments["password"], "secret")
		self.assertEqual((arguments["hostname"], arguments["port"]), ("sftp.example.com", 2222))
		self.assertNotIn("pkey", arguments)

	def test_key_login_sends_the_parsed_key(self):
		self.partner.update({"authentication_method": "Key", "authentication_key": self.key_text})
		self.partner.save()

		arguments = SFTPConnection(self.partner).get_connect_arguments()

		self.assertIsInstance(arguments["pkey"], paramiko.RSAKey)
		self.assertNotIn("password", arguments)

	def test_a_missing_password_is_rejected(self):
		self.partner.password = None
		self.partner.save()

		with self.assertRaises(frappe.ValidationError):
			SFTPConnection(self.partner).get_connect_arguments()

	def test_missing_server_settings_are_named(self):
		self.partner.url = None

		with self.assertRaises(frappe.ValidationError) as context:
			SFTPConnection(self.partner).connect()

		self.assertIn("URL", str(context.exception))

	# --- session ----------------------------------------------------------

	def test_test_connection_reports_the_directory_entries(self):
		client = self.mock_client()
		client.open_sftp.return_value.listdir.return_value = ["a.edi", "b.edi"]

		result = self.partner.try_edi_connection()

		self.assertTrue(result["success"])
		self.assertIn("2 entries in '/inbox'", result["message"])
		client.close.assert_called_once()

	def test_failed_authentication_is_reported_plainly(self):
		self.mock_client().connect.side_effect = paramiko.AuthenticationException()

		with self.assertRaises(frappe.ValidationError) as context:
			self.partner.try_edi_connection()

		self.assertIn("Authentication failed", str(context.exception))

	def test_an_unreachable_server_is_reported_as_a_network_error(self):
		self.mock_client().connect.side_effect = ConnectionRefusedError("refused")

		with self.assertRaises(frappe.ValidationError) as context:
			self.partner.try_edi_connection()

		self.assertIn("Network error", str(context.exception))

	def test_upload_writes_into_the_partner_directory(self):
		client = self.mock_client()

		self.partner.send_file("CMA_0001.edi", "UNB+UNOA:2'")

		upload = client.open_sftp.return_value.putfo
		file_object, remote_path = upload.call_args.args
		self.assertEqual(remote_path, "/inbox/CMA_0001.edi")
		self.assertEqual(file_object.getvalue(), b"UNB+UNOA:2'")
		self.assertTrue(upload.call_args.kwargs["confirm"])
		client.close.assert_called_once()

	def mock_client(self) -> MagicMock:
		client = MagicMock()
		patcher = patch("icd_tz.icd_tz.api.edi.sftp.paramiko.SSHClient", return_value=client)
		patcher.start()
		self.addCleanup(patcher.stop)

		return client
