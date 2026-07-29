<div align="center">
  <img src="icon.png" alt="ArchaeoAstroInsight Logo" width="200" height="200">

  # ArchaeoAstroInsight
  ### *Archaeoastronomy at Scale — From Bearings to Stars*

  [![QGIS Plugin](https://img.shields.io/badge/QGIS_Plugin-3.18%2B-589632?style=for-the-badge&logo=qgis&logoColor=white)](https://qgis.org/)
  [![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
  [![Archaeoastronomy](https://img.shields.io/badge/Domain-Archaeoastronomy-4B0082?style=for-the-badge)](#)
  [![Horizon Engine](https://img.shields.io/badge/Horizon_Engine-C%2B%2B_%2B_OpenMP-00599C?style=for-the-badge&logo=cplusplus&logoColor=white)](https://www.openmp.org/)
  [![Clustering](https://img.shields.io/badge/Clustering-6_Algorithms-F7931E?style=for-the-badge&logo=scikitlearn&logoColor=white)](#clustering-methods)
  [![BSC5](https://img.shields.io/badge/Star_Catalogue-BSC5-4B0082?style=for-the-badge)](#)
  [![License](https://img.shields.io/badge/License-GPL_v2%2B-blue?style=for-the-badge)](#license)

</div>

<p align="center">
  <i>A QGIS plugin for quantitative archaeoastronomy: it turns a bearing drawn on
  the map into an azimuth and horizon altitude, derives the corresponding
  declination, and matches it against the BSC5 bright-star catalogue — with
  batch processing and six interchangeable spatial-clustering algorithms so that
  whole archaeological sites (tombs, monuments, alignments) can be analysed in a
  single, reproducible run.</i>
</p>

---

ArchaeoAstroInsight (A2i) computes the **azimuth** and **horizon altitude**
indicated by a bearing (a line drawn between two points on the map), derives the
corresponding **declination**, and matches it against a star catalogue (BSC5).
The plugin also supports **batch analysis** and **spatial clustering** of many
objects (e.g. tombs, monuments) so that whole sites can be processed at once.

> This plugin extends the original **ArchaeoAstroInsight (A2i)** QGIS plugin.
> See [Attribution & Contributions](#attribution--contributions) for a precise
> breakdown of what was inherited and what was added for this thesis.

---

## Table of Contents

1. [Features](#features)
2. [Technology Stack](#technology-stack)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Usage](#usage)
   - [Quick Start](#quick-start)
   - [Toolbar Actions](#toolbar-actions)
   - [Single Bearing Workflow](#single-bearing-workflow)
   - [Batch Mode & Clustering](#batch-mode--clustering)
   - [Understanding the Output](#understanding-the-output)
   - [Troubleshooting](#troubleshooting)
7. [Clustering Methods](#clustering-methods)
   - [Available Methods](#available-methods)
   - [Interface Specification](#interface-specification)
   - [Barnes-Hut Clustering](#barnes-hut-clustering)
8. [CSV Import Format](#csv-import-format)
9. [SRTM Horizon Pipeline](#srtm-horizon-pipeline)
10. [Testing](#testing)
11. [Project Structure](#project-structure)
12. [Attribution & Contributions](#attribution--contributions)
13. [License](#license)

---

## Features

- Compute azimuth and horizon altitude from a bearing drawn on the map.
- Derive declination and match against the **BSC5** bright-star catalogue.
- Two horizon sources: **HeyWhatsThat** (online) or a local **SRTM** DEM
  pipeline (offline, computed via a bundled C++ calculator).
- **Batch mode**: capture many objects and process them in one run.
- **Spatial clustering** with six interchangeable algorithms.
- **CSV import** of objects (point pairs) for reproducible, scripted analysis.
- **Experiment runner**: repeat a processing mode 10x and auto-save CSVs for
  timing/quality benchmarking.

---

## Technology Stack

ArchaeoAstroInsight is a **QGIS Python plugin**. It does not have a standalone
web/desktop front end; instead it embeds itself into the QGIS application, so the
"front end" is the QGIS GUI (driven through PyQt) and the "back end" is the
Python/C++ computation layer behind it.

### Front End (User Interface)

| Technology | Role |
|------------|------|
| **QGIS 3.18+ GUI** | Host application; toolbar, menu, map canvas, message bar |
| **PyQt5** (`qgis.PyQt`) | All UI widgets: dialogs, input boxes, progress dialogs |
| **Qt Designer `.ui` files** | `dialog.ui` (settings) and `save_data.ui` (save results) |
| **Qt Resources** (`resources.qrc` → `resources.py`) | Bundled toolbar/logo icons |
| **QGIS canvas API** | Drawing bearings (`QgsVertexMarker`, vector line layers), cluster polygons, centroid markers |

### Back End (Computation & Data)

| Technology | Role |
|------------|------|
| **Python 3.8+** | Core engine (`core.py`), declination math and star matching (`utility.py`) |
| **PyQGIS core API** (`qgis.core`) | Coordinate transforms (EPSG:3857 ↔ EPSG:4326), geometry, layers |
| **C++ with OpenMP** | Offline horizon calculator (`calculate_horizon_topography_new.cpp` → `horizon_calc`) |
| **scikit-learn** | DBSCAN, K-Means, Agglomerative clustering, silhouette score |
| **NumPy** | Grid clustering and the Barnes-Hut quadtree |
| **`requests` / `urllib`** | HeyWhatsThat.com horizon API client (`script.py`) |
| **`concurrent.futures`** | Threaded batch/cluster processing (up to 4 workers) |
| **BSC5 catalogue** (`bsc5.dat`) | Bright Star Catalogue used for declination → star matching |

---

## Prerequisites

Before installing the plugin, make sure you have:

- **QGIS 3.18 or newer** (bundles a compatible Python 3.8+ and `requests`).
- **Python packages** (install into the QGIS Python environment):
  - `numpy` — required for the **Grid** and **Barnes-Hut** clustering methods.
  - `scikit-learn` — required for **DBSCAN**, **K-Means**, **Agglomerative**, and
    the Barnes-Hut silhouette quality gate.
- **An internet connection** — required for the HeyWhatsThat horizon source and
  for downloading the Google base map (both optional if you use SRTM offline).

**Optional, only if you use the offline SRTM horizon pipeline:**

- A folder of **SRTM DEM tiles** covering your study area. (These can be downloaded online, for example at https://srtm.csi.cgiar.org/srtmdata/ -> Recommendation: 5×5 tiles, The pipeline only needs a ~3°×3° window around each observer, so a 5°×5° tile already over-covers it. A 30°×30° tile is unnecessarily large to store/manage and offers no accuracy benefit here.)
- A **C++ compiler with OpenMP support** (e.g. `g++`, or MSVC / MinGW on
  Windows). The horizon calculator is distributed as **source only**
  (`srtm_horizon/calculate_horizon_topography_new.cpp`) and **must be compiled**
  into a `horizon_calc` executable before the SRTM pipeline can run — see
  step 4 of [Installation](#installation). This is not needed if you only use the
  online HeyWhatsThat horizon source.

To install the Python dependencies from the **OSGeo4W / QGIS Python** shell:

```bash
python -m pip install numpy scikit-learn
```

---

## Installation

1. Copy the plugin folder into your QGIS plugins directory:
   - Windows: `%APPDATA%/QGIS/QGIS3/profiles/default/python/plugins`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`
2. Restart QGIS, then enable **ArchaeoAstroInsight** in
   *Plugins → Manage and Install Plugins*.
3. Requires **QGIS 3.18+**. Optional Python dependencies for some clustering
   methods: `scikit-learn`, `numpy` (numpy is required for Grid and Barnes-Hut).
4. **(Only for the offline SRTM horizon pipeline) Compile the C++ horizon calculator. The executable is not distributed in the repository, so you must build it once from source and place the result in the `srtm_horizon/` folder:

```bash
# from inside the plugin's srtm_horizon/ folder

# Linux / macOS:
g++ -fopenmp -O2 calculate_horizon_topography_new.cpp -o horizon_calc

# Windows (MinGW):
g++ -fopenmp -O2 calculate_horizon_topography_new.cpp -o horizon_calc.exe

# Windows (MSVC, from a Developer Command Prompt):
cl /openmp:experimental /O2 calculate_horizon_topography_new.cpp /Fe:horizon_calc.exe

```

The plugin looks for `horizon_calc` (Linux/macOS) or `horizon_calc.exe` (Windows) in `srtm_horizon/`. If you only use the online HeyWhatsThat horizon source, you can skip this step.

---

## Configuration

On first use, open **A2i settings** and set:

- **Results path** — where output CSVs are written.
- **Python path** — (optional) a standalone Python interpreter used to run the
  horizon script in a subprocess without opening a console window. Leave empty
  to use QGIS's own Python.
- **Map download / type** — optionally load a Google base map (Satellite,
  Roadmap, Terrain, Hybrid).
- **Line width** and **script sleep**.
- **SRTM path** — folder of SRTM DEM tiles. If set, the offline SRTM horizon
  pipeline is used; otherwise HeyWhatsThat is used.

Settings are persisted in `config.txt`.

---

## Usage

### Quick Start

1. Open QGIS and make sure the **ArchaeoAstroInsight** toolbar is visible.
2. Click **A2i settings** and set at least a **Results path** (where CSVs are
   written). Leave **SRTM path** empty to use the online HeyWhatsThat horizon.
3. Click **A2i compute land and sky orientation**, then click two points on the
   map to draw a bearing.
4. Wait for the horizon to be computed (HeyWhatsThat can take up to ~2 minutes).
   The result (azimuth, altitude, declination, matched stars) appears in the
   message bar and is offered for saving as a CSV.

For analysing many objects at once, use [Batch Mode & Clustering](#batch-mode--clustering).

### Toolbar Actions

| Action | Description |
|--------|-------------|
| A2i settings | Open the configuration dialog |
| A2i set location | Zoom the canvas to entered coordinates |
| A2i compute land and sky orientation | Single-bearing azimuth/horizon tool |
| A2i toggle batch mode | Enable/disable capturing many objects |
| A2i run clustering | Cluster captured objects and process per cluster |
| A2i run batch (no clustering) | Process each captured object individually |
| A2i select clustering method | Choose the clustering algorithm |
| A2i toggle silhouette gate | Enable/disable the Barnes-Hut quality gate |
| A2i clear points | Remove all captured points |
| A2i import from CSV | Import objects (point pairs) from a CSV file |
| A2i run experiment (10x) | Repeat the selected mode 10 times, auto-save CSVs |

### Single Bearing Workflow

1. Click **A2i compute land and sky orientation**.
2. Click two points on the map to define a bearing.
3. The plugin computes azimuth, samples the horizon altitude, derives the
   declination, and matches stars from BSC5.
4. Results are saved to a CSV in your configured results path.

### Batch Mode & Clustering

1. Click **A2i toggle batch mode** (message bar confirms "Batch mode enabled").
2. Click **twice** per object to capture it:
   - First click = first point, second click = second point (a line is drawn,
     red markers appear at both points).
   - Console prints `Object captured. Total objects: X`.
3. Repeat for every object. Objects within ~100 m are clustered together by
   default.
4. Click **A2i run clustering**. A progress dialog appears while the plugin:
   - groups objects into clusters,
   - computes one horizon profile per cluster (using the cluster centroid),
   - computes declination per object using its own azimuth and the shared
     horizon,
   - creates `Cluster_0`, `Cluster_1`, … visualization layers (green polygons +
     centroid markers),
   - writes a CSV including per-cluster and total processing times.

To process every object on its own instead, use **A2i run batch (no clustering)**.

### Understanding the Output

All three modes (single, batch, clustering) write a CSV with the **same column
layout**, so results are directly comparable:

| Column | Meaning |
|--------|---------|
| `object_id` | Index of the object within the run |
| `cluster_id` | Cluster the object belongs to (empty in non-clustering modes) |
| `latitude`, `longitude` | Object location (observer point), EPSG:4326 |
| `centroid_lat`, `centroid_lon` | Cluster centroid used for the shared horizon (clustering only) |
| `azimuth` | Bearing direction, degrees (0–360) |
| `altitude` | Horizon altitude at that azimuth, degrees |
| `declination` | Derived celestial declination, degrees |
| `stars` | Matched BSC5 stars / Sun–Moon events (e.g. solstices, lunar standstills) |
| `processing_time` | Time for this object/cluster, seconds |
| `total_processing_time` | Total time for the whole run, seconds |
| `comments` | Free-text note (e.g. `Cluster 0, object 3`) |

Star matching uses a **±0.5° declination tolerance** against stars of magnitude
≤ 2; declinations are also checked against solstice and lunar-standstill values.

### Troubleshooting

- **"Horizon data failed for all objects/clusters"** — with HeyWhatsThat, the
  panorama may still be generating (it can take up to ~2 minutes) or the service
  may be temporarily down; try again. With SRTM, your tiles likely don't cover
  the area — check the Python Console for the exact coordinates that failed.
- **A console window flashes on each computation** — set a standalone **Python
  path** in *A2i settings* so the horizon script runs in a hidden subprocess.
- **Clustering fails with an import error** — install the required packages
  (`numpy`, `scikit-learn`) into the QGIS Python environment (see
  [Prerequisites](#prerequisites)).
- **"Compiled horizon calculator not found"** — rebuild `horizon_calc` from the
  C++ source and place it in `srtm_horizon/` (see
  [SRTM Horizon Pipeline](#srtm-horizon-pipeline)).
- **Tip:** open *Plugins → Python Console* to see detailed progress and error
  messages for every run.


## Clustering Methods

All clustering algorithms live in `clustering/` and share a common interface,
so they can be swapped without touching the rest of the plugin.

### Available Methods

| Key | Class | Description | Dependencies |
|-----|-------|-------------|--------------|
| `dbscan` | `DBSCANClustering` | Density-Based Spatial Clustering | scikit-learn |
| `kmeans` | `KMeansClustering` | K-Means | scikit-learn |
| `aglomerative` | `AglomerativeClustering` | Agglomerative (hierarchical) | scikit-learn |
| `grid` | `GridClustering` | Grid-based spatial binning | numpy |
| `barnes_hut` | `BarnesHutClustering` | Adaptive quadtree clustering with optional topographic check + silhouette gate | numpy, scikit-learn (optional) |

Methods are registered in `clustering/__init__.py` via `AVAILABLE_METHODS`.

### Interface Specification

Every method:

1. inherits from `BaseClusteringMethod` (`base_clustering.py`),
2. sets `self.name` and `self.description` in `__init__()`,
3. implements `cluster(object_centroids, distance_threshold=100.0)` returning a
   list of integer labels.

**Input** — `object_centroids` is a list of tuples
`(lat, lon, obj_points, obj_transformed, azimuth_or_none)`.

**Output** — a list of integers (one per object). Objects in the same cluster
share a label; labels are consecutive from 0 (e.g. `[0, 0, 0, 1, 1]`).

**Distance threshold** — metres, converted to degrees via
`threshold_deg = distance_threshold / 111000.0` (1° latitude ≈ 111 km). This
approximation is used consistently across all methods.

#### Adding a New Method

1. Create `my_method_clustering.py` in `clustering/`.
2. Inherit from `BaseClusteringMethod` and implement `cluster()`.
3. Register it in `clustering/__init__.py`:

```python
from .my_method_clustering import MyMethodClustering

AVAILABLE_METHODS = {
    # ... existing methods ...
    'my_method': MyMethodClustering,
}
```

### Barnes-Hut Clustering

An adaptation of the **Barnes-Hut** algorithm (originally for N-body
simulations) to spatial clustering. A quadtree decides which groups of objects
can be treated as a single cluster based on spatial proximity and (optionally)
topographic similarity. A **silhouette quality gate** then validates the result;
if the clustering is fragmented, a **proximity merge** recombines nearby
clusters — without leaving the Barnes-Hut framework.

**Algorithm steps:**

1. **Sample elevations** — scan the project for a single-band DEM raster; sample
   each object's elevation. No DEM ⇒ elevations = 0 and the topographic check is
   disabled.
2. **Create Tomb objects** — wrap each centroid as `(id, lat, lon, elevation)`.
3. **Build quadtree** — recursively subdivide space into NW/NE/SW/SE until each
   leaf holds ≤ 1 object.
4. **Bottom-up statistics** — each node computes centroid, elevation range
   (`min_z`, `max_z`) and count.
5. **Top-down labelling** — at each node: if leaf → unique label; else if
   `node.size ≤ threshold_deg` **and** `max_z − min_z < epsilon` → one label for
   the whole subtree; otherwise recurse into children.
6. **Quality gate (optional)** — when K ≥ 2 and N > 2, compute a single
   `silhouette_score` against an **adaptive threshold** (base 0.35, minus a
   penalty for large N, plus a bonus for large area, clamped to [0.15, 0.6]). If
   it fails, run the **proximity merge**: iteratively merge the closest pair of
   cluster centroids within `threshold_deg` until none qualify.

**Parameters:**

- `distance_threshold` (m) — proximity for clustering (default 100 m).
- `epsilon` (m) — max elevation range per cluster (default 20 m; `inf` disables
  the check, set automatically when no DEM is loaded).
- `theta` — the original Barnes-Hut `s/d` ratio is replaced here by a direct
  size threshold (`node.size ≤ threshold_deg`), since clustering has no external
  target point.

**Complexity:** O(N log N) typical; O(N²) worst case when the silhouette gate
runs.

For per-cluster downstream processing, `core.py` groups objects by label,
computes one horizon profile per cluster (from its mean centroid), then computes
declination per object using its own azimuth and the shared horizon, and writes
everything to CSV with per-cluster and total timings.

---

## CSV Import Format

The **A2i import from CSV** action imports objects (each defined by two points)
instead of clicking manually.

### Columns

**Required** (name variations accepted):

| Purpose | Accepted names |
|---------|----------------|
| Latitude 1 | `lat1`, `latitude1`, `lat_1` |
| Longitude 1 | `lon1`, `longitude1`, `lon_1`, `lng1` |
| Latitude 2 | `lat2`, `latitude2`, `lat_2` |
| Longitude 2 | `lon2`, `longitude2`, `lon_2`, `lng2` |

**Optional:**

| Purpose | Accepted names |
|---------|----------------|
| Azimuth | `azimuth`, `az`, `bearing` |

- Coordinates must be **EPSG:4326 (WGS84)** decimal degrees
  (lat −90…+90, lon −180…+180).
- If `azimuth` is provided it is used directly (normalised to 0–360); otherwise
  it is computed from the two points.
- If there is no header row, the first 4–5 columns are read positionally as
  `lat1, lon1, lat2, lon2, [azimuth]`.

### Example

```csv
lat1,lon1,lat2,lon2,azimuth
45.1234,-73.5678,45.1240,-73.5680,45.5
45.1300,-73.5700,45.1305,-73.5705,
45.1400,-73.5800,45.1405,-73.5805,47.8
```

Row 2's azimuth is computed from its points; rows 1 and 3 use the provided
values. Invalid rows are skipped (with a console message) and import continues.
Imported objects can be mixed with manually captured ones before clustering.

---

## SRTM Horizon Pipeline

When an SRTM folder is configured, the horizon is computed offline by
`srtm_horizon/`:

1. `convert_srtm_to_xyz.py` — extract lon/lat/elevation from SRTM raster tiles.
2. `calculate_horizon_topography_new.cpp` — compute azimuth/dip/distance
   (C++ with OpenMP). The compiled executable is **not** shipped in the
   repository; build `horizon_calc` (or `horizon_calc.exe` on Windows) from the
   `.cpp` source and place it in `srtm_horizon/` — see step 4 of
   [Installation](#installation).
3. `aggregate_horizon.py` — aggregate the C++ output into a horizon profile in
   the same shape the rest of the plugin expects from HeyWhatsThat.

`srtm_pipeline.py` ties these together via `compute_srtm_horizon()`.

---


## Project Structure

```
a2i/
  __init__.py            # QGIS entry point (classFactory)
  a2i.py                 # Main plugin: toolbar, menu, actions
  core.py                # Core engine: DeclinationTool, batch, CSV, clustering glue
  script.py              # HeyWhatsThat horizon computation
  utility.py             # Declination math + BSC5 lookup
  dialog.py / dialog.ui  # Settings dialog
  save_data.py / save_data.ui  # Save-results dialog
  resources.py / resources.qrc # Compiled Qt resources (icons)
  config.txt             # Runtime configuration
  metadata.txt           # QGIS plugin metadata
  bsc5.dat               # Bright Star Catalogue (BSC5)
  icon.png / icons/      # Plugin and toolbar icons
  clustering/            # Clustering algorithms (see above)
  srtm_horizon/          # Offline SRTM horizon pipeline
```

---

## Attribution & Contributions

This plugin is a derivative work of the original **ArchaeoAstroInsight (A2i)**
QGIS plugin by **Marc Frincu and R. Ionescu**, generated with the QGIS Plugin
Builder and licensed under the **GNU GPL v2 (or later)**. The original copyright
headers are preserved in the inherited source files as required by the license.

**Inherited from the original plugin (then modified):** the base plugin
scaffold — `a2i.py`, `dialog.py`, `save_data.py`, `utility.py`, `config.txt`,
`metadata.txt`, `resources.qrc`.

**Added for this thesis (original contributions):**

- The complete **`clustering/`** package — DBSCAN, K-Means, Agglomerative, Grid,
  and the custom **Barnes-Hut** clustering with adaptive silhouette quality gate
  and proximity merge, plus the common `BaseClusteringMethod` framework.
- The complete **`srtm_horizon/`** offline pipeline, including the
  `calculate_horizon_topography_new.cpp` horizon calculator.
- **`core.py`** — the processing engine: `DeclinationTool`, batch capture mode,
  per-cluster horizon/declination pipeline, CSV import, and the experiment
  runner.
- **`script.py`** — HeyWhatsThat horizon computation.
- New toolbar icons and the regenerated `resources.py`.
- All project documentation.

