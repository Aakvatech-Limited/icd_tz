import json

import frappe
from frappe import _
from frappe.model.document import Document


class TANeSWDeclaration(Document):
	def sync_from_tanesw(self):
		from tanesw_integration.api import booking_detail

		try:
			res = booking_detail(self.tansad_no)
			if res and isinstance(res, dict):
				bkng = res.get("jntInscBkngInfo") or {}
				bl = res.get("blInfo") or {}
				tansad_info = res.get("tansadInfo") or {}

				# 1. Declaration & Selectivity Details
				if tansad_info:
					self.declaration_date = tansad_info.get("tansadDt") or self.declaration_date
					self.declaration_mode = tansad_info.get("decMode") or self.declaration_mode
					self.customs_office_code = tansad_info.get("cstmOfceCd") or self.customs_office_code
					self.consignee_tin = tansad_info.get("tin") or self.consignee_tin
					self.consignee_name = tansad_info.get("coNm") or self.consignee_name
					self.clearing_agent_name = (
						tansad_info.get("dcltNm") or bkng.get("coNm") or self.clearing_agent_name
					)
					self.warehouse_code = (
						tansad_info.get("godsLoctReffCn") or bkng.get("godsLoctWrhsCd") or self.warehouse_code
					)
					self.crn = tansad_info.get("crn") or self.crn
					self.master_bl_no = tansad_info.get("blNo") or self.master_bl_no
					sltv = tansad_info.get("sltvRsltCd")
					if sltv == "R":
						self.selectivity_channel = "Red Channel (Physical Inspection)"
					elif sltv == "Y":
						self.selectivity_channel = "Yellow Channel (Documentary Check)"
					elif sltv == "G":
						self.selectivity_channel = "Green Channel (Direct Release)"
					elif sltv:
						self.selectivity_channel = sltv

				# 2. Bill of Lading & Vessel Details
				if bl:
					self.mrn = bl.get("mrn") or self.mrn
					self.crn = bl.get("crn") or self.crn
					self.master_bl_no = bl.get("mblNo") or self.master_bl_no
					self.house_bl_no = bl.get("hblNo") or self.house_bl_no
					self.package_count = bl.get("blPckgNo") or self.package_count
					self.package_unit = bl.get("pckgUtCd") or self.package_unit
					self.gross_weight = bl.get("blGwght") or self.gross_weight
					self.net_weight = bl.get("blNwght") or self.net_weight
					self.cargo_classification = bl.get("cagClsfCd") or self.cargo_classification
					self.vessel_name = bl.get("vsslNm") or self.vessel_name
					self.voyage_no = bl.get("vygNo") or self.voyage_no
					self.discharge_port = bl.get("dscgPortCd") or self.discharge_port
					self.discharge_date = bl.get("dscgDt") or self.discharge_date
					self.goods_description = bl.get("godsDesc") or self.goods_description

				# 3. Booking Details
				if bkng:
					self.booking_date = bkng.get("bkngRqstDt")
					self.booking_status = "Approved" if bkng.get("prcsStatCd") == "B" else "Pending"
					self.warehouse_code = bkng.get("godsLoctWrhsCd") or self.warehouse_code

				# 4. Container / Vehicle Lines
				cntrs = res.get("cntrInfo") or res.get("jntInscCntrInfo") or []
				self.set("containers", [])
				for c in cntrs:
					self.append(
						"containers",
						{
							"container_no": c.get("CNTR_NO") or c.get("cntrNo") or c.get("cntrId") or "-",
							"container_size": c.get("CNTR_SIZE_CD")
							or c.get("cntrSzCd")
							or c.get("LOAD_TP_CD")
							or "",
							"seal_no": c.get("SEAL_NO_1") or c.get("sealNo1") or "",
							"weight": c.get("CNTR_WGHT") or c.get("cntrGwght") or 0,
							"package_quantity": c.get("CNTR_PCKG_NO") or 1,
							"package_type": c.get("PCKG_UT_CD") or "",
							"status": "In Inspection" if bkng.get("prcsStatCd") == "B" else "Loaded",
						},
					)

				self.raw_payload_snapshot = json.dumps(res, indent=2)
				self.last_sync_status = "Success"
				self.last_sync_time = frappe.utils.now()
				self.save()
				return {"status": "ok", "message": _("Synchronized all details successfully from TANeSW")}
		except Exception as e:
			self.last_sync_status = f"Failed: {str(e)[:100]}"
			self.last_sync_time = frappe.utils.now()
			self.save()
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- keep the failed-sync status: the throw rolls back
			frappe.throw(f"Sync failed: {e!s}")
