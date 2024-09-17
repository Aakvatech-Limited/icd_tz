# Copyright (c) 2024, Nathan Kagoro and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import nowdate
from frappe.model.document import Document

class ContainerInspection(Document):
    @frappe.whitelist()
    def get_strip_services(self):
        if isinstance(self, str):
            self = frappe.parse_json(self)
        
        if not self.get("in_yard_container_booking"):
            return
        
        has_stripping_charges = frappe.db.get_value(
            "In Yard Container Booking",
            self.get("in_yard_container_booking"),
            "has_stripping_charges"
        )
        if has_stripping_charges == "Yes":
            service_names = []
            for row in self.get("services"):
                service_names.append(row.get("service"))

            in_yard_booking_item = frappe.db.get_single_value("ICD TZ Settings", "in_yard_booking_item")
            
            if in_yard_booking_item not in service_names:
                return in_yard_booking_item
    
    @frappe.whitelist()
    def get_storage_services(self):
        if isinstance(self, str):
            self = frappe.parse_json(self)
        
        if not self.get("in_yard_container_booking"):
            return

        yard_doc = frappe.get_doc("In Yard Container Booking", self.in_yard_container_booking)
        
        has_storage_charges = frappe.db.get_value(
            "Container", yard_doc.container_no, "days_to_be_billed"
        )
        if has_storage_charges > 0:
            service_names = []
            for row in self.get("services"):
                service_names.append(row.get("service"))
            
            storage_item = frappe.db.get_single_value("ICD TZ Settings", "container_storage_item")
            
            if storage_item not in service_names:
                return storage_item

