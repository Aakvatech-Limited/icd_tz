# Copyright (c) 2026, elius mgani and contributors
# For license information, please see license.txt

import io
import socket

import frappe
from frappe import _
from frappe.model.document import Document

from icd_tz.icd_tz.api.edi.templates import (
	SEEDED_EDI_TYPE,
	get_default_template,
	validate_template,
)

CONNECT_TIMEOUT = 30


class EDIPartner(Document):
	"""EDI identity and delivery channel of one shipping line.

	The record is named by the TANeSW shipping agent code, which is also the
	identifier the shipping line is addressed by in the EDIFACT interchange.
	"""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from icd_tz.icd_tz.doctype.edi_partner_template.edi_partner_template import EDIPartnerTemplate

		authentication_key: DF.Password | None
		authentication_method: DF.Literal["Password", "Key"]
		connection_type: DF.Literal["", "SFTP", "SMTP"]
		directory: DF.Data | None
		enable_edi: DF.Check
		ip_behind_dns: DF.Data | None
		password: DF.Password | None
		port: DF.Int
		receiver_cc_email: DF.Data | None
		receiver_email: DF.Data | None
		sender_id: DF.Data | None
		shipping_line_code: DF.Data
		shipping_line_name: DF.Data | None
		source_ip: DF.Data | None
		templates: DF.Table[EDIPartnerTemplate]
		url: DF.Data | None
		user: DF.Data | None
	# end: auto-generated types

	def before_naming(self):
		# the record is named by the code, so it has to be normalised before the name is set
		self.normalise_code()

	def before_insert(self):
		# a new partner starts from the shipped template, one it brought is left alone
		if not self.get_template_row(SEEDED_EDI_TYPE):
			self.append(
				"templates",
				{"edi_type": SEEDED_EDI_TYPE, "template": get_default_template(SEEDED_EDI_TYPE)},
			)

	def validate(self):
		self.normalise_code()
		self.validate_templates()

	def validate_templates(self):
		seen = set()

		for row in self.templates:
			if row.edi_type in seen:
				frappe.throw(_("Row #{0}: there is already a {1} template").format(row.idx, row.edi_type))
			seen.add(row.edi_type)

			validate_template(row.edi_type, row.template)

	def get_template_row(self, edi_type: str):
		rows = self.get("templates", {"edi_type": edi_type}, limit=1)

		return rows[0] if rows else None

	def get_template(self, edi_type: str) -> str:
		"""This partner's template, falling back to the shipped one for a partner that has none"""

		row = self.get_template_row(edi_type)

		return row.template if row and row.template else get_default_template(edi_type)

	def normalise_code(self):
		self.shipping_line_code = (self.shipping_line_code or "").strip().upper()

	@property
	def sender(self) -> str:
		"""Our identifier as this shipping line knows us"""

		if self.sender_id:
			return self.sender_id

		return frappe.db.get_single_value("ICD TZ Settings", "default_sender_id") or ""

	@property
	def is_sftp(self) -> bool:
		return self.connection_type == "SFTP"

	@property
	def is_smtp(self) -> bool:
		return self.connection_type == "SMTP"

	@frappe.whitelist()
	def try_edi_connection(self):
		"""Open an SFTP session with the configured settings and list the target directory"""

		self.check_permission("read")
		self.validate_sftp_settings()

		try:
			import paramiko
		except ImportError:
			frappe.throw(_("paramiko is not installed. Install it with 'pip install paramiko'"))

		client = paramiko.SSHClient()
		# the partners do not publish host keys, so the key is accepted on first use
		client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

		try:
			client.connect(**self.get_connect_arguments(paramiko))

			return {"success": True, "message": self.list_remote_directory(client)}

		except paramiko.AuthenticationException:
			frappe.throw(_("Authentication failed. Please check the credentials."))
		except paramiko.SSHException as error:
			frappe.throw(_("SSH error: {0}").format(str(error)))
		except TimeoutError:
			frappe.throw(_("Connection timed out. Please check the server address and port."))
		except OSError as error:
			frappe.throw(_("Network error: {0}").format(str(error)))
		finally:
			client.close()

	def validate_sftp_settings(self):
		missing = [
			self.meta.get_label(fieldname) for fieldname in ("url", "user", "port") if not self.get(fieldname)
		]
		if missing:
			frappe.throw(_("The following fields are required: {0}").format(", ".join(missing)))

	def get_connect_arguments(self, paramiko) -> dict:
		arguments = {
			"hostname": self.url,
			"port": self.port or 22,
			"username": self.user,
			"timeout": CONNECT_TIMEOUT,
			"allow_agent": False,
			"look_for_keys": False,
		}

		if self.source_ip:
			arguments["sock"] = self._create_bound_socket(self.source_ip, self.url, arguments["port"])

		if self.authentication_method == "Key":
			arguments["pkey"] = self.get_private_key(paramiko)
		else:
			password = self.get_password("password", raise_exception=False)
			if not password:
				frappe.throw(_("Password is required when the authentication method is Password"))
			arguments["password"] = password

		return arguments

	def get_private_key(self, paramiko):
		"""Parse the stored key, trying every format paramiko understands"""

		key_material = self.get_password("authentication_key", raise_exception=False)
		if not key_material:
			frappe.throw(_("Authentication Key is required when the authentication method is Key"))

		key_file = io.StringIO(key_material)
		for key_type in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey):
			try:
				key_file.seek(0)
				return key_type.from_private_key(key_file)
			except (paramiko.SSHException, ValueError):
				continue

		frappe.throw(_("Could not read the Authentication Key. Please check that it is a valid private key."))

	def list_remote_directory(self, client) -> str:
		directory = self.directory or "/"
		sftp = client.open_sftp()

		try:
			sftp.chdir(directory)
			entries = len(sftp.listdir())
		except OSError as error:
			frappe.throw(
				_("Connected, but the directory '{0}' could not be opened: {1}").format(directory, str(error))
			)
		finally:
			sftp.close()

		return _("Connection successful. Found {0} entries in '{1}'").format(entries, directory)

	def _create_bound_socket(self, source_ip, host, port):
		"""Socket bound to a fixed source IP, for partners that allowlist one address"""

		bound_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		bound_socket.settimeout(CONNECT_TIMEOUT)
		bound_socket.bind((source_ip, 0))
		bound_socket.connect((host, port))

		return bound_socket


def get_partner(shipping_line_code: str | None) -> EDIPartner | None:
	"""Enabled partner of a TANeSW shipping agent code.

	Returns None when EDI is switched off, the code is missing, or the shipping
	line has no record. A missing partner is not an error: the ICD works with
	lines that do not exchange EDI at all.
	"""

	if not shipping_line_code:
		return None

	if not frappe.db.get_single_value("ICD TZ Settings", "enable_edi"):
		return None

	name = frappe.db.get_value(
		"EDI Partner", {"shipping_line_code": shipping_line_code.strip().upper(), "enable_edi": 1}
	)
	if not name:
		return None

	return frappe.get_cached_doc("EDI Partner", name)
