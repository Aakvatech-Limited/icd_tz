# Copyright (c) 2025, Administrator and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EDISettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		authentication_key: DF.Code | None
		authentication_method: DF.Literal["Password", "Key"]
		directory: DF.Data | None
		ip_behind_dns: DF.Data | None
		password: DF.Password | None
		port: DF.Int
		source_ip: DF.Data | None
		url: DF.Data
		user: DF.Data
	# end: auto-generated types

	@frappe.whitelist()
	def try_edi_connection(self):
		"""
		Test SFTP/SSH connection with the configured settings.
		Returns a success or failure message.
		"""
		import io
		import socket
		
		try:
			import paramiko
		except ImportError:
			frappe.throw(_("paramiko library is not installed. Please install it using 'pip install paramiko'"))
		
		if not self.url:
			frappe.throw(_("URL is required"))
		if not self.user:
			frappe.throw(_("User is required"))
		if not self.port:
			frappe.throw(_("Port is required"))
		
		hostname = self.url
		port = self.port or 22
		username = self.user
		auth_method = self.authentication_method
		directory = self.directory or "/"
		
		# Create SSH client
		ssh = paramiko.SSHClient()
		ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		
		try:
			# Configure connection parameters
			connect_kwargs = {
				"hostname": hostname,
				"port": port,
				"username": username,
				"timeout": 30,
				"allow_agent": False,
				"look_for_keys": False
			}
			
			# Handle source IP binding if specified
			if self.source_ip:
				connect_kwargs["sock"] = self._create_bound_socket(
					self.source_ip, 
					hostname, 
					port
				)
			
			# Set authentication method
			if auth_method == "Password":
				password = self.get_password("password")
				if not password:
					frappe.throw(_("Password is required when using Password authentication"))
				connect_kwargs["password"] = password
			elif auth_method == "Key":
				if not self.authentication_key:
					frappe.throw(_("Authentication Key is required when using Key authentication"))
				
				# Load private key from string
				key_file = io.StringIO(self.authentication_key)
				
				# Try different key types
				private_key = None
				key_types = [
					paramiko.RSAKey,
					paramiko.Ed25519Key,
					paramiko.ECDSAKey,
					paramiko.DSSKey
				]
				
				for key_type in key_types:
					try:
						key_file.seek(0)
						private_key = key_type.from_private_key(key_file)
						break
					except (paramiko.SSHException, ValueError):
						continue
				
				if not private_key:
					frappe.throw(_("Could not parse the authentication key. Please ensure it's a valid private key."))
				
				connect_kwargs["pkey"] = private_key
			
			# Attempt connection
			ssh.connect(**connect_kwargs)
			
			# Test SFTP connection and directory access
			sftp = ssh.open_sftp()
			try:
				sftp.chdir(directory)
				files = sftp.listdir()
				file_count = len(files)
				sftp.close()
			except IOError as e:
				sftp.close()
				ssh.close()
				frappe.throw(_("Connected successfully, but could not access directory '{0}': {1}").format(
					directory, str(e)
				))
			
			ssh.close()
			
			return {
				"success": True,
				"message": _("Connection successful! Found {0} files/folders in directory '{1}'").format(
					file_count, directory
				)
			}
			
		except paramiko.AuthenticationException:
			frappe.throw(_("Authentication failed. Please check your credentials."))
		except paramiko.SSHException as e:
			frappe.throw(_("SSH error: {0}").format(str(e)))
		except socket.timeout:
			frappe.throw(_("Connection timed out. Please check the server address and port."))
		except socket.error as e:
			frappe.throw(_("Network error: {0}").format(str(e)))
		except Exception as e:
			frappe.throw(_("Connection failed: {0}").format(str(e)))
		finally:
			try:
				ssh.close()
			except:
				pass

	def _create_bound_socket(self, source_ip, dest_host, dest_port):
		"""Create a socket bound to a specific source IP address."""
		import socket
		
		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock.settimeout(30)
		sock.bind((source_ip, 0))  # Bind to source IP with any available port
		sock.connect((dest_host, dest_port))
		return sock
