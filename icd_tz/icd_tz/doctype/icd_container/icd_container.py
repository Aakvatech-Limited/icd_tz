# Copyright (c) 2026, elius mgani and contributors
# For license information, please see license.txt

from collections import defaultdict
from itertools import islice

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, create_batch, getdate, nowdate

from icd_tz.icd_tz.api.accounting_dimensions import build_dimension_name
from icd_tz.icd_tz.api.port_expenses import (
	get_charge_of_day,
	get_port_storage_bands,
	is_band_configured,
)
from icd_tz.icd_tz.api.purchase_order import set_rows
from icd_tz.icd_tz.api.tanesw import get_bill_crns, get_discharge_date

# containers manifested longer ago than this are left to a manifest scoped run,
# so an unscoped run never retries bills the tracking API will not answer for
DISCHARGE_LOOKUP_DAYS = 60
MAX_BILLS_PER_RUN = 40

# a stay longer than this is settled, an unscoped storage run stops looking at it
STORAGE_LOOKBACK_DAYS = 180
BATCH_SIZE = 100


class ICDContainer(Document):
	"""Accounting dimension value for one manifested unit, MSKU1234567:2026-00042"""

	def autoname(self):
		self.name = build_dimension_name(self.container_no, self.manifest)


def update_ship_dc_dates(manifest=None):
	"""Fill ship_dc_date from TANeSW for manifested containers that lack one

	Grouped by bill of lading so the bill search call is issued once per bill
	rather than once per container.
	"""

	for m_bl_no, containers in get_containers_missing_ship_dc_date(manifest).items():
		try:
			set_bill_discharge_dates(m_bl_no, containers)

		except Exception:
			frappe.log_error(title=f"{m_bl_no}: Port Discharge Date Lookup", message=frappe.get_traceback())

		commit_progress()


def commit_progress():
	"""Keep what is already resolved when a later one fails

	Skipped under test, where a commit would escape the rollback the test case
	relies on and leave its fixtures behind on the site.
	"""

	if not frappe.flags.in_test:
		frappe.db.commit()


def get_containers_missing_ship_dc_date(manifest=None) -> dict:
	"""Pending containers grouped by bill of lading, so each bill is looked up once"""

	filters = {"ship_dc_date": ("is", "not set"), "m_bl_no": ("is", "set")}
	if manifest:
		filters["manifest"] = manifest
	else:
		filters["posting_date"] = (">=", add_days(nowdate(), -DISCHARGE_LOOKUP_DAYS))

	pending = defaultdict(dict)
	for row in frappe.get_all(
		"ICD Container",
		filters=filters,
		fields=["name", "container_no", "m_bl_no", "master_bl", "crn"],
		order_by="m_bl_no asc, creation asc",
	):
		pending[row.m_bl_no][row.container_no] = row

	if manifest:
		return dict(pending)

	return dict(islice(pending.items(), MAX_BILLS_PER_RUN))


def set_bill_discharge_dates(m_bl_no: str, containers: dict):
	"""Resolve the bill once, then ask for the discharge date of each of its containers"""

	crns = sorted({crn for row in containers.values() for crn in (row.crn or "").split(",") if crn})
	if not crns:
		crns = cache_bill_crns(m_bl_no, containers)

	for container_no, container in containers.items():
		discharge_date = get_discharge_date(container_no, m_bl_no, crns=crns)
		if discharge_date:
			frappe.db.set_value(
				"ICD Container", container.name, "ship_dc_date", discharge_date, update_modified=False
			)


def cache_bill_crns(m_bl_no: str, containers: dict) -> list:
	"""Resolve the cargo reference numbers of a bill and store them, so later runs skip the search"""

	crns = get_bill_crns(m_bl_no)
	if not crns:
		return []

	cached = ",".join(crns)
	set_rows("ICD Container", [row.name for row in containers.values()], {"crn": cached})

	# a bill number repeats across manifests, so only the bills of these containers are cached
	master_bls = {row.master_bl for row in containers.values() if row.master_bl}
	set_rows("ICD Master BL", master_bls, {"crn": cached})

	return crns


@frappe.whitelist()
def enqueue_ship_dc_dates(manifest: str) -> bool:
	"""Look up the missing discharge dates of one manifest in the background"""

	# an empty name would only be checked against the doctype and then queue the
	# unscoped site wide run, so it is refused before the permission check
	if not manifest:
		frappe.throw(_("Select a Manifest to fetch discharge dates for"))

	frappe.has_permission("Manifest", "read", doc=manifest, throw=True)

	frappe.enqueue(
		"icd_tz.icd_tz.doctype.icd_container.icd_container.update_ship_dc_dates",
		queue="long",
		timeout=3600,
		manifest=manifest,
		job_id=f"icd-discharge-{manifest}",
		deduplicate=True,
	)

	return True


