import frappe
from frappe.utils.password import delete_all_passwords_for, get_decrypted_password

OLD_SINGLE = "EDI Settings"

# old fieldname -> new fieldname, the two differ only where the old name was ambiguous
CHANNEL_FIELDS = {
	"connection_type": "connection_type",
	"url": "url",
	"port": "port",
	"ip_behind_dns": "ip_behind_dns",
	"source_ip": "source_ip",
	"user": "user",
	"authentication_method": "authentication_method",
	"directory": "directory",
	"receiver_email": "receiver_email",
	"receiver_cc_email": "receiver_cc_email",
}


def execute():
	"""Move the single EDI Settings record into an EDI Partner, then retire the Single.

	EDI Settings held one shipping line. Its receiver_id was the TANeSW shipping
	agent code, which is what the new record is named by, so the values transfer
	one for one.
	"""

	settings = get_old_settings()
	if settings is None:
		drop_old_single()
		return

	carry_master_switch(settings)
	create_partner(settings)
	drop_old_single()


def get_old_settings() -> dict | None:
	"""Values of the retired Single, read straight from the table so no DocType is needed"""

	if not frappe.db.table_exists("Singles"):
		return None

	settings = frappe.db.get_singles_dict(OLD_SINGLE)
	if not settings:
		return None

	# the old authentication key was a plain Code field, the password was encrypted
	settings["password"] = get_decrypted_password(OLD_SINGLE, OLD_SINGLE, "password", raise_exception=False)

	return settings


def carry_master_switch(settings):
	# ICD TZ Settings is a Single, so its columns live in tabSingles and only the meta can be asked
	if not frappe.get_meta("ICD TZ Settings").has_field("enable_edi"):
		return

	frappe.db.set_single_value("ICD TZ Settings", "enable_edi", frappe.utils.cint(settings.get("enable_edi")))


def create_partner(settings):
	shipping_line_code = (settings.get("receiver_id") or "").strip().upper()
	if not shipping_line_code:
		print(f"{OLD_SINGLE} has no Receiver ID, no EDI Partner created")
		return

	if frappe.db.exists("EDI Partner", shipping_line_code):
		print(f"EDI Partner {shipping_line_code} already exists, left as it is")
		return

	partner = frappe.new_doc("EDI Partner")
	partner.shipping_line_code = shipping_line_code
	partner.sender_id = settings.get("sender_id")
	partner.enable_edi = frappe.utils.cint(settings.get("enable_edi"))
	partner.authentication_key = settings.get("authentication_key")
	partner.password = settings.get("password")

	for old_field, new_field in CHANNEL_FIELDS.items():
		partner.set(new_field, settings.get(old_field))

	partner.flags.ignore_permissions = True
	partner.flags.ignore_mandatory = True
	partner.insert()

	print(f"Moved {OLD_SINGLE} into EDI Partner {partner.name}")


def drop_old_single():
	"""The DocType folder is gone from the app, so its record and its stored values go too"""

	# deleting the DocType leaves the Singles values and the stored credentials behind
	delete_all_passwords_for(OLD_SINGLE, OLD_SINGLE)
	frappe.db.delete("Singles", {"doctype": OLD_SINGLE})

	if not frappe.db.exists("DocType", OLD_SINGLE):
		return

	frappe.delete_doc("DocType", OLD_SINGLE, force=True, ignore_missing=True, delete_permanently=True)
	print(f"Removed the {OLD_SINGLE} Single")
