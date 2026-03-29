# ICD TZ

Inland Container Depot (ICD) Management Application tailored for operations in Tanzania.

![ICD TZ Dashboard](./docs/dashboard.png)

## Overview

**ICD TZ** is a comprehensive custom application built on the Frappe framework. It is designed to streamline day-to-day operations at an Inland Container Depot. The application unifies gate operations, automated billing, manifest management, EDI integration, and real-time container tracking into a single, intuitive workspace following a logical operational flow.

## Key Features

### 1. Manifest & Bill of Lading (BL) Management
- **Excel Data Extraction:** Seamlessly extract and import large sets of ICD operational data directly from Excel files into the system, drastically reducing manual data entry for incoming vessel manifests.
- **Document Handling:** Capture and process full cargo manifests before the vessel physically arrives.
- **BL Hierarchies:** Full structural support linking **Master Bill of Lading (MBL)** and **House Bill of Lading (HBL)**.
- **Stakeholder Linking:** Associate manifests securely with Consignees, Clearing & Forwarding (C&F) Companies, and authorized Clearing Agents.

### 2. Logistics & Fleet Catalog
- Establish comprehensive registries for **Transporters**, **Trucks**, and **Trailers** well before they reach the yard.
- Manage profiles for **Drivers** and **Security Officers** to ensure strict authorization verification during operational gate events.

### 3. Container Reception (Receiving from Port)
- **Container Movement Orders:** Plan and authorize the initial dispatch of containers directly from the main port to the ICD yard.
- **Gate-In Process:** Log containers as they are physically received from the port. Verify seals, capture gross weights, and instantly transition their status into the active yard stream.
- **Transit Containers:** Contains specialized handling protocols for **Transit Cargo**. The system recognizes transit containers and automatically exempts them from unnecessary local terminal charges and bookings.

### 4. Advanced Container Tracking & Location Management
- **Status Tracking:** Real-time visibility of container states throughout their lifecycle (e.g., *In Yard*, *At Booking*, *At Inspection*, *At Payments*, *Delivered*).
- **Location Tracking:** Precise tracking of where a container is placed within the yard using the dedicated **Container Location** module.
- **Empty Container Handling:** Dedicated workflows to track, manage, and dispatch **Empty Containers** effectively without applying standard full-cargo requirements.
- **Condition State Logging:** Keep a historical record of the physical condition of containers as they undergo movement.

### 5. Yard Operations & Value-Added Services
- **In-Yard Container Booking:** Schedule containers for unpackaging, stripping, or specialized handling.
- **Loose Cargo Details:** Track unpacked items (LCL freight) individually after a container has been cleanly stripped.
- **Container Inspections:** Manage routine checks, offloading services, and status queries directly in the yard.
- **Container Verification Movements:** Coordinate and track internal yard movements required for Customs scanning or physical verification.
- **Service Orders:** Automatically raise service requests that link directly to standard Frappe `Sales Orders` and `Sales Invoices`.

### 6. Automated Billing & Tariff Engine
- **ICD TZ Settings:** A central configuration master defining precise tariff rules based on container dimensions (20ft, 40ft, 45ft, High Cube) and freight types.
- **Dynamic Storage Periods:** Intelligent logic defining grace periods and timeline transitions between *Single Charge* and *Double Charge* storage rates based on the container's final destination.
- **Automated Day Limits:** Background system jobs automatically calculate and increment the `days_to_be_billed` for every active container daily.

### 7. Strict Gate-Out Payment Security
- **Gate Pass Issuance (Gate-Out):** Generate secure gate passes linked to authorized Transporters and Drivers, ending the container's ICD timeline.
- The system enforces a rigorous validation layer before any Gate Pass can be submitted. **A container is mathematically blocked from leaving the yard if pending (unpaid) invoices exist.**
- It automatically verifies clearing status for:
  - **Storage Charges** (Single and Double storage).
  - **Removal and Corridor Levy Charges**.
  - **In-Yard Booking Services** (Stripping and Custom Verification Charges).
  - **Initial Reception Charges** (Transport and Shore Handling).
  - **Container Inspection Holds**.

### 8. Electronic Data Interchange (EDI) Integrations
- **CODECO Generation:** Automatically generate industry-standard **CODECO Gate-In** and **Gate-Out** report messages based on UN/EDIFACT D95B formats.
- **SMTP/SFTP Transmissions:** Natively pushes `.txt` or `.edi` payload files via configured Email workflows exclusively to shipping lines (e.g., CMA CGM).
- **Validation Locks:** Built-in safeguards that completely cancel a Gate-In or Gate-Out action if the generation of the mandatory EDI file fails.

### 9. Dashboard & Performance Monitoring
- A dynamic, visual dashboard providing a high-level overview of depot health.
- **Real-Time KPI Tracking:** View absolute numbers for *Total Containers In Yard*, *Gate In*, *Gate Out*, and *Pending Inspections*.
- **Distribution Charts:** Visual pie charts analyzing current container status distributions.
- **Historical Trends:** Interactive time-series charts presenting *Containers Received*, *Containers Delivered*, and *Gate Pass Issued Trends*.

## Built-In Reporting

ICD TZ comes pre-packaged with a suite of critical operational and financial reports:
- **Received Containers:** Detailed logs of all gate arrivals received from the port.
- **Current Container Stock:** Provide a complete audit of all containers currently residing in the yard.
- **Exited Containers & Gate Out Pass:** Traceability reports for containers that successfully departed the depot.
- **Container Booking & Interchange Document Booking Datewise:** Detailed insights into scheduled yard services over time.
- **Daily Stripped Containers:** Monitor the operational speed of LCL unpacking.
- **Loose Cargo Tracking:** Independent tracing of unpacked, loose cargo items.
- **Revenue Summary:** A comprehensive financial breakdown aggregating all earnings derived exclusively from ICD activities.

## Installation

Ensure you have a configured [Frappe Bench](https://frappeframework.com) environment running.

```bash
bench get-app https://github.com/av-dev2/icd_tz.git
bench --site [your-site-name] install-app icd_tz
```

## License

MIT