Functional Requirements
GIS Specialist
	1.1 The specialist shall have an account in the system.
	1.2 The specialist shall have access to all functionalities in the system.
	1.3 The system shall allow the specialist to import the existing risk exposure report (farmer records/profiles) via CSV file.
	1.4 The system shall allow the specialist to upload the farmers' spatial GPX files to establish farm polygons.
	1.5 The system shall allow the specialist to execute the automated analysis, triggering the system to generate the Tropical Cyclone Bulletin (TCB) data, which includes period of exposure and wind velocity.
	1.6 The system shall automate the calculation process by mapping the period of exposure (e.g., 3 hours exposed to Signal No. 2), identifying the wind velocity, matching the crop growth stage, and calculating the corresponding indemnity/damage factor.
	1.7 The system shall allow the specialist to filter the dashboard and reports by municipality, province, barangay, or city.
	1.8 The system shall allow the specialist to sort records alphabetically, by planting date, or by any specific column.
	1.9 The system shall allow the specialist to generate and export an extended CSV report that appends the calculated results (period of exposure, wind velocity, indemnity factor, and final indemnity payment) to the original PCIC row format.

System Administrator
	2.1 The system shall allow the administrator to securely log in to access the backend infrastructure. 
	2.2 The system shall allow the administrator to create or restrict user accounts, manage localized system configurations, and execute database backups to ensure institutional data security. 
	2.3 The system shall provide a dedicated "Calibration/Settings" module on the dashboard for configuring system parameters.
	2.4 The system shall allow the administrator to input or manage Google Cloud Project credentials to allocate the capacity (e.g., 1000 EEC) for Google Earth Engine SAR analysis.

External Entities
	3.1 The system's Python-based parser shall monitor the PAGASA website and automatically download the 3-hour Tropical Cyclone Bulletin updates during an active typhoon in the PAR.
	3.2 The system shall trigger an on-screen pop-up and an automated email alert to notify the GIS specialist when a new bulletin is successfully parsed.
3.3 The system shall automatically compile and store all downloaded versions of the PAGASA PDF bulletins during a typhoon event without overwriting previous versions.
	3.4 The system shall interface with Google Earth Engine to retrieve Synthetic Aperture Radar (SAR) imagery to analyze the percentage of area planted within the polygons.

User Interface
	4.1 The main dashboard shall be structurally divided into four specific modules to handle the automated disaster risk assessment workflow: a Home Dashboard, Spatial Analysis & Data Import, Assessment & Reporting, and Calibration/Settings. 
	4.2 The system shall provide a drag-and-drop area for uploading new CSV files.
	4.3 The system shall display corresponding metadata (farmer ID, name, address, farm ID, hectare area, and whether it is planted) instantly when a user clicks on a farm polygon on the map.
	4.4 The system shall include tooltips and short explanations for the map tools and assessment results.
	4.5 The system shall display warning prompts before a user deletes, overwrites, or finalizes any data.
	4.6 The system shall provide a "Generate Report" button that allows users to preview the CSV layout before finalizing the download
4.7 The system shall utilize specific UI theme colors combining green, yellow (gold), and blue, and support both light and dark modes.
4..8 The system shall utilize a toggle menu to display high-level statistical summaries rather than permanent sidebar widgets.

Non-Functional Requirements
Accessibility
1.1 The web interface shall be dynamically responsive so that it is readable and functional on varying screen sizes, including smaller monitors and tablets used during field office meetings.
Accuracy
	2.1 The generated reports and CSV headers must use the exact terminology found in official PCIC forms to ensure the output is immediately "Payout-Ready" for the Finance Division.
Compatibility
	3.1 The system shall be compatible with and accessible across multiple web browsers.
	3.2 The system's final exported files must strictly adhere to the CSV format to ensure seamless compatibility with the legacy PCIC Automated Business System (PABS).
Performance
	4.1 The system shall run heavy geoprocessing calculations (like cross-referencing typhoon signals) in the background while displaying a loading spinner to the user.
	4.2 The WebGIS map viewport shall successfully query and render over 100,000 spatial polygons in under 10 seconds. 
Reliability
	5.1 The system shall automatically save ongoing work and imported data to prevent data loss.
	5.2 The system must maintain high availability, with maximum acceptable downtime restricted to 24 to 48 hours.
Security
	6.1 The system shall feature an optional 5-minute session timeout for inactive terminals, configured to retain the user's last session upon logging back in.
Usability
	7.1 The user interface must be simple, formal, functional, and easy to navigate.
	7.2 The map interface shall utilize intuitive color-coding for crop growth stages.
	7.3 The system shall provide specific, descriptive error messages (e.g., "failed to parse PAGASA") rather than generic error codes whenever a process fails.

System Modules
Monitoring & Extraction Module: This module serves as the landing page and active monitoring center for the system. It handles the real-time pulling and extraction of PAGASA Tropical Cyclone Bulletin (TCB) reports and features a notification system to immediately alert the GIS specialist when a new TCB is successfully parsed and downloaded.


Spatial Analysis & Data Import Module: This module maximizes visualization and data handling by dividing the interface into a top and bottom layout.
The top panel features the interactive GIS base map that displays the overlay of the typhoon's trajectory and the mapped polygons of the affected insured rice farms, while also allowing the export of the initial "Period of Exposure" report. 
The bottom panel provides a drag-and-drop interface for importing the legacy farmer record CSV files and spatial GPX polygons, displaying a tabular overview where clicking a row automatically highlights the corresponding farm polygon on the map above.


Assessment & Reporting Module: This module serves as the data compilation and review center for indemnification processing. It presents a summarized view of the parsed TCB records alongside the imported rice risk exposure records, automates the extended tabular calculation results (factoring in the period of exposure, wind velocity, crop growth stage, and indemnity factors), and features a "Generate Report" button to preview and export the finalized CSV indemnification report.


Calibration & Settings Module : This module functions as the administrative and configuration panel, accessed via a toggle menu to maximize the vertical screen space for the map interface. It allows authorized users to manually edit system parameters, or override data as a fail-safe, and manage system credentials such as the Google Cloud Project IDs used to allocate capacity for Google Earth Engine satellite analysis.

"Take a look at our diagrams and ERD (Entity-Relationship Diagram). You will base the working functionality of the High-Fidelity Wireframe on that. It is up to you how you implement it, as long as it shows that a user can log in, upload, and immediately conduct a parametric assessment. Furthermore, it should allow requesting an Area of Interest (AOI) in Google Earth Engine (GEE) using SAR data. Wireframe needed no need for logics

"In the wireframe, I decided that we need to add a feature for the specialist to edit the coverage amount instead of having it hard-coded."