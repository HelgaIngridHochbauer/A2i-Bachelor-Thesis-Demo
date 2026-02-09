"""
Clustering methods for grouping archaeological objects by proximity.

All clustering methods must follow the same interface:
- Input: object_centroids (list of tuples: (lat, lon, obj_points, obj_transformed))
- Parameters: distance_threshold (float, in meters)
- Output: labels (list of integers, one per object, indicating cluster membership)
"""

from .base_clustering import BaseClusteringMethod
from .dbscan_clustering import DBSCANClustering
from .kmeans_clustering import KMeansClustering
from .aglomerative_clustering import AglomerativeClustering
from .grid_clustering import GridClustering

# Register all available clustering methods
AVAILABLE_METHODS = {
    'dbscan': DBSCANClustering,
    'kmeans': KMeansClustering,
    'aglomerative': AglomerativeClustering,
    'grid': GridClustering,
}

def get_clustering_method(method_name):
    """Get a clustering method by name."""
    if method_name not in AVAILABLE_METHODS:
        raise ValueError(f"Unknown clustering method: {method_name}. Available: {list(AVAILABLE_METHODS.keys())}")
    return AVAILABLE_METHODS[method_name]()

def list_methods():
    """List all available clustering methods."""
    return list(AVAILABLE_METHODS.keys())

