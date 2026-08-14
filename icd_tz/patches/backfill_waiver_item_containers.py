import frappe


def execute():
	"""Waiver items used to reference so_detail, which Update Items invalidates. Move to containers."""
	frappe.db.sql(
		"""
		update `tabWaiver Request` waiver
		join `tabSales Order` sales_order on sales_order.name = waiver.sales_order
		set waiver.currency = sales_order.currency
		where ifnull(waiver.currency, '') = ''
		"""
	)

	frappe.db.sql(
		"""
		update `tabWaiver Request Item` waiver_item
		join `tabWaiver Request` waiver on waiver.name = waiver_item.parent
		set waiver_item.currency = waiver.currency
		where ifnull(waiver_item.currency, '') = ''
		"""
	)

	if not frappe.db.has_column("Waiver Request Item", "so_detail"):
		return

	frappe.db.sql(
		"""
		update `tabWaiver Request Item` waiver_item
		join `tabSales Order Item` order_item on order_item.name = waiver_item.so_detail
		set waiver_item.container_no = order_item.container_no,
			waiver_item.container_id = order_item.container_id
		where ifnull(waiver_item.so_detail, '') != ''
			and ifnull(waiver_item.container_no, '') = ''
		"""
	)
