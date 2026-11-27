import hashlib
from typing import ClassVar

import frappe
from frappe import _
from frappe.utils import cint

SETTINGS = "TANeSW Settings"
SHARED = "TANeSW Settings"  # name shown for the shared login (it lives on TANeSW Settings)
SHARED_USER = (
	"tanesw-shared-login"  # token-cache owner: every user of the shared login shares one TANeSW token
)
TANESW_ROLES = ("TANeSW User", "TANeSW Operations", "System Manager")


class SharedAccount:
	"""The one TANeSW login kept on TANeSW Settings, used by every ERPNext user holding a TANeSW role (one shared
	login instead of TANeSW credentials per user). It answers the same attributes
	and methods api_client reads from a TANeSW User Account."""

	name = SHARED
	user = SHARED_USER
	enabled = 1
	_status: ClassVar[dict] = {
		"last_successful_connection": "login_last_success",
		"last_connection_status": "login_status",
		"last_connection_error": "login_error",
	}

	def __init__(self, settings=None):
		s = settings or frappe.get_single(SETTINGS)
		self._settings = s
		self.tanesw_id = (s.get("login_tanesw_id") or "").strip()
		self.company_tin = s.get("login_company_tin")
		self.company_code = s.get("login_company_code")
		self.company_type = s.get("login_company_type")
		self.role_code = s.get("login_role_code")
		self.warehouse_code = (s.get("login_warehouse_code") or "").strip().upper()

	def get(self, key, default=None):
		return getattr(self, key, default)

	def get_password(self, fieldname="tanesw_password", raise_exception=True):
		return self._settings.get_password("login_password", raise_exception=raise_exception)

	def db_set(self, fieldname, value):
		field = self._status.get(fieldname)
		if field:
			frappe.db.set_single_value(SETTINGS, field, value)


def shared_login_configured(settings=None):
	s = settings or frappe.get_single(SETTINGS)
	return bool(
		(s.get("login_tanesw_id") or "").strip()
		and s.get_password("login_password", raise_exception=False)
		and (s.get("login_warehouse_code") or "").strip()
	)


def facility_code():
	"""Our ICD's TANeSW code: TANeSW Settings > Warehouse Code (e.g. WITZDL019). Empty until it is set."""
	return str(frappe.db.get_single_value(SETTINGS, "login_warehouse_code") or "").strip().upper()


@frappe.whitelist(methods=["POST"])
def get_facility_code():
	require_tanesw_user()
	return facility_code()


def require_tanesw_user():
	"""Whitelisted endpoints that write TANeSW records or parse uploads without calling TANeSW (calls to TANeSW are
	already refused for users without a TANeSW role, in get_current_user_account)."""
	if not has_tanesw_role():
		frappe.throw(
			_("Only users with the TANeSW User or TANeSW Operations role can use TANeSW."),
			frappe.PermissionError,
		)


def has_tanesw_role(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(TANESW_ROLES))


def get_current_user_account():
	"""The TANeSW login for this request: the user's own TANeSW User Account if one exists (optional), otherwise the
	shared login on TANeSW Settings for anyone holding a TANeSW role."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sign in to ERPNext before using TANeSW"))

	account_name = frappe.db.get_value("TANeSW User Account", {"user": user, "enabled": 1}, "name")
	if account_name:
		return frappe.get_doc("TANeSW User Account", account_name)

	if not has_tanesw_role(user):
		frappe.throw(
			_("Only users with the TANeSW User or TANeSW Operations role can use TANeSW."),
			frappe.PermissionError,
		)
	settings = frappe.get_single(SETTINGS)
	if not shared_login_configured(settings):
		frappe.throw(
			_(
				"The TANeSW login is not set yet: a System Manager enters the TANeSW ID and password in "
				"TANeSW Settings > TANeSW Login."
			),
			title=_("TANeSW login"),
		)
	return SharedAccount(settings)


def build_token_cache_key(user, company_code, role_code):
	scope = "|".join((user or "", company_code or "", role_code or ""))
	digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
	return f"tanesw:token:{digest}"


def assert_write_operations_enabled():
	from tanesw_integration import test_mode

	if test_mode.on():  # every TANeSW write is refused; Carry-In Submit is simulated in cargo.cri_submit
		frappe.throw(
			_(
				"TEST MODE is on: this action is not sent to TANeSW. Only Carry-In Submit is simulated "
				"(it creates the ERP records)."
			),
			title=_("Test Mode"),
		)
	settings = frappe.get_single("TANeSW Settings")
	if not cint(settings.enable_write_operations):
		frappe.throw(_("TANeSW write operations are disabled in TANeSW Settings"))


def watcher_accounts(settings=None):
	"""Logins for background jobs: the watcher / fallback TANeSW User Accounts if set, otherwise the shared login."""
	s = settings or frappe.get_single(SETTINGS)
	accounts = [
		a for a in (s.get("background_watcher_account"), s.get("background_watcher_fallback_account")) if a
	]
	if not accounts and shared_login_configured(s):
		accounts = [SHARED]
	return accounts
