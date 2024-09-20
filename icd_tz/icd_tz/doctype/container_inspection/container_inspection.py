# Copyright (c) 2024, Nathan Kagoro and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import nowdate
from frappe.model.document import Document
from icd_tz.icd_tz.api.utils import validate_cf_agent

class ContainerInspection(Document):
    def after_insert(self):
        self.update_in_yard_booking()
    
    def before_save(self):
        if not self.company:
            self.company = frappe.defaults.get_user_default("Company")
    
    def validate(self):
        validate_cf_agent(self)
    
    def update_in_yard_booking(self):
        if not self.in_yard_booking:
            return
        
        frappe.db.set_value(
            "In Yard Container Booking",
            self.in_yard_booking,
            "container_inspection",
            self.name
        )