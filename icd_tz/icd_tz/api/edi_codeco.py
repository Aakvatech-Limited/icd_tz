# Copyright (c) 2024, elius mgani and contributors
# For license information, please see license.txt

"""
EDI CODECO (Container Gate-In/Gate-Out Report) Message Generator
Implementation Guide based on UN/EDIFACT D95B Version

CODECO is used by ICD/Terminal to report container movements at the gate:
- Gate-In: Container entering ICD premises (from Container Reception)
- Gate-Out: Container leaving ICD premises (from Gate Pass)

Segment Structure:
- UNB: Interchange Header
- UNH: Message Header
- BGM: Beginning of Message
- TDT: Transport Information (Main carriage)
- NAD: Name and Address
- EQD: Equipment Details
- RFF: Reference
- DTM: Date/Time/Period
- LOC: Location
- TDT: Transport Information (Pick-up/delivery)
- CNT: Control Total
- UNT: Message Footer
- UNZ: Interchange Footer
"""

import frappe
import random
import string
from datetime import datetime
from frappe.utils import now_datetime, getdate, get_datetime


class CODECOGenerator:
    """
    Generate EDI CODECO messages for Gate-In and Gate-Out operations.
    
    CODECO = Container Gate-In/Gate-Out Report Message
    Based on UN/EDIFACT D95B Version (ITG14 subset)
    
    Usage:
    - Gate-In: When container arrives at ICD (Container Reception)
    - Gate-Out: When container leaves ICD (Gate Pass)
    """
    
    # Message type codes
    MESSAGE_TYPE_CODES = {
        "gate_in": "34",   # Gate-In report
        "gate_out": "36",  # Gate-Out report (Departure)
    }
    
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
    
    # Transport mode codes
    TRANSPORT_MODE = {
        "maritime": "1",
        "rail": "2", 
        "road": "3",
        "air": "4"
    }
    
    def __init__(self, container_reception=None, gate_pass=None):
        """
        Initialize the generator with either a Container Reception (Gate-In) or Gate Pass (Gate-Out).
        
        Args:
            container_reception: Name of Container Reception document (for Gate-In)
            gate_pass: Name of Gate Pass document (for Gate-Out)
        """
        self.container_reception = None
        self.gate_pass = None
        self.container = None
        self.manifest = None
        self.movement_type = None  # "gate_in" or "gate_out"
        
        if container_reception:
            self.container_reception = frappe.get_doc("Container Reception", container_reception)
            self.movement_type = "gate_in"
            if self.container_reception.manifest:
                self.manifest = frappe.get_doc("Manifest", self.container_reception.manifest)
        elif gate_pass:
            self.gate_pass = frappe.get_doc("Gate Pass", gate_pass)
            self.movement_type = "gate_out"
            if self.gate_pass.container_id:
                self.container = frappe.get_doc("Container", self.gate_pass.container_id)
            if self.gate_pass.manifest:
                self.manifest = frappe.get_doc("Manifest", self.gate_pass.manifest)
        
        self.segments = []
        self.segment_count = 0
    
    def _generate_interchange_id(self):
        """Generate a unique interchange ID (max 14 characters alphanumeric)"""
        random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return f"BOA{random_suffix}"
    
    def _format_datetime(self, datetime_value, format_code="203"):
        """
        Format datetime according to EDIFACT date format codes.
        
        Format codes:
        - 102: CCYYMMDD
        - 203: CCYYMMDDHHMM
        - 204: CCYYMMDDHHMMSS
        """
        if not datetime_value:
            dt = now_datetime()
        elif isinstance(datetime_value, str):
            try:
                dt = get_datetime(datetime_value)
            except:
                dt = now_datetime()
        else:
            dt = datetime_value
        
        if format_code == "102":
            return dt.strftime("%Y%m%d")
        elif format_code == "203":
            return dt.strftime("%Y%m%d%H%M")
        elif format_code == "204":
            return dt.strftime("%Y%m%d%H%M%S")
        
        return dt.strftime("%Y%m%d%H%M")
    
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
        return "CMA"
    
    def _add_segment(self, segment):
        """Add a segment to the message"""
        self.segments.append(segment)
        self.segment_count += 1
    
    def _build_unb_segment(self, interchange_id):
        """
        Build UNB (Interchange Header) segment.
        
        Format: UNB+UNOA:4+senderID+receiverID+date:time+interchangeID'
        """
        dt = now_datetime()
        interchange_date = dt.strftime("%y%m%d")
        interchange_time = dt.strftime("%H%M")
        sender_id = self._get_sender_id()
        receiver_id = self._get_receiver_id()
        
        return f"UNB+UNOA:4+{sender_id}+{receiver_id}+{interchange_date}:{interchange_time}+{interchange_id}'"
    
    def _build_unh_segment(self, message_id):
        """
        Build UNH (Message Header) segment.
        
        Format: UNH+messageID+CODECO:D:95B:UN:ITG14'
        """
        return f"UNH+{message_id}+CODECO:D:95B:UN:ITG14'"
    
    def _build_bgm_segment(self, message_function="9"):
        """
        Build BGM (Beginning of Message) segment.
        
        Format: BGM+messageTypeCode+receiverID+messageFunction'
        
        Message type codes:
        - 34: Gate-In report
        - 35: Gate-Out report
        """
        msg_type_code = self.MESSAGE_TYPE_CODES.get(self.movement_type, "34")
        receiver_id = self._get_receiver_id()
        
        return f"BGM+{msg_type_code}+{receiver_id}+{message_function}'"
    
    def _build_tdt_main_carriage_segment(self):
        """
        Build TDT segment for main carriage (vessel transport).
        
        Format: TDT+20++transportMode++carrierID:172'
        
        Transport stage qualifier: 20 = Main-carriage transport
        """
        carrier_id = self._get_receiver_id()
        
        return f"TDT+20++1++{carrier_id}:172'"
    
    def _build_nad_segments(self):
        """
        Build NAD (Name and Address) segments.
        
        Returns list of NAD segments:
        - NAD+CF: Container operator/Carrier
        - NAD+MS: Message Sender (ICD)
        """
        segments = []
        
        carrier_id = self._get_receiver_id()
        sender_id = self._get_sender_id()
        
        # NAD+CF: Container operator (shipping line)
        segments.append(f"NAD+CF+{carrier_id}:172'")
        
        # NAD+MS: Message Sender (ICD)
        segments.append(f"NAD+MS+{sender_id}'")
        
        return segments
    
    def _build_eqd_segment(self):
        """
        Build EQD (Equipment Details) segment.
        
        Format: EQD+CN+containerNumber+containerTypeISOcode:102:5++equipmentStatus+fullEmptyIndicator'
        """
        container_no = ""
        container_type = "22G1"
        equipment_status = "3"  # Import
        full_empty = "5"  # Full
        
        if self.container_reception:
            container_no = self.container_reception.container_no or ""
            container_type = self._get_container_type_iso_code(self.container_reception.size)
            if self.container_reception.freight_indicator == "LCL":
                full_empty = "4"
        elif self.gate_pass:
            container_no = self.gate_pass.container_no or ""
            container_type = self._get_container_type_iso_code(self.gate_pass.size)
            if self.gate_pass.is_empty_container:
                full_empty = "4"
            # Gate out could be export
            if self.gate_pass.is_empty_container:
                equipment_status = "2"  # Export for empty returns
        
        return f"EQD+CN+{container_no}+{container_type}:102:5++{equipment_status}+{full_empty}'"
    
    def _build_rff_segment(self):
        """
        Build RFF (Reference) segment for Bill of Lading.
        
        Format: RFF+BN:billOfLadingNo'
        """
        bl_no = ""
        if self.container_reception:
            bl_no = self.container_reception.m_bl_no or ""
        elif self.gate_pass:
            bl_no = self.gate_pass.m_bl_no or self.gate_pass.h_bl_no or ""
        
        return f"RFF+BN:{bl_no}'"
    
    def _build_dtm_segment(self):
        """
        Build DTM (Date/Time/Period) segment.
        
        Format: DTM+7:datetime:203'
        
        DTM qualifier 7 = Effective date/time
        """
        event_datetime = None
        
        if self.container_reception:
            # Gate-In: Use received date + ICD time in
            received_date = self.container_reception.received_date
            icd_time_in = self.container_reception.icd_time_in
            if received_date and icd_time_in:
                event_datetime = f"{received_date} {icd_time_in}"
            elif received_date:
                event_datetime = received_date
        elif self.gate_pass:
            # Gate-Out: Use gate out date or submitted date
            if self.gate_pass.gate_out_date:
                event_datetime = self.gate_pass.gate_out_date
            elif self.gate_pass.submitted_date:
                if self.gate_pass.submitted_time:
                    event_datetime = f"{self.gate_pass.submitted_date} {self.gate_pass.submitted_time}"
                else:
                    event_datetime = self.gate_pass.submitted_date
        
        formatted_dt = self._format_datetime(event_datetime, "203")
        
        return f"DTM+7:{formatted_dt}:203'"
    
    def _build_loc_segment(self):
        """
        Build LOC (Location) segment.
        
        Format: LOC+165+portCode:139:6+terminalCode:TER:ZZZ'
        
        LOC qualifier 165 = Place of discharge
        """
        port_code = "TZDAR"  # Dar es Salaam
        terminal_code = "TZDARDSEL"  # Default terminal
        
        # Try to get port from the document
        if self.container_reception and self.container_reception.port:
            if self.container_reception.port == "DP WORLD":
                terminal_code = "TZDARDPW"
            elif self.container_reception.port == "TEAGTL":
                terminal_code = "TZDARTEAGTL"
        
        return f"LOC+165+{port_code}:139:6+{terminal_code}:TER:ZZZ'"
    
    def _build_tdt_pickup_segment(self):
        """
        Build TDT segment for pick-up/delivery transport (road transport).
        
        Format: TDT+1++transportMode++transporterID:172::transporterName+++truckNo'
        
        Transport stage qualifier: 1 = Pick-up/delivery
        Transport mode: 3 = Road
        """
        transport_mode = "3"  # Road
        transporter_id = ""
        transporter_name = ""
        truck_no = ""
        
        if self.container_reception:
            transporter_name = self.container_reception.transporter or ""
            truck_no = self.container_reception.truck or ""
            if self.container_reception.trailer:
                truck_no = self.container_reception.trailer  # Use trailer as the main vehicle ID
        elif self.gate_pass:
            transporter_name = self.gate_pass.transporter or ""
            truck_no = self.gate_pass.truck or ""
            if self.gate_pass.trailer:
                truck_no = self.gate_pass.trailer
        
        # Use first two letters of transporter name as ID if available
        if transporter_name:
            transporter_id = transporter_name[:2].upper()
        else:
            transporter_id = "GA"
        
        return f"TDT+1++{transport_mode}++{transporter_id}:172::{transporter_name}+++{truck_no}'"
    
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
        Generate the complete CODECO EDI message.
        
        Args:
            message_function: "original", "replace", or "cancellation"
        
        Returns:
            str: Complete EDI message
        """
        self.segments = []
        self.segment_count = 0
        
        # Generate unique IDs
        interchange_id = self._generate_interchange_id()
        message_id = interchange_id
        
        # Get message function code
        msg_func_code = self.MESSAGE_FUNCTIONS.get(message_function, "9")
        
        # Build message segments
        
        # UNB - Interchange Header (not counted in UNT)
        unb = self._build_unb_segment(interchange_id)
        
        # UNH - Message Header
        self._add_segment(self._build_unh_segment(message_id))
        
        # BGM - Beginning of Message
        self._add_segment(self._build_bgm_segment(msg_func_code))
        
        # TDT - Main carriage transport (vessel)
        self._add_segment(self._build_tdt_main_carriage_segment())
        
        # NAD - Name and Address segments
        for nad in self._build_nad_segments():
            self._add_segment(nad)
        
        # EQD - Equipment Details
        self._add_segment(self._build_eqd_segment())
        
        # RFF - Reference (Bill of Lading)
        self._add_segment(self._build_rff_segment())
        
        # DTM - Date/Time
        self._add_segment(self._build_dtm_segment())
        
        # LOC - Location
        self._add_segment(self._build_loc_segment())
        
        # TDT - Pick-up/delivery transport (road)
        self._add_segment(self._build_tdt_pickup_segment())
        
        # CNT - Control Total
        self._add_segment(self._build_cnt_segment(1))
        
        # UNT - Message Footer
        self.segment_count += 1  # Add 1 for UNT itself
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
            doc_name = ""
            movement = "GATEIN" if self.movement_type == "gate_in" else "GATEOUT"
            
            if self.container_reception:
                doc_name = self.container_reception.name
            elif self.gate_pass:
                doc_name = self.gate_pass.name
            
            timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
            filepath = f"/tmp/CODECO_{movement}_{doc_name}_{timestamp}.edi"
        
        with open(filepath, "w") as f:
            f.write(edi_content)
        
        return filepath


@frappe.whitelist()
def generate_codeco_gate_in(container_reception, message_function="original"):
    """
    API method to generate CODECO Gate-In EDI message.
    
    Args:
        container_reception: Name of Container Reception document
        message_function: "original", "replace", or "cancellation"
    
    Returns:
        dict: Contains 'edi_content' and 'filename'
    """
    generator = CODECOGenerator(container_reception=container_reception)
    
    edi_content = generator.generate(message_function)
    
    timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
    filename = f"CODECO_GATEIN_{container_reception}_{timestamp}.edi"
    
    return {
        "edi_content": edi_content,
        "filename": filename,
        "movement_type": "gate_in"
    }


@frappe.whitelist()
def generate_codeco_gate_out(gate_pass, message_function="original"):
    """
    API method to generate CODECO Gate-Out EDI message.
    
    Args:
        gate_pass: Name of Gate Pass document
        message_function: "original", "replace", or "cancellation"
    
    Returns:
        dict: Contains 'edi_content' and 'filename'
    """
    generator = CODECOGenerator(gate_pass=gate_pass)
    
    edi_content = generator.generate(message_function)
    
    timestamp = now_datetime().strftime("%Y%m%d_%H%M%S")
    filename = f"CODECO_GATEOUT_{gate_pass}_{timestamp}.edi"
    
    return {
        "edi_content": edi_content,
        "filename": filename,
        "movement_type": "gate_out"
    }


def generate_sample_codeco_gate_in():
    """
    Generate a sample CODECO Gate-In EDI file with mock data for testing.
    
    Returns:
        str: Sample EDI content
    """
    dt = datetime.now()
    interchange_date = dt.strftime("%y%m%d")
    interchange_time = dt.strftime("%H%M")
    interchange_id = f"BOA{dt.strftime('%H%M%S')}GI"
    message_id = interchange_id
    
    sample_data = {
        "sender_id": "SILVER",
        "receiver_id": "CMA",
        "container_no": "MZWU2103523",
        "container_type": "45G1",
        "bl_no": "ISB1666991A",
        "event_datetime": dt.strftime("%Y%m%d%H%M"),
        "port_code": "TZDAR",
        "terminal_code": "TZDARDSEL",
        "transporter_id": "GA",
        "transporter_name": "GALCO LIMIT",
        "truck_no": "T301DDJ"
    }
    
    segments = [
        f"UNB+UNOA:4+{sample_data['sender_id']}+{sample_data['receiver_id']}+{interchange_date}:{interchange_time}+{interchange_id}'",
        f"UNH+{message_id}+CODECO:D:95B:UN:ITG14'",
        f"BGM+34+{sample_data['receiver_id']}+9'",
        f"TDT+20++1++{sample_data['receiver_id']}:172'",
        f"NAD+CF+{sample_data['receiver_id']}:172'",
        f"NAD+MS+{sample_data['sender_id']}'",
        f"EQD+CN+{sample_data['container_no']}+{sample_data['container_type']}:102:5++3+5'",
        f"RFF+BN:{sample_data['bl_no']}'",
        f"DTM+7:{sample_data['event_datetime']}:203'",
        f"LOC+165+{sample_data['port_code']}:139:6+{sample_data['terminal_code']}:TER:ZZZ'",
        f"TDT+1++3++{sample_data['transporter_id']}:172::{sample_data['transporter_name']}+++{sample_data['truck_no']}'",
        f"CNT+16:1'",
        f"UNT+13+{message_id}'",
        f"UNZ+1+{interchange_id}'",
    ]
    
    return "\n".join(segments)


def generate_sample_codeco_gate_out():
    """
    Generate a sample CODECO Gate-Out EDI file with mock data for testing.
    
    Returns:
        str: Sample EDI content
    """
    dt = datetime.now()
    interchange_date = dt.strftime("%y%m%d")
    interchange_time = dt.strftime("%H%M")
    interchange_id = f"BOA{dt.strftime('%H%M%S')}GO"
    message_id = interchange_id
    
    sample_data = {
        "sender_id": "SILVER",
        "receiver_id": "CMA",
        "container_no": "MZWU2103523",
        "container_type": "45G1",
        "bl_no": "ISB1666991A",
        "event_datetime": dt.strftime("%Y%m%d%H%M"),
        "port_code": "TZDAR",
        "terminal_code": "TZDARDSEL",
        "transporter_id": "TR",
        "transporter_name": "TRANSPORT CO",
        "truck_no": "T456ABC"
    }
    
    segments = [
        f"UNB+UNOA:4+{sample_data['sender_id']}+{sample_data['receiver_id']}+{interchange_date}:{interchange_time}+{interchange_id}'",
        f"UNH+{message_id}+CODECO:D:95B:UN:ITG14'",
        f"BGM+36+{sample_data['receiver_id']}+9'",  # 36 = Gate-Out
        f"TDT+20++1++{sample_data['receiver_id']}:172'",
        f"NAD+CF+{sample_data['receiver_id']}:172'",
        f"NAD+MS+{sample_data['sender_id']}'",
        f"EQD+CN+{sample_data['container_no']}+{sample_data['container_type']}:102:5++2+4'",  # Export, Empty
        f"RFF+BN:{sample_data['bl_no']}'",
        f"DTM+7:{sample_data['event_datetime']}:203'",
        f"LOC+165+{sample_data['port_code']}:139:6+{sample_data['terminal_code']}:TER:ZZZ'",
        f"TDT+1++3++{sample_data['transporter_id']}:172::{sample_data['transporter_name']}+++{sample_data['truck_no']}'",
        f"CNT+16:1'",
        f"UNT+13+{message_id}'",
        f"UNZ+1+{interchange_id}'",
    ]
    
    return "\n".join(segments)


if __name__ == "__main__":
    print("=== Sample CODECO Gate-In ===")
    print(generate_sample_codeco_gate_in())
    print("\n=== Sample CODECO Gate-Out ===")
    print(generate_sample_codeco_gate_out())
