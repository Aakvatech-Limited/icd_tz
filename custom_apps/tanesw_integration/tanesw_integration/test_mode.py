"""TEST MODE: try the screens end to end without sending anything to TANeSW.

With "Test Mode" ticked in TANeSW Settings:
  - the screens' Save / Submit / Delete buttons are enabled, but EVERY write to TANeSW is refused on the server
    (credentials.assert_write_operations_enabled) -- except Carry-In Submit, which is simulated: nothing goes to TRA and
    the ERP side runs for real (movement order filled, Container Reception created and submitted in icd_tz);
  - every TANeSW screen shows an orange TEST MODE badge;
Reading from TANeSW is unchanged. Never leave it on in production: carry-ins would not reach TRA.
"""

import frappe
from frappe import _
from frappe.utils import cint

SETTINGS = "TANeSW Settings"


def on():
	return bool(cint(frappe.db.get_single_value(SETTINGS, "test_mode")))


def simulated_carry_in_submit(body):
	"""What cargo.cri_submit returns instead of TANeSW's answer while in test mode."""
	return {
		"testMode": 1,
		"criBaseNo": body.get("criBaseNo"),
		"crn": body.get("crn"),
		"msg": _("TEST MODE: the carry-in was NOT sent to TANeSW; only the ERP records were created."),
	}
