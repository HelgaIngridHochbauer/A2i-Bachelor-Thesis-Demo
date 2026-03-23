"""
Grid-based clustering method using CLIQUE algorithm from pyclustering.

Grid clustering divides the space into grid cells and groups points
that fall into the same dense grid cells.
"""

from .base_clustering import BaseClusteringMethod

# Import QCoreApplication once for event processing
try:
    from qgis.PyQt.QtCore import QCoreApplication
except ImportError:
    QCoreApplication = None  # Fallback if Qt not available (shouldn't happen in QGIS plugin)


class GridClustering(BaseClusteringMethod):
    """Grid-based clustering using CLIQUE algorithm (requires pyclustering)"""
    
    def __init__(self):
        super().__init__()
        self.name = "Grid"
        self.description = "Grid-based clustering with CLIQUE (requires pyclustering)"
    
    def cluster(self, object_centroids, distance_threshold=100.0):
        """
        Cluster objects using grid-based CLIQUE algorithm.
        
        Args:
            object_centroids: List of tuples, each containing:
                - lat (float): Latitude of object centroid
                - lon (float): Longitude of object centroid
                - obj_points: Original map points (QgsPointXY objects)
                - obj_transformed: Transformed points (QgsPointXY objects in EPSG:4326)
                - azimuth_or_none: Optional azimuth value (float or None)
            distance_threshold: Distance threshold in meters (default: 100m)
        
        Returns:
            labels: List of integers, one per object, indicating cluster membership.
                   Objects in the same cluster have the same label.
                   Labels should start from 0 and be consecutive.
        
        Example:
            If you have 5 objects that form 2 clusters:
            - Objects 0, 1, 2 are in cluster 0
            - Objects 3, 4 are in cluster 1
            Then return: [0, 0, 0, 1, 1]
        """
        n = len(object_centroids)
        if n == 0:
            return []
        if n == 1:
            return [0]
        
        # Convert meters to approximate degrees
        # 1 degree ≈ 111,000 meters at equator
        # Validate input
        if distance_threshold <= 0:
            raise ValueError(f"distance_threshold must be positive, got {distance_threshold}")
        eps_degrees = distance_threshold / 111000.0
        
        try:
            from pyclustering.cluster.clique import clique
            import numpy as np
        except ImportError:
            raise ImportError("pyclustering is required for Grid clustering. Please install pyclustering or use another method.")
        
        # Prepare data for clustering (lat, lon only)
        coords = np.array([(c[0], c[1]) for c in object_centroids])
        
        print(f"Grid: Clustering {n} objects with threshold: {eps_degrees:.6f} degrees (~{distance_threshold} meters)")
        
        # Process events before potentially long-running clustering operation
        if QCoreApplication:
            QCoreApplication.processEvents()
        
        # Calculate grid intervals based on data range and distance threshold
        # CLIQUE divides each dimension into 'intervals' grid cells
        # We want grid cells roughly the size of our distance threshold
        lat_range = coords[:, 0].max() - coords[:, 0].min()
        lon_range = coords[:, 1].max() - coords[:, 1].min()
        
        # Calculate intervals so each grid cell is approximately the size of distance_threshold
        # Use the smaller range to determine intervals (ensures cells aren't too elongated)
        min_range = min(lat_range, lon_range) if min(lat_range, lon_range) > 0 else eps_degrees
        
        # Number of intervals should divide the range into cells of size ~eps_degrees
        # But ensure we have at least 3 intervals and at most 20 for performance
        # Protect against division by zero
        if eps_degrees <= 0:
            intervals = 5  # Fallback default
        elif min_range > eps_degrees:
            intervals = max(3, min(20, int(min_range / eps_degrees)))
        else:
            intervals = 5  # Default when range is smaller than threshold
        
        # Initialize CLIQUE
        # CLIQUE constructor signature: clique(data, amount_intervals, density_threshold)
        # density_threshold: minimum number of points per dense cell (set to 1)
        clique_instance = clique(coords.tolist(), intervals, 1)
        clique_instance.process()
        
        # Process events after clustering computation
        if QCoreApplication:
            QCoreApplication.processEvents()
        
        # Get clusters and noise points
        clusters = clique_instance.get_clusters()
        noise = clique_instance.get_noise()
        
        # Convert to label format
        labels = [-1] * n
        for cluster_id, cluster_indices in enumerate(clusters):
            for idx in cluster_indices:
                labels[idx] = cluster_id
        
        # Handle noise points (points not in any cluster)
        # Assign each noise point to its own cluster
        max_cluster_id = len(clusters) - 1
        for noise_idx in noise:
            max_cluster_id += 1
            labels[noise_idx] = max_cluster_id
        
        # Ensure labels are consecutive starting from 0
        unique_labels = sorted(set(labels))
        label_map = {old_label: new_label for new_label, old_label in enumerate(unique_labels)}
        labels = [label_map[label] for label in labels]
        
        # Process events after label processing
        if QCoreApplication:
            QCoreApplication.processEvents()
        
        # Debug: count clusters
        unique_labels_count = len(set(labels))
        print(f"Grid clustering found {unique_labels_count} cluster(s)")
        
        return labels
