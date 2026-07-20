**How the system works for the PCIC**

**The AgriSureGIS platform is strictly an office-based desktop tool. Access is restricted to authorized office personnel**:

**GIS Specialists / Analysts**: Authorized to import spatial files (GPX/Polygons), upload CSV files from the main PCIC system, link spatial-to-attribute data, run the parametric damage assessments, and manage the database.

**PCIC Management**: Authorized to view the interactive dashboard, monitor regional insurance distribution, and extract PDF reports.

# **Phase 1: Data Integration (Routine Operations)**

1\. **Field Data Turnover (Outside the System)**: Fieldmen manually collect GPX coordinates and farm data during their physical visits through the process of “Georeferencing/GeoMapping” or they just gather necessary data from the Department of Agriculture and turn these files over to the regional office.

2\. **System Ingestion**: The GIS Specialist logs into AgriSureGIS and imports the updated CSV and GPX files.

3\. **Spatial Validation**: The system maps the polygons. The specialist verifies coordinate accuracy and links the spatial boundary to the farmer's attribute profile.

# **Phase 2: Automated Damage Assessment (During Typhoons)**

1\. **PAGASA Notification**: When a typhoon enters the Philippine Area of Responsibility (PAR), the system detects a new PAGASA Tropical Cyclone Bulletin and notifies the GIS Specialist.

2\. **Data Extraction & Overlay**: The system automatically extracts the wind signal radii from the PAGASA report and overlays it onto the PCIC base map containing the 180,000-200,00+ farm polygons.

3\. **Parametric Calculation**: The system cross-references the wind signals against the imported "Risk Exposure List," calculating the duration of exposure and the crop stage for the affected municipalities.

4\. **Finalization**: The GIS Specialist reviews the automated results and generates a finalized list of affected farmers and estimated potential claims for management approval.

# **SUMMARY OF THE FIRST INTERVIEW**

Region X PCIC manages a vast inventory of geospatial data (composed of data regarding what it looks like on the map. in our system, the data consists of the names of the farmer and their hectare plot of land). There are two types: spatial (latitude and longitude coordinates of the farm) and attribute (farmer's name, rsbsa ID, crop type, and insurance statuses of each farmer). 

In our system, these two types of data are to be linked together.

the problem is that they have an existing standalone main PCIC pub managed by their head office capable of extracting those types of data into csv, however it is still complex to digitalize (automation) and so far it is manually inputted by employees to generate insurance history. 

\-prioritize GIS-

In light of this, they wanted a separate system that could handle their 500,000+ Data(polygon/georeference area) but only limited to misamis oriental, camiguin island and bukidnon (exceptions are caraga), and to integrate it into our proposed webGIS platform so that it is accessible to fieldmen (offline compatibility), GIS specialists (interactive dashboard) and easy verification (real time updates). They want to integrate it on a separate system (not on their centralized system) using GPX, since in time of typhoon, it is easier to access.

**SUMMARY OF THE SECOND INTERVIEW**

**Revisions:**

1. The system will still have a dashboard- but mainly for typhoon induced assessment feature. Every time a typhoon is present, The PCIC will conduct an analysis using the Tropical Bulletin on PAGASA website, PAGASA will provide a pdf report, after extracting the spatial data, PCIC  will then summarize it to conduct an analysis for damage assessment.

2. The system will not have a mobile-offline capability, but instead- its main feature is extracting data from PAGASA. Including, Automation and Integration of PAGASA website to our proposed system via notification and data extraction.

**Flow of the system:**

1. A base map is provided to show Farmers each of their polygons (Spatial-to-attribute data linking). Then a feature where we automate pdf report PAGASA, for the PCIC to summarize. 

2. PCIC will then upload/import their spatial, attribute and risk exposure list of farmers record in the system to conduct analysis.  
   *Note: Risk exposure list of farmers record (PCIC will provide the data)  \- farmers who are vulnerable when a typhoon is present.*

3. Analysis includes: Farmers and their exposure filter to view who was damaged PER signal no. based on the PAGASA report. And, the duration of time each municipality is currently affected by what signal no. based on the PAGASA report.  
   *Note: The basis of each signal no. are the wind velocity*

4. The Calculation should include: stage of crops (provided on the risk exposure report) and duration of risk exposure.

5. The Result: list of farmers affected, duration of signal no., possible amount of insurance claim

**Requirements for the damage Assessment:**

1. **For Attribute/Insurance Claims**: workflow consists of employees manually assessing operations and manual calculation constants 

2. **For each Polygon**: georeference/geomapping, on-field conducting data, collaboration with Department Agriculture gather data (optional)

3. **For the Farmers**: They either call or go to the office to get an insurance Application form for claims.

   
**Suggestions for the system by client:**   
1\. Dashboard \= Base map (leaflet), analysis (QGIS, python) 

2\. PAGASA main feature \=  https://www.pagasa.dost.gov.ph/tropical-cyclone-advisory-iframe \> once they upload a report, the system will notify the specialist or user that a report has been generated on the website

3\. The system is only composed of tools.

4\. local storage only, but if there's a way to provide them a secured POSTGIS database (not cloud since mobile application is removed) then much better.