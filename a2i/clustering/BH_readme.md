# Barnes-Hut Adapted Clustering

## Overview

This is an adaptation of the **Barnes-Hut algorithm** (originally used for N-body gravitational simulations) to spatial clustering of archaeological sites. Instead of computing gravitational forces, the algorithm decides which groups of objects can be treated as a single cluster.

The implementation lives in `barnes_hut_clustering.py` (the original development file `Barnes-Hut-addapted.py` is kept for reference).

## How It Works

### 1. Build the Static Quadtree

The algorithm organizes the dataset (megalithic tombs / archaeological objects) into a spatial hierarchy.

- **Recursive Division**: Starting with a bounding box covering all objects, the code recursively subdivides the 2D space into four quadrants (NW, NE, SW, SE).
- **Stopping Condition**: Subdivision continues until each leaf node contains 0 or 1 objects.
- **Static Optimization**: Unlike physics simulations where particles move and the tree must be rebuilt every frame, the tree is built only once because the sites are static.

### 2. Aggregate Data (Bottom-Up)

Once the tree is built, statistical data is propagated from the leaves up to the root. Each internal node calculates:

- **Geometric Centroid**: The average latitude/longitude of all objects within that node.
- **Topographic Variance**: The minimum (`Z_min`) and maximum (`Z_max`) elevation within that subtree. This ensures a cluster does not group a valley tomb with a mountain-top tomb.

### 3. Traverse and Assign Labels (Top-Down)

The core logic traverses the tree top-down. At each node it makes a decision based on **two criteria**:

1. **Spatial Check**: Is `node.size <= size_threshold`? If the quadtree node is small enough, all objects inside are within the distance threshold of each other.
2. **Topographic Check**: Is `Z_max - Z_min < epsilon`? If the elevation range is below the threshold (default: 20 metres), the terrain is flat enough for the cluster to be valid.

### 4. Decision Logic (Three Cases)

Based on the checks, the code does one of three things:

| Case | Condition | Action |
|------|-----------|--------|
| **A. Leaf** | Node contains a single object | Assign it a unique cluster label |
| **B. Cluster Success** | Both spatial AND topographic checks pass | Assign the **same label** to ALL objects in this subtree |
| **C. Cluster Failure** | Either check fails | Recurse into the four children to attempt finer-grained clustering |

This mirrors the original Barnes-Hut three-case structure:
- Case A = "Exact Calculation" (leaf node)
- Case B = "Approximation" (valid cluster)
- Case C = "Dig Deeper" (invalid cluster, recurse)

### 5. Efficiency

By implementing this logic, the algorithm converts the problem from O(N^2) pairwise comparisons to **O(N log N)**. It acts as an adaptive filter: rapidly grouping objects in flat, dense areas while automatically preserving individual treatment for objects in complex, rugged landscapes.

## Key Parameters

### `distance_threshold` (metres -> degrees conversion)

The `distance_threshold` parameter (default: **100 metres**) controls how close objects need to be to form a cluster. Since latitude/longitude coordinates are in **degrees**, the threshold must be converted:

```
threshold_degrees = distance_threshold / 111000.0
```

**Why 111,000?** One degree of latitude is approximately 111 km (111,000 metres) on Earth's surface. So:

| Distance (metres) | Threshold (degrees) | Meaning |
|-------------------|--------------------|---------| 
| 50 m | ~0.00045 deg | Node must be < ~50m wide |
| 100 m | ~0.00090 deg | Node must be < ~100m wide |
| 200 m | ~0.00180 deg | Node must be < ~200m wide |
| 500 m | ~0.00450 deg | Node must be < ~500m wide |

**A quadtree node with `size = 0.0005 deg`** covers roughly a 55m x 55m area. Since 0.0005 < 0.0009 (our 100m threshold), all objects inside are within ~100m of each other and can be clustered.

**Important approximation**: This conversion assumes 1 degree = 111 km, which is exact at the equator. At higher latitudes, 1 degree of longitude covers less ground (e.g., ~78 km at latitude 45 deg). For clustering purposes within a regional study area, this approximation is acceptable. All other clustering methods in the plugin use the same approximation.

### `epsilon` (topographic threshold)

Default: **20 metres**. This is the maximum elevation difference (`Z_max - Z_min`) allowed within a cluster. If the elevation range within a quadtree node exceeds this value, the node is split further even if objects are spatially close.

- `epsilon = 20`: A 20m elevation range is tolerated (fairly strict).
- `epsilon = 50`: More relaxed; allows hilly terrain.
- `epsilon = inf`: Topographic check disabled (purely spatial clustering).

### `theta` (original Barnes-Hut parameter)

In the original N-body Barnes-Hut algorithm, `theta` controls the `s/d` ratio (node size / distance to target). In our clustering adaptation, this is replaced by a direct size threshold (`node.size <= threshold_degrees`), because clustering does not have an external "target point" — the question is whether objects are close to *each other*, not to some external reference.

## Elevation / DEM Integration

The topographic check requires elevation data for each object. Since the plugin's `object_centroids` only contain latitude/longitude, the algorithm automatically samples elevation from a **DEM (Digital Elevation Model) raster layer** loaded in the QGIS project:

1. At the start of `cluster()`, the code scans all layers in `QgsProject.instance().mapLayers()`.
2. If a **single-band raster layer** is found (typical for DEMs), it samples elevation at each object's coordinates using `dataProvider().identify()`.
3. If **no DEM is loaded**, all elevations default to 0 and the topographic check is automatically skipped (epsilon is set to infinity). The algorithm prints a message to the console so the user knows.

**To enable the topographic check**: Load a DEM raster layer into your QGIS project before running Barnes-Hut clustering. The algorithm will detect it automatically.

## Comparison with Original Code

The original Barnes-Hut code was a standalone script with mock testing functions (`run_heavy_script`, `mock_tombs`, `__main__` block). The adapted version:

| Original | Adapted |
|----------|---------|
| `Tomb` class with `.result` attribute | `Tomb` class (`.result` removed; labels stored in flat list) |
| `Node` class | Identical |
| `build_quadtree()` | Identical |
| `Node.compute_statistics()` | Identical |
| `solve_dataset()` with `target_point` | `_assign_labels()` with `size_threshold` |
| `run_heavy_script()` (mock) | Replaced by label assignment |
| `apply_to_all()` | Replaced by `_collect_tombs()` |
| Standalone `__main__` block | `cluster()` method returning labels list |

The three-case decision structure (Leaf / Cluster Success / Cluster Failure) is preserved exactly.

## Integration with the Plugin

Barnes-Hut follows the same `BaseClusteringMethod` interface as all other methods:

- **Input**: `object_centroids` list + `distance_threshold` in metres
- **Output**: List of integer labels (e.g., `[0, 0, 1, 1, 2]`)

After labels are returned, `core.py` handles the rest:
1. Groups objects by cluster label
2. Downloads one HeyWhatsThat horizon profile per cluster (using the cluster's mean centroid)
3. Computes declination for each individual object using its own azimuth + the shared horizon profile

## File Structure

```
clustering/
  barnes_hut_clustering.py    # The importable module (Python requires underscores, not hyphens)
  Barnes-Hut-addapted.py      # Original development file (kept for reference)
  BH_readme.md                # This file
  __init__.py                  # Registers 'barnes_hut' in AVAILABLE_METHODS
```

## Usage

Select "Barnes-Hut" from the clustering method dropdown in the plugin. Optionally load a DEM raster layer for topographic-aware clustering.
