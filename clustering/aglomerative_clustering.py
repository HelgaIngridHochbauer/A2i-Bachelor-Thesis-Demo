"""
Agglomerative clustering method using sklearn.

Agglomerative (Hierarchical) clustering merges clusters based on distance threshold.
"""

from .base_clustering import BaseClusteringMethod

# Import QCoreApplication once for event processing
try:
    from qgis.PyQt.QtCore import QCoreApplication
except ImportError:
    QCoreApplication = None  # Fallback if Qt not available (shouldn't happen in QGIS plugin)


class AglomerativeClustering(BaseClusteringMethod):
    """Agglomerative clustering using sklearn.cluster.AgglomerativeClustering"""
    
    def __init__(self):
        super().__init__()
        self.name = "Agglomerative"
        self.description = "Agglomerative (Hierarchical) clustering (requires sklearn)"
    
    def cluster(self, object_centroids, distance_threshold=100.0):
        """
        Cluster objects using Agglomerative clustering algorithm.
        
        Args:
            object_centroids: List of tuples, each containing:
                - lat (float): Latitude of object centroid
                - lon (float): Longitude of object centroid
                - obj_points: Original map points (QgsPointXY objects)
                - obj_transformed: Transformed points (QgsPointXY objects in EPSG:4326)
                - azimuth_or_none: Optional azimuth value (float or None)
            distance_threshold: Distance threshold in meters (default 100m)
        
        Returns:
            List of cluster labels (integers)
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
            from sklearn.cluster import AgglomerativeClustering
            import numpy as np
        except ImportError:
            raise ImportError("scikit-learn is required for Agglomerative clustering. Please install scikit-learn: pip install scikit-learn")
        
        # Prepare data for Agglomerative clustering (lat, lon only)
        coords = np.array([(c[0], c[1]) for c in object_centroids])
        
        print(f"Agglomerative: Clustering {n} objects with threshold: {eps_degrees:.6f} degrees (~{distance_threshold} meters)")
        
        # Process events before potentially long-running clustering operation
        if QCoreApplication:
            QCoreApplication.processEvents()
        
        # Perform Agglomerative clustering
        # distance_threshold: linkage distance threshold above which clusters will not be merged
        # linkage='ward' doesn't work with distance_threshold, use 'complete' or 'average'
        # Note: For large datasets, consider using 'average' linkage which is faster than 'complete'
        clustering = AgglomerativeClustering(
            distance_threshold=eps_degrees,
            n_clusters=None,  # Let distance_threshold determine number of clusters
            linkage='average'  # Changed from 'complete' to 'average' for better performance
        ).fit(coords)
        
        # Process events after clustering
        if QCoreApplication:
            QCoreApplication.processEvents()
        labels = clustering.labels_.tolist()
        
        # Ensure labels start from 0 and are consecutive
        unique_labels = sorted(set(labels))
        label_map = {old_label: new_label for new_label, old_label in enumerate(unique_labels)}
        labels = [label_map[label] for label in labels]
        
        # Debug: count clusters
        unique_labels_count = len(set(labels))
        print(f"Agglomerative found {unique_labels_count} cluster(s)")
        
        return labels

