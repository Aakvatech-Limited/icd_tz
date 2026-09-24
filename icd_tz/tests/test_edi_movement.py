# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from icd_tz.icd_tz.api.edi.codeco import attach_gate_in, attach_gate_out
from icd_tz.icd_tz.api.edi.movement import from_container_reception, from_gate_pass

test_ignore = ["Company", "Cost Center"]

CONTAINER_NO = "UACU6042588"
M_BL_NO = "HLCUTYO250101920"

# what Amend copies over from the cancelled document
INHERITED_EDI_VALUES = {
	"edi_file": "/private/files/old.edi",
	"receiver_email": "old@example.com",
	"receiver_cc_email": "old-cc@example.com",
}


class TestEDIMovement(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("ICD TZ Settings", "received_date_threshold_hours", 48)
		frappe.db.set_single_value("ICD TZ Settings", "enable_edi", 1)
		frappe.db.set_single_value("ICD TZ Settings", "icd_un_locode", "TZDAR")
		frappe.db.delete("EDI Partner", {"shipping_line_code": "CMA"})
		frappe.get_doc(
			{
				"doctype": "EDI Partner",
				"shipping_line_code": "CMA",
				"enable_edi": 1,
				"connection_type": "SMTP",
				"receiver_email": "edi@example.com",
				"receiver_cc_email": "ops@example.com",
			}
		).insert(ignore_permissions=True)
		self.manifest = make_manifest()

	def tearDown(self):
		frappe.db.rollback()

	# --- gate in ----------------------------------------------------------

	def test_gate_in_reads_the_iso_type_from_the_manifest(self):
		movement = from_container_reception(make_reception(size="45G1"))

		self.assertEqual(movement.iso_size_type, "45G1")

	def test_a_full_container_gates_in_laden(self):
		movement = from_container_reception(make_reception(freight_indicator="FCL"))

		self.assertFalse(movement.is_empty)

	def test_an_emp_container_gates_in_empty(self):
		movement = from_container_reception(make_reception(freight_indicator="EMP"))

		self.assertTrue(movement.is_empty)

	def test_gate_in_is_dated_when_the_box_crossed_the_gate(self):
		# received_date is derived from the storage threshold and falls back to the
		# discharge date at the seaport, which is a different event days earlier
		reception = make_reception(posting_date=nowdate(), ship_dc_date=add_days(nowdate(), -1))

		self.assertNotEqual(reception.received_date, getdate(reception.posting_date))
		self.assertEqual(
			from_container_reception(reception).event_datetime,
			f"{reception.posting_date} {reception.icd_time_in}",
		)

	def test_gate_in_carries_the_vessel_of_the_manifest(self):
		movement = from_container_reception(make_reception())

		self.assertEqual(movement.vessel_name, "YOKOHAMA STAR")
		self.assertEqual(movement.voyage_no, "2508S")
		self.assertEqual(movement.call_sign, "V7A7456")

	def test_a_vehicle_produces_no_gate_in_movement(self):
		add_manifest_unit(self.manifest, "MC1D4GCA1SP000579", unit_type="V")
		reception = make_reception(container_no="MC1D4GCA1SP000579")

		self.assertIsNone(from_container_reception(reception))

	def test_loose_cargo_produces_no_gate_in_movement(self):
		add_manifest_unit(self.manifest, "LOOSE", unit_type="L")

		self.assertIsNone(from_container_reception(make_reception(container_no="LOOSE")))

	def test_a_unit_absent_from_the_manifest_produces_no_movement(self):
		self.assertIsNone(from_container_reception(make_reception(container_no="ZZZU0000000")))

	# --- gate out ---------------------------------------------------------

	def test_gate_out_of_a_physical_container(self):
		movement = from_gate_pass(make_gate_pass(self.make_container()))

		self.assertIsNotNone(movement)
		self.assertFalse(movement.is_gate_in)
		self.assertEqual(movement.container_no, CONTAINER_NO)

	def test_an_hbl_record_produces_no_gate_out_movement(self):
		container = self.make_container(has_hbl=1, h_bl_no="HBL-1")

		self.assertIsNone(from_gate_pass(make_gate_pass(container)))

	def test_a_non_container_unit_produces_no_gate_out_movement(self):
		container = self.make_container(type_of_container="V")

		self.assertIsNone(from_gate_pass(make_gate_pass(container)))

	def test_a_gate_pass_without_a_container_produces_no_movement(self):
		gate_pass = frappe.new_doc("Gate Pass")

		self.assertIsNone(from_gate_pass(gate_pass))

	def test_a_stripped_container_leaves_empty(self):
		container = self.make_container(freight_indicator="LCL")

		self.assertTrue(from_gate_pass(make_gate_pass(container)).is_empty)

	def test_an_emp_container_leaves_empty(self):
		container = self.make_container(freight_indicator="EMP")

		self.assertTrue(from_gate_pass(make_gate_pass(container)).is_empty)

	def test_a_full_container_leaves_laden(self):
		container = self.make_container(freight_indicator="FCL")

		self.assertFalse(from_gate_pass(make_gate_pass(container)).is_empty)

	def test_gate_out_carries_the_container_number_of_the_container_record(self):
		container = self.make_container()
		gate_pass = make_gate_pass(container)
		gate_pass.container_no = ""

		self.assertEqual(from_gate_pass(gate_pass).container_no, CONTAINER_NO)

	# --- nothing owed must never stop the gate ----------------------------

	def test_a_vehicle_gates_in_without_an_edi_file_and_without_an_error(self):
		add_manifest_unit(self.manifest, "MC1D4GCA1SP000579", unit_type="V")
		reception = make_reception(container_no="MC1D4GCA1SP000579")

		attach_gate_in(reception)

		self.assertFalse(reception.edi_file)

	def test_an_hbl_record_gates_out_without_an_edi_file_and_without_an_error(self):
		gate_pass = make_gate_pass(self.make_container(has_hbl=1, h_bl_no="HBL-1"))

		attach_gate_out(gate_pass)

		self.assertFalse(gate_pass.edi_file)

	def test_a_container_of_an_unconfigured_line_gates_in_without_an_edi_file(self):
		reception = make_reception(shipping_line_code="NOSUCH")

		attach_gate_in(reception)

		self.assertFalse(reception.edi_file)

	def test_a_container_with_no_size_stops_the_document(self):
		reception = make_reception(size="")

		with self.assertRaises(frappe.ValidationError):
			attach_gate_in(reception)

	def test_a_configured_container_does_get_a_file(self):
		reception = make_reception()

		attach_gate_in(reception)

		self.assertTrue(reception.edi_file)
		self.assertEqual(reception.receiver_email, "edi@example.com")

	# --- SMTP recipients --------------------------------------------------

	def test_gate_in_of_an_smtp_partner_carries_both_recipients(self):
		reception = make_reception()

		attach_gate_in(reception)

		self.assertEqual(reception.receiver_email, "edi@example.com")
		self.assertEqual(reception.receiver_cc_email, "ops@example.com")

	def test_gate_out_of_an_smtp_partner_carries_both_recipients(self):
		gate_pass = make_gate_pass(self.make_container())
		gate_pass.submitted_date = nowdate()
		gate_pass.submitted_time = "10:00:00"

		attach_gate_out(gate_pass)

		self.assertTrue(gate_pass.edi_file)
		self.assertEqual(gate_pass.receiver_email, "edi@example.com")
		self.assertEqual(gate_pass.receiver_cc_email, "ops@example.com")

	def test_an_amended_reception_of_an_unconfigured_line_drops_the_inherited_recipients(self):
		reception = make_reception(shipping_line_code="NOSUCH", **INHERITED_EDI_VALUES)

		attach_gate_in(reception)

		for fieldname in INHERITED_EDI_VALUES:
			self.assertFalse(reception.get(fieldname), fieldname)

	def test_an_amended_reception_of_an_sftp_partner_drops_the_inherited_recipients(self):
		frappe.db.set_value("EDI Partner", "CMA", "connection_type", "SFTP")
		frappe.clear_document_cache("EDI Partner", "CMA")
		reception = make_reception(**INHERITED_EDI_VALUES)

		attach_gate_in(reception)

		self.assertNotEqual(reception.edi_file, INHERITED_EDI_VALUES["edi_file"])
		self.assertFalse(reception.receiver_email)
		self.assertFalse(reception.receiver_cc_email)

	def test_an_amended_hbl_gate_pass_drops_the_inherited_recipients(self):
		gate_pass = make_gate_pass(self.make_container(has_hbl=1, h_bl_no="HBL-1"))
		gate_pass.update(INHERITED_EDI_VALUES)

		attach_gate_out(gate_pass)

		for fieldname in INHERITED_EDI_VALUES:
			self.assertFalse(gate_pass.get(fieldname), fieldname)

	def test_gate_out_takes_the_shipping_line_from_the_container(self):
		movement = from_gate_pass(make_gate_pass(self.make_container()))

		self.assertEqual(movement.shipping_line_code, "CMA")

	# --- helpers ----------------------------------------------------------

	def make_container(self, **values):
		reception = make_reception()
		container = frappe.new_doc("Container")
		container.update(
			{
				"container_reception": reception.name,
				"container_no": CONTAINER_NO,
				"manifest": self.manifest.name,
				"m_bl_no": M_BL_NO,
				"size": "45G1",
				"type_of_container": "C",
				"status": "In Yard",
				**values,
			}
		)
		# create_mbl_container appends this row before saving, and Container relies on it
		container.append("container_dates", {"date": reception.received_date})
		container.flags.ignore_mandatory = True
		container.insert(ignore_permissions=True)

		return container


def make_manifest():
	manifest = frappe.new_doc("Manifest")
	manifest.update(
		{
			"manifest": "/private/files/test-manifest.xlsx",
			"port": "DP WORLD",
			"mrn": "25ISS000048",
			"vessel_name": "YOKOHAMA STAR",
			"call_sign": "V7A7456",
			"voyage_no": "2508S",
			"arrival_date": nowdate(),
		}
	)
	manifest.append(
		"master_bl", {"m_bl_no": M_BL_NO, "shipping_agent_code": "CMA", "shipping_agent_name": "CMA CGM"}
	)
	manifest.insert(ignore_permissions=True)
	add_manifest_unit(manifest, CONTAINER_NO)

	return manifest


def add_manifest_unit(manifest, container_no, unit_type="C"):
	manifest.append(
		"containers",
		{
			"m_bl_no": M_BL_NO,
			"container_no": container_no,
			"type_of_container": unit_type,
			"container_size": "45G1",
			"freight_indicator": "FCL" if unit_type == "C" else "",
		},
	)
	manifest.save(ignore_permissions=True)


def make_reception(**values):
	reception = frappe.new_doc("Container Reception")
	reception.update(
		{
			"manifest": frappe.db.get_value("Manifest", {}, "name"),
			"container_no": CONTAINER_NO,
			"m_bl_no": M_BL_NO,
			"size": "45G1",
			"freight_indicator": "FCL",
			"weight": 25129,
			"weight_unit": "KG",
			"seal_no_1": "TW1234567",
			"posting_date": nowdate(),
			"ship_dc_date": nowdate(),
			"icd_time_in": "22:55:00",
			"port": "DP WORLD",
			**values,
		}
	)
	reception.flags.ignore_mandatory = True
	reception.insert(ignore_permissions=True)

	return reception


def make_gate_pass(container):
	gate_pass = frappe.new_doc("Gate Pass")
	gate_pass.update({"container_id": container.name, "manifest": container.manifest})
	gate_pass.flags.ignore_mandatory = True
	gate_pass.insert(ignore_permissions=True)

	return gate_pass
