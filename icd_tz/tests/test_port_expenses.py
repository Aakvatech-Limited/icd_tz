# Copyright (c) 2026, elius mgani and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from icd_tz.icd_tz.api.port_expenses import (
	EXPENSE_TYPES,
	get_cargo_type,
	get_charge_of_day,
	get_criteria_score,
	get_expense_row_containers,
	get_expense_rows,
	get_expense_view,
	get_manifest_header,
	get_matching_criteria,
	get_port_storage_bands,
	get_size_bucket,
)
from icd_tz.icd_tz.api.purchase_order import create_purchase_order, get_expense_coverage
from icd_tz.icd_tz.doctype.icd_container.icd_container import (
	PENDING_STATUS,
	RECEIVED_STATUS,
	append_storage_days,
	get_containers_for_storage_days,
	update_port_storage_days,
)

PORT = "DP WORLD"
M_BL_NO = "MAEU777000111"
BOX_20 = "MSKU2000001"
BOX_40 = "MSKU4000002"
PRICE_LIST = "_Test ICD Buying Price List"
BANDS = (("Free", 1, 5), ("Single", 6, 12), ("Double", 13, 999999))

ITEMS = {
	"Shore": "_Test ICD Shore Expense",
	"Levy": "_Test ICD Levy Expense",
	"Storage-Single": "_Test ICD Storage Single Expense",
	"Storage-Double": "_Test ICD Storage Double Expense",
	"Removal": "_Test ICD Removal Expense",
}
RATES = {
	"Shore": 120000,
	"Levy": 45000,
	"Storage-Single": 8000,
	"Storage-Double": 16000,
	"Removal": 30000,
}


