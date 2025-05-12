# Copyright (c) 2025, elius mgani and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import DocType


cn = DocType('Container')
ycb = DocType('In Yard Container Booking')

def execute(filters=None):
	columns = get_columns()
	data =  get_data(filters)
	return columns, data


def get_data(filters):
	query = (
        frappe.qb.from_(ycb)
        .inner_join(cn)
        .on(cn.name == ycb.container_id)
        .select(
            ycb.m_bl_no,
			ycb.container_no,
			ycb.container_size,
            ycb.c_and_f_company,
			ycb.consignee,
            ycb.inspection_location.as_('location'),
			ycb.inspection_date.as_('booking_date'),
			cn.seal_no_1.as_('seal'),
			ycb.cargo_description
        )
		.where(
			(ycb.docstatus == 1)
			& (ycb.inspection_date >= filters.get('from_date'))
			& (ycb.inspection_date <= filters.get('to_date'))
		)
    )
	
	if filters.get('m_bl_no'):
		query = query.where(ycb.m_bl_no == filters.get('m_bl_no'))
	
	records = query.run(as_dict=True)
	
	return records


def get_columns():
    return [
        {
            "fieldname": "container_no",
            "label": _("Container No."),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "m_bl_no",
            "label": _("B/L No."),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "container_size",
            "label": _("Size (FT)"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "seal",
            "label": _("Seal"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "c_and_f_company",
            "label": _("C & F Company"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "consignee",
            "label": _("Consignee"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "location",
            "label": _("Location"),
            "fieldtype": "Data",
            "width": 150
        },
        {
            "fieldname": "booking_date",
            "label": _("Date"),
            "fieldtype": "Datetime",
            "width": 150
        },{
            "fieldname": "cargo_description",
            "label": _("Item Description"),
            "fieldtype": "Small Text"
        },
    ]
    