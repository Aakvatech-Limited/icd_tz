# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

"""
EDI COREOR (Container Release Order) Message Generator
Implementation Guide based on UN/EDIFACT D00B Version

COREOR is used to communicate container release orders from the terminal
to the shipping line or freight forwarder.

Segment Structure:
- UNB: Interchange Header
- UNH: Message Header
- BGM: Beginning of Message
- DTM: Date/Time/Period
- RFF: Reference
- TDT: Transport Information
- LOC: Location
- NAD: Name and Address
- EQD: Equipment Details
- CNT: Control Total
- UNT: Message Footer
- UNZ: Interchange Footer
"""

import frappe
from frappe.utils import now_datetime, getdate, format_datetime
from datetime import datetime
import random
import string


class COREORGenerator:
    """
    Generate EDI COREOR messages based on Container Reception or Container Movement Order data.
    
    COREOR = Container Release Order Message
    Based on UN/EDIFACT D00B Version (SMDG20 subset)
    """
    
    # Message function codes
    MESSAGE_FUNCTIONS = {
        "cancellation": "1",
        "replace": "5",
        "original": "9"
    }
    
    # Equipment status codes
    EQUIPMENT_STATUS = {
        "export": "2",
        "import": "3"
    }
    
    # Full/Empty indicator
    FULL_EMPTY_INDICATOR = {
        "empty": "4",
        "full": "5"
    }
    
    def __init__(self, container_reception=None, container_movement_order=None):
        """
        Initialize the generator with either a Container Reception or Container Movement Order.
        
        Args:
            container_reception: Name of Container Reception document
            container_movement_order: Name of Container Movement Order document
        """
        self.container_reception = None
        self.container_movement_order = None
        self.manifest = None
        
        if container_reception:
            self.container_reception = frappe.get_doc("Container Reception", container_reception)
            if self.container_reception.movement_order:
                self.container_movement_order = frappe.get_doc(
                    "Container Movement Order", 
                    self.container_reception.movement_order
                )
            if self.container_reception.manifest:
                self.manifest = frappe.get_doc("Manifest", self.container_reception.manifest)
        elif container_movement_order:
            self.container_movement_order = frappe.get_doc(
                "Container Movement Order", 
                container_movement_order
            )
            if self.container_movement_order.manifest:
                self.manifest = frappe.get_doc("Manifest", self.container_movement_order.manifest)
        
        self.segments = []
        self.segment_count = 0
    
    def _generate_interchange_id(self):
        """Generate a unique interchange ID (max 14 characters alphanumeric)"""
        timestamp = now_datetime().strftime("%y%m%d%H%M")
        random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"{timestamp}{random_suffix}"
    
    def _format_date(self, date_value, format_code="102"):
        """
        Format date according to EDIFACT date format codes.
        
        Format codes:
        - 102: CCYYMMDD
        - 203: CCYYMMDDHHMM
        """
        if not date_value:
            return ""
        
        if isinstance(date_value, str):
            date_value = getdate(date_value)
        
        if format_code == "102":
            return date_value.strftime("%Y%m%d")
        elif format_code == "203":
            # For document datetime, include time
            dt = now_datetime()
            return dt.strftime("%Y%m%d%H%M")
        
        return date_value.strftime("%Y%m%d")
    
    def _get_container_type_iso_code(self, size):
        """
        Map container size to ISO container type code.
        
        Common ISO codes:
        - 22G1: 20ft General Purpose
        - 42G1: 40ft General Purpose
        - 45G1: 40ft High Cube
        """
        size_mapping = {
            "20": "22G1",
            "40": "42G1",
            "40HC": "45G1",
            "45": "45G1"
        }
        
        if size:
            # Clean up size string
            size_clean = str(size).upper().replace("FT", "").replace("'", "").strip()
            return size_mapping.get(size_clean, "22G1")
        
        return "22G1"
    
    def _get_sender_id(self):
        """Get the sender ID from EDI Settings"""
        try:
            edi_settings = frappe.get_single("EDI Settings")
            if edi_settings.sender_id:
                return edi_settings.sender_id
        except Exception:
            pass
        return "ICD"
    
    def _get_receiver_id(self):
        """Get the receiver ID from EDI Settings"""
        try:
            edi_settings = frappe.get_single("EDI Settings")
            if edi_settings.receiver_id:
                return edi_settings.receiver_id
        except Exception:
            pass
        return "TZDARDSEL"
    
    def _add_segment(self, segment):
        """Add a segment to the message"""
        self.segments.append(segment)
        self.segment_count += 1
    
    def _build_unb_segment(self, interchange_id):
        """
        Build UNB (Interchange Header) segment.
        
        Format: UNB+UNOA:2+senderID+receiverID+interchangeDate:interchangeTime+interchangeID'
        """
        dt = now_datetime()
        interchange_date = dt.strftime("%y%m%d")
        interchange_time = dt.strftime("%H%M")
        sender_id = self._get_sender_id()
        receiver_id = self._get_receiver_id()
        
        return f"UNB+UNOA:2+{sender_id}+{receiver_id}+{interchange_date}:{interchange_time}+{interchange_id}'"
    
    def _build_unh_segment(self, message_id):
        """
        Build UNH (Message Header) segment.
        
        Format: UNH+messageID+COREOR:D:00B:UN:SMDG20'
        """
        return f"UNH+{message_id}+COREOR:D:00B:UN:SMDG20'"
    
    def _build_bgm_segment(self, message_number, message_function="9"):
        """
        Build BGM (Beginning of Message) segment.
        
        Format: BGM+129+messageNumber+messageFunction'
        
        Message function codes:
        - 1: Cancellation
        - 5: Replace
        - 9: Original
        """
        return f"BGM+129+{message_number}+{message_function}'"
    
    def _build_dtm_segments(self):
        """
        Build DTM (Date/Time/Period) segments.
        
        Returns list of DTM segments:
        - DTM+137: Document date/time (format 203: CCYYMMDDHHMM)
        - DTM+36: Expiry date (format 102: CCYYMMDD) - optional
        - DTM+7: Effective date/time (format 102: CCYYMMDD)
        """
        segments = []
        
        # DTM+137: Document date/time
        doc_datetime = self._format_date(None, "203")
        segments.append(f"DTM+137:{doc_datetime}:203'")
        
        # DTM+7: Effective date (DO effective date - received date or movement date)
        effective_date = None
        if self.container_reception:
            effective_date = self.container_reception.received_date
        elif self.container_movement_order:
            effective_date = self.container_movement_order.movement_date
        
        if effective_date:
            segments.append(f"DTM+7:{self._format_date(effective_date, '102')}:102'")
        
        return segments
    
    def _build_rff_segments(self):
        """
        Build RFF (Reference) segments.
        
        Returns list of RFF segments:
        - RFF+RE: Delivery Order Number
        - RFF+BM: Bill of Lading Number
        """
        segments = []
        
        # RFF+RE: Delivery Order Number (use document name)
        doc_name = ""
        if self.container_reception:
            doc_name = self.container_reception.name
        elif self.container_movement_order:
            doc_name = self.container_movement_order.name
        
        segments.append(f"RFF+RE:{doc_name}'")
        
        # RFF+BM: Bill of Lading Number
        m_bl_no = ""
        if self.container_reception:
            m_bl_no = self.container_reception.m_bl_no or ""
        elif self.container_movement_order:
            m_bl_no = self.container_movement_order.m_bl_no or ""
        
        if m_bl_no:
            segments.append(f"RFF+BM:{m_bl_no}'")
        
        return segments
    
    def _build_tdt_segment(self):
        """
        Build TDT (Transport Information) segment.
        
        Format: TDT+20+voyageNo+1++carrierID:172:20+++vesselCallsign:146::vesselName'
        
        Transport stage qualifier: 20 = Main-carriage transport
        """
        voyage_no = ""
        vessel_name = ""
        call_sign = ""
        carrier_id = ""
        
        if self.manifest:
            voyage_no = self.manifest.voyage_no or ""
            vessel_name = self.manifest.vessel_name or ""
            call_sign = self.manifest.call_sign or ""
        
        if self.container_movement_order:
            voyage_no = voyage_no or self.container_movement_order.voyage_no or ""
        
        # Build the TDT segment
        # Format: TDT+20+voyageNo+1++carrierID:172:20+++callSign:103::vesselName'
        tdt = f"TDT+20+{voyage_no}+1++{carrier_id}:172:20+++{call_sign}:103::{vessel_name}'"
        
        return tdt
    
    def _build_loc_segments(self):
        """
        Build LOC (Location) segments.
        
        Returns list of LOC segments:
        - LOC+7: Place of delivery (UNLOCODE)
        - LOC+8: Port of final destination (UNLOCODE)
        - LOC+76: Port of loading (UNLOCODE)
        """
        segments = []
        
        # Default to Dar es Salaam
        port_code = "TZDAR"
        
        # LOC+7: Place of delivery
        segments.append(f"LOC+7+{port_code}:139:6'")
        
        # LOC+8: Port of final destination
        destination_code = port_code
        if self.container_reception and self.container_reception.abbr_for_destination:
            destination_code = self.container_reception.abbr_for_destination
        segments.append(f"LOC+8+{destination_code}:139:6'")
        
        # LOC+76: Port of loading
        loading_port = port_code
        segments.append(f"LOC+76+{loading_port}:139:6'")
        
        return segments
    
    def _build_dtm_arrival_segment(self):
        """
        Build DTM segment for estimated arrival date.
        
        Format: DTM+132:estimatedArrivalDate:102'
        """
        arrival_date = None
        
        if self.container_reception:
            arrival_date = self.container_reception.ship_dc_date
        elif self.container_movement_order:
            arrival_date = self.container_movement_order.ship_dc_date
        elif self.manifest:
            arrival_date = self.manifest.arrival_date
        
        if arrival_date:
            return f"DTM+132:{self._format_date(arrival_date, '102')}:102'"
        
        return None
    
    def _build_nad_segments(self):
        """
        Build NAD (Name and Address) segments.
        
        Returns list of NAD segments:
        - NAD+MS: Message Sender
        - NAD+CF: Container operator/lessee/Consignee
        - NAD+FW: Forwarder Identifier (TIN)
        """
        segments = []
        
        sender_id = self._get_sender_id()
        
        # NAD+MS: Message Sender
        segments.append(f"NAD+MS+{sender_id}:172:20'")
        
        # NAD+CF: Consignee (placeholder)
        segments.append("NAD+CF+:ZZZ:ZZZ'")
        
        # NAD+FW: Forwarder (TIN Number format: 999-999-999)
        transporter = ""
        if self.container_reception and self.container_reception.transporter:
            transporter_doc = frappe.get_doc("Transporter", self.container_reception.transporter)
            transporter = getattr(transporter_doc, "tin_number", "") or ""
        elif self.container_movement_order and self.container_movement_order.transporter:
            transporter_doc = frappe.get_doc("Transporter", self.container_movement_order.transporter)
            transporter = getattr(transporter_doc, "tin_number", "") or ""
        
        if transporter:
            segments.append(f"NAD+FW+{transporter}:160:ZZZ'")
        
        return segments
    
    def _build_eqd_segment(self):
        """
        Build EQD (Equipment Details) segment.
        
        Format: EQD+CN+containerNumber+containerTypeISOcode:102:5++equipmentStatus+full/emptyIndicator'
        
        Equipment qualifiers:
        - CN: Container
        
        Equipment status:
        - 2: Export
        - 3: Import
        
        Full/Empty indicator:
        - 4: Empty
        - 5: Full
        """
        container_no = ""
        container_type = "22G1"
        equipment_status = "3"  # Import
        full_empty = "5"  # Full
        
        if self.container_reception:
            container_no = self.container_reception.container_no or ""
            container_type = self._get_container_type_iso_code(self.container_reception.size)
            # Check freight indicator for full/empty
            if self.container_reception.freight_indicator == "LCL":
                full_empty = "4"  # Empty for LCL
        elif self.container_movement_order:
            container_no = self.container_movement_order.container_no or ""
            container_type = self._get_container_type_iso_code(self.container_movement_order.size)
            if self.container_movement_order.freight_indicator == "LCL":
                full_empty = "4"
        
        return f"EQD+CN+{container_no}+{container_type}:102:5++{equipment_status}+{full_empty}'"
    
    def _build_rff_sq_segment(self, sequence_number=1):
        """
        Build RFF+SQ segment for sequence number.
        
        Format: RFF+SQ:sequenceNumber'
        """
        return f"RFF+SQ:{sequence_number}'"
    
    def _build_cnt_segment(self, container_count=1):
        """
        Build CNT (Control Total) segment.
        
        Format: CNT+16:containersQuantity'
        """
        return f"CNT+16:{container_count}'"
    
    def _build_unt_segment(self, message_id):
        """
        Build UNT (Message Footer) segment.
        
        Format: UNT+numberOfMessageSegment+messageID'
        
        Note: segment_count includes UNH and UNT
        """
        return f"UNT+{self.segment_count}+{message_id}'"
    
    def _build_unz_segment(self, interchange_id):
        """
        Build UNZ (Interchange Footer) segment.
        
        Format: UNZ+1+interchangeID'
        """
        return f"UNZ+1+{interchange_id}'"
    
    def generate(self, message_function="original"):
        """
        Generate the complete COREOR EDI message.
        
        Args:
            message_function: "original", "replace", or "cancellation"
        
        Returns:
            str: Complete EDI message
        """
        self.segments = []
        self.segment_count = 0
        
        # Generate unique IDs
        interchange_id = self._generate_interchange_id()
        message_id = interchange_id  # Can be same as interchange ID
        
        # Get message number (document name)
        message_number = ""
        if self.container_reception:
            message_number = self.container_reception.name
        elif self.container_movement_order:
            message_number = self.container_movement_order.name
        
        # Get message function code
        msg_func_code = self.MESSAGE_FUNCTIONS.get(message_function, "9")
        
        # Build message segments
        
        # UNB - Interchange Header (not counted in UNT)
        unb = self._build_unb_segment(interchange_id)
        
        # Start counting segments for UNT (from UNH to UNT inclusive)
        
        # UNH - Message Header
        self._add_segment(self._build_unh_segment(message_id))
        
        # BGM - Beginning of Message
        self._add_segment(self._build_bgm_segment(message_number, msg_func_code))
        
        # DTM - Date/Time segments
        for dtm in self._build_dtm_segments():
            self._add_segment(dtm)
        
        # RFF - Reference segments
        for rff in self._build_rff_segments():
            self._add_segment(rff)
        
        # TDT - Transport Information
        self._add_segment(self._build_tdt_segment())
        
        # RFF+VON - Voyage Number (additional reference)
        voyage_no = ""
        if self.manifest:
            voyage_no = self.manifest.voyage_no or ""
        if voyage_no:
            self._add_segment(f"RFF+VON:{voyage_no}'")
        
        # LOC - Location segments
        for loc in self._build_loc_segments():
            self._add_segment(loc)
        
        # DTM+132 - Estimated Arrival Date
        dtm_arrival = self._build_dtm_arrival_segment()
        if dtm_arrival:
            self._add_segment(dtm_arrival)
        
        # NAD - Name and Address segments
        for nad in self._build_nad_segments():
            self._add_segment(nad)
        
        # EQD - Equipment Details
        self._add_segment(self._build_eqd_segment())
        
        # RFF+SQ - Sequence Number
        self._add_segment(self._build_rff_sq_segment(1))
        
        # CNT - Control Total
        self._add_segment(self._build_cnt_segment(1))
        
        # UNT - Message Footer (count includes UNH and UNT itself)
        self.segment_count += 1  # Add 1 for UNT itself before building
        self._add_segment(self._build_unt_segment(message_id))
        
        # UNZ - Interchange Footer (not counted in UNT)
        unz = self._build_unz_segment(interchange_id)
        
        # Combine all segments
        all_segments = [unb] + self.segments + [unz]
        
        return "\n".join(all_segments)
    
    def save_to_file(self, filepath=None, message_function="original"):
        """
        Generate EDI message and save to file.
        
        Args:
            filepath: Optional file path. If not provided, generates a default path.
            message_function: "original", "replace", or "cancellation"
        
        Returns:
            str: Path to the saved file
        """
        edi_content = self.generate(message_function)
        
        if not filepath:
            # Generate default filepath
            doc_name = ""
            if self.container_reception:
                doc_name = self.container_reception.name
            elif self.container_movement_order:
                doc_name = self.container_movement_order.name
            
            timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
            filepath = f"/tmp/COREOR_{doc_name}_{timestamp}.edi"
        
        with open(filepath, "w") as f:
            f.write(edi_content)
        
        return filepath