class TestPortExpenses(FrappeTestCase):
	def setUp(self):
		make_buying_price_list()
		for expense_type, item_code in ITEMS.items():
			make_expense_item(item_code, RATES[expense_type])

		set_expense_settings()
		self.manifest = make_manifest()
		self.manifest.submit()

	def tearDown(self):
		frappe.db.rollback()

	# criteria resolution

	def test_size_bucket_reads_the_leading_digit(self):
		for size, bucket in (("20", "20ft"), ("20ft", "20ft"), ("40HC", "40ft"), ("", None), (None, None)):
			self.assertEqual(get_size_bucket(size), bucket)

	def test_cargo_type_is_local_or_transit_only(self):
		self.assertEqual(get_cargo_type("IM"), "Local")
		self.assertEqual(get_cargo_type("TR"), "Transit")
		self.assertIsNone(get_cargo_type(""))

	def test_the_most_specific_criteria_row_wins_over_a_wildcard(self):
		settings_doc = frappe.get_cached_doc("ICD TZ Settings")

		key = {"size": "20ft", "cargo_type": "Local", "destination": "TZDAR", "port": PORT}
		winner = get_matching_criteria(settings_doc.expense_types, key)["Shore"]

		self.assertEqual(winner.size, "20ft")
		self.assertEqual(get_criteria_score(winner), 2)

	def test_a_criteria_row_of_another_port_never_appears(self):
		"""The TEAGTL Shore row must not reach a DP WORLD manifest"""

		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		self.assertNotIn("TEAGTL", {row["port"] for row in rows})

	def test_the_booked_flag_mapping_matches_the_select_options(self):
		options = frappe.get_meta("ICD TZ Expense Detail").get_field("expense_type").options
		declared = {option for option in options.split("\n") if option}

		self.assertEqual(declared, set(EXPENSE_TYPES))

	# aggregation

	def test_every_configured_charge_is_returned_even_with_no_container(self):
		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		levy = get_row(rows, "Levy")
		self.assertEqual(levy["container_count"], 0)
		self.assertEqual(levy["qty"], 0)
		self.assertEqual(levy["amount"], 0)

	def test_a_one_off_charge_counts_one_unit_per_container(self):
		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		shore = get_row(rows, "Shore", size="20ft")
		self.assertEqual(shore["container_count"], 1)
		self.assertEqual(shore["qty"], 1)
		self.assertEqual(shore["amount"], RATES["Shore"])

	def test_a_container_with_no_discharge_date_is_reported_not_counted(self):
		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		storage = get_row(rows, "Storage-Single")
		self.assertEqual(storage["qty"], 0)
		self.assertEqual(storage["container_count"], 0)

		view = get_expense_view(self.manifest.name, PRICE_LIST)
		self.assertEqual(view["summary"]["missing_discharge_date"], 2)

	def test_storage_counts_the_unbilled_days_of_each_band(self):
		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -9))
		update_port_storage_days(self.manifest.name)

		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		# 5 free, then single from day 6: a ten day stay bills 5 single days and no double
		self.assertEqual(get_row(rows, "Storage-Single")["qty"], 5)
		self.assertEqual(get_row(rows, "Storage-Double")["qty"], 0)

	def test_a_long_stay_reaches_the_double_band(self):
		"""A fifteen day stay crosses all three bands"""

		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -14))
		update_port_storage_days(self.manifest.name)

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		charges = [row.charge for row in container.storage_dates]
		self.assertEqual((charges.count("Free"), charges.count("Single"), charges.count("Double")), (5, 7, 3))

		rows = get_expense_rows(self.manifest.name, PRICE_LIST)
		self.assertEqual(get_row(rows, "Storage-Single")["qty"], 7)
		self.assertEqual(get_row(rows, "Storage-Double")["qty"], 3)

	def test_a_day_no_band_covers_is_not_recorded(self):
		"""A row is never revisited, so an unbanded day must not be written at all"""

		settings_doc = frappe.get_doc("ICD TZ Settings")
		settings_doc.port_storage_days = []
		for charge, from_day, to_day in (("Free", 1, 5), ("Single", 6, 12), ("Double", 13, 20)):
			settings_doc.append("port_storage_days", {"charge": charge, "from": from_day, "to": to_day})
		settings_doc.flags.ignore_mandatory = True
		settings_doc.save()
		frappe.clear_cache(doctype="ICD TZ Settings")

		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -29))
		update_port_storage_days(self.manifest.name)

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		self.assertEqual(len(container.storage_dates), 20)
		self.assertTrue(all(row.charge for row in container.storage_dates))

	def test_a_storage_charge_splits_into_one_row_per_day_count(self):
		"""Every displayed row has to read quantity x containers x rate"""

		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -8))
		set_discharge_date(self.manifest.name, BOX_40, add_days(nowdate(), -10))
		update_port_storage_days(self.manifest.name)

		view = get_expense_view(self.manifest.name, PRICE_LIST)
		single = [row for row in view["rows"] if row["expense_type"] == "Storage-Single"]

		# nine and eleven day stays, each less its five free days
		self.assertEqual(sorted(row["display_qty"] for row in single), [4, 6])
		for row in single:
			self.assertEqual(row["container_count"], 1)
			self.assertEqual(row["display_qty"] * row["container_count"], row["qty"])

		for row in view["rows"]:
			self.assertEqual(row["display_qty"] * row["container_count"], row["qty"])

	def test_a_split_row_drills_down_to_its_own_day_count_only(self):
		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -8))
		set_discharge_date(self.manifest.name, BOX_40, add_days(nowdate(), -10))
		update_port_storage_days(self.manifest.name)

		view = get_expense_view(self.manifest.name, PRICE_LIST)

		for row in view["rows"]:
			if not row["container_count"]:
				continue

			behind = get_expense_row_containers(self.manifest.name, row["criteria_row"], row["display_qty"])

			self.assertEqual(len(behind), row["container_count"])
			self.assertTrue(all(box["qty"] == row["display_qty"] for box in behind))

	def test_the_drill_down_returns_only_that_row_s_containers(self):
		"""Regression: it flattened every bucket, so each row listed the whole manifest"""

		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		for row in rows:
			behind = get_expense_row_containers(self.manifest.name, row["criteria_row"])

			self.assertEqual(len(behind), row["container_count"])

		sized = get_expense_row_containers(self.manifest.name, get_criteria_row("Shore", "20ft"))
		wildcard = get_expense_row_containers(self.manifest.name, get_criteria_row("Shore", ""))

		self.assertEqual([box["container_no"] for box in sized], [BOX_20])
		self.assertEqual([box["container_no"] for box in wildcard], [BOX_40])

	def test_a_one_off_charge_shows_one_per_container_not_the_container_count(self):
		"""The Qty / Days column is one for a one off charge, and days for storage"""

		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -9))
		update_port_storage_days(self.manifest.name)

		rows = get_expense_view(self.manifest.name, PRICE_LIST)["rows"]

		removal = get_row(rows, "Removal")
		self.assertEqual(removal["container_count"], 2)
		self.assertEqual(removal["display_qty"], 1)
		# what the page shows has to explain the amount it sits next to
		self.assertEqual(removal["display_qty"] * removal["container_count"], removal["qty"])

		self.assertEqual(get_row(rows, "Levy")["display_qty"], 0)

	def test_a_booked_container_drops_out_of_the_next_run(self):
		frappe.db.set_value("ICD Container", get_container(self.manifest.name, BOX_20), "is_shore_booked", 1)

		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		self.assertEqual(get_row(rows, "Shore", size="20ft")["container_count"], 0)

	def test_an_item_with_no_price_gets_a_zero_rate(self):
		frappe.db.delete("Item Price", {"price_list": PRICE_LIST, "item_code": ITEMS["Removal"]})

		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		self.assertEqual(get_row(rows, "Removal")["rate"], 0)
		self.assertEqual(get_row(rows, "Removal")["amount"], 0)

	def test_the_rate_follows_the_chosen_price_list(self):
		other = make_buying_price_list("_Test ICD Buying Price List 2")
		make_item_price(ITEMS["Shore"], other, 999000)

		rows = get_expense_rows(self.manifest.name, other)

		self.assertEqual(get_row(rows, "Shore", size="20ft")["rate"], 999000)

	# purchase order

	def test_one_order_line_is_created_per_container(self):
		name = create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), get_shore_rows())
		order = frappe.get_doc("Purchase Order", name)

		self.assertEqual(len(order.items), 2)
		self.assertEqual(sorted(item.container_no for item in order.items), sorted([BOX_20, BOX_40]))

	def test_a_container_binds_to_its_most_specific_criteria_row(self):
		"""The 20ft box takes the sized row, the 40ft box falls to the wildcard"""

		rows = get_expense_rows(self.manifest.name, PRICE_LIST)

		self.assertEqual(get_row(rows, "Shore", size="20ft")["container_count"], 1)
		self.assertEqual(get_row(rows, "Shore", size="")["container_count"], 1)

	def test_every_order_line_carries_its_own_dimensions(self):
		name = create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), get_shore_rows())
		order = frappe.get_doc("Purchase Order", name)

		for item in order.items:
			self.assertTrue(item.icd_container)
			self.assertTrue(item.icd_master_bl)
			self.assertEqual(item.manifest, self.manifest.name)

	def test_a_row_with_no_rate_cannot_be_ordered(self):
		frappe.db.delete("Item Price", {"price_list": PRICE_LIST, "item_code": ITEMS["Shore"]})

		self.assertRaises(
			frappe.ValidationError,
			create_purchase_order,
			self.manifest.name,
			PRICE_LIST,
			get_supplier(),
			[get_criteria_row("Shore", "")],
		)

	def test_a_row_with_no_container_cannot_be_ordered(self):
		self.assertRaises(
			frappe.ValidationError,
			create_purchase_order,
			self.manifest.name,
			PRICE_LIST,
			get_supplier(),
			[get_criteria_row("Levy", "")],
		)

	def test_an_empty_selection_cannot_be_ordered(self):
		self.assertRaises(
			frappe.ValidationError, create_purchase_order, self.manifest.name, PRICE_LIST, get_supplier(), []
		)

	def test_an_order_without_a_supplier_is_refused(self):
		self.assertRaises(
			frappe.ValidationError,
			create_purchase_order,
			self.manifest.name,
			PRICE_LIST,
			None,
			[get_criteria_row("Shore", "")],
		)

	# duplicate guard

	def test_the_page_is_told_which_draft_orders_block_it(self):
		"""Named as data so the page can link to them, not buried in prose"""

		name = create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), get_shore_rows())

		view = get_expense_view(self.manifest.name, PRICE_LIST)

		self.assertEqual(view["draft_purchase_orders"], [name])

	def test_no_message_the_page_shows_carries_markup(self):
		"""The page renders these as text, so a tag would be read literally"""

		messages = []
		for call, args in (
			(get_manifest_header, ("NO-SUCH-MANIFEST",)),
			(create_purchase_order, (self.manifest.name, PRICE_LIST, get_supplier(), [])),
		):
			try:
				call(*args)
			except frappe.ValidationError as error:
				messages.append(str(error))

		self.assertEqual(len(messages), 2)
		for message in messages:
			self.assertNotRegex(message, r"</?[a-zA-Z]+[^>]*>")

	def test_a_draft_order_on_the_same_manifest_blocks_another(self):
		create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), [get_criteria_row("Shore", "")])

		self.assertRaises(
			frappe.ValidationError,
			create_purchase_order,
			self.manifest.name,
			PRICE_LIST,
			get_supplier(),
			[get_criteria_row("Removal", "")],
		)

	def test_a_submitted_order_does_not_block(self):
		name = create_purchase_order(
			self.manifest.name, PRICE_LIST, get_supplier(), [get_criteria_row("Shore", "")]
		)
		frappe.get_doc("Purchase Order", name).submit()

		second = create_purchase_order(
			self.manifest.name, PRICE_LIST, get_supplier(), [get_criteria_row("Removal", "")]
		)

		self.assertTrue(second)

	# booking

	def test_submit_ticks_only_the_charge_it_carried(self):
		name = create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), get_shore_rows())
		frappe.get_doc("Purchase Order", name).submit()

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		self.assertEqual(container.is_shore_booked, 1)
		self.assertEqual(container.is_removal_booked, 0)
		self.assertEqual(container.purchase_order, name)

	def test_cancel_releases_what_the_order_claimed(self):
		name = create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), get_shore_rows())
		order = frappe.get_doc("Purchase Order", name)
		order.submit()
		order.cancel()

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		self.assertEqual(container.is_shore_booked, 0)
		self.assertFalse(container.purchase_order)

	def test_cancel_releases_every_charge_the_order_carried(self):
		"""Regression: clearing the stamp per charge released only the first one"""

		rows = [*get_shore_rows(), get_criteria_row("Removal", "")]
		name = create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), rows)
		order = frappe.get_doc("Purchase Order", name)
		order.submit()
		order.cancel()

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		self.assertEqual(container.is_shore_booked, 0)
		self.assertEqual(container.is_removal_booked, 0)
		self.assertFalse(container.purchase_order)

	def test_storage_days_are_stamped_and_the_rest_stay_free(self):
		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -9))
		update_port_storage_days(self.manifest.name)

		name = create_purchase_order(
			self.manifest.name, PRICE_LIST, get_supplier(), [get_criteria_row("Storage-Single", "")]
		)
		frappe.get_doc("Purchase Order", name).submit()

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		stamped = [row for row in container.storage_dates if row.purchase_order == name]
		unbilled = [row for row in container.storage_dates if not row.purchase_order]

		self.assertEqual(len(stamped), 5)
		self.assertEqual(len(unbilled), 5)
		self.assertTrue(all(row.charge == "Single" for row in stamped))

	def test_an_order_for_an_already_booked_charge_cannot_be_submitted(self):
		"""Two people can build a draft at the same time, submit is what stops the double bill"""

		first = create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), get_shore_rows())
		second = frappe.copy_doc(frappe.get_doc("Purchase Order", first))
		second.insert()

		frappe.get_doc("Purchase Order", first).submit()

		self.assertRaises(frappe.ValidationError, second.submit)

	def test_the_booked_count_reads_the_order_stamp(self):
		"""A container no criteria matches is not a booked container"""

		view = get_expense_view(self.manifest.name, PRICE_LIST)

		self.assertEqual(view["summary"]["booked_containers"], 0)
		self.assertEqual(view["summary"]["total_containers"], 2)

	def test_the_invoice_stamps_the_storage_days_it_bills(self):
		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -9))
		update_port_storage_days(self.manifest.name)

		name = create_purchase_order(
			self.manifest.name, PRICE_LIST, get_supplier(), [get_criteria_row("Storage-Single", "")]
		)
		order = frappe.get_doc("Purchase Order", name)
		order.submit()

		line = order.items[0]
		invoice = frappe.new_doc("Purchase Invoice")
		invoice.update({"supplier": order.supplier, "company": order.company, "posting_date": nowdate()})
		invoice.append(
			"items",
			{
				"item_code": line.item_code,
				"qty": line.qty,
				"rate": line.rate,
				"expense_account": get_expense_account(order.company),
				"purchase_order": name,
				"po_detail": line.name,
				"container_no": line.container_no,
				"icd_container": line.icd_container,
				"container_child_refs": line.container_child_refs,
			},
		)
		invoice.insert()
		invoice.submit()

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		invoiced = [row for row in container.storage_dates if row.purchase_invoice == invoice.name]
		self.assertEqual(len(invoiced), 5)

		invoice.reload()
		invoice.cancel()

		container.reload()
		self.assertFalse([row for row in container.storage_dates if row.purchase_invoice])

	def test_the_invoice_stamps_only_the_containers_on_its_own_lines(self):
		"""A part invoice must not stamp the whole order"""

		name = create_purchase_order(self.manifest.name, PRICE_LIST, get_supplier(), get_shore_rows())
		order = frappe.get_doc("Purchase Order", name)
		order.submit()

		billed = order.items[0]
		invoice = frappe.new_doc("Purchase Invoice")
		invoice.update({"supplier": order.supplier, "company": order.company, "posting_date": nowdate()})
		invoice.append(
			"items",
			{
				"item_code": billed.item_code,
				"qty": billed.qty,
				"rate": billed.rate,
				"expense_account": get_expense_account(order.company),
				"purchase_order": name,
				"po_detail": billed.name,
				"container_no": billed.container_no,
				"icd_container": billed.icd_container,
			},
		)
		invoice.insert()
		invoice.submit()

		stamped = frappe.get_all(
			"ICD Container",
			filters={"manifest": self.manifest.name, "purchase_invoice": invoice.name},
			pluck="container_no",
		)

		self.assertEqual(stamped, [billed.container_no])

	def test_a_plain_purchase_order_is_untouched_by_the_hooks(self):
		order = frappe.new_doc("Purchase Order")
		order.update({"supplier": get_supplier(), "company": get_company(), "schedule_date": nowdate()})
		order.append("items", {"item_code": ITEMS["Shore"], "qty": 1, "rate": 100})

		self.assertEqual(get_expense_coverage(order), ({}, set()))

	# storage day rows

	def test_storage_days_stop_at_the_icd_receipt_date(self):
		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -9))
		make_received_container(self.manifest.name, BOX_20, add_days(nowdate(), -5))

		update_port_storage_days(self.manifest.name)

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		self.assertEqual(len(container.storage_dates), 5)

	def test_only_a_container_with_a_discharge_date_gets_day_rows(self):
		"""The stay is counted from Ship D/C Date, so without one there is nothing to count"""

		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -3))
		update_port_storage_days(self.manifest.name)

		dated = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		undated = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_40))

		self.assertEqual(len(dated.storage_dates), 4)
		self.assertFalse(undated.ship_dc_date)
		self.assertEqual(len(undated.storage_dates), 0)

	def test_counting_a_stay_with_no_discharge_date_is_refused(self):
		"""getdate(None) reads as today, which would bill a day that never happened"""

		container = get_container(self.manifest.name, BOX_40)

		self.assertRaises(frappe.ValidationError, append_storage_days, container, {}, None, nowdate())

	def test_the_page_refuses_to_open_until_the_day_ranges_are_set(self):
		"""A seeded band carries only the charge, and storage cannot be priced from that"""

		settings_doc = frappe.get_doc("ICD TZ Settings")
		for row in settings_doc.port_storage_days:
			row.update({"from": 0, "to": 0})
		settings_doc.flags.ignore_mandatory = True
		settings_doc.flags.ignore_validate = True
		settings_doc.save()
		frappe.clear_cache(doctype="ICD TZ Settings")

		self.assertRaises(frappe.ValidationError, get_expense_view, self.manifest.name, PRICE_LIST)

	def test_free_days_are_counted_but_never_billed(self):
		"""The terminal grants free days; they belong on the container, not on an order"""

		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -9))
		update_port_storage_days(self.manifest.name)

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		charges = [row.charge for row in container.storage_dates]

		self.assertEqual(charges.count("Free"), 5)
		self.assertEqual(charges.count("Single"), 5)

		view = get_expense_view(self.manifest.name, PRICE_LIST)
		self.assertNotIn("Free", {row["expense_type"] for row in view["rows"]})
		self.assertEqual(get_row(view["rows"], "Storage-Single")["qty"], 5)

	def test_a_free_day_never_reaches_a_purchase_order(self):
		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -9))
		update_port_storage_days(self.manifest.name)

		name = create_purchase_order(
			self.manifest.name, PRICE_LIST, get_supplier(), [get_criteria_row("Storage-Single", "")]
		)
		order = frappe.get_doc("Purchase Order", name)
		billed = {ref for item in order.items for ref in (item.container_child_refs or "").split(",") if ref}

		free_rows = {
			row.name
			for row in frappe.get_doc(
				"ICD Container", get_container(self.manifest.name, BOX_20)
			).storage_dates
			if row.charge == "Free"
		}

		self.assertEqual(len(free_rows), 5)
		self.assertFalse(billed & free_rows)

	def test_a_container_starts_pending_with_no_receipt_date(self):
		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))

		self.assertEqual(container.status, PENDING_STATUS)
		self.assertFalse(container.received_date)

	def test_receiving_a_container_records_the_status_and_the_date(self):
		reception = frappe.new_doc("Container Reception")
		reception.update(
			{
				"manifest": self.manifest.name,
				"container_no": BOX_20,
				"posting_date": add_days(nowdate(), -2),
			}
		)
		reception.set_icd_container_status(RECEIVED_STATUS, reception.posting_date)

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		self.assertEqual(container.status, RECEIVED_STATUS)
		# the posting date, not the reception's own received_date, which falls back
		# to the ship discharge date on a quick turnaround
		self.assertEqual(getdate(container.received_date), getdate(add_days(nowdate(), -2)))

		# cancelling the receipt puts the box back at the port
		reception.set_icd_container_status(PENDING_STATUS)

		container.reload()
		self.assertEqual(container.status, PENDING_STATUS)
		self.assertFalse(container.received_date)

	def test_a_received_container_stops_counting_days(self):
		"""Its stay at the port ended, so the job must leave it alone"""

		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -9))
		update_port_storage_days(self.manifest.name)

		container_id = get_container(self.manifest.name, BOX_20)
		before = len(frappe.get_doc("ICD Container", container_id).storage_dates)
		self.assertTrue(before)

		frappe.db.set_value("ICD Container", container_id, "status", RECEIVED_STATUS)
		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -20))
		update_port_storage_days(self.manifest.name)

		self.assertEqual(len(frappe.get_doc("ICD Container", container_id).storage_dates), before)
		self.assertNotIn(
			container_id, [row.name for row in get_containers_for_storage_days(self.manifest.name)]
		)

	def test_a_rerun_adds_no_duplicate_day(self):
		set_discharge_date(self.manifest.name, BOX_20, add_days(nowdate(), -3))
		update_port_storage_days(self.manifest.name)
		update_port_storage_days(self.manifest.name)

		container = frappe.get_doc("ICD Container", get_container(self.manifest.name, BOX_20))
		dates = [row.date for row in container.storage_dates]

		self.assertEqual(len(dates), len(set(dates)))

	def test_a_day_is_banded_from_the_discharge_date(self):
		bands = get_port_storage_bands(frappe.get_cached_doc("ICD TZ Settings"))
		start = getdate_days_ago(0)

		self.assertEqual(get_charge_of_day(start, start, bands), "Free")
		self.assertEqual(get_charge_of_day(add_days(start, 5), start, bands), "Single")
		self.assertEqual(get_charge_of_day(add_days(start, 12), start, bands), "Double")


