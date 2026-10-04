"""SFTP session to one EDI Partner, opened with its password or its private key."""

import io
import re
import socket
import textwrap

import frappe
import paramiko
from frappe import _

CONNECT_TIMEOUT = 30

# one PEM block: a single-line password input loses the line breaks, so the key is rebuilt from it
PEM_PATTERN = re.compile(r"(-----BEGIN [A-Z0-9 ]+-----)(.*?)(-----END [A-Z0-9 ]+-----)", re.DOTALL)
PEM_LINE_LENGTH = 64
KEY_TYPES = (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey)


class SFTPConnection:
	"""Use as a context manager: the session is closed however the block ends.

	with SFTPConnection(partner) as connection:
	        connection.upload("file.edi", content)
	"""

	def __init__(self, partner):
		self.partner = partner
		self.client = None
		self.sftp = None

	def __enter__(self):
		self.connect()

		return self

	def __exit__(self, *exception):
		self.close()

	def connect(self):
		self.partner.validate_sftp_settings()
		self.client = paramiko.SSHClient()
		# the partners do not publish host keys, so the key is accepted on first use
		self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosemgrep

		try:
			self.client.connect(**self.get_connect_arguments())
			self.sftp = self.client.open_sftp()
		except (paramiko.SSHException, OSError) as error:
			self.close()
			frappe.throw(get_connection_error_message(error))

	def close(self):
		if self.sftp:
			self.sftp.close()
		if self.client:
			self.client.close()

	def get_connect_arguments(self) -> dict:
		partner = self.partner
		arguments = {
			"hostname": partner.url,
			"port": partner.port or 22,
			"username": partner.user,
			"timeout": CONNECT_TIMEOUT,
			"allow_agent": False,
			"look_for_keys": False,
		}

		if partner.authentication_method == "Key":
			arguments["pkey"] = get_private_key(
				partner.get_password("authentication_key", raise_exception=False)
			)
		else:
			arguments["password"] = partner.get_password("password", raise_exception=False)
			if not arguments["password"]:
				frappe.throw(_("Password is required when the authentication method is Password"))

		# opened last, so a credential error above leaves no socket behind
		if partner.source_ip:
			arguments["sock"] = socket.create_connection(
				(partner.url, arguments["port"]), CONNECT_TIMEOUT, source_address=(partner.source_ip, 0)
			)

		return arguments

	@property
	def directory(self) -> str:
		return self.partner.directory or "/"

	def count_entries(self) -> int:
		"""Entries in the partner directory, which proves it exists and can be read"""

		try:
			return len(self.sftp.listdir(self.directory))
		except OSError as error:
			frappe.throw(
				_("Connected, but the directory '{0}' could not be opened: {1}").format(
					self.directory, str(error)
				)
			)

	def upload(self, file_name: str, content: str | bytes):
		if isinstance(content, str):
			content = content.encode()

		remote_path = f"{self.directory.rstrip('/')}/{file_name}"
		# confirm stats the file after writing, so a short write fails here instead of at the partner
		self.sftp.putfo(io.BytesIO(content), remote_path, file_size=len(content), confirm=True)


def get_connection_error_message(error: Exception) -> str:
	if isinstance(error, paramiko.AuthenticationException):
		return _("Authentication failed. Please check the user and the credentials.")
	if isinstance(error, paramiko.SSHException):
		return _("SSH error: {0}").format(str(error))
	if isinstance(error, TimeoutError):
		return _("Connection timed out. Please check the server address and port.")

	return _("Network error: {0}").format(str(error))


def get_private_key(key_text: str | None):
	"""Parse a stored private key in any format paramiko reads"""

	if not key_text:
		frappe.throw(_("Authentication Key is required when the authentication method is Key"))

	key_file = io.StringIO(get_pem_text(key_text))
	for key_type in KEY_TYPES:
		try:
			key_file.seek(0)
			return key_type.from_private_key(key_file)
		except (paramiko.SSHException, ValueError):
			continue

	frappe.throw(
		_(
			"Could not read the Authentication Key. Paste an unencrypted OpenSSH or PEM private key (RSA, ECDSA or Ed25519)."
		)
	)


def get_pem_text(key_text: str) -> str:
	"""The key with its PEM line breaks put back, whether they came as spaces or not at all"""

	match = PEM_PATTERN.search(key_text)
	if not match:
		return key_text

	header, body, footer = match.groups()
	body_lines = textwrap.wrap("".join(body.split()), PEM_LINE_LENGTH)

	return "\n".join([header, *body_lines, footer]) + "\n"