@frappe.whitelist()
def generate_coreor_edi(container_reception=None, container_movement_order=None, message_function="original"):
    """
    API method to generate COREOR EDI message.
    
    Args:
        container_reception: Name of Container Reception document
        container_movement_order: Name of Container Movement Order document
        message_function: "original", "replace", or "cancellation"
    
    Returns:
        dict: Contains 'edi_content' and 'filename'
    """
    generator = COREORGenerator(
        container_reception=container_reception,
        container_movement_order=container_movement_order
    )
    
    edi_content = generator.generate(message_function)
    
    # Generate filename
    doc_name = container_reception or container_movement_order or "UNKNOWN"
    timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
    filename = f"COREOR_{doc_name}_{timestamp}.edi"
    
    return {
        "edi_content": edi_content,
        "filename": filename
    }


def generate_sample_edi():
    """
    Generate a sample COREOR EDI file with mock data for testing.
    
    This function demonstrates the EDI format without requiring actual database records.
    
    Returns:
        str: Sample EDI content
    """
    
    # Generate unique IDs
    dt = datetime.now()
    interchange_date = dt.strftime("%y%m%d")
    interchange_time = dt.strftime("%H%M")
    interchange_id = f"ICD{dt.strftime('%y%m%d%H%M%S')}"
    message_id = interchange_id
    
    # Sample data matching the format
    sample_data = {
        "sender_id": "ICDTZ",
        "receiver_id": "TZDARDSEL",
        "document_number": "ICD-CR-2026-00001",
        "m_bl_no": "BAC0435360",
        "voyage_no": "04GGKE1MA",
        "vessel_name": "SPIL NISAKA",
        "call_sign": "3E3920",
        "container_no": "MAGU2309626",
        "container_type": "22G1",
        "arrival_date": dt.strftime("%Y%m%d"),
        "effective_date": dt.strftime("%Y%m%d"),
        "document_datetime": dt.strftime("%Y%m%d%H%M"),
        "expiry_date": (dt.replace(day=31) if dt.month == 12 else dt.replace(month=dt.month+1, day=1)).strftime("%Y%m%d"),
        "delivery_port": "TZDAR",
        "destination_port": "TZDAR",
        "loading_port": "SGSIN",
        "consignee_id": "0005203110",
        "forwarder_tin": "108-530-057",
    }
    
    # Build EDI message
    segments = [
        f"UNB+UNOA:2+{sample_data['sender_id']}+{sample_data['receiver_id']}+{interchange_date}:{interchange_time}+{interchange_id}'",
        f"UNH+{message_id}+COREOR:D:00B:UN:SMDG20'",
        f"BGM+129+{sample_data['document_number']}+9'",
        f"DTM+137:{sample_data['document_datetime']}:203'",
        f"RFF+RE:{sample_data['document_number']}'",
        f"RFF+BM:{sample_data['m_bl_no']}'",
        f"DTM+36:{sample_data['expiry_date']}:102'",
        f"DTM+7:{sample_data['effective_date']}:102'",
        f"TDT+20+{sample_data['voyage_no']}+1++:172:20+++{sample_data['call_sign']}:103::{sample_data['vessel_name']}'",
        f"LOC+7+{sample_data['delivery_port']}:139:6'",
        f"LOC+8+{sample_data['destination_port']}:139:6'",
        f"LOC+76+{sample_data['loading_port']}:139:6'",
        f"NAD+MS+{sample_data['sender_id']}:172:20'",
        f"NAD+CF+{sample_data['consignee_id']}:ZZZ:ZZZ'",
        f"NAD+FW+{sample_data['forwarder_tin']}:160:ZZZ'",
        f"EQD+CN+{sample_data['container_no']}+{sample_data['container_type']}:102:5++3+5'",
        f"RFF+SQ:1'",
        f"CNT+16:1'",
        f"UNT+18+{message_id}'",
        f"UNZ+1+{interchange_id}'",
    ]
    
    return "\n".join(segments)


if __name__ == "__main__":
    # Generate sample EDI for testing
    print(generate_sample_edi())
