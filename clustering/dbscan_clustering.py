"""
DBSCAN clustering method using sklearn.

This clustering method uses DBSCAN from scikit-learn (imported as sklearn).
Requires scikit-learn package to be installed.
"""

from .base_clustering import BaseClusteringMethod

# Import QCoreApplication once for event processing
try:
    from qgis.PyQt.QtCore import QCoreApplication
except ImportError:
    QCoreApplication = None  # Fallback if Qt not available (shouldn't happen in QGIS plugin)


class DBSCANClustering(BaseClusteringMethod):
    """DBSCAN clustering using sklearn.cluster.DBSCAN"""
    
    def __init__(self):
        super().__init__()
        self.name = "DBSCAN"
        self.description = "Density-Based Spatial Clustering (requires sklearn)"
    
    def cluster(self, object_centroids, distance_threshold=100.0, **kwargs):
        """
        Cluster objects using DBSCAN algorithm.
        
        Args:
            object_centroids: List of (lat, lon, obj_points, obj_transformed) tuples
            distance_threshold: Distance threshold in meters (default 100m)
        
        Returns:
            List of cluster labels (integers)
        """
        # Convert meters to approximate degrees
        # 1 degree ≈ 111,000 meters at equator
        # Validate input
        if distance_threshold <= 0:
            raise ValueError(f"distance_threshold must be positive, got {distance_threshold}")
        eps_degrees = distance_threshold / 111000.0
        
        try:
            from sklearn.cluster import DBSCAN
            import numpy as np
        except ImportError:
            # If sklearn not available, raise error - caller should handle fallback
            raise ImportError("scikit-learn is required for DBSCAN clustering. Please install scikit-learn: pip install scikit-learn")
        
        # Prepare data for DBSCAN (lat, lon only)
        coords = np.array([(c[0], c[1]) for c in object_centroids])
        
        print(f"DBSCAN: Clustering {len(object_centroids)} objects with threshold: {eps_degrees:.6f} degrees (~{distance_threshold} meters)")
        
        # Process events before potentially long-running clustering operation
        if QCoreApplication:
            QCoreApplication.processEvents()
        
        # Perform DBSCAN clustering
        # min_samples=1 means each point can form its own cluster
        clustering = DBSCAN(eps=eps_degrees, min_samples=1).fit(coords)
        
        # Process events after clustering
        if QCoreApplication:
            QCoreApplication.processEvents()
        labels = clustering.labels_.tolist()
        
        # DBSCAN can return -1 for noise points, but with min_samples=1 this shouldn't happen
        # Convert any -1 labels to positive integers
        unique_label_set = set(labels)
        if -1 in unique_label_set:
            # Remap -1 to the next available label
            max_label = max(unique_label_set)
            labels = [max_label + 1 if l == -1 else l for l in labels]
        
        # Debug: count clusters
        unique_labels_count = len(set(labels))
        print(f"DBSCAN found {unique_labels_count} cluster(s)")
        
        return labels