def getdate_days_ago(days):
	from frappe.utils import getdate

	return getdate(add_days(nowdate(), -days))


def get_row(rows, expense_type, size=None):
	for row in rows:
		if row["expense_type"] == expense_type and (size is None or row["size"] == size):
			return row

	frappe.throw(f"No expense row for {expense_type}")


def get_shore_rows():
	return [get_criteria_row("Shore", "20ft"), get_criteria_row("Shore", "")]


def get_criteria_row(expense_type, size):
	settings_doc = frappe.get_cached_doc("ICD TZ Settings")
	for row in settings_doc.expense_types:
		if row.expense_type == expense_type and (row.size or "") == size:
			return row.name

	frappe.throw(f"No criteria row for {expense_type} {size}")


def get_container(manifest, container_no):
	return frappe.db.get_value("ICD Container", {"manifest": manifest, "container_no": container_no})


def set_discharge_date(manifest, container_no, discharge_date):
	frappe.db.set_value(
		"ICD Container", get_container(manifest, container_no), "ship_dc_date", discharge_date
	)


def set_expense_settings():
	settings_doc = frappe.get_doc("ICD TZ Settings")
	settings_doc.default_buying_price_list = PRICE_LIST
	settings_doc.expense_types = []
	settings_doc.port_storage_days = []

	criteria = [
		("Shore", "20ft", "Local", ""),
		("Shore", "", "", ""),
		("Shore", "20ft", "", "TEAGTL"),
		("Levy", "", "Transit", ""),
		("Storage-Single", "", "", ""),
		("Storage-Double", "", "", ""),
		("Removal", "", "", ""),
	]
	for expense_type, size, cargo_type, port in criteria:
		settings_doc.append(
			"expense_types",
			{
				"expense_type": expense_type,
				"expense_item": ITEMS[expense_type],
				"size": size,
				"cargo_type": cargo_type,
				"port": port,
			},
		)

	for charge, from_day, to_day in BANDS:
		settings_doc.append("port_storage_days", {"charge": charge, "from": from_day, "to": to_day})

	settings_doc.flags.ignore_mandatory = True
	settings_doc.save()
	frappe.clear_cache(doctype="ICD TZ Settings")


