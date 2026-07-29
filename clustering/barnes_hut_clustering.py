"""
Barnes-Hut adapted clustering method for archaeoastronomical site analysis.

This is an adaptation of the Barnes-Hut algorithm (originally used for N-body
gravitational simulations) to spatial clustering with an optional topographic
check. Instead of computing forces, the algorithm decides which groups of
objects can be treated as a single cluster based on:

  1. Spatial proximity  — all objects in a quadtree node fit within the
     distance threshold (node size < threshold).
  2. Topographic similarity — the elevation range within the node is below
     a configurable epsilon (Z_max - Z_min < epsilon).

If a DEM raster layer is loaded in the QGIS project, elevation is sampled
automatically.  Otherwise the topographic check is skipped and clustering
is purely spatial.

Complexity: O(N log N) — significantly faster than pairwise O(N^2) methods
for large datasets spread across varied terrain.
"""

import numpy as np
from .base_clustering import BaseClusteringMethod

# QGIS imports for DEM raster sampling (optional — gracefully degrade)
try:
    from qgis.core import (
        QgsProject,
        QgsRasterLayer,
        QgsPointXY,
        QgsRaster,
    )
    from qgis.PyQt.QtCore import QCoreApplication
    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False
    QCoreApplication = None


#---------------------------------------------------------------------------
# Data structures
#--------------------------------------------------------------------------
class Tomb:
    """Represents a single archaeological object (tomb / megalithic structure)."""

    def __init__(self, id, lat, lon, elevation):
        self.id = id                       # Global index in object_centroids
        self.pos = np.array([lat, lon])    # Position vector (Lat/Lon)
        self.ele = elevation               # Z value (metres above sea level)


class Node:
    """A node in the quadtree — either a leaf holding <=1 tomb, or an
    internal node with four children (NW, NE, SW, SE)."""

    def __init__(self, center, size):
        self.center = center   # Centre of this quadrant (Lat/Lon)
        self.size = size       # Width of the quadrant (degrees)
        self.children = None   # 4 children nodes (NW, NE, SW, SE)
        self.tombs = []        # Tombs contained in this specific leaf node

        # Aggregate statistics (populated bottom-up)
        self.centroid = np.zeros(2)        # Geometric centroid
        self.min_z = float('inf')          # Lowest elevation in subtree
        self.max_z = float('-inf')         # Highest elevation in subtree
        self.count = 0                     # Number of tombs in subtree

    def is_leaf(self):
        return self.children is None

    def compute_statistics(self):
        """
        Bottom-Up Statistics.
        Recursively calculates the centroid and elevation range for this node
        based on its children or the tombs it holds.
        """
        # Base case: Leaf node with tombs
        if self.is_leaf():
            if not self.tombs:
                return

            positions = np.array([t.pos for t in self.tombs])
            elevations = np.array([t.ele for t in self.tombs])

            self.count = len(self.tombs)
            self.centroid = np.mean(positions, axis=0)
            self.min_z = np.min(elevations)
            self.max_z = np.max(elevations)

        # Recursive step: Internal node
        else:
            total_pos = np.zeros(2)
            z_min_list = []
            z_max_list = []

            for child in self.children:
                child.compute_statistics()  # Recurse down
                if child.count > 0:
                    self.count += child.count
                    total_pos += child.centroid * child.count  # Weighted sum
                    z_min_list.append(child.min_z)
                    z_max_list.append(child.max_z)

            if self.count > 0:
                self.centroid = total_pos / self.count
                self.min_z = min(z_min_list)
                self.max_z = max(z_max_list)


#---------------------------------------------------------------------------
# Quadtree construction
#--------------------------------------------------------------------------

def build_quadtree(tombs, center, size):
    """Recursively build the quadtree.  Subdivision stops when a node
    contains at most 1 tomb (bucket size = 1)."""
    node = Node(center, size)

    # Stop condition: leaf
    if len(tombs) <= 1:
        node.tombs = tombs
        return node

    # Split into 4 quadrants
    half_size = size / 2
    step = size / 4

    # Define centres for NW, NE, SW, SE
    offsets = [(-1, 1), (1, 1), (-1, -1), (1, -1)]
    children = []

    for dx, dy in offsets:
        child_center = node.center + np.array([dx * step, dy * step])

        # Filter tombs belonging to this quadrant
        child_tombs = [
            t for t in tombs
            if abs(t.pos[0] - child_center[0]) <= step
            and abs(t.pos[1] - child_center[1]) <= step
        ]

        children.append(build_quadtree(child_tombs, child_center, half_size))

    node.children = children
    return node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_tombs(node):
    """Recursively collect all Tomb objects under *node*."""
    if node.is_leaf():
        return list(node.tombs)
    tombs = []
    for child in node.children:
        tombs.extend(_collect_tombs(child))
    return tombs