def update_port_storage_days(manifest=None):
	"""Append one storage day row per calendar day a container spent at the port

	Counting starts at the discharge date and stops on the day the container was
	received at the ICD, which is what keeps the table from growing for ever.
	"""

	containers = get_containers_for_storage_days(manifest)
	if not containers:
		# say why nothing happened, an empty run and a skipped run look identical otherwise
		frappe.logger("icd_tz").info(
			f"Port storage days: nothing to count for {manifest or 'the recent window'}, "
			f"{count_containers_outside_window(manifest)} container(s) fall outside it"
		)
		return

	settings_doc = frappe.get_cached_doc("ICD TZ Settings")
	bands = get_port_storage_bands(settings_doc)
	if not bands or not all(is_band_configured(row) for row in settings_doc.port_storage_days):
		# counting against a half configured band set would leave the uncovered days
		# out, and the page refuses to price in the same state
		frappe.logger("icd_tz").warning(
			"Port storage days: the day ranges are not set on the Expenses tab of ICD TZ Settings"
		)
		return

	manifests = {container.manifest for container in containers}
	receipt_dates = get_icd_receipt_dates(manifests)

	for batch in create_batch(containers, BATCH_SIZE):
		for container in batch:
			try:
				end_date = receipt_dates.get((container.manifest, container.container_no)) or nowdate()
				append_storage_days(container.name, bands, container.ship_dc_date, end_date)

			except Exception:
				frappe.log_error(title=f"{container.name}: Port Storage Days", message=frappe.get_traceback())

		commit_progress()


def get_containers_for_storage_days(manifest=None) -> list:
	"""Containers whose stay can still grow a day row

	The stay is counted from Ship D/C Date, so a container without one has no
	day to count and is left out entirely. An unscoped run is held to the recent
	ones as well, so a year of settled containers is not walked every night to
	append nothing.
	"""

	filters = [["ship_dc_date", "is", "set"]]

	# and then either the manifest asked for, or a window for the scheduled run
	if manifest:
		filters.append(["manifest", "=", manifest])
	else:
		filters.append(["ship_dc_date", ">=", add_days(nowdate(), -STORAGE_LOOKBACK_DAYS)])

	return frappe.get_all(
		"ICD Container",
		filters=filters,
		fields=["name", "manifest", "container_no", "ship_dc_date"],
		order_by="creation asc",
	)


def count_containers_outside_window(manifest=None) -> int:
	"""Dated containers the look back window leaves out, so a quiet run can be explained"""

	if manifest:
		return 0

	return frappe.db.count(
		"ICD Container",
		{
			"ship_dc_date": ("<", add_days(nowdate(), -STORAGE_LOOKBACK_DAYS)),
		},
	)


def get_icd_receipt_dates(manifests: set) -> dict:
	"""Date each container was received at the ICD, keyed by manifest and container number"""

	rows = frappe.get_all(
		"Container",
		filters={"manifest": ("in", list(manifests)), "received_date": ("is", "set")},
		fields=["manifest", "container_no", "received_date"],
	)

	return {(row.manifest, row.container_no): row.received_date for row in rows}


def append_storage_days(container_id: str, bands: dict, start_date, end_date):
	"""Add the day rows a container is still missing, never touching the rows it has"""

	# without a discharge date getdate() would read as today and bill a day that
	# was never counted, so say so rather than write it
	if not start_date:
		frappe.throw(f"{container_id} has no Ship D/C Date, so its port stay cannot be counted")

	# hold the row until this container is saved, or a concurrent run appends the same days twice
	frappe.db.get_value("ICD Container", container_id, "name", for_update=True)

	container_doc = frappe.get_doc("ICD Container", container_id)
	counted = {getdate(row.date) for row in container_doc.storage_dates}

	day = getdate(start_date)
	last_day = getdate(end_date)
	added = 0
	while day <= last_day:
		charge = get_charge_of_day(day, start_date, bands)

		# a row is never revisited, so writing a day no band covers would make it
		# unbillable for ever; leaving it out lets a later run add it once the
		# bands reach that far
		if day not in counted and charge:
			container_doc.append("storage_dates", {"date": day, "charge": charge})
			added += 1

		day = add_days(day, 1)

	if added:
		container_doc.flags.ignore_permissions = True
		container_doc.save()
