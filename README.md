# ArchaeoAstroInsight (A2i) QGIS Plugin

ArchaeoAstroInsight is a powerful QGIS plugin designed for archaeoastronomy research. It enables researchers to compute precise azimuths, horizon altitudes, and celestial declinations for archaeological orientations, now featuring an advanced multi-point clustering system for large-scale field data.

---

##  Key Features

* **Multi-Point Clustering**: Capture hundreds of objects and group them automatically by proximity.
* **Efficient Calculations**: Performs complex horizon API requests once per cluster centroid rather than per object.
* **Batch CSV Import**: Load large datasets from external surveys using a flexible CSV schema.
* **Horizon Integration**: Automatically fetches horizon profile data via the HeyWhatsThat.com API.
* **Star Catalog Matching**: Cross-references calculated declinations with the BSC5 star catalog, Sun, and Moon.
* **Visual Analysis**: Dynamic map layers showing object lines, cluster boundaries (green polygons), and centroids.

---

##  Workflow & Usage

### 1. Data Entry: Manual or Import
You can populate your project using two primary methods:

**A. Manual Batch Capture**
1. Click the **A2i Toggle Batch Mode** button.
2. **First Click**: Sets the start point of an object (e.g., a megalith or wall end).
3. **Second Click**: Sets the end point. A red marker and line will appear.
4. Repeat for all objects in your study area.

**B. CSV Import**
Click **A2i Import from CSV** to load coordinates. The system supports flexible headers:
* **Required**: `lat1`, `lon1`, `lat2`, `lon2` (Decimal Degrees, EPSG:4326).
* **Optional**: `azimuth` (If provided, skips auto-calculation).

### 2. Processing: Clustering
Once objects are captured, click **A2i Run Clustering**. The system follows these steps:
1. **Midpoint Extraction**: Calculates the centroid for every object.
2. **DBSCAN Grouping**: Groups objects within a **100-meter threshold**.
3. **Centroid Calculation**: Determines the mean location and average azimuth for the entire cluster.


### 3. Analysis: Astronomical Calculations
For each cluster, the plugin performs:
* **Horizon Altitude**: Requests data from `script.py` using the cluster centroid.
* **Declination**: Calculates celestial declination using the mean azimuth and altitude.
* **Body Identification**: Identifies matching stars, planets, or solar/lunar events.

---

## 📊 CSV Import Specifications

To import data, ensure your CSV follows this structure (WGS84 / EPSG:4326):

| lat1 | lon1 | lat2 | lon2 | azimuth (optional) |
| :--- | :--- | :--- | :--- | :--- |
| 45.1234 | -73.5678 | 45.1240 | -73.5680 | 45.5 |
| 45.1300 | -73.5700 | 45.1305 | -73.5705 | |

*Accepted variations: `latitude1`, `longitude1`, `lat_1`, `lng1`, `bearing`.*

---


##  Technical Details & Requirements

* **QGIS Version**: 3.x
* **Python Dependencies**: `sklearn` (for DBSCAN clustering), `requests`. 
    * *Note: If `sklearn` is missing, the plugin uses an optimized Union-Find fallback.*
* **Coordinate Systems**: 
    * Map Canvas: EPSG:3857 (Web Mercator)
    * Calculations: EPSG:4326 (WGS84)
* **API**: Requires an active internet connection for HeyWhatsThat.com horizon data.

---

##  Exporting Results

Upon completion, you can export a comprehensive CSV containing:
1.  **Cluster Rows**: Full astronomical data (Declination, Stars, Altitude).
2.  **Object Rows**: Reference data (Individual coordinates and azimuths).

---

## Troubleshooting

* **Objects not clustering?** Ensure they are within 100 meters of each other.
* **Layers not visible?** Check the Layers Panel for "Cluster_X" layers and ensure they are at the top of the stack.
* **API Errors?** Verify your internet connection and ensure your coordinates are in valid decimal degrees (-90 to 90).
