"""One container crossing the ICD gate, read from a Container Reception or a Gate Pass."""

from dataclasses import dataclass

import frappe

# Manifest Type column. Only a container carries a container number, a size and an ISO type.
CONTAINER_TYPE = "C"

# TANeSW freight indicators that mean the box holds no cargo when it crosses the gate.
# EMP comes from the manifest, LCL is set by the ICD once the box has been stripped.
UNLADEN_INDICATORS = ("EMP", "LCL")

KILOGRAM_UNITS = ("KG", "KGM", "KGS")


@dataclass(frozen=True)
class ContainerMovement:
	"""Everything a CODECO message needs about one gate movement."""

	document: str
	is_gate_in: bool
	shipping_line_code: str
	container_no: str
	iso_size_type: str
	is_empty: bool
	m_bl_no: str = ""
	weight: float | None = None
	weight_unit: str = ""
	seal_no: str = ""
	event_datetime: object = None
	transporter: str = ""
	truck: str = ""
	voyage_no: str = ""
	vessel_name: str = ""
	call_sign: str = ""

	@property
	def has_weight_in_kilograms(self) -> bool:
		return bool(self.weight) and str(self.weight_unit).upper() in KILOGRAM_UNITS


def from_container_reception(reception) -> ContainerMovement | None:
	"""Gate-in movement, or None when the reception is not a container"""

	if not is_container(reception.manifest, reception.container_no):
		return None

	voyage = get_voyage(reception.manifest)

	return ContainerMovement(
		document=reception.name,
		is_gate_in=True,
		shipping_line_code=reception.shipping_line_code,
		container_no=reception.container_no,
		iso_size_type=reception.size,
		is_empty=str(reception.freight_indicator or "").upper() in UNLADEN_INDICATORS,
		m_bl_no=reception.m_bl_no,
		weight=reception.weight,
		weight_unit=reception.weight_unit,
		seal_no=reception.seal_no_1,
		# posting_date is when the box crossed the gate. received_date is derived from the
		# storage threshold and falls back to the seaport discharge date, so it stands in only
		# when a reception carries no posting date at all, which older records do not.
		event_datetime=get_event_datetime(
			reception.posting_date or reception.received_date, reception.icd_time_in
		),
		transporter=reception.transporter,
		truck=reception.truck,
		voyage_no=reception.voyage_no or voyage.get("voyage_no"),
		vessel_name=reception.ship or voyage.get("vessel_name"),
		call_sign=voyage.get("call_sign"),
	)


def from_gate_pass(gate_pass) -> ContainerMovement | None:
	"""Gate-out movement, or None when the gate pass is not for a physical container.

	A Gate Pass raised against an HBL record moves cargo out of a container that
	stays in the yard, so it is not an equipment movement and carries no CODECO.
	"""

	if not gate_pass.container_id:
		return None

	container = frappe.get_cached_doc("Container", gate_pass.container_id)
	if container.has_hbl or container.type_of_container != CONTAINER_TYPE:
		return None

	voyage = get_voyage(gate_pass.manifest)
	is_empty = bool(gate_pass.is_empty_container) or (
		str(container.freight_indicator or "").upper() in UNLADEN_INDICATORS
	)

	return ContainerMovement(
		document=gate_pass.name,
		is_gate_in=False,
		shipping_line_code=container.sline_code or gate_pass.shipping_line_code,
		# the Gate Pass copies are fetched values, the Container is the source of truth
		container_no=container.container_no or gate_pass.container_no,
		iso_size_type=container.size or gate_pass.size,
		is_empty=is_empty,
		m_bl_no=gate_pass.m_bl_no or container.m_bl_no,
		weight=container.weight,
		weight_unit=container.weight_unit,
		seal_no=gate_pass.seal_no or container.seal_no_1,
		event_datetime=get_event_datetime(
			gate_pass.gate_out_date or gate_pass.submitted_date, gate_pass.submitted_time
		),
		transporter=gate_pass.transporter,
		truck=gate_pass.truck,
		voyage_no=gate_pass.voyage_no or voyage.get("voyage_no"),
		vessel_name=gate_pass.vessel_name or voyage.get("vessel_name"),
		call_sign=voyage.get("call_sign"),
	)


def is_container(manifest: str, container_no: str) -> bool:
	"""Vehicles, loose cargo and other units share the field but are not equipment"""

	if not manifest or not container_no:
		return False

	unit_type = frappe.db.get_value(
		"Containers Detail", {"parent": manifest, "container_no": container_no}, "type_of_container"
	)

	return unit_type == CONTAINER_TYPE


def get_voyage(manifest: str) -> dict:
	"""Vessel, voyage and call sign of the manifest, which the carrier matches the event to"""

	if not manifest:
		return {}

	return (
		frappe.db.get_value("Manifest", manifest, ["vessel_name", "voyage_no", "call_sign"], as_dict=True)
		or {}
	)


def get_event_datetime(date, time):
	if date and time:
		return f"{date} {time}"

	return date