# ---------------------------------------------------------------------------
# Clustering class
# ---------------------------------------------------------------------------

class BarnesHutClustering(BaseClusteringMethod):
    """Adaptive Barnes-Hut spatial clustering with optional topographic check.

    The algorithm builds a quadtree over the input objects, then traverses it
    top-down.  At each node it checks:

    1. **Spatial check** — is the node small enough that all objects are within
       ``distance_threshold`` of each other?  (``node.size < threshold_deg``)
    2. **Topographic check** — is the terrain flat enough?
       (``Z_max - Z_min < epsilon``)

    If both checks pass the entire node is assigned one cluster label.
    Otherwise the node is "opened" and its four children are examined
    recursively.  Leaf nodes (single objects) always receive their own label
    or share one if they are part of a valid parent cluster.
    """

    # Default topographic threshold in metres.  Clusters whose internal
    # elevation range exceeds this value are split further.
    DEFAULT_EPSILON = 20.0

    def __init__(self, use_silhouette=True):
        super().__init__()
        self.name = "Barnes-Hut"
        self.description = "Adaptive Barnes-Hut spatial clustering with optional topographic check"
        self.use_silhouette = use_silhouette

    # -----------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------

    def cluster(self, object_centroids, distance_threshold=100.0,
                use_silhouette=None):
        """
        Cluster objects using the adapted Barnes-Hut algorithm.

        Args:
            object_centroids: List of tuples, each containing:
                - lat (float): Latitude of object centroid
                - lon (float): Longitude of object centroid
                - obj_points: Original map points (QgsPointXY objects)
                - obj_transformed: Transformed points (EPSG:4326)
                - azimuth_or_none: Optional azimuth value
            distance_threshold: Distance threshold in metres (default 100 m)
            use_silhouette: Enable/disable the silhouette quality gate.
                If None (default), falls back to ``self.use_silhouette``.

        Returns:
            labels: List of integers, one per object, indicating cluster
                    membership.  Labels start from 0 and are consecutive.
        """
        n = len(object_centroids)
        if n == 0:
            return []
        if n == 1:
            return [0]

        # Validate input
        if distance_threshold <= 0:
            raise ValueError(
                f"distance_threshold must be positive, got {distance_threshold}"
            )

        # Convert metres → approximate degrees (1° ≈ 111 000 m at equator)
        threshold_deg = distance_threshold / 111000.0

        # Process events before potentially long operation
        if QCoreApplication:
            QCoreApplication.processEvents()

        # Sample elevations (DEM or zeros)
        elevations = self._sample_elevations(object_centroids)
        has_elevation = any(e != 0.0 for e in elevations)
        if has_elevation:
            print("Barnes-Hut: DEM raster detected — topographic check ACTIVE")
        else:
            print("Barnes-Hut: No DEM raster found — topographic check SKIPPED (purely spatial)")

        # Create Tomb objects
        tombs = []
        for idx, centroid in enumerate(object_centroids):
            lat, lon = centroid[0], centroid[1]
            tombs.append(Tomb(id=idx, lat=lat, lon=lon, elevation=elevations[idx]))

        # Build quadtree
        all_pos = np.array([t.pos for t in tombs])
        min_coords = np.min(all_pos, axis=0)
        max_coords = np.max(all_pos, axis=0)
        center = (min_coords + max_coords) / 2
        size = np.max(max_coords - min_coords) + 0.01  # small padding

        root = build_quadtree(tombs, center, size)

        # Compute bottom-up statistics
        root.compute_statistics()

        # Process events after tree construction
        if QCoreApplication:
            QCoreApplication.processEvents()

        # Top-down traversal → assign cluster labels
        # epsilon is only meaningful when we have real elevation data;
        # otherwise set it to infinity so the check always passes.
        epsilon = self.DEFAULT_EPSILON if has_elevation else float('inf')

        labels = [-1] * n  # pre-allocate; one slot per object
        next_label = self._assign_labels(
            root, labels, current_label=0,
            size_threshold=threshold_deg, epsilon=epsilon,
        )

        # Process events after label assignment
        if QCoreApplication:
            QCoreApplication.processEvents()

        # Sanity: ensure every object received a label
        if any(l < 0 for l in labels):
            # Fallback: assign orphans to individual clusters
            for i in range(n):
                if labels[i] < 0:
                    labels[i] = next_label
                    next_label += 1

        # Make labels consecutive starting from 0
        unique = sorted(set(labels))
        remap = {old: new for new, old in enumerate(unique)}
        labels = [remap[l] for l in labels]

        unique_count = len(set(labels))
        print(f"Barnes-Hut: Initial traversal found {unique_count} cluster(s) from {n} objects")

        # Silhouette quality gate
        silhouette_enabled = use_silhouette if use_silhouette is not None else self.use_silhouette
        K = len(set(labels))
        if silhouette_enabled and K >= 2 and n > 2:
            coords = np.array([(c[0], c[1]) for c in object_centroids])
            spread_deg = float(np.max(np.ptp(coords, axis=0)))

            score, threshold, passed = self._evaluate_quality(
                coords, labels, n, spread_deg, threshold_deg)

            if not passed:
                labels = self._merge_nearby_clusters(coords, labels, threshold_deg)
        elif not silhouette_enabled:
            print("Barnes-Hut: Silhouette quality gate DISABLED")

        if QCoreApplication:
            QCoreApplication.processEvents()

        final_count = len(set(labels))
        print(f"Barnes-Hut clustering result: {final_count} cluster(s) from {n} objects")

        return labels

    # -----------------------------------------------------------------
    # Core traversal 
    # -----------------------------------------------------------------

    def _assign_labels(self, node, labels, current_label, size_threshold, epsilon):
        """Top-down traversal that assigns cluster labels.

        Returns the next available label integer so that sibling sub-trees
        do not collide.

        Decision logic (mirrors the original Barnes-Hut solve):

        * Leaf node — assign current label to each tomb in the leaf,
          then increment.
        * Node passes BOTH checks (small enough + flat enough) — assign
          the same label to ALL tombs under this node (cluster success).
        * Node fails either check — recurse into children
          (cluster failure, dig deeper).
        """
        if node.count == 0:
            return current_label

        # Check 1: Spatial — is the node small enough?
        is_small_enough = node.size <= size_threshold

        # Check 2: Topographic — is the terrain flat enough?
        elevation_diff = node.max_z - node.min_z
        is_flat_enough = elevation_diff < epsilon

        # CASE A: Leaf node → assign label (exact calculation equivalent)
        if node.is_leaf():
            for tomb in node.tombs:
                labels[tomb.id] = current_label
            return current_label + 1

        # CASE B: Both checks pass → cluster all tombs under this node
        if is_small_enough and is_flat_enough:
            for tomb in _collect_tombs(node):
                labels[tomb.id] = current_label
            count = node.count
            print(
                f"  Barnes-Hut: clustered {count} objects "
                f"(node size={node.size:.6f}°, Δz={elevation_diff:.1f}m)"
            )
            return current_label + 1

        # CASE C: Cluster invalid → recurse into children
        for child in node.children:
            if child.count > 0:
                current_label = self._assign_labels(
                    child, labels, current_label, size_threshold, epsilon,
                )
        return current_label

    # -----------------------------------------------------------------
    # Silhouette quality gate
    # -----------------------------------------------------------------

    def _evaluate_quality(self, coords, labels, n, spread_deg, threshold_deg):
        """Compute silhouette score once and compare to an adaptive threshold.

        The threshold adjusts for dataset size and spatial extent:
        - More objects  → slightly lower threshold (scores naturally decrease)
        - Larger area relative to threshold → higher threshold expected

        Returns (score, adaptive_threshold, passed).
        """
        try:
            from sklearn.metrics import silhouette_score
        except ImportError:
            print("Barnes-Hut: sklearn not available — skipping quality check")
            return (1.0, 0.0, True)

        K = len(set(labels))

        # Singletons produce an artificially perfect score of 1.0;
        # treat that as a guaranteed failure so the merge step runs.
        if K == n:
            print(f"Barnes-Hut: All {n} objects are singletons — quality check FAILED")
            return (0.0, 1.0, False)

        score = silhouette_score(coords, labels)

        base = 0.35
        n_penalty = min(0.1, 0.002 * n)
        area_factor = min(0.15, 0.1 * (spread_deg / threshold_deg)) if threshold_deg > 0 else 0.0
        adaptive_threshold = base - n_penalty + area_factor
        adaptive_threshold = max(0.15, min(0.6, adaptive_threshold))

        passed = bool(score >= adaptive_threshold)
        status = "PASSED" if passed else "BELOW threshold"
        print(f"Barnes-Hut: Silhouette score = {score:.4f}, "
              f"adaptive threshold = {adaptive_threshold:.4f} — {status}")

        return (score, adaptive_threshold, passed)

    # -----------------------------------------------------------------
    # Proximity-based cluster merge (tree-native fix)
    # -----------------------------------------------------------------

    @staticmethod
    def _merge_nearby_clusters(coords, labels, threshold_deg):
        """Merge clusters whose centroids are within threshold_deg of each other.

        This fixes two common quadtree artifacts:
        - Singletons that ended up in a different quadrant from their
          natural cluster.
        - Non-singleton sub-clusters where the quadtree boundary split a
          natural group in two.

        Iteratively merges the closest pair of centroids that are within
        threshold_deg until no more pairs qualify.

        Returns an updated label list (consecutive integers from 0).
        """
        labels = list(labels)
        n = len(labels)
        initial_k = len(set(labels))
        threshold_sq = threshold_deg ** 2

        merged = True
        while merged:
            merged = False
            cluster_ids = sorted(set(labels))
            if len(cluster_ids) <= 1:
                break

            centroids = {}
            for cid in cluster_ids:
                members = [i for i, l in enumerate(labels) if l == cid]
                centroids[cid] = coords[members].mean(axis=0)

            id_list = list(centroids.keys())
            c_arr = np.array([centroids[c] for c in id_list])

            best_dist = float('inf')
            merge_a, merge_b = -1, -1
            for ia in range(len(id_list)):
                for ib in range(ia + 1, len(id_list)):
                    d = float(np.sum((c_arr[ia] - c_arr[ib]) ** 2))
                    if d < best_dist:
                        best_dist = d
                        merge_a = id_list[ia]
                        merge_b = id_list[ib]

            if best_dist <= threshold_sq:
                for i in range(n):
                    if labels[i] == merge_b:
                        labels[i] = merge_a
                merged = True

        # Re-map to consecutive labels
        unique = sorted(set(labels))
        remap = {old: new for new, old in enumerate(unique)}
        labels = [remap[l] for l in labels]

        final_k = len(set(labels))
        if final_k < initial_k:
            print(f"Barnes-Hut: Merged nearby clusters {initial_k} -> {final_k}")

        return labels

    # -----------------------------------------------------------------
    # DEM elevation sampling
    # -----------------------------------------------------------------

    @staticmethod
    def _sample_elevations(object_centroids):
        """Try to sample elevation for each object from a DEM raster layer
        loaded in the current QGIS project.

        Returns a list of floats (one per object).  If no suitable DEM is
        found, returns all zeros.
        """
        n = len(object_centroids)
        elevations = [0.0] * n

        if not HAS_QGIS:
            return elevations

        # Look for a single-band raster layer (DEM candidate)
        dem_layer = None
        try:
            for layer in QgsProject.instance().mapLayers().values():
                if isinstance(layer, QgsRasterLayer) and layer.bandCount() == 1:
                    dem_layer = layer
                    print(f"Barnes-Hut: Using DEM raster layer '{layer.name()}'")
                    break
        except Exception as exc:
            print(f"Barnes-Hut: Could not scan for DEM layers: {exc}")
            return elevations

        if dem_layer is None:
            return elevations

        provider = dem_layer.dataProvider()
        for idx, centroid in enumerate(object_centroids):
            lat, lon = centroid[0], centroid[1]
            point = QgsPointXY(lon, lat)  # QgsPointXY takes (x=lon, y=lat)
            try:
                ident = provider.identify(point, QgsRaster.IdentifyFormatValue)
                if ident.isValid():
                    val = ident.results().get(1)  # Band 1
                    if val is not None:
                        elevations[idx] = float(val)
            except Exception as exc:
                print(f"Barnes-Hut: Could not sample elevation for object {idx}: {exc}")

        return elevations