def make_buying_price_list(name=PRICE_LIST):
	if frappe.db.exists("Price List", name):
		return name

	frappe.get_doc(
		{
			"doctype": "Price List",
			"price_list_name": name,
			"buying": 1,
			"currency": frappe.db.get_value("Company", get_company(), "default_currency"),
			"enabled": 1,
		}
	).insert()

	return name


def make_expense_item(item_code, rate):
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert()

	make_item_price(item_code, PRICE_LIST, rate)


def make_item_price(item_code, price_list, rate):
	existing = frappe.db.get_value("Item Price", {"item_code": item_code, "price_list": price_list})
	if existing:
		frappe.db.set_value("Item Price", existing, "price_list_rate", rate)
		return

	frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": price_list,
			"buying": 1,
			"price_list_rate": rate,
		}
	).insert()


def make_received_container(manifest, container_no, received_date):
	"""Operational container, which is what ends the port storage count"""

	frappe.get_doc(
		{
			"doctype": "Container",
			"container_no": container_no,
			"manifest": manifest,
			"m_bl_no": M_BL_NO,
			"received_date": received_date,
			"posting_date": received_date,
			"size": "20",
		}
	).db_insert()


def make_manifest():
	manifest = frappe.new_doc("Manifest")
	manifest.update(
		{
			"manifest": "/private/files/_test_icd_expense_manifest.xlsx",
			"company": get_company(),
			"mrn": "_TEST-MRN-EXP",
			"vessel_name": "_Test Vessel",
			"voyage_no": "V-900",
			"arrival_date": nowdate(),
			"port": PORT,
		}
	)
	manifest.append(
		"master_bl",
		{
			"m_bl_no": M_BL_NO,
			"cargo_classification": "IM",
			"place_of_destination": "TZDAR",
			"place_of_delivery": "WITZDL019",
			"port_of_loading": "CNSHA",
			"number_of_containers": "2",
			"cargo_description": "_Test cargo",
			"consignee_name": "_Test ICD Expense Consignee",
			"consignee_tin": "123456789",
			"shipping_agent_code": "MAEU",
			"shipping_agent_name": "_Test Shipping Agent",
		},
	)

	for container_no, size in ((BOX_20, "20"), (BOX_40, "40")):
		manifest.append(
			"containers",
			{
				"m_bl_no": M_BL_NO,
				"container_no": container_no,
				"type_of_container": "C",
				"container_size": size,
				"freight_indicator": "FCL",
				"no_of_packages": "10",
				"package_unit": "PK",
				"weight": "12000",
				"weight_unit": "KG",
			},
		)

	manifest.insert()
	return manifest


def get_expense_account(company):
	return frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name")


def get_supplier():
	supplier = frappe.db.get_value("Supplier", {}, "name")
	if supplier:
		return supplier

	return frappe.get_doc({"doctype": "Supplier", "supplier_name": "_Test ICD Port"}).insert().name


def get_company():
	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		frappe.throw("No Company on the test site")

	return company
