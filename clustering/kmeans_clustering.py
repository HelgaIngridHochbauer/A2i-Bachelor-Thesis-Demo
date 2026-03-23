"""
K-means clustering method using sklearn.

Note: K-means requires specifying the number of clusters, not a distance threshold.
This implementation estimates the number of clusters based on the distance threshold.
"""

from .base_clustering import BaseClusteringMethod

# Import QCoreApplication once for event processing
try:
    from qgis.PyQt.QtCore import QCoreApplication
except ImportError:
    QCoreApplication = None  # Fallback if Qt not available (shouldn't happen in QGIS plugin)


class KMeansClustering(BaseClusteringMethod):
    """K-means clustering using sklearn.cluster.KMeans"""
    
    def __init__(self):
        super().__init__()
        self.name = "K-means"
        self.description = "K-means clustering (requires sklearn)"
    
    def cluster(self, object_centroids, distance_threshold=100.0):
        """
        Cluster objects using K-means algorithm.
        
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
            from sklearn.cluster import KMeans
            import numpy as np
        except ImportError:
            raise ImportError("scikit-learn is required for K-means clustering. Please install scikit-learn: pip install scikit-learn")
        
        # Prepare data for K-means (lat, lon only)
        coords = np.array([(c[0], c[1]) for c in object_centroids])
        
        # Estimate number of clusters based on distance threshold
        # Calculate data range and estimate how many clusters fit
        lat_range = coords[:, 0].max() - coords[:, 0].min()
        lon_range = coords[:, 1].max() - coords[:, 1].min()
        avg_range = (lat_range + lon_range) / 2.0
        
        # Estimate clusters: divide range by threshold distance
        # But ensure at least 1 cluster and at most n clusters
        # Protect against division by zero (shouldn't happen with default threshold, but safer)
        if eps_degrees <= 0:
            estimated_clusters = max(1, n // 3)  # Fallback if threshold is invalid
        elif avg_range > eps_degrees:
            estimated_clusters = max(1, min(n, int(avg_range / eps_degrees)))
        else:
            estimated_clusters = max(1, n // 3)  # Default to roughly 1/3 of objects
        
        print(f"K-means: Clustering {n} objects with threshold: {eps_degrees:.6f} degrees (~{distance_threshold} meters), estimated {estimated_clusters} clusters")
        
        # Process events before potentially long-running clustering operation
        if QCoreApplication:
            QCoreApplication.processEvents()
        
        # Perform K-means clustering
        # K-means requires n_clusters parameter
        # Reduced n_init from 10 to 3 for faster execution
        clustering = KMeans(n_clusters=estimated_clusters, random_state=42, n_init=3).fit(coords)
        
        # Process events after clustering
        if QCoreApplication:
            QCoreApplication.processEvents()
        labels = clustering.labels_.tolist()
        
        # Debug: count clusters
        unique_labels = len(set(labels))
        print(f"K-means found {unique_labels} cluster(s)")
        
        return labels

