# Copyright (c) 2026, elius mgani and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import comma_or, escape_html

from icd_tz.icd_tz.api.edi.sftp import SFTPConnection
from icd_tz.icd_tz.api.edi.templates import (
	RULES,
	SEEDED_EDI_TYPES,
	get_default_template,
	validate_template,
)

DEFAULT_FILE_NAME_FORMAT = "<sender ID>_<receiver ID>_<message type>_<message #>"
FILE_NAME_PLACEHOLDERS = ("<sender ID>", "<receiver ID>", "<message type>", "<control #>", "<message #>")
# every value a message template can use is also a placeholder, as <container_no> for {{ container_no }}
MESSAGE_PLACEHOLDERS = tuple(sorted({f"<{name}>" for rules in RULES.values() for name in rules["variables"]}))
# without one of these every file of the partner would carry the same name
UNIQUE_PLACEHOLDERS = ("<control #>", "<message #>", "<reference>")
PLACEHOLDER_PATTERN = re.compile(r"<[^>]*>")
# what a file name may carry outside the placeholders, and what their values are cut down to
FILE_UNSAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


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
		file_extension: DF.Literal["edi", "txt"]
		file_name_format: DF.Data | None
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
		self.seed_templates()

	def validate(self):
		self.normalise_code()
		self.validate_file_name_format()
		self.validate_file_name_text()
		self.validate_templates()

	def seed_templates(self) -> list:
		"""Add the shipped template of each type the partner lacks, one it brought is left alone"""

		rows = []
		for edi_type in SEEDED_EDI_TYPES:
			if not self.get_template_row(edi_type):
				template = get_default_template(edi_type)
				rows.append(self.append("templates", {"edi_type": edi_type, "template": template}))

		return rows

	def validate_file_name_format(self):
		# the form fills the default when EDI is ticked, a record saved another way gets it here
		self.file_name_format = (self.file_name_format or "").strip() or DEFAULT_FILE_NAME_FORMAT

		allowed = FILE_NAME_PLACEHOLDERS + MESSAGE_PLACEHOLDERS
		unknown = sorted(set(PLACEHOLDER_PATTERN.findall(self.file_name_format)) - set(allowed))
		if unknown:
			frappe.throw(
				_(
					"File Name Format uses unknown placeholders: {0}. The available placeholders are: {1}"
				).format(", ".join(get_code_list(unknown)), ", ".join(get_code_list(allowed)))
			)

		if not any(placeholder in self.file_name_format for placeholder in UNIQUE_PLACEHOLDERS):
			frappe.throw(
				_("File Name Format must include {0} so that each file gets its own name").format(
					comma_or(get_code_list(UNIQUE_PLACEHOLDERS), add_quotes=False)
				)
			)

	def validate_file_name_text(self):
		"""The text around the placeholders goes into the file name as typed, so it must be safe there"""

		text = PLACEHOLDER_PATTERN.sub("", self.file_name_format)
		unsafe = sorted({character for character in text if FILE_UNSAFE_PATTERN.match(character)})
		if unsafe:
			frappe.throw(
				_(
					"File Name Format may only use letters, digits, dot, dash and underscore outside the placeholders. Remove: {0}"
				).format(", ".join(get_code_list(repr(character) for character in unsafe)))
			)

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

	def get_file_name(
		self, message_type: str, control_reference: str, message_reference: str, message_values: dict
	) -> str:
		"""File name of one interchange, in this partner's naming convention.

		`message_values` is the context the message template is rendered with.
		"""

		values = {
			**{f"<{name}>": value for name, value in message_values.items()},
			"<sender ID>": self.sender,
			"<receiver ID>": self.shipping_line_code,
			"<message type>": message_type,
			"<control #>": control_reference,
			"<message #>": message_reference,
		}

		file_name = PLACEHOLDER_PATTERN.sub(
			lambda match: get_file_safe_text(values[match.group()]), self.file_name_format
		)

		return f"{file_name}.{self.file_extension}"

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
	def try_edi_connection(self) -> dict:
		"""Open an SFTP session with the saved settings and list the target directory"""

		self.check_permission("read")

		with SFTPConnection(self) as connection:
			entries = connection.count_entries()

		return {
			"success": True,
			"message": _("Connection successful. Found {0} entries in '{1}'").format(
				entries, connection.directory
			),
		}

	def validate_sftp_settings(self):
		missing = [
			self.meta.get_label(fieldname) for fieldname in ("url", "user", "port") if not self.get(fieldname)
		]
		if missing:
			frappe.throw(_("The following fields are required: {0}").format(", ".join(missing)))

	def send_file(self, file_name: str, content: str | bytes):
		"""Upload one file to the partner directory"""

		with SFTPConnection(self) as connection:
			connection.upload(file_name, content)


@frappe.whitelist()
def get_default_file_name_format() -> str:
	"""Read by the form when EDI is ticked, so the user starts from it and changes it there"""

	return DEFAULT_FILE_NAME_FORMAT


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


def get_file_safe_text(value: str) -> str:
	"""A message value fit for a file name. A released character goes with its release character."""

	return FILE_UNSAFE_PATTERN.sub("_", value).strip("_")


def get_code_list(values) -> list[str]:
	"""Escaped, so the message dialog shows a placeholder instead of reading it as an HTML tag"""

	return [f"<code>{escape_html(value)}</code>" for value in values]
